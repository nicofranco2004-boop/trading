// MobileTopBar — barra superior fija en mobile (Sprint M1, item 05).
// ═══════════════════════════════════════════════════════════════════════════
// Audit: ticker bar superior (mini-strip de cotizaciones) + logo a la izq +
// search icon a la derecha. Sticky para que esté siempre accesible.
// Por debajo, indicador de pull-to-refresh cuando el user tira hacia abajo.
//
// Ticker bar: scroll horizontal con 4-5 índices clave (S&P, Nasdaq, MERVAL,
// Blue, BTC). Se actualiza con el mismo endpoint /indices del Home.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, RefreshCcw } from 'lucide-react'
import RendiLogo from '../RendiLogo'
import { api } from '../../utils/api'
import { usePullToRefresh } from '../../hooks/usePullToRefresh'

const TICKER_KEYS = ['^GSPC', '^IXIC', 'MERVAL', 'BLUE', 'BTC-USD']
const TICKER_LABELS = {
  '^GSPC': 'S&P',
  '^IXIC': 'NDQ',
  'MERVAL': 'MERVAL',
  'BLUE': 'BLUE',
  'BTC-USD': 'BTC',
}

export default function MobileTopBar({ onRefresh }) {
  const [items, setItems] = useState([])

  useEffect(() => { loadTickers() }, [])

  async function loadTickers() {
    try {
      const data = await api.get('/home/indices')
      setItems(data?.items || [])
    } catch { /* silent */ }
  }

  const { isPulling, pullDistance, isRefreshing, threshold } = usePullToRefresh({
    onRefresh: async () => {
      await loadTickers()
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
            className="flex items-center gap-2 text-data-cyan text-[10px] font-mono uppercase tracking-caps"
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
        <div className="flex items-center justify-between h-12 px-3">
          <Link to="/" className="flex items-center gap-1.5">
            <RendiLogo size={18} />
            <span className="text-sm font-semibold text-ink-0 tracking-tight">rendi</span>
          </Link>
          <Link
            to="/?action=search"
            aria-label="Buscar"
            className="p-2 rounded-sm text-ink-2 hover:text-ink-0 hover:bg-bg-2/60 transition-colors"
          >
            <Search size={16} strokeWidth={1.75} />
          </Link>
        </div>

        {/* Ticker bar */}
        {items.length > 0 && (
          <div className="overflow-x-auto scrollbar-none border-t border-line/30">
            <ul className="flex items-center gap-4 px-3 py-1.5 whitespace-nowrap">
              {items.slice(0, 6).map((it, i) => {
                const sym = it.symbol || it.key || i
                const label = TICKER_LABELS[sym] || (it.label || sym)
                const change = Number(it.change_pct ?? it.changePct ?? 0)
                const positive = change >= 0
                return (
                  <li key={sym} className="flex items-center gap-1.5 text-[10px] font-mono">
                    <span className="text-ink-3 uppercase tracking-caps">{label}</span>
                    <span className={positive ? 'text-rendi-pos tabular' : 'text-rendi-neg tabular'}>
                      {positive ? '+' : '−'}{Math.abs(change).toFixed(2)}%
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </header>
    </>
  )
}
