// StarToggle — botón estrella para agregar/quitar un ticker de la watchlist.
// ═══════════════════════════════════════════════════════════════════════════
// Reusa el patrón visual (Star de lucide, fill ámbar cuando está activo). La
// lógica de mutación vive en useWatchlist; este componente es presentacional.

import { Star } from 'lucide-react'

export default function StarToggle({ active, onToggle, size = 16, className = '' }) {
  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); onToggle?.() }}
      aria-pressed={active}
      title={active ? 'Quitar de favoritos' : 'Agregar a favoritos'}
      aria-label={active ? 'Quitar de favoritos' : 'Agregar a favoritos'}
      className={`inline-flex items-center justify-center rounded-sm p-1 transition-colors ${
        active
          ? 'text-rendi-warn hover:text-rendi-warn/80'
          : 'text-ink-3 hover:text-ink-1'
      } ${className}`}
    >
      <Star size={size} strokeWidth={1.75} fill={active ? 'currentColor' : 'none'} aria-hidden="true" />
    </button>
  )
}
