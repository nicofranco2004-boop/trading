"""builders.position — packet de UNA posición individual.
═══════════════════════════════════════════════════════════════════════════
Topic: position

Params:
  asset: str    — ticker exacto (ej. "NVDA", "AAVE/USDT", "MELI")
  broker: str   — nombre del broker para desambiguar la misma posición en
                  cuentas distintas (ej. "Schwab", "Cocos Capital")

Shape (~700 bytes):
{
  "screen": "position",
  "asset": str,
  "broker": str,
  "currency": str,
  "qty": float,
  "avg_price": float | null,
  "current_price": float | null,
  "invested_usd": float,
  "current_value_usd": float,
  "pnl_usd": float,
  "pnl_pct": float | null,
  "weight_pct": float | null,
  "days_held": int | null,
  "lots_count": int,
}
"""
from __future__ import annotations
from typing import Dict, Any
from datetime import datetime, date


_AR_BROKERS = {"cocos", "iol", "bull", "balanz", "naranja", "pppi", "invertironline", "lemon"}


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    asset = (kwargs.get("asset") or "").strip()
    broker = (kwargs.get("broker") or "").strip()
    if not asset:
        raise ValueError("Falta param 'asset' — ticker exacto de la posición.")

    # Posición agregada (qty, invested) — match por asset (+ broker si viene)
    if broker:
        rows = conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND asset=? AND broker=? AND quantity > 0",
            (user_id, asset, broker),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM positions WHERE user_id=? AND asset=? AND quantity > 0",
            (user_id, asset),
        ).fetchall()

    positions = [dict(r) for r in rows]
    if not positions:
        raise ValueError(
            f"Posición no encontrada para asset='{asset}' broker='{broker or '*'}'."
        )

    qty = sum(float(p.get("quantity") or 0) for p in positions)
    invested = sum(float(p.get("invested") or 0) for p in positions)
    broker_resolved = positions[0].get("broker") or broker

    # Currency del broker
    brokers_row = conn.execute(
        "SELECT currency FROM brokers WHERE user_id=? AND name=?",
        (user_id, broker_resolved),
    ).fetchone()
    currency = (brokers_row["currency"] or "USD").upper() if brokers_row else "USD"
    is_ars = currency == "ARS"

    # TC blue
    tc_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (user_id,)
    ).fetchone()
    try:
        tc_blue = float(tc_row["value"]) if tc_row and tc_row["value"] else 1415.0
    except (TypeError, ValueError):
        tc_blue = 1415.0
    if tc_blue <= 0:
        tc_blue = 1415.0

    invested_usd = invested / tc_blue if is_ars else invested
    avg_price = (invested / qty) if qty > 0 else None

    # Precio actual
    current_price = None
    try:
        from home.market import _fetch_batch_quotes
        symbol = f"{asset}.BA" if is_ars else asset
        quotes = _fetch_batch_quotes([symbol])
        q = quotes.get(symbol) or {}
        if q.get("price"):
            current_price = float(q["price"])
    except Exception:
        current_price = None

    current_value_usd = (current_price * qty) / tc_blue if (current_price and is_ars) else (
        current_price * qty if current_price else invested_usd
    )
    pnl_usd = current_value_usd - invested_usd
    pnl_pct = (pnl_usd / invested_usd * 100) if invested_usd > 0 else None

    # Weight % vs cartera total
    all_pos = conn.execute(
        "SELECT broker, quantity, invested, is_cash FROM positions WHERE user_id=?",
        (user_id,),
    ).fetchall()
    brokers_currency = {}
    for r in conn.execute("SELECT name, currency FROM brokers WHERE user_id=?", (user_id,)):
        brokers_currency[r["name"]] = (r["currency"] or "USD").upper()

    total_value = 0.0
    for p in all_pos:
        v = float(p["invested"] or 0)
        if brokers_currency.get(p["broker"], "USD") == "ARS":
            v = v / tc_blue
        total_value += v
    weight_pct = (current_value_usd / total_value * 100) if total_value > 0 else None

    # Días en posición (primer Compra del ticker)
    days_held = None
    first_op = conn.execute(
        """SELECT date FROM operations
            WHERE user_id=? AND asset=? AND op_type IN ('Compra')
            ORDER BY date ASC LIMIT 1""",
        (user_id, asset),
    ).fetchone()
    if first_op and first_op["date"]:
        try:
            d0 = datetime.fromisoformat(str(first_op["date"])[:10]).date()
            days_held = (date.today() - d0).days
        except (TypeError, ValueError):
            days_held = None

    # Cantidad de lotes (operaciones Compra del ticker)
    lots_count = int(conn.execute(
        """SELECT COUNT(*) AS c FROM operations
            WHERE user_id=? AND asset=? AND op_type='Compra'""",
        (user_id, asset),
    ).fetchone()["c"])

    return {
        "screen": "position",
        "asset": asset,
        "broker": broker_resolved,
        "currency": currency,
        "qty": round(qty, 6),
        "avg_price": round(avg_price, 4) if avg_price is not None else None,
        "current_price": round(current_price, 4) if current_price is not None else None,
        "invested_usd": round(invested_usd, 2),
        "current_value_usd": round(current_value_usd, 2),
        "pnl_usd": round(pnl_usd, 2),
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "weight_pct": round(weight_pct, 2) if weight_pct is not None else None,
        "days_held": days_held,
        "lots_count": lots_count,
    }
