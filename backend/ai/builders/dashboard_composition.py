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
    # Valuación canónica de Análisis: estampa moneda, precios .BA-aware y MEP.
    # Holdings AR/.BA → MEP (no blue); CEDEAR en sub-broker '· USD' → su .BA (no
    # el ticker US). Antes reimplementaba al blue y compartía el bug C1.
    from analysis_prep import currency_context
    from behavioral import _position_value_usd, _native_ccy
    prices, tc_blue, tc_cedear = currency_context(conn, user_id, positions)

    # Compute USD value per position + aggregations
    by_asset: Dict[str, float] = {}
    by_broker: Dict[str, float] = {}
    usd_total = 0.0
    ars_total = 0.0
    cash_total = 0.0
    grand = 0.0

    for p in positions:
        v = _position_value_usd(p, prices, tc_blue, tc_cedear)
        is_ar = _native_ccy(p) == "ARS"  # moneda nativa real (no por nombre)
        if p.get("is_cash"):
            cash_total += v
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

    # Top 5 holdings by value — nomenclatura canónica: 'ticker' + 'weight_pct'
    # (alineado con dashboard.top_holdings, home, news, events que esperan
    # estas claves).
    top5 = sorted(by_asset.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_holdings = [
        {
            "ticker": asset,
            "weight_pct": round(val / grand * 100, 2),
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
            {"broker": b, "weight_pct": round(v / grand * 100, 2)}
            for b, v in sorted(by_broker.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "by_currency": {
            "usd_pct": round(usd_total / grand * 100, 2),
            "ars_pct": round(ars_total / grand * 100, 2),
        },
        "cash_pct": round(cash_total / grand * 100, 2),
        "hhi": hhi,
    }
