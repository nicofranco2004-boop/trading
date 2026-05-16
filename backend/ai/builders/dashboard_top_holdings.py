"""builders.dashboard_top_holdings — packet del top de holdings.
═══════════════════════════════════════════════════════════════════════════
Topic: dashboard.top_holdings

Top 8 holdings con su weight, P/L %, sector si se puede inferir, días
desde la primera compra. Útil para responder "¿qué posición me está
haciendo el resultado?" o "¿cuánto pesan mis ganadoras?".

Shape (~500 bytes):
{
  "screen": "dashboard.top_holdings",
  "total_value_usd": int,
  "top_holdings": [
    {
      "ticker": str, "broker": str, "weight_pct": float,
      "value_usd": int, "pnl_pct": float | null,
      "days_held": int | null,
    }
  ],
  "winners_count": int,
  "losers_count": int,
}

NOTA: La clave es `top_holdings` (no `holdings`) — varios builders downstream
(home, news, events, insights.observation) la consumen con ese nombre para
extraer pesos por ticker. El field `ticker` reemplaza a `asset` por consistencia
con la nomenclatura del resto del sistema (atribution, eventos, etc.).
"""

from __future__ import annotations
from typing import Dict, Any, List
from datetime import datetime


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE user_id=?", (user_id,)
    ).fetchall()]
    brokers = [dict(r) for r in conn.execute(
        "SELECT * FROM brokers WHERE user_id=?", (user_id,)
    ).fetchall()]
    tc_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (user_id,)
    ).fetchone()
    try:
        tc_blue = float(tc_row["value"]) if tc_row and tc_row["value"] else 1
    except (TypeError, ValueError):
        tc_blue = 1
    if tc_blue <= 0:
        tc_blue = 1

    ars_brokers = {b["name"] for b in brokers if b.get("currency") == "ARS"}

    prices: Dict[str, float] = {}
    try:
        from home.market import _fetch_batch_quotes
        symbols = set()
        for p in positions:
            if p.get("is_cash") or not p.get("asset"):
                continue
            if p.get("broker") in ars_brokers:
                symbols.add(f"{p['asset']}.BA")
            else:
                symbols.add(p["asset"])
        if symbols:
            quotes = _fetch_batch_quotes(list(symbols))
            prices = {s: q["price"] for s, q in quotes.items() if q and q.get("price")}
    except Exception:
        prices = {}

    today = datetime.utcnow().date()
    enriched: List[Dict[str, Any]] = []
    grand = 0.0

    for p in positions:
        if p.get("is_cash"):
            continue
        is_ar = p.get("broker") in ars_brokers
        qty = p.get("quantity") or 0
        invested = p.get("invested") or 0
        if invested <= 0 or qty <= 0:
            continue
        if is_ar:
            price = p.get("price_override") or prices.get(f"{p['asset']}.BA")
            value_usd = (price * qty) / tc_blue if price else invested / tc_blue
            invested_usd = invested / tc_blue
        else:
            price = p.get("price_override") or prices.get(p.get("asset"))
            value_usd = price * qty if price else invested
            invested_usd = invested
        pnl_pct = ((value_usd - invested_usd) / invested_usd) if invested_usd > 0 else 0
        grand += value_usd

        days_held = None
        if p.get("entry_date"):
            try:
                d = datetime.strptime(p["entry_date"][:10], "%Y-%m-%d").date()
                days_held = max(0, (today - d).days)
            except (ValueError, TypeError):
                pass

        enriched.append({
            "asset": p.get("asset"),
            "broker": p.get("broker"),
            "value_usd": value_usd,
            "pnl_pct": pnl_pct,
            "days_held": days_held,
        })

    if not enriched or grand <= 0:
        return {
            "screen": "dashboard.top_holdings",
            "insufficient_data": True,
            "reason": "Sin holdings non-cash cargados.",
        }

    # Top 8 by value
    enriched.sort(key=lambda x: x["value_usd"], reverse=True)
    top = enriched[:8]

    winners = sum(1 for h in enriched if (h.get("pnl_pct") or 0) > 0)
    losers = sum(1 for h in enriched if (h.get("pnl_pct") or 0) < 0)

    return {
        "screen": "dashboard.top_holdings",
        "total_value_usd": int(round(grand)),
        "top_holdings": [
            {
                "ticker": h["asset"],
                "broker": h["broker"],
                "weight_pct": round(h["value_usd"] / grand * 100, 2),
                "value_usd": int(round(h["value_usd"])),
                "pnl_pct": round(h["pnl_pct"] * 100, 2),
                "days_held": h["days_held"],
            }
            for h in top
        ],
        "winners_count": winners,
        "losers_count": losers,
    }
