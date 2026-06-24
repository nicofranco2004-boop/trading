// FavoritesView — vista "Favoritos" de Fundamentals.
// ═══════════════════════════════════════════════════════════════════════════
// Reusa la watchlist EXISTENTE del app (GET/POST/DELETE /watchlist + el bus de
// eventos window-level), vía el hook useWatchlist. Filtra a EQUITIES (inferType
// === 'stock_us') porque cripto/bonos/CEDEAR no tienen fundamentales.
//
// Cada card mini: AssetLogo + symbol + company_name + ScoreGauge chico + label.
// Click → abre el ticker en Analizar (?ticker=). Estrella → quita de favoritos.

import { useState, useEffect } from 'react'
import { Star } from 'lucide-react'
import Panel from '../Panel'
import EmptyState from '../EmptyState'
import Skeleton from '../Skeleton'
import AssetLogo from '../AssetLogo'
import { api } from '../../utils/api'
import { inferType } from '../../utils/tickers'
import ScoreGauge from './ScoreGauge'
import StarToggle from './StarToggle'

export default function FavoritesView({ watchlist, onOpenTicker }) {
  // Equities seguidas (solo stock_us → tienen fundamentales).
  const equities = watchlist.symbols.filter(s => inferType(s) === 'stock_us')

  // cardData: { [symbol]: { loading, data } }
  const [cardData, setCardData] = useState({})

  useEffect(() => {
    let cancelled = false
    const missing = equities.filter(s => !cardData[s])
    if (missing.length === 0) return
    setCardData(prev => {
      const next = { ...prev }
      for (const s of missing) next[s] = { loading: true, data: null }
      return next
    })
    for (const s of missing) {
      api.get('/fundamentals/' + encodeURIComponent(s))
        .then(res => {
          if (cancelled) return
          setCardData(prev => ({ ...prev, [s]: { loading: false, data: res } }))
        })
        .catch(() => {
          if (cancelled) return
          setCardData(prev => ({ ...prev, [s]: { loading: false, data: null } }))
        })
    }
    return () => { cancelled = true }
  }, [equities.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  if (watchlist.loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {[0, 1, 2].map(i => <Skeleton key={i} className="h-32 w-full rounded" />)}
      </div>
    )
  }

  if (equities.length === 0) {
    return (
      <Panel padding="lg">
        <EmptyState
          icon={<Star size={20} strokeWidth={1.75} />}
          eyebrow="FAVORITOS"
          title="Todavía no guardaste ninguna acción"
          description="Tocá la ⭐ en Analizar o Comparar para seguir una acción acá. Solo aparecen acciones US — cripto y bonos no tienen fundamentales para puntuar."
        />
      </Panel>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {equities.map(sym => {
        const entry = cardData[sym]
        const d = entry?.data
        const available = d?.available
        return (
          <Panel key={sym} padding="md" hoverable className="relative">
            <button
              type="button"
              onClick={() => onOpenTicker?.(sym)}
              className="w-full text-left"
              title={`Ver ${sym} en Analizar`}
            >
              <div className="flex items-center gap-2 mb-3 pr-7">
                <AssetLogo asset={sym} size={28} />
                <span className="min-w-0">
                  <span className="block font-mono text-sm font-semibold text-ink-0 truncate">{sym}</span>
                  <span className="block text-[11px] text-ink-3 truncate">
                    {d?.company_name || (entry?.loading ? '' : sym)}
                  </span>
                </span>
              </div>

              {entry?.loading ? (
                <div className="flex justify-center py-2">
                  <Skeleton className="h-20 w-20 rounded-full" />
                </div>
              ) : available ? (
                <div className="flex justify-center">
                  <ScoreGauge score={d.score?.overall} label={d.score?.label} size={92} />
                </div>
              ) : (
                <p className="text-[11px] text-ink-3 text-center py-4">Sin fundamentales</p>
              )}
            </button>

            <div className="absolute top-3 right-3">
              <StarToggle active onToggle={() => watchlist.toggle(sym)} size={15} />
            </div>
          </Panel>
        )
      })}
    </div>
  )
}
