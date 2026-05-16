"""builders.insights_observation — packet de UNA observación del diagnóstico.
═══════════════════════════════════════════════════════════════════════════
Topic: insights.observation

Las observaciones del diagnóstico de Insights se generan en el FRONTEND
con un set de reglas heurísticas (D1: concentración, D2: drawdown, D3:
big loser, etc.). Replicar esa lógica en backend sería costoso y propenso
a desincronización.

Approach: el frontend pasa la observación tal cual la armó (title, text,
category, level, id) en los `params`. El builder agrega contexto del
portfolio relevante (top holdings, attribution, exposure, drawdown) para
que el LLM pueda elaborar la observación con números concretos.

Params (todos opcionales menos title):
  title: str           # headline de la observación
  text: str            # cuerpo / descripción de la observación
  category: str        # 'Concentración' | 'Drawdown' | 'Riesgo' | etc.
  level: str           # 'danger' | 'warning' | 'info' | 'positive'
  id: str              # 'D1', 'D2', etc. — solo para tracking

Shape:
{
  "screen": "insights.observation",
  "observation": { title, text, category, level, id },
  "portfolio_context": {
    "total_value_usd": float,
    "twr_pct": float | null,
    "drawdown_current_pct": float,
    "drawdown_max_pct": float,
    "top_holdings": [{ ticker, weight_pct, pnl_pct }],
    "top_contributors": [{ ticker, total_usd }],
    "exposure": { cash_pct, ar_pct, us_pct, crypto_pct },
  },
}
"""
from __future__ import annotations
from typing import Dict, Any


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    title = (kwargs.get("title") or "").strip()
    if not title:
        raise ValueError(
            "Falta param 'title' — la observación necesita su headline para "
            "que el LLM pueda elaborarla."
        )

    observation = {
        "title": title,
        "text": (kwargs.get("text") or "").strip(),
        "category": (kwargs.get("category") or "").strip(),
        "level": (kwargs.get("level") or "").strip().lower(),
        "id": (kwargs.get("id") or "").strip(),
    }

    # Contexto del portfolio — reusamos el builder insights general y el
    # de attribution para no duplicar lógica. El cache del LLM agrupa esto
    # por user, así que aunque varias observaciones lo pidan, solo se
    # ejecuta una vez por window.
    portfolio_context: Dict[str, Any] = {}
    try:
        from .insights import build as build_insights_general
        from .insights_attribution import build as build_attribution
        from .dashboard_top_holdings import build as build_top_holdings

        ins = build_insights_general(conn, user_id, window_days=365)
        attr = build_attribution(conn, user_id)
        top = build_top_holdings(conn, user_id)

        portfolio_context = {
            "total_value_usd": top.get("total_value_usd"),
            "twr_pct": ins.get("twr_pct"),
            "drawdown_current_pct": (ins.get("drawdown") or {}).get("current_pct"),
            "drawdown_max_pct": (ins.get("drawdown") or {}).get("max_pct"),
            "top_holdings": [
                {
                    "ticker": h.get("ticker"),
                    "weight_pct": h.get("weight_pct"),
                    "pnl_pct": h.get("pnl_pct"),
                }
                for h in (top.get("top_holdings") or [])[:5]
            ],
            "top_contributors": [
                {"ticker": c.get("ticker"), "total_usd": c.get("total_usd")}
                for c in (attr.get("top_contributors") or [])[:3]
            ],
            "exposure": ins.get("exposure") or {},
        }
    except Exception:
        # Si algo del contexto falla, no rompemos — el LLM puede analizar
        # la observación con menos datos.
        portfolio_context = {}

    return {
        "screen": "insights.observation",
        "observation": observation,
        "portfolio_context": portfolio_context,
    }
