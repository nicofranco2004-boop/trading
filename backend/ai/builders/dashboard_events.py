"""builders.dashboard_events — packet de próximos eventos del portfolio.
═══════════════════════════════════════════════════════════════════════════
Topic: dashboard.upcoming_events

Eventos próximos (earnings, dividendos) de los tickers que tiene el user.
Ventana: 14 días (mismo que el endpoint /api/events/portfolio).

Shape (~400 bytes):
{
  "screen": "dashboard.upcoming_events",
  "window_days": 14,
  "events": [
    { "ticker": str, "type": str, "date": str, "days_ahead": int,
      "weight_pct": float | null, "details": str | null }
  ],
  "total_events": int,
  "tickers_affected": int,
  "earnings_count": int,
  "dividends_count": int,
  "weight_at_risk_pct": float,    # % cartera con evento próximo
}
"""

from __future__ import annotations
from typing import Dict, Any, List
from datetime import date, timedelta


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    window_days = int(kwargs.get("window_days", 14))
    today = date.today()
    cutoff = today + timedelta(days=window_days)

    # Tickers del user (non-cash, qty > 0)
    rows = conn.execute(
        """SELECT asset, asset_type, broker, currency, quantity, invested,
                  is_cash, price_override
             FROM positions
            WHERE user_id = ? AND (is_cash = 0 OR is_cash IS NULL)
              AND quantity > 0""",
        (user_id,),
    ).fetchall()
    positions = [dict(r) for r in rows]
    tickers = sorted({p["asset"] for p in positions if p.get("asset")})

    if not tickers:
        return {
            "screen": "dashboard.upcoming_events",
            "window_days": window_days,
            "events": [],
            "total_events": 0,
            "tickers_affected": 0,
            "earnings_count": 0,
            "dividends_count": 0,
            "weight_at_risk_pct": 0,
        }

    # Buscar eventos en la ventana (tabla `financial_events`)
    placeholders = ",".join("?" * len(tickers))
    events = conn.execute(
        f"""SELECT ticker, event_type, event_date, details
              FROM financial_events
             WHERE ticker IN ({placeholders})
               AND event_date >= ? AND event_date <= ?
             ORDER BY event_date ASC""",
        (*tickers, today.isoformat(), cutoff.isoformat()),
    ).fetchall()

    # Valor de cartera + por-ticker para weight_pct. Valuación canónica de
    # Análisis (MEP para holdings AR/.BA; CEDEAR en sub-broker '· USD' por su .BA,
    # no el ticker US → fix C1). Antes reimplementaba al blue/ticker US.
    from analysis_prep import currency_context
    from behavioral import _position_value_usd
    prices, tc_blue, tc_cedear = currency_context(conn, user_id, positions)

    # USD value por ticker (agregado)
    value_by_ticker: Dict[str, float] = {}
    total_value = 0.0
    for p in positions:
        v = _position_value_usd(p, prices, tc_blue, tc_cedear)
        value_by_ticker[p["asset"]] = value_by_ticker.get(p["asset"], 0) + v
        total_value += v
    total_value = max(total_value, 1)

    # Armamos lista de eventos enriquecidos
    enriched: List[Dict[str, Any]] = []
    tickers_in_events = set()
    earnings_count = 0
    dividends_count = 0
    weight_at_risk = 0.0
    counted_for_risk = set()

    for ev in events:
        ticker = ev["ticker"]
        try:
            d = date.fromisoformat(ev["event_date"])
            days_ahead = (d - today).days
        except (TypeError, ValueError):
            days_ahead = None

        ttype = (ev["event_type"] or "").lower()
        if "earning" in ttype:
            earnings_count += 1
        elif "div" in ttype:
            dividends_count += 1

        weight = value_by_ticker.get(ticker, 0) / total_value
        # Acumular weight solo una vez por ticker (no doblar si tiene 2 eventos)
        if ticker not in counted_for_risk:
            weight_at_risk += weight
            counted_for_risk.add(ticker)

        tickers_in_events.add(ticker)
        enriched.append({
            "ticker": ticker,
            "type": ev["event_type"],
            "date": ev["event_date"],
            "days_ahead": days_ahead,
            # weight es fracción 0..1 (value/total) → emitir en 0..100 como el
            # resto (events.py/home.py/top_holdings) y como lo espera el prompt
            # (umbral ">30%"). Antes iba en fracción → la IA reportaba "0,45%"
            # por 45% y el umbral del prompt nunca disparaba.
            "weight_pct": round(weight * 100, 2) if weight else None,
            "details": ev["details"],
        })

    return {
        "screen": "dashboard.upcoming_events",
        "window_days": window_days,
        "events": enriched[:12],   # cap a 12 para no inflar el packet
        "total_events": len(enriched),
        "tickers_affected": len(tickers_in_events),
        "earnings_count": earnings_count,
        "dividends_count": dividends_count,
        "weight_at_risk_pct": round(weight_at_risk * 100, 2),  # 0..100, no fracción
    }
