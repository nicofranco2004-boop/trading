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

    # ⚠️ NO se leen los snapshots crudos. La tabla mezcla mediciones reales del
    # cron con fotos que el import FABRICA copiando la cadena contable
    # (persister.py:1289-1292): esas no bajan con el mercado, asi que fijan
    # picos que nunca existieron y el drawdown sale de la brecha entre dos
    # formas de medir. `twr.serie_medible` deja solo lo que esta en base de
    # mercado (medido por el cron o reconstruido a precio real).
    import twr as _twr
    _serie = _twr.serie_medible(conn, user_id)
    snapshots = [{"date": p["date"], "total_value": p["value"]} for p in _serie["medibles"]]

    monthly = [dict(r) for r in conn.execute(
        "SELECT * FROM monthly_entries WHERE user_id=? AND broker='global' "
        "ORDER BY year ASC, month ASC", (user_id,)
    ).fetchall()]

    if not snapshots:
        return {
            "screen": "dashboard.evolution",
            "period_days": period_days,
            "insufficient_data": True,
            # El motivo sale de `twr.MOTIVO_TEXTO`: el asesor y el usuario final
            # tienen que leer exactamente lo mismo.
            "reason": (_serie.get("motivo_texto")
                       or "Sin snapshots cargados — la curva necesita historial diario."),
        }

    # Cortar a la ventana solicitada
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=period_days)).date().isoformat()
    in_window = [s for s in snapshots if s["date"] >= cutoff and s.get("total_value")]
    # ⚠️ El fallback amplía la ventana; el rótulo tiene que decirlo. Sin esto el
    # paquete salía con `period_days: 365` y un `value_now` de hace tres años, y
    # el LLM leía "así evolucionó tu último año". Ningún campo declaraba la
    # ventana real.
    ventana_ampliada = False
    if len(in_window) < 2:
        in_window = [s for s in snapshots if s.get("total_value")][-12:]
        ventana_ampliada = True

    if len(in_window) < 2:
        return {
            "screen": "dashboard.evolution",
            "period_days": period_days,
            "insufficient_data": True,
            "reason": "Necesitamos al menos 2 snapshots para construir la curva.",
        }

    values = [(s["date"], float(s["total_value"])) for s in in_window]
    _ventana_real = {"desde": values[0][0], "hasta": values[-1][0],
                     "ampliada": ventana_ampliada}
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
        # La ventana que estos números describen DE VERDAD (puede no ser
        # `period_days` si hubo que ampliarla por falta de mediciones).
        "ventana": _ventana_real,
        "current_drawdown_pct": round(current_dd, 4),
        "best_month": best_month,
        "worst_month": worst_month,
        "points": [[d, int(round(v))] for d, v in points],
    }
