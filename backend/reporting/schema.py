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
    # OJO: estos dos son el EXCESO en puntos porcentuales (cartera − benchmark),
    # que es lo que dice el nombre y lo que el frontend siempre asumió.
    # Hasta AUDIT D-2 guardaban el retorno PROPIO del benchmark, así que la
    # narrativa decía "quedaste 2,5 puntos por encima del S&P 500" en un mes de
    # −63,4%. El retorno del benchmark ahora vive en `sp500_return_pct` /
    # `inflation_pct`. Null si no se puede comparar (sin `delta_pct`).
    #
    # ⚠️ LA "CARTERA" DE CADA UNO NO ES LA MISMA (F5). `vs_sp500_pct` se mide en
    # la moneda del selector, igual que `delta_pct`. `vs_inflation_pct` se mide
    # SIEMPRE EN PESOS, porque la inflación del INDEC mide precios argentinos y
    # restársela a un rendimiento en dólares deja afuera la devaluación. El
    # rendimiento del que sale esa resta viaja en `retorno_ars_pct`: con el
    # selector en dólares NO es `delta_pct`, y quien muestre los dos juntos tiene
    # que usar ése.
    vs_sp500_pct: Optional[float]
    vs_inflation_pct: Optional[float]
    # Cuánto hizo el S&P en el período, EN LA MISMA MONEDA QUE `delta_pct`. Con el
    # selector en pesos es el S&P convertido (`performance.retorno_bench_en_moneda`,
    # la misma tabla `BENCH_EN_ARS` que usa el gráfico), no el S&P en dólares: si
    # no fuera el mismo número del que salió `vs_sp500_pct`, la tarjeta que muestra
    # los dos juntos se contradiría sola. Null cuando falta el TC para convertir.
    sp500_return_pct: Optional[float] = None
    inflation_pct: Optional[float] = None      # inflación AR del período
    # El rendimiento CON EL QUE SE HIZO la comparación contra inflación, medido en
    # PESOS. La inflación del INDEC mide precios argentinos; restársela a un
    # rendimiento en dólares es restar unidades distintas (le falta la
    # devaluación). Viaja aparte de `delta_pct` porque ese sigue la moneda del
    # selector: sin este campo, con el selector en dólares la tarjeta mostraría un
    # rendimiento y un exceso que no salen el uno del otro. Null cuando no se pudo
    # convertir — y entonces `vs_inflation_pct` tampoco se publica.
    retorno_ars_pct: Optional[float] = None
    # AUDIT D-1: true = las dos puntas del período no son comparables (start de
    # la cadena contable, end a mercado) → delta_usd/delta_pct no se publican.
    basis_incomparable: bool = False
    # En qué BASE se midió el período: 'mercado' = las dos puntas salieron de
    # cierres medidos (o reconstruidos a precio real); 'contable' = de la cadena
    # de monthly_entries. Importa porque para un mes CERRADO la cadena garantiza
    # `capital_final = capital_inicio + flujos + pnl_realized` (main.py:9316-9318),
    # así que `end − start − flows` es EXACTAMENTE `pnl_realized`: el número no
    # sabe nada del mercado. Eso es lo que producía "+3,6% anual" en una cuenta
    # que a mercado se había derrumbado, y "9 de 12 meses positivos" perdiendo plata.
    basis: str = "contable"
    # ⚠️ POR QUÉ EL NÚMERO NO ESTÁ, CUANDO NO ESTÁ. `basis_incomparable` sólo cubre
    # un caso (las dos puntas en bases distintas). Cuando el motor canónico corta
    # por una foto que no cierra o por una contabilidad que no coincide con la
    # primera medición, Reportes publicaba igual desde la cadena mensual: la misma
    # cuenta leía "—" en Métricas y un porcentaje acá. Ahora el motivo viaja y la
    # pantalla dice lo mismo que la otra.
    motor_motivo: Optional[str] = None
    motor_motivo_texto: Optional[str] = None
    # La ventana que el % REALMENTE cubre cuando lo midió el motor (puede ser más
    # corta que el período: "del 3 al 31 de julio", no "julio entero").
    medido_desde: Optional[str] = None
    medido_hasta: Optional[str] = None
    # ⚠️ LA VENTANA EN LA QUE SE MIDIÓ EL BENCHMARK, QUE ES LA DEL NÚMERO PUBLICADO
    # y no siempre la del motor: el % del año puede venir del motor, de la
    # composición contable o de las puntas, y cada fuente cubre un tramo distinto.
    # Se publica por dos razones: la pantalla tiene que poder decir "comparado del
    # 31/12 al 11/9" en vez de dejarlo implícito, y sin esto la ventana no es
    # observable — un test sobre el veredicto pasa igual midiendo el tramo
    # equivocado, que fue exactamente lo que pasó auditando esto.
    bench_desde: Optional[str] = None
    bench_hasta: Optional[str] = None
    # Con qué modo y en qué moneda se midió — los mismos dos controles que Métricas.
    modo: str = "certero"
    moneda: str = "usd"


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
