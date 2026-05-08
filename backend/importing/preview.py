"""Genera el resumen estructurado que ve el usuario antes de confirmar.

El preview agrupa por activo/op_type y reporta totales para que el usuario
pueda confirmar visualmente que Rendi entendió bien la historia."""
from __future__ import annotations
from collections import defaultdict
from typing import Dict, List, Any
from .schema import (
    NormalizedTx, RowError,
    OP_BUY, OP_SELL, OP_DEPOSIT, OP_WITHDRAW, OP_DIVIDEND, OP_INTEREST,
    OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS, OP_FEE, OP_TRANSFER, OP_FUTURES_PNL,
)


def _op_label(op: str) -> str:
    return {
        OP_BUY: "Compra",
        OP_SELL: "Venta",
        OP_DEPOSIT: "Depósito",
        OP_WITHDRAW: "Retiro",
        OP_DIVIDEND: "Dividendo",
        OP_INTEREST: "Interés",
        OP_FX_ARS_TO_USD: "Conversión ARS → USD",
        OP_FX_USD_TO_ARS: "Conversión USD → ARS",
        OP_FEE: "Comisión",
        OP_TRANSFER: "Transferencia",
        OP_FUTURES_PNL: "PnL de futuros",
    }.get(op, op)


def build_preview(
    *,
    total_rows: int,
    valid_txs: List[NormalizedTx],
    errors_by_row: Dict[int, List[RowError]],
    parser_format: str,
    file_name: str | None,
    duplicate_of_batch_id: str | None = None,
) -> Dict[str, Any]:
    valid_rows = len(valid_txs)
    invalid_rows = len(errors_by_row)

    # Agrupar por op_type
    by_op_type = defaultdict(int)
    for tx in valid_txs:
        by_op_type[tx.operation_type] += 1

    # Agrupar por activo (solo op_types con activo)
    by_asset = defaultdict(lambda: {"buys": 0, "sells": 0, "buy_qty": 0.0, "sell_qty": 0.0})
    assets_set = set()
    for tx in valid_txs:
        if tx.asset_symbol and tx.operation_type in (OP_BUY, OP_SELL):
            entry = by_asset[tx.asset_symbol]
            assets_set.add(tx.asset_symbol)
            if tx.operation_type == OP_BUY:
                entry["buys"] += 1
                entry["buy_qty"] += tx.quantity or 0
            else:
                entry["sells"] += 1
                entry["sell_qty"] += tx.quantity or 0

    # Detected metadata
    currencies = sorted({tx.currency for tx in valid_txs if tx.currency})
    brokers = sorted({tx.broker for tx in valid_txs})
    dates = sorted({tx.date for tx in valid_txs})
    date_range = {"from": dates[0], "to": dates[-1]} if dates else None

    # Estimación de impacto (no es definitiva — ese es el job del persister)
    impact = {
        "positions_to_create": by_op_type.get(OP_BUY, 0),
        "operations_to_create": (by_op_type.get(OP_SELL, 0)
                                  + by_op_type.get(OP_FX_USD_TO_ARS, 0)
                                  + by_op_type.get(OP_FUTURES_PNL, 0)
                                  + by_op_type.get(OP_DIVIDEND, 0)
                                  + by_op_type.get(OP_INTEREST, 0)),
        "cash_movements": (by_op_type.get(OP_DEPOSIT, 0) + by_op_type.get(OP_WITHDRAW, 0)
                           + by_op_type.get(OP_FEE, 0)),
        "fx_conversions": by_op_type.get(OP_FX_ARS_TO_USD, 0) + by_op_type.get(OP_FX_USD_TO_ARS, 0),
    }

    # Lista plana de errores (frontend la pagina)
    flat_errors: List[Dict[str, Any]] = []
    for ridx in sorted(errors_by_row.keys()):
        for e in errors_by_row[ridx]:
            flat_errors.append(e.to_dict())

    # Lista de filas válidas serializadas (para mostrar tabla)
    rows_preview = []
    for tx in valid_txs:
        rows_preview.append({
            "row_index": tx.row_index,
            "date": tx.date,
            "broker": tx.broker,
            "operation_type": tx.operation_type,
            "operation_label": _op_label(tx.operation_type),
            "asset_symbol": tx.asset_symbol,
            "asset_type": tx.asset_type,
            "quantity": tx.quantity,
            "unit_price": tx.unit_price,
            "gross_amount": tx.gross_amount,
            "fees": tx.fees,
            "currency": tx.currency,
            "notes": tx.notes,
        })

    return {
        "summary": {
            "total_rows": total_rows,
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            "by_operation_type": [
                {"type": k, "label": _op_label(k), "count": v}
                for k, v in sorted(by_op_type.items(), key=lambda kv: -kv[1])
            ],
            "detected_brokers": brokers,
            "detected_currencies": currencies,
            "detected_assets": sorted(assets_set),
            "date_range": date_range,
            "estimated_impact": impact,
        },
        "by_asset": [
            {
                "asset": a,
                "buys": v["buys"], "sells": v["sells"],
                "buy_qty": round(v["buy_qty"], 8),
                "sell_qty": round(v["sell_qty"], 8),
                "net_qty": round(v["buy_qty"] - v["sell_qty"], 8),
            }
            for a, v in sorted(by_asset.items())
        ],
        "rows_preview": rows_preview,
        "errors": flat_errors,
        "parser_format": parser_format,
        "file_name": file_name,
        "duplicate_of_batch_id": duplicate_of_batch_id,
    }
