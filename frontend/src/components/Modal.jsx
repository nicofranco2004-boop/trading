// Modal — wrapper unificado. En desktop renderiza modal centrado; en mobile
// delega a BottomSheet (drag handle + swipe-to-dismiss + sticky footer).
// ═══════════════════════════════════════════════════════════════════════════
// Esto es lo que permite que cada Modal viejo del producto (Positions,
// Operations, Goals, Monthly, etc.) tenga UX mobile correcta sin refactor
// por página — solo cambiando este componente.

import { X } from 'lucide-react'
import { useIsMobile } from '../hooks/useIsMobile'
import BottomSheet from './mobile/BottomSheet'

export default function Modal({ title, onClose, children }) {
  const isMobile = useIsMobile()

  if (isMobile) {
    return (
      <BottomSheet open onClose={onClose} title={title} ariaLabel={title}>
        <div className="p-4">{children}</div>
      </BottomSheet>
    )
  }

  // Desktop: modal centrado clásico.
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto">
      <div className="bg-white dark:bg-bg-2 border border-line rounded-t-2xl sm:rounded-xl w-full max-w-lg shadow-2xl max-h-[95vh] sm:max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-4 sm:px-5 py-3 sm:py-4 border-b border-line flex-shrink-0">
          <h2 className="font-semibold text-ink-0 text-sm sm:text-base truncate pr-2">{title}</h2>
          <button onClick={onClose} className="text-ink-3 hover:text-ink-2 dark:hover:text-ink-0 flex-shrink-0">
            <X size={18} />
          </button>
        </div>
        <div className="p-4 sm:p-5 overflow-y-auto flex-1">{children}</div>
      </div>
    </div>
  )
}
