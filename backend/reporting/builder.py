"""Builder de PeriodReports — funciones puras sobre la DB.

Punto de entrada: `build_period_report(conn, uid, period_type, period_key, broker_filter)`.

Reusa lógica existente del backend:
- monthly_entries (broker='global' o broker específico) → start/end value, flows, realized
- operations → drivers por activo, win rate, trades count
- snapshots → start/end value para semanas (cuando no hay monthly_entry)
- benchmarks (sp500, inflation) → vs S&P / vs inflación
"""
from __future__ import annotations

import math
from datetime import date as date_cls, datetime, timedelta
from typing import Optional, List, Tuple, Dict, Any

from .schema import (
    PeriodReport, PeriodMetrics, Insight, Highlight, AssetContribution,
)


# ─── Período: parseo y bounds ────────────────────────────────────────────────

def parse_period_bounds(period_type: str, period_key: str) -> Tuple[str, str]:
    """Devuelve (start_date, end_date) ISO ('YYYY-MM-DD') inclusivos.

    Soporta:
    - 'day': period_key = 'YYYY-MM-DD'
    - 'week': period_key = 'YYYY-Wnn' (ISO week, lunes a domingo)
    - 'month': period_key = 'YYYY-MM'
    """
    if period_type == "day":
        y, m, d = (int(x) for x in period_key.split("-"))
        dt = date_cls(y, m, d)
        return dt.isoformat(), dt.isoformat()
    if period_type == "week":
        y_str, w_str = period_key.split("-W")
        y, w = int(y_str), int(w_str)
        # ISO week: lunes de la semana w del año y
        # date.fromisocalendar disponible desde Python 3.8
        monday = date_cls.fromisocalendar(y, w, 1)
        sunday = monday + timedelta(days=6)
        return monday.isoformat(), sunday.isoformat()
    if period_type == "month":
        y, m = (int(x) for x in period_key.split("-"))
        first = date_cls(y, m, 1)
        # Último día del mes
        if m == 12:
            next_m = date_cls(y + 1, 1, 1)
        else:
            next_m = date_cls(y, m + 1, 1)
        last = next_m - timedelta(days=1)
        return first.isoformat(), last.isoformat()
    raise ValueError(f"period_type desconocido: {period_type}")


def period_label(period_type: str, period_key: str, period_start: str) -> str:
    """Label legible para el chip. Ej: 'Mayo 2026', 'Semana 19', 'Lun 13 may'."""
    MES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
           "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    DIA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    if period_type == "month":
        y, m = period_key.split("-")
        return f"{MES[int(m) - 1]} {y}"
    if period_type == "week":
        _, w = period_key.split("-W")
        return f"Semana {int(w)}"
    if period_type == "day":
        y, m, d = (int(x) for x in period_key.split("-"))
        dt = date_cls(y, m, d)
        return f"{DIA[dt.weekday()]} {dt.day} {MES[m - 1].lower()}"
    return period_key


def is_period_current(period_type: str, period_start: str, period_end: str,
                     today: Optional[date_cls] = None) -> bool:
    today = today or date_cls.today()
    start = date_cls.fromisoformat(period_start)
    end = date_cls.fromisoformat(period_end)
    return start <= today <= end


# ─── Queries primitives ──────────────────────────────────────────────────────

def _broker_clause(broker_filter: str) -> Tuple[str, tuple]:
    """SQL fragment para filtrar por broker. 'global' = sin filtro."""
    if broker_filter == "global":
        return "", ()
    return " AND broker = ?", (broker_filter,)


def _operations_clause(broker_filter: str) -> Tuple[str, tuple]:
    if broker_filter == "global":
        return "", ()
    return " AND broker = ?", (broker_filter,)


def fetch_operations_in_range(conn, uid: int, start: str, end: str,
                              broker_filter: str = "global") -> List[Dict[str, Any]]:
    """Operations cerradas (Venta, Dividendo, Interés, Futuros) en el rango."""
    br_sql, br_args = _operations_clause(broker_filter)
    rows = conn.execute(
        f"""SELECT id, date, broker, asset, op_type, quantity, entry_price,
                   exit_price, pnl_usd, pnl_pct
              FROM operations
             WHERE user_id = ? AND date >= ? AND date <= ?{br_sql}
             ORDER BY date ASC, id ASC""",
        (uid, start, end, *br_args),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_snapshots_in_range(conn, uid: int, start: str, end: str) -> List[Dict[str, Any]]:
    """Snapshots del portfolio en el rango. Snapshot es global (no per-broker)."""
    rows = conn.execute(
        """SELECT date, total_value, total_invested, net_deposited
             FROM snapshots
            WHERE user_id = ? AND date >= ? AND date <= ?
            ORDER BY date ASC""",
        (uid, start, end),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_snapshot_at_or_before(conn, uid: int, when: str) -> Optional[Dict[str, Any]]:
    """Último snapshot con date <= when. Útil para encontrar el "valor de
    arranque" de un período cuando no hay snapshot exacto en el primer día."""
    row = conn.execute(
        """SELECT date, total_value, total_invested, net_deposited
             FROM snapshots
            WHERE user_id = ? AND date <= ?
            ORDER BY date DESC LIMIT 1""",
        (uid, when),
    ).fetchone()
    return dict(row) if row else None


def fetch_monthly_entry(conn, uid: int, year: int, month: int,
                       broker_filter: str = "global") -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """SELECT capital_inicio, capital_final, deposits, withdrawals,
                  pnl_realized, pnl_unrealized
             FROM monthly_entries
            WHERE user_id = ? AND broker = ? AND year = ? AND month = ?""",
        (uid, broker_filter, year, month),
    ).fetchone()
    return dict(row) if row else None


def fetch_cum_deposits_until(conn, uid: int, end_date: str,
                            broker_filter: str = "global") -> float:
    """Σ(deposits − withdrawals) en monthly_entries hasta `end_date` (incl).

    Sirve como denominador para la métrica alternativa "% sobre aportado".
    """
    y, m = (int(x) for x in end_date[:7].split("-"))
    row = conn.execute(
        """SELECT COALESCE(SUM(deposits) - SUM(withdrawals), 0) AS net
             FROM monthly_entries
            WHERE user_id = ? AND broker = ?
              AND (year < ? OR (year = ? AND month <= ?))""",
        (uid, broker_filter, y, y, m),
    ).fetchone()
    return float(row["net"] or 0)


# ─── Benchmarks ──────────────────────────────────────────────────────────────

def benchmark_return_for_period(bench: Dict[str, Any], period_type: str,
                                period_start: str, period_end: str,
                                key: str) -> Optional[float]:
    """% del benchmark en el período. `key` ∈ {'sp500', 'inflation_ar'}.

    sp500 está keyed por YYYY-MM con cierre del mes. Para mes completo es directo.
    Para semana, devolvemos None (no podemos pro-ratear sin daily data).
    """
    if not bench or key not in bench:
        return None
    series = bench.get(key) or {}
    if period_type != "month":
        return None  # Phase 1: no soportamos benchmark sub-mensual
    start_mk = period_start[:7]
    end_mk = period_end[:7]
    if key == "sp500":
        # close del mes anterior vs close de este mes
        y, m = (int(x) for x in end_mk.split("-"))
        prev_y, prev_m = (y, m - 1) if m > 1 else (y - 1, 12)
        prev_mk = f"{prev_y:04d}-{prev_m:02d}"
        cur = series.get(end_mk)
        prev = series.get(prev_mk)
        if cur and prev and prev > 0:
            return ((cur / prev) - 1) * 100
        return None
    if key == "inflation_ar":
        # ya viene en % por mes
        v = series.get(end_mk)
        return float(v) if v is not None else None
    return None


# ─── Métricas core del período ───────────────────────────────────────────────

def _modified_dietz_pct(start_value: float, end_value: float, flows: float) -> float:
    """Period return Modified Dietz. Clamped a [-0.99, +inf]."""
    avg = start_value + 0.5 * flows
    if avg <= 0:
        return 0.0
    pnl = end_value - start_value - flows
    r = pnl / avg
    return max(r, -0.99) * 100


def compute_metrics_for_period(
    conn, uid: int, period_type: str, period_start: str, period_end: str,
    broker_filter: str, bench: Optional[Dict[str, Any]],
    live_value: Optional[float] = None,
) -> Tuple[PeriodMetrics, List[Dict[str, Any]]]:
    """Computa métricas + devuelve operaciones del período (para drivers/highlights).

    Estrategia:
    - month: usa monthly_entries (canónico).
    - week/day: usa snapshots para start/end + operations para realized/trades.

    Para el período en curso, si hay liveValue, lo usamos como end_value.
    """
    ops = fetch_operations_in_range(conn, uid, period_start, period_end, broker_filter)
    realized = sum(float(o.get("pnl_usd") or 0) for o in ops)

    # Trades cerrados (Venta + Futuros), excluyendo dividendos/intereses/compras/conversiones
    def _is_trade(op):
        t = (op.get("op_type") or "").strip()
        if t in ("Compra", "Dividendo", "Interés"):
            return False
        if t.startswith("Conversión") or t.startswith("CONVERSION"):
            return False
        return True

    trade_ops = [o for o in ops if _is_trade(o) and o.get("pnl_usd") is not None]
    wins = [o for o in trade_ops if o["pnl_usd"] > 0]
    losses = [o for o in trade_ops if o["pnl_usd"] < 0]
    win_rate = (len(wins) / len(trade_ops) * 100) if trade_ops else None

    deposits = 0.0
    withdrawals = 0.0
    start_value = 0.0
    end_value = 0.0
    unrealized = 0.0

    if period_type == "month":
        y, m = (int(x) for x in period_start[:7].split("-"))
        me = fetch_monthly_entry(conn, uid, y, m, broker_filter)
        if me:
            start_value = float(me.get("capital_inicio") or 0)
            end_value = float(me.get("capital_final") or 0)
            deposits = float(me.get("deposits") or 0)
            withdrawals = float(me.get("withdrawals") or 0)
            unrealized = float(me.get("pnl_unrealized") or 0)
        if live_value is not None and is_period_current(period_type, period_start, period_end):
            end_value = float(live_value)
    else:
        # week / day: snapshots para start/end
        snap_start = fetch_snapshot_at_or_before(conn, uid, period_start)
        snap_end = fetch_snapshot_at_or_before(conn, uid, period_end)
        # Para "start" buscamos snapshot ANTES del período (cierre del día previo).
        # Si snap_start coincide con period_start, está bien igual; si es más viejo, asumimos
        # que el valor no cambió (es lo mejor que podemos hacer sin daily data).
        start_value = float(snap_start["total_value"]) if snap_start else 0.0
        if live_value is not None and is_period_current(period_type, period_start, period_end):
            end_value = float(live_value)
        else:
            end_value = float(snap_end["total_value"]) if snap_end else start_value
        # deposits/withdrawals para week/day: no tenemos granularidad fina —
        # los dejamos en 0 en Phase 1. Phase 3 (daily) los va a precisar.

    flows = deposits - withdrawals
    delta_usd = end_value - start_value - flows
    delta_pct = _modified_dietz_pct(start_value, end_value, flows)

    cum_aportado = fetch_cum_deposits_until(conn, uid, period_end, broker_filter)
    delta_pct_over_contrib = (
        (delta_usd / cum_aportado) * 100 if cum_aportado > 0 else None
    )

    vs_sp500 = benchmark_return_for_period(bench or {}, period_type, period_start,
                                            period_end, "sp500")
    vs_inflation = benchmark_return_for_period(bench or {}, period_type, period_start,
                                                period_end, "inflation_ar")

    metrics = PeriodMetrics(
        start_value=round(start_value, 2),
        end_value=round(end_value, 2),
        delta_usd=round(delta_usd, 2),
        delta_pct=round(delta_pct, 2),
        delta_pct_over_contrib=round(delta_pct_over_contrib, 2) if delta_pct_over_contrib is not None else None,
        realized_pnl=round(realized, 2),
        unrealized_pnl=round(unrealized, 2),
        deposits=round(deposits, 2),
        withdrawals=round(withdrawals, 2),
        trades_count=len(trade_ops),
        win_count=len(wins),
        loss_count=len(losses),
        win_rate=round(win_rate, 1) if win_rate is not None else None,
        vs_sp500_pct=round(vs_sp500, 2) if vs_sp500 is not None else None,
        vs_inflation_pct=round(vs_inflation, 2) if vs_inflation is not None else None,
    )
    return metrics, ops


# ─── Drivers (atribución por activo) ─────────────────────────────────────────

def compute_drivers(ops: List[Dict[str, Any]], top_n: int = 5) -> List[AssetContribution]:
    """Top activos por |pnl_usd|. Cada uno con su contribución %."""
    by_asset: Dict[str, float] = {}
    for o in ops:
        a = (o.get("asset") or "").upper().strip()
        if not a or a == "—":
            continue
        by_asset[a] = by_asset.get(a, 0.0) + float(o.get("pnl_usd") or 0)
    if not by_asset:
        return []
    total_abs = sum(abs(v) for v in by_asset.values()) or 1.0
    items = sorted(by_asset.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_n]
    return [
        AssetContribution(
            asset=a,
            pnl_usd=round(pnl, 2),
            contribution_pct=round(abs(pnl) / total_abs * 100, 1),
        )
        for a, pnl in items
    ]


# ─── Highlights (mejor op, peor op, etc.) ────────────────────────────────────

def compute_highlights(ops: List[Dict[str, Any]]) -> List[Highlight]:
    """Para Phase 1: best_op + worst_op. Best/worst day/week vienen en builder
    de mes-con-semanas (se computan desde los children)."""
    out: List[Highlight] = []
    if not ops:
        return out

    def _is_trade(op):
        t = (op.get("op_type") or "").strip()
        if t in ("Compra", "Dividendo", "Interés"):
            return False
        if t.startswith("Conversión") or t.startswith("CONVERSION"):
            return False
        return True

    trades = [o for o in ops if _is_trade(o) and o.get("pnl_usd") is not None]
    if trades:
        best = max(trades, key=lambda o: o["pnl_usd"])
        worst = min(trades, key=lambda o: o["pnl_usd"])
        if best["pnl_usd"] > 1:
            out.append(Highlight(
                kind="best_op",
                icon="🚀",
                label="Mejor operación",
                value_label=f"{best['asset']} +US${best['pnl_usd']:,.0f}",
                context=best["date"],
            ))
        if worst["pnl_usd"] < -1:
            out.append(Highlight(
                kind="worst_op",
                icon="💀",
                label="Peor operación",
                value_label=f"{worst['asset']} −US${abs(worst['pnl_usd']):,.0f}",
                context=worst["date"],
            ))
    return out


# ─── Headline auto-generada ─────────────────────────────────────────────────

# Tabla de sustantivo + género por tipo de período. Necesaria para que los
# adjetivos del headline concuerden correctamente en español (semana = fem,
# mes/día = masc). "difícil" es invariable y "período" es masc (fallback).
_PERIOD_WORD = {
    "month": ("Mes", "m"),
    "week":  ("Semana", "f"),
    "day":   ("Día", "m"),
}

# Adjetivos: forma masculina → forma femenina. Si no aparece, se asume invariable.
_ADJ_FEMININE = {
    "sólido":  "sólida",
    "mixto":   "mixta",
    "tranquilo": "tranquila",
    # "difícil" es invariable → no entra acá
}


def _conjugate(adj_masc: str, gender: str) -> str:
    """Devuelve el adjetivo concordado al género del sustantivo."""
    if gender == "f":
        return _ADJ_FEMININE.get(adj_masc, adj_masc)
    return adj_masc


def generate_headline(metrics: PeriodMetrics, drivers: List[AssetContribution],
                     period_type: str) -> Tuple[str, Optional[str]]:
    """Genera headline + subheadline narrativos basados en la data.

    Reglas determinísticas (no LLM). Cada caso es un detector simple.
    Concuerda el género del adjetivo con el sustantivo del período.
    """
    delta = metrics.delta_pct
    abs_usd = abs(metrics.delta_usd)
    period_word, gender = _PERIOD_WORD.get(period_type, ("Período", "m"))

    # Caso 1: período flat — frase invariable
    if abs(delta) < 0.5 and abs_usd < 100:
        return (f"{period_word} sin grandes movimientos.", None)

    # Caso 2: período negativo significativo — "difícil" es invariable
    if delta < -3:
        sub = None
        if drivers:
            top_neg = next((d for d in drivers if d.pnl_usd < 0), None)
            if top_neg:
                sub = f"{top_neg.asset} fue el principal responsable de la caída."
        return (f"{period_word} difícil — {delta:.1f}%.", sub)

    # Caso 3: período positivo significativo — "sólido/sólida"
    if delta > 3:
        sub = None
        if drivers:
            top_pos = next((d for d in drivers if d.pnl_usd > 0), None)
            if top_pos and top_pos.contribution_pct >= 30:
                sub = f"{top_pos.asset} explicó el {top_pos.contribution_pct:.0f}% del rendimiento."
        return (f"{period_word} {_conjugate('sólido', gender)} — +{delta:.1f}%.", sub)

    # Default: período mixto — "mixto/mixta"
    sign = "+" if delta >= 0 else ""
    return (f"{period_word} {_conjugate('mixto', gender)} — {sign}{delta:.1f}%.", None)


# ─── Punto de entrada principal ──────────────────────────────────────────────

def build_period_report(
    conn, uid: int, period_type: str, period_key: str,
    broker_filter: str = "global",
    bench: Optional[Dict[str, Any]] = None,
    live_value: Optional[float] = None,
    today: Optional[date_cls] = None,
) -> PeriodReport:
    """Builder principal — recibe un período, devuelve el PeriodReport completo
    (sin children. Children se anidan en `timeline.py`)."""
    start, end = parse_period_bounds(period_type, period_key)
    label = period_label(period_type, period_key, start)
    is_current = is_period_current(period_type, start, end, today=today)

    metrics, ops = compute_metrics_for_period(
        conn, uid, period_type, start, end, broker_filter,
        bench=bench, live_value=live_value,
    )
    drivers = compute_drivers(ops)
    highlights = compute_highlights(ops)
    headline, subheadline = generate_headline(metrics, drivers, period_type)

    # is_relevant: hay actividad económica o cambios significativos
    is_relevant = (
        metrics.trades_count > 0
        or abs(metrics.delta_usd) >= 100
        or metrics.deposits > 0
        or metrics.withdrawals > 0
    )

    return PeriodReport(
        period_type=period_type,
        period_key=period_key,
        period_label=label,
        period_start=start,
        period_end=end,
        is_current=is_current,
        is_relevant=is_relevant,
        headline=headline,
        subheadline=subheadline,
        metrics=metrics,
        insights=[],  # se llena en otro pase (detectors.py)
        highlights=highlights,
        drivers=drivers,
        children=[],
    )
