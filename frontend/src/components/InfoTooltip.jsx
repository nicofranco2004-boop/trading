import { useEffect, useRef, useState } from 'react'
import { HelpCircle } from 'lucide-react'

/**
 * InfoTooltip — small (?) icon that opens a popover with explanation.
 *
 * Designed for "Cómo se calcula" hints on Insights cards. Click to open,
 * click outside or Escape to close. Touch-friendly (no pure-hover).
 *
 * Usage:
 *   <InfoTooltip>
 *     <p>Drawdown = caída desde el máximo histórico.</p>
 *     <p className="text-slate-400">Fórmula: (valor − HWM) / HWM</p>
 *   </InfoTooltip>
 */
export default function InfoTooltip({ children, label = 'Cómo se calcula', size = 13, align = 'right' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

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

  return (
    <span ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={`inline-flex items-center justify-center rounded-full transition ${
          open
            ? 'text-slate-700 dark:text-slate-200'
            : 'text-slate-400 hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300'
        }`}
        title={label}
        aria-label={label}
      >
        <HelpCircle size={size} />
      </button>
      {open && (
        <div
          className={`absolute z-30 top-full mt-1 w-64 px-3 py-2.5 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-lg text-xs leading-relaxed text-slate-700 dark:text-slate-200 space-y-1.5 ${align === 'right' ? 'right-0' : 'left-0'}`}
          role="tooltip"
        >
          {children}
        </div>
      )}
    </span>
  )
}
