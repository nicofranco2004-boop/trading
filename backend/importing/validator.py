"""Validación semántica determinística de NormalizedTx.

Reglas:
- Broker debe existir entre los del usuario.
- Por op_type se exigen los campos correspondientes.
- Cantidades positivas (excepto fees que pueden ser 0).
- En SELL: chequea que haya stock suficiente al momento de la operación,
  considerando compras *previas* del mismo CSV (orden cronológico) y la
  posición actual del usuario.

La validación NO toca la base; solo lee el estado actual del usuario para
los chequeos que lo requieren (broker existe, stock disponible).
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from .schema import (
    NormalizedTx, RowError,
    OP_BUY, OP_SELL, OP_DEPOSIT, OP_WITHDRAW, OP_DIVIDEND, OP_INTEREST,
    OP_TRANSFER, OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS, OP_FEE, OP_FUTURES_PNL,
)


def _ge_zero(v: Optional[float]) -> bool:
    return v is not None and v >= 0


def _gt_zero(v: Optional[float]) -> bool:
    return v is not None and v > 0


def validate(
    txs: List[NormalizedTx],
    *,
    user_brokers: Dict[str, dict],          # name → {id, currency, parent_broker_id}
    existing_positions: Dict[Tuple[str, str], float],  # (broker, asset) → qty actual
    route_by_currency: bool = False,        # si True, omitimos chequeos de broker-currency
                                              # para FX (el persister rerutea al broker correcto)
) -> Tuple[List[NormalizedTx], List[RowError]]:
    """Devuelve (válidas, errores). Las inválidas se descartan del output."""
    errors: List[RowError] = []
    valid: List[NormalizedTx] = []

    # Estado simulado para evaluar SELL contra compras previas del mismo CSV.
    # Procesamos en orden cronológico (date, row_index) para que las ventas vean
    # las compras anteriores, sin importar el orden original del CSV.
    sim_qty: Dict[Tuple[str, str], float] = dict(existing_positions)

    sorted_txs = sorted(txs, key=lambda t: (t.date, t.row_index))

    for tx in sorted_txs:
        ridx = tx.row_index
        row_errs: List[RowError] = []

        # Broker debe existir
        if tx.broker not in user_brokers:
            row_errs.append(RowError(ridx, "broker", "UNKNOWN_BROKER",
                                     f"El broker '{tx.broker}' no existe. Creálo en Configuración → Brokers, o "
                                     f"corregí el nombre en el wizard (modo 'Mezcla de brokers' lo crea automáticamente)."))

        broker_currency = (user_brokers.get(tx.broker) or {}).get("currency")

        op = tx.operation_type
        if op == OP_BUY:
            if not tx.asset_symbol:
                row_errs.append(RowError(ridx, "activo", "MISSING_ASSET",
                                         "La compra necesita un activo (ticker en columna 'activo')."))
            if not _gt_zero(tx.quantity):
                row_errs.append(RowError(ridx, "cantidad", "MISSING_QUANTITY",
                                         "La compra necesita una cantidad mayor a 0. Si tu CSV solo tiene 'monto' "
                                         "sin desglosar cantidad y precio, completá precio para que lo calculemos."))
            if not _gt_zero(tx.unit_price) and not _gt_zero(tx.gross_amount):
                row_errs.append(RowError(ridx, "precio", "MISSING_PRICE",
                                         "La compra necesita 'precio' o 'monto' para calcular el costo. "
                                         "Mapeá una de las dos columnas en el wizard."))

        elif op == OP_SELL:
            if not tx.asset_symbol:
                row_errs.append(RowError(ridx, "activo", "MISSING_ASSET",
                                         "La venta necesita un activo (ticker en columna 'activo')."))
            if not _gt_zero(tx.quantity):
                row_errs.append(RowError(ridx, "cantidad", "MISSING_QUANTITY", "La venta necesita una cantidad mayor a 0."))
            # El normalizer ya intentó autocompletar precio si vino monto + cantidad.
            # Si igual falta, exigir uno u otro.
            if not _gt_zero(tx.unit_price) and not _gt_zero(tx.gross_amount):
                row_errs.append(RowError(ridx, "precio", "MISSING_PRICE",
                                         "La venta necesita 'precio' o 'monto' para calcular el resultado. "
                                         "Mapeá una de las dos columnas en el wizard."))

        elif op in (OP_DEPOSIT, OP_WITHDRAW):
            if not _gt_zero(tx.gross_amount):
                op_label = "El depósito" if op == OP_DEPOSIT else "El retiro"
                row_errs.append(RowError(ridx, "monto", "MISSING_AMOUNT",
                                         f"{op_label} necesita 'monto' mayor a 0. Verificá que la columna de "
                                         f"cash (Amount/Net Amount/Importe) esté mapeada al campo 'monto' en el wizard."))

        elif op in (OP_DIVIDEND, OP_INTEREST):
            if not _gt_zero(tx.gross_amount):
                row_errs.append(RowError(ridx, "monto", "MISSING_AMOUNT",
                                         "El dividendo / interés necesita 'monto' mayor a 0. "
                                         "Mapeá la columna de monto en el wizard."))

        elif op in (OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS):
            # Tras el normalizer: gross_amount=ARS, quantity=USD, unit_price=TC
            if not _gt_zero(tx.gross_amount) or not _gt_zero(tx.quantity) or not _gt_zero(tx.unit_price):
                row_errs.append(RowError(ridx, None, "INVALID_FX",
                                         "La conversión necesita 'monto' (ARS), 'monto_usd' y 'tc' positivos."))
            # Chequeos de broker-currency: solo aplican si NO hay ruteo. Con ruteo
            # activo, el persister mueve la fila al broker correcto antes de persistir.
            if not route_by_currency:
                if op == OP_FX_ARS_TO_USD and broker_currency and broker_currency != "ARS":
                    row_errs.append(RowError(ridx, "broker", "FX_BROKER_MISMATCH",
                                             "Una conversión ARS→USD debe partir de un broker ARS."))
                if op == OP_FX_USD_TO_ARS and broker_currency and broker_currency != "USDT":
                    row_errs.append(RowError(ridx, "broker", "FX_BROKER_MISMATCH",
                                             "Una conversión USD→ARS debe partir de un broker USD."))

        elif op == OP_TRANSFER:
            row_errs.append(RowError(ridx, "tipo", "TRANSFER_NOT_SUPPORTED",
                                     "Transferencia ambigua (Wire Transfer / ACAT / Journal sin signo de monto claro). "
                                     "Si era un ingreso o egreso, agregale signo al monto en el CSV (positivo = depósito, "
                                     "negativo = retiro), o cambiá el tipo a DEPOSITO/RETIRO antes de importar."))

        elif op == OP_FEE:
            if not _gt_zero(tx.gross_amount):
                row_errs.append(RowError(ridx, "monto", "MISSING_AMOUNT",
                                         "Una comisión aislada necesita 'monto' mayor a 0."))

        elif op == OP_FUTURES_PNL:
            # PnL puede ser positivo o negativo. Solo exigimos que no sea 0.
            if tx.gross_amount is None or abs(tx.gross_amount) < 1e-9:
                row_errs.append(RowError(ridx, "monto", "MISSING_AMOUNT",
                                         "El PnL de futuros necesita un 'monto' (positivo o negativo)."))

        # Validación cruzada para SELL: hay stock suficiente?
        if op == OP_SELL and not row_errs:
            key = (tx.broker, tx.asset_symbol or "")
            available = sim_qty.get(key, 0.0)
            if (tx.quantity or 0) > available + 1e-9:
                row_errs.append(RowError(
                    ridx, "cantidad", "INSUFFICIENT_STOCK",
                    f"No hay suficiente stock de {tx.asset_symbol} en {tx.broker} para esta venta. "
                    f"Disponible al {tx.date}: {available:g}, querés vender: {tx.quantity:g}. "
                    f"Si tu CSV no incluye las compras previas, cargá el estado inicial al ver la vista previa.",
                ))

        if row_errs:
            errors.extend(row_errs)
            continue

        # Update simulación de stock
        if op == OP_BUY:
            key = (tx.broker, tx.asset_symbol or "")
            sim_qty[key] = sim_qty.get(key, 0.0) + (tx.quantity or 0)
        elif op == OP_SELL:
            key = (tx.broker, tx.asset_symbol or "")
            sim_qty[key] = sim_qty.get(key, 0.0) - (tx.quantity or 0)

        valid.append(tx)

    # Devolver en el orden original (row_index) para que el preview sea predecible
    valid.sort(key=lambda t: t.row_index)
    return valid, errors
