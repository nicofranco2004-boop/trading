"""builders.dashboard_composition — packet de la sección "Composición" del Dashboard.
═══════════════════════════════════════════════════════════════════════════
Topic: dashboard.composition

Mirá cómo está repartida la plata: por activo (top 5), por sector si lo
podemos derivar, por broker, por moneda (USD vs ARS), por tipo (cash vs
non-cash). Más concentración == más riesgo idiosincrático.

Shape (~300 bytes):
{
  "screen": "dashboard.composition",
  "total_value_usd": int,
  "top_holdings": [{"asset": str, "pct": float, "value_usd": int}],  # top 5
  "by_broker": [{"broker": str, "pct": float}],
  "by_currency": {"usd_pct": float, "ars_pct": float},
  "cash_pct": float,
  "hhi": float,  # Herfindahl index — 0=balanced, 1=concentrated
}
"""

from __future__ import annotations
from typing import Dict, Any


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

    # Fetch prices
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

    # Compute USD value per position + aggregations
    by_asset: Dict[str, float] = {}
    by_broker: Dict[str, float] = {}
    usd_total = 0.0
    ars_total = 0.0
    cash_total = 0.0
    grand = 0.0

    for p in positions:
        is_ar = p.get("broker") in ars_brokers
        invested = p.get("invested") or 0
        qty = p.get("quantity") or 0
        if p.get("is_cash"):
            v = invested / tc_blue if is_ar else invested
            cash_total += v
        elif is_ar:
            price = p.get("price_override") or prices.get(f"{p['asset']}.BA")
            v = (price * qty) / tc_blue if price else invested / tc_blue
        else:
            price = p.get("price_override") or prices.get(p.get("asset"))
            v = price * qty if price else invested
        grand += v
        if p.get("asset"):
            by_asset[p["asset"]] = by_asset.get(p["asset"], 0) + v
        if p.get("broker"):
            by_broker[p["broker"]] = by_broker.get(p["broker"], 0) + v
        if is_ar:
            ars_total += v
        else:
            usd_total += v

    grand = max(grand, 1)  # evitar div-by-zero

    # Top 5 holdings by value
    top5 = sorted(by_asset.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_holdings = [
        {
            "asset": asset,
            "pct": round(val / grand, 4),
            "value_usd": int(round(val)),
        }
        for asset, val in top5
    ]

    # Herfindahl-Hirschman Index (HHI) — concentration metric
    # 0 = perfectly diversified, 1 = single asset
    weights = [val / grand for val in by_asset.values()]
    hhi = round(sum(w * w for w in weights), 4)

    return {
        "screen": "dashboard.composition",
        "total_value_usd": int(round(grand)),
        "top_holdings": top_holdings,
        "by_broker": [
            {"broker": b, "pct": round(v / grand, 4)}
            for b, v in sorted(by_broker.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "by_currency": {
            "usd_pct": round(usd_total / grand, 4),
            "ars_pct": round(ars_total / grand, 4),
        },
        "cash_pct": round(cash_total / grand, 4),
        "hhi": hhi,
    }
