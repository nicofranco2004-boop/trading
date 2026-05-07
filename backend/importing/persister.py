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
    OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS, OP_FEE,
)


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
) -> Dict[str, Any]:
    """Aplica todas las txs en orden cronológico. Devuelve resumen.
    El caller debe haber abierto `with conn:`. Si esta función levanta,
    SQLite hace rollback automático.
    """
    # Orden cronológico determinístico
    sorted_txs = sorted(txs, key=lambda t: (t.date, t.row_index))

    # Currency routing: si el batch tiene route_by_currency=1 y el broker
    # principal es ARS, las filas con moneda USD/USDT van al sub-broker USD.
    # El sub-broker se crea on-demand. Esto se aplica ANTES de procesar las
    # txs para que las downstream queries (FIFO, cash) usen el broker correcto.
    batch_row = conn.execute(
        "SELECT broker, route_by_currency FROM import_batches WHERE id=? AND user_id=?",
        (batch_id, uid),
    ).fetchone()
    route_currency = bool(batch_row and (batch_row["route_by_currency"] or 0))
    sibling_name: Optional[str] = None
    if route_currency:
        parent = conn.execute(
            "SELECT * FROM brokers WHERE name=? AND user_id=?",
            (batch_row["broker"], uid),
        ).fetchone()
        if parent and parent["currency"] == "ARS":
            sibling = helpers._ensure_usd_sibling(conn, uid, parent)
            sibling_name = sibling["name"]
            for tx in sorted_txs:
                cur = (tx.currency or "").upper()
                op = tx.operation_type
                # FX: siempre ruteamos al broker correcto según la dirección,
                # ignorando la columna 'currency' (que para FX es ambigua —
                # el usuario puede ponerla ARS o USD según prefiera).
                if op == "FX_ARS_TO_USD":
                    # Compra de USD pagando ARS → fuente es el padre ARS
                    if tx.broker == sibling_name:
                        tx.broker = parent["name"]
                elif op == "FX_USD_TO_ARS":
                    # Venta de USD recibiendo ARS → fuente es el sibling USD
                    if tx.broker == parent["name"]:
                        tx.broker = sibling_name
                # Resto: rutear por moneda de la fila
                elif cur in ("USD", "USDT") and tx.broker == parent["name"]:
                    tx.broker = sibling_name

    brokers_touched: set = set()
    counts = {"positions": 0, "operations": 0, "cash_movements": 0, "conversions": 0}

    for tx in sorted_txs:
        raw_row_id = raw_row_ids_by_index.get(tx.row_index)
        broker = tx.broker
        brokers_touched.add(broker)

        op = tx.operation_type
        try:
            if op == OP_BUY:
                _persist_buy(conn, uid, batch_id, raw_row_id, tx, helpers)
                counts["positions"] += 1

            elif op == OP_SELL:
                created_op_ids = _persist_sell_fifo(conn, uid, batch_id, raw_row_id, tx, helpers)
                counts["operations"] += len(created_op_ids)

            elif op in (OP_DEPOSIT, OP_DIVIDEND, OP_INTEREST):
                _persist_cash_in(conn, uid, batch_id, raw_row_id, tx, helpers)
                counts["cash_movements"] += 1

            elif op in (OP_WITHDRAW, OP_FEE):
                _persist_cash_out(conn, uid, batch_id, raw_row_id, tx, helpers)
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

            else:
                # OP_TRANSFER no debería llegar acá (filtrado por validator)
                raise PersistError(tx.row_index, f"Tipo de operación no soportado: {op}")

        except PersistError:
            raise
        except Exception as ex:
            raise PersistError(tx.row_index, f"Error al persistir fila {tx.row_index}: {ex}")

    # Repair chain una sola vez por broker tocado + global
    for b in brokers_touched:
        helpers._repair_monthly_chain(conn, uid, b)
    helpers._repair_monthly_chain(conn, uid, "global")

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


def _persist_sell_fifo(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers) -> List[int]:
    """Venta FIFO. Replica la lógica de sell_position_fifo en main.py.
    Como no tenemos `tc_venta` en el CSV genérico, usamos 1 cuando el broker es
    USDT (no aplica) y la moneda native del broker para ARS — el persister
    usa una aproximación simple: para ARS, exigimos que la moneda de la fila
    sea ARS y registramos PnL en ARS dividido por unit_price (sin TC sintético).
    Para MVP solo soportamos venta de assets en brokers USDT (precio en USD).
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

    # Si el broker es ARS, necesitamos un TC para convertir a USD-equivalente.
    # Como no tenemos tc_venta en el CSV: usar 1 si la moneda de la fila es USD
    # (broker USD), o levantar error explícito si broker es ARS sin TC. MVP:
    # para brokers ARS exigimos que el CSV traiga moneda='ARS' y persistimos
    # PnL en ARS divididos por exit_price-implied-tc=1 → eso da números raros.
    # Solución pragmática: para brokers ARS, requerimos que la fila traiga 'tc'
    # en el campo notes? No. Mejor: documentar que el MVP solo soporta venta
    # FIFO en brokers USD; para ARS el usuario debe usar el flow manual.
    if currency == "ARS":
        raise PersistError(tx.row_index,
            "Las ventas en brokers ARS aún no se importan automáticamente. "
            "Usá la página Posiciones → Vender por ahora. "
            "Las compras ARS sí se importan.")

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
    helpers._update_monthly_pnl_realized(conn, uid, tx.broker, op_year, op_month, total_pnl_usd)
    helpers._update_monthly_pnl_realized(conn, uid, "global", op_year, op_month, total_pnl_usd)

    return ops_created


def _persist_cash_in(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers):
    """Depósito / Dividendo / Interés → suma cash al broker, registra monthly flow."""
    _apply_cash_flow(conn, uid, batch_id, raw_row_id, tx, helpers, sign=+1)


def _persist_cash_out(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers):
    """Retiro / Comisión aislada → resta cash, registra monthly flow."""
    _apply_cash_flow(conn, uid, batch_id, raw_row_id, tx, helpers, sign=-1)


def _apply_cash_flow(conn, uid, batch_id, raw_row_id, tx: NormalizedTx, helpers, sign: int):
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
        if new_invested < 0:
            raise PersistError(tx.row_index,
                f"Saldo insuficiente al aplicar fila. Disponible: {cash_pos['invested'] or 0:.2f} {currency}.")
        conn.execute(
            "UPDATE positions SET invested=? WHERE id=? AND user_id=?",
            (new_invested, cash_pos["id"], uid),
        )
        cash_pos_id = cash_pos["id"]
    else:
        if sign < 0:
            raise PersistError(tx.row_index, f"No hay posición cash en {tx.broker} para debitar.")
        asset_name = "ARS" if currency == "ARS" else "USDT"
        cur = conn.execute(
            """INSERT INTO positions (user_id, broker, asset, is_cash, invested)
               VALUES (?,?,?,1,?)""",
            (uid, tx.broker, asset_name, amount),
        )
        cash_pos_id = cur.lastrowid

    # Monthly flow: convertir ARS → USD si el broker es ARS. Sin TC del CSV,
    # usamos 1 como aproximación (mismo dato persistido para broker y global).
    # NOTA: el endpoint manual usa data.tc_blue. En import, si la fila trae
    # 'tc' en notas o columna tc, lo respetamos. MVP: amount_usd = amount si
    # USD, sino se loguea como warning (los monthly_entries ARS quedan en USDT
    # con esta aproximación — el usuario puede ajustar).
    amount_usd = amount if currency != "ARS" else amount  # aproximación
    direction = "deposit" if sign > 0 else "withdraw"
    year, month = int(tx.date[:4]), int(tx.date[5:7])
    helpers._update_monthly_flow(conn, uid, tx.broker, year, month, direction, amount_usd)
    helpers._update_monthly_flow(conn, uid, "global", year, month, direction, amount_usd)

    _link(conn, batch_id, raw_row_id, position_id=cash_pos_id)


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
        helpers._adjust_cash(conn, uid, ars_broker["name"], "ARS", -ars_amount)
        helpers._adjust_cash(conn, uid, usd_broker["name"], "USDT", usd_amount, tc_for_basis=tc)
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
        helpers._adjust_cash(conn, uid, usd_broker["name"], "USDT", -usd_amount)
        helpers._adjust_cash(conn, uid, ars_broker["name"], "ARS", ars_amount)
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

def revert_batch(conn, *, uid: int, batch_id: str, helpers) -> Dict[str, Any]:
    """Reversa todos los side-effects de un batch ya confirmado.

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

    links = conn.execute(
        """SELECT l.*, n.operation_type, n.quantity AS normalized_qty
             FROM import_op_links l
             LEFT JOIN import_normalized_tx n
                    ON n.batch_id = l.batch_id AND n.raw_row_id = l.raw_row_id
            WHERE l.batch_id=?""",
        (batch_id,),
    ).fetchall()

    # Pre-check: ninguna posición creada por este batch puede haber sido vendida
    for l in links:
        if l["position_id"]:
            pos = conn.execute(
                "SELECT * FROM positions WHERE id=? AND user_id=?",
                (l["position_id"], uid),
            ).fetchone()
            if not pos:
                raise PersistError(0,
                    "No se puede revertir: una posición creada por este import ya no existe (probablemente fue vendida). "
                    "Deshacé las ventas posteriores primero.")
            # is_cash: la posición cash no se borra sino que se ajusta — skip
            if not pos["is_cash"] and l["operation_type"] == "BUY":
                if (pos["quantity"] or 0) < (l["normalized_qty"] or 0) - 1e-9:
                    raise PersistError(0,
                        f"No se puede revertir: la posición {pos['asset']} en {pos['broker']} "
                        f"fue parcialmente vendida después del import.")

    brokers_touched = set()

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

        elif op in ("DEPOSIT", "DIVIDEND", "INTEREST"):
            amount = float(tx["gross_amount"] or 0)
            # Reverse el cash movement
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
            helpers._update_monthly_flow(conn, uid, tx["broker"], y, m, "withdraw", amount)
            helpers._update_monthly_flow(conn, uid, "global", y, m, "withdraw", amount)

        elif op in ("WITHDRAW", "FEE"):
            amount = float(tx["gross_amount"] or 0)
            helpers._adjust_broker_cash(conn, uid, tx["broker"], amount)
            y, m = int(tx["date"][:4]), int(tx["date"][5:7])
            helpers._update_monthly_flow(conn, uid, tx["broker"], y, m, "deposit", amount)
            helpers._update_monthly_flow(conn, uid, "global", y, m, "deposit", amount)

        elif op in ("SELL", "FX_ARS_TO_USD", "FX_USD_TO_ARS"):
            # MVP: ventas y conversiones no son revertibles automáticamente.
            # Las ventas reabrirían posiciones consumidas; las conversiones
            # tienen P&L cambiario que requeriría recalcular tc_compra promedio.
            raise PersistError(0,
                "Este import contiene ventas o conversiones de moneda que no se pueden revertir "
                "automáticamente. Por seguridad, los reverts se permiten solo cuando el import "
                "no incluye ventas ni FX. Eliminá las operaciones manualmente desde la página correspondiente.")

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
