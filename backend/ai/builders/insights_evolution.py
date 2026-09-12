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
  "monthly_returns": [
    { "month": "YYYY-MM", "return_pct": float, "capital_final": float }
  ],
  "best_month": { "month": str, "return_pct": float } | null,
  "worst_month": { "month": str, "return_pct": float } | null,
  "positive_months": int,
  "total_months": int,
  "consistency_pct": float,    # % de meses con retorno > 0
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

    rows = conn.execute(
        """SELECT year, month, capital_inicio, capital_final, deposits, withdrawals
             FROM monthly_entries
            WHERE user_id=? AND broker='global'
            ORDER BY year, month""",
        (user_id,),
    ).fetchall()

    monthly_returns = []
    positive = 0
    for r in rows:
        y, m = r["year"], r["month"]
        try:
            end_of_month = date(y, m + 1, 1) - timedelta(days=1) if m < 12 else date(y, 12, 31)
        except ValueError:
            continue
        if end_of_month < cutoff:
            continue
        ci = float(r["capital_inicio"] or 0)
        cf = float(r["capital_final"] or 0)
        dep = float(r["deposits"] or 0)
        wd = float(r["withdrawals"] or 0)
        # El retorno del mes con sus dos guards (el mes de alta no se mide; el
        # denominador lleva el 0,5 del flujo). Ver `twr.retorno_mensual`.
        ret = _twr.retorno_mensual(ci, cf, dep - wd)
        if ret is None:
            continue
        if ret < -0.95 or ret > 5:
            continue
        if ret > 0:
            positive += 1
        monthly_returns.append({
            "month": f"{y:04d}-{m:02d}",
            "return_pct": round(ret * 100, 2),
            "capital_final": round(cf, 2),
        })

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
    total = len(monthly_returns)
    best = max(monthly_returns, key=lambda x: x["return_pct"]) if monthly_returns else None
    worst = min(monthly_returns, key=lambda x: x["return_pct"]) if monthly_returns else None

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
    }
