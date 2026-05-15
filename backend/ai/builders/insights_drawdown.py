"""builders.insights_drawdown — packet de drawdown / riesgo del Insights.
═══════════════════════════════════════════════════════════════════════════
Topic: insights.drawdown

Sub-componente del Insights — análisis específico del riesgo: caídas
desde peak, profundidad histórica, tiempo de recovery, número de
drawdown events superiores a un umbral.

Shape (~600 bytes):
{
  "screen": "insights.drawdown",
  "window_days": int,
  "current_pct": float,         # caída actual desde peak (0 si estamos en peak)
  "max_pct": float,             # peor caída del período
  "days_since_peak": int | null,
  "peak_value": float | null,
  "trough_value": float | null,
  "dd_events": [                # eventos > -5%
    { "start_date": str, "end_date": str, "depth_pct": float, "duration_days": int }
  ],
  "events_count": int,
  "recovered": bool,            # True si después del worst trough volvió al peak
}
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import date, datetime, timedelta


_DD_THRESHOLD = -5.0  # % — eventos de drawdown reportables


def _parse_date(s) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except (TypeError, ValueError):
        return None


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    window_days = int(kwargs.get("window_days", 365))
    today = date.today()
    cutoff = today - timedelta(days=window_days)

    rows = conn.execute(
        "SELECT date, total_value FROM snapshots WHERE user_id=? ORDER BY date ASC",
        (user_id,),
    ).fetchall()
    snaps = [dict(r) for r in rows]
    window = [
        s for s in snaps
        if _parse_date(s["date"]) and _parse_date(s["date"]) >= cutoff
        and s["total_value"] is not None
    ]

    if len(window) < 2:
        return {
            "screen": "insights.drawdown",
            "window_days": window_days,
            "current_pct": 0.0,
            "max_pct": 0.0,
            "days_since_peak": None,
            "peak_value": None,
            "trough_value": None,
            "dd_events": [],
            "events_count": 0,
            "recovered": True,
        }

    values = [(s["date"], float(s["total_value"] or 0)) for s in window]
    peak = values[0][1]
    peak_idx = 0
    max_dd = 0.0
    trough_value = peak

    # Eventos de DD: tracking de start/end cuando cruzamos el threshold
    events: List[Dict[str, Any]] = []
    in_event = False
    event_peak = peak
    event_peak_date = values[0][0]
    event_trough = peak

    for i, (d, v) in enumerate(values):
        if v > peak:
            peak = v
            peak_idx = i
        dd_pct = ((v - peak) / peak * 100) if peak > 0 else 0
        if dd_pct < max_dd:
            max_dd = dd_pct
            trough_value = v

        # Event tracking
        if not in_event:
            if dd_pct <= _DD_THRESHOLD:
                in_event = True
                event_peak = peak
                event_peak_date = values[peak_idx][0]
                event_trough = v
        else:
            if v < event_trough:
                event_trough = v
            if v >= event_peak:
                # Recovered → close event
                depth = ((event_trough - event_peak) / event_peak * 100) if event_peak > 0 else 0
                start_d = _parse_date(event_peak_date)
                end_d = _parse_date(d)
                duration = (end_d - start_d).days if (start_d and end_d) else None
                events.append({
                    "start_date": str(event_peak_date),
                    "end_date": str(d),
                    "depth_pct": round(depth, 2),
                    "duration_days": duration,
                })
                in_event = False

    # Si quedó un evento abierto al cierre, lo agregamos (sin end)
    if in_event:
        depth = ((event_trough - event_peak) / event_peak * 100) if event_peak > 0 else 0
        start_d = _parse_date(event_peak_date)
        events.append({
            "start_date": str(event_peak_date),
            "end_date": None,
            "depth_pct": round(depth, 2),
            "duration_days": (today - start_d).days if start_d else None,
        })

    current_value = values[-1][1]
    current_dd = ((current_value - peak) / peak * 100) if peak > 0 else 0
    days_since_peak = (len(values) - 1) - peak_idx

    return {
        "screen": "insights.drawdown",
        "window_days": window_days,
        "current_pct": round(current_dd, 2),
        "max_pct": round(max_dd, 2),
        "days_since_peak": days_since_peak,
        "peak_value": round(peak, 2),
        "trough_value": round(trough_value, 2),
        # Cap a los 5 eventos más profundos para no inflar
        "dd_events": sorted(events, key=lambda e: e["depth_pct"])[:5],
        "events_count": len(events),
        "recovered": (current_dd > -1.0),
    }
