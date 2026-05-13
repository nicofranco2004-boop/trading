// InsightEvidence — renderizado contextual de la evidencia del insight.
//
// Cada `code` de insight tiene un renderer específico. Si no hay match,
// fallback al JSON crudo (para developer debugging).
//
// Diseño: mini-cards con bars/grids/comparisons en vez de listas planas.
// El objetivo es que el user "vea" la evidencia, no que la lea.

function fmtUsd(v) {
  if (v == null) return '—'
  const sign = v < 0 ? '−' : ''
  return `${sign}US$${Math.abs(v).toLocaleString('es-AR', { maximumFractionDigits: 0 })}`
}

function fmtPct(p, withSign = true) {
  if (p == null) return '—'
  const sign = withSign ? (p >= 0 ? '+' : '−') : (p < 0 ? '−' : '')
  return `${sign}${Math.abs(p).toFixed(1)}%`
}

// ─── Renderers por código de insight ────────────────────────────────────────

function ConcentrationRiskEvidence({ ev }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-[11px]">
        <span className="text-ink-2 font-mono">{ev.asset}</span>
        <span className="text-ink-1 font-mono tabular">{fmtPct(ev.pct, false)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-bg-3 overflow-hidden">
        <div
          className="h-full bg-rendi-warn"
          style={{ width: `${Math.min(100, ev.pct)}%` }}
          aria-hidden="true"
        />
      </div>
      <p className="text-[10px] text-ink-3">
        Concentración aceptable: hasta 25–30% por activo.
      </p>
    </div>
  )
}

function DriverEvidence({ ev }) {
  return (
    <div className="rounded-sm bg-bg-3/40 px-2.5 py-2 text-[11px]">
      <div className="flex items-baseline justify-between mb-0.5">
        <span className="font-mono text-ink-1">{ev.asset}</span>
        <span className={`font-mono tabular ${ev.pnl >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
          {fmtUsd(ev.pnl)}
        </span>
      </div>
      <p className="text-[10px] text-ink-3">P&L realizado de este activo en el período.</p>
    </div>
  )
}

function VsBenchmarkEvidence({ ev }) {
  const portfolio = ev.portfolio
  const benchmark = ev.sp500
  const portfolioWon = portfolio > benchmark
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-ink-2">Portfolio</span>
        <span className={`font-mono tabular ${portfolio >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
          {fmtPct(portfolio)}
        </span>
      </div>
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-ink-2">S&P 500</span>
        <span className="font-mono tabular text-ink-1">{fmtPct(benchmark)}</span>
      </div>
      <div className="text-[10px] text-ink-3 pt-1 border-t border-line/40">
        Diferencia: <span className={`font-mono tabular ${portfolioWon ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
          {fmtPct(portfolio - benchmark)} puntos
        </span>
      </div>
    </div>
  )
}

function WinRateEvidence({ ev }) {
  return (
    <div className="space-y-2 text-[11px]">
      <div className="flex items-baseline justify-between">
        <span className="text-ink-2">Este período</span>
        <span className="font-mono tabular text-ink-0">{ev.period_wr?.toFixed(0)}%</span>
      </div>
      <div className="flex items-baseline justify-between">
        <span className="text-ink-2">Promedio histórico</span>
        <span className="font-mono tabular text-ink-1">{ev.historical_wr?.toFixed(0)}%</span>
      </div>
    </div>
  )
}

function DepositsDriveEvidence({ ev }) {
  const deps = ev.deposits || 0
  const market = ev.market_growth || 0
  const totalAbs = deps + Math.abs(market) || 1
  const depsPct = (deps / totalAbs) * 100
  const marketPct = (Math.abs(market) / totalAbs) * 100
  return (
    <div className="space-y-2">
      <div className="flex h-2 rounded-full overflow-hidden bg-bg-3">
        <div className="bg-ink-2/60" style={{ width: `${depsPct}%` }} aria-hidden="true" />
        <div
          className={market >= 0 ? 'bg-rendi-pos/70' : 'bg-rendi-neg/70'}
          style={{ width: `${marketPct}%` }}
          aria-hidden="true"
        />
      </div>
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div>
          <div className="text-ink-3 uppercase tracking-wider text-[9px]">Aportaste</div>
          <div className="font-mono tabular text-ink-1">{fmtUsd(deps)}</div>
        </div>
        <div>
          <div className="text-ink-3 uppercase tracking-wider text-[9px]">Mercado</div>
          <div className={`font-mono tabular ${market >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
            {fmtUsd(market)}
          </div>
        </div>
      </div>
    </div>
  )
}

function CashDragEvidence({ ev }) {
  return (
    <div className="space-y-1.5 text-[11px]">
      <div className="flex items-baseline justify-between">
        <span className="text-ink-2">En cash</span>
        <span className="font-mono tabular text-ink-1">{fmtUsd(ev.cash_usd)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-bg-3 overflow-hidden">
        <div className="h-full bg-ink-2/50" style={{ width: `${Math.min(100, ev.cash_pct)}%` }} aria-hidden="true" />
      </div>
      <p className="text-[10px] text-ink-3">
        {fmtPct(ev.cash_pct, false)} del portfolio total.
      </p>
    </div>
  )
}

function StreakEvidence({ ev }) {
  const dots = Array.from({ length: Math.min(ev.streak, 12) })
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1">
        {dots.map((_, i) => (
          <span
            key={i}
            className={`block h-2 w-2 rounded-full ${
              ev.sign === 'positive' ? 'bg-rendi-pos' : 'bg-rendi-neg'
            }`}
            aria-hidden="true"
          />
        ))}
        <span className="text-[10px] text-ink-3 ml-1">{ev.streak} meses</span>
      </div>
    </div>
  )
}

function RealizedVsUnrealizedEvidence({ ev }) {
  return (
    <div className="grid grid-cols-2 gap-2 text-[11px]">
      <div className="rounded-sm bg-rendi-pos/[0.08] px-2 py-1.5 border border-rendi-pos/20">
        <div className="text-ink-3 uppercase tracking-wider text-[9px]">Realizado</div>
        <div className="font-mono tabular text-rendi-pos">{fmtUsd(ev.realized)}</div>
      </div>
      <div className="rounded-sm bg-rendi-neg/[0.08] px-2 py-1.5 border border-rendi-neg/20">
        <div className="text-ink-3 uppercase tracking-wider text-[9px]">No realizado</div>
        <div className="font-mono tabular text-rendi-neg">{fmtUsd(ev.unrealized)}</div>
      </div>
    </div>
  )
}

function ReversalEvidence({ ev }) {
  return (
    <div className="flex items-center justify-around text-[11px]">
      <div className="text-center">
        <div className="text-ink-3 uppercase tracking-wider text-[9px]">Mes anterior</div>
        <div className={`font-mono tabular text-base ${ev.prior_delta >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
          {fmtPct(ev.prior_delta)}
        </div>
      </div>
      <span className="text-ink-3 text-base" aria-hidden="true">→</span>
      <div className="text-center">
        <div className="text-ink-3 uppercase tracking-wider text-[9px]">Este mes</div>
        <div className={`font-mono tabular text-base ${ev.current_delta >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
          {fmtPct(ev.current_delta)}
        </div>
      </div>
    </div>
  )
}

function DividendHeavyEvidence({ ev }) {
  const totalPos = (ev.total_realized || 0) > 0 ? ev.total_realized : 1
  const divPct = ((ev.dividends_interest || 0) / totalPos) * 100
  const tradingPct = 100 - divPct
  return (
    <div className="space-y-2">
      <div className="flex h-2 rounded-full overflow-hidden bg-bg-3">
        <div className="bg-ink-2/50" style={{ width: `${divPct}%` }} aria-hidden="true" />
        <div className="bg-rendi-pos/60" style={{ width: `${tradingPct}%` }} aria-hidden="true" />
      </div>
      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div>
          <div className="text-ink-3 uppercase tracking-wider text-[9px]">Dividendos</div>
          <div className="font-mono tabular text-ink-1">{fmtUsd(ev.dividends_interest)}</div>
        </div>
        <div>
          <div className="text-ink-3 uppercase tracking-wider text-[9px]">Trading</div>
          <div className="font-mono tabular text-ink-1">
            {fmtUsd((ev.total_realized || 0) - (ev.dividends_interest || 0))}
          </div>
        </div>
      </div>
    </div>
  )
}

function ConsistencyEvidence({ ev }) {
  const total = ev.total_weeks || 0
  const positive = ev.positive_weeks || 0
  const negative = ev.negative_weeks || 0
  const neutral = total - positive - negative
  return (
    <div className="flex gap-0.5 text-[11px]">
      {Array.from({ length: positive }).map((_, i) => (
        <span key={`p${i}`} className="block flex-1 h-3 bg-rendi-pos rounded-sm" aria-hidden="true" />
      ))}
      {Array.from({ length: neutral }).map((_, i) => (
        <span key={`n${i}`} className="block flex-1 h-3 bg-bg-3 rounded-sm" aria-hidden="true" />
      ))}
      {Array.from({ length: negative }).map((_, i) => (
        <span key={`x${i}`} className="block flex-1 h-3 bg-rendi-neg rounded-sm" aria-hidden="true" />
      ))}
    </div>
  )
}

function HighTurnoverEvidence({ ev }) {
  return (
    <div className="grid grid-cols-2 gap-2 text-[11px]">
      <div>
        <div className="text-ink-3 uppercase tracking-wider text-[9px]">Este período</div>
        <div className="font-mono tabular text-ink-1">{ev.value} trades</div>
      </div>
      <div>
        <div className="text-ink-3 uppercase tracking-wider text-[9px]">Promedio</div>
        <div className="font-mono tabular text-ink-2">{ev.avg?.toFixed(1)}</div>
      </div>
    </div>
  )
}

// ─── Dispatcher ──────────────────────────────────────────────────────────────

const RENDERERS = {
  CONCENTRATION_RISK: ConcentrationRiskEvidence,
  DRIVER_OF_PERIOD:   DriverEvidence,
  HIGH_TURNOVER:      HighTurnoverEvidence,
  DEPOSITS_DRIVE_GROWTH: DepositsDriveEvidence,
  WIN_RATE_UP:        WinRateEvidence,
  WIN_RATE_DOWN:      WinRateEvidence,
  BEAT_BENCHMARK:     VsBenchmarkEvidence,
  UNDERPERFORM_BENCHMARK: VsBenchmarkEvidence,
  CONSISTENT_POSITIVE: ConsistencyEvidence,
  CONSISTENT_NEGATIVE: ConsistencyEvidence,
  LARGE_CASH_DRAG:    CashDragEvidence,
  STREAK_POSITIVE:    StreakEvidence,
  STREAK_NEGATIVE:    StreakEvidence,
  REALIZED_VS_UNREALIZED_GAP: RealizedVsUnrealizedEvidence,
  REVERSAL:           ReversalEvidence,
  DIVIDEND_HEAVY:     DividendHeavyEvidence,
}

export default function InsightEvidence({ insight }) {
  const Renderer = RENDERERS[insight.code]
  if (!insight.evidence || Object.keys(insight.evidence).length === 0) return null
  if (!Renderer) {
    // Fallback: JSON crudo (debug-only — debería no ocurrir en prod)
    return (
      <pre className="text-[10px] text-ink-3 font-mono px-2 py-1 rounded bg-bg-3 overflow-x-auto">
        {JSON.stringify(insight.evidence, null, 2)}
      </pre>
    )
  }
  return <Renderer ev={insight.evidence} />
}
