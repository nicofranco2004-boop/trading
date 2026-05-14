// PerformanceCalendar — overview visual arriba de la timeline (V2).
// ═══════════════════════════════════════════════════════════════════════════
// Dos piezas:
//   1) KPI strip 12M (acumulado realizado, meses positivos, mejor/peor mes,
//      trades).
//   2) Calendario de performance: heatmap por año con 12 cuadraditos (ENE-DIC),
//      colores 9-pasos basados en delta_pct mensual, suma anual a la derecha.
//
// Mantiene la narrativa de MonthCard intacta — se usa como vista resumen
// arriba, antes de la timeline.

import Eyebrow from '../Eyebrow'

const MONTH_SHORT = ['ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN', 'JUL', 'AGO', 'SEP', 'OCT', 'NOV', 'DIC']

// Extrae month_number (1-12) desde period_key "YYYY-MM"
function monthNum(period_key) {
  if (!period_key) return null
  const m = period_key.match(/-(\d{1,2})/)
  return m ? parseInt(m[1], 10) : null
}

// ─── Color bins ──────────────────────────────────────────────────────────────
// Escala 9-pasos cold + signal. Para Tailwind usamos style inline (los hex
// no calzan en arbitrary values sin perder claridad).
function colorForCell(pct, hasData) {
  if (!hasData) {
    return { bg: 'transparent', border: '1px solid rgba(255,255,255,0.04)', label: 'text-ink-3', value: 'text-ink-3' }
  }
  if (pct == null || pct === 0) {
    return { bg: '#1B2230', border: 'none', label: 'text-ink-2', value: 'text-ink-1' }
  }
  if (pct > 0) {
    if (pct >= 10)  return { bg: '#21D07A', border: 'none', label: 'text-[#06160E]', value: 'text-[#06160E]' }
    if (pct >= 5)   return { bg: '#14A560', border: 'none', label: 'text-ink-0',     value: 'text-ink-0' }
    if (pct >= 2)   return { bg: '#0F5C36', border: 'none', label: 'text-ink-0',     value: 'text-ink-0' }
    if (pct >= 0.5) return { bg: '#0B4127', border: 'none', label: 'text-ink-1',     value: 'text-rendi-pos' }
    return { bg: '#06160E', border: 'none', label: 'text-ink-2', value: 'text-rendi-pos' }
  }
  const abs = Math.abs(pct)
  if (abs >= 10)  return { bg: '#FF5360', border: 'none', label: 'text-[#1F0A0C]', value: 'text-[#1F0A0C]' }
  if (abs >= 5)   return { bg: '#C8333E', border: 'none', label: 'text-ink-0',     value: 'text-ink-0' }
  if (abs >= 2)   return { bg: '#8E2B33', border: 'none', label: 'text-ink-0',     value: 'text-ink-0' }
  if (abs >= 0.5) return { bg: '#5E1F25', border: 'none', label: 'text-ink-1',     value: 'text-rendi-neg' }
  return { bg: '#1F0A0C', border: 'none', label: 'text-ink-2', value: 'text-rendi-neg' }
}

function fmtPctShort(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(p >= 10 || p <= -10 ? 1 : 2)}`
}

function fmtUsdSigned(v) {
  if (v == null) return '—'
  const sign = v >= 0 ? '+' : '−'
  return `${sign}US$${Math.abs(v).toLocaleString('es-AR', { maximumFractionDigits: 0 })}`
}

// ─── KPI strip (12 meses más recientes) ──────────────────────────────────────
function computeKpis(yearGroups) {
  const allMonths = yearGroups
    .flatMap(g => g.months)
    .filter(m => m.is_relevant && m.metrics)
  // Tomar los 12 más recientes ordenados desc por period_key
  const sorted = [...allMonths].sort((a, b) => (a.period_key < b.period_key ? 1 : -1))
  const last12 = sorted.slice(0, 12)
  if (last12.length === 0) return null

  const realizedSum = last12.reduce((s, m) => s + (m.metrics.realized_pnl || 0), 0)
  const trades = last12.reduce((s, m) => s + (m.metrics.trades_count || 0), 0)
  const positiveCount = last12.filter(m => (m.metrics.delta_pct || 0) > 0).length
  const totalCount = last12.length

  let best = null, worst = null
  for (const m of last12) {
    if (m.metrics.delta_pct == null) continue
    if (!best  || m.metrics.delta_pct > best.metrics.delta_pct)  best  = m
    if (!worst || m.metrics.delta_pct < worst.metrics.delta_pct) worst = m
  }
  return { realizedSum, trades, positiveCount, totalCount, best, worst }
}

function KpiCell({ label, value, sub, tone, hero }) {
  const valueColor =
    tone === 'pos' ? 'text-rendi-pos' :
    tone === 'neg' ? 'text-rendi-neg' :
    'text-ink-0'
  return (
    <div className="px-3 py-2.5 border-r border-line/40 last:border-r-0 flex-1 min-w-[120px]">
      <div className="text-[9px] font-mono uppercase tracking-label text-ink-3 leading-none">{label}</div>
      <div className={`mt-1.5 font-medium tabular num leading-none ${hero ? 'text-2xl tracking-tight' : 'text-lg'} ${valueColor}`}>
        {value}
      </div>
      {sub && (
        <div className="text-[10px] font-mono text-ink-3 mt-1 leading-none truncate">{sub}</div>
      )}
    </div>
  )
}

export default function PerformanceCalendar({ yearGroups }) {
  const kpis = computeKpis(yearGroups)
  if (!kpis) return null

  return (
    <section className="mb-6">
      {/* ── KPI strip ── */}
      <div className="border border-line rounded bg-bg-1 flex flex-wrap mb-4">
        <KpiCell
          label="P&L Realizado · 12M"
          value={fmtUsdSigned(kpis.realizedSum)}
          tone={kpis.realizedSum >= 0 ? 'pos' : 'neg'}
          sub={`${kpis.totalCount} ${kpis.totalCount === 1 ? 'mes' : 'meses'} con actividad`}
          hero
        />
        <KpiCell
          label="Meses positivos"
          value={`${kpis.positiveCount}/${kpis.totalCount}`}
          sub={kpis.totalCount > 0 ? `${Math.round((kpis.positiveCount / kpis.totalCount) * 100)}% win rate` : '—'}
        />
        <KpiCell
          label="Mejor mes"
          value={kpis.best ? `${fmtPctShort(kpis.best.metrics.delta_pct)}%` : '—'}
          tone="pos"
          sub={kpis.best ? kpis.best.period_label : undefined}
        />
        <KpiCell
          label="Peor mes"
          value={kpis.worst ? `${fmtPctShort(kpis.worst.metrics.delta_pct)}%` : '—'}
          tone={kpis.worst && kpis.worst.metrics.delta_pct < 0 ? 'neg' : undefined}
          sub={kpis.worst ? kpis.worst.period_label : undefined}
        />
        <KpiCell
          label="Trades · 12M"
          value={kpis.trades.toLocaleString('es-AR')}
          sub="operaciones cerradas"
        />
      </div>

      {/* ── Calendar heatmap ── */}
      <div className="border border-line rounded bg-bg-1 overflow-hidden">
        <header className="flex items-center justify-between px-3 py-2 border-b border-line/60">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-rendi-pos" aria-hidden="true" />
            <Eyebrow>Calendario de performance</Eyebrow>
            <span className="text-[10px] font-mono text-ink-3 ml-1">/ TWR mensual</span>
          </div>
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
            {yearGroups.length} {yearGroups.length === 1 ? 'año' : 'años'} cargados
          </span>
        </header>

        <div className="px-3 py-3 space-y-3">
          {yearGroups.map(({ year, months }) => {
            const cells = Array.from({ length: 12 }, (_, idx) => {
              const m = months.find(mm => monthNum(mm.period_key) === idx + 1)
              return { idx, month: m }
            })
            const yearDeltaSum = months.reduce((s, m) => s + (m.metrics?.delta_pct || 0), 0)
            return (
              <div key={year} className="flex items-center gap-3">
                <div className="font-mono text-[11px] tracking-label text-ink-3 min-w-[44px]">{year}</div>
                <div className="grid grid-cols-12 gap-1 flex-1">
                  {cells.map(({ idx, month }) => {
                    const pct = month?.metrics?.delta_pct
                    const hasData = !!month && month.is_relevant && pct != null
                    const c = colorForCell(pct, hasData)
                    const isCurrent = month?.is_current
                    return (
                      <div
                        key={idx}
                        title={month ? `${month.period_label}: ${fmtPctShort(pct)}%` : `${MONTH_SHORT[idx]}: sin datos`}
                        className="aspect-[1.3/1] p-1.5 flex flex-col justify-between rounded-[2px]"
                        style={{
                          background: c.bg,
                          border: c.border,
                          outline: isCurrent ? '1.5px solid rgb(33,208,122)' : undefined,
                          outlineOffset: isCurrent ? '-2px' : undefined,
                        }}
                      >
                        <span className={`font-mono text-[9px] tracking-label leading-none ${c.label}`}>
                          {MONTH_SHORT[idx]}
                        </span>
                        <span className={`font-mono text-[11px] font-semibold leading-none tabular ${c.value}`}>
                          {hasData ? fmtPctShort(pct) : '—'}
                        </span>
                      </div>
                    )
                  })}
                </div>
                <div className={`font-mono text-[11px] min-w-[70px] text-right tabular ${
                  yearDeltaSum >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'
                }`}>
                  {yearDeltaSum >= 0 ? '+' : ''}{yearDeltaSum.toFixed(2)}%
                </div>
              </div>
            )
          })}

          {/* Legend */}
          <div className="flex items-center gap-1.5 pt-2 border-t border-line/40 text-[10px] font-mono text-ink-3">
            <span className="mr-1">−5%</span>
            {['#1F0A0C', '#5E1F25', '#8E2B33', '#C8333E', '#FF5360'].map((c, i) => (
              <span key={i} className="inline-block w-4 h-2" style={{ background: c }} />
            ))}
            <span className="inline-block w-4 h-2 mx-0.5" style={{ background: '#1B2230' }} />
            {['#21D07A', '#14A560', '#0F5C36', '#0B4127', '#06160E'].map((c, i) => (
              <span key={i} className="inline-block w-4 h-2" style={{ background: c }} />
            ))}
            <span className="ml-1">+5%</span>
            <span className="ml-auto uppercase tracking-caps">Rendimiento mensual · TWR</span>
          </div>
        </div>
      </div>
    </section>
  )
}
