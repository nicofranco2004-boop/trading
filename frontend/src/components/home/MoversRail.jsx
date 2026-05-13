// MoversRail — top gainers / top losers del día (S&P top 50).
// Dos columnas lado a lado, mobile-friendly (stack vertical en mobile).

import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { api } from '../../utils/api'
import AssetQuickView from './AssetQuickView'

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(2)}%`
}

function Row({ item, onClick }) {
  const pos = item.change_pct >= 0
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between gap-2 px-3 py-2 hover:bg-bg-3/40 transition-colors rounded-sm text-left"
    >
      <div className="min-w-0">
        <div className="text-sm font-medium text-ink-1 truncate">{item.symbol}</div>
        <div className="text-[10px] text-ink-3 truncate">{item.name}</div>
      </div>
      <div className={`text-sm font-mono tabular ${pos ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
        {fmtPct(item.change_pct)}
      </div>
    </button>
  )
}

export default function MoversRail({ market = "sp500" }) {
  const [data, setData] = useState({ gainers: [], losers: [] })
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    let cancelled = false
    api.get(`/home/movers?market=${market}`)
      .then(d => { if (!cancelled) setData(d) })
      .catch(ex => { if (!cancelled) setErr(ex.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [market])

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="h-48 rounded-sm bg-bg-2 animate-pulse" />
        <div className="h-48 rounded-sm bg-bg-2 animate-pulse" />
      </div>
    )
  }
  if (err) return <div className="text-xs text-rendi-neg">Sin movers: {err}</div>

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="rounded-sm border border-line bg-bg-1 overflow-hidden">
          <div className="px-3 py-2 border-b border-line/40 flex items-center gap-2">
            <TrendingUp size={13} className="text-rendi-pos" strokeWidth={1.75} aria-hidden="true" />
            <span className="text-xs uppercase tracking-wider text-ink-2">Más suben</span>
          </div>
          <div className="divide-y divide-line/30">
            {(data.gainers || []).map(g => (
              <Row key={g.symbol} item={g} onClick={() => setSelected(g)} />
            ))}
          </div>
        </div>
        <div className="rounded-sm border border-line bg-bg-1 overflow-hidden">
          <div className="px-3 py-2 border-b border-line/40 flex items-center gap-2">
            <TrendingDown size={13} className="text-rendi-neg" strokeWidth={1.75} aria-hidden="true" />
            <span className="text-xs uppercase tracking-wider text-ink-2">Más bajan</span>
          </div>
          <div className="divide-y divide-line/30">
            {(data.losers || []).map(l => (
              <Row key={l.symbol} item={l} onClick={() => setSelected(l)} />
            ))}
          </div>
        </div>
      </div>
      {selected && (
        <AssetQuickView symbol={selected.symbol} onClose={() => setSelected(null)} />
      )}
    </>
  )
}
