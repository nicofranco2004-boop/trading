"""builders.monthly_insight — packet de UN insight chip del MonthCard.
═══════════════════════════════════════════════════════════════════════════
Topic: monthly.insight

Cada mes en Reportes muestra "chips" con insights detectados (ej. "BTC
explicó el 64% del rendimiento", "Win rate del mes: 70%"). El user puede
pedir análisis de UNO específico — éste es el builder de ese flujo.

Approach paralelo a insights.observation: las chips se generan en
detectors.py (backend) y se pasan tal cual al frontend. Acá el frontend
nos manda la chip como params (code, text, severity), y nosotros sumamos
contexto del mes (métricas, headline) para que el LLM tenga material
para profundizar.

Params:
  year: int
  month: int
  code: str          # código del detector (ej. 'gain_concentration')
  text: str          # texto del chip
  severity: str      # 'positive' | 'neutral' | 'warn' | 'critical'

Shape (~900 bytes):
{
  "screen": "monthly.insight",
  "period": {"year": int, "month": int, "label": str},
  "insight": { code, text, severity },
  "month_context": {
    "headline": str,
    "delta_pct": float,
    "delta_usd": float,
    "trades_count": int,
    "win_rate": float | null,
    "vs_sp500_pct": float | null,
    "best_trade": { asset, pnl_usd, pnl_pct } | null,
    "top_driver": { asset, contribution_pct } | null,
  }
}
"""
from __future__ import annotations
from typing import Dict, Any


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    year = kwargs.get("year")
    month = kwargs.get("month")
    code = (kwargs.get("code") or "").strip()
    text = (kwargs.get("text") or "").strip()
    severity = (kwargs.get("severity") or "neutral").strip()

    if year is None or month is None:
        raise ValueError("Faltan params 'year' y 'month'.")
    if not text:
        raise ValueError("Falta param 'text' del insight a analizar.")
    try:
        year = int(year)
        month = int(month)
    except (TypeError, ValueError):
        raise ValueError("year y month deben ser enteros.")

    # Reusamos el builder de monthly general para tener el contexto del
    # mes ya pre-calculado y consistente.
    month_context: Dict[str, Any] = {}
    try:
        from .monthly import build as build_monthly
        full = build_monthly(conn, user_id, year=year, month=month)
        m = full.get("metrics") or {}
        drivers = full.get("top_drivers") or []
        month_context = {
            "headline": full.get("headline"),
            "delta_pct": m.get("delta_pct"),
            "delta_usd": m.get("delta_usd"),
            "trades_count": m.get("trades_count"),
            "win_rate": m.get("win_rate"),
            "vs_sp500_pct": m.get("vs_sp500_pct"),
            "best_trade": full.get("best_trade"),
            "top_driver": drivers[0] if drivers else None,
        }
        period_label = (full.get("period") or {}).get("label") or f"{year:04d}-{month:02d}"
    except Exception:
        period_label = f"{year:04d}-{month:02d}"

    return {
        "screen": "monthly.insight",
        "period": {"year": year, "month": month, "label": period_label},
        "insight": {
            "code": code,
            "text": text,
            "severity": severity,
        },
        "month_context": month_context,
    }
