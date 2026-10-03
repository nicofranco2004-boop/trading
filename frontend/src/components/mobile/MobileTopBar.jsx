// MobileTopBar — barra superior fija en mobile (Sprint M1, item 05).
// ═══════════════════════════════════════════════════════════════════════════
// Logo a la izquierda; moneda, Rendi AI y búsqueda a la derecha; abajo, la
// cinta de cotizaciones (MarketTicker, la misma que va arriba del contenido en
// la compu) y, abajo de todo, los avisos que le pasa App.jsx (cliente abierto,
// demo, prueba gratis). Sticky para que esté siempre accesible. Por debajo, indicador de
// pull-to-refresh cuando el user tira hacia abajo: refresca también la cinta.

import { useLayoutEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Search, RefreshCcw } from 'lucide-react'
import RendiLogo from '../RendiLogo'
import CurrencySwitcher from '../CurrencySwitcher'
import MarketTicker from '../MarketTicker'
import { refreshMarketIndices } from '../../hooks/useMarketIndices'
import { usePullToRefresh } from '../../hooks/usePullToRefresh'
import { useCoachDrawer } from '../../contexts/CoachDrawerContext'
import { useAuth } from '../../contexts/AuthContext'
import { useAdvisorContext } from '../../contexts/AdvisorContext'
import { menuVisible } from '../../utils/navegacion'
import MervallE from '../ai/MervallE'

// El alto de esta barra (logo, cinta y los avisos: cliente abierto, demo, prueba)
// queda anotado en la variable CSS --alto-barra-celular, y lo leen los que se
// acomodan debajo: las cabeceras que se quedan fijas al bajar (Cartera,
// Movimientos) y la burbuja de Rendi. Antes cada uno tenía escrito a mano
// 88 px; cuando la barra creció (la cinta, la franja del cliente, el notch de
// un iPhone con la app instalada) quedaban tapados detrás. Mismo mecanismo que
// --sidebar-w en la compu.
export const VARIABLE_ALTO_BARRA = '--alto-barra-celular'

// Mide la barra ENTERA (el <header>, con la cinta y los avisos) y lo anota.
// Devuelve cómo deshacerlo: al pasar al armado de compu la barra se desarma, y
// sin barra no hay alto. Separada del hook para poder probarla sin navegador.
export function anotarAltoDeLaBarra(el, raiz, Observador = globalThis.ResizeObserver) {
  const anotar = () => raiz.style.setProperty(VARIABLE_ALTO_BARRA, `${Math.round(el.getBoundingClientRect().height)}px`)
  anotar()
  // Vuelve a medir cuando la barra cambia de alto: aparece la cinta, se abre o
  // se cierra un cliente, llega la barra de la prueba.
  const ro = typeof Observador === 'function' ? new Observador(anotar) : null
  ro?.observe(el)
  return () => { ro?.disconnect(); raiz.style.removeProperty(VARIABLE_ALTO_BARRA) }
}

function useAnotarAlto(ref) {
  useLayoutEffect(() => {
    if (!ref.current) return
    return anotarAltoDeLaBarra(ref.current, document.documentElement)
  }, [ref])
}

export default function MobileTopBar({ onRefresh, children }) {
  const coachDrawer = useCoachDrawer()
  const barraRef = useRef(null)
  useAnotarAlto(barraRef)
  // La lupa busca activos para TU cartera (ficha, empresa, watchlist): el
  // asesor en su nivel no tiene cartera propia, así que no la ve (como el "+").
  const { user } = useAuth()
  const { clientCtx } = useAdvisorContext()
  const { atOwnLevel } = menuVisible({ user, clientCtx })

  const { isPulling, pullDistance, isRefreshing, threshold } = usePullToRefresh({
    onRefresh: async () => {
      await refreshMarketIndices()
      if (typeof onRefresh === 'function') await onRefresh()
    },
  })

  const progress = Math.min(1, pullDistance / threshold)

  return (
    <>
      {/* Pull-to-refresh indicator */}
      {(isPulling || isRefreshing) && (
        <div
          aria-hidden
          className="fixed top-0 left-0 right-0 z-50 flex items-center justify-center pointer-events-none"
          style={{
            height: `${Math.max(40, pullDistance)}px`,
            opacity: Math.max(0.2, progress),
            transition: isRefreshing ? 'opacity 200ms ease' : 'none',
          }}
        >
          <div
            className="flex items-center gap-2 text-data-cyan text-[12px] font-medium"
            style={{ transform: `rotate(${isRefreshing ? 360 : progress * 180}deg)`, transition: isRefreshing ? 'transform 600ms linear infinite' : 'none' }}
          >
            <RefreshCcw size={14} strokeWidth={1.75} className={isRefreshing ? 'animate-spin' : ''} />
          </div>
        </div>
      )}

      <header
        ref={barraRef}
        className="sticky top-0 z-30 bg-bg-0/95 backdrop-blur-md border-b border-line"
        style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}
      >
        <div className="flex items-center justify-between h-16 px-3">
          <Link to="/" className="flex items-center gap-2">
            <RendiLogo size={36} />
            <span className="text-lg font-semibold text-ink-0 tracking-tight">rendi</span>
          </Link>
          <div className="flex items-center gap-1">
            {/* Moneda — el mismo control que la sidebar de escritorio, acá fijo
                en la barra: la preferencia es global y se cambia desde donde
                estés, sin ir a buscarla a la pantalla que la tenga. Alineado a
                la derecha para que el panel no se salga del viewport. */}
            <CurrencySwitcher variant="chip" align="right" className="mr-1" />
            {/* Rendi AI — botón siempre visible para abrir el drawer global */}
            <button
              type="button"
              onClick={() => coachDrawer.open()}
              aria-label="Rendi AI"
              className="p-1.5 rounded-sm text-data-violet hover:bg-data-violet/10 active:bg-data-violet/15 transition-colors"
            >
              <MervallE size={24} forma="head" quieto />
            </button>
            {!atOwnLevel && <Link
              to="/buscar"
              aria-label="Buscar"
              className="p-2 rounded-sm text-ink-2 hover:text-ink-0 hover:bg-bg-2/60 transition-colors"
            >
              <Search size={16} strokeWidth={1.75} />
            </Link>}
          </div>
        </div>

        {/* Cinta de cotizaciones */}
        <MarketTicker className="border-t border-line/30" />

        {/* Los avisos de arriba de todo (cliente abierto, demo, prueba gratis):
            App.jsx los pasa acá para que su alto entre en lo que la barra mide
            (ver components/mobile/avisos.js). */}
        {children}
      </header>
    </>
  )
}
