"""Prep compartido de moneda para TODO caller que valúe posiciones en la sección
Análisis y adyacentes (goals, wrapped, builders de IA del comportamiento).

Centraliza la resolución money-critical de moneda para que NINGÚN caller la
olvide (era la causa de que el fix de moneda no llegara a goals/wrapped/builders):
  - estampa positions/ops con brokers.currency (evita que ARS de un broker AR
    fuera de la lista de hints se cuente como USD ~1415×),
  - arma símbolos '.BA' para holdings de brokers AR (precio en pesos),
  - devuelve tc_blue (cash en pesos) y tc_cedear=MEP (holdings AR/.BA).

Uso típico:
    prices, tc_blue, tc_cedear = currency_context(conn, uid, positions, ops)
    out = build_behavioral_insights(ops, positions, prices, infl, tc_blue, tc_cedear)
"""
from typing import Dict, List, Any, Optional, Tuple

from behavioral import stamp_positions_currency, _is_ars_broker


def _config_float(conn, user_id: int, key: str, default: float) -> float:
    row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key=?", (user_id, key)
    ).fetchone()
    try:
        v = float(row["value"]) if row and row["value"] else default
    except (TypeError, ValueError):
        v = default
    return v if v > 0 else default


def user_fx(conn, user_id: int) -> Tuple[float, float]:
    """(tc_blue, tc_cedear). tc_cedear (dólar-MEP) cae a tc_blue si no hay 'tc_mep'."""
    tc_blue = _config_float(conn, user_id, "tc_blue", 1415.0)
    tc_cedear = _config_float(conn, user_id, "tc_mep", tc_blue)
    return tc_blue, tc_cedear


def fetch_ba_aware_prices(positions: List[Dict[str, Any]]) -> Dict[str, float]:
    """Precios live; pide '<asset>.BA' (ARS) para holdings de brokers AR — es lo
    que _resolve_price busca para esos brokers. Sin esto, toda posición AR cae a
    costo de compra (y recency_bias las descarta)."""
    from home.market import _fetch_batch_quotes
    symbols = set()
    for p in positions:
        if not p.get("asset") or p.get("is_cash"):
            continue
        a = p["asset"]
        if _is_ars_broker(p.get("broker")) and not a.upper().endswith(".BA"):
            symbols.add(a + ".BA")
        else:
            symbols.add(a)
    if not symbols:
        return {}
    try:
        quotes = _fetch_batch_quotes(list(symbols))
        return {s: q["price"] for s, q in quotes.items()
                if q and q.get("price") is not None}
    except Exception:
        return {}


def currency_context(conn, user_id: int,
                     positions: List[Dict[str, Any]],
                     ops: Optional[List[Dict[str, Any]]] = None,
                     *, fetch_prices: bool = True
                     ) -> Tuple[Dict[str, float], float, float]:
    """Estampa positions (y ops si se pasan) con brokers.currency in-place, arma
    los precios .BA-aware y devuelve (prices, tc_blue, tc_cedear).

    Llamar ANTES de valuar o de build_behavioral_insights. operations comparte
    las claves 'broker'/'currency' con positions, así que el mismo estampado
    resuelve la moneda nativa de las ops (que _position_size_usd necesita)."""
    broker_ccy = {
        r["name"]: (r["currency"] or "")
        for r in conn.execute(
            "SELECT name, currency FROM brokers WHERE user_id=?", (user_id,)
        ).fetchall()
    }
    stamp_positions_currency(positions, broker_ccy)
    if ops:
        stamp_positions_currency(ops, broker_ccy)
    tc_blue, tc_cedear = user_fx(conn, user_id)
    prices = fetch_ba_aware_prices(positions) if fetch_prices else {}
    return prices, tc_blue, tc_cedear
