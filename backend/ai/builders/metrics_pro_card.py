"""builders.metrics_pro_card — packet de UNA card de Métricas Pro.
═══════════════════════════════════════════════════════════════════════════
Topic: metrics_pro.card

Las métricas pro (Sharpe, Sortino, Alpha, IR, Beta, Volatilidad, CAGR, Calmar)
se calculan en el frontend porque dependen de la moneda seleccionada por el
user (USD vs ARS) y de los benchmarks ya en cache. Replicarlas en Python
sería duplicar ~200 líneas de fórmulas.

Estrategia: el frontend manda los valores ya calculados como params. El
backend confía en esos params (son del propio user, no hay vector de abuso —
manipular en devtools solo afecta la respuesta de su propia IA).

Params esperados:
  code: 'sharpe' | 'sortino' | 'alpha' | 'ir' | 'beta' | 'volatility' | 'cagr' | 'calmar'
  value: number (el valor visible de la card)
  months: int (sample size)
  # opcionales según code:
  rf_annual, return_annual, downside_dev, alpha_annual, beta, r_squared,
  active_return, tracking_error, total_growth, cagr_annual, max_drawdown_pct

Contexto adicional:
  El builder también pesca el `globalMonthly` del user para que el LLM tenga
  visibilidad del rango temporal real y pueda razonar sobre el peor mes, etc.

Shape (~0.7KB):
{
  "screen": "metrics_pro.card",
  "code": "sharpe",
  "metric": {
    "title": "Sharpe Ratio",
    "value": 1.2,
    "months": 11,
    # campos específicos del code, lo que mandó el frontend
  },
  "context": {
    "currency": "USD",
    "n_months_loaded": int,
    "date_range": { "from": "2025-04", "to": "2026-05" },
    "monthly_pnl_range_usd": [worst, best],
  }
}
"""
from __future__ import annotations
from typing import Dict, Any


_CARD_TITLES = {
    "volatility": "Volatilidad anualizada",
    "beta":       "Beta (vs S&P 500)",
    "cagr":       "CAGR anualizado",
    "sharpe":     "Sharpe Ratio",
    "sortino":    "Sortino Ratio",
    "alpha":      "Alpha (vs S&P 500)",
    "ir":         "Information Ratio",
    "calmar":     "Calmar Ratio",
}

_VALID_CODES = set(_CARD_TITLES.keys())


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    code = (kwargs.get("code") or "").strip().lower()
    if code not in _VALID_CODES:
        raise ValueError(
            f"code '{code}' inválido. Válidos: {sorted(_VALID_CODES)}"
        )

    # Métricas vienen como params del frontend (precomputadas). El builder
    # las pasa al LLM tal cual; no las recomputa (duplicaría lógica de
    # insightsMetrics.js). Si falta algún param, el LLM lo notará y razonará
    # sobre lo que hay — no inventa números faltantes.
    metric = {
        "title": _CARD_TITLES[code],
        "value": kwargs.get("value"),
        "months": kwargs.get("months"),
    }
    # Campos extras según code — solo los seteamos si vienen en params,
    # así el LLM no recibe nulls innecesarios para tier no aplicable.
    extras_by_code = {
        "volatility": ["volatility_annual_pct"],
        "beta":       ["beta", "r_squared_pct"],
        "cagr":       ["total_growth_pct", "cagr_annual_pct"],
        "sharpe":     ["return_annual_pct", "rf_annual_pct"],
        "sortino":    ["return_annual_pct", "rf_annual_pct", "downside_dev_pct"],
        "alpha":      ["alpha_annual_pct", "beta", "r_squared_pct"],
        "ir":         ["active_return_pct", "tracking_error_pct"],
        "calmar":     ["cagr_annual_pct", "max_drawdown_pct"],
    }
    for k in extras_by_code.get(code, []):
        if k in kwargs and kwargs[k] is not None:
            metric[k] = kwargs[k]

    # ── Contexto: rango temporal y peor/mejor mes del user ──────────────
    # No requerimos para el cálculo (ya viene precomputado en metric.value)
    # pero ayuda al LLM a contextualizar "tu peor mes fue -8% en feb 2026".
    monthly_rows = conn.execute(
        """SELECT year, month, deposits, withdrawals, pnl_realized, pnl_unrealized
             FROM monthly_entries
            WHERE user_id = ? AND broker = 'global'
            ORDER BY year ASC, month ASC""",
        (user_id,),
    ).fetchall()

    n_months = len(monthly_rows)
    date_range = None
    monthly_pnl_range = None
    if n_months > 0:
        first = monthly_rows[0]
        last = monthly_rows[-1]
        date_range = {
            "from": f"{first['year']}-{int(first['month']):02d}",
            "to":   f"{last['year']}-{int(last['month']):02d}",
        }
        pnls = []
        for r in monthly_rows:
            pnl = (r["pnl_realized"] or 0) + (r["pnl_unrealized"] or 0)
            pnls.append(pnl)
        if pnls:
            monthly_pnl_range = {
                "worst_usd": round(min(pnls), 2),
                "best_usd":  round(max(pnls), 2),
            }

    # Currency: leemos el config del user (default USD)
    cur_row = conn.execute(
        "SELECT value FROM config WHERE user_id=? AND key='display_currency'",
        (user_id,),
    ).fetchone()
    currency = (cur_row["value"] if cur_row and cur_row["value"] else "USD")

    return {
        "screen": "metrics_pro.card",
        "code": code,
        "metric": metric,
        "context": {
            "currency": currency,
            "n_months_loaded": n_months,
            "date_range": date_range,
            "monthly_pnl_range": monthly_pnl_range,
        },
    }
