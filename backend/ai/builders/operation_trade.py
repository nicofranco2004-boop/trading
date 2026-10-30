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


from realized_pnl import is_closed_op, realized_usd_sql, closed_filter_sql, pct_creible


def _is_trade(op: Dict[str, Any]) -> bool:
    # Criterio único en realized_pnl (era otra copia a mano).
    return is_closed_op(op.get("op_type")) and op.get("pnl_usd") is not None


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    op_id = kwargs.get("operation_id") or kwargs.get("id")
    if op_id is None:
        raise ValueError("Falta param 'operation_id' (id de la operación).")
    try:
        op_id = int(op_id)
    except (TypeError, ValueError):
        raise ValueError("operation_id debe ser entero.")

    # `pnl_usd` convertido en el SELECT (moneda del broker en Cupón/Amortización).
    # Tiene que salir de la MISMA expresión que la lista del año de más abajo:
    # el rank se calcula con `year_pnls.index(pnl)`, o sea igualdad exacta de
    # floats — si un lado se convierte en SQL y el otro en Python, el rank queda
    # en None sin que nadie se entere. Ver backend/realized_pnl.py.
    row = conn.execute(
        f"""SELECT id, date, asset, broker, op_type, entry_price, exit_price,
                  quantity, {realized_usd_sql()} AS pnl_usd, pnl_pct, entry_date,
                  currency, fx_to_usd, cobrado_ars, costo_ars, costo_moneda,
                  pnl_pct_ars, pnl_pct_usd, pnl_sin_dato
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
            # Misma expresión que el SELECT de la operación de arriba, para que
            # el `index(pnl)` de abajo compare valores producidos igual.
            year_rows = conn.execute(
                f"""SELECT {realized_usd_sql()} AS pnl_usd FROM operations
                    WHERE user_id = ? AND pnl_usd IS NOT NULL
                      AND substr(date, 1, 4) = ?
                      AND {closed_filter_sql()}""",
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

    # La moneda de la venta (la de la fila o la del broker): los precios están en ELLA y
    # pnl_usd en dólares, así que el % se da en las dos monedas y no uno solo sin decir cuál.
    import resultado_dual as _rd
    moneda = _rd.moneda_de_la_venta(conn, user_id, op) if _rd.es_venta_de_un_lote(op) else None
    pct_ars, pct_usd = _rd.pcts_de_la_venta(op, moneda) if moneda else (None, None)
    # La cuenta única del resultado en pesos (la de Operaciones, Reportes y el Resumen mensual).
    resultado_ars = _rd.resultado_en_pesos(op)[0] if _rd.es_venta_de_un_lote(op) else None
    _r2 = lambda v: round(v, 2) if v is not None else None  # noqa: E731

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
            # Techo de credibilidad: ver realized_pnl.pct_creible.
            "pnl_pct": (lambda v: round(v, 2) if v is not None else None)(
                pct_creible(op.get("pnl_pct"))),
            "sale_currency": moneda,
            "pnl_pct_ars": _r2(pct_creible(pct_ars)),
            "pnl_pct_usd": _r2(pct_creible(pct_usd)),
            "result_ars": resultado_ars,
            "holding_days": holding_days,
        },
        "user_context": user_context,
    }
