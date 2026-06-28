// SearchOverlay — buscador de activos como command-palette (no como barra-héroe).
// ═══════════════════════════════════════════════════════════════════════════
// La búsqueda deja de ser la portada (eso era Vesty): es una herramienta que se
// abre con el botón "Buscar" o con ⌘K / Ctrl+K. Al elegir un activo, la página
// abre su ficha. Cierra con Escape o click en el fondo.

import { useEffect } from 'react'
import { X } from 'lucide-react'
import TickerSearch from './TickerSearch'

export default function SearchOverlay({ onSelect, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center pt-[14vh] px-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Buscar activo"
    >
      <div
        className="w-full max-w-xl bg-bg-1 border border-line rounded-xl shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 pt-3.5 pb-2">
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">Buscar activo</span>
          <button onClick={onClose} className="text-ink-3 hover:text-ink-0 p-1 -mr-1" aria-label="Cerrar">
            <X size={16} strokeWidth={2} />
          </button>
        </div>
        <div className="px-4 pb-4">
          <TickerSearch onSelect={onSelect} autoFocus />
          <p className="text-[11px] text-ink-3 mt-3">
            Buscá cualquier acción o CEDEAR (NVDA, Apple, MELI…) para ver su calidad — la tengas o no.
          </p>
        </div>
      </div>
    </div>
  )
}
