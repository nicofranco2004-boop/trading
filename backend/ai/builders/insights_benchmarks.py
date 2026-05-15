"""builders.insights_benchmarks — packet de comparación vs benchmarks.
═══════════════════════════════════════════════════════════════════════════
Topic: insights.benchmarks

Sub-componente del Insights — análisis específico de cómo te fue vs los
3 benchmarks que tiene el producto: S&P 500 (USD), inflación AR (ARS),
y dólar blue (peso real). Reusa el cálculo del topic 'insights' pero
enfocado solo en esta comparación.

Shape (~600 bytes):
{
  "screen": "insights.benchmarks",
  "window_days": int,
  "user_return_pct": float | null,
  "benchmarks": {
    "sp500_pct": float | null,
    "inflation_ar_pct": float | null,
    "dolar_blue_pct": float | null,
  },
  "deltas_pp": {
    "vs_sp500": float | null,    # points = user - benchmark
    "vs_inflation": float | null,
    "vs_dolar_blue": float | null,
  },
  "outperform": {
    "sp500": bool | null,
    "inflation": bool | null,
    "dolar_blue": bool | null,
  },
}
"""
from __future__ import annotations
from typing import Dict, Any, Optional
from datetime import date, timedelta


def _compute_user_twr(conn, user_id: int, window_days: int) -> Optional[float]:
    """TWR del user via monthly_entries (broker='global') — compoundea retornos
    mensuales aislando flujos. Idéntico al del builder 'insights' general."""
    today = date.today()
    cutoff = today - timedelta(days=window_days)
    rows = conn.execute(
        """SELECT year, month, capital_inicio, capital_final, deposits, withdrawals
             FROM monthly_entries
            WHERE user_id=? AND broker='global'
            ORDER BY year, month""",
        (user_id,),
    ).fetchall()
    compound = 1.0
    used = 0
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
        used += 1
    if used == 0:
        return None
    return round((compound - 1) * 100, 2)


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    window_days = int(kwargs.get("window_days", 365))
    today = date.today()
    cutoff = today - timedelta(days=window_days)
    cutoff_ym = cutoff.strftime("%Y-%m")

    user_pct = _compute_user_twr(conn, user_id, window_days)

    sp500_pct: Optional[float] = None
    inflation_pct: Optional[float] = None
    dolar_pct: Optional[float] = None
    try:
        import main as _m
        cache_bench = getattr(_m, "_bench_cache", {}) or {}
        data = cache_bench.get("data") or {}

        sp = data.get("sp500") or {}
        infl = data.get("inflation_ar") or {}
        # Dólar blue: en el bench cache aparece como serie {YYYY-MM-DD: precio}.
        blue = data.get("dolar_blue") or {}

        # S&P: % change desde primer close ≥ cutoff
        sp_window = sorted([(k, v) for k, v in sp.items() if k >= cutoff_ym])
        if len(sp_window) >= 2 and sp_window[0][1]:
            sp500_pct = round((sp_window[-1][1] - sp_window[0][1]) / sp_window[0][1] * 100, 2)

        # Inflación: compound de los % mensuales
        infl_window = sorted([(k, v) for k, v in infl.items() if k >= cutoff_ym])
        if infl_window:
            comp = 1.0
            for _, pct in infl_window:
                comp *= (1 + pct / 100)
            inflation_pct = round((comp - 1) * 100, 2)

        # Dólar blue: % change desde primera fecha ≥ cutoff
        cutoff_iso = cutoff.isoformat()
        blue_window = sorted([(k, v) for k, v in blue.items() if k >= cutoff_iso])
        if len(blue_window) >= 2 and blue_window[0][1]:
            dolar_pct = round((blue_window[-1][1] - blue_window[0][1]) / blue_window[0][1] * 100, 2)
    except Exception:
        pass

    def _delta(u, b):
        return round(u - b, 2) if (u is not None and b is not None) else None

    deltas = {
        "vs_sp500": _delta(user_pct, sp500_pct),
        "vs_inflation": _delta(user_pct, inflation_pct),
        "vs_dolar_blue": _delta(user_pct, dolar_pct),
    }
    outperform = {
        "sp500": (deltas["vs_sp500"] > 0) if deltas["vs_sp500"] is not None else None,
        "inflation": (deltas["vs_inflation"] > 0) if deltas["vs_inflation"] is not None else None,
        "dolar_blue": (deltas["vs_dolar_blue"] > 0) if deltas["vs_dolar_blue"] is not None else None,
    }

    return {
        "screen": "insights.benchmarks",
        "window_days": window_days,
        "user_return_pct": user_pct,
        "benchmarks": {
            "sp500_pct": sp500_pct,
            "inflation_ar_pct": inflation_pct,
            "dolar_blue_pct": dolar_pct,
        },
        "deltas_pp": deltas,
        "outperform": outperform,
    }
