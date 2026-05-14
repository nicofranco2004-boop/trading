// YearlyHighlights — banda destacada arriba de cada año.
// Diseño: rail horizontal compacto con cards minimalistas. Iconos lucide,
// sin emojis. Tono por tipo (positivo / negativo / actividad / hit).

import { Trophy, TrendingDown, Activity, Rocket, Award } from 'lucide-react'

function computeHighlights(months) {
  if (!months || months.length === 0) return []

  const relevant = months.filter(m => m.is_relevant && m.metrics.delta_pct != null)
  let bestMonth = null, worstMonth = null
  for (const m of relevant) {
    if (!bestMonth || m.metrics.delta_pct > bestMonth.metrics.delta_pct) bestMonth = m
    if (!worstMonth || m.metrics.delta_pct < worstMonth.metrics.delta_pct) worstMonth = m
  }
  if (bestMonth && bestMonth === worstMonth) worstMonth = null

  const busiest = relevant
    .filter(m => m.metrics.trades_count > 0)
    .reduce((a, b) => (!a || b.metrics.trades_count > a.metrics.trades_count) ? b : a, null)

  let bestOpHighlight = null
  let bestOpAmount = -Infinity
  for (const m of months) {
    for (const h of m.highlights || []) {
      if (h.kind === 'best_op') {
        const match = (h.value_label || '').match(/US\$([\d,]+)/)
        if (!match) continue
        const amt = parseInt(match[1].replace(/,/g, ''), 10) || 0
        if (amt > bestOpAmount) {
          bestOpAmount = amt
          bestOpHighlight = { ...h, month_label: m.period_label }
        }
      }
    }
  }

  const out = []
  if (bestMonth) {
    out.push({
      kind: 'best_month',
      Icon: Trophy,
      label: 'Mejor mes',
      value: `${bestMonth.period_label.split(' ')[0]} ${bestMonth.metrics.delta_pct >= 0 ? '+' : ''}${bestMonth.metrics.delta_pct.toFixed(1)}%`,
      tone: 'positive',
    })
  }
  if (worstMonth && worstMonth.metrics.delta_pct < 0) {
    out.push({
      kind: 'worst_month',
      Icon: TrendingDown,
      label: 'Peor mes',
      value: `${worstMonth.period_label.split(' ')[0]} ${worstMonth.metrics.delta_pct.toFixed(1)}%`,
      tone: 'negative',
    })
  }
  if (busiest && busiest.metrics.trades_count >= 3) {
    out.push({
      kind: 'busiest_month',
      Icon: Activity,
      label: 'Mes con más actividad',
      value: `${busiest.period_label.split(' ')[0]} · ${busiest.metrics.trades_count} trades`,
      tone: 'neutral',
    })
  }
  if (bestOpHighlight) {
    out.push({
      kind: 'best_op_year',
      Icon: Rocket,
      label: 'Mejor operación',
      value: bestOpHighlight.value_label,
      tone: 'positive',
      context: bestOpHighlight.month_label,
    })
  }
  return out
}

const TONE_STYLE = {
  positive: {
    container: 'border-rendi-pos/30 bg-rendi-pos/[0.06]',
    icon:      'text-rendi-pos',
  },
  negative: {
    container: 'border-rendi-neg/30 bg-rendi-neg/[0.06]',
    icon:      'text-rendi-neg',
  },
  neutral: {
    container: 'border-line bg-bg-2/40',
    icon:      'text-data-cyan',
  },
}

export default function YearlyHighlights({ months }) {
  const items = computeHighlights(months)
  if (items.length === 0) return null

  return (
    <div className="flex gap-2 overflow-x-auto -mx-1 px-1 pb-2 mb-2">
      {items.map((h, i) => {
        const style = TONE_STYLE[h.tone] || TONE_STYLE.neutral
        const Icon = h.Icon || Award
        return (
          <div
            key={`${h.kind}-${i}`}
            className={`flex-shrink-0 flex items-center gap-2.5 px-3 py-2 rounded-sm border ${style.container} min-w-[170px]`}
          >
            <span className="inline-flex items-center justify-center w-7 h-7 rounded-sm bg-bg-1/60 flex-shrink-0" aria-hidden="true">
              <Icon size={14} strokeWidth={1.75} className={style.icon} />
            </span>
            <div className="flex flex-col min-w-0">
              <span className="text-[10px] uppercase tracking-label text-ink-3 leading-tight font-mono">
                {h.label}
              </span>
              <span className="text-xs font-mono text-ink-1 truncate" title={h.value}>
                {h.value}
              </span>
              {h.context && (
                <span className="text-[10px] text-ink-3 leading-tight font-mono">{h.context}</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
