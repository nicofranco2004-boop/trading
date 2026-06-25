"""Timeline composer — arma la vista cronológica anidada de PeriodReports.

Reglas de composición (Phase 1):
- Devuelve los últimos N meses, cada uno con sus semanas como children.
- Días NO se computan en Phase 1 (no hay snapshots diarios).
- El mes en curso siempre es el primero, expandido visualmente (frontend).
- Meses cerrados con `is_relevant=False` (sin actividad) se siguen mostrando,
  pero el frontend los renderiza colapsados/minimal.

Reusa el builder de `builder.py` y los detectores de `detectors.py`.
"""
from __future__ import annotations
from datetime import date as date_cls, timedelta
from typing import List, Optional, Dict, Any

from .builder import build_period_report
from .detectors import run_detectors
from .schema import PeriodReport


def _months_back(months: int) -> List[str]:
    """Genera period_keys de los últimos N meses (incluyendo el actual),
    ordenados descendientes (más reciente primero)."""
    today = date_cls.today()
    out = []
    y, m = today.year, today.month
    for _ in range(months):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return out


def _weeks_in_month(year: int, month: int) -> List[str]:
    """Devuelve los period_keys de las ISO weeks que tocan el mes (Mon-Sun).
    Una semana "pertenece" al mes si el lunes está en ese mes."""
    first = date_cls(year, month, 1)
    if month == 12:
        next_m = date_cls(year + 1, 1, 1)
    else:
        next_m = date_cls(year, month + 1, 1)

    out: List[str] = []
    seen = set()
    d = first
    while d < next_m:
        iso_year, iso_week, _ = d.isocalendar()
        key = f"{iso_year:04d}-W{iso_week:02d}"
        if key not in seen:
            # Una semana "pertenece" al mes si el LUNES está en el mes.
            monday = d - timedelta(days=d.weekday())
            if monday.year == year and monday.month == month:
                out.append(key)
                seen.add(key)
        d += timedelta(days=1)
    return out


def _compute_user_historical_win_rate(conn, uid: int) -> Optional[float]:
    """Win rate lifetime del usuario sobre operaciones cerradas (excl. dividendos)."""
    rows = conn.execute(
        """SELECT pnl_usd, op_type FROM operations
            WHERE user_id = ? AND pnl_usd IS NOT NULL""",
        (uid,),
    ).fetchall()
    trades = [
        r for r in rows
        if (r["op_type"] or "") not in ("Compra", "Dividendo", "Interés")
        and not (r["op_type"] or "").startswith("Conversión")
        and not (r["op_type"] or "").startswith("CONVERSION")
    ]
    if not trades:
        return None
    wins = sum(1 for r in trades if r["pnl_usd"] > 0)
    return wins / len(trades) * 100


def _compute_avg_trades_per_month(conn, uid: int, lookback_months: int = 12) -> float:
    """Promedio mensual de trades cerrados en los últimos N meses."""
    today = date_cls.today()
    start = (today.replace(day=1) - timedelta(days=lookback_months * 30)).isoformat()
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM operations
            WHERE user_id = ? AND date >= ?
              AND (op_type NOT IN ('Compra', 'Dividendo', 'Interés')
                   AND op_type NOT LIKE 'Conversión%'
                   AND op_type NOT LIKE 'CONVERSION%')""",
        (uid, start),
    ).fetchone()
    n = (row["n"] if row else 0) or 0
    return n / max(lookback_months, 1)


def _fetch_positions_for_concentration(conn, uid: int, broker_filter: str,
                                        prices: Dict[str, Any], tc_blue: float) -> List[Dict[str, Any]]:
    """Devuelve lista de {asset, value_usd, is_cash} para usar en CONCENTRATION_RISK.

    Computa value en USD igual que el frontend (price × qty para non-cash,
    invested para cash). Cash en pesos → dólar-blue; holdings AR/.BA → dólar-MEP
    (tc_cedear), igual que el resto de Análisis. Ver CORRECTNESS_AUDIT (M-REP).
    """
    try:
        from analysis_prep import user_fx
        _, tc_cedear = user_fx(conn, uid)
        if not (tc_cedear and tc_cedear > 0):
            tc_cedear = tc_blue
    except Exception:
        tc_cedear = tc_blue
    br_sql = "" if broker_filter == "global" else " AND p.broker = ?"
    br_args = () if broker_filter == "global" else (broker_filter,)
    rows = conn.execute(
        f"""SELECT p.asset, p.asset_type, p.broker, p.quantity, p.invested,
                   p.is_cash, p.price_override, br.currency
              FROM positions p
              JOIN brokers br ON br.name = p.broker AND br.user_id = p.user_id
             WHERE p.user_id = ?{br_sql}""",
        (uid, *br_args),
    ).fetchall()

    # Valuamos por el canónico _position_value_usd: maneja el doble eje de moneda
    # (costo por _native_ccy; precio .BA por _price_is_ars ESTRUCTURAL → un CEDEAR
    # en sub-broker '· USD' rutea a .BA aunque currency='USDT'), el guard y el
    # price_override. Con prices={} cae a costo igual que antes (sin regresión),
    # pero elimina el residuo latente de rutear por currency=='ARS'. (LOW C1.)
    from behavioral import _position_value_usd
    out = []
    for r in rows:
        p = dict(r)
        v = _position_value_usd(p, prices, tc_blue, tc_cedear)
        out.append({"asset": r["asset"], "value_usd": v, "is_cash": bool(r["is_cash"])})
    return out


def build_timeline(
    conn, uid: int, *,
    broker_filter: str = "global",
    months: int = 12,
    bench: Optional[Dict[str, Any]] = None,
    live_value: Optional[float] = None,
    prices: Optional[Dict[str, Any]] = None,
    tc_blue: float = 1415.0,
) -> List[PeriodReport]:
    """Devuelve los últimos N meses con sus semanas como children.

    Cada PeriodReport incluye sus insights ya computados.
    """
    # Pre-cómputo de contexto reusable entre detectores
    historical_wr = _compute_user_historical_win_rate(conn, uid)
    avg_trades = _compute_avg_trades_per_month(conn, uid)
    positions = _fetch_positions_for_concentration(conn, uid, broker_filter,
                                                    prices or {}, tc_blue)

    month_keys = _months_back(months)
    # Procesamos los meses del más viejo al más nuevo para que podamos pasar
    # `prior_monthly_deltas` ascendiente a los detectores STREAK/REVERSAL.
    month_keys_asc = list(reversed(month_keys))
    out_asc: List[PeriodReport] = []
    prior_deltas: List[float] = []

    for mk in month_keys_asc:
        y, m = (int(x) for x in mk.split("-"))
        # 1. Construir reporte del mes
        month_rpt = build_period_report(
            conn, uid, "month", mk,
            broker_filter=broker_filter, bench=bench, live_value=live_value,
        )

        # 2. Operaciones del mes — para DIVIDEND_HEAVY y otros
        from .builder import fetch_operations_in_range
        month_ops = fetch_operations_in_range(
            conn, uid, month_rpt.period_start, month_rpt.period_end, broker_filter,
        )

        # 3. Construir reportes de las semanas dentro del mes
        weeks = _weeks_in_month(y, m)
        children: List[PeriodReport] = []
        for wk in weeks:
            wrpt = build_period_report(
                conn, uid, "week", wk,
                broker_filter=broker_filter, bench=bench,
                live_value=live_value if wrpt_is_current_check(wk) else None,
            )
            # Detectores en semanas: contexto reducido (no STREAK, no aggregate-level)
            wrpt.insights = run_detectors(
                wrpt, positions=[], avg_trades_per_period=0,
                historical_win_rate=historical_wr,
            )
            children.append(wrpt)
        month_rpt.children = children

        # 4. Detectores del mes con contexto completo
        month_rpt.insights = run_detectors(
            month_rpt, positions=positions,
            avg_trades_per_period=avg_trades,
            historical_win_rate=historical_wr,
            prior_monthly_deltas=list(prior_deltas),
            period_operations=month_ops,
        )

        out_asc.append(month_rpt)
        prior_deltas.append(month_rpt.metrics.delta_pct)

    # Devolver descendente (más reciente primero) — convención del frontend
    return list(reversed(out_asc))


def wrpt_is_current_check(week_key: str) -> bool:
    """¿La semana del key es la semana actual ISO? (para decidir liveValue)."""
    from datetime import date as _date
    y_str, w_str = week_key.split("-W")
    y, w = int(y_str), int(w_str)
    today = _date.today()
    iy, iw, _ = today.isocalendar()
    return iy == y and iw == w
