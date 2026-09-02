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


def _bench_pct_entre(bench: list, curva: list, desde: str, hasta: str):
    """Retorno del benchmark entre dos fechas de la curva (los puntos de
    `perf.benchmark` van alineados uno a uno con `perf.curva`)."""
    if not bench or not curva or not desde or not hasta:
        return None
    idx_por_fecha = {}
    for p, b in zip(curva, bench):
        if isinstance(b, dict) and b.get("index") is not None:
            idx_por_fecha[str(p.get("date"))] = float(b["index"])
    i0, i1 = idx_por_fecha.get(str(desde)), idx_por_fecha.get(str(hasta))
    if i1 is None and "hoy" in idx_por_fecha and str(hasta) == "hoy":
        i1 = idx_por_fecha["hoy"]
    if not i0 or i1 is None:
        return None
    return round((i1 / i0 - 1) * 100, 2)


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    """⚠️ EL MISMO NÚMERO QUE LA PANTALLA. Este packet calculaba un TERCER
    rendimiento: la cadena contable de `monthly_entries` con los meses fuera de
    [−95 %, +500 %] descartados en silencio, contra el S&P desde el primer cierre
    MENSUAL posterior al cutoff. Ni el Certero ni el Estimado de Métricas mostraban
    ese número, así que el chat podía afirmar "le ganaste al S&P" con un dato que
    ninguna posición del toggle publica (AUDIT_benchmark_2026-09-01 §2.6).

    Ahora sale de `performance.performance`, la MISMA fuente que el gráfico: el
    TWR publicado del modo Certero (si no hay medición, el del Estimado, y se
    declara `basis='contable'`), y el S&P entre las MISMAS dos fechas que ese
    número, del benchmark diario. `window_days` se conserva por compatibilidad
    del packet, pero la ventana real es la que el motor declara
    (`window_from`/`window_to`): un número medido sobre un período publicado
    como si fuera de otro es exactamente el defecto de esta familia.
    """
    window_days = int(kwargs.get("window_days", 365))
    today = date.today()

    user_pct: Optional[float] = None
    sp500_pct: Optional[float] = None
    inflation_pct: Optional[float] = None
    dolar_pct: Optional[float] = None
    basis: Optional[str] = None
    window_from = window_to = None
    excluye_no_realizado = False

    data: Dict[str, Any] = {}
    try:
        import main as _m
        cache_bench = getattr(_m, "_bench_cache", {}) or {}
        data = cache_bench.get("data") or {}
    except Exception:
        data = {}

    try:
        import performance as _perf
        import twr as _twr
        perf = None
        for modo in (_twr.MODO_CERTERO, _twr.MODO_ESTIMADO):
            p = _perf.performance(conn, user_id, data, bench_key="sp500", modo=modo)
            if p.get("twr") is not None:
                perf = p
                break
        if perf is not None:
            window_from, window_to = perf.get("ventana_desde"), perf.get("ventana_hasta")
            # ⚠️ VENTANA MÍNIMA. Medido en la copia de producción: el fallback al
            # Estimado devolvía ventanas de DOS DÍAS (2026-08-14 → 08-16, +0,09 %)
            # y el modelo compararía eso contra el S&P como si fuera un período.
            # Menos de 28 días no es una comparación: se publica la ventana y el
            # motivo, no el número.
            _d0 = str(window_from or "")[:10]
            _d1 = (today.isoformat() if str(window_to) in ("hoy", "None", "")
                   else str(window_to)[:10])
            try:
                _dias = (date.fromisoformat(_d1) - date.fromisoformat(_d0)).days
            except ValueError:
                _dias = 0
            if _dias >= 28:
                user_pct = round(float(perf["twr"]) * 100, 2)
                basis = perf.get("base_del_twr")
                excluye_no_realizado = bool(perf.get("excluye_no_realizado"))
                sp500_pct = _bench_pct_entre(perf.get("benchmark"), perf.get("curva"),
                                             window_from, window_to)
            else:
                basis = "ventana_corta"
                window_from = window_to = None
    except Exception:
        perf = None

    # Inflación y blue: sobre la MISMA ventana que el número del usuario. Sin
    # ventana (sin número) no hay comparación que armar.
    try:
        if window_from:
            cutoff_ym = str(window_from)[:7]
            hasta_ym = (today.strftime("%Y-%m") if str(window_to) in ("hoy", "", "None")
                        else str(window_to)[:7])
            infl = data.get("inflation_ar") or {}
            infl_window = sorted([(k, v) for k, v in infl.items() if cutoff_ym < k <= hasta_ym])
            if infl_window:
                comp = 1.0
                for _, pct in infl_window:
                    comp *= (1 + float(pct) / 100)
                inflation_pct = round((comp - 1) * 100, 2)
            blue = data.get("dolar_blue") or {}
            k0 = max((k for k in blue if k <= cutoff_ym), default=None)
            k1 = max((k for k in blue if k <= hasta_ym), default=None)
            if k0 and k1 and blue.get(k0):
                dolar_pct = round((float(blue[k1]) - float(blue[k0])) / float(blue[k0]) * 100, 2)
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
        # La ventana REAL del número, la que el motor declara. Y con qué regla se
        # midió: 'mercado' (Certero) o 'contable' (Estimado, que no cuenta lo no
        # realizado — el modelo tiene que decirlo si compara contra el S&P).
        "window_from": window_from,
        "window_to": window_to,
        "basis": basis,
        "excluye_no_realizado": excluye_no_realizado,
        "user_return_pct": user_pct,
        "benchmarks": {
            "sp500_pct": sp500_pct,
            "inflation_ar_pct": inflation_pct,
            "dolar_blue_pct": dolar_pct,
        },
        "deltas_pp": deltas,
        "outperform": outperform,
    }
