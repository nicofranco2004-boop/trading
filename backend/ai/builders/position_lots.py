"""builders.position_lots — packet del historial de operaciones de una posición.
═══════════════════════════════════════════════════════════════════════════
Topic: position.lots

Params: asset, broker (opcional)
"""
from __future__ import annotations
from typing import Dict, Any


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    asset = (kwargs.get("asset") or "").strip()
    if not asset:
        raise ValueError("Falta param 'asset'.")
    broker = (kwargs.get("broker") or "").strip()

    if broker:
        rows = conn.execute(
            """SELECT date, op_type, entry_price, exit_price, quantity, pnl_usd
                 FROM operations
                WHERE user_id=? AND asset=? AND broker=?
                ORDER BY date ASC""",
            (user_id, asset, broker),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT date, op_type, entry_price, exit_price, quantity, pnl_usd, broker
                 FROM operations
                WHERE user_id=? AND asset=?
                ORDER BY date ASC""",
            (user_id, asset),
        ).fetchall()

    lots = []
    total_buy_qty = 0.0
    total_buy_value = 0.0
    closes = 0
    for r in rows:
        # sqlite3.Row no tiene .get() — usar dict() o el acceso por índice
        # con try/except. Convertimos a dict para uniformar y poder probar
        # con .get() seguro.
        rd = dict(r)
        op_type = (rd.get("op_type") or "").strip()
        qty = float(rd.get("quantity") or 0)
        entry = float(rd.get("entry_price") or 0)
        exit_p = rd.get("exit_price")
        pnl = rd.get("pnl_usd")
        price = float(exit_p) if exit_p is not None else entry
        lot = {
            "date": str(rd.get("date"))[:10] if rd.get("date") else None,
            "op_type": op_type,
            "price": round(price, 4),
            "qty": round(qty, 6),
        }
        if pnl is not None:
            lot["pnl_usd"] = round(float(pnl), 2)
            closes += 1
        lots.append(lot)
        if op_type == "Compra":
            total_buy_qty += qty
            total_buy_value += entry * qty

    avg_buy_price = (total_buy_value / total_buy_qty) if total_buy_qty > 0 else None

    # Pattern: averaging up / down / mixto
    pattern = "single"
    buys = [l for l in lots if l["op_type"] == "Compra"]
    if len(buys) >= 2:
        prices = [b["price"] for b in buys]
        diffs = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
        up = sum(1 for d in diffs if d > 0)
        down = sum(1 for d in diffs if d < 0)
        if down > up:
            pattern = "averaging_down"
        elif up > down:
            pattern = "averaging_up"
        else:
            pattern = "mixed"

    return {
        "screen": "position.lots",
        "asset": asset,
        "broker": broker or None,
        "total_qty_bought": round(total_buy_qty, 6),
        "avg_buy_price": round(avg_buy_price, 4) if avg_buy_price else None,
        "lots_count": len(lots),
        "closes_count": closes,
        "pattern": pattern,
        # Cap a 15 lots para no inflar el prompt
        "lots": lots[:15],
    }
