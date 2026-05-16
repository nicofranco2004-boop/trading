"""builders.operation_trade — packet de UNA operación cerrada individual.
═══════════════════════════════════════════════════════════════════════════
Topic: operations.trade

Análisis de un trade específico del historial. Params:
  operation_id: int   — ID de la fila en operations

El packet trae el trade + estadísticas comparativas del propio user
para que el LLM contextualice: este trade vs su avg_win/avg_loss, vs
su mejor/peor histórico, vs su holding period típico.

Shape (~700 bytes):
{
  "screen": "operations.trade",
  "trade": {
    "id", "date", "ticker", "broker", "op_type",
    "entry_price", "exit_price", "quantity", "pnl_usd", "pnl_pct",
    "holding_days" | null,
  },
  "user_context": {
    "avg_win_usd", "avg_loss_usd", "payoff_ratio",
    "rank_in_year": int | null,         # "este fue el N-ésimo más grande del año"
    "vs_avg_win_multiplier": float | null,  # pnl/avg_win (cuántas veces el promedio)
  },
}
"""
from __future__ import annotations
from typing import Dict, Any
from datetime import datetime


def _is_trade(op: Dict[str, Any]) -> bool:
    op_type = (op.get("op_type") or "").strip()
    if op_type in ("Compra", "Dividendo", "Interés", ""):
        return False
    if op_type.startswith(("CONVERSION", "Conversión")):
        return False
    return op.get("pnl_usd") is not None


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    op_id = kwargs.get("operation_id") or kwargs.get("id")
    if op_id is None:
        raise ValueError("Falta param 'operation_id' (id de la operación).")
    try:
        op_id = int(op_id)
    except (TypeError, ValueError):
        raise ValueError("operation_id debe ser entero.")

    row = conn.execute(
        """SELECT id, date, asset, broker, op_type, entry_price, exit_price,
                  quantity, pnl_usd, pnl_pct, entry_date
             FROM operations
            WHERE id = ? AND user_id = ?""",
        (op_id, user_id),
    ).fetchone()
    if not row:
        raise ValueError(f"Operación {op_id} no encontrada.")
    op = dict(row)
    if not _is_trade(op):
        raise ValueError(
            f"Operación {op_id} no es un trade cerrado (tipo: {op.get('op_type')})."
        )

    # Holding days
    holding_days = None
    try:
        if op.get("entry_date") and op.get("date"):
            ed = datetime.fromisoformat(str(op["entry_date"])[:10]).date()
            xd = datetime.fromisoformat(str(op["date"])[:10]).date()
            holding_days = max(0, (xd - ed).days)
    except (TypeError, ValueError):
        holding_days = None

    pnl = float(op.get("pnl_usd") or 0)

    # Reusamos el builder de operations general para tener stats del user
    user_context: Dict[str, Any] = {}
    try:
        from .operations import build as build_ops
        ops_packet = build_ops(conn, user_id)
        avg_win = ops_packet.get("avg_win_usd")
        avg_loss = ops_packet.get("avg_loss_usd")
        user_context = {
            "avg_win_usd": avg_win,
            "avg_loss_usd": avg_loss,
            "payoff_ratio": ops_packet.get("payoff_ratio"),
            "vs_avg_win_multiplier": (
                round(pnl / avg_win, 2) if (avg_win and pnl > 0) else None
            ),
            "vs_avg_loss_multiplier": (
                round(abs(pnl) / abs(avg_loss), 2) if (avg_loss and pnl < 0) else None
            ),
        }
    except Exception:
        user_context = {}

    # Rank en el año del trade — cuál puesto ocupa este P&L vs los demás del año
    rank_in_year = None
    try:
        year_str = str(op.get("date") or "")[:4]
        if year_str.isdigit():
            year_rows = conn.execute(
                """SELECT pnl_usd FROM operations
                    WHERE user_id = ? AND pnl_usd IS NOT NULL
                      AND substr(date, 1, 4) = ?
                      AND op_type NOT IN ('Compra', 'Dividendo', 'Interés', '')
                      AND op_type NOT LIKE 'CONVERSION%'
                      AND op_type NOT LIKE 'Conversión%'""",
                (user_id, year_str),
            ).fetchall()
            year_pnls = sorted(
                [float(r["pnl_usd"] or 0) for r in year_rows],
                reverse=True,
            )
            if pnl in year_pnls:
                rank_in_year = year_pnls.index(pnl) + 1
            user_context["year_total_trades"] = len(year_pnls)
    except Exception:
        rank_in_year = None
    user_context["rank_in_year"] = rank_in_year

    return {
        "screen": "operations.trade",
        "trade": {
            "id": op_id,
            "date": str(op.get("date") or "")[:10],
            "ticker": (op.get("asset") or "").upper(),
            "broker": op.get("broker"),
            "op_type": op.get("op_type"),
            "entry_price": round(float(op.get("entry_price") or 0), 4),
            "exit_price": round(float(op.get("exit_price") or 0), 4) if op.get("exit_price") else None,
            "quantity": round(float(op.get("quantity") or 0), 6),
            "pnl_usd": round(pnl, 2),
            "pnl_pct": round(float(op.get("pnl_pct") or 0), 2) if op.get("pnl_pct") is not None else None,
            "holding_days": holding_days,
        },
        "user_context": user_context,
    }
