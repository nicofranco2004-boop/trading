"""Rebuild global de FIFO post-import — hace que el ORDEN de carga no importe.

Problema que resuelve
─────────────────────
El persister (`persist_batch`) es incremental: procesa las txs de UN batch
contra el estado actual de la DB. El FIFO (con qué compra se matchea cada venta)
se calcula al momento de importar. NO hay re-cálculo global después.

Entonces, si el usuario importa su historial en tandas y FUERA de orden
cronológico — típico: "tengo 2025, después consigo 2024" — una venta de 2025 de
algo comprado en 2024 NO encuentra su compra (todavía no se cargó). El persister,
con su política "history-as-truth", crea un lote semilla al PRECIO DE VENTA →
P&L = 0 en esa operación. Cuando después se carga la compra de 2024, entra como
un lote ABIERTO fantasma que nunca se cierra. Resultado: tenencia inflada +
ganancia realizada subestimada.

Qué hace este módulo
────────────────────
Después de cada import, por cada (broker, activo) que el batch tocó, replaya
TODAS las compras/ventas importadas de ese (broker, activo) — de todos los
batches confirmados — en orden cronológico global, y reconstruye:
  • los lotes abiertos (`positions`)
  • las ventas (`operations` con op_type='Venta') con su P&L correcto

Es exactamente equivalente a "importar todo junto en el orden correcto", que es
el caso que ya sabemos que funciona bien.

Qué NO toca (a propósito)
─────────────────────────
  • Cash / saldos de broker: los proceeds de una venta y los depósitos son
    order-independent (qty×precio no depende del cost basis). El neto de cash es
    idéntico sin importar el orden → rebuild NO ajusta cash.
  • Depósitos / retiros / dividendos / intereses / FX: no dependen del FIFO.
  • monthly_entries: se arreglan solos llamando `_recalc_pnl_realized_from_ops`
    después (recalcula pnl_realized = SUM(operations.pnl_usd) desde la fuente
    autoritativa). El caller (import_confirm) ya lo hace.

Frontera de seguridad (CRÍTICO)
───────────────────────────────
El log de eventos reproducible y sin contaminar es `import_normalized_tx`. Las
operaciones MANUALES (botón Nueva posición / Vender) NO viven ahí — mutan
positions/operations directo. Un (broker, activo) con CUALQUIER posición o venta
manual (no vinculada a un import vía `import_op_links`) se SALTEA intacto: nunca
reconstruimos sobre data que no podemos reproducir. Peor caso = comportamiento
de hoy (sin corromper nada).

Revert
──────
Reconstruimos la doble vinculación que usa el revert (`_link`):
`import_normalized_tx.created_*_id` + filas en `import_op_links`. Antes de
recrear, limpiamos la vinculación vieja de los raw rows afectados.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .schema import OP_BUY, OP_SELL
from .persister import _link

log = logging.getLogger(__name__)

_EPS = 1e-9


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _norm_cur(c: Optional[str]) -> Optional[str]:
    u = (c or "").upper() or None
    return "USD" if u == "USDT" else u


def _replay_asset(events: List[Dict[str, Any]], broker_currency: str,
                   tc_blue: float) -> Dict[str, List[Dict[str, Any]]]:
    """Replaya los eventos BUY/SELL (ya ordenados cronológicamente, BUY antes
    que SELL el mismo día) de UN (broker, activo) y devuelve:
      {"operations": [...], "open_lots": [...]}

    Espeja `_persist_sell_fifo` / `_persist_buy` exactamente, pero EN MEMORIA y
    SIN efectos de cash. Cada dict de salida lleva su origen (batch_id,
    raw_row_id) para re-vincular; None en lotes semilla (igual que el persister,
    que no linkea las semillas)."""
    lots: List[Dict[str, Any]] = []   # lotes abiertos, FIFO desde el frente
    operations: List[Dict[str, Any]] = []

    for ev in events:
        op = ev["operation_type"]

        if op == OP_BUY:
            qty = _num(ev["quantity"])
            unit = _num(ev["unit_price"])
            invested = _num(ev["gross_amount"]) if ev["gross_amount"] is not None else unit * qty
            fees = _num(ev["fees"])
            lots.append({
                "qty": qty,
                "invested": invested,
                "buy_price": unit if unit > 0 else None,
                "commissions": fees,
                "entry_date": ev["date"],
                "currency": _norm_cur(ev["currency"]),
                "batch_id": ev["batch_id"],
                "raw_row_id": ev["raw_row_id"],
                "is_seed": False,
            })
            continue

        if op != OP_SELL:
            continue  # defensivo: solo BUY/SELL llegan acá

        # ── Venta FIFO (espejo de _persist_sell_fifo) ──────────────────────
        sell_currency = _norm_cur(ev["currency"]) or broker_currency
        if sell_currency not in ("ARS", "USD"):
            sell_currency = broker_currency
        currency = sell_currency

        exit_price = _num(ev["unit_price"])
        sell_commissions = _num(ev["fees"])
        qty_to_sell = _num(ev["quantity"])
        op_date = ev["date"]

        total_avail = sum(l["qty"] for l in lots)

        # Política history-as-truth: si se vende más de lo disponible, lote
        # semilla al precio de venta para el faltante → P&L = 0 sobre ese chunk.
        if qty_to_sell > total_avail + _EPS:
            missing = qty_to_sell - total_avail
            lots.append({
                "qty": missing,
                "invested": missing * exit_price,
                "buy_price": exit_price,
                "commissions": 0.0,
                "entry_date": op_date,
                "currency": _norm_cur(ev["currency"]),
                "batch_id": None,      # semilla sintética: sin origen → sin link
                "raw_row_id": None,
                "is_seed": True,
            })

        tc_venta = tc_blue if sell_currency == "ARS" else 1.0
        remaining = qty_to_sell

        for lot in lots:
            if remaining <= _EPS:
                break
            pos_qty = lot["qty"]
            take = min(remaining, pos_qty)
            if take <= 0:
                continue
            ratio = take / pos_qty if pos_qty > 0 else 0
            pos_buy_commissions = lot["commissions"] or 0
            base_invested = (lot["invested"] or 0) + pos_buy_commissions

            lot_currency = lot["currency"] or currency
            # Cross-currency: valuar el invested del lote en la moneda de la venta.
            if lot_currency != currency and tc_blue:
                if lot_currency == "USD" and currency == "ARS":
                    base_invested = base_invested * tc_blue
                elif lot_currency == "ARS" and currency == "USD":
                    base_invested = base_invested / tc_blue

            entry_invested = base_invested * ratio if base_invested else None
            chunk_commission = sell_commissions * (take / qty_to_sell) if qty_to_sell else 0

            if currency == "ARS":
                pnl_ars_chunk = exit_price * take - (entry_invested or 0) - chunk_commission
                pnl_usd = pnl_ars_chunk / tc_venta if tc_venta else 0
                invested_usd = (entry_invested or 0) / tc_venta if entry_invested and tc_venta else 0
            else:
                cost = entry_invested if entry_invested is not None else ((lot["buy_price"] or 0) * take)
                pnl_usd = (exit_price * take) - cost - chunk_commission
                invested_usd = cost

            pnl_pct = (pnl_usd / invested_usd * 100) if invested_usd else None

            operations.append({
                "date": op_date,
                "broker": ev["broker"],
                "asset": ev["asset_symbol"],
                "op_type": "Venta",
                "entry_price": lot["buy_price"],
                "exit_price": exit_price,
                "quantity": take,
                "pnl_usd": round(pnl_usd, 2),
                "pnl_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
                "entry_date": lot["entry_date"],
                "commissions": round(chunk_commission, 4),
                # origen = la VENTA (para revert / dedup de links)
                "batch_id": ev["batch_id"],
                "raw_row_id": ev["raw_row_id"],
            })

            # Consumir el lote
            if take >= pos_qty - _EPS:
                lot["qty"] = 0.0
            else:
                remaining_ratio = 1 - ratio
                lot["qty"] = pos_qty - take
                lot["invested"] = round((lot["invested"] or 0) * remaining_ratio, 6) if lot["invested"] is not None else None
                lot["commissions"] = round(pos_buy_commissions * remaining_ratio, 6)
            remaining -= take

        # limpiar lotes agotados
        lots = [l for l in lots if l["qty"] > _EPS]

    open_lots = [l for l in lots if l["qty"] > _EPS]
    return {"operations": operations, "open_lots": open_lots}


def _affected_assets(conn, uid: int, batch_id: str) -> List[Dict[str, str]]:
    """(broker, activo) con compras/ventas en el batch recién confirmado."""
    rows = conn.execute(
        """SELECT DISTINCT broker, asset_symbol
             FROM import_normalized_tx
            WHERE batch_id = ?
              AND operation_type IN (?, ?)
              AND asset_symbol IS NOT NULL
              AND asset_symbol != ''""",
        (batch_id, OP_BUY, OP_SELL),
    ).fetchall()
    return [{"broker": r["broker"], "asset": r["asset_symbol"]} for r in rows]


def _full_events(conn, uid: int, broker: str, asset: str) -> List[Dict[str, Any]]:
    """Todos los BUY/SELL confirmados de (broker, activo), orden cronológico
    determinístico (fecha asc; BUY antes que SELL el mismo día; id asc).

    INVARIANTE: import_normalized_tx = "lo que se aplicó". Las filas que el
    usuario marca para saltear (skip_row_indices) se BORRAN de esta tabla en
    import_confirm antes de llegar acá; si no, este replay las resucitaría."""
    rows = conn.execute(
        """SELECT n.id, n.batch_id, n.raw_row_id, n.date, n.broker, n.asset_symbol,
                  n.operation_type, n.quantity, n.unit_price, n.gross_amount,
                  n.fees, n.currency, n.created_position_id
             FROM import_normalized_tx n
             JOIN import_batches b ON b.id = n.batch_id
            WHERE b.user_id = ?
              AND b.status = 'confirmed'
              AND n.broker = ?
              AND n.asset_symbol = ?
              AND n.operation_type IN (?, ?)
            ORDER BY n.date ASC,
                     CASE n.operation_type WHEN ? THEN 0 ELSE 1 END ASC,
                     n.id ASC""",
        (uid, broker, asset, OP_BUY, OP_SELL, OP_BUY),
    ).fetchall()
    return [dict(r) for r in rows]


def _is_safe_to_rebuild(conn, uid: int, broker: str, asset: str) -> bool:
    """True si TODAS las positions (lotes abiertos) y ventas actuales de
    (broker, activo) fueron creadas por imports (vinculadas en import_op_links).
    Si hay cualquier fila manual / sin vincular (incluye lotes semilla huérfanos),
    devolvemos False → se saltea, nunca se corrompe data no reproducible."""
    cur_pos = [r["id"] for r in conn.execute(
        "SELECT id FROM positions WHERE user_id=? AND broker=? AND asset=? AND is_cash=0",
        (uid, broker, asset),
    ).fetchall()]
    cur_sells = [r["id"] for r in conn.execute(
        "SELECT id FROM operations WHERE user_id=? AND broker=? AND asset=? AND op_type='Venta'",
        (uid, broker, asset),
    ).fetchall()]

    linked_pos = {r["position_id"] for r in conn.execute(
        """SELECT DISTINCT l.position_id
             FROM import_op_links l JOIN import_batches b ON b.id = l.batch_id
            WHERE b.user_id=? AND l.position_id IS NOT NULL""",
        (uid,),
    ).fetchall()}
    linked_ops = {r["operation_id"] for r in conn.execute(
        """SELECT DISTINCT l.operation_id
             FROM import_op_links l JOIN import_batches b ON b.id = l.batch_id
            WHERE b.user_id=? AND l.operation_id IS NOT NULL""",
        (uid,),
    ).fetchall()}

    if any(pid not in linked_pos for pid in cur_pos):
        return False
    if any(oid not in linked_ops for oid in cur_sells):
        return False
    return True


def _clear_old_state(conn, uid: int, broker: str, asset: str,
                     events: List[Dict[str, Any]]) -> Dict[tuple, Optional[int]]:
    """Borra los lotes abiertos + ventas import-creadas de (broker, activo) y
    limpia su vinculación de revert, dejando todo listo para re-crear.

    Devuelve {(batch_id, raw_row_id): old_created_position_id} para las filas
    BUY — lo usamos para dejar un "tombstone" en las compras que el rebuild
    consume del todo (así el revert seguro sigue bloqueándose: la posición ya
    no existe = fue vendida)."""
    old_buy_pos: Dict[tuple, Optional[int]] = {}
    for ev in events:
        if ev["operation_type"] == OP_BUY:
            old_buy_pos[(ev["batch_id"], ev["raw_row_id"])] = ev.get("created_position_id")

    conn.execute(
        "DELETE FROM positions WHERE user_id=? AND broker=? AND asset=? AND is_cash=0",
        (uid, broker, asset),
    )
    conn.execute(
        "DELETE FROM operations WHERE user_id=? AND broker=? AND asset=? AND op_type='Venta'",
        (uid, broker, asset),
    )
    # Resetear la vinculación de cada raw row afectado (las vamos a re-linkear).
    for ev in events:
        conn.execute(
            """UPDATE import_normalized_tx
                  SET created_position_id = NULL, created_operation_id = NULL
                WHERE id = ?""",
            (ev["id"],),
        )
        conn.execute(
            "DELETE FROM import_op_links WHERE batch_id=? AND raw_row_id=?",
            (ev["batch_id"], ev["raw_row_id"]),
        )
    return old_buy_pos


def _write_buy_tombstones(conn, consumed_keys: set,
                          old_buy_pos: Dict[tuple, Optional[int]]) -> None:
    """Para cada compra que el rebuild consumió por completo (no quedó lote
    abierto), restaura un link apuntando a su position_id viejo (ya borrado;
    AUTOINCREMENT no lo reusa). Así el pre-check del revert seguro lo detecta
    como 'posición ya no existe → vendida' y bloquea, en vez de revertir y
    devolver cash de una compra que en realidad se cerró."""
    for key in consumed_keys:
        old_pid = old_buy_pos.get(key)
        if not old_pid:
            continue
        batch_id, raw_row_id = key
        conn.execute(
            """UPDATE import_normalized_tx SET created_position_id = ?
                WHERE batch_id=? AND raw_row_id=?""",
            (old_pid, batch_id, raw_row_id),
        )
        conn.execute(
            "INSERT INTO import_op_links (batch_id, raw_row_id, position_id) VALUES (?,?,?)",
            (batch_id, raw_row_id, old_pid),
        )


def _write_rebuilt(conn, uid: int, replay: Dict[str, List[Dict[str, Any]]]) -> None:
    """Inserta los lotes abiertos + ventas reconstruidos y re-vincula para revert."""
    for lot in replay["open_lots"]:
        # broker/asset vienen del grupo (_broker/_asset), no del lote individual.
        cur = conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price,
                   quantity, invested, tc_compra, price_override, notes, entry_date,
                   commissions, currency)
               VALUES (?,?,?,0,?,?,?,?,?,?,?,?,?)""",
            (uid, lot["_broker"], lot["_asset"], lot["buy_price"], lot["qty"],
             lot["invested"], None, None, None, lot["entry_date"],
             lot["commissions"], lot["currency"]),
        )
        position_id = cur.lastrowid
        # Lotes semilla no tienen origen → no se linkean (igual que el persister).
        if lot.get("batch_id") and lot.get("raw_row_id"):
            _link(conn, lot["batch_id"], lot["raw_row_id"], position_id=position_id)

    for o in replay["operations"]:
        cur = conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type,
                   entry_price, exit_price, quantity, pnl_usd, pnl_pct, entry_date,
                   commissions)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, o["date"], o["broker"], o["asset"], o["op_type"],
             o["entry_price"], o["exit_price"], o["quantity"], o["pnl_usd"],
             o["pnl_pct"], o["entry_date"], o["commissions"]),
        )
        op_id = cur.lastrowid
        if o.get("batch_id") and o.get("raw_row_id"):
            _link(conn, o["batch_id"], o["raw_row_id"], operation_id=op_id)


def _ensure_monthly_rows(conn, uid: int, operations: List[Dict[str, Any]]) -> None:
    """Garantiza que exista la fila de monthly_entries (broker + 'global') del
    mes de cada venta reconstruida.

    Por qué: `_recalc_pnl_realized_from_ops` recalcula pnl_realized SOLO para
    los (broker, año, mes) que YA tienen fila en monthly_entries. Si las ventas
    se importaron primero fuera de orden, su P&L era 0 (lote semilla) y el
    recalc borró esas filas "todo en 0". Tras reconstruir el P&L correcto, sin
    esta garantía no habría fila donde sumarlo y el monthly quedaría en 0.
    INSERT OR IGNORE crea la fila con ceros; el recalc posterior la rellena."""
    seen = set()
    for o in operations:
        d = o.get("date") or ""
        if len(d) < 7:
            continue
        try:
            y, m = int(d[:4]), int(d[5:7])
        except ValueError:
            continue
        for broker in (o["broker"], "global"):
            key = (broker, y, m)
            if key in seen:
                continue
            seen.add(key)
            conn.execute(
                """INSERT OR IGNORE INTO monthly_entries (user_id, year, month, broker)
                   VALUES (?,?,?,?)""",
                (uid, y, m, broker),
            )


def rebuild_fifo_after_import(conn, uid: int, batch_id: str, *,
                              tc_blue: float = 1415.0) -> Dict[str, Any]:
    """Reconstruye el FIFO (lotes abiertos + ventas) de cada (broker, activo) que
    el batch tocó, replayando todo su historial importado en orden cronológico.

    Idempotente: si los datos ya estaban en orden, reproduce el mismo estado.
    Seguro: saltea (broker, activo) con data manual no reproducible.

    Devuelve {"rebuilt": [...], "skipped_manual": [...], "skipped_no_sell": [...]}.
    El caller debe correr `_recalc_pnl_realized_from_ops` después para sincronizar
    monthly_entries desde las operations corregidas.
    """
    rebuilt: List[Dict[str, Any]] = []
    skipped_manual: List[Dict[str, Any]] = []
    skipped_no_sell: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for i, ba in enumerate(_affected_assets(conn, uid, batch_id)):
        broker, asset = ba["broker"], ba["asset"]
        events = _full_events(conn, uid, broker, asset)
        if not events:
            continue
        # Sin ventas → el orden FIFO no afecta nada (solo compras abiertas).
        if not any(e["operation_type"] == OP_SELL for e in events):
            skipped_no_sell.append(ba)
            continue
        # Frontera de seguridad: data manual no reproducible → no tocar.
        if not _is_safe_to_rebuild(conn, uid, broker, asset):
            skipped_manual.append(ba)
            log.info("rebuild_fifo: skip %s/%s (ops manuales no vinculadas)", broker, asset)
            continue

        # Moneda del broker (fallback para ventas sin moneda explícita).
        br = conn.execute(
            "SELECT currency FROM brokers WHERE name=? AND user_id=?", (broker, uid),
        ).fetchone()
        broker_currency = (br["currency"] if br else "USDT")
        if broker_currency == "USDT":
            broker_currency = "USD"
        if broker_currency not in ("ARS", "USD"):
            broker_currency = "USD"

        replay = _replay_asset(events, broker_currency, tc_blue)
        # Inyectar broker/asset del grupo en cada lote abierto para el insert.
        for lot in replay["open_lots"]:
            lot["_broker"] = broker
            lot["_asset"] = asset

        # Atomicidad por activo: SAVEPOINT. Si la reconstrucción de UN activo
        # falla a mitad (borró las ops viejas pero no escribió las nuevas), se
        # revierte SOLO ese activo a su estado previo y el resto del rebuild
        # sigue. Nunca dejamos un activo a medias.
        sp = f"rebuild_{i}"
        conn.execute(f"SAVEPOINT {sp}")
        try:
            old_buy_pos = _clear_old_state(conn, uid, broker, asset, events)
            _write_rebuilt(conn, uid, replay)
            _ensure_monthly_rows(conn, uid, replay["operations"])

            # Tombstones: compras consumidas del todo (sin lote abierto
            # sobreviviente) → dejar link a la posición vieja para que el revert
            # seguro siga bloqueando ("ya se vendió"). Las compras con lote
            # sobreviviente ya quedaron re-linkeadas por _write_rebuilt; si
            # quedaron con menos qty que la original, el pre-check de revert las
            # bloquea por el quantity-check.
            surviving_buys = {
                (l["batch_id"], l["raw_row_id"])
                for l in replay["open_lots"]
                if l.get("batch_id") and l.get("raw_row_id")
            }
            consumed = set(old_buy_pos.keys()) - surviving_buys
            if consumed:
                _write_buy_tombstones(conn, consumed, old_buy_pos)

            conn.execute(f"RELEASE {sp}")
            rebuilt.append({
                "broker": broker, "asset": asset,
                "open_lots": len(replay["open_lots"]),
                "sells": len(replay["operations"]),
            })
        except Exception as ex:
            conn.execute(f"ROLLBACK TO {sp}")
            conn.execute(f"RELEASE {sp}")
            log.warning("rebuild_fifo: %s/%s falló, se deja como estaba: %s",
                        broker, asset, ex)
            errors.append({"broker": broker, "asset": asset, "error": str(ex)})

    if rebuilt or errors:
        log.info("rebuild_fifo user=%s rebuilt=%d skipped_manual=%d errors=%d",
                 uid, len(rebuilt), len(skipped_manual), len(errors))
    return {
        "rebuilt": rebuilt,
        "skipped_manual": skipped_manual,
        "skipped_no_sell": skipped_no_sell,
        "errors": errors,
    }
