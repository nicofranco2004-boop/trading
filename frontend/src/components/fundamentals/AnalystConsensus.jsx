// AnalystConsensus — bloque "Consenso de analistas".
// ═══════════════════════════════════════════════════════════════════════════
// props: { analysts } con el shape del contrato:
//   { available, recommendation_key, recommendation_label, n_analysts,
//     target_mean_usd, current_price_usd, upside_pct }
// Color de la recomendación por key (buy→verde, hold→ámbar, sell→rojo).
// upside_pct como Pill (+X% verde / -X% rojo). null/available:false → no render.

import { Users } from 'lucide-react'
import Pill from '../Pill'

function toneForRec(key) {
  const k = (key || '').toLowerCase()
  if (k.includes('buy')) return 'signal'
  if (k.includes('sell') || k.includes('underperform')) return 'red'
  return 'warn' // hold / neutral
}

function fmtUsd(v) {
  if (v == null) return '—'
  return `$${Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })}`
}

export default function AnalystConsensus({ analysts }) {
  if (!analysts || !analysts.available) return null

  const upside = analysts.upside_pct
  const hasUpside = typeof upside === 'number' && !Number.isNaN(upside)
  const upsideTone = hasUpside ? (upside >= 0 ? 'signal' : 'red') : 'default'
  const upsideLabel = hasUpside
    ? `${upside >= 0 ? '+' : ''}${upside.toFixed(0)}%`
    : '—'

  return (
    <div className="bg-bg-1 border border-line rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <Users size={15} strokeWidth={1.75} className="text-ink-3" />
        <p className="text-[12px] text-ink-2 font-medium">
          Consenso de analistas
        </p>
      </div>

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Pill tone={toneForRec(analysts.recommendation_key)}>
              {analysts.recommendation_label || '—'}
            </Pill>
          </div>
          {analysts.n_analysts != null && (
            <p className="text-xs text-ink-3 mt-1.5">
              según {analysts.n_analysts} analistas
            </p>
          )}
        </div>

        <div className="text-right">
          <p className="text-[12px] text-ink-3 font-medium">
            Precio objetivo
          </p>
          <div className="flex items-center justify-end gap-2 mt-0.5">
            <span className="text-lg font-semibold text-ink-0 tabular">
              {fmtUsd(analysts.target_mean_usd)}
            </span>
            <Pill tone={upsideTone}>{upsideLabel}</Pill>
          </div>
        </div>
      </div>
    </div>
  )
}
