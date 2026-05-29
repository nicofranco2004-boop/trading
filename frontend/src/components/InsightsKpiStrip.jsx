// InsightsKpiStrip — KPI strip denso al tope de /insights (V2).
// ═══════════════════════════════════════════════════════════════════════════
// Cinco celdas tabular, estilo audit:
//   1) Findings detectados  → bucket HI / MED / LO
//   2) Concentración top    → activo con mayor share
//   3) Drawdown actual      → TWRR
//   4) Rendimiento acum.    → TWRR vs benchmark si está
//   5) Win rate · trades    → ratio de operaciones cerradas

const SEV_LABEL = { urgent: 'HI', warn: 'MED', positive: 'POS', info: 'LO' }
const SEV_TONE = {
  urgent:   'text-rendi-neg',
  warn:     'text-rendi-warn',
  positive: 'text-rendi-pos',
  info:     'text-ink-3',
}

function fmtPctShort(p, opts = {}) {
  if (p == null || Number.isNaN(p)) return '—'
  const sign = p >= 0 && opts.showPlus ? '+' : ''
  return `${sign}${p.toFixed(opts.decimals ?? 1)}`
}

export default function InsightsKpiStrip({
  diagnosis = [],
  assetPieData = [],
  drawdownTwrr,
  winRate,
  cumulativeReturnPct,
  benchmarkReturnPct,
  benchmarkLabel,
  currency = 'USD',
}) {
  // ── 1) Findings buckets ────────────────────────────────────────────────────
  const buckets = { urgent: 0, warn: 0, positive: 0, info: 0 }
  for (const d of diagnosis) {
    if (buckets[d.severity] != null) buckets[d.severity]++
  }
  const totalFindings = diagnosis.length

  // ── 2) Concentración top ───────────────────────────────────────────────────
  const totalAssetValue = assetPieData.reduce((s, x) => s + (x.value || 0), 0)
  let topAsset = null
  if (totalAssetValue > 0) {
    const top = [...assetPieData].sort((a, b) => (b.value || 0) - (a.value || 0))[0]
    if (top) {
      topAsset = { name: top.name, pct: (top.value / totalAssetValue) * 100 }
    }
  }
  const concentrationTone =
    !topAsset ? null :
    topAsset.pct >= 50 ? 'neg' :
    topAsset.pct >= 30 ? 'warn' :
    null

  // ── 3) Drawdown ────────────────────────────────────────────────────────────
  const ddCurrent = drawdownTwrr?.currentPct
  const ddMax = drawdownTwrr?.maxPct
  const ddTone = ddCurrent == null ? null : (ddCurrent < -5 ? 'neg' : (ddCurrent < -1 ? 'warn' : null))

  // ── 4) Rendimiento acumulado vs benchmark ──────────────────────────────────
  const rendTone = cumulativeReturnPct == null ? null : (cumulativeReturnPct >= 0 ? 'pos' : 'neg')

  // ── 5) Win rate ────────────────────────────────────────────────────────────
  const wr = winRate?.pct ?? null
  const wrTotal = winRate?.total ?? 0

  return (
    <div className="border border-line rounded bg-bg-1 flex flex-wrap">
      <KpiCell
        label="Findings detectados"
        value={totalFindings}
        hero
        sub={
          totalFindings > 0 ? (
            <span className="flex items-center gap-1.5">
              {buckets.urgent > 0 && <span className={SEV_TONE.urgent}>{buckets.urgent} {SEV_LABEL.urgent}</span>}
              {buckets.warn > 0 && <span className={SEV_TONE.warn}>{buckets.warn} {SEV_LABEL.warn}</span>}
              {buckets.positive > 0 && <span className={SEV_TONE.positive}>{buckets.positive} {SEV_LABEL.positive}</span>}
              {buckets.info > 0 && <span className={SEV_TONE.info}>{buckets.info} {SEV_LABEL.info}</span>}
            </span>
          ) : 'sin observaciones'
        }
      />
      <KpiCell
        label={topAsset ? `Concentración · ${topAsset.name}` : 'Concentración'}
        value={topAsset ? `${fmtPctShort(topAsset.pct, { decimals: 0 })}%` : '—'}
        tone={concentrationTone}
        sub={topAsset ? 'del portfolio total' : 'sin posiciones'}
      />
      <KpiCell
        label="Drawdown actual"
        value={ddCurrent != null ? `${fmtPctShort(ddCurrent, { decimals: 1 })}%` : '—'}
        tone={ddTone}
        sub={ddMax != null ? `peak histórico ${fmtPctShort(ddMax, { decimals: 1 })}%` : 'TWRR'}
      />
      <KpiCell
        label={`Acumulado · ${currency}`}
        value={cumulativeReturnPct != null ? `${fmtPctShort(cumulativeReturnPct, { decimals: 1, showPlus: true })}%` : '—'}
        tone={rendTone}
        sub={
          benchmarkReturnPct != null
            ? `vs ${benchmarkLabel}: ${fmtPctShort(benchmarkReturnPct, { decimals: 1, showPlus: true })}%`
            : 'TWRR ajustado'
        }
      />
      <KpiCell
        label="Win rate"
        value={wr != null ? `${fmtPctShort(wr, { decimals: 0 })}%` : '—'}
        sub={wrTotal > 0 ? `${wrTotal} ${wrTotal === 1 ? 'op cerrada' : 'ops cerradas'}` : 'sin operaciones'}
      />
    </div>
  )
}

function KpiCell({ label, value, sub, tone, hero }) {
  const valueColor =
    tone === 'pos'  ? 'text-rendi-pos' :
    tone === 'neg'  ? 'text-rendi-neg' :
    tone === 'warn' ? 'text-rendi-warn' :
    'text-ink-0'
  return (
    <div className="px-4 py-3 border-r border-line/40 last:border-r-0 flex-1 min-w-[150px]">
      <div className="text-[9px] font-mono uppercase tracking-label text-ink-2 leading-none">{label}</div>
      <div className={`mt-2 font-medium tabular num leading-none ${hero ? 'text-3xl tracking-tight' : 'text-2xl'} ${valueColor}`}>
        {value}
      </div>
      <div className="text-[10px] font-mono text-ink-3 mt-1.5 leading-none truncate">{sub}</div>
    </div>
  )
}
