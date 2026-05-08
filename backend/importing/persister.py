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
    OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS, OP_FEE, OP_FUTURES_PNL,
)
from . import seed as _seed


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
                conn.execute(
                    """INSERT INTO import_normalized_tx
                       (batch_id, raw_row_id, date, broker, operation_type, asset_symbol, asset_name, asset_type,
                        quantity, unit_price, gross_amount, fees, taxes, currency, settlement_currency, notes)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (batch_id, raw_id, st.date, st.broker, st.operation_type,
                     st.asset_symbol, st.asset_name, st.asset_type,
                     st.quantity, st.unit_price, st.gross_amount,
                     st.fees, st.taxes, st.currency, st.settlement_currency, st.notes),
                )
            txs = list(seed_txs) + list(txs)

    # Orden cronológico determinístico — el seed (1 día antes) cae naturalmente
    # primero en este sort.
    sorted_txs = sorted(txs, key=lambda t: (t.date, t.row_index))

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

                elif op in (OP_WITHDRAW, OP_FEE):
                    _persist_cash_out(conn, uid, batch_id, raw_row_id, tx, helpers, tc_blue=tc_blue)
                    counts["cash_movements"] += 1

                elif op == OP_FX_ARS_TO_USD:
                    touched = _persist_fx(conn, uid, batch_id, raw_row_id, tx, helpers,
                                          direction="ars_to_usd")
                    counts["conversions"] += 1
                    brokers_touched.update(touched)

                elif op == OP_FX_USD_TO_ARS:
                    touched = _persist_fx(conn, uid, batch_id, raw_row_id, tx, helpers,
                                          direction="usd_to_ars")
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

    cur = conn.execute(
        """INSERT INTO positions (user_id, broker, asset, is_cash, buy_price, quantity,
           invested, tc_compra, price_override, notes, entry_date, commissions)
           VALUES (?,?,?,0,?,?,?,?,?,?,?,?)""",
        (uid, tx.broker, tx.asset_symbol, unit if unit > 0 else None, qty,
         invested, None, None, tx.notes, tx.date, fees),
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
    # Resolver currency del broker
    br = conn.execute(
        "SELECT currency FROM brokers WHERE name=? AND user_id=?", (tx.broker, uid)
    ).fetchone()
    currency = br["currency"] if br else "USDT"

    positions = conn.execute(
        """SELECT * FROM positions
           WHERE user_id=? AND broker=? AND asset=? AND is_cash=0 AND quantity > 0
           ORDER BY COALESCE(entry_date, '9999-12-31') ASC, id ASC""",
        (uid, tx.broker, tx.asset_symbol),
    ).fetchall()
    total_avail = sum((p["quantity"] or 0) for p in positions)
    qty_to_sell = float(tx.quantity or 0)
    if qty_to_sell > total_avail + 1e-9:
        raise PersistError(tx.row_index,
            f"Stock insuficiente al vender {tx.asset_symbol} en {tx.broker} (disponible: {total_avail:g}).")

    exit_price = float(tx.unit_price or 0)
    sell_commissions = float(tx.fees or 0)
    op_date = tx.date

    remaining = qty_to_sell
    total_pnl_usd = 0.0
    total_pnl_ars_native = 0.0
    total_proceeds_native = 0.0
    ops_created: List[int] = []

    # TC efectivo de venta para brokers ARS (USD para ARS no aplica)
    tc_venta = tc_blue if currency == "ARS" else 1.0

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
        entry_invested = base_invested * ratio if base_invested else None

        chunk_commission = sell_commissions * (take / qty_to_sell) if qty_to_sell else 0

        if currency == "ARS":
            # Mismo modelo que el flow manual con FX-phantom-fix:
            # cost basis y venta se valúan al MISMO TC (el de venta).
            pnl_ars_chunk = exit_price * take - (entry_invested or 0) - chunk_commission
            pnl_usd = pnl_ars_chunk / tc_venta if tc_venta else 0
            invested_usd = (entry_invested or 0) / tc_venta if entry_invested and tc_venta else 0
            total_pnl_ars_native += pnl_ars_chunk
        else:
            cost = entry_invested if entry_invested is not None else ((p["buy_price"] or 0) * take)
            pnl_usd = (exit_price * take) - cost - chunk_commission
            invested_usd = cost

        total_pnl_usd += pnl_usd
        total_proceeds_native += exit_price * take - chunk_commission
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


def _persist_dividend_or_interest(conn, uid, batch_id, raw_row_id, tx: NormalizedTx,
                                    helpers, tc_blue: float):
    """Dividendo / Interés → cash up + fila en operations + pnl_realized.

    A diferencia de DEPOSIT (que cuenta como capital aportado), el dividendo
    y el interés son retorno SOBRE el portfolio — entran como ganancia
    realizada (pnl_realized), aparecen en /operaciones para que el usuario
    vea historia, y suben el cash igual que un deposit.

    En operations:
        op_type = "Dividendo" o "Interés"
        asset   = el ticker que pagó (VOO, AL30, etc — puede ser NULL)
        quantity = el monto (en moneda nativa del broker)
        pnl_usd = el monto convertido a USD si el broker es ARS
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

    # 2. Insertar fila en operations
    op_label = "Dividendo" if tx.operation_type == OP_DIVIDEND else "Interés"
    amount_usd = (amount / tc_blue) if currency == "ARS" else amount
    cur = conn.execute(
        """INSERT INTO operations (user_id, date, broker, asset, op_type,
           entry_price, exit_price, quantity, pnl_usd, pnl_pct, commissions)
           VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
        (uid, tx.date, tx.broker, tx.asset_symbol or "—", op_label,
         None, None, round(amount, 4),
         round(amount_usd, 2), None),
    )
    op_id = cur.lastrowid
    _link(conn, batch_id, raw_row_id, operation_id=op_id)

    # 3. monthly_pnl_realized (en USD — convención de monthly_entries)
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


def _persist_fx(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers, *, direction: str):
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
    """Lee tc_blue de la config del usuario, default 1415.0 si falta o es inválido."""
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
            # Convertir a USD para revertir monthly_flow (mismo TC que persist)
            broker_row = conn.execute(
                "SELECT currency FROM brokers WHERE user_id=? AND name=?", (uid, tx["broker"]),
            ).fetchone()
            broker_currency = broker_row["currency"] if broker_row else ""
            amount_usd = (amount / tc_blue) if (row_currency == "ARS" or broker_currency == "ARS") else amount
            # Revertir el cash movement (en moneda nativa del broker)
            cash = conn.execute(
                "SELECT * FROM positions WHERE user_id=? AND broker=? AND is_cash=1 LIMIT 1",
                (uid, tx["broker"]),
            ).fetchone()
            if cash:
                new_inv = (cash["invested"] or 0) - amount
                if new_inv < 0:
                    raise PersistError(0, f"No alcanza el cash en {tx['broker']} para revertir el depósito.")
                conn.execute(
                    "UPDATE positions SET invested=? WHERE id=? AND user_id=?",
                    (new_inv, cash["id"], uid),
                )
            y, m = int(tx["date"][:4]), int(tx["date"][5:7])
            helpers._update_monthly_flow(conn, uid, tx["broker"], y, m, "withdraw", amount_usd)
            helpers._update_monthly_flow(conn, uid, "global", y, m, "withdraw", amount_usd)

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
            # Bajar pnl_realized (revertir lo que sumó al persistir)
            y, m = int(tx["date"][:4]), int(tx["date"][5:7])
            helpers._update_monthly_pnl_realized(conn, uid, tx["broker"], y, m, -amount_usd)
            helpers._update_monthly_pnl_realized(conn, uid, "global", y, m, -amount_usd)

        elif op in ("WITHDRAW", "FEE"):
            amount = float(tx["gross_amount"] or 0)
            row_currency = (tx["currency"] or "").upper() if "currency" in tx.keys() else ""
            amount_usd = (amount / tc_blue) if row_currency == "ARS" else amount
            helpers._adjust_broker_cash(conn, uid, tx["broker"], amount)
            y, m = int(tx["date"][:4]), int(tx["date"][5:7])
            helpers._update_monthly_flow(conn, uid, tx["broker"], y, m, "deposit", amount_usd)
            helpers._update_monthly_flow(conn, uid, "global", y, m, "deposit", amount_usd)

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

    # Repair chain
    for b in brokers_touched:
        helpers._repair_monthly_chain(conn, uid, b)
    helpers._repair_monthly_chain(conn, uid, "global")

    conn.execute(
        "UPDATE import_batches SET status='reverted', reverted_at=datetime('now') WHERE id=? AND user_id=?",
        (batch_id, uid),
    )
    return {"reverted": True, "batch_id": batch_id}
