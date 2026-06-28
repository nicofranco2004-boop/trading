"""builders.fundamentals_category — packet de UNA dimensión fundamental de una acción.
═══════════════════════════════════════════════════════════════════════════
Topic: fundamentals.category

Params:
  asset: str       — ticker base (ej. "AAPL", "NVDA", "MELI"). Para CEDEARs el
                     frontend manda el ticker US (sin .BA).
  category: str    — key de la categoría: valuation | growth | profitability |
                     health | dividends.

Reusa _build_fundamentals_response (yfinance, cacheado) — la MISMA fuente que la
ficha y el Resumen IA. No toca la cartera del user: analiza la empresa.

Shape (~600 bytes):
{
  "screen": "fundamentals.category",
  "ticker": str, "company_name": str|null, "sector": str|null,
  "category": str,            # label legible (Precio, Crecimiento, …)
  "category_question": str|null,
  "category_score": int|null, # 0-100 de esa categoría
  "overall_score": int|null,
  "metrics": [ {label, value, status, direction} ... ],
  "price_current_usd": float|null, "fair_value_usd": float|null,
  "margin_of_safety_pct": float|null,
}
"""
from __future__ import annotations
from typing import Dict, Any


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    asset = (kwargs.get("asset") or "").strip().upper()
    category = (kwargs.get("category") or "").strip().lower()
    if not asset:
        raise ValueError("Falta param 'asset' — ticker de la acción.")

    # Lazy import: evita ciclo (registry lo carga lazy desde el endpoint, ya con
    # main cargado), igual que el resto de builders importan helpers adentro.
    from main import _build_fundamentals_response
    data = _build_fundamentals_response(asset)
    if not data or not data.get("available"):
        raise ValueError(f"No hay fundamentales para {asset}.")

    cats = {c.get("key"): c for c in (data.get("score", {}).get("categories") or [])}
    detail = {c.get("key"): c for c in (data.get("categories_detail") or [])}
    cat_head = cats.get(category) or {}
    det = detail.get(category) or {}
    if not cat_head and not det:
        raise ValueError(f"Categoría '{category}' no disponible para {asset}.")

    metrics = [
        {
            "label": m.get("label"),
            "value": m.get("value_label"),
            "status": m.get("status"),          # green | amber | red | na
            "direction": m.get("direction"),    # higher | lower | info
        }
        for m in (det.get("metrics") or [])
        if m.get("value_label") not in (None, "—")
    ]

    price = data.get("price") or {}
    score = cat_head.get("score")
    if score is None:
        score = det.get("score")

    return {
        "screen": "fundamentals.category",
        "ticker": data.get("ticker") or asset,
        "company_name": data.get("company_name"),
        "sector": data.get("sector"),
        "category": det.get("label") or cat_head.get("label") or category,
        "category_question": det.get("question") or cat_head.get("question"),
        "category_score": score,
        "overall_score": (data.get("score") or {}).get("overall"),
        "metrics": metrics,
        "price_current_usd": price.get("current_usd"),
        "fair_value_usd": price.get("fair_value_usd"),
        "margin_of_safety_pct": price.get("margin_of_safety_pct"),
    }
