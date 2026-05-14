// SearchBar — buscador denso de tickers (V2).
// ═══════════════════════════════════════════════════════════════════════════
// Estructura del dropdown:
//   ┌─ input + atajos de teclado a la derecha
//   ├─ tabs de filtro por tipo + counter
//   ├─ EN TU PORTFOLIO (si hay match con holdings) — destacado
//   ├─ SUGERIDOS (tickers populares matching)
//   └─ footer con atajos
//
// Sin command palette global (no Cmd+K). Es un buscador inline en el header.
// Keyboard: ↑↓ navega, ↩ abre la ficha, ESC cierra.

import { useState, useEffect, useRef, useMemo } from 'react'
import { Search, X, CornerDownLeft, ArrowUp, ArrowDown, Plus, Check } from 'lucide-react'
import { api } from '../../utils/api'
import AssetQuickView from './AssetQuickView'

// ─── Fallback estático: tickers populares + tipo + meta minimal ──────────────
// `type` matchea las tabs de filtro: stock_us | cedear | bond | crypto | etf
const POPULAR_TICKERS = [
  { symbol: 'AAPL',  name: 'Apple',                   exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'MSFT',  name: 'Microsoft',               exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'NVDA',  name: 'NVIDIA',                  exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'GOOGL', name: 'Alphabet',                exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'AMZN',  name: 'Amazon',                  exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'META',  name: 'Meta',                    exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'TSLA',  name: 'Tesla',                   exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'AMD',   name: 'Advanced Micro Devices',  exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'AVGO',  name: 'Broadcom',                exchange: 'NASDAQ', type: 'stock_us' },
  { symbol: 'TSM',   name: 'Taiwan Semiconductor',    exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'JPM',   name: 'JPMorgan',                exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'V',     name: 'Visa',                    exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'WMT',   name: 'Walmart',                 exchange: 'NYSE',   type: 'stock_us' },
  { symbol: 'BTC',   name: 'Bitcoin',                 exchange: 'CRYPTO', type: 'crypto'   },
  { symbol: 'ETH',   name: 'Ethereum',                exchange: 'CRYPTO', type: 'crypto'   },
  { symbol: 'SOL',   name: 'Solana',                  exchange: 'CRYPTO', type: 'crypto'   },
  { symbol: 'SPY',   name: 'SPDR S&P 500 ETF',        exchange: 'NYSE',   type: 'etf'      },
  { symbol: 'QQQ',   name: 'Invesco Nasdaq 100 ETF',  exchange: 'NASDAQ', type: 'etf'      },
  { symbol: 'VOO',   name: 'Vanguard S&P 500 ETF',    exchange: 'NYSE',   type: 'etf'      },
]

const FILTERS = [
  { id: 'all',      label: 'Todos'       },
  { id: 'stock_us', label: 'Acciones US' },
  { id: 'cedear',   label: 'CEDEARs'     },
  { id: 'bond',     label: 'Bonos'       },
  { id: 'crypto',   label: 'Cripto'      },
  { id: 'etf',      label: 'ETFs'        },
]

// Heurística para inferir tipo a partir de la posición del user (campo `asset`).
function inferType(asset) {
  if (!asset) return 'stock_us'
  const a = asset.toUpperCase()
  // crypto comunes
  if (['BTC', 'ETH', 'SOL', 'USDT', 'USDC', 'BNB', 'XRP', 'ADA', 'DOGE', 'AVAX'].includes(a)) return 'crypto'
  // bonos AR (heurística simple por prefijo letra+número largo)
  if (/^(AL|GD|AE|TX|TY|TZ|S[0-9]|T[0-9]{2})/.test(a)) return 'bond'
  return 'stock_us'
}

function fmtPct(p) {
  if (p == null) return null
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(2)}%`
}

function fmtUsd(v) {
  if (v == null) return null
  return `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
}

export default function SearchBar() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('all')
  const [userHoldings, setUserHoldings] = useState([])
  const [watchlist, setWatchlist] = useState([])
  const [selected, setSelected] = useState(null)
  const [cursor, setCursor] = useState(0)
  const [addingSymbol, setAddingSymbol] = useState(null)
  const inputRef = useRef(null)
  const containerRef = useRef(null)
  const startedAt = useRef(performance.now())

  // ── Fetch posiciones del user (agregadas por símbolo) ─────────────────────
  useEffect(() => {
    api.get('/positions')
      .then(d => {
        const map = new Map()
        for (const p of (d || [])) {
          if (p.is_cash || !p.asset) continue
          const symbol = p.asset.toUpperCase()
          const prev = map.get(symbol)
          const qty = Number(p.quantity || 0)
          const invested = Number(p.invested || 0)
          if (prev) {
            prev.quantity += qty
            prev.invested += invested
          } else {
            map.set(symbol, {
              symbol,
              name: p.asset,
              quantity: qty,
              invested,
              type: inferType(p.asset),
              fromUser: true,
            })
          }
        }
        setUserHoldings(Array.from(map.values()))
      })
      .catch(() => setUserHoldings([]))
  }, [])

  // ── Fetch watchlist actual para hidear "+ WATCHLIST" si ya está ───────────
  useEffect(() => {
    api.get('/watchlist')
      .then(d => setWatchlist((d || []).map(w => (w.symbol || '').toUpperCase())))
      .catch(() => setWatchlist([]))
  }, [])

  // ── Click-outside cierra ───────────────────────────────────────────────────
  useEffect(() => {
    function onClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  // ── Cómputo de resultados ──────────────────────────────────────────────────
  const qUpper = q.trim().toUpperCase()
  const { holdingsMatch, suggestedMatch, totalCount } = useMemo(() => {
    if (!qUpper) return { holdingsMatch: [], suggestedMatch: [], totalCount: 0 }

    const matches = (t) =>
      t.symbol.startsWith(qUpper) ||
      (t.name || '').toUpperCase().includes(qUpper)

    const passFilter = (t) => filter === 'all' || t.type === filter

    const hm = userHoldings.filter(t => matches(t) && passFilter(t))
    const sm = POPULAR_TICKERS
      .filter(t => matches(t) && passFilter(t))
      .filter(t => !hm.some(h => h.symbol === t.symbol))
      .slice(0, 6)

    return { holdingsMatch: hm, suggestedMatch: sm, totalCount: hm.length + sm.length }
  }, [qUpper, filter, userHoldings])

  // Lista plana para navegación por teclado
  const flatResults = useMemo(() => [...holdingsMatch, ...suggestedMatch], [holdingsMatch, suggestedMatch])

  // Reset cursor cuando cambian los resultados
  useEffect(() => {
    setCursor(0)
    startedAt.current = performance.now()
  }, [qUpper, filter])

  const elapsedMs = Math.max(1, Math.round(performance.now() - startedAt.current))

  // ── Actions ────────────────────────────────────────────────────────────────
  function pick(symbol) {
    setSelected(symbol)
    setOpen(false)
    setQ('')
  }

  async function addToWatchlist(symbol) {
    if (!symbol || watchlist.includes(symbol)) return
    setAddingSymbol(symbol)
    try {
      await api.post('/watchlist', { symbol })
      setWatchlist(prev => [...prev, symbol])
    } catch {
      // silent fail; backend ya es idempotente
    } finally {
      setAddingSymbol(null)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') { setOpen(false); return }
    if (!flatResults.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setCursor(c => (c + 1) % flatResults.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setCursor(c => (c - 1 + flatResults.length) % flatResults.length)
    } else if (e.key === 'Enter') {
      const target = flatResults[cursor]
      if (!target) return
      // En holdings → abre ficha. En suggested → agrega a watchlist.
      if (target.fromUser) pick(target.symbol)
      else addToWatchlist(target.symbol)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <>
      <div ref={containerRef} className="relative w-full max-w-[420px]">
        {/* INPUT */}
        <div className="flex items-center gap-2 bg-bg-2 border border-line rounded px-3 py-2 focus-within:border-ink-2 transition-colors">
          <Search size={14} className="text-ink-3 flex-shrink-0" strokeWidth={1.75} aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={q}
            onChange={e => { setQ(e.target.value); setOpen(true) }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
            placeholder="Buscar ticker (NVDA, BTC, AL30…)"
            className="bg-transparent flex-1 outline-none text-sm text-ink-0 placeholder:text-ink-3 min-w-0"
          />
          {q && (
            <button
              onClick={() => { setQ(''); inputRef.current?.focus() }}
              className="text-ink-3 hover:text-ink-0"
              aria-label="Limpiar"
            >
              <X size={12} strokeWidth={1.75} />
            </button>
          )}
        </div>

        {/* DROPDOWN */}
        {open && qUpper.length > 0 && (
          <div className="absolute top-full right-0 mt-1 w-[min(640px,calc(100vw-2rem))] bg-bg-1 border border-line rounded shadow-2xl z-50 overflow-hidden">
            {/* HEADER: filtros + counter */}
            <div className="px-3 py-2 border-b border-line/60 flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-1 flex-wrap">
                {FILTERS.map(f => (
                  <button
                    key={f.id}
                    onClick={() => setFilter(f.id)}
                    className={`text-[10px] font-mono uppercase tracking-caps px-2 py-1 rounded-sm transition-colors ${
                      filter === f.id
                        ? 'bg-bg-3 text-ink-0 border border-line-2'
                        : 'text-ink-3 hover:text-ink-1 border border-transparent'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3 flex-shrink-0">
                {totalCount} {totalCount === 1 ? 'resultado' : 'resultados'} · {elapsedMs}ms
              </span>
            </div>

            {totalCount === 0 ? (
              <div className="px-4 py-6 text-center">
                <p className="text-xs text-ink-2 mb-1">Sin resultados para <span className="font-mono text-ink-0">{qUpper}</span></p>
                <p className="text-[11px] text-ink-3">Probá con el símbolo exacto (ej. "AAPL", "AL30")</p>
              </div>
            ) : (
              <div className="max-h-[480px] overflow-y-auto">
                {/* SECCIÓN: EN TU PORTFOLIO */}
                {holdingsMatch.length > 0 && (
                  <section>
                    <SectionHeader
                      label="En tu portfolio"
                      count={holdingsMatch.length}
                      hint="Posiciones que ya tenés"
                    />
                    <div>
                      {holdingsMatch.map((t, i) => (
                        <ResultRow
                          key={t.symbol}
                          ticker={t}
                          active={cursor === i}
                          highlight
                          onPick={pick}
                          onHover={() => setCursor(i)}
                        />
                      ))}
                    </div>
                  </section>
                )}

                {/* SECCIÓN: SUGERIDOS */}
                {suggestedMatch.length > 0 && (
                  <section className={holdingsMatch.length > 0 ? 'border-t border-line/40' : ''}>
                    <SectionHeader
                      label="Sugeridos"
                      count={suggestedMatch.length}
                      hint="Tickers populares"
                    />
                    <div>
                      {suggestedMatch.map((t, i) => {
                        const idx = holdingsMatch.length + i
                        const inWatchlist = watchlist.includes(t.symbol)
                        return (
                          <ResultRow
                            key={t.symbol}
                            ticker={t}
                            active={cursor === idx}
                            onPick={pick}
                            onHover={() => setCursor(idx)}
                            actionLabel={inWatchlist ? 'EN WATCHLIST' : '+ WATCHLIST'}
                            actionDisabled={inWatchlist || addingSymbol === t.symbol}
                            actionDone={inWatchlist}
                            onAction={() => addToWatchlist(t.symbol)}
                          />
                        )
                      })}
                    </div>
                  </section>
                )}
              </div>
            )}

            {/* FOOTER: atajos */}
            <div className="px-3 py-2 border-t border-line/60 flex items-center gap-4 text-[10px] font-mono uppercase tracking-caps text-ink-3 bg-bg-2/40">
              <Shortcut icon={<><ArrowUp size={9} strokeWidth={2} /><ArrowDown size={9} strokeWidth={2} /></>} label="navegar" />
              <Shortcut icon={<CornerDownLeft size={9} strokeWidth={2} />} label="abrir / agregar" />
              <Shortcut text="ESC" label="cerrar" />
              <span className="ml-auto flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-rendi-pos" aria-hidden="true" />
                feed local · {elapsedMs}ms
              </span>
            </div>
          </div>
        )}
      </div>

      {selected && <AssetQuickView symbol={selected} onClose={() => setSelected(null)} />}
    </>
  )
}

// ─── Subcomponentes ──────────────────────────────────────────────────────────

function SectionHeader({ label, count, hint }) {
  return (
    <div className="px-3 pt-2.5 pb-1 flex items-baseline justify-between gap-3">
      <span className="text-[10px] font-mono uppercase tracking-label text-ink-3">
        {label} <span className="text-ink-2">· {count}</span>
      </span>
      {hint && (
        <span className="text-[10px] text-ink-3 truncate">{hint}</span>
      )}
    </div>
  )
}

function Shortcut({ icon, text, label }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-sm border border-line bg-bg-2 text-ink-2">
        {icon}
        {text}
      </span>
      <span>{label}</span>
    </span>
  )
}

function ResultRow({ ticker, active, highlight, onPick, onHover, actionLabel, actionDisabled, actionDone, onAction }) {
  const initial = (ticker.symbol || '?').slice(0, 1)
  return (
    <div
      onMouseEnter={onHover}
      className={`relative flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-colors ${
        active ? 'bg-bg-2' : 'hover:bg-bg-2/60'
      } ${highlight ? 'border-l-2 border-rendi-pos' : 'border-l-2 border-transparent'}`}
      onClick={() => onPick(ticker.symbol)}
    >
      {/* Avatar */}
      <div className="w-7 h-7 flex-shrink-0 rounded-sm bg-bg-3 border border-line flex items-center justify-center">
        <span className="text-[11px] font-mono text-ink-1">{initial}</span>
      </div>

      {/* Meta */}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-sm font-mono text-ink-0">{ticker.symbol}</span>
          <span className="text-xs text-ink-2 truncate">{ticker.name}</span>
          {ticker.exchange && (
            <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
              · {ticker.exchange}
            </span>
          )}
        </div>
        {ticker.fromUser && (
          <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mt-0.5">
            En posición
            {ticker.quantity > 0 && <> · {ticker.quantity.toLocaleString('es-AR', { maximumFractionDigits: 4 })} {ticker.type === 'crypto' ? 'unid.' : 'acc.'}</>}
            {ticker.invested > 0 && <> · invertido {fmtUsd(ticker.invested)}</>}
          </div>
        )}
      </div>

      {/* Acción */}
      {ticker.fromUser ? (
        <button
          onClick={(e) => { e.stopPropagation(); onPick(ticker.symbol) }}
          className="flex-shrink-0 text-[10px] font-mono uppercase tracking-caps text-ink-2 hover:text-ink-0 border border-line bg-bg-2 hover:bg-bg-3 px-2 py-1 rounded-sm transition-colors"
        >
          Ver posición
        </button>
      ) : onAction ? (
        <button
          onClick={(e) => { e.stopPropagation(); if (!actionDisabled) onAction() }}
          disabled={actionDisabled}
          className={`flex-shrink-0 text-[10px] font-mono uppercase tracking-caps px-2 py-1 rounded-sm border transition-colors inline-flex items-center gap-1 ${
            actionDone
              ? 'border-rendi-pos/30 bg-rendi-pos/10 text-rendi-pos cursor-default'
              : 'border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3'
          }`}
        >
          {actionDone ? <Check size={9} strokeWidth={2.25} /> : <Plus size={9} strokeWidth={2.25} />}
          {actionLabel}
        </button>
      ) : null}
    </div>
  )
}
