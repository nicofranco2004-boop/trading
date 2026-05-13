// MonthCard — el card premium de la timeline. Es el "hero" mensual.
//
// Layout:
//   ┌────────────────────────────────────────────┐
//   │ <MonthHero>                                │
//   │   Mayo 2026                       +5.6%    │
//   │   "Tu mejor mes del año."                  │
//   │   "BTC explicó el 64% del rendimiento."    │
//   ├────────────────────────────────────────────┤
//   │ <HighlightsRail>  best_op | worst_op       │
//   ├────────────────────────────────────────────┤
//   │ <Insights>  chips con evidencia            │
//   ├────────────────────────────────────────────┤
//   │ [Ver semanas ▾]  [Métricas técnicas ▾]     │
//   └────────────────────────────────────────────┘
//
// Estado:
//   - Mes en curso: badge "EN CURSO" + countdown.
//   - Mes cerrado: solo el delta + headline.
//   - Mes irrelevante (sin actividad): renderiza colapsado a 1 línea.
//
// Default visual:
//   - Mes en curso: expandido.
//   - Otros meses del año actual: expandidos.
//   - Años pasados: colapsados (decisión del Page).

import { useState } from 'react'
import { ChevronDown, ChevronUp, Calendar, BarChart2 } from 'lucide-react'
import InsightChip from './InsightChip'
import HighlightsRail from './HighlightsRail'
import WeekCard from './WeekCard'

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : '−'
  return `${sign}${Math.abs(p).toFixed(2)}%`
}

function fmtUsd(v) {
  if (v == null) return '—'
  const abs = Math.abs(v)
  const sign = v >= 0 ? '+' : '−'
  return `${sign}US$${abs.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`
}

function daysUntilMonthEnd(period_end_iso) {
  const today = new Date()
  const end = new Date(period_end_iso + 'T23:59:59')
  const diff = Math.ceil((end - today) / 86400000)
  return Math.max(0, diff)
}

export default function MonthCard({ month, defaultExpanded = false }) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [weeksOpen, setWeeksOpen] = useState(false)
  const [metricsOpen, setMetricsOpen] = useState(false)
  const positive = month.metrics.delta_pct >= 0

  // Caso minimal: mes sin actividad y no en curso → colapsado a 1 línea sticky
  if (!month.is_relevant && !month.is_current) {
    return (
      <div className="px-4 py-2.5 rounded-sm border border-line/50 bg-bg-2/20 flex items-center gap-4 text-sm">
        <span className="font-display text-base text-ink-2 min-w-[90px]">{month.period_label}</span>
        <span className="text-ink-3 text-xs flex-1">Sin actividad relevante</span>
      </div>
    )
  }

  return (
    <article className="rounded border border-line bg-bg-1 overflow-hidden">
      {/* HERO */}
      <header className="px-5 py-4">
        <div className="flex items-baseline justify-between gap-4 mb-2">
          <div className="flex items-baseline gap-3 flex-wrap">
            <h3 className="font-display text-xl text-ink-0 tracking-tight">{month.period_label}</h3>
            {month.is_current && (
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-rendi-pos border border-rendi-pos/30 bg-rendi-pos/10 px-1.5 py-0.5 rounded-sm">
                <Calendar size={9} aria-hidden="true" /> En curso
              </span>
            )}
          </div>
          <div className="flex items-baseline gap-2 flex-shrink-0">
            <span className={`text-2xl font-semibold tabular ${positive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {fmtPct(month.metrics.delta_pct)}
            </span>
            <span className="text-xs tabular text-ink-3">
              {fmtUsd(month.metrics.delta_usd)}
            </span>
          </div>
        </div>

        <p className="text-sm text-ink-1 leading-snug">{month.headline}</p>
        {month.subheadline && (
          <p className="text-xs text-ink-2 leading-relaxed mt-0.5">{month.subheadline}</p>
        )}

        {month.is_current && (
          <p className="text-[11px] text-ink-3 mt-2 font-mono">
            Faltan {daysUntilMonthEnd(month.period_end)} días para el cierre
          </p>
        )}
      </header>

      {/* HIGHLIGHTS */}
      {month.highlights && month.highlights.length > 0 && (
        <div className="px-5 pb-3">
          <HighlightsRail highlights={month.highlights} />
        </div>
      )}

      {/* INSIGHTS */}
      {month.insights && month.insights.length > 0 && (
        <div className="px-5 pb-4 space-y-1.5">
          {month.insights.map((ins, i) => (
            <InsightChip key={ins.code + i} insight={ins} />
          ))}
        </div>
      )}

      {/* TOGGLE: SEMANAS */}
      {month.children && month.children.length > 0 && (
        <div className="border-t border-line/50">
          <button
            onClick={() => setWeeksOpen(o => !o)}
            className="w-full px-5 py-2.5 flex items-center justify-between text-xs text-ink-2 hover:text-ink-1 hover:bg-bg-2/30 transition-colors"
            aria-expanded={weeksOpen}
          >
            <span>Ver semanas ({month.children.filter(w => w.is_relevant).length})</span>
            {weeksOpen
              ? <ChevronUp size={12} strokeWidth={1.75} aria-hidden="true" />
              : <ChevronDown size={12} strokeWidth={1.75} aria-hidden="true" />}
          </button>
          {weeksOpen && (
            <div className="px-5 pb-4 space-y-1.5">
              {month.children.map(w => (
                <WeekCard key={w.period_key} week={w} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* TOGGLE: MÉTRICAS TÉCNICAS */}
      <div className="border-t border-line/50">
        <button
          onClick={() => setMetricsOpen(o => !o)}
          className="w-full px-5 py-2.5 flex items-center justify-between text-xs text-ink-2 hover:text-ink-1 hover:bg-bg-2/30 transition-colors"
          aria-expanded={metricsOpen}
        >
          <span className="flex items-center gap-1.5">
            <BarChart2 size={12} strokeWidth={1.75} aria-hidden="true" />
            Métricas técnicas
          </span>
          {metricsOpen
            ? <ChevronUp size={12} strokeWidth={1.75} aria-hidden="true" />
            : <ChevronDown size={12} strokeWidth={1.75} aria-hidden="true" />}
        </button>
        {metricsOpen && <MetricsGrid metrics={month.metrics} />}
      </div>
    </article>
  )
}

// ─── Grid de métricas técnicas ───────────────────────────────────────────────

function MetricsGrid({ metrics: m }) {
  return (
    <div className="px-5 pb-4 grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
      <Cell label="Valor inicio" value={m.start_value != null ? fmtUsdRaw(m.start_value) : '—'} />
      <Cell label="Valor cierre" value={m.end_value != null ? fmtUsdRaw(m.end_value) : '—'} />
      <Cell label="Depósitos" value={m.deposits ? fmtUsdRaw(m.deposits) : 'US$0'} />
      <Cell label="Retiros"   value={m.withdrawals ? fmtUsdRaw(m.withdrawals) : 'US$0'} />
      <Cell label="Realizado" value={fmtUsdSigned(m.realized_pnl)} accent />
      <Cell label="No realizado" value={fmtUsdSigned(m.unrealized_pnl)} accent />
      <Cell label="Trades" value={m.trades_count} />
      <Cell label="Win rate" value={m.win_rate != null ? `${m.win_rate.toFixed(0)}%` : '—'} />
      {m.vs_sp500_pct != null && (
        <Cell label="vs S&P 500" value={`${m.vs_sp500_pct >= 0 ? '+' : ''}${m.vs_sp500_pct.toFixed(1)}%`} accent />
      )}
      {m.vs_inflation_pct != null && (
        <Cell label="vs Inflación AR" value={`${m.vs_inflation_pct >= 0 ? '+' : ''}${m.vs_inflation_pct.toFixed(1)}%`} accent />
      )}
      {m.delta_pct_over_contrib != null && (
        <Cell label="Sobre aportado" value={`${m.delta_pct_over_contrib >= 0 ? '+' : ''}${m.delta_pct_over_contrib.toFixed(1)}%`} accent />
      )}
    </div>
  )
}

function Cell({ label, value, accent = false }) {
  return (
    <div className="rounded-sm bg-bg-2/40 px-2 py-1.5">
      <div className="text-ink-3 uppercase tracking-wider text-[9px]">{label}</div>
      <div className={`font-mono tabular ${accent ? 'text-ink-0' : 'text-ink-1'}`}>{value}</div>
    </div>
  )
}

function fmtUsdRaw(v) {
  return `US$${Math.abs(v).toLocaleString('es-AR', { maximumFractionDigits: 0 })}`
}

function fmtUsdSigned(v) {
  if (v == null) return '—'
  const sign = v >= 0 ? '+' : '−'
  return `${sign}US$${Math.abs(v).toLocaleString('es-AR', { maximumFractionDigits: 0 })}`
}
