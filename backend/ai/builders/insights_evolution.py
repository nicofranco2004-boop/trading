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
  "twr_pct": float | null,
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
    compound = 1.0
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
        if ci <= 0:
            continue
        ret = ((cf - dep + wd) / ci) - 1
        if ret < -0.95 or ret > 5:
            continue
        compound *= (1 + ret)
        if ret > 0:
            positive += 1
        monthly_returns.append({
            "month": f"{y:04d}-{m:02d}",
            "return_pct": round(ret * 100, 2),
            "capital_final": round(cf, 2),
        })

    twr_pct: Optional[float] = (
        round((compound - 1) * 100, 2) if monthly_returns else None
    )
    total = len(monthly_returns)
    best = max(monthly_returns, key=lambda x: x["return_pct"]) if monthly_returns else None
    worst = min(monthly_returns, key=lambda x: x["return_pct"]) if monthly_returns else None

    return {
        "screen": "insights.evolution",
        "window_days": window_days,
        "twr_pct": twr_pct,
        # Cap a 18 entradas (~1.5 años) para no inflar el prompt
        "monthly_returns": monthly_returns[-18:],
        "best_month": best,
        "worst_month": worst,
        "positive_months": positive,
        "total_months": total,
        "consistency_pct": round((positive / total) * 100, 1) if total > 0 else 0,
    }
