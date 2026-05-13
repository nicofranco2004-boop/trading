// HighlightsRail — fila horizontal con highlights del período (best op, worst op, etc.).
// Diseño compacto, scrolleable en mobile. Cada highlight es un mini chip.

export default function HighlightsRail({ highlights }) {
  if (!highlights || highlights.length === 0) return null

  return (
    <div className="flex gap-2 overflow-x-auto -mx-1 px-1 pb-1">
      {highlights.map((h, i) => (
        <div
          key={`${h.kind}-${i}`}
          className="flex-shrink-0 flex items-center gap-2 px-3 py-2 rounded-sm border border-line bg-bg-2/40 min-w-[140px]"
        >
          <span className="text-base" aria-hidden="true">{h.icon}</span>
          <div className="flex flex-col min-w-0">
            <span className="text-[10px] uppercase tracking-wider text-ink-3 leading-tight">
              {h.label}
            </span>
            <span className="text-xs font-mono text-ink-1 truncate" title={h.value_label}>
              {h.value_label}
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
