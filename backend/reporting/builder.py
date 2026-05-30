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
    if period_type == "year":
        y = int(period_key)
        return f"{y:04d}-01-01", f"{y:04d}-12-31"
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
    if period_type == "year":
        return f"Año {period_key}"
    return period_key


def is_period_current(period_type: str, period_start: str, period_end: str,
                     today: Optional[date_cls] = None) -> bool:
    # Usar UTC para consistencia con _iso_today() del endpoint principal.
    # Sin esto, servidores con TZ no-UTC pueden divergir del frontend cerca
    # de medianoche, marcando un período como "no current" cuando sí lo es.
    today = today or datetime.utcnow().date()
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

    Fase 3 (2026-05-30): delega en la SSoT `compute_net_deposited_db`.
    Mantenemos `include_baseline=False` para preservar la semántica
    histórica del endpoint /reportes (que nunca incluyó capital_inicio).
    """
    from snapshots_job import compute_net_deposited_db
    return compute_net_deposited_db(
        conn, uid,
        as_of_date=end_date,
        broker_filter=broker_filter,
        include_baseline=False,
    )


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

def _modified_dietz_pct(start_value: float, end_value: float, flows: float) -> Optional[float]:
    """Period return Modified Dietz.

    Devuelve None si el promedio invertido es <=0 (no se puede computar un %
    significativo — el frontend muestra "—"). NO clampa: si el portfolio cae
    -150%, devolvemos -150 (raro pero real para shorts/leverage).
    """
    avg = start_value + 0.5 * flows
    if avg <= 0:
        return None
    pnl = end_value - start_value - flows
    return (pnl / avg) * 100


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
    elif period_type == "year":
        # Sumamos los monthly_entries del año. start = capital_inicio del primer
        # mes con data; end = capital_final del último mes con data (o live
        # value si el año en curso). flows = suma de deposits/withdrawals.
        y = int(period_start[:4])
        rows = conn.execute(
            """SELECT month, capital_inicio, capital_final, deposits, withdrawals,
                       pnl_realized, pnl_unrealized
                 FROM monthly_entries
                WHERE user_id = ? AND broker = ? AND year = ?
                ORDER BY month ASC""",
            (uid, broker_filter, y),
        ).fetchall()
        if rows:
            start_value = float(rows[0]["capital_inicio"] or 0)
            end_value = float(rows[-1]["capital_final"] or 0)
            deposits = sum(float(r["deposits"] or 0) for r in rows)
            withdrawals = sum(float(r["withdrawals"] or 0) for r in rows)
            unrealized = float(rows[-1]["pnl_unrealized"] or 0)
        if live_value is not None and is_period_current(period_type, period_start, period_end):
            end_value = float(live_value)
    else:
        # week / day: snapshots para start/end
        snap_start = fetch_snapshot_at_or_before(conn, uid, period_start)
        snap_end = fetch_snapshot_at_or_before(conn, uid, period_end)
        start_value = float(snap_start["total_value"]) if snap_start else 0.0
        if live_value is not None and is_period_current(period_type, period_start, period_end):
            end_value = float(live_value)
        else:
            end_value = float(snap_end["total_value"]) if snap_end else start_value
        # Audit follow-up (2026-05-31): usar net_deposited de los snapshots
        # como proxy de flows sub-mensuales. Antes asumíamos flows=0 → si el
        # user depositaba/retiraba entre el inicio del período y hoy, el
        # delta_usd raw lo contaba como ganancia/pérdida → "P&L semana"
        # divergía del Dashboard chart "1S" (que sí descontaba flujos).
        # Con net_deposited podemos calcular flows = end_netdep - start_netdep.
        start_netdep = float(snap_start["net_deposited"] or 0) if snap_start else 0.0
        if live_value is not None and is_period_current(period_type, period_start, period_end):
            # Live: usamos cum_aportado (calculado más abajo, pero acá usamos
            # SUM monthly_entries directamente para evitar referencia circular).
            row = conn.execute(
                """SELECT COALESCE(SUM(deposits - withdrawals), 0) AS net
                     FROM monthly_entries
                    WHERE user_id=? AND broker=? AND broker <> 'global'""",
                (uid, broker_filter),
            ).fetchone() if broker_filter != "global" else conn.execute(
                """SELECT COALESCE(SUM(deposits - withdrawals), 0) AS net
                     FROM monthly_entries
                    WHERE user_id=? AND broker='global'""",
                (uid,),
            ).fetchone()
            end_netdep = float(row["net"] or 0) if row else 0.0
        else:
            end_netdep = float(snap_end["net_deposited"] or 0) if snap_end else start_netdep
        # flows sub-mensuales derivados de los snapshots
        deposits = max(0.0, end_netdep - start_netdep)
        withdrawals = max(0.0, start_netdep - end_netdep)

    flows = deposits - withdrawals
    delta_usd = end_value - start_value - flows
    delta_pct_val = _modified_dietz_pct(start_value, end_value, flows)
    delta_pct = round(delta_pct_val, 2) if delta_pct_val is not None else None

    # Para day/week, el unrealized del período = todo el delta que no es
    # realized (las posiciones abiertas se movieron en su mark-to-market).
    # monthly_entries trae unrealized directo; day/week lo derivamos.
    if period_type in ("day", "week"):
        unrealized = delta_usd - realized

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
        delta_pct=delta_pct,
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
    "year":  ("Año", "m"),
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
    # delta_pct puede ser None (avg<=0) — caemos a "sin grandes movimientos"
    delta = metrics.delta_pct if metrics.delta_pct is not None else 0.0
    abs_usd = abs(metrics.delta_usd or 0)
    realized = metrics.realized_pnl or 0
    period_word, gender = _PERIOD_WORD.get(period_type, ("Período", "m"))

    # Caso especial: cerraste operaciones ganadoras pero el portfolio total bajó
    # (mark-to-market negativo). El user "ganó plata" en lo que cerró, aunque
    # el delta total sea rojo. Lo hacemos explícito para evitar el headline
    # "perdiste X%" cuando en realidad cerraste con ganancia.
    if realized >= 50 and delta < -0.5 and metrics.trades_count > 0:
        return (
            f"Cerraste con ganancia (+US$ {realized:,.0f}), pero el portfolio bajó {abs(delta):.1f}%.".replace(",", "."),
            "Operaciones ganadoras compensadas por mark-to-market negativo de las posiciones abiertas.",
        )
    # Caso simétrico inverso: cerraste con pérdida pero el portfolio subió por mark-to-market positivo
    if realized <= -50 and delta > 0.5 and metrics.trades_count > 0:
        return (
            f"Operaciones con pérdida (US$ {realized:,.0f}), pero el portfolio subió {delta:.1f}%.".replace(",", "."),
            "Mark-to-market positivo compensó las pérdidas realizadas.",
        )

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


# ─── Narrativa larga (qué pasó en el período) ────────────────────────────────

def generate_narrative(metrics: "PeriodMetrics", drivers: List["AssetContribution"],
                       highlights: List["Highlight"], period_type: str,
                       period_label_str: str) -> Optional[str]:
    """Genera un párrafo de 2-4 oraciones contando qué pasó en el período.

    Determinístico — combina métricas, drivers y benchmark. No usa LLM.
    Devuelve None si el período no tiene actividad relevante.
    """
    delta = metrics.delta_pct if metrics.delta_pct is not None else 0.0
    abs_usd = abs(metrics.delta_usd or 0)
    realized = metrics.realized_pnl or 0
    if abs(delta) < 0.5 and abs_usd < 100 and metrics.trades_count == 0:
        return None

    parts: List[str] = []

    # Oración 1: balance general del período en USD y %.
    # Caso especial: realized positivo pero delta total negativo (o viceversa).
    # No usamos "ganaste/perdiste" sin contexto porque las dos cosas pueden ser
    # ciertas a la vez — separamos "valor del portfolio" de "P&L realizado".
    mismatch = (realized >= 50 and delta < -0.5) or (realized <= -50 and delta > 0.5)
    if mismatch:
        port_dir = "bajó" if delta < 0 else "subió"
        real_sign = "+" if realized >= 0 else "−"
        parts.append(
            f"En {period_label_str.lower()} tu portfolio {port_dir} US$ {abs(metrics.delta_usd):,.0f} ({delta:+.1f}%), "
            f"pero las operaciones cerradas dejaron {real_sign}US$ {abs(realized):,.0f} de P&L realizado. "
            f"La diferencia viene del mark-to-market de tus posiciones abiertas."
            .replace(",", ".")
        )
    else:
        direction = "ganaste" if delta >= 0 else "perdiste"
        parts.append(
            f"En {period_label_str.lower()} {direction} "
            f"US$ {abs(metrics.delta_usd):,.0f} ({delta:+.1f}%) "
            f"sobre un capital inicial de US$ {metrics.start_value:,.0f}."
            .replace(",", ".")
        )

    # Oración 2: drivers principales (top + bottom).
    top_pos = next((d for d in drivers if d.pnl_usd > 0), None)
    top_neg = next((d for d in reversed(drivers) if d.pnl_usd < 0), None)
    driver_bits: List[str] = []
    if top_pos and abs(top_pos.pnl_usd) >= 50:
        driver_bits.append(
            f"{top_pos.asset} aportó +US$ {top_pos.pnl_usd:,.0f}".replace(",", ".")
        )
    if top_neg and abs(top_neg.pnl_usd) >= 50:
        driver_bits.append(
            f"{top_neg.asset} restó US$ {abs(top_neg.pnl_usd):,.0f}".replace(",", ".")
        )
    if driver_bits:
        parts.append("Los movimientos más relevantes: " + " · ".join(driver_bits) + ".")

    # Oración 3: flujos de capital del período.
    net_flow = metrics.deposits - metrics.withdrawals
    if abs(net_flow) >= 100:
        if net_flow > 0:
            parts.append(f"Aportaste US$ {net_flow:,.0f} de capital nuevo.".replace(",", "."))
        else:
            parts.append(f"Retiraste US$ {abs(net_flow):,.0f} del portfolio.".replace(",", "."))

    # Oración 4: trades cerrados + win rate.
    if metrics.trades_count > 0:
        wr = metrics.win_rate
        wr_str = f" con {wr:.0f}% de win rate" if wr is not None else ""
        parts.append(
            f"Cerraste {metrics.trades_count} operación{'es' if metrics.trades_count != 1 else ''}"
            f"{wr_str}, sumando US$ {metrics.realized_pnl:+,.0f} de P&L realizado.".replace(",", ".")
        )

    # Oración 5: comparativa vs S&P 500 (solo si hay dato).
    if metrics.vs_sp500_pct is not None and abs(metrics.vs_sp500_pct) >= 0.5:
        sign = "encima" if metrics.vs_sp500_pct > 0 else "debajo"
        parts.append(
            f"Quedaste {abs(metrics.vs_sp500_pct):.1f} puntos por {sign} del S&P 500."
        )

    return " ".join(parts) if parts else None


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
    narrative = generate_narrative(metrics, drivers, highlights, period_type, label)

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
        narrative=narrative,
    )
