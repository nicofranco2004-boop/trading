"""builders.reports — packet de la vista de Reportes (performance histórica).
═══════════════════════════════════════════════════════════════════════════
Topic: reports

Análisis de la página /reportes — performance mensual histórica del
portfolio. Distinto de `insights.evolution` (que es 12m rolling para
insights del Dashboard) — éste enfoca la VISTA CRONOLÓGICA: por año,
con cantidad de meses activos, win rate mensual, P&L acumulado, mejor
y peor mes en contexto.

Params:
  year: int (opcional) — año a analizar. Default: el año actual.

Shape (~900 bytes):
{
  "screen": "reports",
  "year": int,
  "total_months_active": int,    # meses con actividad real
  "winrate_monthly": float,       # % meses positivos
  "twr_year_pct": float | null,   # rendimiento del año — SIEMPRE de `twr.rendimiento_publicable`
  "twr_year_base": "mercado"|"contable"|null,   # de dónde sale ese número
  "twr_year_motivo_texto": str | null,          # por qué no se pudo medir a mercado
  "realized_pnl_year_usd": float, # P&L REALIZADO del año (suma pnl_realized
                                  # de monthly_entries del año) — SOLO trades
                                  # cerrados, NO mark-to-market
  "pnl_year_usd": float,          # ALIAS de realized_pnl_year_usd (back-compat)
  "trades_year": int,             # # de operaciones cerradas en el año
  "best_month": { "month": str, "delta_pct": float } | null,
  "worst_month": { "month": str, "delta_pct": float } | null,
  "months_base": "mercado" | "contable" | null,  # con qué regla se midieron los meses
  "months_not_market": int,       # meses del año que no se midieron a mercado
  "vs_sp500_pp": float | null,    # twr_year_pct − S&P 500 entre las MISMAS dos fechas
  "consistency": "alto" | "medio" | "bajo",
  "years_available": [int],       # años con datos cargados
}
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import date
import twr as _twr
from realized_pnl import closed_filter_sql


def build(conn, user_id: int, **kwargs) -> Dict[str, Any]:
    today = date.today()
    year = int(kwargs.get("year") or today.year)

    rows = conn.execute(
        """SELECT year, month, capital_inicio, capital_final, deposits,
                  withdrawals, pnl_realized, pnl_unrealized
             FROM monthly_entries
            WHERE user_id = ? AND broker = 'global'
            ORDER BY year, month""",
        (user_id,),
    ).fetchall()

    all_entries = [dict(r) for r in rows]
    years_available = sorted({e["year"] for e in all_entries})

    # Filter al año pedido
    entries = [e for e in all_entries if e["year"] == year]

    positive = 0
    used = 0
    best: Optional[Dict[str, Any]] = None
    worst: Optional[Dict[str, Any]] = None
    monthly_deltas: List[Dict[str, Any]] = []

    # ⚠️ CADA MES SE LE PIDE AL MOTOR, igual que el acumulado de abajo. El Dietz
    # de `monthly_entries` de un mes cerrado es lo REALIZADO sobre el costo: un mes
    # sin ventas daba ~0 % aunque la cartera se hubiera movido 20 %, y con eso se
    # elegían el mejor mes, el peor y el % de meses positivos. Ver
    # `twr.rendimientos_mensuales`; `mejor_y_peor_mes` no mezcla reglas.
    rk = _twr.mejor_y_peor_mes(_twr.rendimientos_mensuales(
        conn, user_id, desde=f"{year:04d}-01-01", hasta=f"{year:04d}-12-31"))
    for m in rk["meses"]:
        monthly_deltas.append({"month": m["mes"], "delta_pct": round(m["pct"], 2)})
    used = rk["total"]
    positive = rk["positivos"]
    if rk["mejor"] is not None:
        best = {"month": rk["mejor"]["mes"], "delta_pct": round(rk["mejor"]["pct"], 2)}
        worst = {"month": rk["peor"]["mes"], "delta_pct": round(rk["peor"]["pct"], 2)}

    # ⚠️ EL ACUMULADO DEL AÑO SE LE PIDE AL MOTOR (F6). Ver el comentario largo en
    # `twr.rendimiento_publicable`: componer `monthly_entries` acá publicaba
    # +129.544 % para un usuario al que el motor le mide +0,7 %, y agregarle
    # `leg_dudoso` no alcanzaba porque el defecto es SALTEAR el mes malo en vez de
    # cortar el tramo. Los meses de `monthly_deltas` siguen igual: cada uno por
    # separado es honesto, lo que estaba mal era el producto.
    _rend = _twr.rendimiento_publicable(
        conn, user_id, desde=f"{year:04d}-01-01", hasta=f"{year:04d}-12-31", periodo=True)
    twr_year_pct: Optional[float] = _rend["pct"]
    winrate_monthly = round((positive / used) * 100, 1) if used > 0 else 0.0
    pnl_year_usd = round(sum(
        float(e.get("pnl_realized") or 0) for e in entries
    ), 2)
    # trades del año via operations (más confiable que monthly_entries)
    trades_year_row = conn.execute(
        f"""SELECT COUNT(*) AS c FROM operations
            WHERE user_id = ?
              AND {closed_filter_sql()}
              AND substr(date, 1, 4) = ?""",
        (user_id, str(year)),
    ).fetchone()
    trades_year = int(trades_year_row["c"] or 0) if trades_year_row else 0

    # ⚠️ EL S&P ENTRE LAS MISMAS DOS FECHAS QUE EL NÚMERO (H7). Antes: el promedio
    # de "mes del usuario − mes del S&P", con la fórmula propia de acá y sobre los
    # meses de `monthly_deltas` —que pueden ser contables—, mientras el número del
    # año sale del motor con su propia ventana. Era otra cuenta sobre otro período.
    # Ahora es la misma regla que el dashboard y las métricas:
    # `performance.bench_pct_entre` sobre la ventana que el motor declaró. Sin
    # ventana (sin número, o el número es contable) no hay comparación.
    vs_sp500_avg = None
    try:
        import main as _m
        import performance as _perf_r
        _data = ((getattr(_m, "_bench_cache", {}) or {}).get("data") or {})
        if twr_year_pct is not None:
            _sp = _perf_r.bench_pct_entre(_data, "sp500", _rend.get("desde"), _rend.get("hasta"))
            if _sp is not None:
                vs_sp500_avg = round(twr_year_pct - _sp, 2)
    except Exception:
        vs_sp500_avg = None

    # Consistencia cualitativa
    if winrate_monthly >= 70:
        consistency = "alto"
    elif winrate_monthly >= 50:
        consistency = "medio"
    else:
        consistency = "bajo"

    return {
        "screen": "reports",
        # _field_docs — descripciones inline para el LLM (Ola 2-E).
        "_field_docs": {
            "_doc_scope": "Solo documentamos campos ambiguos donde el nombre no basta. Los demás (year, broker, sections, monthly_breakdown) son explícitos por su nombre — confiá en ellos.",
            "twr_year_pct": "Rendimiento del año. Sale del motor canónico; mirá SIEMPRE `twr_year_base` antes de hablar de él.",
            "twr_year_base": "De dónde sale `twr_year_pct`. 'mercado' = medido contra fotos reales de la cartera, es el bueno. 'contable' = de la cadena de monthly_entries, que no sabe nada del mercado: al hablarlo decilo (\"según tu contabilidad cargada\"). null = no se pudo medir y NO hay que publicar ningún número; el motivo está en `twr_year_motivo_texto`.",
            "twr_year_motivo_texto": "Por qué no se pudo medir a mercado, ya escrito en castellano para el usuario. Si `twr_year_pct` es null, esto es lo que hay que contestar EN LUGAR de un número — no inventes uno de otra parte del packet.",
            "realized_pnl_year_usd": "USD ABSOLUTO de P&L REALIZADO del año (suma pnl_realized de monthly_entries). Solo trades cerrados.",
            "pnl_year_usd": "Alias back-compat de realized_pnl_year_usd. Mismo valor.",
            "trades_year": "Cantidad de operaciones CERRADAS en el año.",
            "winrate_monthly": "% de meses con delta positivo (TWRR > 0).",
            "best_month / worst_month": "Mejor/peor mes por delta_pct, del motor (`twr.rendimientos_mensuales`). Mirá `months_base`: 'mercado' = medido contra fotos reales de la cartera; 'contable' = ningún mes del año se pudo medir a mercado y salen de la contabilidad, que sólo cuenta lo VENDIDO (un mes sin ventas da ~0 %): al hablarlo decilo.",
            "months_not_market": "Meses del año que no se pudieron medir a mercado. Si hay meses de mercado, éstos NO entran en best/worst ni en winrate_monthly.",
            "vs_sp500_pp": "`twr_year_pct` menos lo que hizo el S&P 500 entre las MISMAS dos fechas que ese número (puntos). null si no hay número del año o no hay datos del S&P para esa ventana.",
        },
        "year": year,
        "total_months_active": used,
        "winrate_monthly": winrate_monthly,
        "twr_year_pct": twr_year_pct,
        # De dónde sale: 'mercado' (fotos) o 'contable' (la cadena mensual). Sin
        # esto el modelo no sabe con qué confianza hablar del número.
        "twr_year_base": _rend["base"],
        "twr_year_motivo_texto": _rend["motivo_texto"],
        # realized_pnl_year_usd es el nombre claro — suma pnl_realized de
        # monthly_entries (solo trades cerrados). pnl_year_usd queda como
        # alias para back-compat (mismo valor) hasta migrar consumers.
        "realized_pnl_year_usd": pnl_year_usd,
        "pnl_year_usd": pnl_year_usd,
        "trades_year": trades_year,
        "best_month": best,
        "worst_month": worst,
        "months_base": rk["base"],
        "months_not_market": rk["sin_medir_a_mercado"],
        "vs_sp500_pp": vs_sp500_avg,
        "consistency": consistency,
        "years_available": years_available,
    }
