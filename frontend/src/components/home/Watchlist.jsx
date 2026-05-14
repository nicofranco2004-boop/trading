// Watchlist — tickers seguidos sin holding (V2).
// Panel denso + DataRow por ticker.

import { useEffect, useState } from 'react'
import { Star, X, TrendingUp, TrendingDown, Eye } from 'lucide-react'
import { api } from '../../utils/api'
import AssetQuickView from './AssetQuickView'
import Panel from '../Panel'
import Eyebrow from '../Eyebrow'
import DataRow from '../DataRow'

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(2)}%`
}

function fmtPrice(p) {
  if (p == null) return '—'
  return p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
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
      load()
    } finally {
      setRemovingSym(null)
    }
  }

  if (loading) {
    return (
      <section>
        <Eyebrow>Watchlist</Eyebrow>
        <div className="mt-2 rounded border border-line bg-bg-1 p-3 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-8 rounded-sm bg-bg-2 animate-pulse" />
          ))}
        </div>
      </section>
    )
  }

  return (
    <section>
      <div className="flex items-baseline justify-between mb-2">
        <Eyebrow>Watchlist</Eyebrow>
        {items.length > 0 && (
          <span className="text-[10px] text-ink-3 font-mono">{items.length} tickers</span>
        )}
      </div>

      {items.length === 0 ? (
        <Panel padding="lg" className="text-center">
          <Eye size={18} className="mx-auto mb-2 text-ink-3" strokeWidth={1.5} aria-hidden="true" />
          <p className="text-xs text-ink-2">
            Tu watchlist está vacía. Buscá un ticker arriba y agregalo desde su ficha.
          </p>
        </Panel>
      ) : (
        <Panel padding="none" className="overflow-hidden">
          <div className="divide-y divide-line/30">
            {items.map(it => {
              const pos = (it.change_pct ?? 0) >= 0
              return (
                <div key={it.symbol} className="flex items-center group">
                  <DataRow
                    density="default"
                    hoverable
                    onClick={() => setSelected(it.symbol)}
                    className="flex-1"
                  >
                    <Star size={11} className="text-rendi-warn flex-shrink-0" fill="currentColor" strokeWidth={1.5} aria-hidden="true" />
                    <DataRow.Cell width={80} mono>
                      <span className="text-ink-0 text-[13px]">{it.symbol}</span>
                    </DataRow.Cell>
                    <DataRow.Cell align="right" mono tabular>
                      US${fmtPrice(it.price)}
                    </DataRow.Cell>
                    <DataRow.Cell align="right" width={80} mono tabular>
                      <span className={`flex items-center justify-end gap-1 ${pos ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                        {pos
                          ? <TrendingUp size={9} strokeWidth={1.75} aria-hidden="true" />
                          : <TrendingDown size={9} strokeWidth={1.75} aria-hidden="true" />}
                        {fmtPct(it.change_pct)}
                      </span>
                    </DataRow.Cell>
                  </DataRow>
                  <button
                    onClick={(e) => { e.stopPropagation(); remove(it.symbol) }}
                    disabled={removingSym === it.symbol}
                    className="text-ink-3 hover:text-rendi-neg p-2 flex-shrink-0 disabled:opacity-40 opacity-0 group-hover:opacity-100 transition-opacity"
                    title="Quitar de watchlist"
                    aria-label="Quitar"
                  >
                    <X size={11} strokeWidth={1.75} />
                  </button>
                </div>
              )
            })}
          </div>
        </Panel>
      )}

      {selected && (
        <AssetQuickView symbol={selected} onClose={() => { setSelected(null); load() }} />
      )}
    </section>
  )
}
