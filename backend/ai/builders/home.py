"""builders.home — packet del Home (snapshot rápido del día).
═══════════════════════════════════════════════════════════════════════════
Topic: home

El Home es la primera vista cuando entrás. Mezcla 3 dimensiones:
- Estado de mercado (índices del día — SPY/NDX/blue/etc.).
- Estado del portfolio del user (delta del día via snapshots).
- Cards de "lo que te afecta hoy" (holdings que se movieron, eventos
  próximos en tus tickers).

El análisis IA acá responde a la pregunta "¿qué pasó hoy con el mercado
y mi cartera?" sin entrar en el detalle profundo (eso lo hace
Dashboard/Insights).

Shape (~1KB):
{
  "screen": "home",
  "market": {
    "indices": [{ "symbol": str, "kind": str, "change_pct": float | null }],
    "summary": "mostly_up" | "mostly_down" | "mixed" | "flat",
  },
  "portfolio_today": {
    "total_value_usd": float | null,
    "delta_pct_today": float | null,
    "delta_usd_today": float | null,
  },
  "personal_cards_count": int,         # cuántas cards condicionales aparecen
  "portfolio_events_window": {
    "total": int,                       # eventos próximos en sus tickers
    "weight_at_risk_pct": float,        # % cartera con evento próximo
    "next_event": { ticker, type, days_ahead } | null,
  },
  "top_holdings_pulse": [               # top 3 holdings con su delta del día
    { ticker, weight_pct, change_pct_today | null }
  ],
}
"""
from __future__ import annotations
from typing import Dict, Any, List
from datetime import date, timedelta


def _market_summary(indices: List[Dict[str, Any]]) -> str:
    """Clasifica el día de mercado en 4 categorías."""
    if not indices:
        return "flat"
    deltas = [i.get("change_pct") for i in indices if i.get("change_pct") is not None]
    if not deltas:
        return "flat"
    up = sum(1 for d in deltas if d > 0.5)
    down = sum(1 for d in deltas if d < -0.5)
    if up >= 4 and down == 0:
        return "mostly_up"
    if down >= 4 and up == 0:
        return "mostly_down"
    if abs(up - down) <= 1:
        return "mixed"
    return "mostly_up" if up > down else "mostly_down"


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    # ── 1. Índices de mercado ────────────────────────────────────────────────
    # Llamamos directo al fetcher de home.market (mismo que /api/home/indices).
    # Tiene su propio cache TTL internamente, así que no duplicamos.
    indices_list: List[Dict[str, Any]] = []
    try:
        from home.market import get_indices_strip
        data = get_indices_strip() or []
        for item in data[:6]:
            indices_list.append({
                "symbol": item.get("symbol") or item.get("name"),
                "kind": item.get("kind") or "index",
                "change_pct": (
                    round(float(item["change_pct"]), 2)
                    if item.get("change_pct") is not None else None
                ),
            })
    except Exception:
        indices_list = []

    market = {
        "indices": indices_list,
        "summary": _market_summary(indices_list),
    }

    # ── 2. Portfolio del día via últimos 2 snapshots ─────────────────────────
    snaps = conn.execute(
        """SELECT date, total_value FROM snapshots
            WHERE user_id = ? ORDER BY date DESC LIMIT 2""",
        (user_id,),
    ).fetchall()
    portfolio_today: Dict[str, Any] = {
        "total_value_usd": None,
        "delta_pct_today": None,
        "delta_usd_today": None,
    }
    if snaps:
        latest = float(snaps[0]["total_value"] or 0)
        portfolio_today["total_value_usd"] = round(latest, 2)
        if len(snaps) >= 2:
            prev = float(snaps[1]["total_value"] or 0)
            if prev > 0:
                portfolio_today["delta_usd_today"] = round(latest - prev, 2)
                portfolio_today["delta_pct_today"] = round((latest / prev - 1) * 100, 2)

    # ── 3. Personal cards count (lo que cambió hoy para el user) ─────────────
    personal_cards_count = 0
    try:
        import main as _m
        rows = conn.execute(
            """SELECT DISTINCT asset FROM positions
                WHERE user_id = ? AND is_cash = 0 AND quantity > 0""",
            (user_id,),
        ).fetchall()
        symbols = [r["asset"] for r in rows if r["asset"]]
        quotes = _m._fetch_batch_quotes(symbols) if symbols else {}
        try:
            events = _m._get_portfolio_events_cached(user_id)
        except Exception:
            events = []
        cards = _m.build_personal_cards(
            conn, user_id, all_quotes=quotes, portfolio_events=events,
        )
        personal_cards_count = len(cards or [])
    except Exception:
        personal_cards_count = 0

    # ── 4. Eventos próximos (14d) ────────────────────────────────────────────
    today = date.today()
    cutoff = today + timedelta(days=14)
    portfolio_assets = [r["asset"] for r in conn.execute(
        """SELECT DISTINCT asset FROM positions
            WHERE user_id = ? AND is_cash = 0 AND quantity > 0""",
        (user_id,),
    ).fetchall() if r["asset"]]

    events_window = {"total": 0, "weight_at_risk_pct": 0.0, "next_event": None}
    if portfolio_assets:
        placeholders = ",".join("?" * len(portfolio_assets))
        ev_rows = conn.execute(
            f"""SELECT ticker, event_type, event_date FROM financial_events
                 WHERE ticker IN ({placeholders})
                   AND event_date >= ? AND event_date <= ?
                 ORDER BY event_date ASC""",
            (*portfolio_assets, today.isoformat(), cutoff.isoformat()),
        ).fetchall()
        events_window["total"] = len(ev_rows)
        if ev_rows:
            first = ev_rows[0]
            try:
                d = date.fromisoformat(str(first["event_date"])[:10])
                days_ahead = (d - today).days
            except (TypeError, ValueError):
                days_ahead = None
            events_window["next_event"] = {
                "ticker": first["ticker"],
                "type": first["event_type"],
                "days_ahead": days_ahead,
            }

            # weight_at_risk_pct: peso combinado de tickers únicos con evento
            # próximo (usamos weights de top_holdings que reusamos arriba).
            try:
                from .dashboard_top_holdings import build as build_top_w
                weights_packet = build_top_w(conn, user_id)
                weights_by_ticker = {
                    h.get("ticker"): h.get("weight_pct", 0)
                    for h in (weights_packet.get("top_holdings") or [])
                }
                affected = {ev["ticker"] for ev in ev_rows if ev["ticker"]}
                w_sum = sum(
                    weights_by_ticker.get(t, 0) for t in affected
                )
                events_window["weight_at_risk_pct"] = round(w_sum, 2)
            except Exception:
                pass

    # ── 5. Top 3 holdings con su delta del día ───────────────────────────────
    # change_pct_today viene de las quotes (cada quote trae change_pct del día).
    top_holdings_pulse: List[Dict[str, Any]] = []
    try:
        from .dashboard_top_holdings import build as build_top
        top_packet = build_top(conn, user_id)
        top_list = top_packet.get("top_holdings") or []

        # Map ticker → change_pct del día desde las quotes que ya fetcheamos
        ticker_change: Dict[str, float] = {}
        try:
            import main as _m
            symbols_for_change = set()
            for h in top_list[:3]:
                t = h.get("ticker")
                if not t:
                    continue
                # broker AR → símbolo termina en .BA
                broker_n = (h.get("broker") or "").lower()
                if broker_n in {"cocos", "cocos capital", "iol", "bull", "balanz", "naranja", "pppi", "invertironline"}:
                    symbols_for_change.add(f"{t}.BA")
                else:
                    symbols_for_change.add(t)
            if symbols_for_change:
                quotes = _m._fetch_batch_quotes(list(symbols_for_change))
                for sym, q in (quotes or {}).items():
                    if q and q.get("change_pct") is not None:
                        base = sym.replace(".BA", "")
                        ticker_change[base] = round(float(q["change_pct"]), 2)
        except Exception:
            ticker_change = {}

        for h in top_list[:3]:
            ticker = h.get("ticker")
            top_holdings_pulse.append({
                "ticker": ticker,
                "weight_pct": h.get("weight_pct"),
                "change_pct_today": ticker_change.get(ticker),
            })
    except Exception:
        top_holdings_pulse = []

    return {
        "screen": "home",
        "market": market,
        "portfolio_today": portfolio_today,
        "personal_cards_count": personal_cards_count,
        "portfolio_events_window": events_window,
        "top_holdings_pulse": top_holdings_pulse,
    }
