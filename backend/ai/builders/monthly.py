"""builders.monthly — packet de un mes específico de Reportes.
═══════════════════════════════════════════════════════════════════════════
Topic: monthly

Reusa build_period_report (mismo cálculo que usa el endpoint público
/api/reports/period/...) para mantener coherencia con lo que ve el user
en la timeline. Adelgaza para el LLM: sin children (semanas) y sin
todos los campos del Pydantic — solo lo necesario para narrar.

Params:
  year: int — 2025, 2026, etc.
  month: int — 1..12

Shape (~1KB):
{
  "screen": "monthly",
  "period": {"year": int, "month": int, "label": str},
  "is_current": bool,           # mes en curso (parcial)
  "is_relevant": bool,           # tuvo actividad
  "headline": str,               # narrativa breve del backend
  "metrics": {
    "delta_pct": float,         # TWRR del mes (combina realized + unrealized)
    "delta_usd": float,         # P&L absoluto del mes (combina ambos)
    "start_value": float,
    "end_value": float,
    "deposits": float,
    "withdrawals": float,
    "realized_pnl": float,      # P&L USD de trades CERRADOS en el mes
    "unrealized_pnl": float,    # P&L USD mark-to-market de posiciones abiertas
    "trades_count": int,        # cantidad de trades CERRADOS en el mes
    "win_rate": float | null,   # win rate sobre los trades cerrados del mes
    "vs_sp500_pct": float | null,
    "vs_inflation_pct": float | null,
  },
  "best_trade": {               # CERRADO — operación con mayor P&L USD del mes
    "asset": str, "pnl_usd": float, "pnl_pct": float, "kind": "closed_trade"
  } | null,
  "worst_trade": {              # CERRADO — operación con menor P&L USD del mes
    "asset": str, "pnl_usd": float, "pnl_pct": float, "kind": "closed_trade"
  } | null,
  "top_drivers": [              # top 3 activos por contribución a P&L
                                # SOLO TRADES CERRADOS — el contribution_pct
                                # es sobre el realized del mes, NO mark-to-market.
                                # Si querés concentración presente real, usar
                                # dashboard.top_holdings o current_holdings_top
                                # del insights.
    {
      "asset": str,
      "contribution_pct": float,
      "pnl_usd": float,
      "kind": "closed_trade"    # explícito para el LLM
    }
  ],
  "insights_count": int,         # cuántas señales detectó el backend
}
"""
from __future__ import annotations
from typing import Dict, Any


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    year = kwargs.get("year")
    month = kwargs.get("month")
    if year is None or month is None:
        raise ValueError(
            "Faltan params 'year' y 'month' — ej. {year: 2026, month: 5}."
        )
    try:
        year = int(year)
        month = int(month)
    except (TypeError, ValueError):
        raise ValueError("year y month deben ser enteros.")
    if month < 1 or month > 12:
        raise ValueError(f"month inválido: {month}")

    from reporting.builder import build_period_report
    from reporting.schema import report_to_dict as _to_dict

    period_key = f"{year:04d}-{month:02d}"

    # Inflación + S&P para el delta vs benchmarks. Si fetch falla, los
    # campos vs_* van a quedar None — el builder es robusto.
    bench: Dict[str, Any] = {}
    try:
        import main as _m
        cache_bench = getattr(_m, "_bench_cache", {}) or {}
        data = cache_bench.get("data") or {}
        bench = {
            "inflation_ar": data.get("inflation_ar") or {},
            "sp500": data.get("sp500") or {},
        }
    except Exception:
        bench = {"inflation_ar": {}, "sp500": {}}

    # live_value para mes en curso (delta hasta el último snapshot, no
    # hasta el cierre teórico del mes).
    live_value = None
    try:
        import main as _m
        live_value = _m._latest_snapshot_value(conn, user_id)
    except Exception:
        live_value = None

    report = build_period_report(
        conn, user_id, "month", period_key,
        broker_filter="global", bench=bench, live_value=live_value,
    )

    # Adelgazar: tomamos el dict completo y descartamos lo que no necesita el LLM
    full = _to_dict(report) or {}

    m = full.get("metrics") or {}
    highlights = full.get("highlights") or {}
    drivers = full.get("drivers") or []

    def _trade(side: str):
        item = highlights.get(side) if isinstance(highlights, dict) else None
        if not item:
            return None
        return {
            "asset": item.get("asset"),
            "pnl_usd": round(float(item.get("pnl_usd") or 0), 2),
            "pnl_pct": round(float(item.get("pnl_pct") or 0), 2),
            # Etiqueta explícita para el LLM: estos son trades CERRADOS
            # del mes (filtrados de operations con pnl_usd no null y
            # op_type != Compra/Dividendo). No son posiciones abiertas.
            "kind": "closed_trade",
        }

    top_drivers = []
    for d in (drivers or [])[:3]:
        if not isinstance(d, dict):
            continue
        top_drivers.append({
            "asset": d.get("asset"),
            "contribution_pct": round(float(d.get("contribution_pct") or 0), 2),
            "pnl_usd": round(float(d.get("pnl_usd") or 0), 2),
            # Top drivers se computan SOLO sobre operations cerradas en
            # `compute_drivers` (reporting/builder.py:355). El campo
            # `contribution_pct` es % de realized — NO mezcla unrealized.
            "kind": "closed_trade",
        })

    return {
        "screen": "monthly",
        "period": {
            "year": year,
            "month": month,
            "label": full.get("period_label") or period_key,
        },
        "is_current": bool(full.get("is_current")),
        "is_relevant": bool(full.get("is_relevant", True)),
        "headline": full.get("headline"),
        "subheadline": full.get("subheadline"),
        "metrics": {
            "delta_pct": round(float(m.get("delta_pct") or 0), 2),
            "delta_usd": round(float(m.get("delta_usd") or 0), 2),
            "start_value": round(float(m.get("start_value") or 0), 2),
            "end_value": round(float(m.get("end_value") or 0), 2),
            "deposits": round(float(m.get("deposits") or 0), 2),
            "withdrawals": round(float(m.get("withdrawals") or 0), 2),
            "realized_pnl": round(float(m.get("realized_pnl") or 0), 2),
            "unrealized_pnl": round(float(m.get("unrealized_pnl") or 0), 2),
            "trades_count": int(m.get("trades_count") or 0),
            "win_rate": (
                round(float(m["win_rate"]), 2) if m.get("win_rate") is not None else None
            ),
            "vs_sp500_pct": (
                round(float(m["vs_sp500_pct"]), 2) if m.get("vs_sp500_pct") is not None else None
            ),
            "vs_inflation_pct": (
                round(float(m["vs_inflation_pct"]), 2) if m.get("vs_inflation_pct") is not None else None
            ),
        },
        "best_trade": _trade("best_op"),
        "worst_trade": _trade("worst_op"),
        "top_drivers": top_drivers,
        "insights_count": len(full.get("insights") or []),
    }
