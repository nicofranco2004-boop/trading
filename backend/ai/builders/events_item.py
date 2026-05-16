"""builders.events_item — packet de UN evento individual.
═══════════════════════════════════════════════════════════════════════════
Topic: events.item

Params (el frontend pasa el evento tal cual):
  ticker: str
  event_type: str  — 'earnings', 'dividend', 'split', etc.
  event_date: str  — ISO YYYY-MM-DD
  details: str | None
"""
from __future__ import annotations
from typing import Dict, Any
from datetime import date


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    ticker = (kwargs.get("ticker") or "").strip().upper()
    event_type = (kwargs.get("event_type") or "").strip()
    event_date_str = (kwargs.get("event_date") or "").strip()
    if not ticker:
        raise ValueError("Falta param 'ticker'.")
    if not event_type:
        raise ValueError("Falta param 'event_type' (earnings/dividend/etc.).")

    # Días hasta el evento
    days_ahead = None
    try:
        d = date.fromisoformat(event_date_str[:10])
        days_ahead = (d - date.today()).days
    except (TypeError, ValueError):
        days_ahead = None

    # Context del portfolio sobre el ticker
    portfolio_context: Dict[str, Any] = {
        "holds_ticker": False,
        "weight_pct": None,
        "pnl_pct": None,
        "broker": None,
    }
    pos_rows = conn.execute(
        """SELECT broker, quantity, invested FROM positions
            WHERE user_id = ? AND asset = ? AND quantity > 0""",
        (user_id, ticker),
    ).fetchall()

    if pos_rows:
        portfolio_context["holds_ticker"] = True
        try:
            from .position import build as build_position
            pos_dicts = [dict(r) for r in pos_rows]
            pos_dicts.sort(key=lambda p: float(p.get("invested") or 0), reverse=True)
            broker = pos_dicts[0]["broker"]
            p = build_position(conn, user_id, asset=ticker, broker=broker)
            portfolio_context["weight_pct"] = p.get("weight_pct")
            portfolio_context["pnl_pct"] = p.get("pnl_pct")
            portfolio_context["broker"] = broker
        except Exception:
            pass

    return {
        "screen": "events.item",
        "event": {
            "ticker": ticker,
            "type": event_type,
            "date": event_date_str[:10] if event_date_str else None,
            "days_ahead": days_ahead,
            "details": (kwargs.get("details") or "").strip() or None,
        },
        "portfolio_context": portfolio_context,
    }
