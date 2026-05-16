"""builders.behavioral_card — packet de UN sesgo específico.
═══════════════════════════════════════════════════════════════════════════
Topic: behavioral.card

Versión "zoom" del topic 'behavioral' — el user clickea el ✦ de una card
puntual (disposition_effect, overtrade, etc.) y queremos un análisis
profundo solo de ese sesgo, no del resumen general.

Params:
  code: str — el código del detector (ver behavioral.py).
              Ej: 'disposition_effect', 'overtrade', 'concentration', etc.

Builder strategy: corre el orchestrator full (build_behavioral_insights),
encuentra la card por código, y devuelve esa card CON TODO el evidence/
references (a diferencia del topic 'behavioral' general que adelgaza).
También sumamos un mini-contexto: las 2-3 cards más relevantes (severidad
high/medium) para que el LLM pueda hacer relación cruzada si aplica.

Shape (~1KB):
{
  "screen": "behavioral.card",
  "card": {
    code, title, severity, detected, score, value_label, one_liner,
    evidence: {...},      # dict completo del detector
    references: [...],    # citas académicas
  },
  "context": {
    "other_active_biases": [
      { "code": str, "title": str, "severity": str, "value_label": str }
    ]
  }
}
"""
from __future__ import annotations
from typing import Dict, Any, List


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    code = (kwargs.get("code") or "").strip().lower()
    if not code:
        raise ValueError("Falta param 'code' (ej. disposition_effect, overtrade, etc.)")

    from behavioral import build_behavioral_insights

    # Datos crudos — mismo dataset que /api/behavioral/insights
    ops = [dict(r) for r in conn.execute(
        "SELECT * FROM operations WHERE user_id=? ORDER BY date ASC", (user_id,)
    ).fetchall()]
    positions = [dict(r) for r in conn.execute(
        "SELECT * FROM positions WHERE user_id=?", (user_id,)
    ).fetchall()]

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

    tc_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='tc_blue'", (user_id,)
    ).fetchone()
    try:
        tc_blue = float(tc_row["value"]) if tc_row and tc_row["value"] else 1415.0
    except (TypeError, ValueError):
        tc_blue = 1415.0
    if tc_blue <= 0:
        tc_blue = 1415.0

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

    cards = full.get("cards", []) or []
    target = next((c for c in cards if (c.get("code") or "").lower() == code), None)
    if not target:
        available = sorted(c.get("code") for c in cards if c.get("code"))
        raise ValueError(
            f"Code '{code}' no existe. Disponibles: {available}"
        )

    # Contexto: otras cards activas (high/medium) para que el LLM pueda
    # mencionar correlaciones si aplica. Sin evidence — solo el header.
    others = [
        {
            "code": c.get("code"),
            "title": c.get("title"),
            "severity": c.get("severity"),
            "value_label": c.get("value_label"),
        }
        for c in cards
        if c.get("code") != code
        and c.get("severity") in ("high", "medium")
    ]

    return {
        "screen": "behavioral.card",
        "card": {
            "code": target.get("code"),
            "title": target.get("title"),
            "severity": target.get("severity"),
            "detected": bool(target.get("detected")),
            "score": target.get("score"),
            "value_label": target.get("value_label"),
            "one_liner": target.get("one_liner"),
            "evidence": target.get("evidence") or {},
            "references": target.get("references") or [],
            "insufficient_data": bool(target.get("insufficient_data")),
        },
        "context": {
            "other_active_biases": others[:4],
        },
    }
