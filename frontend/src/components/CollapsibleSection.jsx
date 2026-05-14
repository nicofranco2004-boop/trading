import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'

/**
 * CollapsibleSection — sección que arranca colapsada.
 * Diseñada para "Análisis avanzado" en Insights: oculta detalle pesado por
 * defecto, el usuario lo abre solo si lo necesita.
 *
 * Mantiene el hijo MONTADO siempre cuando defaultOpen=true. Cuando se
 * colapsa el hijo se desmonta para evitar costos de cálculo si se vuelve
 * a abrir reactiva el state.
 */
export default function CollapsibleSection({
  title,
  subtitle,
  defaultOpen = false,
  badge,
  children,
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <section className="border-t border-line/60 dark:border-line/40 pt-6">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-3 text-left group"
      >
        <div className="flex items-center gap-2 min-w-0">
          <h2 className="section-title group-hover:text-ink-0 dark:group-hover:text-ink-1 transition-colors">
            {title}
          </h2>
          {badge != null && (
            <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-bg-2 dark:bg-bg-2/60 text-ink-2">
              {badge}
            </span>
          )}
        </div>
        <span className="flex-shrink-0 text-ink-3 group-hover:text-ink-0 dark:group-hover:text-ink-1 transition-colors">
          {open ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
        </span>
      </button>
      {subtitle && <p className="section-subtitle mt-1">{subtitle}</p>}
      {open && (
        <div className="mt-5 space-y-6">
          {children}
        </div>
      )}
    </section>
  )
}
