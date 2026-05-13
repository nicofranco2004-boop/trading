// Watchlist — tickers que el user "sigue" sin tenerlos en portfolio.
//
// Diseño: tabla compacta. Cada row clickeable → AssetQuickView.
// Empty state: explicación + CTA "Buscá un ticker arriba para agregarlo".
//
// V1.5: backend GET/POST/DELETE /api/watchlist
// V2: integrar mini-sparkline 30d en cada row

import { useEffect, useState } from 'react'
import { Star, X, TrendingUp, TrendingDown, Eye } from 'lucide-react'
import { api } from '../../utils/api'
import AssetQuickView from './AssetQuickView'

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(2)}%`
}

function fmtPrice(p) {
  if (p == null) return '—'
  return `US$${p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function Watchlist() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  const [removingSym, setRemovingSym] = useState(null)

  function load() {
    setLoading(true)
    api.get('/watchlist')
      .then(d => setItems(d.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  async function remove(symbol) {
    setRemovingSym(symbol)
    try {
      await api.delete(`/watchlist/${encodeURIComponent(symbol)}`)
      setItems(prev => prev.filter(i => i.symbol !== symbol))
    } catch {
      // silent fail; al cerrar el optimistic refresh lo restaura
      load()
    } finally {
      setRemovingSym(null)
    }
  }

  if (loading) {
    return (
      <section>
        <h2 className="font-display text-sm uppercase tracking-wider text-ink-3 mb-2">
          Watchlist
        </h2>
        <div className="rounded-sm border border-line bg-bg-1 p-3">
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-8 rounded-sm bg-bg-2 animate-pulse" />
            ))}
          </div>
        </div>
      </section>
    )
  }

  return (
    <section>
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="font-display text-sm uppercase tracking-wider text-ink-3">
          Watchlist
        </h2>
        {items.length > 0 && (
          <span className="text-[11px] text-ink-3 font-mono">{items.length} tickers</span>
        )}
      </div>

      {items.length === 0 ? (
        <div className="rounded-sm border border-line bg-bg-1 p-6 text-center">
          <Eye size={20} className="mx-auto mb-2 text-ink-3" strokeWidth={1.5} aria-hidden="true" />
          <p className="text-xs text-ink-2">
            Tu watchlist está vacía. Buscá un ticker arriba y agregalo desde su ficha.
          </p>
        </div>
      ) : (
        <div className="rounded-sm border border-line bg-bg-1 overflow-hidden">
          <ul className="divide-y divide-line/30">
            {items.map(it => {
              const pos = (it.change_pct ?? 0) >= 0
              return (
                <li key={it.symbol} className="flex items-center gap-2 px-3 py-2 hover:bg-bg-2/40 transition-colors">
                  <button
                    onClick={() => setSelected(it.symbol)}
                    className="flex-1 min-w-0 flex items-center gap-3 text-left"
                  >
                    <Star size={11} className="text-rendi-warn flex-shrink-0" fill="currentColor" strokeWidth={1.5} aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-mono text-ink-0">{it.symbol}</div>
                    </div>
                    <div className="text-sm font-mono tabular text-ink-1 min-w-[90px] text-right">
                      {fmtPrice(it.price)}
                    </div>
                    <div className={`text-sm font-mono tabular min-w-[70px] text-right flex items-center justify-end gap-1 ${pos ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                      {pos
                        ? <TrendingUp size={10} strokeWidth={1.75} aria-hidden="true" />
                        : <TrendingDown size={10} strokeWidth={1.75} aria-hidden="true" />}
                      {fmtPct(it.change_pct)}
                    </div>
                  </button>
                  <button
                    onClick={() => remove(it.symbol)}
                    disabled={removingSym === it.symbol}
                    className="text-ink-3 hover:text-rendi-neg p-1 flex-shrink-0 disabled:opacity-40"
                    title="Quitar de watchlist"
                    aria-label="Quitar"
                  >
                    <X size={12} strokeWidth={1.75} />
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {selected && (
        <AssetQuickView symbol={selected} onClose={() => { setSelected(null); load() }} />
      )}
    </section>
  )
}
