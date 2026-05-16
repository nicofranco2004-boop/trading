"""builders.behavioral — packet del screen "Comportamiento".
═══════════════════════════════════════════════════════════════════════════
Topic: behavioral

Reusa el detector orchestrator existente (build_behavioral_insights) y
arma un packet compacto con las 12 cards (severidad + value_label +
one_liner). Mantenemos el shape lean para no inflar el prompt; el LLM
solo necesita los códigos / labels / severidades para interpretar.

Shape (~600 bytes):
{
  "screen": "behavioral",
  "summary": {
    "total_detected": int,    # sesgos high+medium
    "total_high": int,
    "total_medium": int,
    "total_positive": int,
    "total_cards": int,
  },
  "cards": [
    { "code": str, "title": str, "severity": str, "detected": bool,
      "value_label": str, "one_liner": str }
  ],
}
"""
from __future__ import annotations
from typing import Dict, Any


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    from behavioral import build_behavioral_insights

    # Datos crudos — mismo dataset que /api/behavioral/insights consume
    ops = [dict(r) for r in conn.execute(
        "SELECT * FROM operations WHERE user_id=? ORDER BY date ASC",
        (user_id,),
    ).fetchall()]
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE user_id=?",
        (user_id,),
    ).fetchall()]

    # Precios actuales — opcional. Si falla, los detectores caen al fallback
    # (invested como proxy de market value).
    prices: Dict[str, float] = {}
    try:
        from home.market import _fetch_batch_quotes
        symbols = list({p["asset"] for p in positions
                        if p.get("asset") and not p.get("is_cash")})
        if symbols:
            quotes = _fetch_batch_quotes(symbols)
            prices = {s: q["price"] for s, q in quotes.items()
                      if q and q.get("price") is not None}
    except Exception:
        prices = {}

    # TC blue del user (para conversión ARS → USD)
    tc_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (user_id,)
    ).fetchone()
    try:
        tc_blue = float(tc_row["value"]) if tc_row and tc_row["value"] else 1415.0
    except (TypeError, ValueError):
        tc_blue = 1415.0
    if tc_blue <= 0:
        tc_blue = 1415.0

    # Inflación AR mensual — last resort para inflation_loss detector
    inflation_monthly: Dict[str, float] = {}
    try:
        import main as _m
        cache_bench = getattr(_m, "_bench_cache", {}) or {}
        if cache_bench.get("data"):
            inflation_monthly = cache_bench["data"].get("inflation_ar") or {}
    except Exception:
        inflation_monthly = {}

    full = build_behavioral_insights(
        operations=ops,
        positions=positions,
        prices=prices,
        inflation_monthly=inflation_monthly,
        tc_blue=tc_blue,
    )

    # Adelgazamos las cards — el LLM no necesita evidence/references/score,
    # solo lo necesario para interpretar y narrar.
    cards = [
        {
            "code": c.get("code"),
            "title": c.get("title"),
            "severity": c.get("severity"),
            "detected": bool(c.get("detected")),
            "value_label": c.get("value_label"),
            "one_liner": c.get("one_liner"),
        }
        for c in full.get("cards", [])
    ]

    return {
        "screen": "behavioral",
        "summary": full.get("summary", {}),
        "cards": cards,
    }
