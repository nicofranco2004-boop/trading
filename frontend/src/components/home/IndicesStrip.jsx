// IndicesStrip — fila horizontal con índices y referentes (S&P, BTC, etc.).
//
// Cada item: label + valor + variación diaria. Cache 15min en backend.
// Compact, scrolleable en mobile, grid en desktop.

import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { api } from '../../utils/api'

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(2)}%`
}

function fmtPrice(p, kind) {
  if (p == null) return '—'
  if (kind === 'crypto') return `US$${p.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
  if (kind === 'commodity') return `US$${p.toFixed(2)}`
  return p.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

export default function IndicesStrip() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let cancelled = false
    api.get('/home/indices')
      .then(d => { if (!cancelled) setItems(d.items || []) })
      .catch(ex => { if (!cancelled) setErr(ex.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  if (loading) {
    return (
      <div className="flex gap-2 overflow-x-auto pb-1">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex-shrink-0 min-w-[140px] h-14 rounded-sm bg-bg-2 animate-pulse" />
        ))}
      </div>
    )
  }
  if (err) {
    return <div className="text-xs text-rendi-neg">No pudimos cargar los índices: {err}</div>
  }

  return (
    <div className="flex gap-2 overflow-x-auto pb-1 -mx-1 px-1">
      {items.map(it => {
        const positive = (it.change_pct ?? 0) >= 0
        return (
          <div
            key={it.symbol}
            className="flex-shrink-0 min-w-[140px] rounded-sm border border-line bg-bg-1 px-3 py-2"
          >
            <div className="text-[10px] uppercase tracking-wider text-ink-3">{it.label}</div>
            <div className="text-sm font-mono tabular text-ink-0 leading-tight">
              {fmtPrice(it.price, it.kind)}
            </div>
            <div className={`flex items-center gap-1 text-[11px] font-mono tabular ${positive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {positive
                ? <TrendingUp size={10} strokeWidth={1.75} aria-hidden="true" />
                : <TrendingDown size={10} strokeWidth={1.75} aria-hidden="true" />}
              {fmtPct(it.change_pct)}
            </div>
          </div>
        )
      })}
    </div>
  )
}
