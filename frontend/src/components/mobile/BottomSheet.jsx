// BottomSheet — patrón unificado de sheet bottom-up para mobile (Sprint M2).
// ═══════════════════════════════════════════════════════════════════════════
// Reemplaza Modal en mobile. Estructura del audit:
//   ┌─────────────────────────┐
//   │       ▬▬▬               │ ← drag handle (44px hit target)
//   │ EYEBROW                 │
//   │ Título                ✕ │ ← header
//   │ ───────────────         │
//   │                         │
//   │  body                   │ ← scrollable
//   │                         │
//   │ ─────────────           │
//   │ [Acción primaria]       │ ← footer sticky
//   └─────────────────────────┘
//
// Features:
// - Swipe-to-dismiss (drag down > 100px → cierra)
// - Backdrop click → cierra
// - ESC → cierra
// - Lockea scroll del body mientras está abierto
// - safe-area-inset-bottom para no cortar el footer
// - Animación slide-up al abrir, slide-down al cerrar (160ms)
//
// API:
//   <BottomSheet
//     open={bool}
//     onClose={fn}
//     eyebrow="Tipo de sheet"
//     title="Título"
//     footer={<button>Confirmar</button>}  // opcional, sticky
//   >
//     {body content}
//   </BottomSheet>

import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'

const DISMISS_THRESHOLD = 100  // px de drag para cerrar
const MAX_DRAG = 400           // tope visible

export default function BottomSheet({
  open,
  onClose,
  eyebrow,
  title,
  footer,
  children,
  maxHeight = '92vh',
  ariaLabel,
}) {
  const [dragOffset, setDragOffset] = useState(0)
  const [closing, setClosing] = useState(false)
  const startY = useRef(null)
  const dragging = useRef(false)

  // Lock body scroll mientras está abierto
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [open])

  // ESC → cerrar
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') triggerClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  function triggerClose() {
    setClosing(true)
    // Esperar a que termine la anim slide-down
    setTimeout(() => {
      setClosing(false)
      setDragOffset(0)
      onClose?.()
    }, 180)
  }

  // ── Drag handlers (solo en el handle/header) ──────────────────────────
  function onTouchStart(e) {
    startY.current = e.touches[0].clientY
    dragging.current = true
  }

  function onTouchMove(e) {
    if (!dragging.current || startY.current == null) return
    const dy = e.touches[0].clientY - startY.current
    if (dy < 0) {
      setDragOffset(0)  // sólo permitimos drag hacia abajo
      return
    }
    setDragOffset(Math.min(dy, MAX_DRAG))
  }

  function onTouchEnd() {
    if (!dragging.current) return
    dragging.current = false
    if (dragOffset >= DISMISS_THRESHOLD) {
      triggerClose()
    } else {
      // snap back
      setDragOffset(0)
    }
    startY.current = null
  }

  if (!open && !closing) return null

  const sheetTransform = closing
    ? 'translateY(100%)'
    : dragOffset > 0
      ? `translateY(${dragOffset}px)`
      : 'translateY(0)'

  const sheetTransition = dragging.current
    ? 'none'
    : 'transform 180ms cubic-bezier(0.32, 0.72, 0, 1)'

  const backdropOpacity = closing
    ? 0
    : Math.max(0.35, 1 - dragOffset / 400)

  return (
    <div
      className="fixed inset-0 z-[60] flex items-end"
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel || title || 'Sheet'}
      onClick={(e) => {
        if (e.target === e.currentTarget) triggerClose()
      }}
    >
      {/* Backdrop */}
      <div
        aria-hidden
        className="absolute inset-0 bg-black backdrop-blur-sm"
        style={{
          opacity: backdropOpacity,
          transition: closing ? 'opacity 180ms ease' : 'none',
        }}
        onClick={triggerClose}
      />

      {/* Sheet */}
      <div
        className="relative w-full bg-bg-1 border-t border-line-2 rounded-t-2xl flex flex-col shadow-2xl"
        style={{
          transform: sheetTransform,
          transition: sheetTransition,
          maxHeight,
          paddingBottom: 'env(safe-area-inset-bottom, 0px)',
          ...(open && !closing && dragOffset === 0 ? { animation: 'mobile-slide-up 220ms cubic-bezier(0.32, 0.72, 0, 1)' } : null),
        }}
      >
        {/* Drag handle (hit target 44px) */}
        <div
          className="flex justify-center pt-2 pb-1 cursor-grab active:cursor-grabbing"
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
        >
          <div aria-hidden className="w-9 h-1 rounded-full bg-line-3" />
        </div>

        {/* Header */}
        {(title || eyebrow) && (
          <header
            className="flex items-start justify-between gap-2 px-4 pb-3 border-b border-line/40"
            onTouchStart={onTouchStart}
            onTouchMove={onTouchMove}
            onTouchEnd={onTouchEnd}
          >
            <div className="min-w-0 flex-1">
              {eyebrow && (
                <div className="text-[12.5px] text-ink-2 leading-none mb-1.5 font-medium">
                  {eyebrow}
                </div>
              )}
              {title && (
                <h2 className="text-base font-medium text-ink-0 leading-tight">
                  {title}
                </h2>
              )}
            </div>
            <button
              onClick={triggerClose}
              aria-label="Cerrar"
              className="text-ink-3 hover:text-ink-0 transition-colors p-1 -mt-1 -mr-1 flex-shrink-0"
            >
              <X size={16} strokeWidth={1.75} />
            </button>
          </header>
        )}

        {/* Body — scrollable */}
        <div className="flex-1 overflow-y-auto overscroll-contain">
          {children}
        </div>

        {/* Footer sticky — acción primaria */}
        {footer && (
          <div className="border-t border-line/40 px-4 py-3 bg-bg-1 flex-shrink-0">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
