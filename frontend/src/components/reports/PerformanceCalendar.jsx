// PerformanceCalendar — overview visual fuerte de Reportes (V2).
// ═══════════════════════════════════════════════════════════════════════════
// Dos piezas:
//   1) KPI strip 12M (acumulado realizado, meses positivos, mejor/peor, trades)
//   2) Calendario heatmap por año — bandas con 12 cuadrados (ENE-DIC)
//      coloreados según delta_pct mensual. Escala 7 pasos + neutro + sin datos.
//
// Visual: tipografía mono operativa, celdas con altura generosa, colores
// con buen contraste sobre bg-bg-1.

const MONTH_SHORT = ['ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN', 'JUL', 'AGO', 'SEP', 'OCT', 'NOV', 'DIC']

function monthNum(period_key) {
  if (!period_key) return null
  const m = period_key.match(/-(\d{1,2})/)
  return m ? parseInt(m[1], 10) : null
}

// ─── Color bins (7 niveles + neutro + sin datos) ─────────────────────────────
// Colores con buen contraste sobre bg-bg-1. Texto adapta al fondo.
function colorForCell(pct, hasData) {
  if (!hasData) {
    return {
      bg: 'transparent',
      border: '1px dashed rgba(255,255,255,0.06)',
      label: '#5A6478',
      value: '#5A6478',
    }
  }
  if (pct == null || Math.abs(pct) < 0.5) {
    return { bg: '#1B2230', border: 'none', label: '#9CA3B5', value: '#C3CAD8' }
  }
  if (pct >= 5)    return { bg: '#21D07A', border: 'none', label: '#06160E', value: '#06160E' }
  if (pct >= 2)    return { bg: '#14A560', border: 'none', label: '#E6EAF2', value: '#E6EAF2' }
  if (pct > 0)     return { bg: '#0F5C36', border: 'none', label: '#C3CAD8', value: '#5FE19D' }
  if (pct <= -5)   return { bg: '#FF5360', border: 'none', label: '#1F0A0C', value: '#1F0A0C' }
  if (pct <= -2)   return { bg: '#C8333E', border: 'none', label: '#E6EAF2', value: '#E6EAF2' }
  return            { bg: '#8E2B33', border: 'none', label: '#C3CAD8', value: '#FFB1B7' }
}

function fmtPctValue(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  // Compacto: enteros para >=10, 1 decimal para <10
  const abs = Math.abs(p)
  return `${sign}${abs >= 10 ? p.toFixed(0) : p.toFixed(2)}`
}

function fmtUsdSigned(v) {
  if (v == null) return '—'
  const sign = v >= 0 ? '+' : '−'
  return `${sign}US$${Math.abs(v).toLocaleString('es-AR', { maximumFractionDigits: 0 })}`
}

// ─── KPI strip data ──────────────────────────────────────────────────────────
function computeKpis(yearGroups) {
  const allMonths = yearGroups
    .flatMap(g => g.months)
    .filter(m => m.is_relevant && m.metrics)
  const sorted = [...allMonths].sort((a, b) => (a.period_key < b.period_key ? 1 : -1))
  const last12 = sorted.slice(0, 12)
  if (last12.length === 0) return null

  const realizedSum = last12.reduce((s, m) => s + (m.metrics.realized_pnl || 0), 0)
  const trades = last12.reduce((s, m) => s + (m.metrics.trades_count || 0), 0)
  const positiveCount = last12.filter(m => (m.metrics.delta_pct || 0) > 0).length

  let best = null, worst = null
  for (const m of last12) {
    if (m.metrics.delta_pct == null) continue
    if (!best  || m.metrics.delta_pct > best.metrics.delta_pct)  best  = m
    if (!worst || m.metrics.delta_pct < worst.metrics.delta_pct) worst = m
  }
  return { realizedSum, trades, positiveCount, totalCount: last12.length, best, worst }
}

function KpiCell({ label, value, sub, tone, first }) {
  const valueColor =
    tone === 'pos' ? 'text-rendi-pos' :
    tone === 'neg' ? 'text-rendi-neg' :
    'text-ink-0'
  return (
    <div className={`px-4 py-3 flex-1 min-w-[140px] ${first ? '' : 'border-l border-line/50'}`}>
      <div className="text-[10px] font-mono uppercase tracking-label text-ink-3 leading-none">
        {label}
      </div>
      <div className={`mt-2 font-medium tabular num leading-none text-2xl tracking-tight ${valueColor}`}>
        {value}
      </div>
      <div className="text-[10px] font-mono text-ink-3 mt-1.5 leading-none truncate uppercase tracking-caps">
        {sub}
      </div>
    </div>
  )
}

export default function PerformanceCalendar({ yearGroups }) {
  const kpis = computeKpis(yearGroups)
  if (!kpis) return null

  return (
    <section className="mb-6 space-y-3">
      {/* ── KPI strip ── */}
      <div className="border border-line rounded bg-bg-1 flex flex-wrap">
        <KpiCell
          first
          label="P&L Realizado · 12M"
          value={fmtUsdSigned(kpis.realizedSum)}
          tone={kpis.realizedSum >= 0 ? 'pos' : 'neg'}
          sub={`${kpis.totalCount} ${kpis.totalCount === 1 ? 'mes activo' : 'meses activos'}`}
        />
        <KpiCell
          label="Win rate mensual"
          value={`${kpis.positiveCount}/${kpis.totalCount}`}
          sub={
            kpis.totalCount > 0
              ? `${Math.round((kpis.positiveCount / kpis.totalCount) * 100)}% positivos`
              : '—'
          }
        />
        <KpiCell
          label="Mejor mes"
          value={kpis.best ? `${fmtPctValue(kpis.best.metrics.delta_pct)}%` : '—'}
          tone="pos"
          sub={kpis.best ? kpis.best.period_label : ''}
        />
        <KpiCell
          label="Peor mes"
          value={kpis.worst ? `${fmtPctValue(kpis.worst.metrics.delta_pct)}%` : '—'}
          tone={kpis.worst && kpis.worst.metrics.delta_pct < 0 ? 'neg' : undefined}
          sub={kpis.worst ? kpis.worst.period_label : ''}
        />
        <KpiCell
          label="Trades · 12M"
          value={kpis.trades.toLocaleString('es-AR')}
          sub="operaciones cerradas"
        />
      </div>

      {/* ── Calendar heatmap ── */}
      <div className="border border-line rounded bg-bg-1 overflow-hidden">
        <header className="flex items-center justify-between px-4 py-2.5 border-b border-line">
          <div className="flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-rendi-pos" aria-hidden="true" />
            <span className="text-[11px] font-mono uppercase tracking-label text-ink-0">
              Calendario de performance
            </span>
            <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3 ml-1">
              / TWR mensual
            </span>
          </div>
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
            {yearGroups.length} {yearGroups.length === 1 ? 'año' : 'años'} cargados
          </span>
        </header>

        <div className="px-4 py-5 space-y-5">
          {yearGroups.map(({ year, months }) => {
            const cells = Array.from({ length: 12 }, (_, idx) => {
              const m = months.find(mm => monthNum(mm.period_key) === idx + 1)
              return { idx, month: m }
            })
            const yearDeltaSum = months.reduce((s, m) => s + (m.metrics?.delta_pct || 0), 0)
            return (
              <div key={year} className="flex items-center gap-4">
                <div className="font-mono text-[12px] tracking-label text-ink-3 min-w-[52px] tabular">
                  {year}
                </div>
                <div className="grid grid-cols-12 gap-1.5 flex-1">
                  {cells.map(({ idx, month }) => {
                    const pct = month?.metrics?.delta_pct
                    const hasData = !!month && month.is_relevant && pct != null
                    const c = colorForCell(pct, hasData)
                    const isCurrent = month?.is_current
                    return (
                      <div
                        key={idx}
                        title={month ? `${month.period_label}: ${fmtPctValue(pct)}%` : `${MONTH_SHORT[idx]}: sin datos`}
                        className="aspect-[1.4/1] min-h-[56px] p-2 flex flex-col justify-between"
                        style={{
                          background: c.bg,
                          border: c.border,
                          outline: isCurrent ? '1.5px solid #21D07A' : undefined,
                          outlineOffset: isCurrent ? '-2px' : undefined,
                          borderRadius: '3px',
                        }}
                      >
                        <span
                          className="font-mono text-[10px] tracking-label leading-none"
                          style={{ color: c.label }}
                        >
                          {MONTH_SHORT[idx]}
                        </span>
                        <span
                          className="font-mono text-[13px] font-semibold leading-none tabular"
                          style={{ color: c.value }}
                        >
                          {hasData ? fmtPctValue(pct) : '—'}
                        </span>
                      </div>
                    )
                  })}
                </div>
                <div
                  className={`font-mono text-[12px] min-w-[80px] text-right tabular font-medium ${
                    yearDeltaSum >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'
                  }`}
                >
                  {yearDeltaSum >= 0 ? '+' : ''}{yearDeltaSum.toFixed(2)}%
                </div>
              </div>
            )
          })}

          {/* Legend */}
          <div className="flex items-center gap-1 pt-3 border-t border-line/50 text-[10px] font-mono text-ink-3">
            <span className="mr-2 uppercase tracking-caps">−5%</span>
            <span className="inline-block w-5 h-2.5" style={{ background: '#FF5360' }} />
            <span className="inline-block w-5 h-2.5" style={{ background: '#C8333E' }} />
            <span className="inline-block w-5 h-2.5" style={{ background: '#8E2B33' }} />
            <span className="inline-block w-5 h-2.5 mx-1" style={{ background: '#1B2230' }} />
            <span className="inline-block w-5 h-2.5" style={{ background: '#0F5C36' }} />
            <span className="inline-block w-5 h-2.5" style={{ background: '#14A560' }} />
            <span className="inline-block w-5 h-2.5" style={{ background: '#21D07A' }} />
            <span className="ml-2 uppercase tracking-caps">+5%</span>
            <span className="ml-auto uppercase tracking-caps">Rendimiento mensual</span>
          </div>
        </div>
      </div>
    </section>
  )
}
