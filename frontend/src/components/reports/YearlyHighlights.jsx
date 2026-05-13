// YearlyHighlights — banda destacada arriba de cada año (años cerrados o en
// curso con ≥3 meses). Muestra los momentos memorables del año:
//   • Mejor mes (mayor delta_pct)
//   • Peor mes
//   • Mes con más operaciones
//   • Mejor operación individual (más alta)
//
// Diseño: rail horizontal compacto con cards minimalistas. Es la pieza que
// le da a la timeline sentido de "memoria financiera" — el year-in-review
// chico sin necesidad de scrollear todo.
//
// Para el año en curso solo se renderiza si hay ≥3 meses con datos.

const FALLBACK_MEDAL = '◯'

function computeHighlights(months) {
  if (!months || months.length === 0) return []

  // Mejor / peor mes por delta_pct (solo meses relevantes con delta != 0)
  const relevant = months.filter(m => m.is_relevant && m.metrics.delta_pct != null)
  let bestMonth = null, worstMonth = null
  for (const m of relevant) {
    if (!bestMonth || m.metrics.delta_pct > bestMonth.metrics.delta_pct) bestMonth = m
    if (!worstMonth || m.metrics.delta_pct < worstMonth.metrics.delta_pct) worstMonth = m
  }
  if (bestMonth && bestMonth === worstMonth) worstMonth = null  // un solo dato → no compararse

  // Mes con más trades
  const busiest = relevant
    .filter(m => m.metrics.trades_count > 0)
    .reduce((a, b) => (!a || b.metrics.trades_count > a.metrics.trades_count) ? b : a, null)

  // Mejor operación del año: buscar en los highlights best_op de cada mes,
  // quedarse con el que tenga mayor pnl (parseando el value_label "+US$X")
  let bestOpHighlight = null
  let bestOpAmount = -Infinity
  for (const m of months) {
    for (const h of m.highlights || []) {
      if (h.kind === 'best_op') {
        // value_label viene como "BTC +US$1,234"
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
      icon: '🏆',
      label: 'Mejor mes',
      value: `${bestMonth.period_label.split(' ')[0]} ${bestMonth.metrics.delta_pct >= 0 ? '+' : ''}${bestMonth.metrics.delta_pct.toFixed(1)}%`,
      tone: 'positive',
    })
  }
  if (worstMonth && worstMonth.metrics.delta_pct < 0) {
    out.push({
      kind: 'worst_month',
      icon: '📉',
      label: 'Peor mes',
      value: `${worstMonth.period_label.split(' ')[0]} ${worstMonth.metrics.delta_pct.toFixed(1)}%`,
      tone: 'negative',
    })
  }
  if (busiest && busiest.metrics.trades_count >= 3) {
    out.push({
      kind: 'busiest_month',
      icon: '⚡',
      label: 'Mes con más actividad',
      value: `${busiest.period_label.split(' ')[0]} · ${busiest.metrics.trades_count} trades`,
      tone: 'neutral',
    })
  }
  if (bestOpHighlight) {
    out.push({
      kind: 'best_op_year',
      icon: '🚀',
      label: 'Mejor operación',
      value: bestOpHighlight.value_label,
      tone: 'positive',
      context: bestOpHighlight.month_label,
    })
  }
  return out
}

const TONE_STYLE = {
  positive: 'border-rendi-pos/30 bg-rendi-pos/[0.06]',
  negative: 'border-rendi-neg/30 bg-rendi-neg/[0.06]',
  neutral:  'border-line bg-bg-2/40',
}

export default function YearlyHighlights({ months }) {
  const items = computeHighlights(months)
  if (items.length === 0) return null

  return (
    <div className="flex gap-2 overflow-x-auto -mx-1 px-1 pb-2 mb-2">
      {items.map((h, i) => (
        <div
          key={`${h.kind}-${i}`}
          className={`flex-shrink-0 flex items-center gap-2.5 px-3 py-2 rounded-sm border ${TONE_STYLE[h.tone] || TONE_STYLE.neutral} min-w-[170px]`}
        >
          <span className="text-lg leading-none" aria-hidden="true">{h.icon || FALLBACK_MEDAL}</span>
          <div className="flex flex-col min-w-0">
            <span className="text-[10px] uppercase tracking-wider text-ink-3 leading-tight">
              {h.label}
            </span>
            <span className="text-xs font-mono text-ink-1 truncate" title={h.value}>
              {h.value}
            </span>
            {h.context && (
              <span className="text-[10px] text-ink-3 leading-tight">{h.context}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
