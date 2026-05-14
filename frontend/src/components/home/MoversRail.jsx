// MoversRail — top gainers / top losers (V2).
// Dos columnas con DataRow denso. Eyebrows uppercase mono. Sin cards anidadas.

import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'
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

function MoverList({ items, tone, icon: Icon, label, onSelect }) {
  return (
    <Panel padding="none" className="overflow-hidden">
      <div className="px-3 py-2 border-b border-line flex items-center gap-2">
        <Icon size={12} className={tone === 'pos' ? 'text-rendi-pos' : 'text-rendi-neg'} strokeWidth={1.75} aria-hidden="true" />
        <Eyebrow tone={tone === 'pos' ? 'signal' : 'red'}>{label}</Eyebrow>
      </div>
      <div className="divide-y divide-line/30">
        {items.map(it => {
          const pos = (it.change_pct ?? 0) >= 0
          return (
            <DataRow key={it.symbol} density="compact" hoverable onClick={() => onSelect(it)}>
              <DataRow.Cell width={64} mono>
                <span className="text-ink-0 text-[13px]">{it.symbol}</span>
              </DataRow.Cell>
              <DataRow.Cell muted className="text-[11px]">
                {it.name}
              </DataRow.Cell>
              <DataRow.Cell align="right" width={70} mono tabular>
                <span className={pos ? 'text-rendi-pos' : 'text-rendi-neg'}>
                  {fmtPct(it.change_pct)}
                </span>
              </DataRow.Cell>
            </DataRow>
          )
        })}
      </div>
    </Panel>
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
        <div className="h-48 rounded bg-bg-1 border border-line animate-pulse" />
        <div className="h-48 rounded bg-bg-1 border border-line animate-pulse" />
      </div>
    )
  }
  if (err) return <div className="text-xs text-rendi-neg">Sin movers: {err}</div>

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <MoverList
          items={data.gainers || []}
          tone="pos"
          icon={TrendingUp}
          label="Más suben"
          onSelect={setSelected}
        />
        <MoverList
          items={data.losers || []}
          tone="neg"
          icon={TrendingDown}
          label="Más bajan"
          onSelect={setSelected}
        />
      </div>
      {selected && (
        <AssetQuickView symbol={selected.symbol} onClose={() => setSelected(null)} />
      )}
    </>
  )
}
