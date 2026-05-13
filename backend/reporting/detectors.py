"""Motor de detección de insights — reglas determinísticas sobre un PeriodReport.

Cada detector es una función standalone que recibe el contexto y devuelve
un Insight o None. El registry los compone en `run_detectors`.

Filosofía:
- Reglas simples, no ML/LLM (Phase 1).
- Cada insight tiene "evidencia" — frontend la muestra al clickear.
- Severity acota la intensidad visual: positive (verde), warning (amber), info (gris).
- Si en duda, devolver None. Mejor silencio que ruido.
"""
from __future__ import annotations
from typing import List, Optional, Dict, Any

from .schema import PeriodReport, Insight


# ─── Contexto que se pasa a los detectores ───────────────────────────────────
# Cada detector recibe el report + datos adicionales (positions actuales, etc).
# Para Phase 1, el contexto es minimalista. Si un detector necesita más data,
# la fetcheamos en run_detectors.


def _push(out: List[Insight], i: Optional[Insight]) -> None:
    if i is not None:
        out.append(i)


# ─── Detectores individuales ─────────────────────────────────────────────────

def detect_concentration_risk(report: PeriodReport, positions: List[Dict[str, Any]]) -> Optional[Insight]:
    """Si un solo activo es >40% del portfolio al cierre del período."""
    if not positions:
        return None
    # Suma valor por activo (excluyendo cash)
    by_asset: Dict[str, float] = {}
    total = 0.0
    for p in positions:
        if p.get("is_cash"):
            continue
        v = float(p.get("value_usd") or 0)
        if v <= 0:
            continue
        a = (p.get("asset") or "").upper()
        by_asset[a] = by_asset.get(a, 0.0) + v
        total += v
    if total < 100:
        return None
    if not by_asset:
        return None
    top_asset, top_value = max(by_asset.items(), key=lambda kv: kv[1])
    pct = top_value / total * 100
    if pct < 40:
        return None
    severity = "warning" if pct >= 60 else "info"
    return Insight(
        code="CONCENTRATION_RISK",
        severity=severity,
        title=f"Tu portfolio depende mucho de {top_asset}",
        body=(
            f"{top_asset} representa el {pct:.0f}% del valor de tu portfolio. "
            f"Si baja fuerte, te impacta mucho. Considerá diversificar."
        ),
        evidence={"type": "positions", "asset": top_asset, "pct": round(pct, 1)},
    )


def detect_driver_of_period(report: PeriodReport) -> Optional[Insight]:
    """Si un activo explicó >40% del P&L total del período, marcarlo."""
    if not report.drivers:
        return None
    top = report.drivers[0]
    if top.contribution_pct < 40:
        return None
    if abs(top.pnl_usd) < 50:
        return None  # contribución alta % pero monto chico → ruido
    direction = "ganancia" if top.pnl_usd > 0 else "pérdida"
    severity = "info"  # neutral — solo describe, no juzga
    return Insight(
        code="DRIVER_OF_PERIOD",
        severity=severity,
        title=f"{top.asset} fue el motor del período",
        body=(
            f"{top.asset} explicó el {top.contribution_pct:.0f}% de la "
            f"{direction} (US${abs(top.pnl_usd):,.0f}). "
            f"Tu rendimiento depende fuerte de cómo se mueve este activo."
        ),
        evidence={"type": "asset", "asset": top.asset, "pnl": top.pnl_usd},
    )


def detect_high_turnover(report: PeriodReport, avg_trades_per_period: float = 0) -> Optional[Insight]:
    """Si operaste mucho más que tu promedio (≥2x), advertencia de turnover."""
    if report.metrics.trades_count < 5:
        return None  # base chica, no comparar
    if avg_trades_per_period <= 0:
        return None
    ratio = report.metrics.trades_count / avg_trades_per_period
    if ratio < 2:
        return None
    return Insight(
        code="HIGH_TURNOVER",
        severity="info",
        title="Operaste más que tu promedio",
        body=(
            f"Hiciste {report.metrics.trades_count} operaciones — "
            f"{ratio:.1f}x tu promedio histórico. "
            f"Más rotación = más comisiones y mayor probabilidad de errores."
        ),
        evidence={"type": "metric", "value": report.metrics.trades_count, "avg": round(avg_trades_per_period, 1)},
    )


def detect_deposits_vs_gains(report: PeriodReport) -> Optional[Insight]:
    """Si el crecimiento del período vino mayormente de aportes y no de rendimiento."""
    deps = report.metrics.deposits
    delta = report.metrics.delta_usd
    if deps < 500:
        return None
    growth_from_market = delta  # delta ya excluye flujos por construcción
    if abs(growth_from_market) >= deps * 0.3:
        return None  # el rendimiento fue significativo, no es "solo aportes"
    if deps < abs(growth_from_market) * 3:
        return None  # los flujos no dominan
    return Insight(
        code="DEPOSITS_DRIVE_GROWTH",
        severity="info",
        title="El crecimiento vino de aportes, no de rendimiento",
        body=(
            f"Aportaste US${deps:,.0f} este período. "
            f"El portfolio creció US${delta:+,.0f} por rendimiento de mercado. "
            f"La mayor parte del aumento de valor fue plata que pusiste, no que generaste."
        ),
        evidence={"type": "metric", "deposits": deps, "market_growth": delta},
    )


def detect_win_rate_delta(report: PeriodReport, historical_win_rate: Optional[float]) -> Optional[Insight]:
    """Win rate del período vs el histórico del usuario. Sube o baja >10pp."""
    wr = report.metrics.win_rate
    if wr is None or report.metrics.trades_count < 4:
        return None
    if historical_win_rate is None:
        return None
    delta = wr - historical_win_rate
    if abs(delta) < 10:
        return None
    if delta > 0:
        return Insight(
            code="WIN_RATE_UP",
            severity="positive",
            title="Tu acierto subió este período",
            body=(
                f"Win rate del período: {wr:.0f}% (tu histórico: {historical_win_rate:.0f}%). "
                f"+{delta:.0f} puntos."
            ),
            evidence={"type": "metric", "period_wr": wr, "historical_wr": historical_win_rate},
        )
    return Insight(
        code="WIN_RATE_DOWN",
        severity="warning",
        title="Tu acierto bajó este período",
        body=(
            f"Win rate del período: {wr:.0f}% (tu histórico: {historical_win_rate:.0f}%). "
            f"{delta:.0f} puntos. Revisá si las decisiones fueron impulsivas."
        ),
        evidence={"type": "metric", "period_wr": wr, "historical_wr": historical_win_rate},
    )


def detect_vs_benchmark(report: PeriodReport) -> Optional[Insight]:
    """Performance vs S&P 500 — solo aplica a períodos mensuales con bench disponible."""
    if report.period_type != "month":
        return None
    sp = report.metrics.vs_sp500_pct
    if sp is None:
        return None
    delta = report.metrics.delta_pct - sp
    if abs(delta) < 1.0:
        return None  # casi igual, no es noticia
    if delta > 0:
        return Insight(
            code="BEAT_BENCHMARK",
            severity="positive",
            title="Le ganaste al S&P 500",
            body=(
                f"Tu portfolio: {report.metrics.delta_pct:+.1f}%. "
                f"S&P 500: {sp:+.1f}%. Diferencia: +{delta:.1f} puntos."
            ),
            evidence={"type": "metric", "portfolio": report.metrics.delta_pct, "sp500": sp},
        )
    return Insight(
        code="UNDERPERFORM_BENCHMARK",
        severity="info",
        title="El S&P 500 te ganó",
        body=(
            f"Tu portfolio: {report.metrics.delta_pct:+.1f}%. "
            f"S&P 500: {sp:+.1f}%. Diferencia: {delta:.1f} puntos."
        ),
        evidence={"type": "metric", "portfolio": report.metrics.delta_pct, "sp500": sp},
    )


def detect_large_cash_drag(report: PeriodReport, positions: List[Dict[str, Any]]) -> Optional[Insight]:
    """Más del 30% del portfolio en cash. Es plata sin trabajar (especialmente
    en períodos inflacionarios o de mercado alcista)."""
    if not positions:
        return None
    cash_value = sum(float(p.get("value_usd") or 0) for p in positions if p.get("is_cash"))
    total = sum(float(p.get("value_usd") or 0) for p in positions)
    if total < 1000:
        return None
    cash_pct = cash_value / total * 100
    if cash_pct < 30:
        return None
    return Insight(
        code="LARGE_CASH_DRAG",
        severity="info",
        title=f"{cash_pct:.0f}% de tu portfolio está en cash",
        body=(
            f"Tenés US${cash_value:,.0f} sin invertir ({cash_pct:.0f}% del total). "
            f"Considerá si esa proporción de liquidez está alineada con tus objetivos — "
            f"el cash pierde poder adquisitivo con inflación."
        ),
        evidence={"type": "metric", "cash_usd": round(cash_value, 0), "cash_pct": round(cash_pct, 1)},
    )


def detect_streak(report: PeriodReport, prior_deltas: List[float]) -> Optional[Insight]:
    """Racha: ≥3 períodos seguidos del mismo signo, contando el actual.
    `prior_deltas` viene en orden cronológico ascendente, sin incluir el reporte actual."""
    if report.period_type != "month":
        return None
    current = report.metrics.delta_pct
    if abs(current) < 0.5:
        return None
    sign = 1 if current > 0 else -1
    streak = 1
    for d in reversed(prior_deltas):
        if abs(d) < 0.5:
            break
        if (d > 0 and sign > 0) or (d < 0 and sign < 0):
            streak += 1
        else:
            break
    if streak < 3:
        return None
    if sign > 0:
        return Insight(
            code="STREAK_POSITIVE",
            severity="positive",
            title=f"Vas {streak} meses positivos seguidos",
            body=f"El portfolio acumula {streak} meses consecutivos en verde. Buena inercia — pero no te confíes, los ciclos cambian.",
            evidence={"type": "metric", "streak": streak, "sign": "positive"},
        )
    return Insight(
        code="STREAK_NEGATIVE",
        severity="warning",
        title=f"Vas {streak} meses negativos seguidos",
        body=f"Llevás {streak} meses consecutivos en rojo. Revisá si la estrategia o exposición necesitan ajuste antes de que se profundice.",
        evidence={"type": "metric", "streak": streak, "sign": "negative"},
    )


def detect_realized_vs_unrealized_gap(report: PeriodReport) -> Optional[Insight]:
    """Cerraste ganancias importantes pero el portfolio actual está en pérdida
    no realizada. Patrón clásico de "vender ganadoras temprano, holdear perdedoras"."""
    if report.period_type != "month":
        return None
    realized = report.metrics.realized_pnl
    unrealized = report.metrics.unrealized_pnl
    if realized < 500:
        return None
    if unrealized > -realized * 0.5:
        return None  # las no realizadas no son lo suficientemente negativas
    if abs(unrealized) < 500:
        return None
    return Insight(
        code="REALIZED_VS_UNREALIZED_GAP",
        severity="warning",
        title="Cerraste ganancias pero arrastrás pérdidas abiertas",
        body=(
            f"Realizaste US${realized:,.0f} este período, pero tus posiciones abiertas "
            f"están US${abs(unrealized):,.0f} en negativo. "
            f"Cuidado con vender ganadoras temprano y holdear perdedoras — sesgo común."
        ),
        evidence={"type": "metric", "realized": realized, "unrealized": unrealized},
    )


def detect_reversal(report: PeriodReport, prior_delta: Optional[float]) -> Optional[Insight]:
    """Período anterior y actual con signos opuestos y magnitud significativa.
    Sirve para señalar volatilidad: "Mes anterior +8%, este -5%"."""
    if report.period_type != "month":
        return None
    if prior_delta is None:
        return None
    current = report.metrics.delta_pct
    if (prior_delta * current) >= 0:
        return None  # mismo signo
    if abs(prior_delta) < 2 or abs(current) < 2:
        return None  # alguno de los dos es muy chico
    direction = "ganancia" if current > 0 else "pérdida"
    return Insight(
        code="REVERSAL",
        severity="info",
        title="Cambio de tendencia respecto del mes anterior",
        body=(
            f"El mes pasado cerró con {prior_delta:+.1f}%, este con {current:+.1f}%. "
            f"Pasaste de {'pérdida' if prior_delta < 0 else 'ganancia'} a {direction}. "
            f"Si el patrón se repite, considerá revisar tu exposición."
        ),
        evidence={"type": "metric", "prior_delta": prior_delta, "current_delta": current},
    )


def detect_dividend_heavy(report: PeriodReport, ops: List[Dict[str, Any]]) -> Optional[Insight]:
    """Si los dividendos+intereses fueron >50% del realized, marcarlo —
    señala estrategia income-driven (no es bueno ni malo, es informativo)."""
    if not ops:
        return None
    div_int = sum(
        float(o.get("pnl_usd") or 0)
        for o in ops
        if (o.get("op_type") or "") in ("Dividendo", "Interés")
    )
    total_realized = report.metrics.realized_pnl
    if div_int < 50 or total_realized <= 0:
        return None
    pct = div_int / total_realized * 100
    if pct < 50:
        return None
    return Insight(
        code="DIVIDEND_HEAVY",
        severity="info",
        title=f"Los dividendos explicaron el {pct:.0f}% del rendimiento",
        body=(
            f"Cobraste US${div_int:,.0f} en dividendos e intereses (de US${total_realized:,.0f} totales realizados). "
            f"Es income que no depende de timing — pero significa que tu trading activo "
            f"aportó relativamente poco al resultado."
        ),
        evidence={"type": "metric", "dividends_interest": div_int, "total_realized": total_realized, "pct": round(pct, 1)},
    )


def detect_consistency(report: PeriodReport) -> Optional[Insight]:
    """Para un mes con children semanales: cuántas semanas positivas vs negativas."""
    if report.period_type != "month" or not report.children:
        return None
    weeks = [c for c in report.children if c.period_type == "week" and c.is_relevant]
    if len(weeks) < 2:
        return None
    pos = sum(1 for w in weeks if w.metrics.delta_pct > 0.2)
    neg = sum(1 for w in weeks if w.metrics.delta_pct < -0.2)
    total = len(weeks)
    if pos == total:
        return Insight(
            code="CONSISTENT_POSITIVE",
            severity="positive",
            title="Mes consistente",
            body=f"Las {total} semanas relevantes terminaron positivas. Buena estabilidad.",
            evidence={"type": "metric", "positive_weeks": pos, "total_weeks": total},
        )
    if neg == total:
        return Insight(
            code="CONSISTENT_NEGATIVE",
            severity="warning",
            title="Mes con caídas sostenidas",
            body=f"Las {total} semanas relevantes terminaron negativas. Revisá tu exposición.",
            evidence={"type": "metric", "negative_weeks": neg, "total_weeks": total},
        )
    return None  # mes mixto = sin insight (es la norma)


# ─── Orchestrator ────────────────────────────────────────────────────────────

def run_detectors(report: PeriodReport, *,
                   positions: List[Dict[str, Any]] = None,
                   avg_trades_per_period: float = 0,
                   historical_win_rate: Optional[float] = None,
                   prior_monthly_deltas: List[float] = None,
                   period_operations: List[Dict[str, Any]] = None) -> List[Insight]:
    """Ejecuta todos los detectores y devuelve los insights ordenados por
    severity (warning primero, después positive, después info).

    Args:
        report: el período base
        positions: posiciones actuales (para CONCENTRATION_RISK, LARGE_CASH_DRAG)
        avg_trades_per_period: promedio histórico (para HIGH_TURNOVER)
        historical_win_rate: win rate histórico del user (para WIN_RATE_DELTA)
        prior_monthly_deltas: deltas de meses anteriores en orden ascendente
                             (para STREAK y REVERSAL)
        period_operations: operations del período (para DIVIDEND_HEAVY)
    """
    positions = positions or []
    prior_monthly_deltas = prior_monthly_deltas or []
    period_operations = period_operations or []
    out: List[Insight] = []
    # Detectores que pueden generar warnings — más prominentes en la UI
    _push(out, detect_concentration_risk(report, positions))
    _push(out, detect_streak(report, prior_monthly_deltas))
    _push(out, detect_realized_vs_unrealized_gap(report))
    _push(out, detect_high_turnover(report, avg_trades_per_period))
    _push(out, detect_consistency(report))
    _push(out, detect_win_rate_delta(report, historical_win_rate))
    # Detectores informativos / neutros
    _push(out, detect_driver_of_period(report))
    _push(out, detect_deposits_vs_gains(report))
    _push(out, detect_vs_benchmark(report))
    _push(out, detect_large_cash_drag(report, positions))
    _push(out, detect_reversal(report, prior_monthly_deltas[-1] if prior_monthly_deltas else None))
    _push(out, detect_dividend_heavy(report, period_operations))

    # Orden: warning → positive → info
    severity_order = {"warning": 0, "positive": 1, "info": 2}
    out.sort(key=lambda i: severity_order.get(i.severity, 9))
    return out
