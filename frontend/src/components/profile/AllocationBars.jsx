// AllocationBars — asignación sugerida vs real por clase de activo.
// ═══════════════════════════════════════════════════════════════════════════
// Por fila, dos barras finas apiladas: gris = mix sugerido para la categoría
// del test (p.ej. "Moderado"), violeta = cartera real. Los colores de serie
// van SOLO en las marcas/swatches — el texto siempre en tokens ink.
// Renderiza solo el BODY del módulo — header/badge viven en el shell.

const GRAY = '#4A5468'
const VIOLET = '#8B7DFF'

const clamp = (v) => Math.max(0, Math.min(100, Number(v) || 0))

function Bar({ value, color, valueCls }) {
  const pct = clamp(value)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-[6px] rounded-full bg-bg-3 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className={`font-mono text-[10px] tabular-nums w-9 text-right ${valueCls}`}>
        {Math.round(pct)}%
      </span>
    </div>
  )
}

export default function AllocationBars({ rows, categoryLabel }) {
  if (!rows?.length) return null

  return (
    <div>
      <div className="space-y-2.5">
        {rows.map((r, i) => (
          <div key={i} className="flex items-center gap-3">
            <span className="w-24 shrink-0 text-xs text-ink-2">{r.label}</span>
            <div className="flex-1 space-y-[2px]">
              <Bar value={r.suggested} color={GRAY} valueCls="text-ink-2" />
              <Bar value={r.actual} color={VIOLET} valueCls="text-ink-1" />
            </div>
          </div>
        ))}
      </div>

      {/* Leyenda */}
      <div className="flex items-center gap-4 mt-3">
        <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-2">
          <span
            className="inline-block w-3 h-2 rounded-[2px]"
            style={{ background: GRAY }}
            aria-hidden="true"
          />
          Sugerida{categoryLabel ? ` (${categoryLabel})` : ''}
        </span>
        <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-2">
          <span
            className="inline-block w-3 h-2 rounded-[2px]"
            style={{ background: VIOLET }}
            aria-hidden="true"
          />
          Tu cartera
        </span>
      </div>
    </div>
  )
}
