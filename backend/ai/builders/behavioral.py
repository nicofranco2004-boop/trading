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
    from analysis_prep import currency_context

    # Datos crudos — mismo dataset que /api/behavioral/insights consume
    ops = [dict(r) for r in conn.execute(
        "SELECT * FROM operations WHERE user_id=? ORDER BY date ASC",
        (user_id,),
    ).fetchall()]
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE user_id=?",
        (user_id,),
    ).fetchall()]

    # Prep money-critical: estampa moneda por broker, arma precios .BA-aware y
    # resuelve tc_blue (cash) + tc_cedear (MEP, holdings AR). Si los precios
    # fallan, los detectores caen al fallback (invested como proxy).
    prices, tc_blue, tc_cedear = currency_context(conn, user_id, positions, ops)

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
        tc_cedear=tc_cedear,
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
