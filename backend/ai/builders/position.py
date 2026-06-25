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

    # Valuación canónica de Análisis (MEP para holdings AR/.BA; CEDEAR en
    # sub-broker '· USD' por su .BA, NO el ticker US → fix C1). Cargamos TODAS las
    # posiciones una vez: para valuar la pedida y el total de cartera (weight) con
    # la misma fuente de precios. currency_context estampa currency in-place.
    from analysis_prep import currency_context
    from behavioral import _position_value_usd, _resolve_price, _price_is_ars
    all_pos = [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE user_id=?", (user_id,)
    ).fetchall()]
    prices, tc_blue, tc_cedear = currency_context(conn, user_id, all_pos)

    # Subconjunto pedido (de all_pos ya estampado) — match por asset (+ broker).
    positions = [
        p for p in all_pos
        if (p.get("asset") or "").strip() == asset
        and (not broker or (p.get("broker") or "").strip() == broker)
        and float(p.get("quantity") or 0) > 0
    ]
    if not positions:
        raise ValueError(
            f"Posición no encontrada para asset='{asset}' broker='{broker or '*'}'."
        )

    qty = sum(float(p.get("quantity") or 0) for p in positions)
    invested = sum(float(p.get("invested") or 0) for p in positions)
    broker_resolved = positions[0].get("broker") or broker
    currency = (positions[0].get("currency") or "USD").upper()

    invested_usd = sum(
        _position_value_usd(p, {}, tc_blue, tc_cedear, honor_override=False)
        for p in positions
    )
    current_value_usd = sum(
        _position_value_usd(p, prices, tc_blue, tc_cedear) for p in positions
    )
    avg_price = (invested / qty) if qty > 0 else None
    # Precio actual por unidad, en moneda nativa (.BA ARS para AR, US$ para USD).
    p0 = positions[0]
    current_price = _resolve_price(
        (p0.get("asset") or "").upper(), p0.get("broker"), prices,
        is_ars=_price_is_ars(p0),
    )
    pnl_usd = current_value_usd - invested_usd
    pnl_pct = (pnl_usd / invested_usd * 100) if invested_usd > 0 else None

    # Weight % vs total de cartera (cost basis canónico, misma moneda/MEP).
    total_value = sum(
        _position_value_usd(p, {}, tc_blue, tc_cedear, honor_override=False)
        for p in all_pos
    )
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
