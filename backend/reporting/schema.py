"""Dataclasses puras del módulo de reportes.

Estos structs viajan al frontend tal cual (vía .__dict__ o asdict). El shape
acá define el contrato con el frontend — modificarlo requiere update del UI.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


# ─── Sub-structs ─────────────────────────────────────────────────────────────

@dataclass
class Insight:
    """Chip narrativo con evidencia clickeable.

    `evidence` tiene shape libre — cada detector elige qué datos mandar:
    posiciones, operaciones, métricas. El frontend lo renderiza en un popover.
    """
    code: str                          # 'BTC_DRIVER' | 'CONCENTRATION_RISK' | ...
    severity: str                      # 'positive' | 'warning' | 'info'
    title: str                         # 1 línea
    body: str                          # 2-3 oraciones explicando
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Highlight:
    """Item destacado (mejor op, peor día, etc.). Visible siempre, sin click."""
    kind: str                          # 'best_op' | 'worst_op' | 'best_week' | ...
    icon: str                          # emoji o nombre de lucide-icon
    label: str                         # 'Mejor operación'
    value_label: str                   # 'BTC +$1,234'
    context: Optional[str] = None      # '14 de mayo'


@dataclass
class AssetContribution:
    """Atribución por activo al P&L del período."""
    asset: str
    pnl_usd: float
    contribution_pct: float            # % del P&L total del período


@dataclass
class HoldingMover:
    """Contribución MtM de un holding al período (incluye NO realizado).

    Sale de diferenciar la foto por activo (snapshots.holdings_json) entre los
    bordes del período. A diferencia de AssetContribution (solo ops cerradas),
    esto captura qué holding movió tu cartera aunque no lo hayas tradeado.
    """
    asset: str
    delta_usd: float                   # cambio de valor del holding en el período (USD)
    delta_pct: Optional[float]         # % de variación del holding (null si sin valor inicial)
    kind: str                          # 'best' | 'worst'


@dataclass
class PeriodMetrics:
    """Métricas core del período. Se renderizan en la cara "técnica" del card."""
    start_value: float
    end_value: float
    delta_usd: float
    delta_pct: Optional[float]         # TWRR (Modified Dietz); None si base incompleta (AUDIT B16)
    delta_pct_over_contrib: Optional[float]  # alternativa conservadora
    realized_pnl: float
    unrealized_pnl: float
    deposits: float
    withdrawals: float
    trades_count: int
    win_count: int
    loss_count: int
    win_rate: Optional[float]          # null si trades_count == 0
    vs_sp500_pct: Optional[float]
    vs_inflation_pct: Optional[float]


@dataclass
class PeriodReport:
    """Reporte completo de un período (day/week/month)."""
    period_type: str                   # 'day' | 'week' | 'month'
    period_key: str                    # '2026-05-13' | '2026-W19' | '2026-05'
    period_label: str                  # 'Hoy' | 'Semana 19' | 'Mayo 2026'
    period_start: str                  # ISO date 'YYYY-MM-DD'
    period_end: str                    # ISO date
    is_current: bool                   # ¿es el período en curso?
    is_relevant: bool                  # false = "sin actividad", se colapsa
    headline: str                      # 1 línea generada del data
    subheadline: Optional[str]         # 2da línea complementaria
    metrics: PeriodMetrics
    insights: List[Insight] = field(default_factory=list)
    highlights: List[Highlight] = field(default_factory=list)
    drivers: List[AssetContribution] = field(default_factory=list)
    movers: List[HoldingMover] = field(default_factory=list)  # mejor/peor holding por MtM
    movers_available: bool = False     # true = había foto por activo en los bordes
    children: List["PeriodReport"] = field(default_factory=list)  # weeks dentro de month, etc.
    narrative: Optional[str] = None    # descripción narrativa larga (qué pasó)


def report_to_dict(r: PeriodReport) -> Dict[str, Any]:
    """Serializa un PeriodReport a dict (recursive sobre children)."""
    d = asdict(r)
    # asdict ya recursa sobre dataclasses anidadas, así que children quedan ok.
    return d
