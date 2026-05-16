"""builders.events — packet del calendario completo de eventos próximos.
═══════════════════════════════════════════════════════════════════════════
Topic: events

Más rico que dashboard.upcoming_events (que es preview): este es el
análisis de la tab "Eventos" en /novedades. Trae ventana extendida
(60 días default), distribución temporal (esta semana / mes / más allá),
distribución por tipo (earnings vs dividendos vs split) y weight_at_risk.

Shape (~900 bytes):
{
  "screen": "events",
  "window_days": int,
  "total_events": int,
  "by_type": { "earnings": int, "dividend": int, "split": int, "other": int },
  "by_horizon": { "this_week": int, "this_month": int, "later": int },
  "weight_at_risk_pct": float,
  "concentrated_week": bool,         # True si una semana tiene >= 3 eventos relevantes
  "events": [                         # cap 12
    { "ticker", "type", "date", "days_ahead", "weight_pct" }
  ],
}
"""
from __future__ import annotations
from typing import Dict, Any
from datetime import date, timedelta
from collections import Counter


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    window_days = int(kwargs.get("window_days", 60))
    today = date.today()
    cutoff = today + timedelta(days=window_days)

    # Tickers del user
    rows = conn.execute(
        """SELECT asset, broker, quantity, invested
             FROM positions
            WHERE user_id = ? AND is_cash = 0 AND quantity > 0""",
        (user_id,),
    ).fetchall()
    positions = [dict(r) for r in rows]
    tickers = sorted({p["asset"] for p in positions if p.get("asset")})

    if not tickers:
        return {
            "screen": "events",
            "window_days": window_days,
            "total_events": 0,
            "by_type": {"earnings": 0, "dividend": 0, "split": 0, "other": 0},
            "by_horizon": {"this_week": 0, "this_month": 0, "later": 0},
            "weight_at_risk_pct": 0.0,
            "concentrated_week": False,
            "events": [],
        }

    placeholders = ",".join("?" * len(tickers))
    ev_rows = conn.execute(
        f"""SELECT ticker, event_type, event_date FROM financial_events
             WHERE ticker IN ({placeholders})
               AND event_date >= ? AND event_date <= ?
             ORDER BY event_date ASC""",
        (*tickers, today.isoformat(), cutoff.isoformat()),
    ).fetchall()

    # Weight por ticker — reusamos top_holdings
    weights: Dict[str, float] = {}
    try:
        from .dashboard_top_holdings import build as build_top
        top_packet = build_top(conn, user_id)
        for h in top_packet.get("top_holdings") or []:
            weights[h["ticker"]] = h.get("weight_pct") or 0
    except Exception:
        weights = {}

    by_type: Counter = Counter()
    by_horizon = {"this_week": 0, "this_month": 0, "later": 0}
    weight_at_risk = 0.0
    counted = set()
    events_list = []
    week_counter: Counter = Counter()  # para detectar concentración semanal

    for ev in ev_rows:
        ticker = ev["ticker"]
        try:
            d = date.fromisoformat(str(ev["event_date"])[:10])
            days_ahead = (d - today).days
            week_key = d.isocalendar()[1]
        except (TypeError, ValueError):
            days_ahead = None
            week_key = None

        ttype = (ev["event_type"] or "").lower()
        if "earning" in ttype:
            by_type["earnings"] += 1
        elif "div" in ttype:
            by_type["dividend"] += 1
        elif "split" in ttype:
            by_type["split"] += 1
        else:
            by_type["other"] += 1

        if days_ahead is not None:
            if days_ahead <= 7:
                by_horizon["this_week"] += 1
            elif days_ahead <= 30:
                by_horizon["this_month"] += 1
            else:
                by_horizon["later"] += 1

        if week_key is not None:
            week_counter[week_key] += 1

        if ticker not in counted:
            weight_at_risk += weights.get(ticker, 0)
            counted.add(ticker)

        events_list.append({
            "ticker": ticker,
            "type": ev["event_type"],
            "date": str(ev["event_date"])[:10] if ev["event_date"] else None,
            "days_ahead": days_ahead,
            "weight_pct": weights.get(ticker),
        })

    concentrated_week = any(c >= 3 for c in week_counter.values())

    return {
        "screen": "events",
        "window_days": window_days,
        "total_events": len(events_list),
        "by_type": {
            "earnings": by_type.get("earnings", 0),
            "dividend": by_type.get("dividend", 0),
            "split": by_type.get("split", 0),
            "other": by_type.get("other", 0),
        },
        "by_horizon": by_horizon,
        "weight_at_risk_pct": round(weight_at_risk, 2),
        "concentrated_week": concentrated_week,
        "events": events_list[:12],
    }
