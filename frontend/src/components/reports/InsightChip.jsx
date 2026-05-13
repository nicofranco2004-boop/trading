// InsightChip — chip narrativo con popover de evidencia al hover/click.
//
// Diseño: minimalista, una línea visible (severity dot + title). Al click se
// expande mostrando body + evidencia visual rica (mini chart / bars / pills),
// renderizada por `InsightEvidence` según el `code` del insight.

import { useState } from 'react'
import { AlertTriangle, TrendingUp, Info, X } from 'lucide-react'
import InsightEvidence from './InsightEvidence'

const SEVERITY_STYLE = {
  warning:  { border: 'border-rendi-warn/30', bg: 'bg-rendi-warn/[0.06]', text: 'text-rendi-warn', icon: AlertTriangle },
  positive: { border: 'border-rendi-pos/30',  bg: 'bg-rendi-pos/[0.06]',  text: 'text-rendi-pos',  icon: TrendingUp },
  info:     { border: 'border-line',          bg: 'bg-bg-2',              text: 'text-ink-2',      icon: Info },
}

export default function InsightChip({ insight }) {
  const [open, setOpen] = useState(false)
  const style = SEVERITY_STYLE[insight.severity] || SEVERITY_STYLE.info
  const Icon = style.icon

  return (
    <div className={`relative rounded-sm border ${style.border} ${style.bg}`}>
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start gap-2 px-3 py-2 text-left hover:bg-black/5 dark:hover:bg-white/5 transition-colors"
      >
        <Icon size={13} strokeWidth={1.75} className={`flex-shrink-0 mt-0.5 ${style.text}`} aria-hidden="true" />
        <span className="text-xs text-ink-1 leading-snug flex-1">
          {insight.title}
        </span>
      </button>

      {open && (
        <div className="px-3 pb-3 pt-1 text-xs leading-relaxed text-ink-2 border-t border-line/50 space-y-2">
          <p>{insight.body}</p>
          <div className="pt-1">
            <InsightEvidence insight={insight} />
          </div>
          <button
            onClick={() => setOpen(false)}
            className="absolute top-1.5 right-1.5 text-ink-3 hover:text-ink-1"
            aria-label="Cerrar"
          >
            <X size={12} strokeWidth={1.75} />
          </button>
        </div>
      )}
    </div>
  )
}
