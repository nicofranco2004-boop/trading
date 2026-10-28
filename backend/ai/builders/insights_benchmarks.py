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
  "user_return_pct": float | null,      # en dólares, contra el S&P
  "user_return_ars_pct": float | null,  # en pesos, contra inflación y blue
  "modo": "certero" | "estimado" | null,
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
    TWR publicado del modo que ELIGIÓ EL USUARIO (`twr.modo_de`; si ése no tiene
    número, el otro, declarado en `modo`/`basis`), y el S&P entre las MISMAS dos fechas que ese
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

    def _dias(d0, d1):
        _a = str(d0 or "")[:10]
        _b = today.isoformat() if str(d1) in ("hoy", "None", "") else str(d1)[:10]
        try:
            return (date.fromisoformat(_b) - date.fromisoformat(_a)).days
        except ValueError:
            return 0

    user_ars_pct: Optional[float] = None
    modo_usado: Optional[str] = None
    try:
        import performance as _perf
        import twr as _twr
        # ⚠️ EL MODO DEL USUARIO PRIMERO. Antes era siempre certero y, si no
        # había medición, estimado: con la app en Estimado, el chat comparaba
        # contra el S&P un número que la pantalla no mostraba. El otro modo queda
        # como respaldo DECLARADO (`modo`/`basis` en el paquete).
        _pref = _twr.modo_de(conn, user_id, kwargs.get("modo"))
        _orden = (_pref,) + tuple(m for m in _twr.MODOS if m != _pref)
        perf = None
        for modo in _orden:
            p = _perf.performance(conn, user_id, data, bench_key="sp500", modo=modo)
            if p.get("twr") is not None:
                perf = p
                break
        if perf is not None:
            modo_usado = perf.get("modo")
            window_from, window_to = perf.get("ventana_desde"), perf.get("ventana_hasta")
            # ⚠️ VENTANA MÍNIMA. Medido en la copia de producción: el fallback al
            # Estimado devolvía ventanas de DOS DÍAS (2026-08-14 → 08-16, +0,09 %)
            # y el modelo compararía eso contra el S&P como si fuera un período.
            # Menos de 28 días no es una comparación: se publica la ventana y el
            # motivo, no el número.
            if _dias(window_from, window_to) >= 28:
                user_pct = round(float(perf["twr"]) * 100, 2)
                basis = perf.get("base_del_twr")
                excluye_no_realizado = bool(perf.get("excluye_no_realizado"))
                sp500_pct = _bench_pct_entre(perf.get("benchmark"), perf.get("curva"),
                                             window_from, window_to)
            else:
                basis = "ventana_corta"
                window_from = window_to = None

            # ⚠️ INFLACIÓN Y BLUE, EN PESOS Y CON EL MISMO MODO. Se restaba la
            # inflación del INDEC (pesos) a `user_pct` (dólares): le faltaba la
            # devaluación, que es justo lo que separa las dos monedas (ver
            # `twr.vs_inflacion_ar`). Ahora es la misma cuenta que la tarjeta
            # "Cartera vs Inflación AR (ARS)": la cartera medida EN PESOS por el
            # motor y la inflación entre las MISMAS dos fechas de esa medición.
            if user_pct is not None:
                p_ars = _perf.performance(conn, user_id, data, bench_key="inflation_ar",
                                          modo=modo_usado, moneda=_twr.MONEDA_ARS)
                a0, a1 = p_ars.get("ventana_desde"), p_ars.get("ventana_hasta")
                if p_ars.get("twr") is not None and _dias(a0, a1) >= 28:
                    user_ars_pct = round(float(p_ars["twr"]) * 100, 2)
                    inflation_pct = _bench_pct_entre(p_ars.get("benchmark"),
                                                     p_ars.get("curva"), a0, a1)
                    dolar_pct = _perf.bench_pct_entre(data, "dolar_blue", a0, a1)
    except Exception:
        perf = None

    def _delta(u, b):
        return round(u - b, 2) if (u is not None and b is not None) else None

    deltas = {
        "vs_sp500": _delta(user_pct, sp500_pct),
        # Pesos contra pesos: la inflación y el blue se miden en pesos.
        "vs_inflation": _delta(user_ars_pct, inflation_pct),
        "vs_dolar_blue": _delta(user_ars_pct, dolar_pct),
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
        # El mismo rendimiento EN PESOS (incluye la devaluación): contra éste se
        # comparan la inflación y el blue.
        "user_return_ars_pct": user_ars_pct,
        # Con qué modo se midió: el que eligió el usuario, salvo que no tuviera
        # número (entonces el otro, y acá se ve).
        "modo": modo_usado,
        "benchmarks": {
            "sp500_pct": sp500_pct,
            "inflation_ar_pct": inflation_pct,
            "dolar_blue_pct": dolar_pct,
        },
        "deltas_pp": deltas,
        "outperform": outperform,
    }
