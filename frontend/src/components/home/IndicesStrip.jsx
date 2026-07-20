// IndicesStrip — strip horizontal de índices (clean pass 2026-07).
// Cards con gap y aire: label sans + valor grande tabular + delta con flecha.

import { useEffect, useState } from 'react'
import { api } from '../../utils/api'

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(2)}%`
}

function fmtPrice(p, kind) {
  if (p == null) return '—'
  if (kind === 'crypto') return p.toLocaleString('en-US', { maximumFractionDigits: 0 })
  if (kind === 'commodity') return p.toFixed(2)
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
      <div className="rounded border border-line bg-bg-1">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 divide-x divide-y sm:divide-y-0 divide-line">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-16 p-3">
              <div className="h-2 w-12 rounded-sm bg-bg-3 animate-pulse mb-2" />
              <div className="h-4 w-20 rounded-sm bg-bg-3 animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    )
  }
  if (err) {
    return <div className="text-xs text-rendi-neg">No pudimos cargar los índices: {err}</div>
  }

  // Clean pass 2026-07: cards con gap (antes: grilla con hairlines divide-x,
  // look planilla). Label sans, número grande, variación con flecha.
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {items.map(it => {
        const positive = (it.change_pct ?? 0) >= 0
        return (
          <div key={it.symbol} className="rounded-xl border border-line bg-bg-1 px-4 py-3.5">
            <div className="text-[12.5px] text-ink-2 font-medium leading-tight">{it.label}</div>
            <div className="mt-2 text-[19px] font-semibold text-ink-0 num tabular leading-none">
              {fmtPrice(it.price, it.kind)}
            </div>
            <div className={`mt-1.5 text-[12.5px] font-semibold tabular num ${positive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {positive ? '▲ ' : '▼ '}{fmtPct(it.change_pct)}
            </div>
          </div>
        )
      })}
    </div>
  )
}
