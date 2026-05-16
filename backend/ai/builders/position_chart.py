"""builders.position_chart — packet del chart de precio reciente de una posición.
═══════════════════════════════════════════════════════════════════════════
Topic: position.chart

Params: asset, broker (mismo que position)
"""
from __future__ import annotations
from typing import Dict, Any


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    # Reusamos position para tener qty/avg/current/days_held/etc.
    from .position import build as build_position
    pos = build_position(conn, user_id, **kwargs)

    asset = pos.get("asset")
    is_ars = pos.get("currency") == "ARS"

    # Serie reciente de precios (30d) — usa el fetch_price_history del backend
    series = []
    drawdown_recent_pct = 0.0
    pct_from_avg = pos.get("pnl_pct")  # aprox: pnl_pct ~= (current - avg) / avg * 100
    try:
        import main as _m
        symbol = f"{asset}.BA" if is_ars else asset
        hist = _m._fetch_price_history(symbol, period="1m")
        # hist devuelve dict {date_iso: close}
        if hist:
            sorted_items = sorted(hist.items())
            series = [{"date": k, "price": float(v)} for k, v in sorted_items[-30:]]
            prices = [s["price"] for s in series]
            if len(prices) >= 2:
                peak = max(prices)
                last = prices[-1]
                if peak > 0:
                    drawdown_recent_pct = round((last - peak) / peak * 100, 2)
    except Exception:
        series = []

    return {
        "screen": "position.chart",
        "asset": asset,
        "broker": pos.get("broker"),
        "qty": pos.get("qty"),
        "avg_price": pos.get("avg_price"),
        "current_price": pos.get("current_price"),
        "pct_from_avg": pct_from_avg,
        "price_series_30d": series[:30],
        "drawdown_recent_pct": drawdown_recent_pct,
        "days_held": pos.get("days_held"),
    }
