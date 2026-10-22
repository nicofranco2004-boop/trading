// Modal — wrapper unificado. En desktop renderiza modal centrado; en mobile
// delega a BottomSheet (drag handle + swipe-to-dismiss + sticky footer).
// ═══════════════════════════════════════════════════════════════════════════
// Esto es lo que permite que cada Modal viejo del producto (Positions,
// Operations, Goals, Monthly, etc.) tenga UX mobile correcta sin refactor
// por página — solo cambiando este componente.

import { useId, useRef } from 'react'
import { X } from 'lucide-react'
import { useIsMobile } from '../hooks/useIsMobile'
import { useDialogo } from '../hooks/useDialogo'
import BottomSheet from './mobile/BottomSheet'

export default function Modal({ title, onClose, children, wide = false }) {
  // `wide`: variante ancha para contenido tabular (ej. la tabla de asignación
  // de la operación grupal del Plan Asesor). En mobile no cambia nada (sheet).
  const isMobile = useIsMobile()

  if (isMobile) {
    return (
      <BottomSheet open onClose={onClose} title={title} ariaLabel={title}>
        <div className="p-4">{children}</div>
      </BottomSheet>
    )
  }

  // Desktop: modal centrado clásico.
  return <ModalEscritorio title={title} onClose={onClose} wide={wide}>{children}</ModalEscritorio>
}

// Aparte para que los hooks de teclado no queden detrás del `return` de mobile
// (un hook después de un return condicional rompe el orden de React).
function ModalEscritorio({ title, onClose, children, wide }) {
  const caja = useRef(null)
  const tituloId = useId()
  useDialogo(caja, onClose)

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto">
      <div
        ref={caja}
        role="dialog"
        aria-modal="true"
        aria-labelledby={tituloId}
        tabIndex={-1}
        className={`bg-bg-raised border border-line rounded-t-2xl sm:rounded-xl w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} shadow-2xl max-h-[95vh] sm:max-h-[90vh] flex flex-col outline-none`}
      >
        <div className="flex items-center justify-between px-4 sm:px-5 py-3 sm:py-4 border-b border-line flex-shrink-0">
          <h2 id={tituloId} className="font-semibold text-ink-0 text-sm sm:text-base truncate pr-2">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Cerrar" className="text-ink-3 hover:text-ink-2 dark:hover:text-ink-0 flex-shrink-0">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div className="p-4 sm:p-5 overflow-y-auto flex-1">{children}</div>
      </div>
    </div>
  )
}
