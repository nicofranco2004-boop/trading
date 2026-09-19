import { useEffect, useLayoutEffect, useRef, useState } from 'react'
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
 *     <p className="text-ink-3">Fórmula: (valor − HWM) / HWM</p>
 *   </InfoTooltip>
 *
 * `align`: 'right' (default, el globo crece hacia la izquierda del ícono) |
 * 'left' | 'center'. Usá 'center' cuando el ícono queda en el medio de una
 * columna angosta: con 'right' el globo mide 256px hacia un solo lado y se
 * escapa del contenedor (y de la pantalla, en mobile).
 *
 * ⚠️ El `align` es la INTENCIÓN, no la última palabra: elegir bien el lado
 * depende de dónde caiga el ícono, y eso cambia con el ancho de la pantalla.
 * Un `align` que en la compu queda perfecto puede tirar el globo fuera del
 * teléfono — medido: el (?) de "¿movió la plata?" quedaba en x=297 de 375 y el
 * globo (256px hacia la derecha) se cortaba en TODAS sus líneas. Por eso, si el
 * globo se saldría de la pantalla, se corre lo justo para entrar. Sólo se mueve
 * el que se iba a salir: los que ya entraban quedan exactamente donde estaban.
 */
export default function InfoTooltip({ children, label = 'Cómo se calcula', size = 13, align = 'right', side = 'bottom' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const globoRef = useRef(null)
  // Corrimiento horizontal para que el globo entre en la pantalla. Va por
  // `marginLeft` y no por `transform`: la variante 'center' ya usa
  // `-translate-x-1/2`, y un transform inline la pisaría.
  const [corrimiento, setCorrimiento] = useState(0)
  const corrimientoRef = useRef(0)

  useLayoutEffect(() => {
    if (!open) {
      corrimientoRef.current = 0
      setCorrimiento(0)
      return
    }
    const acomodar = () => {
      const el = globoRef.current
      if (!el) return
      const MARGEN = 8
      const r = el.getBoundingClientRect()
      // La posición SIN el corrimiento ya aplicado, para no acumular.
      const izq = r.left - corrimientoRef.current
      const der = r.right - corrimientoRef.current
      let d = 0
      if (der > window.innerWidth - MARGEN) d = (window.innerWidth - MARGEN) - der
      if (izq + d < MARGEN) d = MARGEN - izq
      d = Math.round(d)
      if (d !== corrimientoRef.current) {
        corrimientoRef.current = d
        setCorrimiento(d)
      }
    }
    acomodar()
    window.addEventListener('resize', acomodar)
    return () => window.removeEventListener('resize', acomodar)
  }, [open, children])

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
            ? 'text-ink-1'
            : 'text-ink-3 hover:text-ink-2 dark:hover:text-ink-1'
        }`}
        title={label}
        aria-label={label}
      >
        <HelpCircle size={size} />
      </button>
      {open && (
        <div
          ref={globoRef}
          style={corrimiento ? { marginLeft: corrimiento } : undefined}
          className={`absolute z-30 w-64 max-w-[80vw] px-3 py-2.5 rounded-lg bg-bg-1 border border-line shadow-lg text-xs leading-relaxed text-ink-1 space-y-1.5 ${
            align === 'center' ? 'left-1/2 -translate-x-1/2'
              : align === 'right' ? 'right-0' : 'left-0'
          } ${side === 'top' ? 'bottom-full mb-1' : 'top-full mt-1'}`}
          role="tooltip"
        >
          {children}
        </div>
      )}
    </span>
  )
}
