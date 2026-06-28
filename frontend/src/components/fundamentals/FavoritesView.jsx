// FavoritesView — vista "Favoritos" de Calidad de cartera.
// ═══════════════════════════════════════════════════════════════════════════
// Reusa la watchlist EXISTENTE del app (GET/POST/DELETE /watchlist + el bus de
// eventos window-level), vía el hook useWatchlist. Filtra a EQUITIES y CEDEARs
// (los únicos con fundamentales). Sin gauge: cada card muestra los dos ejes
// Negocio / Precio, igual que el resto de Calidad de cartera.

import { useState, useEffect } from 'react'
import { Star } from 'lucide-react'
import Panel from '../Panel'
import Pill from '../Pill'
import EmptyState from '../EmptyState'
import Skeleton from '../Skeleton'
import AssetLogo from '../AssetLogo'
import { api } from '../../utils/api'
import { inferType } from '../../utils/tickers'
import StarToggle from './StarToggle'
import { businessQuality, priceRead, AXIS_PILL } from './axes'

const hasFund = (s) => { const t = inferType(s); return t === 'stock_us' || t === 'cedear' }

export default function FavoritesView({ watchlist, onOpenTicker }) {
  const equities = watchlist.symbols.filter(hasFund)
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
        .then(res => { if (!cancelled) setCardData(prev => ({ ...prev, [s]: { loading: false, data: res } })) })
        .catch(() => { if (!cancelled) setCardData(prev => ({ ...prev, [s]: { loading: false, data: null } })) })
    }
    return () => { cancelled = true }
  }, [equities.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  if (watchlist.loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {[0, 1, 2].map(i => <Skeleton key={i} className="h-28 w-full rounded" />)}
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
          description="Tocá la ⭐ en Explorar para seguir una acción o CEDEAR acá. Cripto y bonos no entran — no tienen estados financieros para analizar."
        />
      </Panel>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {equities.map(sym => {
        const entry = cardData[sym]
        const d = entry?.data
        const cats = d?.available ? (d.score?.categories || []) : null
        const neg = cats ? businessQuality(cats) : null
        const prc = cats ? priceRead(cats) : null
        return (
          <Panel key={sym} padding="md" hoverable className="relative">
            <button
              type="button"
              onClick={() => onOpenTicker?.(sym)}
              className="w-full text-left"
              title={`Ver ${sym} en Explorar`}
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
                <div className="flex gap-2"><Skeleton className="h-5 w-20 rounded" /><Skeleton className="h-5 w-20 rounded" /></div>
              ) : cats ? (
                <div className="grid grid-cols-2 gap-3">
                  <AxisMini label="Negocio" read={neg} />
                  <AxisMini label="Precio" read={prc} />
                </div>
              ) : (
                <p className="text-[11px] text-ink-3 py-2">Sin fundamentales</p>
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

function AxisMini({ label, read }) {
  return (
    <div>
      <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1">{label}</p>
      {read ? <Pill tone={AXIS_PILL[read.tone]}>{read.label}</Pill> : <span className="text-[11px] text-ink-3">—</span>}
    </div>
  )
}
