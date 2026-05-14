import { useEffect, useRef, useState } from 'react'
import { MoreVertical } from 'lucide-react'

/**
 * ActionMenu — three-dot menu for table rows.
 * Replaces multiple icon buttons with a clean popover.
 *
 * Usage:
 *   <ActionMenu items={[
 *     { label: 'Editar', onClick: () => ..., icon: <Pencil size={13} /> },
 *     { label: 'Eliminar', onClick: () => ..., danger: true, icon: <Trash2 size={13} /> },
 *   ]} />
 */
export default function ActionMenu({ items = [], align = 'right' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  // Close on outside click / escape
  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    function onKey(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const visibleItems = items.filter(Boolean)
  if (visibleItems.length === 0) return null

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className={`p-1 rounded-md transition ${open
          ? 'bg-bg-2 dark:bg-bg-2/60 text-ink-1'
          : 'text-ink-3 hover:text-ink-1 dark:hover:text-ink-0 hover:bg-bg-2 dark:hover:bg-bg-2/40'
        }`}
        title="Más acciones"
        aria-label="Más acciones"
      >
        <MoreVertical size={14} />
      </button>

      {open && (
        <div
          className={`absolute z-30 mt-1 min-w-[180px] py-1 bg-white dark:bg-bg-2 border border-line rounded-lg shadow-lg ${align === 'right' ? 'right-0' : 'left-0'}`}
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
        </div>
      )}
    </div>
  )
}
