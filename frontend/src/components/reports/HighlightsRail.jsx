// HighlightsRail — fila horizontal con highlights del período.
// Diseño denso, scrolleable. Iconos lucide (no emojis); el icon del backend
// se ignora y mapeamos por `kind`.

import { Rocket, Skull, Award, TrendingUp, TrendingDown } from 'lucide-react'

const KIND_STYLE = {
  best_op:  { Icon: Rocket,         tone: 'pos' },
  worst_op: { Icon: TrendingDown,   tone: 'neg' },
  best_day: { Icon: TrendingUp,     tone: 'pos' },
  worst_day:{ Icon: TrendingDown,   tone: 'neg' },
}
const FALLBACK = { Icon: Award, tone: 'neutral' }

const TONE_STYLE = {
  pos:     { container: 'border-rendi-pos/30 bg-rendi-pos/[0.06]',  icon: 'text-rendi-pos' },
  neg:     { container: 'border-rendi-neg/30 bg-rendi-neg/[0.06]',  icon: 'text-rendi-neg' },
  neutral: { container: 'border-line bg-bg-2/40',                    icon: 'text-data-cyan' },
}

export default function HighlightsRail({ highlights }) {
  if (!highlights || highlights.length === 0) return null

  return (
    <div className="flex gap-2 overflow-x-auto -mx-1 px-1 pb-1">
      {highlights.map((h, i) => {
        const cfg = KIND_STYLE[h.kind] || FALLBACK
        const style = TONE_STYLE[cfg.tone]
        const Icon = cfg.Icon
        return (
          <div
            key={`${h.kind}-${i}`}
            className={`flex-shrink-0 flex items-center gap-2.5 px-3 py-2 rounded-sm border ${style.container} min-w-[160px]`}
          >
            <span className="inline-flex items-center justify-center w-7 h-7 rounded-sm bg-bg-1/60 flex-shrink-0" aria-hidden="true">
              <Icon size={14} strokeWidth={1.75} className={style.icon} />
            </span>
            <div className="flex flex-col min-w-0">
              <span className="text-[12.5px] text-ink-2 leading-tight font-medium">
                {h.label}
              </span>
              <span className="text-xs font-mono text-ink-1 truncate" title={h.value_label}>
                {h.value_label}
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
