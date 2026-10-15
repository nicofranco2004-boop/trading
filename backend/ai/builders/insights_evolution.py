"""builders.insights_evolution — packet de la curva de evolución del Insights.
═══════════════════════════════════════════════════════════════════════════
Topic: insights.evolution

Sub-componente del Insights — analiza específicamente la trayectoria del
portfolio en el tiempo: TWR período, monthly returns, mejor/peor mes,
consistencia (% de meses positivos).

Shape (~700 bytes):
{
  "screen": "insights.evolution",
  "window_days": int,
  "twr_pct": float | null,           # acumulado — SIEMPRE de `twr.rendimiento_publicable`
  "twr_base": "mercado" | "contable" | null,   # de dónde sale ese número
  "twr_motivo_texto": str | null,    # por qué no se pudo medir a mercado
  "monthly_returns": [         # cada mes, de `twr.rendimientos_mensuales`
    { "month": "YYYY-MM", "return_pct": float, "base": str, "capital_final": float }
  ],
  "best_month": { "month": str, "return_pct": float, "base": str } | null,
  "worst_month": { "month": str, "return_pct": float, "base": str } | null,
  "positive_months": int,
  "total_months": int,
  "consistency_pct": float,    # % de meses con retorno > 0
  "monthly_base": "mercado" | "contable" | null,   # con qué regla se midieron
  "months_not_market": int,    # meses de la ventana que no se midieron a mercado
}
"""
from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import date, timedelta
import twr as _twr


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    window_days = int(kwargs.get("window_days", 365))
    today = date.today()
    cutoff = today - timedelta(days=window_days)

    # ⚠️ CADA MES SE LE PIDE AL MOTOR, IGUAL QUE EL ACUMULADO. Antes salía del
    # Dietz de `monthly_entries`, que para un mes cerrado está AL COSTO: un mes sin
    # ventas daba ~0 % aunque la cartera se hubiera movido mucho, y de ahí salían
    # el mejor mes, el peor y la consistencia. `rendimientos_mensuales` mide a
    # mercado cuando puede y, si no, etiqueta la contabilidad; `mejor_y_peor_mes`
    # no mezcla las dos reglas en el mismo ranking.
    # El mes que TERMINA antes del corte queda afuera: `desde` es el primer día del
    # mes que contiene al corte.
    meses = _twr.rendimientos_mensuales(conn, user_id,
                                        desde=cutoff.replace(day=1).isoformat())
    rk = _twr.mejor_y_peor_mes(meses)
    monthly_returns = [{
        "month": m["mes"],
        "return_pct": round(m["pct"], 2),
        "base": m["base"],
        "capital_final": m["capital_final"],
    } for m in rk["meses"]]
    positive = rk["positivos"]

    def _corto(m):
        return ({"month": m["mes"], "return_pct": round(m["pct"], 2), "base": m["base"]}
                if m else None)

    # ⚠️ EL ACUMULADO SE LE PIDE AL MOTOR, NO SE COMPONE ACÁ (F6).
    #
    # Esto multiplicaba `(1 + ret)` mes a mes sobre `monthly_entries`. MEDIDO sobre
    # la copia de producción del 2026-08-16: 121 usuarios publicaban un acumulado
    # de más de 100 % y el peor llegaba a **+129.544 %** (uid 118), para el que el
    # motor dice **+0,7 %**. El motor no se equivocaba: no lo estaban llamando.
    #
    # Y agregarle `leg_dudoso` a esta composición NO alcanzaba —bajaba el peor a
    # +30.300 %— porque el defecto no es un mes malo suelto: saltear el mes que no
    # se puede medir y seguir encadenando toma la base ya achicada como si fuera
    # continua. Al uid 826 el guard SOLO le SUBÍA el número, de 884 % a 3.983 %.
    #
    # `rendimiento_publicable` mide a mercado cuando puede y, cuando no, publica la
    # contabilidad DICIENDO que es contabilidad. Los meses de abajo se siguen
    # listando tal cual: cada uno por separado es un dato honesto, y lo que estaba
    # mal era el producto.
    _rend = _twr.rendimiento_publicable(conn, user_id, desde=cutoff.isoformat())
    twr_pct: Optional[float] = _rend["pct"]
    total = rk["total"]
    best = _corto(rk["mejor"])
    worst = _corto(rk["peor"])

    return {
        "screen": "insights.evolution",
        "window_days": window_days,
        "twr_pct": twr_pct,
        # De dónde sale el número: 'mercado' (fotos reales) o 'contable' (la cadena
        # de monthly_entries). Sin esto el modelo no puede decir con qué confianza
        # hablar del rendimiento, que es justo lo que se le pide.
        "twr_base": _rend["base"],
        "twr_motivo_texto": _rend["motivo_texto"],
        # Cap a 18 entradas (~1.5 años) para no inflar el prompt
        "monthly_returns": monthly_returns[-18:],
        "best_month": best,
        "worst_month": worst,
        "positive_months": positive,
        "total_months": total,
        "consistency_pct": round((positive / total) * 100, 1) if total > 0 else 0,
        # Con qué regla se midieron los meses de arriba, y cuántos de la ventana
        # no se pudieron medir a mercado (no entran al ranking si hay de mercado).
        "monthly_base": rk["base"],
        "months_not_market": rk["sin_medir_a_mercado"],
    }
