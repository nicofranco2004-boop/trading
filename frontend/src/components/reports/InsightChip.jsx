// InsightChip — chip narrativo con popover de evidencia al hover/click.
//
// Diseño: minimalista, una línea visible (severity dot + title). Al hover/tap
// se expande mostrando body + evidencia. La evidencia tiene shape libre — la
// renderizamos en JSON crudo por default; cards específicos pueden override.

import { useState } from 'react'
import { AlertTriangle, TrendingUp, Info, X } from 'lucide-react'

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
        <div className="px-3 pb-2.5 pt-1 text-xs leading-relaxed text-ink-2 border-t border-line/50">
          <p className="mb-2">{insight.body}</p>
          {insight.evidence && Object.keys(insight.evidence).length > 0 && (
            <details className="text-[10px] text-ink-3">
              <summary className="cursor-pointer hover:text-ink-2">Ver datos</summary>
              <pre className="mt-1 px-2 py-1 rounded bg-bg-3 overflow-x-auto font-mono">
                {JSON.stringify(insight.evidence, null, 2)}
              </pre>
            </details>
          )}
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
