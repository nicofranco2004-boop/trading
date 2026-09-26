"""builders.insights_drawdown — packet de drawdown / riesgo del Insights.
═══════════════════════════════════════════════════════════════════════════
Topic: insights.drawdown — el ✦ de la tarjeta "Curva de drawdown" de Métricas:
"¿Cuál fue mi peor caída y cuánto tardé en recuperarla?".

Caídas desde el máximo, la peor de la historia medida, cuánto tardó en
recuperarse cada una. TODO MEDIDO COMO RENDIMIENTO (`caida_medida`, sobre
`twr.curva_indexada`): un retiro no es una caída ni un depósito una subida. Son
los mismos "Actual" y "Máx histórico" que muestra la tarjeta.

⚠️ Hasta 2026-09 esto se medía sobre el VALOR de la cartera: sacar la mitad de
la plata con el mercado quieto era "una caída del 50 %". Ver la cabecera de
`caida_medida.py`.

Params (los manda AskAIAbout desde Insights.jsx):
    moneda      — 'usd' | 'ars', la del selector de la pantalla
    valor_live  — la cartera de ahora en USD, la misma que cierra la curva
    window_days — lo mandaban versiones anteriores de la página; se ignora: la
                  tarjeta mide toda la historia ("Máx histórico"), y el paquete
                  declara la ventana real en `medido_desde`/`medido_hasta`.

Shape (~700 bytes):
{
  "screen": "insights.drawdown",
  "que_es": str,
  "moneda": "usd" | "ars",
  "medido_desde": str | null, "medido_hasta": str | null,
  "incluye_hoy": bool,          # la curva cierra con la cartera de ahora
  "current_pct": float | null,  # caída actual desde el máximo (0 = en el máximo)
  "max_pct": float | null,      # peor caída de la historia medida
  "max_date": str | null,       # el fondo de la peor caída
  "max_peak_date": str | null,  # el pico desde el que cayó
  "days_since_peak": int | null,
  "recovered": bool | null,     # ¿volvió al pico después de la peor caída?
  "worst_event": {...} | null,  # la peor caída, con la forma de dd_events
  "dd_events": [                # caídas de más de 5 %, las 5 más profundas
    { "start_date", "trough_date", "end_date" | null, "depth_pct",
      "duration_days", "recovery_days" | null }
  ],
  "events_count": int,
  "insufficient_data": true, "reason": str,   # sólo si no se puede medir
}
"""
from __future__ import annotations

from typing import Any, Dict

from . import caida_medida


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    m = caida_medida.medir(conn, user_id, moneda=kwargs.get("moneda"),
                           valor_live=kwargs.get("valor_live"))
    episodios = m.pop("episodios")
    eventos = [e for e in episodios if e["depth_pct"] <= caida_medida.UMBRAL_EVENTO_PCT]
    return {
        "screen": "insights.drawdown",
        **m,
        # Cap a los 5 eventos más profundos para no inflar
        "dd_events": sorted(eventos, key=lambda e: e["depth_pct"])[:5],
        "events_count": len(eventos),
    }
