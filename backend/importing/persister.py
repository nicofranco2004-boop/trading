"""Persister: traduce NormalizedTx a side-effects en el motor existente.

Diseño:
- Se ejecuta en una sola transacción (single `with conn:`) que el caller abre.
- Las transacciones se procesan en orden cronológico (date asc, row_index asc)
  para que las ventas vean el stock creado por compras anteriores del mismo CSV.
- Reusa los helpers de bajo nivel de main.py (que ya aceptan `conn` y no
  abren transacciones propias):
    _adjust_broker_cash, _adjust_cash, _update_monthly_pnl_realized,
    _update_monthly_flow, _repair_monthly_chain, _ensure_usd_sibling.
- _repair_monthly_chain se llama UNA SOLA VEZ por broker tocado al final,
  no por fila — evita O(n × meses) en imports grandes.

Cada NormalizedTx insertada se trackea para revert: el persister actualiza
import_normalized_tx con created_position_id / created_operation_id.

Ventas FIFO pueden generar múltiples rows en `operations`. Guardamos solo el
primer ID en created_operation_id; al revertir, buscamos todas las rows con
ese batch_id en `operations` (vamos a marcar las que creó este batch con un
filtro adicional). En vez de eso, usamos un campo `import_batch_id` en
positions/operations? No: para no migrar las tablas existentes, llevamos un
mapping en import_normalized_tx → operation_ids vía notes.

Decisión MVP: tabla intermedia `import_op_links` (batch_id, position_id,
operation_id) que enumera todos los IDs creados por el batch. Más simple
para revert.
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional

from .schema import (
    NormalizedTx,
    OP_BUY, OP_SELL, OP_DEPOSIT, OP_WITHDRAW, OP_DIVIDEND, OP_INTEREST,
    OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS, OP_FEE, OP_TAX, OP_FUTURES_PNL,
)
from . import seed as _seed


def blue_for_date(conn, date_str, fallback):
    """Blue (venta) del día `date_str` (YYYY-MM-DD) desde fx_rates_daily — el más
    reciente en o antes de esa fecha. Fallback al valor dado si no hay data.

    Se usa para valuar el cost basis de un lote ARS vendido en USD (dólar-MEP):
    los pesos que pusiste valían `cost_ars / blue_de_la_compra` dólares, NO
    `/ blue_de_hoy`. Como el peso se devalúa, usar el blue actual achica el costo
    en USD y por ende INFLA la ganancia realizada. Esto lo evita.
    """
    if not date_str:
        return fallback
    try:
        row = conn.execute(
            "SELECT blue_venta FROM fx_rates_daily WHERE date <= ? ORDER BY date DESC LIMIT 1",
            (str(date_str)[:10],),
        ).fetchone()
        if row and row[0] and float(row[0]) > 0:
            return float(row[0])
    except Exception:
        pass
    return fallback


def broker_pair(conn, uid: int, broker: str) -> List[str]:
    """Nombres del PAR de brokers padre↔'· USD' al que pertenece `broker`.

    El MISMO activo comprado en una moneda y vendido en la otra (dólar-MEP con
    acciones/CEDEARs) queda PARTIDO por el routing: la pata USD en el sibling
    '· USD' y la pata ARS en el padre. Para que el FIFO las NETEE (neto de
    tenencia = 0, P&L realizado correcto) sin romper el cash (que sí queda
    per-broker), el FIFO consume lotes del activo en AMBOS brokers del par.
    Si `broker` no tiene par, devuelve [broker].
    """
    row = conn.execute(
        "SELECT id, parent_broker_id FROM brokers WHERE user_id=? AND name=?",
        (uid, broker)).fetchone()
    if not row:
        return [broker]
    names = {broker}
    if row["parent_broker_id"]:                    # es sibling → sumar el padre
        pr = conn.execute("SELECT name FROM brokers WHERE id=? AND user_id=?",
                          (row["parent_broker_id"], uid)).fetchone()
        if pr:
            names.add(pr["name"])
    else:                                          # es padre → sumar su(s) sibling(s)
        for s in conn.execute(
                "SELECT name FROM brokers WHERE user_id=? AND parent_broker_id=?",
                (uid, row["id"])).fetchall():
            names.add(s["name"])
    return sorted(names)


class PersistError(Exception):
    """Error fatal durante la persistencia. Aborta toda la transacción."""
    def __init__(self, row_index: int, message: str):
        self.row_index = row_index
        self.message = message
        super().__init__(message)


def persist_batch(
    conn,
    *,
    uid: int,
    batch_id: str,
    txs: List[NormalizedTx],
    raw_row_ids_by_index: Dict[int, int],   # row_index → import_raw_rows.id
    helpers,                                 # módulo / namespace con los helpers de main
    seed_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Aplica todas las txs en orden cronológico. Devuelve resumen.
    El caller debe haber abierto `with conn:`. Si esta función levanta,
    SQLite hace rollback automático.

    Si `seed_state` es no-None, prependemos NormalizedTx sintéticas (DEPOSITs
    + BUYs) al inicio del orden cronológico — fecha = `seed_date` (1 día antes
    del primer movimiento del CSV). Eso resuelve los casos de CSVs parciales
    donde faltaban aportes y posiciones previas.
    """
    # Si hay seed_state, generar txs sintéticas y persistirlas en raw_rows /
    # normalized_tx para que queden auditables y revertibles junto al batch.
    if seed_state:
        seed_txs = _seed.build_seed_txs(seed_state)
        if seed_txs:
            for st in seed_txs:
                # Una fila sintética por seed tx — guardamos el contenido como
                # raw_json para que la página de detalle del batch tenga algo
                # que mostrar.
                payload = {
                    "fecha": st.date,
                    "tipo": st.operation_type,
                    "broker": st.broker,
                    "activo": st.asset_symbol or "",
                    "cantidad": st.quantity,
                    "precio": st.unit_price,
                    "monto": st.gross_amount,
                    "moneda": st.currency or "",
                    "notas": st.notes or "",
                    "_synthetic_seed": True,
                }
                cur = conn.execute(
                    """INSERT INTO import_raw_rows (batch_id, row_index, raw_json, status, errors_json)
                       VALUES (?,?,?,'valid',NULL)""",
                    (batch_id, st.row_index, json.dumps(payload, ensure_ascii=False)),
                )
                raw_id = cur.lastrowid
                raw_row_ids_by_index[st.row_index] = raw_id
                # Fase 4: stamp gross_amount_usd al momento del seed (con
                # tc_blue actual del user — el seed corre ahora, no en el
                # pasado, así que esto refleja el FX del momento del import).
                # Audit follow-up: stamp también en memory (st es NormalizedTx)
                # para que `_apply_cash_flow` use el mismo USD que la DB.
                from .pipeline import _stamp_gross_amount_usd, _read_user_tc_blue
                _tc_blue_seed = _read_user_tc_blue(conn, uid)
                gross_usd = _stamp_gross_amount_usd(st.currency, st.gross_amount, _tc_blue_seed)
                st.gross_amount_usd = gross_usd
                conn.execute(
                    """INSERT INTO import_normalized_tx
                       (batch_id, raw_row_id, date, broker, operation_type, asset_symbol, asset_name, asset_type,
                        quantity, unit_price, gross_amount, fees, taxes, currency, settlement_currency, notes,
                        gross_amount_usd)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (batch_id, raw_id, st.date, st.broker, st.operation_type,
                     st.asset_symbol, st.asset_name, st.asset_type,
                     st.quantity, st.unit_price, st.gross_amount,
                     st.fees, st.taxes, st.currency, st.settlement_currency, st.notes,
                     gross_usd),
                )
            txs = list(seed_txs) + list(txs)

    # Orden cronológico determinístico — el seed (1 día antes) cae naturalmente
    # primero en este sort. Dentro del mismo día, BUYs van antes que SELLs:
    # evita "stock insuficiente" cuando el CSV tiene una venta intra-día antes
    # que su compra correspondiente (típico en Cocos "Venta Trading" + "Compra
    # Trading" mismo día). El neto en posición/cash es idéntico — solo cambia
    # el orden de ejecución.
    _BUY_FIRST_KEY = {OP_BUY: 0}  # BUY = 0, todo lo demás (SELL/etc) = 1
    sorted_txs = sorted(txs, key=lambda t: (
        t.date,
        _BUY_FIRST_KEY.get(t.operation_type, 1),
        t.row_index,
    ))

    # Currency routing: por cada broker ARS mencionado en las txs que tenga al
    # menos una fila con moneda USD/USDT, auto-creamos su sub-broker USD y
    # routeamos las filas correspondientes. Funciona tanto en single-broker
    # mode (1 par parent/sibling) como en multi-broker mode (N pares).
    # Las FX siempre van al broker correcto según el op_type, sin importar
    # la columna currency de la fila.
    batch_row = conn.execute(
        "SELECT broker, route_by_currency FROM import_batches WHERE id=? AND user_id=?",
        (batch_id, uid),
    ).fetchone()
    route_currency = bool(batch_row and (batch_row["route_by_currency"] or 0))

    # Mapa parent_name → sibling_name. Se llena solo si route_currency=True.
    sibling_for: Dict[str, str] = {}
    if route_currency:
        # Identificar todos los brokers ARS que tienen filas USD para ellos.
        unique_brokers = {tx.broker for tx in sorted_txs}
        for broker_name in unique_brokers:
            parent = conn.execute(
                "SELECT * FROM brokers WHERE name=? AND user_id=?",
                (broker_name, uid),
            ).fetchone()
            if not parent or parent["currency"] != "ARS":
                continue
            has_usd_rows = any(
                (t.currency or "").upper() in ("USD", "USDT")
                for t in sorted_txs
                if t.broker == broker_name
            )
            has_fx = any(
                t.operation_type in ("FX_ARS_TO_USD", "FX_USD_TO_ARS")
                for t in sorted_txs
                if t.broker == broker_name
            )
            if has_usd_rows or has_fx:
                sibling = helpers._ensure_usd_sibling(conn, uid, parent)
                sibling_for[broker_name] = sibling["name"]
                # Asegurar que existe cash position USD en el sibling (con 0 si
                # no hay). Sin esto, los BUYs USD que aterrizan en un sibling
                # recién creado no descuentan cash (silent no-op de
                # _adjust_broker_cash) y el saldo queda inflado.
                cash_exists = conn.execute(
                    "SELECT 1 FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
                    (uid, sibling["name"]),
                ).fetchone()
                if not cash_exists:
                    conn.execute(
                        """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
                           VALUES (?,?,?,1,0)""",
                        (uid, sibling["name"], "USDT"),
                    )

        # Aplicar routing per-row. Cuando muteamos tx.broker, también
        # actualizamos la fila en import_normalized_tx para que el revert
        # (que lee desde la DB, no desde memoria) sepa el broker REAL al
        # que se aplicó el cash y pueda revertirlo correctamente.
        for tx in sorted_txs:
            sib = sibling_for.get(tx.broker)
            if not sib:
                continue
            cur = (tx.currency or "").upper()
            op = tx.operation_type
            new_broker = None
            if op == "FX_ARS_TO_USD":
                # Compra USD pagando ARS → fuente es el padre ARS (no tocar)
                pass
            elif op == "FX_USD_TO_ARS":
                # Venta USD → fuente es el sibling
                new_broker = sib
            elif cur in ("USD", "USDT"):
                new_broker = sib
            if new_broker:
                tx.broker = new_broker
                # Sync DB para que el revert lea el broker correcto
                raw_id = raw_row_ids_by_index.get(tx.row_index)
                if raw_id is not None:
                    conn.execute(
                        "UPDATE import_normalized_tx SET broker=? WHERE batch_id=? AND raw_row_id=?",
                        (new_broker, batch_id, raw_id),
                    )

    brokers_touched: set = set()
    counts = {"positions": 0, "operations": 0, "cash_movements": 0, "conversions": 0}
    # Filas que fallaron al persistir (errores no detectados en validación,
    # ej.: cash insuficiente en FX). Cada fila va en su propio SAVEPOINT, así
    # un fallo puntual no aborta todo el batch.
    skipped: List[Dict[str, Any]] = []

    # TC para convertir movimientos ARS a USD-equivalente al cargar
    # monthly_entries (que almacena todo en USD). Lo leemos una vez de la
    # config del usuario; mismo default que usa el endpoint manual.
    tc_blue_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (uid,),
    ).fetchone()
    try:
        tc_blue = float(tc_blue_row["value"]) if tc_blue_row else 1415.0
        if tc_blue <= 0:
            tc_blue = 1415.0
    except (TypeError, ValueError):
        tc_blue = 1415.0

    for i, tx in enumerate(sorted_txs):
        raw_row_id = raw_row_ids_by_index.get(tx.row_index)
        broker = tx.broker
        op = tx.operation_type
        sp_name = f"row_{i}"

        try:
            conn.execute(f"SAVEPOINT {sp_name}")
            try:
                if op == OP_BUY:
                    _persist_buy(conn, uid, batch_id, raw_row_id, tx, helpers)
                    counts["positions"] += 1

                elif op == OP_SELL:
                    created_op_ids = _persist_sell_fifo(conn, uid, batch_id, raw_row_id, tx, helpers,
                                                          tc_blue=tc_blue)
                    counts["operations"] += len(created_op_ids)

                elif op == OP_DEPOSIT:
                    _persist_cash_in(conn, uid, batch_id, raw_row_id, tx, helpers, tc_blue=tc_blue)
                    counts["cash_movements"] += 1

                elif op in (OP_DIVIDEND, OP_INTEREST):
                    # Dividendos / intereses se tratan como GANANCIA (no como
                    # deposit). Crean fila en operations + suben pnl_realized.
                    _persist_dividend_or_interest(conn, uid, batch_id, raw_row_id, tx,
                                                    helpers, tc_blue=tc_blue)
                    counts["operations"] += 1

                elif op in (OP_WITHDRAW, OP_FEE, OP_TAX):
                    # IMPUESTO (retención) se comporta igual que FEE en el cash:
                    # debita, sin crear posición. Solo cambia la CATEGORÍA (métrica).
                    _persist_cash_out(conn, uid, batch_id, raw_row_id, tx, helpers, tc_blue=tc_blue)
                    counts["cash_movements"] += 1

                elif op == OP_FX_ARS_TO_USD:
                    touched = _persist_fx(conn, uid, batch_id, raw_row_id, tx, helpers,
                                          direction="ars_to_usd", tc_blue=tc_blue)
                    counts["conversions"] += 1
                    brokers_touched.update(touched)

                elif op == OP_FX_USD_TO_ARS:
                    touched = _persist_fx(conn, uid, batch_id, raw_row_id, tx, helpers,
                                          direction="usd_to_ars", tc_blue=tc_blue)
                    counts["conversions"] += 1
                    brokers_touched.update(touched)

                elif op == OP_FUTURES_PNL:
                    _persist_futures_pnl(conn, uid, batch_id, raw_row_id, tx, helpers)
                    counts["operations"] += 1

                else:
                    # OP_TRANSFER no debería llegar acá (filtrado por validator)
                    raise PersistError(tx.row_index, f"Tipo de operación no soportado: {op}")

                conn.execute(f"RELEASE {sp_name}")
                brokers_touched.add(broker)

            except Exception as inner_ex:
                # Rollback de esta fila — el resto del batch continúa
                conn.execute(f"ROLLBACK TO {sp_name}")
                conn.execute(f"RELEASE {sp_name}")
                msg = inner_ex.message if isinstance(inner_ex, PersistError) else str(inner_ex)
                # Limpiar prefijos repetidos tipo "400: ..." de HTTPExceptions internas
                if isinstance(msg, str) and msg.startswith("400: "):
                    msg = msg[5:]
                skipped.append({"row_index": tx.row_index, "message": msg})

        except Exception as savepoint_ex:
            # Si fallar el SAVEPOINT mismo, no podemos continuar — eso sí es fatal.
            raise PersistError(tx.row_index, f"Error al crear savepoint: {savepoint_ex}")

    # Repair chain una sola vez por broker tocado + global
    for b in brokers_touched:
        helpers._repair_monthly_chain(conn, uid, b)
    helpers._repair_monthly_chain(conn, uid, "global")

    # Backfill de snapshots: una entrada al último día de cada mes cerrado
    # del global, así el chart "Evolución del portfolio" tiene historia para
    # mostrar después del import. Los snapshots existentes de fechas que no
    # toca el batch quedan intactos.
    _backfill_snapshots_from_monthly(conn, uid)

    # Snapshot final de cash por broker tocado — sirve para que el frontend
    # muestre warnings si algún saldo quedó negativo.
    cash_health: List[Dict[str, Any]] = []
    for b in sorted(brokers_touched):
        rows = conn.execute(
            """SELECT p.broker, p.asset, p.invested, br.currency
                 FROM positions p
                 JOIN brokers br ON br.name = p.broker AND br.user_id = p.user_id
                WHERE p.user_id=? AND p.broker=? AND p.is_cash=1""",
            (uid, b),
        ).fetchall()
        for r in rows:
            cash_health.append({
                "broker": r["broker"],
                "asset": r["asset"],
                "currency": r["currency"],
                "balance": float(r["invested"] or 0),
            })

    # Update batch counters
    conn.execute(
        """UPDATE import_batches
              SET status='confirmed',
                  confirmed_at=datetime('now')
            WHERE id=? AND user_id=?""",
        (batch_id, uid),
    )
    return {
        "positions_created": counts["positions"],
        "operations_created": counts["operations"],
        "cash_movements": counts["cash_movements"],
        "conversions": counts["conversions"],
        "skipped_rows": skipped,
        "cash_health": cash_health,
    }


# ─── Implementaciones por op_type ────────────────────────────────────────────

def _persist_buy(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers):
    """Compra → INSERT positions + debit cash. Equivalente a POST /positions."""
    qty = float(tx.quantity or 0)
    unit = float(tx.unit_price or 0)
    invested = float(tx.gross_amount) if tx.gross_amount is not None else (unit * qty)
    fees = float(tx.fees or 0)
    # Persistimos la moneda nativa del lote (USD para Compra Dolar Mep, ARS
    # para compras normales). Sin esto, el SELL no podía distinguir lots
    # cross-currency y producía P&L absurdo.
    lot_currency = (tx.currency or "").upper() or None
    if lot_currency == "USDT":
        lot_currency = "USD"

    cur = conn.execute(
        """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
           invested, tc_compra, price_override, notes, entry_date, commissions, currency, asset_type)
           VALUES (?,?,?,0,?,?,?,?,?,?,?,?,?,?)""",
        (uid, tx.broker, tx.asset_symbol, unit if unit > 0 else None, qty,
         invested, None, None, tx.notes, tx.date, fees, lot_currency,
         (tx.asset_type or None)),
    )
    position_id = cur.lastrowid
    cost_total = invested + fees
    if cost_total > 0:
        helpers._adjust_broker_cash(conn, uid, tx.broker, -cost_total)

    _link(conn, batch_id, raw_row_id, position_id=position_id)


def _persist_sell_fifo(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers,
                        tc_blue: float = 1415.0) -> List[int]:
    """Venta FIFO. Replica la lógica de sell_position_fifo en main.py.

    Para brokers ARS: usa `tc_blue` de la config como TC de venta para convertir
    el P&L ARS a USD-equivalente (mismo patrón que el flow manual con data.tc_venta).
    Para brokers USDT/USD: el cálculo es directo sin conversión.
    """
    # Resolver currency del broker (para cash side y monthly_entries)
    br = conn.execute(
        "SELECT currency FROM brokers WHERE name=? AND user_id=?", (tx.broker, uid)
    ).fetchone()
    broker_currency = br["currency"] if br else "USDT"

    # Moneda EN LA QUE SE VENDIÓ — viene del CSV. Para Cocos "Venta Dolar Mep"
    # esto es USD aunque el broker padre sea ARS. Antes usábamos broker_currency
    # acá, lo que comparaba ARS entry_invested vs USD exit_price (P&L -99.8%
    # falso para SELLs MEP).
    sell_currency = (tx.currency or "").upper() or broker_currency
    if sell_currency == "USDT":
        sell_currency = "USD"
    if sell_currency not in ("ARS", "USD"):
        sell_currency = broker_currency  # fallback defensivo
    currency = sell_currency  # alias usado abajo (mantengo el nombre antiguo)

    # FIFO POR MONEDA: una venta en X consume SOLO lotes en X (el mismo ticker se
    # puede tener en ARS y USD). En import el routing ya separa ARS (padre)/USD
    # (sibling) por broker → esto es un no-op para data ruteada; cubre el caso
    # same-broker dual-currency y lotes NULL legacy. Fallback a todos si no hay
    # lotes de esa moneda (red de seguridad: no rompe P&L existente).
    from behavioral import _native_ccy as _nccy

    def _by_ccy(rows):
        # Same-currency FIFO; fallback a todos solo si NO hay lotes de esa moneda
        # (legacy NULL). El NETEO dólar-MEP (spill cross-currency con guarda de
        # neteo-total) vive en rebuild._replay_asset, que es la fuente autoritativa
        # de las posiciones finales post-import (sobrescribe lo que escribe el
        # persister). Acá NO hacemos spill para no destruir tenencias dual-currency
        # genuinas en el estado transitorio (audit 2026-06-26).
        same = [p for p in rows if _nccy(dict(p)) == currency]
        return same if same else rows

    # NETEO CROSS-BROKER del par padre↔'· USD': el MISMO activo comprado vía
    # dólar-MEP (pata USD ruteada al sibling) y vendido en pesos (pata ARS en el
    # padre) queda PARTIDO por el routing. Una compra-USD de BMA en el sibling +
    # su venta-ARS en el padre deben NETEAR (tenencia 0), no dejar un fantasma en
    # el sibling. Buscamos los lotes del activo en AMBOS brokers del par; _by_ccy
    # prioriza los de la moneda de la venta y, si no hay (este caso: venta ARS,
    # lote USD), cae al lote cross-currency y lo valúa con tc_blue. El CASH no se
    # toca acá → sigue per-broker correcto (USD sale del sibling, ARS entra al padre).
    _pair = broker_pair(conn, uid, tx.broker)
    _ph = ",".join("?" * len(_pair))

    positions = _by_ccy(conn.execute(
        f"""SELECT * FROM positions
           WHERE user_id=? AND broker IN ({_ph}) AND asset=? AND is_cash=0 AND quantity > 0
           ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC""",
        (uid, *_pair, tx.asset_symbol),
    ).fetchall())
    total_avail = sum((p["quantity"] or 0) for p in positions)
    qty_to_sell = float(tx.quantity or 0)

    # Política: si el CSV vende más de lo disponible, asumimos que existe stock
    # previo que el CSV no incluye (history-as-truth). Auto-creamos un seed lot
    # al precio de venta para la porción faltante — P&L = 0 sobre ese chunk
    # (no inventamos ganancia ni pérdida ficticia). Si el user quiere reflejar
    # la pérdida real, puede usar el wizard de "Estado inicial" antes de
    # confirmar para precisar el cost basis.
    if qty_to_sell > total_avail + 1e-9:
        missing_qty = qty_to_sell - total_avail
        seed_price = float(tx.unit_price or 0)
        seed_invested = missing_qty * seed_price
        # entry_date: la misma fecha de la venta (FIFO lo ordena por entry_date,
        # luego por id — queda al final entre lotes con la misma fecha).
        seed_cur = conn.execute(
            """INSERT INTO positions
                  (user_id, broker, asset, quantity, invested,
                   buy_price, commissions, entry_date, is_cash, currency, asset_type)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?)""",
            (uid, tx.broker, tx.asset_symbol,
             missing_qty, round(seed_invested, 6),
             seed_price, tx.date, (tx.currency or "USD").upper(),
             (tx.asset_type or None)),
        )
        # Linkear el seed lot al batch para que el revert lo borre. Sin esto
        # quedaba una posición fantasma que sobrevivía todos los reverts (B3).
        _link(conn, batch_id, raw_row_id, position_id=seed_cur.lastrowid)
        # Re-leer positions para que el FIFO encuentre el seed lot (mismo filtro
        # por moneda + mismo par de brokers — el seed se creó en la moneda/broker
        # de la venta).
        positions = _by_ccy(conn.execute(
            f"""SELECT * FROM positions
               WHERE user_id=? AND broker IN ({_ph}) AND asset=? AND is_cash=0 AND quantity > 0
               ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC""",
            (uid, *_pair, tx.asset_symbol),
        ).fetchall())
        total_avail = sum((p["quantity"] or 0) for p in positions)

    exit_price = float(tx.unit_price or 0)
    sell_commissions = float(tx.fees or 0)
    op_date = tx.date

    remaining = qty_to_sell
    total_pnl_usd = 0.0
    total_pnl_ars_native = 0.0
    total_proceeds_native = 0.0
    ops_created: List[int] = []

    # TC efectivo de venta para SELLs ARS (USD para SELLs USD no aplica)
    tc_venta = tc_blue if sell_currency == "ARS" else 1.0

    for p in positions:
        if remaining <= 1e-9:
            break
        pos_qty = p["quantity"] or 0
        take = min(remaining, pos_qty)
        if take <= 0:
            continue
        ratio = take / pos_qty if pos_qty > 0 else 0
        pos_buy_commissions = (p["commissions"] if "commissions" in p.keys() else 0) or 0
        base_invested = (p["invested"] or 0) + pos_buy_commissions

        # Moneda nativa del lote — la guardamos en positions.currency desde
        # el BUY. Si el lote es viejo (pre-migración) o no la trajo el parser,
        # asumimos la moneda del broker para back-compat.
        lot_currency = (p["currency"] if "currency" in p.keys() else None) or currency

        # CROSS-CURRENCY: el SELL es en otra moneda que el BUY → convertimos el
        # cost basis del lote a la moneda del SELL. Sin esto, un lote comprado por
        # USD 573 vs SELL en ARS daba P&L de +160000%.
        if lot_currency != currency and tc_blue:
            if lot_currency == "USD" and currency == "ARS":
                # Lote USD vendido en ARS: el costo USD es real. Se lleva a ARS al
                # MISMO TC que la venta (tc_venta) — así pnl_ars/tc_venta preserva
                # el costo USD (se cancela). tc_venta == tc_blue para SELLs ARS.
                base_invested = base_invested * (tc_venta or tc_blue)
            elif lot_currency == "ARS" and currency == "USD":
                # Lote ARS vendido en USD (dólar-MEP): convertiste pesos→dólares al
                # vender, así que el FX SÍ se realiza. El costo en USD es lo que esos
                # pesos valían CUANDO COMPRASTE (blue de la fecha de entrada del
                # lote), NO el blue de hoy: usarlo achica el costo e infla la
                # ganancia con la devaluación del peso.
                entry_dt = p["entry_date"] if "entry_date" in p.keys() else None
                purchase_blue = blue_for_date(conn, entry_dt, tc_blue)
                base_invested = base_invested / (purchase_blue or tc_blue)

        entry_invested = base_invested * ratio if base_invested else None

        chunk_commission = sell_commissions * (take / qty_to_sell) if qty_to_sell else 0

        if getattr(tx, "transfer_out", False):
            # RETIRO/TRANSFERENCIA del activo fuera de la cuenta (ej. cripto que
            # sale de un exchange a una wallet, polvo→BNB): NO es una venta →
            # cerramos el lote A COSTO (P&L 0) y NO generamos cash (no entró plata).
            # Sin esto, un retiro bookeaba una pérdida fantasma = costo del lote.
            if currency == "ARS":
                invested_usd = (entry_invested or 0) / tc_venta if entry_invested and tc_venta else 0
            else:
                invested_usd = entry_invested if entry_invested is not None else ((p["buy_price"] or 0) * take)
            pnl_usd = 0.0
            proceeds_native = 0.0
        elif currency == "ARS":
            # Mismo modelo que el flow manual con FX-phantom-fix:
            # cost basis y venta se valúan al MISMO TC (el de venta).
            pnl_ars_chunk = exit_price * take - (entry_invested or 0) - chunk_commission
            pnl_usd = pnl_ars_chunk / tc_venta if tc_venta else 0
            invested_usd = (entry_invested or 0) / tc_venta if entry_invested and tc_venta else 0
            total_pnl_ars_native += pnl_ars_chunk
            proceeds_native = exit_price * take - chunk_commission
        else:
            cost = entry_invested if entry_invested is not None else ((p["buy_price"] or 0) * take)
            pnl_usd = (exit_price * take) - cost - chunk_commission
            invested_usd = cost
            proceeds_native = exit_price * take - chunk_commission

        total_pnl_usd += pnl_usd
        total_proceeds_native += proceeds_native
        pnl_pct = (pnl_usd / invested_usd * 100) if invested_usd else None

        cur = conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type, entry_price,
               exit_price, quantity, pnl_usd, pnl_pct, entry_date, commissions)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (uid, op_date, p["broker"], p["asset"], "Venta",
             p["buy_price"], exit_price, take,
             round(pnl_usd, 2),
             round(pnl_pct, 4) if pnl_pct is not None else None,
             p["entry_date"] if "entry_date" in p.keys() else None,
             round(chunk_commission, 4)),
        )
        op_id = cur.lastrowid
        ops_created.append(op_id)
        _link(conn, batch_id, raw_row_id, operation_id=op_id)

        if take >= pos_qty - 1e-9:
            conn.execute("DELETE FROM positions WHERE id=? AND user_id=?", (p["id"], uid))
        else:
            new_qty = pos_qty - take
            remaining_ratio = 1 - ratio
            new_invested = round((p["invested"] or 0) * remaining_ratio, 6) if p["invested"] is not None else None
            new_commissions = round(pos_buy_commissions * remaining_ratio, 6)
            conn.execute(
                "UPDATE positions SET quantity=?, invested=?, commissions=? WHERE id=? AND user_id=?",
                (new_qty, new_invested, new_commissions, p["id"], uid),
            )
        remaining -= take

    if total_proceeds_native > 0:
        helpers._adjust_broker_cash(conn, uid, tx.broker, total_proceeds_native)

    op_year, op_month = int(op_date[:4]), int(op_date[5:7])
    # Para brokers ARS, el broker entry guarda P&L ARS-nativo / TC = USD-equivalente
    # (mismo patrón que el flow manual). Global siempre USD-true.
    if currency == "ARS":
        pnl_for_broker = total_pnl_ars_native / tc_venta if tc_venta else 0
    else:
        pnl_for_broker = total_pnl_usd
    helpers._update_monthly_pnl_realized(conn, uid, tx.broker, op_year, op_month, pnl_for_broker)
    helpers._update_monthly_pnl_realized(conn, uid, "global", op_year, op_month, total_pnl_usd)

    return ops_created


def _persist_futures_pnl(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers):
    """PnL realizado de un cierre de posición de futuros.

    Crea una fila en `operations` con op_type='Futuros' (visible en la página
    Operaciones), suma/resta el monto al cash del broker, y actualiza
    monthly_entries.pnl_realized para que el Dashboard refleje el resultado.

    No tenemos info del par específico (BTC/USDT, etc.) ni de la dirección
    (LONG/SHORT) desde el export estándar de Binance — el TradeID por sí solo
    no lo dice. El usuario puede editar la operación después si quiere
    agregar el detalle.
    """
    pnl = float(tx.gross_amount or 0)
    if abs(pnl) < 1e-9:
        return

    # Insertar operación
    cur = conn.execute(
        """INSERT INTO operations (user_id, date, broker, asset, op_type, entry_price,
           exit_price, quantity, pnl_usd, pnl_pct, commissions)
           VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
        (uid, tx.date, tx.broker, tx.asset_symbol or "Futuros",
         "Futuros", None, None, None, round(pnl, 2), None),
    )
    op_id = cur.lastrowid
    _link(conn, batch_id, raw_row_id, operation_id=op_id)

    # Sumar al cash del broker (PnL positivo entra, negativo sale)
    helpers._adjust_broker_cash(conn, uid, tx.broker, pnl)

    # Actualizar monthly_entries.pnl_realized para broker + global
    year, month = int(tx.date[:4]), int(tx.date[5:7])
    helpers._update_monthly_pnl_realized(conn, uid, tx.broker, year, month, pnl)
    helpers._update_monthly_pnl_realized(conn, uid, "global", year, month, pnl)


def _persist_cash_in(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers, tc_blue: float):
    """Depósito → suma cash al broker, registra monthly flow como deposit."""
    _apply_cash_flow(conn, uid, batch_id, raw_row_id, tx, helpers, sign=+1, tc_blue=tc_blue)


def _is_amort_capital_return(op_type: str, asset_symbol, asset_type, notes) -> bool:
    """¿Este DIVIDEND/INTEREST es el CASH de una AMORTIZACIÓN de bono SIN cantidad?

    Balanz ("Renta y Amortización / TX26" con cantidad 0), IOL y el generic mandan
    la amortización como cash-only → caía en DIVIDENDO y el capital DEVUELTO se
    contaba entero como ganancia realizada (P&L inflado — reporte de user 2026-07-09
    con TX26). Una amortización devuelve TU capital: no es ingreso.

    Sin la cantidad no podemos armar la VENTA (eso es la Parte A, que sí ocurre
    cuando el export trae cantidad) ni consumir cost-basis FIFO (necesita el face)
    → modelamos DEVOLUCIÓN DE CAPITAL P&L-neutral: el cash entra igual, pero NO
    suma a pnl_realized y la operation queda como 'Amortización' con pnl 0 (mismo
    op_type que el flujo manual de bond_cashflow, que tampoco toca el P&L mensual).
    Conservador: si el pago incluía cupón/CER genuino, se sub-cuenta (nunca se
    sobre-cuenta). El nominal lo termina de clavar la foto de tenencia o el sweep.

    Contrato del marcador (mismo que las VENTA-amort del sweep): notes contiene
    'amortiz' Y el activo es un bono (asset_type BOND o ticker de bono AR conocido).
    """
    if op_type not in (OP_DIVIDEND, OP_INTEREST):
        return False
    if not asset_symbol:
        return False
    if "amortiz" not in (notes or "").lower():
        return False
    if (asset_type or "").upper() == "BOND":
        return True
    try:
        from ai.ar_bonds_metadata import is_known_ar_bond
        return is_known_ar_bond(asset_symbol)
    except Exception:
        return False


def _persist_dividend_or_interest(conn, uid, batch_id, raw_row_id, tx: NormalizedTx,
                                    helpers, tc_blue: float):
    """Dividendo / Interés → cash up + fila en operations + pnl_realized.

    A diferencia de DEPOSIT (que cuenta como capital aportado), el dividendo
    y el interés son retorno SOBRE el portfolio — entran como ganancia
    realizada (pnl_realized), aparecen en /operaciones para que el usuario
    vea historia, y suben el cash igual que un deposit.

    EXCEPCIÓN — amortización de bono sin cantidad (_is_amort_capital_return):
    devolución de capital → cash entra igual, pero op_type='Amortización' con
    pnl_usd=0 y SIN tocar pnl_realized (no es ganancia). Ver docstring del helper.

    En operations:
        op_type = "Dividendo" o "Interés" (o "Amortización" para el caso especial)
        asset   = el ticker que pagó (VOO, AL30, etc — puede ser NULL)
        quantity = el monto (en moneda nativa del broker)
        pnl_usd = el monto convertido a USD si el broker es ARS (0 para amort)
    """
    broker_row = conn.execute(
        "SELECT * FROM brokers WHERE user_id=? AND name=?", (uid, tx.broker),
    ).fetchone()
    if not broker_row:
        raise PersistError(tx.row_index, f"Broker '{tx.broker}' no encontrado.")
    currency = broker_row["currency"]
    amount = float(tx.gross_amount or 0)
    if amount <= 0:
        raise PersistError(tx.row_index, "Monto debe ser positivo.")

    # 1. Subir cash del broker (auto-crea posición si no existe)
    helpers._adjust_broker_cash(conn, uid, tx.broker, amount)

    # ¿Amortización de bono sin cantidad? → devolución de capital, P&L-neutral.
    is_amort = _is_amort_capital_return(
        tx.operation_type, tx.asset_symbol, tx.asset_type, tx.notes)

    # 2. Insertar fila en operations
    if is_amort:
        op_label = "Amortización"
    else:
        op_label = "Dividendo" if tx.operation_type == OP_DIVIDEND else "Interés"
    amount_usd = (amount / tc_blue) if currency == "ARS" else amount
    pnl_usd = 0.0 if is_amort else round(amount_usd, 2)
    cur = conn.execute(
        """INSERT INTO operations (user_id, date, broker, asset, op_type,
           entry_price, exit_price, quantity, pnl_usd, pnl_pct, commissions)
           VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
        (uid, tx.date, tx.broker, tx.asset_symbol or "—", op_label,
         None, None, round(amount, 4),
         pnl_usd, None),
    )
    op_id = cur.lastrowid
    _link(conn, batch_id, raw_row_id, operation_id=op_id)

    # 3. monthly_pnl_realized (en USD — convención de monthly_entries).
    #    La amortización NO suma: es capital que vuelve, no ganancia.
    if not is_amort:
        y, m = int(tx.date[:4]), int(tx.date[5:7])
        helpers._update_monthly_pnl_realized(conn, uid, tx.broker, y, m, amount_usd)
        helpers._update_monthly_pnl_realized(conn, uid, "global", y, m, amount_usd)


def _persist_cash_out(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers, tc_blue: float):
    """Retiro / Comisión aislada → resta cash, registra monthly flow."""
    _apply_cash_flow(conn, uid, batch_id, raw_row_id, tx, helpers, sign=-1, tc_blue=tc_blue)


def _apply_cash_flow(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers, sign: int, tc_blue: float):
    """Aplica DEPOSIT/WITHDRAW/DIVIDEND/INTEREST/FEE.

    Política de overdraft del importer: a diferencia del flow manual
    (que es estricto con saldos negativos), acá permitimos que el cash quede
    negativo. Razón: los CSVs reales pueden traer porciones parciales del
    histórico (faltan aportes viejos), y los CSVs generados por IA suelen
    tener cronología imperfecta. En vez de saltar la fila, dejamos que el
    saldo refleje el estado y reportamos el balance final al usuario.
    """
    broker_row = conn.execute(
        "SELECT * FROM brokers WHERE user_id=? AND name=?", (uid, tx.broker),
    ).fetchone()
    if not broker_row:
        raise PersistError(tx.row_index, f"Broker '{tx.broker}' no encontrado.")
    currency = broker_row["currency"]
    amount = float(tx.gross_amount or 0)
    if amount <= 0:
        raise PersistError(tx.row_index, "Monto debe ser positivo.")

    cash_pos = conn.execute(
        "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
        (uid, tx.broker),
    ).fetchone()
    if cash_pos:
        new_invested = (cash_pos["invested"] or 0) + sign * amount
        # Overdraft permitido: NO rechazamos saldos negativos en import.
        conn.execute(
            "UPDATE positions SET invested=? WHERE id=? AND user_id=?",
            (new_invested, cash_pos["id"], uid),
        )
        cash_pos_id = cash_pos["id"]
    else:
        # Si no hay cash position, la creamos con el monto neto (puede ser negativo si es withdraw)
        asset_name = "ARS" if currency == "ARS" else "USDT"
        cur = conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (uid, tx.broker, asset_name, sign * amount),
        )
        cash_pos_id = cur.lastrowid

    # Monthly flow: monthly_entries.deposits/withdrawals se almacenan en USD
    # (convención global del motor). Si el broker es ARS, convertimos usando
    # el tc_blue de la config del usuario — mismo patrón que /api/cash/flow.
    # Sin esta conversión, un depósito de 10M ARS se guarda como 10M USD y
    # rompe el "Capital Aportado" del Dashboard.
    #
    # Fase 4 audit follow-up (2026-05-30): PRIORIZAR el USD stamped al preview
    # time (tx.gross_amount_usd) sobre la conversión runtime. Si el preview
    # stampeó $500 con tc=1000 y entre confirm y persist tc cambia a 1500, la
    # conversión runtime daría $666.67 — drift con respecto al stamped en
    # `import_normalized_tx.gross_amount_usd`. Al usar el stamped acá, ambos
    # campos (monthly_entries.deposits + import_normalized_tx.gross_amount_usd)
    # quedan consistentes y el `_recalc` posterior no introduce sorpresas.
    # Fallback a runtime conversion si el stamped no está (seed sintético
    # legacy, tests directos, etc).
    if getattr(tx, "gross_amount_usd", None) is not None:
        amount_usd = float(tx.gross_amount_usd)
    else:
        amount_usd = (amount / tc_blue) if currency == "ARS" else amount
    direction = "deposit" if sign > 0 else "withdraw"
    year, month = int(tx.date[:4]), int(tx.date[5:7])
    helpers._update_monthly_flow(conn, uid, tx.broker, year, month, direction, amount_usd)
    helpers._update_monthly_flow(conn, uid, "global", year, month, direction, amount_usd)

    _link(conn, batch_id, raw_row_id, position_id=cash_pos_id)


def _adjust_cash_permissive(conn, uid: int, broker_name: str, asset: str, delta: float,
                             tc_for_basis: Optional[float] = None):
    """Variante de _adjust_cash que NO rechaza saldos negativos. Permite que
    el cash quede en overdraft tras una FX que descuenta más de lo disponible.
    Resto del comportamiento (tc_compra ponderado, creación on-demand) idem.
    """
    cash = conn.execute(
        "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
        (uid, broker_name),
    ).fetchone()
    if cash:
        existing = cash["invested"] or 0
        new_invested = existing + delta
        # Overdraft permitido — NO clamp a 0.
        if tc_for_basis is not None and delta > 0 and new_invested > 0:
            existing_tc = cash["tc_compra"] or tc_for_basis
            new_tc = (existing * existing_tc + delta * tc_for_basis) / new_invested
            conn.execute(
                "UPDATE positions SET invested=?, tc_compra=? WHERE id=? AND user_id=?",
                (new_invested, new_tc, cash["id"], uid),
            )
        else:
            conn.execute(
                "UPDATE positions SET invested=? WHERE id=? AND user_id=?",
                (new_invested, cash["id"], uid),
            )
    else:
        conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested, tc_compra)
               VALUES (?,?,?,1,?,?)""",
            (uid, broker_name, asset, delta, tc_for_basis),
        )


def _persist_fx(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers, *, direction: str,
                tc_blue: float = 1415.0):
    """FX_ARS_TO_USD o FX_USD_TO_ARS. Después del normalizer:
       gross_amount = ARS, quantity = USD, unit_price = TC.
    """
    ars_amount = float(tx.gross_amount or 0)
    usd_amount = float(tx.quantity or 0)
    tc = float(tx.unit_price or 0)

    if direction == "ars_to_usd":
        ars_broker = conn.execute(
            "SELECT * FROM brokers WHERE user_id=? AND name=?", (uid, tx.broker),
        ).fetchone()
        if not ars_broker:
            raise PersistError(tx.row_index, f"Broker '{tx.broker}' no encontrado.")
        if ars_broker["currency"] != "ARS":
            raise PersistError(tx.row_index, "Una conversión ARS→USD parte de un broker ARS.")
        usd_broker = helpers._ensure_usd_sibling(conn, uid, ars_broker)
        _adjust_cash_permissive(conn, uid, ars_broker["name"], "ARS", -ars_amount)
        _adjust_cash_permissive(conn, uid, usd_broker["name"], "USDT", usd_amount, tc_for_basis=tc)
        # Capital aportado (FIX bug #1 — el FX no escribía monthly_entries): el
        # depósito en pesos se registró al blue (subvaluado vs el MEP al que el
        # usuario realmente convirtió). Corregimos el libro de capital para que
        # refleje los USD efectivamente obtenidos: sacamos la pata ARS a su valor
        # BLUE (cancela lo que sumó el depósito) y metemos la pata USD a valor
        # FACE. Sin esto el "Capital Aportado" queda subvaluado y el return sale
        # fantasma (1M ARS→1000 USD daba capital 706,71 y un +41% irreal). El
        # criterio: valuar el capital a la MISMA tasa que las tenencias (ARS→blue,
        # USD→face), así una conversión no inventa ni P&L ni capital nuevo, solo
        # re-ancla la base a la moneda en que ahora está la plata.
        _y, _m = int(tx.date[:4]), int(tx.date[5:7])
        _ars_as_usd = (ars_amount / tc_blue) if tc_blue else 0.0
        helpers._update_monthly_flow(conn, uid, ars_broker["name"], _y, _m, "withdraw", _ars_as_usd)
        helpers._update_monthly_flow(conn, uid, "global", _y, _m, "withdraw", _ars_as_usd)
        helpers._update_monthly_flow(conn, uid, usd_broker["name"], _y, _m, "deposit", usd_amount)
        helpers._update_monthly_flow(conn, uid, "global", _y, _m, "deposit", usd_amount)
        from_b, from_curr, to_curr = ars_broker["name"], "ARS", "USDT"
        op_pnl_usd = 0.0
        op_pnl_pct = None
        entry_p, exit_p = tc, None
        op_qty = ars_amount
    else:  # usd_to_ars
        usd_broker = conn.execute(
            "SELECT * FROM brokers WHERE user_id=? AND name=?", (uid, tx.broker),
        ).fetchone()
        if not usd_broker:
            raise PersistError(tx.row_index, f"Broker '{tx.broker}' no encontrado.")
        if usd_broker["currency"] != "USDT":
            raise PersistError(tx.row_index, "Una conversión USD→ARS parte de un broker USD.")
        if not usd_broker["parent_broker_id"]:
            raise PersistError(tx.row_index, "El broker USD no tiene padre ARS asociado.")
        ars_broker = conn.execute(
            "SELECT * FROM brokers WHERE id=? AND user_id=?",
            (usd_broker["parent_broker_id"], uid),
        ).fetchone()
        cash_usd = conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
            (uid, usd_broker["name"]),
        ).fetchone()
        tc_avg = (cash_usd["tc_compra"] if cash_usd else None) or tc
        cost_basis_ars = usd_amount * tc_avg
        pnl_ars = ars_amount - cost_basis_ars
        op_pnl_usd = pnl_ars / tc if tc > 0 else 0.0
        op_pnl_pct = (op_pnl_usd / usd_amount * 100) if usd_amount > 0 else None
        _adjust_cash_permissive(conn, uid, usd_broker["name"], "USDT", -usd_amount)
        _adjust_cash_permissive(conn, uid, ars_broker["name"], "ARS", ars_amount)
        from_b, from_curr, to_curr = usd_broker["name"], "USDT", "ARS"
        entry_p, exit_p = tc_avg, tc
        op_qty = usd_amount

    op_type_str = f"CONVERSION IMPORT {from_curr}→{to_curr}"
    cur = conn.execute(
        """INSERT INTO operations
           (user_id, date, broker, asset, op_type, entry_price, exit_price,
            quantity, pnl_usd, pnl_pct, commissions)
           VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
        (uid, tx.date, from_b, f"{from_curr}→{to_curr}", op_type_str,
         entry_p, exit_p, op_qty,
         round(op_pnl_usd, 2),
         round(op_pnl_pct, 4) if op_pnl_pct is not None else None),
    )
    op_id = cur.lastrowid
    _link(conn, batch_id, raw_row_id, operation_id=op_id)

    if direction == "usd_to_ars" and abs(op_pnl_usd) > 1e-6:
        y, m = int(tx.date[:4]), int(tx.date[5:7])
        helpers._update_monthly_pnl_realized(conn, uid, ars_broker["name"], y, m, op_pnl_usd)
        helpers._update_monthly_pnl_realized(conn, uid, "global", y, m, op_pnl_usd)

    return [from_b]


# ─── Linking (para revert) ───────────────────────────────────────────────────

def _link(conn, batch_id: str, raw_row_id: Optional[int], *,
          position_id: Optional[int] = None, operation_id: Optional[int] = None):
    """Registra qué position/operation creó esta fila normalizada — usado para revert."""
    if raw_row_id is None:
        return
    conn.execute(
        """UPDATE import_normalized_tx
              SET created_position_id = COALESCE(created_position_id, ?),
                  created_operation_id = COALESCE(created_operation_id, ?)
            WHERE batch_id=? AND raw_row_id=?""",
        (position_id, operation_id, batch_id, raw_row_id),
    )
    # Para SELL FIFO o múltiples operaciones por fila, además insertamos en
    # un mapping auxiliar para no perder los IDs adicionales.
    if operation_id is not None:
        conn.execute(
            "INSERT INTO import_op_links (batch_id, raw_row_id, operation_id) VALUES (?,?,?)",
            (batch_id, raw_row_id, operation_id),
        )
    if position_id is not None:
        conn.execute(
            "INSERT INTO import_op_links (batch_id, raw_row_id, position_id) VALUES (?,?,?)",
            (batch_id, raw_row_id, position_id),
        )


# ─── Revert ──────────────────────────────────────────────────────────────────

def _backfill_snapshots_from_monthly(conn, uid: int) -> None:
    """Genera snapshots al último día de cada mes a partir de monthly_entries.global.
    Usado tras un import histórico para que el chart "Evolución del portfolio"
    tenga datos para graficar. UPSERT por fecha — no duplica si ya hay snapshot.

    Convención:
      total_value     = capital_final del mes
      total_invested  = cumulative net_deposited (proxy razonable para el chart)
      net_deposited   = Σ (deposits - withdrawals) acumulado hasta el mes
    """
    rows = conn.execute(
        """SELECT year, month, deposits, withdrawals, capital_final
             FROM monthly_entries
            WHERE user_id=? AND broker='global'
            ORDER BY year ASC, month ASC""",
        (uid,),
    ).fetchall()
    if not rows:
        return

    cum_dep = 0.0
    cum_wd = 0.0
    import calendar
    from datetime import date as _date
    for r in rows:
        cum_dep += r["deposits"] or 0
        cum_wd += r["withdrawals"] or 0
        net_dep = cum_dep - cum_wd
        last_day = calendar.monthrange(r["year"], r["month"])[1]
        snap_date = _date(r["year"], r["month"], last_day).isoformat()
        cap_final = r["capital_final"] or 0
        # UPSERT (UNIQUE constraint en (user_id, date) lo permite)
        conn.execute(
            """INSERT INTO snapshots (user_id, date, total_value, total_invested, net_deposited)
               VALUES (?,?,?,?,?)
               ON CONFLICT(user_id, date) DO UPDATE SET
                 total_value = excluded.total_value,
                 total_invested = excluded.total_invested,
                 net_deposited = excluded.net_deposited""",
            (uid, snap_date, cap_final, net_dep, net_dep),
        )


def _read_tc_blue(conn, uid: int) -> float:
    """Blue con el que el persister convierte ARS→USD (cash/monthly_entries) al
    aplicar un batch. Preferimos el blue LIVE (mismo dolarapi que el display) y
    solo caemos al config si el caché está frío. Mismo criterio que
    pipeline._read_user_tc_blue — así el import no depende de un tc_blue guardado
    que en cuentas viejas quedaba stale (~143 de 2021) e inflaba el 'aportado'
    ~10× con pérdida fantasma. Late-import de main para evitar circular."""
    try:
        import main as _main
        live = _main._display_blue(conn, uid)
        if live and float(live) > 0:
            return float(live)
    except Exception:
        pass
    row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (uid,),
    ).fetchone()
    try:
        v = float(row["value"]) if row else 1415.0
        return v if v > 0 else 1415.0
    except (TypeError, ValueError):
        return 1415.0


def revert_batch(conn, *, uid: int, batch_id: str, helpers,
                  nuclear: bool = False) -> Dict[str, Any]:
    """Reversa todos los side-effects de un batch ya confirmado.

    Modos:
    - safe (default): solo reversa BUY/DEPOSIT/WITHDRAW/etc. Si el batch tiene
      SELL/FX/FUTURES_PNL, levanta PersistError pidiendo que se borren a mano.
    - nuclear (`nuclear=True`): además reversa SELL/FX/FUTURES_PNL en best-effort
      reconstruyendo posiciones desde la tabla `operations` y reversando los
      cash/monthly_entries asociados. Acepta drift en tc_compra para FX y
      reconstrucción aproximada del invested original en SELLs.

    Reglas de seguridad:
    - Solo se puede revertir un batch en estado 'confirmed'.
    - Si alguna posición creada por este batch ya fue (parcial o totalmente)
      vendida posteriormente — detectamos esto si el position_id ya no existe
      o su quantity disminuyó comparada con la NormalizedTx — abortamos con
      mensaje claro. El usuario debe deshacer las ventas posteriores primero.
    """
    batch = conn.execute(
        "SELECT * FROM import_batches WHERE id=? AND user_id=?", (batch_id, uid),
    ).fetchone()
    if not batch:
        raise PersistError(0, "Batch no encontrado.")
    if batch["status"] != "confirmed":
        raise PersistError(0, f"Solo se pueden revertir batches confirmados (estado actual: {batch['status']}).")

    # Pre-check 1: si el batch incluye SELL/FX/FUTURES_PNL y NO estamos en
    # modo nuclear, bloqueamos con mensaje claro. En nuclear seguimos.
    blocked_ops = conn.execute(
        """SELECT operation_type, COUNT(*) c
             FROM import_normalized_tx
            WHERE batch_id=? AND operation_type IN ('SELL','FX_ARS_TO_USD','FX_USD_TO_ARS','FUTURES_PNL')
            GROUP BY operation_type""",
        (batch_id,),
    ).fetchall()
    if blocked_ops and not nuclear:
        parts = []
        for r in blocked_ops:
            label = {"SELL": "ventas", "FX_ARS_TO_USD": "conversiones ARS→USD",
                     "FX_USD_TO_ARS": "conversiones USD→ARS",
                     "FUTURES_PNL": "PnL de futuros"}.get(r["operation_type"], r["operation_type"])
            parts.append(f"{r['c']} {label}")
        raise PersistError(0,
            f"Este import incluye {' y '.join(parts)}, que no se pueden revertir "
            f"automáticamente. Las ventas consumieron lotes con FIFO y las conversiones "
            f"modifican el tipo de cambio promedio del cash. Borrá esas operaciones "
            f"manualmente desde Operaciones / Posiciones antes de revertir el resto.")

    links = conn.execute(
        """SELECT l.*, n.operation_type, n.quantity AS normalized_qty
             FROM import_op_links l
             LEFT JOIN import_normalized_tx n
                    ON n.batch_id = l.batch_id AND n.raw_row_id = l.raw_row_id
            WHERE l.batch_id=?""",
        (batch_id,),
    ).fetchall()

    # Pre-check 2: para batches que solo tienen BUY/DEPOSIT, verificar que
    # ninguna posición fue vendida posteriormente (fuera del batch).
    # En modo nuclear este check se relaja: las ventas dentro del MISMO batch
    # son OK (el revert nuclear las deshace recreando los lots), y aceptamos
    # también drift en posiciones tocadas posteriormente. Solo bloqueamos en
    # safe mode.
    if not nuclear:
        for l in links:
            if l["position_id"]:
                pos = conn.execute(
                    "SELECT * FROM positions WHERE id=? AND user_id=?",
                    (l["position_id"], uid),
                ).fetchone()
                if not pos:
                    raise PersistError(0,
                        "No se puede revertir: una posición creada por este import ya no existe "
                        "(probablemente fue vendida en una operación posterior). Deshacé esa venta primero.")
                if not pos["is_cash"] and l["operation_type"] == "BUY":
                    if (pos["quantity"] or 0) < (l["normalized_qty"] or 0) - 1e-9:
                        raise PersistError(0,
                            f"No se puede revertir: la posición {pos['asset']} en {pos['broker']} "
                            f"fue parcialmente vendida después del import. Deshacé esa venta primero.")

    brokers_touched = set()
    tc_blue = _read_tc_blue(conn, uid)

    # Revertir en orden inverso al aplicado
    txs = conn.execute(
        """SELECT * FROM import_normalized_tx
            WHERE batch_id=?
            ORDER BY date DESC, id DESC""",
        (batch_id,),
    ).fetchall()

    for tx in txs:
        brokers_touched.add(tx["broker"])
        op = tx["operation_type"]

        if op == "BUY":
            # Devolver el cash y borrar la position
            invested = (tx["gross_amount"] if tx["gross_amount"] is not None
                        else (tx["unit_price"] or 0) * (tx["quantity"] or 0))
            cost_total = (invested or 0) + (tx["fees"] or 0)
            if tx["created_position_id"]:
                conn.execute(
                    "DELETE FROM positions WHERE id=? AND user_id=? AND is_cash=0",
                    (tx["created_position_id"], uid),
                )
            if cost_total > 0:
                helpers._adjust_broker_cash(conn, uid, tx["broker"], cost_total)

        elif op == "DEPOSIT":
            amount = float(tx["gross_amount"] or 0)
            row_currency = (tx["currency"] or "").upper() if "currency" in tx.keys() else ""
            # Fase 4 (2026-05-30): preferimos gross_amount_usd stamped (USD
            # exacto del momento del persist) → revert restaura monthly_entries
            # con valor IDÉNTICO al que se sumó. Fallback a tc_blue actual para
            # rows legacy sin stamp.
            stamped_usd = tx["gross_amount_usd"] if "gross_amount_usd" in tx.keys() else None
            if stamped_usd is not None:
                amount_usd = float(stamped_usd)
            else:
                broker_row = conn.execute(
                    "SELECT currency FROM brokers WHERE user_id=? AND name=?", (uid, tx["broker"]),
                ).fetchone()
                broker_currency = broker_row["currency"] if broker_row else ""
                amount_usd = (amount / tc_blue) if (row_currency == "ARS" or broker_currency == "ARS") else amount
            # Revertir el cash movement (en moneda nativa del broker).
            # Aceptamos saldo negativo resultante — consistente con la policy
            # del módulo ("se permiten balances negativos — señal visible de
            # overdraft / margen") y con los otros revert paths (BUY, WITHDRAW,
            # DIVIDEND) que no validan. Antes este check bloqueaba reverts
            # legítimos cuando ya se había gastado parte del depósito en BUYs
            # que se revertirán después en este mismo loop.
            cash = conn.execute(
                "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
                (uid, tx["broker"]),
            ).fetchone()
            if cash:
                new_inv = (cash["invested"] or 0) - amount
                conn.execute(
                    "UPDATE positions SET invested=? WHERE id=? AND user_id=?",
                    (new_inv, cash["id"], uid),
                )
            # Bug C fix (2026-05-30): el revert de un DEPOSIT debe RESTAR de
            # `deposits`, no sumar a `withdrawals`. Antes inflaba withdrawals
            # con un movimiento que nunca ocurrió, contaminando el bruto
            # histórico y el Capital Aportado vía monthly_entries.
            # Ahora pasamos amount negativo con la misma dirección ("deposit").
            y, m = int(tx["date"][:4]), int(tx["date"][5:7])
            helpers._update_monthly_flow(conn, uid, tx["broker"], y, m, "deposit", -amount_usd)
            helpers._update_monthly_flow(conn, uid, "global", y, m, "deposit", -amount_usd)

        elif op in ("DIVIDEND", "INTEREST"):
            # Revertir: bajar cash + bajar pnl_realized + borrar la fila de
            # operations (la borra el bloque general al final via import_op_links).
            amount = float(tx["gross_amount"] or 0)
            broker_row = conn.execute(
                "SELECT currency FROM brokers WHERE user_id=? AND name=?", (uid, tx["broker"]),
            ).fetchone()
            broker_currency = broker_row["currency"] if broker_row else ""
            amount_usd = (amount / tc_blue) if broker_currency == "ARS" else amount
            # Cash down
            cash = conn.execute(
                "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
                (uid, tx["broker"]),
            ).fetchone()
            if cash:
                conn.execute(
                    "UPDATE positions SET invested=? WHERE id=? AND user_id=?",
                    ((cash["invested"] or 0) - amount, cash["id"], uid),
                )
            # Bajar pnl_realized (revertir lo que sumó al persistir). SIMÉTRICO
            # con el persist: la amortización-capital-return NUNCA sumó → acá
            # tampoco resta (sin el guard, revertir dejaría pnl_realized en
            # negativo por un profit que jamás se contó).
            if not _is_amort_capital_return(
                    tx["operation_type"], tx["asset_symbol"], tx["asset_type"], tx["notes"]):
                y, m = int(tx["date"][:4]), int(tx["date"][5:7])
                helpers._update_monthly_pnl_realized(conn, uid, tx["broker"], y, m, -amount_usd)
                helpers._update_monthly_pnl_realized(conn, uid, "global", y, m, -amount_usd)

        elif op in ("WITHDRAW", "FEE", "IMPUESTO"):
            amount = float(tx["gross_amount"] or 0)
            row_currency = (tx["currency"] or "").upper() if "currency" in tx.keys() else ""
            # Fase 4: prefer stamped USD (idem DEPOSIT revert).
            stamped_usd = tx["gross_amount_usd"] if "gross_amount_usd" in tx.keys() else None
            if stamped_usd is not None:
                amount_usd = float(stamped_usd)
            else:
                amount_usd = (amount / tc_blue) if row_currency == "ARS" else amount
            helpers._adjust_broker_cash(conn, uid, tx["broker"], amount)
            # Bug C fix (2026-05-30): el revert de un WITHDRAW/FEE debe RESTAR
            # de `withdrawals`, no sumar a `deposits`. Antes inflaba deposits
            # con un movimiento que nunca ocurrió. Ahora pasamos amount
            # negativo con la misma dirección ("withdraw").
            y, m = int(tx["date"][:4]), int(tx["date"][5:7])
            helpers._update_monthly_flow(conn, uid, tx["broker"], y, m, "withdraw", -amount_usd)
            helpers._update_monthly_flow(conn, uid, "global", y, m, "withdraw", -amount_usd)

        elif op == "SELL":
            if not nuclear:
                raise PersistError(0,
                    "Este import contiene ventas que no se pueden revertir automáticamente.")
            # Best-effort: solo deshacemos el cash credit y el monthly_pnl_realized.
            # No recreamos las posiciones consumidas — eso causaría duplicados
            # si la BUY de este mismo batch también se está revirtiendo. El uso
            # típico del nuclear revert es "Editar y rehacer", donde el usuario
            # va a re-importar y las posiciones se recrean desde el preview nuevo.
            # Si el usuario solo quiere revertir (no rehacer), las posiciones
            # consumidas por la SELL quedan ausentes — comportamiento aceptable
            # porque al re-importar se restauran.
            sell_ops = conn.execute(
                """SELECT o.* FROM operations o
                     JOIN import_op_links l ON l.operation_id = o.id
                    WHERE l.batch_id=? AND l.raw_row_id=? AND o.user_id=?""",
                (batch_id, tx["raw_row_id"], uid),
            ).fetchall()
            total_proceeds = 0.0
            total_pnl_usd = 0.0
            for so in sell_ops:
                qty = float(so["quantity"] or 0)
                exit_p = float(so["exit_price"] or 0)
                comm = float(so["commissions"] or 0)
                pnl = float(so["pnl_usd"] or 0)
                total_proceeds += exit_p * qty - comm
                total_pnl_usd += pnl
            if total_proceeds > 0:
                helpers._adjust_broker_cash(conn, uid, tx["broker"], -total_proceeds)
            if abs(total_pnl_usd) > 1e-6:
                y, m = int(tx["date"][:4]), int(tx["date"][5:7])
                helpers._update_monthly_pnl_realized(conn, uid, tx["broker"], y, m, -total_pnl_usd)
                helpers._update_monthly_pnl_realized(conn, uid, "global", y, m, -total_pnl_usd)

        elif op in ("FX_ARS_TO_USD", "FX_USD_TO_ARS"):
            if not nuclear:
                raise PersistError(0,
                    "Este import contiene conversiones de moneda que no se pueden revertir automáticamente.")
            # Reverse el cash en ambas puntas. Aceptamos drift en tc_compra
            # (es un best-effort; el usuario va a re-importar si quiere precisión).
            ars_amount = float(tx["gross_amount"] or 0)
            usd_amount = float(tx["quantity"] or 0)
            ars_broker_name = None
            if op == "FX_ARS_TO_USD":
                # tx.broker era el padre ARS (en el persist no se reasigna).
                # Buscamos el sibling USD para deshacer el credit.
                parent = conn.execute(
                    "SELECT * FROM brokers WHERE name=? AND user_id=?", (tx["broker"], uid),
                ).fetchone()
                if parent:
                    sibling = conn.execute(
                        """SELECT * FROM brokers WHERE parent_broker_id=? AND user_id=? AND currency='USDT'""",
                        (parent["id"], uid),
                    ).fetchone()
                    if usd_amount > 0 and sibling:
                        _adjust_cash_permissive(conn, uid, sibling["name"], "USDT", -usd_amount)
                        brokers_touched.add(sibling["name"])
                    if ars_amount > 0:
                        _adjust_cash_permissive(conn, uid, tx["broker"], "ARS", ars_amount)
                ars_broker_name = tx["broker"]
            else:  # FX_USD_TO_ARS
                # tx.broker era el sibling USD. El padre ARS es el broker que recibió.
                sibling = conn.execute(
                    "SELECT * FROM brokers WHERE name=? AND user_id=?", (tx["broker"], uid),
                ).fetchone()
                if sibling and sibling["parent_broker_id"]:
                    parent = conn.execute(
                        "SELECT * FROM brokers WHERE id=? AND user_id=?",
                        (sibling["parent_broker_id"], uid),
                    ).fetchone()
                    if usd_amount > 0:
                        _adjust_cash_permissive(conn, uid, sibling["name"], "USDT", usd_amount)
                    if ars_amount > 0 and parent:
                        _adjust_cash_permissive(conn, uid, parent["name"], "ARS", -ars_amount)
                        brokers_touched.add(parent["name"])
                        ars_broker_name = parent["name"]
            # Revertir monthly_pnl_realized para FX_USD_TO_ARS (el persist agrega pnl_usd)
            if op == "FX_USD_TO_ARS":
                fx_op = conn.execute(
                    """SELECT o.pnl_usd FROM operations o
                         JOIN import_op_links l ON l.operation_id = o.id
                        WHERE l.batch_id=? AND l.raw_row_id=? AND o.user_id=? LIMIT 1""",
                    (batch_id, tx["raw_row_id"], uid),
                ).fetchone()
                if fx_op and fx_op["pnl_usd"] and ars_broker_name:
                    pnl = float(fx_op["pnl_usd"])
                    if abs(pnl) > 1e-6:
                        y, m = int(tx["date"][:4]), int(tx["date"][5:7])
                        helpers._update_monthly_pnl_realized(conn, uid, ars_broker_name, y, m, -pnl)
                        helpers._update_monthly_pnl_realized(conn, uid, "global", y, m, -pnl)

        elif op == "FUTURES_PNL":
            if not nuclear:
                raise PersistError(0,
                    "Este import contiene PnL de futuros que no se puede revertir automáticamente.")
            pnl = float(tx["gross_amount"] or 0)
            if abs(pnl) > 1e-9:
                # En el persist se sumó pnl al cash y al monthly_pnl. Lo restamos.
                helpers._adjust_broker_cash(conn, uid, tx["broker"], -pnl)
                y, m = int(tx["date"][:4]), int(tx["date"][5:7])
                helpers._update_monthly_pnl_realized(conn, uid, tx["broker"], y, m, -pnl)
                helpers._update_monthly_pnl_realized(conn, uid, "global", y, m, -pnl)

    # Borrar operations creadas (si quedaba alguna — actualmente solo BUYs llegan acá)
    for l in links:
        if l["operation_id"]:
            conn.execute(
                "DELETE FROM operations WHERE id=? AND user_id=?",
                (l["operation_id"], uid),
            )

    # Barrido final de posiciones: borrar cualquier position (no-cash) linkeada al
    # batch que siga existiendo. Cubre el seed lot de ventas FIFO y cualquier lote
    # que no pase por el handler BUY (B3). Las cash positions NO se tocan acá: su
    # balance ya lo revierte el accounting de arriba.
    for l in links:
        if l["position_id"]:
            conn.execute(
                "DELETE FROM positions WHERE id=? AND user_id=? AND is_cash=0",
                (l["position_id"], uid),
            )

    # Marcar el batch como 'reverted' ANTES del repair/recalc. CRÍTICO: el
    # self-heal `_recalc_pnl_realized_from_ops` reconstruye, de forma
    # autoritativa, deposits = imports_CONFIRMED + manual_*. Si el batch
    # siguiera 'confirmed' acá, el recalc volvería a sumar SUS deposits (que el
    # loop de arriba ya restó vía _update_monthly_flow) → deposits huérfanos
    # inflados, capital aportado inflado y "ganancias retiradas" fantasma. Este
    # ordenamiento (status primero) es el root-cause-fix del bug reportado.
    conn.execute(
        "UPDATE import_batches SET status='reverted', reverted_at=datetime('now') WHERE id=? AND user_id=?",
        (batch_id, uid),
    )

    # Repair chain (ya con el batch fuera de los flows confirmados)
    for b in brokers_touched:
        helpers._repair_monthly_chain(conn, uid, b)
    helpers._repair_monthly_chain(conn, uid, "global")

    # Self-heal: recalcular desde fuentes autoritativas (operations + imports
    # confirmados + manual_*). El batch ya está 'reverted' → sus flows quedan
    # excluidos y los deposits que el loop restó NO se re-inflan.
    recalc_fn = getattr(helpers, "_recalc_pnl_realized_from_ops", None)
    if recalc_fn:
        recalc_fn(conn, uid)

    # B1: limpiar snapshots que dejó el import. Sin esto, el chart "Evolución del
    # portfolio" seguía mostrando los puntos del import aun después de revertirlo
    # (queja "quedan datos cargados"). Los cierres de mes se re-backfillean desde
    # monthly_entries ya corregido; PERO los snapshots DIARIOS intermedios (los que
    # el cron guardó día a día entre el import y el revert) no son fin de mes ni hoy
    # → el backfill no los tocaba y quedaban inflados. Fix: purgar TODOS los
    # snapshots desde la fecha más vieja del batch en adelante (diarios + month-ends
    # + hoy), y DESPUÉS re-backfillear los month-ends desde monthly_entries. ORDEN
    # crítico: borrar primero, backfillear después (si no, un revert en un día de
    # cierre borraría el month-end recién recreado y dejaría un hueco permanente).
    batch_dates = [t["date"][:10] for t in txs if t["date"]]
    if batch_dates:
        conn.execute(
            "DELETE FROM snapshots WHERE user_id=? AND date >= ?",
            (uid, min(batch_dates)),
        )
    else:
        # Batch sin fechas (raro) → al menos descartar el intradiario de hoy.
        conn.execute(
            "DELETE FROM snapshots WHERE user_id=? AND date=?",
            (uid, datetime.utcnow().strftime("%Y-%m-%d")),
        )
    _backfill_snapshots_from_monthly(conn, uid)

    return {"reverted": True, "batch_id": batch_id}
