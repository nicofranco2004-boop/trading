"""builders.dashboard_evolution — packet de la evolución / curva del portfolio.
═══════════════════════════════════════════════════════════════════════════
Topic: dashboard.evolution

Análisis del gráfico de valor del portfolio en el tiempo. Devuelve la
serie reducida (12 puntos) + métricas de la curva: peak, trough,
drawdown actual, mejor / peor mes, volatilidad simple.

Shape (~400 bytes):
{
  "screen": "dashboard.evolution",
  "period_days": int,
  "value_now": int,
  "value_start": int,
  "delta_pct": float,
  "delta_usd": int,
  "peak": {"date": str, "value": int},
  "trough": {"date": str, "value": int},
  "current_drawdown_pct": float,    # vs peak
  "best_month": {"month": str, "pct": float} | null,
  "worst_month": {"month": str, "pct": float} | null,
  "points": [[date, value_usd], ...],  # 12 puntos representativos
}
"""

from __future__ import annotations
from typing import Dict, Any, List
from datetime import datetime


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    # Período: por default 1 año. Si pasan 'period_days' lo respetamos.
    period_days = int(kwargs.get("period_days", 365))

    snapshots = [dict(r) for r in conn.execute(
        "SELECT date, total_value FROM snapshots WHERE user_id=? "
        "ORDER BY date ASC", (user_id,)
    ).fetchall()]

    monthly = [dict(r) for r in conn.execute(
        "SELECT * FROM monthly_entries WHERE user_id=? AND broker='global' "
        "ORDER BY year ASC, month ASC", (user_id,)
    ).fetchall()]

    if not snapshots:
        return {
            "screen": "dashboard.evolution",
            "period_days": period_days,
            "insufficient_data": True,
            "reason": "Sin snapshots cargados — la curva necesita historial diario.",
        }

    # Cortar a la ventana solicitada
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=period_days)).date().isoformat()
    in_window = [s for s in snapshots if s["date"] >= cutoff and s.get("total_value")]
    if len(in_window) < 2:
        in_window = [s for s in snapshots if s.get("total_value")][-12:]

    if len(in_window) < 2:
        return {
            "screen": "dashboard.evolution",
            "period_days": period_days,
            "insufficient_data": True,
            "reason": "Necesitamos al menos 2 snapshots para construir la curva.",
        }

    values = [(s["date"], float(s["total_value"])) for s in in_window]
    value_start = values[0][1]
    value_end = values[-1][1]
    delta_usd = value_end - value_start
    delta_pct = (value_end - value_start) / value_start if value_start > 0 else 0

    # Peak / trough
    peak = max(values, key=lambda v: v[1])
    trough = min(values, key=lambda v: v[1])
    current_dd = (value_end - peak[1]) / peak[1] if peak[1] > 0 else 0

    # Reducir a 12 puntos representativos (downsampling uniforme)
    n = len(values)
    if n <= 12:
        points = values
    else:
        step = n / 12
        points = [values[min(int(i * step), n - 1)] for i in range(12)]
        if points[-1][0] != values[-1][0]:
            points[-1] = values[-1]  # asegurar el último punto

    # Mejor / peor mes (de monthly_entries)
    best_month = None
    worst_month = None
    if monthly:
        scored = []
        for m in monthly:
            ci = m.get("capital_inicio") or 0
            cf = m.get("capital_final") or 0
            net = (m.get("deposits") or 0) - (m.get("withdrawals") or 0)
            if ci > 0:
                ret = (cf - ci - net) / ci
                ret = max(-0.95, min(5.0, ret))
                scored.append((f"{m['year']}-{m['month']:02d}", ret))
        if scored:
            scored.sort(key=lambda x: x[1])
            worst_month = {"month": scored[0][0], "pct": round(scored[0][1], 4)}
            best_month = {"month": scored[-1][0], "pct": round(scored[-1][1], 4)}

    return {
        "screen": "dashboard.evolution",
        "period_days": period_days,
        "value_now": int(round(value_end)),
        "value_start": int(round(value_start)),
        "delta_pct": round(delta_pct, 4),
        "delta_usd": int(round(delta_usd)),
        "peak": {"date": peak[0], "value": int(round(peak[1]))},
        "trough": {"date": trough[0], "value": int(round(trough[1]))},
        "current_drawdown_pct": round(current_dd, 4),
        "best_month": best_month,
        "worst_month": worst_month,
        "points": [[d, int(round(v))] for d, v in points],
    }
