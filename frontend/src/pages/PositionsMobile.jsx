// PositionsMobile — lista densa 1-col (Sprint M1, item 02 del audit).
// ═══════════════════════════════════════════════════════════════════════════
// Audit: misma data que la tabla desktop, pero una columna:
//   avatar + ticker + meta (izq) · sparkline 30d (centro) · precio + Δ (der)
// Header sticky con "ordenar por" mono caps.
//
// Swipe izq con acciones rápidas (operar / ocultar / watchlist) viene en M3.
// Tap por ahora navega a /posiciones (vista desktop / detail pendiente M3).

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDownUp, Search } from 'lucide-react'
import AssetLogo from '../components/AssetLogo'
import LazySparkline from '../components/LazySparkline'
import { api } from '../utils/api'
import { fmtUsd, ars, pctSigned, colorClass } from '../utils/format'

const SORT_OPTIONS = [
  { id: 'value',  label: 'Valor' },
  { id: 'pnl',    label: 'P&L %' },
  { id: 'alpha',  label: 'A-Z' },
]

export default function PositionsMobile() {
  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [dolar, setDolar] = useState(null)
  const [loading, setLoading] = useState(true)
  const [sortBy, setSortBy] = useState('value')
  const [query, setQuery] = useState('')

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    try {
      const [pos, bkrs, dol] = await Promise.all([
        api.get('/positions').catch(() => []),
        api.get('/brokers').catch(() => []),
        api.get('/dolar').catch(() => null),
      ])
      setPositions(pos || [])
      setBrokers(bkrs || [])
      setDolar(dol)
      await loadPrices(pos || [], bkrs || [])
    } finally {
      setLoading(false)
    }
  }

  async function loadPrices(pos, bkrs) {
    const arsBrokers = new Set(bkrs.filter(b => b.currency === 'ARS').map(b => b.name))
    const usdtBrokers = new Set(bkrs.filter(b => b.currency !== 'ARS').map(b => b.name))
    const arsSyms = [...new Set(pos.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => p.asset + '.BA'))]
    const usdtSyms = [...new Set(pos.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => p.asset))]
    const all = [...arsSyms, ...usdtSyms].join(',')
    if (!all) return
    try { setPrices(await api.get(`/prices?symbols=${all}`)) } catch { /* silent */ }
  }

  const tcBlue = dolar?.blue?.venta || 1415
  const arsBrokerSet = useMemo(
    () => new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name)),
    [brokers]
  )

  // Enriquecemos cada posición con su valor USD y P&L %.
  const enriched = useMemo(() => {
    return positions.map(p => {
      const isAR = arsBrokerSet.has(p.broker)
      const qty = p.quantity || 0
      const invested = p.invested || 0
      let valueUsd = 0
      let priceLocal = null
      if (p.is_cash) {
        valueUsd = isAR ? invested / tcBlue : invested
        priceLocal = null
      } else if (isAR) {
        priceLocal = p.price_override ?? prices[p.asset + '.BA']
        if (priceLocal) valueUsd = (priceLocal * qty) / tcBlue
        else valueUsd = invested / tcBlue
      } else {
        priceLocal = p.price_override ?? prices[p.asset]
        if (priceLocal) valueUsd = priceLocal * qty
        else valueUsd = invested
      }
      const investedUsd = isAR && !p.is_cash ? invested / tcBlue : invested
      const pnlUsd = valueUsd - investedUsd
      const pnlPct = investedUsd > 0 ? pnlUsd / investedUsd : 0
      return { ...p, valueUsd, priceLocal, pnlUsd, pnlPct, isAR }
    })
  }, [positions, prices, arsBrokerSet, tcBlue])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    let list = q
      ? enriched.filter(p => (p.asset || '').toLowerCase().includes(q) || (p.broker || '').toLowerCase().includes(q))
      : enriched
    list = [...list]
    switch (sortBy) {
      case 'pnl':   list.sort((a, b) => (b.pnlPct || 0) - (a.pnlPct || 0)); break
      case 'alpha': list.sort((a, b) => (a.asset || '').localeCompare(b.asset || '')); break
      case 'value':
      default:      list.sort((a, b) => (b.valueUsd || 0) - (a.valueUsd || 0))
    }
    return list
  }, [enriched, sortBy, query])

  const total = enriched.reduce((s, p) => s + (p.valueUsd || 0), 0)

  if (loading) {
    return (
      <div className="px-4 py-8 text-center text-ink-3 text-sm" aria-live="polite">
        Cargando posiciones…
      </div>
    )
  }

  return (
    <div className="pb-8">
      {/* Header con total + sort */}
      <header className="sticky top-[88px] z-20 bg-bg-0/95 backdrop-blur-md border-b border-line/40 px-4 pt-3 pb-2">
        <div className="flex items-baseline justify-between mb-2">
          <div>
            <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none mb-1">
              Cartera total
            </div>
            <div className="text-xl font-medium tabular text-ink-0 leading-none">
              ${Math.round(total).toLocaleString('en-US')}
              <span className="text-xs text-ink-3 ml-1 font-normal">USD</span>
            </div>
          </div>
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
            {filtered.length} {filtered.length === 1 ? 'pos' : 'pos'}
          </span>
        </div>

        {/* Search input compacto */}
        <div className="relative mb-2">
          <Search size={12} strokeWidth={1.75} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar ticker o broker…"
            className="w-full bg-bg-2 border border-line/40 rounded-sm pl-7 pr-3 py-1.5 text-xs text-ink-0 placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-rendi-accent/40"
          />
        </div>

        {/* Sort segmented */}
        <div className="flex items-center gap-1.5">
          <ArrowDownUp size={11} strokeWidth={1.75} className="text-ink-3" />
          <div className="inline-flex bg-bg-2 p-0.5 rounded-sm">
            {SORT_OPTIONS.map(o => (
              <button
                key={o.id}
                onClick={() => setSortBy(o.id)}
                className={`px-2 py-0.5 text-[10px] font-mono uppercase tracking-caps rounded-sm transition-colors ${
                  sortBy === o.id ? 'bg-bg-3 text-ink-0' : 'text-ink-3 hover:text-ink-1'
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {/* Lista densa */}
      {filtered.length === 0 ? (
        <div className="px-4 py-10 text-center text-sm text-ink-3">
          {query ? 'No encontramos coincidencias.' : 'No tenés posiciones cargadas.'}
        </div>
      ) : (
        <ul className="divide-y divide-line/30">
          {filtered.map(p => (
            <PositionRow key={`${p.broker}:${p.asset}:${p.id || p.entry_date}`} p={p} />
          ))}
        </ul>
      )}
    </div>
  )
}

// ─── Row ──────────────────────────────────────────────────────────────────

function PositionRow({ p }) {
  const positive = (p.pnlPct || 0) >= 0
  const cur = p.isAR ? 'ARS' : 'USD'
  const priceFmt = p.priceLocal != null
    ? (p.isAR ? `${ars(p.priceLocal)} ARS` : `$${p.priceLocal.toLocaleString('en-US', { maximumFractionDigits: 2 })}`)
    : null
  return (
    <Link
      to={`/posiciones#${p.id || ''}`}
      className="flex items-center gap-3 px-4 py-3 hover:bg-bg-2/30 active:bg-bg-3 transition-colors"
    >
      <AssetLogo asset={p.asset} isCash={!!p.is_cash} size={32} />

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className="text-sm font-semibold text-ink-0 leading-none truncate">
            {p.asset}
          </span>
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none">
            {p.broker}
          </span>
        </div>
        <div className="text-[11px] font-mono text-ink-3 leading-none mt-1.5 truncate">
          {p.is_cash ? 'Cash' : `${formatQty(p.quantity)} · ${cur}`}
        </div>
      </div>

      {!p.is_cash && (
        <div className="hidden xs:block flex-shrink-0">
          <LazySparkline
            symbol={p.isAR ? `${p.asset}.BA` : p.asset}
            variant="row"
          />
        </div>
      )}

      <div className="flex-shrink-0 text-right min-w-[78px]">
        <div className="text-sm font-medium tabular text-ink-0 leading-none">
          ${Math.round(p.valueUsd).toLocaleString('en-US')}
        </div>
        <div className={`text-[11px] font-mono tabular leading-none mt-1.5 ${colorClass(p.pnlPct)}`}>
          {pctSigned(p.pnlPct)}
        </div>
      </div>
    </Link>
  )
}

function formatQty(q) {
  if (q == null || isNaN(q)) return '—'
  if (Math.abs(q) >= 1000) return Math.round(q).toLocaleString('en-US')
  if (Math.abs(q) >= 1) return q.toFixed(2).replace(/\.00$/, '')
  return q.toFixed(4)
}
