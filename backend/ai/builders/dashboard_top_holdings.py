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


def holding_weights(conn, user_id: int) -> Dict[str, float]:
    """Mapa ticker → % de la cartera (por valor USD-MEP), SIN cap de top-N.

    Agrega por ticker (suma brokers) y reusa la MISMA valuación canónica que
    build(). Sirve para anclar noticias/eventos a "afecta X% de tu cartera" en
    cualquier posición, no solo el top 8. Cero costo IA (sólo valuación).
    """
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE user_id=?", (user_id,)
    ).fetchall()]
    from analysis_prep import currency_context
    from behavioral import _position_value_usd
    prices, tc_blue, tc_cedear = currency_context(conn, user_id, positions)

    by_ticker: Dict[str, float] = {}
    grand = 0.0
    for p in positions:
        if p.get("is_cash"):
            continue
        qty = p.get("quantity") or 0
        invested = p.get("invested") or 0
        if invested <= 0 or qty <= 0:
            continue
        v = _position_value_usd(p, prices, tc_blue, tc_cedear)
        grand += v
        t = p.get("asset")
        if t:
            by_ticker[t] = by_ticker.get(t, 0.0) + v
    if grand <= 0:
        return {}
    return {t: round(v / grand * 100, 2) for t, v in by_ticker.items()}


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE user_id=?", (user_id,)
    ).fetchall()]
    # Valuación canónica de Análisis: estampa moneda, arma precios .BA-aware y
    # devuelve tc_cedear (dólar-MEP). Así los holdings AR/.BA se valúan a MEP (no
    # blue) y un CEDEAR en sub-broker '· USD' por su .BA (no el ticker US, que
    # valía 15-100× más). Antes este builder reimplementaba la valuación al blue
    # y compartía el bug C1. Ver CORRECTNESS_AUDIT (M-AI1 / C1).
    from analysis_prep import currency_context
    from behavioral import _position_value_usd
    prices, tc_blue, tc_cedear = currency_context(conn, user_id, positions)

    today = datetime.utcnow().date()
    enriched: List[Dict[str, Any]] = []
    grand = 0.0

    for p in positions:
        if p.get("is_cash"):
            continue
        qty = p.get("quantity") or 0
        invested = p.get("invested") or 0
        if invested <= 0 or qty <= 0:
            continue
        # value con precios; invested con {} → fallback a costo, MISMA regla de
        # moneda (evita FX-phantom: ambos al MEP para holdings AR).
        value_usd = _position_value_usd(p, prices, tc_blue, tc_cedear)
        invested_usd = _position_value_usd(p, {}, tc_blue, tc_cedear, honor_override=False)
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
