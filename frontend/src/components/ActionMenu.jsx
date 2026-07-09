import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MoreVertical } from 'lucide-react'

/**
 * ActionMenu — three-dot menu for table rows.
 * Replaces multiple icon buttons with a clean popover.
 *
 * El menú se renderiza en un PORTAL (document.body) con position:fixed y un z-index
 * alto: así escapa del contexto de apilamiento / overflow de la fila de la tabla.
 * Sin esto, el ⋮ de la fila siguiente quedaba POR ENCIMA del menú abierto (cada fila
 * es su propio stacking context) y lo tapaba (bug reportado en Posiciones, mobile).
 *
 * Usage:
 *   <ActionMenu items={[
 *     { label: 'Editar', onClick: () => ..., icon: <Pencil size={13} /> },
 *     { label: 'Eliminar', onClick: () => ..., danger: true, icon: <Trash2 size={13} /> },
 *   ]} />
 */
export default function ActionMenu({ items = [], align = 'right' }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(null)   // coords fixed {top, left} del menú
  const btnRef = useRef(null)
  const menuRef = useRef(null)

  const MENU_W = 190

  // Posiciona el menú debajo del botón, alineado a der/izq y clampeado al viewport.
  const place = () => {
    const b = btnRef.current?.getBoundingClientRect()
    if (!b) return
    const left = align === 'right' ? b.right - MENU_W : b.left
    const clampedLeft = Math.min(Math.max(8, left), window.innerWidth - MENU_W - 8)
    setPos({ top: Math.round(b.bottom + 4), left: Math.round(clampedLeft) })
  }

  useLayoutEffect(() => { if (open) place() }, [open])

  // Cerrar en click afuera / escape / scroll / resize (más simple y robusto que
  // reposicionar: el menú es transitorio).
  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (btnRef.current?.contains(e.target)) return
      if (menuRef.current?.contains(e.target)) return
      setOpen(false)
    }
    function onKey(e) { if (e.key === 'Escape') setOpen(false) }
    function onScrollResize() { setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('touchstart', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScrollResize, true)
    window.addEventListener('resize', onScrollResize)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('touchstart', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScrollResize, true)
      window.removeEventListener('resize', onScrollResize)
    }
  }, [open])

  const visibleItems = items.filter(Boolean)
  if (visibleItems.length === 0) return null

  return (
    <>
      <button
        ref={btnRef}
        onClick={() => setOpen(o => !o)}
        className={`p-1 rounded-md transition ${open
          ? 'bg-bg-2 dark:bg-bg-2/60 text-ink-1'
          : 'text-ink-3 hover:text-ink-1 dark:hover:text-ink-0 hover:bg-bg-2 dark:hover:bg-bg-2/40'
        }`}
        title="Más acciones"
        aria-label="Más acciones"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <MoreVertical size={14} />
      </button>

      {open && pos && createPortal(
        <div
          ref={menuRef}
          className="fixed z-[200] min-w-[190px] py-1 bg-white dark:bg-bg-2 border border-line rounded-lg shadow-lg"
          style={{ top: pos.top, left: pos.left }}
          role="menu"
        >
          {visibleItems.map((it, i) => {
            if (it.divider) {
              return <div key={`d-${i}`} className="my-1 border-t border-line/60" />
            }
            return (
              <button
                key={it.label}
                onClick={() => { setOpen(false); it.onClick?.() }}
                disabled={it.disabled}
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left transition disabled:opacity-40 disabled:cursor-not-allowed ${
                  it.danger
                    ? 'text-red-600 dark:text-red-400 hover:bg-red-500/10'
                    : 'text-ink-1 hover:bg-bg-2 dark:hover:bg-bg-2/50'
                }`}
                role="menuitem"
              >
                {it.icon && <span className="flex-shrink-0">{it.icon}</span>}
                <span className="flex-1">{it.label}</span>
              </button>
            )
          })}
        </div>,
        document.body,
      )}
    </>
  )
}
