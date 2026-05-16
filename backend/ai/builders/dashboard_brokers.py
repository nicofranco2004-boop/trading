"""builders.dashboard_brokers — packet del breakdown por broker.
═══════════════════════════════════════════════════════════════════════════
Topic: dashboard.brokers

Útil para responder "¿qué broker me está manejando el resultado?",
"¿estoy concentrado en un solo broker (riesgo de plataforma)?", o
"¿tengo plata muerta en algún broker que no rinde?".

Shape (~400 bytes):
{
  "screen": "dashboard.brokers",
  "total_value_usd": int,
  "brokers": [
    {
      "name": str, "currency": str,
      "value_usd": int, "invested_usd": int,
      "pnl_pct": float, "weight_pct": float,
      "positions_count": int,
    }
  ],
  "broker_count": int,
  "top1_pct": float,         # % del broker más grande
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

    prices: Dict[str, float] = {}
    try:
        from home.market import _fetch_batch_quotes
        ars_brokers = {b["name"] for b in brokers if b.get("currency") == "ARS"}
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

    # Agregamos por broker
    ars_broker_set = {b["name"] for b in brokers if b.get("currency") == "ARS"}
    by_broker: Dict[str, Dict[str, float]] = {}
    grand = 0.0

    for p in positions:
        bname = p.get("broker")
        if not bname:
            continue
        is_ar = bname in ars_broker_set
        invested = p.get("invested") or 0
        qty = p.get("quantity") or 0
        if p.get("is_cash"):
            v = invested / tc_blue if is_ar else invested
            inv_usd = v  # cash: invested == value
        elif is_ar:
            price = p.get("price_override") or prices.get(f"{p['asset']}.BA")
            v = (price * qty) / tc_blue if price else invested / tc_blue
            inv_usd = invested / tc_blue
        else:
            price = p.get("price_override") or prices.get(p.get("asset"))
            v = price * qty if price else invested
            inv_usd = invested

        slot = by_broker.setdefault(bname, {"value": 0.0, "invested": 0.0, "count": 0})
        slot["value"] += v
        slot["invested"] += inv_usd
        if not p.get("is_cash"):
            slot["count"] += 1
        grand += v

    grand = max(grand, 1)

    # Lista ordenada por valor descendente
    rows = []
    for bname, data in by_broker.items():
        bmeta = next((b for b in brokers if b["name"] == bname), None)
        currency = bmeta["currency"] if bmeta else "USDT"
        pnl_pct = (data["value"] - data["invested"]) / data["invested"] if data["invested"] > 0 else 0
        rows.append({
            "name": bname,
            "currency": currency,
            "value_usd": int(round(data["value"])),
            "invested_usd": int(round(data["invested"])),
            "pnl_pct": round(pnl_pct, 4),
            "weight_pct": round(data["value"] / grand, 4),
            "positions_count": data["count"],
        })
    rows.sort(key=lambda r: r["value_usd"], reverse=True)

    return {
        "screen": "dashboard.brokers",
        "total_value_usd": int(round(grand)),
        "brokers": rows,
        "broker_count": len(rows),
        "top1_pct": rows[0]["weight_pct"] if rows else 0,
    }
