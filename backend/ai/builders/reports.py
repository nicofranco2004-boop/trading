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
  "twr_year_pct": float | null,   # TWR compoundeado del año (combina P&L
                                  # realizado de meses cerrados + unrealized
                                  # mark-to-market del mes en curso)
  "realized_pnl_year_usd": float, # P&L REALIZADO del año (suma pnl_realized
                                  # de monthly_entries del año) — SOLO trades
                                  # cerrados, NO mark-to-market
  "pnl_year_usd": float,          # ALIAS de realized_pnl_year_usd (back-compat)
  "trades_year": int,             # # de operaciones cerradas en el año
  "best_month": { "month": str, "delta_pct": float } | null,
  "worst_month": { "month": str, "delta_pct": float } | null,
  "vs_sp500_pp": float | null,    # promedio de vs_sp500_pct mensual
  "consistency": "alto" | "medio" | "bajo",
  "years_available": [int],       # años con datos cargados
}
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
from datetime import date


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

    # Compoundear retornos mensuales (TWR aislando flujos, igual que insights)
    compound = 1.0
    positive = 0
    used = 0
    best: Optional[Dict[str, Any]] = None
    worst: Optional[Dict[str, Any]] = None
    vs_sp500_values: List[float] = []
    monthly_deltas: List[Dict[str, Any]] = []

    for e in entries:
        ci = float(e.get("capital_inicio") or 0)
        cf = float(e.get("capital_final") or 0)
        dep = float(e.get("deposits") or 0)
        wd = float(e.get("withdrawals") or 0)
        if ci <= 0:
            continue
        ret = ((cf - dep + wd) / ci) - 1
        if ret < -0.95 or ret > 5:
            continue

        month_label = f"{e['year']:04d}-{e['month']:02d}"
        delta_pct = round(ret * 100, 2)
        compound *= (1 + ret)
        used += 1
        if ret > 0:
            positive += 1
        monthly_deltas.append({"month": month_label, "delta_pct": delta_pct})

        # Track best/worst
        if best is None or delta_pct > best["delta_pct"]:
            best = {"month": month_label, "delta_pct": delta_pct}
        if worst is None or delta_pct < worst["delta_pct"]:
            worst = {"month": month_label, "delta_pct": delta_pct}

    twr_year_pct: Optional[float] = (
        round((compound - 1) * 100, 2) if used > 0 else None
    )
    winrate_monthly = round((positive / used) * 100, 1) if used > 0 else 0.0
    pnl_year_usd = round(sum(
        float(e.get("pnl_realized") or 0) for e in entries
    ), 2)
    # trades del año via operations (más confiable que monthly_entries)
    trades_year_row = conn.execute(
        """SELECT COUNT(*) AS c FROM operations
            WHERE user_id = ?
              AND pnl_usd IS NOT NULL
              AND op_type NOT IN ('Compra', 'Dividendo', 'Interés', '')
              AND op_type NOT LIKE 'CONVERSION%'
              AND op_type NOT LIKE 'Conversión%'
              AND substr(date, 1, 4) = ?""",
        (user_id, str(year)),
    ).fetchone()
    trades_year = int(trades_year_row["c"] or 0) if trades_year_row else 0

    # vs S&P — heurística: si tenemos serie de SPY mensual en bench cache,
    # restamos para promediar.
    try:
        import main as _m
        cache_bench = getattr(_m, "_bench_cache", {}) or {}
        sp = (cache_bench.get("data") or {}).get("sp500") or {}
        for md in monthly_deltas:
            ym = md["month"]
            sp_val = sp.get(ym)
            sp_prev_key = None
            # Aprox: tomamos cambio MoM si tenemos consecutivos
            try:
                y, m = ym.split("-")
                prev_m = int(m) - 1
                prev_y = int(y)
                if prev_m == 0:
                    prev_m = 12
                    prev_y -= 1
                sp_prev_key = f"{prev_y:04d}-{prev_m:02d}"
            except Exception:
                pass
            sp_prev = sp.get(sp_prev_key) if sp_prev_key else None
            if sp_val and sp_prev:
                sp_ret = (sp_val - sp_prev) / sp_prev * 100
                vs_sp500_values.append(md["delta_pct"] - sp_ret)
    except Exception:
        vs_sp500_values = []

    vs_sp500_avg = (
        round(sum(vs_sp500_values) / len(vs_sp500_values), 2)
        if vs_sp500_values else None
    )

    # Consistencia cualitativa
    if winrate_monthly >= 70:
        consistency = "alto"
    elif winrate_monthly >= 50:
        consistency = "medio"
    else:
        consistency = "bajo"

    return {
        "screen": "reports",
        "year": year,
        "total_months_active": used,
        "winrate_monthly": winrate_monthly,
        "twr_year_pct": twr_year_pct,
        # realized_pnl_year_usd es el nombre claro — suma pnl_realized de
        # monthly_entries (solo trades cerrados). pnl_year_usd queda como
        # alias para back-compat (mismo valor) hasta migrar consumers.
        "realized_pnl_year_usd": pnl_year_usd,
        "pnl_year_usd": pnl_year_usd,
        "trades_year": trades_year,
        "best_month": best,
        "worst_month": worst,
        "vs_sp500_pp": vs_sp500_avg,
        "consistency": consistency,
        "years_available": years_available,
    }
