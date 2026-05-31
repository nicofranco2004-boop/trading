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
import { ChevronDown, ChevronUp, BarChart2 } from 'lucide-react'
import InsightChip from './InsightChip'
import HighlightsRail from './HighlightsRail'
import WeekCard from './WeekCard'
import Pill from '../Pill'
import AskAIAbout from '../ai/AskAIAbout'
import { useMoneyFormat } from '../../contexts/CurrencyContext'

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : '−'
  return `${sign}${Math.abs(p).toFixed(2)}%`
}

function daysUntilPeriodEnd(period_end_iso) {
  // UTC para consistencia con el backend (que usa _iso_today / utcnow).
  // Sin esto, usuarios cerca de medianoche local pueden ver "1 día" cuando
  // el backend ya considera el día actual como pasado.
  const todayMs = Date.UTC(
    new Date().getUTCFullYear(),
    new Date().getUTCMonth(),
    new Date().getUTCDate(),
  )
  const [y, m, d] = period_end_iso.split('-').map(Number)
  const endMs = Date.UTC(y, m - 1, d)
  const diff = Math.ceil((endMs - todayMs) / 86400000)
  return Math.max(0, diff)
}

// Acepta `period` (recibe day/week/month/year). `month` se mantiene como
// alias por back-compat con callers existentes.
export default function MonthCard({ period, month, defaultExpanded = false }) {
  const p = period || month
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [weeksOpen, setWeeksOpen] = useState(false)
  const [metricsOpen, setMetricsOpen] = useState(false)
  const deltaPct = p.metrics?.delta_pct
  const positive = (deltaPct ?? 0) >= 0
  // Fase B: el delta_usd / valores monetarios respetan el toggle global
  // ARS/USD. El backend siempre devuelve USD; la conversión a ARS usa
  // tcBlue ACTUAL (limitación MVP — Fase C trackeará TC histórico).
  const money = useMoneyFormat()

  // Caso minimal: período sin actividad y no en curso → colapsado a 1 línea sticky
  if (!p.is_relevant && !p.is_current) {
    return (
      <div className="px-4 py-2.5 rounded-sm border border-line/50 bg-bg-2/20 flex items-center gap-4 text-sm">
        <span className="font-display text-base text-ink-2 min-w-[90px]">{p.period_label}</span>
        <span className="text-ink-3 text-xs flex-1">Sin actividad relevante</span>
      </div>
    )
  }

  // Extracción year/month del period_key para los topics de IA.
  // Soporta keys de tipo "YYYY-MM" (month) o "YYYY" (year). Para week/day,
  // period_key tiene otra forma — el ai_topic no aplica.
  const periodKey = p.period_key || ''
  const aiParams = (() => {
    if (p.period_type === 'month' || /^\d{4}-\d{2}$/.test(periodKey)) {
      const [yyyy, mm] = periodKey.split('-')
      return { year: parseInt(yyyy, 10) || null, month: parseInt(mm, 10) || null }
    }
    if (p.period_type === 'year' || /^\d{4}$/.test(periodKey)) {
      return { year: parseInt(periodKey, 10) || null, month: null }
    }
    return {}
  })()

  return (
    <AskAIAbout
      topic="monthly"
      params={aiParams}
      subtitle={p.period_label}
    >
    <article className="rounded border border-line bg-bg-1 overflow-hidden">
      {/* HERO */}
      <header className="px-5 py-4">
        <div className="flex items-baseline justify-between gap-4 mb-2">
          <div className="flex items-baseline gap-3 flex-wrap">
            <h3 className="font-display text-xl text-ink-0 tracking-tight">{p.period_label}</h3>
            {p.is_current && <Pill tone="signal" dot>En curso</Pill>}
          </div>
          <div className="flex items-baseline gap-2 flex-shrink-0">
            <span className={`text-2xl font-semibold tabular ${positive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {fmtPct(deltaPct)}
            </span>
            <span className="text-xs tabular text-ink-3">
              {money.fmtMoney(p.metrics?.delta_usd, { signed: true })}
            </span>
          </div>
        </div>

        <p className="text-sm text-ink-1 leading-snug">{p.headline}</p>
        {p.subheadline && (
          <p className="text-xs text-ink-2 leading-relaxed mt-0.5">{p.subheadline}</p>
        )}
        {p.narrative && (
          <p className="text-xs text-ink-2 leading-relaxed mt-3 max-w-3xl">{p.narrative}</p>
        )}

        {p.is_current && p.period_end && (
          <p className="text-[11px] text-ink-3 mt-2 font-mono">
            Faltan {daysUntilPeriodEnd(p.period_end)} días para el cierre
          </p>
        )}
      </header>

      {/* HIGHLIGHTS */}
      {p.highlights && p.highlights.length > 0 && (
        <div className="px-5 pb-3">
          <HighlightsRail highlights={p.highlights} />
        </div>
      )}

      {/* INSIGHTS — cada chip wrappeada con AskAIAbout (monthly.insight) */}
      {p.insights && p.insights.length > 0 && (
        <div className="px-5 pb-4 space-y-1.5">
          {p.insights.map((ins, i) => (
            <AskAIAbout
              key={ins.code + i}
              topic="monthly.insight"
              params={{
                ...aiParams,
                code: ins.code,
                text: ins.text,
                severity: ins.severity,
              }}
              subtitle={`Insight · ${p.period_label}`}
            >
              <InsightChip insight={ins} />
            </AskAIAbout>
          ))}
        </div>
      )}

      {/* TOGGLE: SEMANAS — solo aplica cuando es mes con children */}
      {p.period_type === 'month' && p.children && p.children.length > 0 && (
        <div className="border-t border-line/50">
          <button
            onClick={() => setWeeksOpen(o => !o)}
            className="w-full px-5 py-2.5 flex items-center justify-between text-xs text-ink-2 hover:text-ink-1 hover:bg-bg-2/30 transition-colors"
            aria-expanded={weeksOpen}
          >
            <span>Ver semanas ({p.children.filter(w => w.is_relevant).length})</span>
            {weeksOpen
              ? <ChevronUp size={12} strokeWidth={1.75} aria-hidden="true" />
              : <ChevronDown size={12} strokeWidth={1.75} aria-hidden="true" />}
          </button>
          {weeksOpen && (
            <div className="px-5 pb-4 space-y-1.5">
              {p.children.map(w => (
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
        {metricsOpen && <MetricsGrid metrics={p.metrics} money={money} />}
      </div>
    </article>
    </AskAIAbout>
  )
}

// ─── Grid de métricas técnicas ───────────────────────────────────────────────

function MetricsGrid({ metrics: m, money }) {
  // Fallback al formatter inyectado o, si no llega (defensa), USD plano.
  const fmt = money?.fmtMoney || ((v) => v == null ? '—' : `US$${Math.abs(v).toLocaleString('es-AR', { maximumFractionDigits: 0 })}`)
  return (
    <div className="px-5 pb-4 grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
      <Cell label="Valor inicio" value={m.start_value != null ? fmt(m.start_value) : '—'} />
      <Cell label="Valor cierre" value={m.end_value != null ? fmt(m.end_value) : '—'} />
      <Cell label="Depósitos" value={m.deposits ? fmt(m.deposits) : fmt(0)} />
      <Cell label="Retiros"   value={m.withdrawals ? fmt(m.withdrawals) : fmt(0)} />
      <Cell label="Realizado" value={fmt(m.realized_pnl, { signed: true })} accent />
      <Cell label="No realizado" value={fmt(m.unrealized_pnl, { signed: true })} accent />
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
