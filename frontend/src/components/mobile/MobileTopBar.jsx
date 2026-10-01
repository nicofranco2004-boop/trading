// MobileTopBar — barra superior fija en mobile (Sprint M1, item 05).
// ═══════════════════════════════════════════════════════════════════════════
// Logo a la izquierda; moneda, Rendi AI y búsqueda a la derecha; abajo, la
// cinta de cotizaciones (MarketTicker, la misma que va arriba del contenido en
// la compu) y, si el asesor abrió un cliente, la franja "Estás viendo la cuenta
// de…". Sticky para que esté siempre accesible. Por debajo, indicador de
// pull-to-refresh cuando el user tira hacia abajo: refresca también la cinta.

import { Link } from 'react-router-dom'
import { Search, RefreshCcw, Sparkles } from 'lucide-react'
import RendiLogo from '../RendiLogo'
import CurrencySwitcher from '../CurrencySwitcher'
import MarketTicker from '../MarketTicker'
import ClientContextBar from '../advisor/ClientContextBar'
import { refreshMarketIndices } from '../../hooks/useMarketIndices'
import { usePullToRefresh } from '../../hooks/usePullToRefresh'
import { useCoachDrawer } from '../../contexts/CoachDrawerContext'

export default function MobileTopBar({ onRefresh }) {
  const coachDrawer = useCoachDrawer()

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
              className="p-2 rounded-sm text-data-violet hover:bg-data-violet/10 active:bg-data-violet/15 transition-colors"
            >
              <Sparkles size={16} strokeWidth={1.75} />
            </button>
            <Link
              to="/buscar"
              aria-label="Buscar"
              className="p-2 rounded-sm text-ink-2 hover:text-ink-0 hover:bg-bg-2/60 transition-colors"
            >
              <Search size={16} strokeWidth={1.75} />
            </Link>
          </div>
        </div>

        {/* Cinta de cotizaciones */}
        <MarketTicker className="border-t border-line/30" />

        {/* "Estás viendo la cuenta de…" (sólo con un cliente abierto): acá
            adentro queda siempre a la vista, debajo de la cinta, mida lo que
            mida la barra. */}
        <ClientContextBar enLaBarra />
      </header>
    </>
  )
}
