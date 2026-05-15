// SwipeRow — fila con acciones reveladas al swipear izquierda (Sprint M3, item 12).
// ═══════════════════════════════════════════════════════════════════════════
// Patrón nativo iOS/Android: el user arrastra el row hacia la izquierda y
// se revelan 1-3 botones de acción rápida (operar / ocultar / watchlist).
//
// Implementación:
// - track del drag con touch events (no requiere libs)
// - threshold: si arrastra > 1/2 del width de las acciones → quedan abiertas
// - tap fuera → cierra
// - tap en otra row → cierra la actual
//
// API:
//   <SwipeRow
//     actions={[{ id, label, icon, tone, onClick }, ...]}
//     onTap={() => navigate(...)}
//   >
//     row content
//   </SwipeRow>
//
// Si actions es vacío, se comporta como un div normal sin swipe.

import { useEffect, useRef, useState } from 'react'

const ACTION_W = 72  // px por acción
const OPEN_THRESHOLD = 0.5  // % del width total para "abrir"
const DRAG_MIN = 8  // px mínimos para considerar gesture (ignora micro-touches)

// State global de "row abierta" — al abrir una, cierra la anterior.
let openRowId = null
const openListeners = new Set()
function setOpenRow(id) {
  openRowId = id
  openListeners.forEach(fn => fn(id))
}

const TONE_CLASS = {
  pos:    'bg-rendi-pos text-bg-0',
  neg:    'bg-rendi-neg text-bg-0',
  warn:   'bg-rendi-warn text-bg-0',
  accent: 'bg-rendi-accent text-white',
  neutral: 'bg-bg-3 text-ink-0',
}

export default function SwipeRow({ actions = [], onTap, children, className = '', rowId }) {
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState(false)
  const dragging = useRef(false)
  const startX = useRef(null)
  const startY = useRef(null)
  const moved = useRef(false)
  const id = useRef(rowId || Math.random().toString(36).slice(2)).current

  const maxOffset = actions.length * ACTION_W

  // Si otra row se abre → cerrar esta
  useEffect(() => {
    function onChange(activeId) {
      if (activeId !== id && open) {
        setOpen(false)
        setOffset(0)
      }
    }
    openListeners.add(onChange)
    return () => { openListeners.delete(onChange) }
  }, [open, id])

  function onTouchStart(e) {
    if (!actions.length) return
    startX.current = e.touches[0].clientX
    startY.current = e.touches[0].clientY
    dragging.current = true
    moved.current = false
  }

  function onTouchMove(e) {
    if (!dragging.current || startX.current == null) return
    const dx = e.touches[0].clientX - startX.current
    const dy = e.touches[0].clientY - startY.current
    // Si el gesto es más vertical → cancelar (es scroll)
    if (Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > DRAG_MIN) {
      dragging.current = false
      setOffset(open ? -maxOffset : 0)
      return
    }
    if (Math.abs(dx) > DRAG_MIN) moved.current = true
    // Solo permitimos swipe izquierda (dx < 0). dx > 0 cierra si abierta.
    const startOffset = open ? -maxOffset : 0
    const newOffset = Math.min(0, Math.max(-maxOffset, startOffset + dx))
    setOffset(newOffset)
  }

  function onTouchEnd() {
    if (!dragging.current) return
    dragging.current = false
    const shouldOpen = Math.abs(offset) > maxOffset * OPEN_THRESHOLD
    if (shouldOpen) {
      setOpen(true)
      setOffset(-maxOffset)
      setOpenRow(id)
    } else {
      setOpen(false)
      setOffset(0)
      if (openRowId === id) setOpenRow(null)
    }
    startX.current = null
    startY.current = null
  }

  function handleClick(e) {
    if (open) {
      e.preventDefault()
      e.stopPropagation()
      setOpen(false)
      setOffset(0)
      setOpenRow(null)
      return
    }
    if (moved.current) {
      e.preventDefault()
      e.stopPropagation()
      moved.current = false
      return
    }
    if (typeof onTap === 'function') onTap(e)
  }

  function handleActionClick(action) {
    setOpen(false)
    setOffset(0)
    setOpenRow(null)
    if (typeof action.onClick === 'function') action.onClick()
  }

  return (
    <div className={`relative overflow-hidden ${className}`}>
      {/* Botones de acción al fondo (siempre presentes, se revelan al swipear) */}
      {actions.length > 0 && (
        <div
          aria-hidden={!open}
          className="absolute inset-y-0 right-0 flex"
          style={{ width: maxOffset }}
        >
          {actions.map((a) => {
            const Icon = a.icon
            return (
              <button
                key={a.id}
                onClick={(e) => { e.stopPropagation(); handleActionClick(a) }}
                tabIndex={open ? 0 : -1}
                aria-label={a.label}
                className={`flex flex-col items-center justify-center gap-1 text-[10px] font-mono uppercase tracking-caps active:opacity-80 transition-opacity ${TONE_CLASS[a.tone] || TONE_CLASS.neutral}`}
                style={{ width: ACTION_W }}
              >
                {Icon && <Icon size={16} strokeWidth={1.75} />}
                {a.label}
              </button>
            )
          })}
        </div>
      )}

      {/* Row content que se mueve con el drag */}
      <div
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onClick={handleClick}
        style={{
          transform: `translateX(${offset}px)`,
          transition: dragging.current ? 'none' : 'transform 220ms cubic-bezier(0.32, 0.72, 0, 1)',
        }}
        className="bg-bg-0 relative"
      >
        {children}
      </div>
    </div>
  )
}
