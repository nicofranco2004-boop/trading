// NewsTagBadge — badge para clasificar visualmente el tipo de noticia.
// ════════════════════════════════════════════════════════════════════════════
// Los tags vienen del backend (CSV en DB → array en JSON). Cada uno tiene
// un label visible y un color semántico:
//
//   earnings     → purple   (Q1/Q2/Q3/Q4 results)
//   m_and_a      → blue     (mergers, acquisitions)
//   rates        → amber    (Fed/BCRA, tasas)
//   inflation    → rose     (CPI, IPC, INDEC)
//   forex        → indigo   (dólar, FX)
//   dividend     → green    (payouts)
//   regulatory   → gray     (SEC, multas, antitrust)
//   debt         → amber    (default, FMI, deuda)
//
// Mantenemos las clases Tailwind explícitas (no template strings dinámicos)
// para que el purger no las borre.

const TAG_META = {
  earnings:    { label: 'Earnings',   classes: 'bg-purple-500/15 text-purple-500 dark:text-purple-400 border-purple-500/40' },
  m_and_a:     { label: 'M&A',        classes: 'bg-blue-500/15   text-blue-500   dark:text-blue-400   border-blue-500/40' },
  rates:       { label: 'Tasas',      classes: 'bg-amber-500/15  text-amber-600  dark:text-amber-400  border-amber-500/40' },
  inflation:   { label: 'Inflación',  classes: 'bg-rose-500/15   text-rose-500   dark:text-rose-400   border-rose-500/40' },
  forex:       { label: 'FX',         classes: 'bg-indigo-500/15 text-indigo-500 dark:text-indigo-400 border-indigo-500/40' },
  dividend:    { label: 'Dividendo',  classes: 'bg-rendi-pos/15  text-rendi-pos                       border-rendi-pos/40' },
  regulatory:  { label: 'Regulación', classes: 'bg-bg-3          text-ink-2                           border-line' },
  debt:        { label: 'Deuda',      classes: 'bg-amber-500/15  text-amber-600  dark:text-amber-400  border-amber-500/40' },
}

export const NEWS_TAG_VALUES = Object.keys(TAG_META)

export function newsTagLabel(tagId) {
  return TAG_META[tagId]?.label || tagId
}

// Si recibe `onClick`, se renderiza como botón clickeable (afford visual:
// hover + cursor). Caller debe llamar e.preventDefault() / stopPropagation()
// si está dentro de un <a> para evitar disparar el link.
export default function NewsTagBadge({ tag, size = 'sm', onClick }) {
  const meta = TAG_META[tag]
  if (!meta) return null
  const sizeClasses = size === 'lg'
    ? 'text-[10px] px-2 py-0.5'
    : 'text-[9px] px-1.5 py-0.5'
  const baseClasses = `font-mono uppercase tracking-[0.12em] rounded-sm border inline-flex items-center ${sizeClasses} ${meta.classes}`
  if (onClick) {
    return (
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClick(tag) }}
        className={`${baseClasses} cursor-pointer hover:opacity-80 transition-opacity`}
        aria-label={`Filtrar por ${meta.label}`}
      >
        {meta.label}
      </button>
    )
  }
  return (
    <span className={baseClasses}>
      {meta.label}
    </span>
  )
}
