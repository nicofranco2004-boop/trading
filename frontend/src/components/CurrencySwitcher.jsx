import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, Coins } from 'lucide-react'
import { useCurrencyChoice } from '../hooks/useCurrencyChoice'

/**
 * CurrencySwitcher — el selector de moneda GLOBAL, fijo en el chrome de la app.
 * ═════════════════════════════════════════════════════════════════════════════
 * En qué moneda ve el usuario sus números es una decisión que atraviesa TODA la
 * app (state global, persistido). El control, en cambio, vivía repartido: un
 * toggle USD|ARS escondido en la toolbar de Cartera, otro arriba del hero del
 * Dashboard, y el riel de 3 opciones sólo en Configuración → Tipos de cambio.
 * Resultado: en Métricas —donde los números SÍ respetan la preferencia— no había
 * cómo cambiarla, y el que la encontraba en Cartera tenía que volver ahí cada vez.
 *
 * Este componente es la respuesta: UN control, siempre en el mismo lugar de la
 * pantalla, en todas las páginas. Vive en el shell (sidebar en escritorio, barra
 * superior en mobile), nunca dentro de una página.
 *
 * Muestra las 3 opciones del riel (USD MEP · USD CCL · Pesos) con su cotización,
 * usando el mismo modelo que el CurrencyRail de Config (`useCurrencyChoice`).
 *
 * Variantes (`variant`) — cambia el DISPARADOR, el panel es el mismo:
 *   • 'row'  → fila ancha de la sidebar expandida (label + cotización + chevron)
 *   • 'chip' → pastilla compacta de la barra superior mobile ("US$ MEP")
 *   • 'mini' → sidebar colapsada: símbolo y tag apilados en 40px de ancho útil
 *
 * El panel se abre en un PORTAL con position:fixed y z alto: la sidebar es
 * `fixed` con `overflow-y-auto` en la nav y la topbar mobile es sticky — un
 * panel absolute quedaría clipeado o por debajo del contenido.
 *
 * ⚠️ QUÉ PANTALLAS LA RESPETAN — verificado a mano en demo, moneda = Pesos:
 *   • SÍ: Cartera, Dashboard, Movimientos, Métricas → Diagnóstico, las vistas
 *     mobile, y los KPIs de arriba de Métricas → Reportes.
 *   • NO: Métricas → Comportamiento (todas sus cifras) y el detalle del período
 *     de Métricas → Reportes (Capital actual / P&L del mes / la narrativa).
 *     No es un descuido del frontend: esos textos llegan YA FORMATEADOS en USD
 *     desde el backend (`backend/behavioral.py`, `backend/reporting/builder.py`),
 *     así que honrar la preferencia ahí es un cambio de backend, no de acá.
 *
 * El control igual se muestra en todas: la preferencia es una sola y el usuario
 * la cambia desde donde esté. Cuando el backend devuelva números en vez de
 * strings, esas dos pantallas se convierten — la salida NO es esconder el
 * control en algunas páginas, que es justo el problema que este componente vino
 * a resolver.
 */

const PANEL_W = 244

export default function CurrencySwitcher({ variant = 'row', align = 'left', className = '' }) {
  const { options, active, activeOption, rates, pick } = useCurrencyChoice()
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(null)
  const btnRef = useRef(null)
  const panelRef = useRef(null)

  // Posiciona el panel debajo del botón, clampeado al viewport (mismo patrón
  // que ActionMenu: reposicionar en scroll es más frágil que cerrar).
  const place = () => {
    const b = btnRef.current?.getBoundingClientRect()
    if (!b) return
    const raw = align === 'right' ? b.right - PANEL_W : b.left
    const left = Math.min(Math.max(8, raw), window.innerWidth - PANEL_W - 8)
    setPos({ top: Math.round(b.bottom + 6), left: Math.round(left) })
  }

  useLayoutEffect(() => { if (open) place() }, [open])

  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (btnRef.current?.contains(e.target)) return
      if (panelRef.current?.contains(e.target)) return
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

  const rate = rates[active]
  const title = `Moneda: ${activeOption.label}${rate && active !== 'ars' ? ` · ${rate}` : ''}`

  // Props comunes de los 3 disparadores: el ref y el aria son iguales, sólo
  // cambia el contenido. Escritos una vez para que no se desincronicen.
  const btnProps = {
    ref: btnRef,
    type: 'button',
    onClick: () => setOpen(o => !o),
    title,
    'aria-label': `Moneda de valuación: ${activeOption.label}`,
    'aria-haspopup': 'listbox',
    'aria-expanded': open,
  }
  const onCls = 'border-data-violet/40 bg-data-violet/15 text-data-violet'
  const offCls = 'border-line-2 bg-bg-2 text-ink-1 hover:text-ink-0 hover:border-line-3'

  function renderTrigger() {
    if (variant === 'chip') {
      return (
        <button {...btnProps}
          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1.5 text-[11.5px] font-medium select-none transition-colors ${open ? onCls : offCls} ${className}`}
        >
          <span className="tabular">{activeOption.symbol} {activeOption.tag}</span>
          <ChevronDown size={12} strokeWidth={2} aria-hidden="true"
            className={`transition-transform ${open ? 'rotate-180' : ''}`} />
        </button>
      )
    }
    if (variant === 'mini') {
      return (
        <button {...btnProps}
          className={`flex flex-col items-center justify-center rounded-lg border px-1.5 py-1 leading-none select-none transition-colors ${open ? onCls : offCls} ${className}`}
        >
          <span className="text-[11px] font-semibold tabular">{activeOption.symbol}</span>
          <span className="mt-0.5 text-[8.5px] tracking-wide opacity-70">{activeOption.tag}</span>
        </button>
      )
    }
    return (
      <button {...btnProps}
        className={`w-full flex items-center gap-2.5 rounded-xl border px-2.5 py-2 text-left select-none transition-colors ${
          open
            ? 'border-data-violet/40 bg-data-violet/10'
            : 'border-line bg-bg-1 hover:border-line-2 hover:bg-bg-2'
        } ${className}`}
      >
        <Coins size={16} strokeWidth={1.75} aria-hidden="true" className="text-data-violet flex-shrink-0" />
        <span className="flex-1 min-w-0">
          <span className="block text-[13px] font-medium text-ink-0 leading-tight">{activeOption.label}</span>
          <span className="block text-[11px] text-ink-3 leading-tight tabular">{rate || ' '}</span>
        </span>
        <ChevronDown size={14} strokeWidth={2} aria-hidden="true"
          className={`text-ink-3 flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
    )
  }

  return (
    <>
      {renderTrigger()}
      {open && pos && createPortal(
        <div
          ref={panelRef}
          role="listbox"
          aria-label="Moneda de valuación"
          className="fixed z-[200] rounded-xl border border-line-2 bg-bg-2 shadow-lg p-1.5"
          style={{ top: pos.top, left: pos.left, width: PANEL_W }}
        >
          <p className="px-2 pt-1 pb-1.5 text-[11px] text-ink-3">
            En qué moneda ves toda la app
          </p>
          {options.map(o => {
            const on = active === o.key
            return (
              <button
                key={o.key}
                type="button"
                role="option"
                aria-selected={on}
                onClick={() => { pick(o.key); setOpen(false) }}
                className={`w-full flex items-center gap-2 rounded-lg px-2 py-2 text-left transition-colors ${
                  on ? 'bg-data-violet/15 text-data-violet' : 'text-ink-1 hover:bg-bg-3 hover:text-ink-0'
                }`}
              >
                <Check size={14} strokeWidth={2.25} aria-hidden="true"
                  className={on ? 'flex-shrink-0' : 'flex-shrink-0 opacity-0'} />
                <span className="flex-1 min-w-0">
                  <span className="block text-[13px] font-medium leading-tight">{o.label}</span>
                  <span className={`block text-[11px] leading-tight ${on ? 'text-data-violet/70' : 'text-ink-3'}`}>{o.hint}</span>
                </span>
                <span className={`text-[11.5px] tabular flex-shrink-0 ${on ? 'text-data-violet/80' : 'text-ink-3'}`}>
                  {rates[o.key] || ''}
                </span>
              </button>
            )
          })}
        </div>,
        document.body,
      )}
    </>
  )
}
