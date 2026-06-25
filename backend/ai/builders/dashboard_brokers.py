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
    # Valuación canónica de Análisis: estampa moneda, precios .BA-aware y MEP.
    # Holdings AR/.BA → MEP (no blue); CEDEAR en sub-broker '· USD' → su .BA.
    from analysis_prep import currency_context
    from behavioral import _position_value_usd
    prices, tc_blue, tc_cedear = currency_context(conn, user_id, positions)

    # Agregamos por broker
    by_broker: Dict[str, Dict[str, float]] = {}
    grand = 0.0

    for p in positions:
        bname = p.get("broker")
        if not bname:
            continue
        # value con precios; invested con {} → costo (misma regla de moneda).
        v = _position_value_usd(p, prices, tc_blue, tc_cedear)
        inv_usd = _position_value_usd(p, {}, tc_blue, tc_cedear, honor_override=False)

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
