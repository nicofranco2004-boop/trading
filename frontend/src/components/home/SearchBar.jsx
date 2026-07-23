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
import AssetLogo from '../AssetLogo'
import AssetTypeBadge from '../AssetTypeBadge'
import AssetQuickView from './AssetQuickView'
import { notifyWatchlistChanged, subscribeWatchlistChanged } from '../../utils/watchlistEvents'
import { POPULAR_TICKERS, CEDEAR_SEARCH, AR_STOCK_SEARCH, US_SEARCH, inferType } from '../../utils/tickers'

// Normaliza el símbolo para resolver el logo: strip sufijo CEDEAR (.BA) para
// reutilizar el logo de la US version; deja todo lo demás intacto.
function logoSymbolFor(symbol) {
  if (!symbol) return symbol
  if (symbol.endsWith('.BA')) return symbol.slice(0, -3)
  return symbol
}

// ─── Universo de tickers + helpers de tipo ───────────────────────────────────
// POPULAR_TICKERS e inferType viven ahora en utils/tickers.js (centralizados
// para que Fundamentals y otras features los reusen sin importar este modal).
// Re-exportados acá para no romper imports existentes.
export { POPULAR_TICKERS, inferType }

export const FILTERS = [
  { id: 'all',      label: 'Todos'        },
  { id: 'stock_us', label: 'Acciones US'  },
  { id: 'stock_ar', label: 'Acciones AR'  },
  { id: 'cedear',   label: 'CEDEARs'      },
  { id: 'bond',     label: 'Bonos'        },
  { id: 'crypto',   label: 'Cripto'       },
  { id: 'etf',      label: 'ETFs'         },
]

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
    function load() {
      api.get('/watchlist')
        .then(d => {
          // El backend devuelve { items: [...] }. Compat con array directo
          // por si algún caller legacy sigue ese shape.
          const items = Array.isArray(d) ? d : (d?.items || [])
          setWatchlist(items.map(w => (w.symbol || '').toUpperCase()))
        })
        .catch(() => setWatchlist([]))
    }
    load()
    // Cuando otro componente cambia la watchlist (MobileSearch, AssetQuickView)
    // refrescamos para que el botón "+ WATCHLIST" refleje el estado actual.
    return subscribeWatchlistChanged(load)
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
  // Si no hay query: mostramos todos los del tab activo (universo curado).
  // Si hay query: filtramos por symbol prefix o name substring.
  const qUpper = q.trim().toUpperCase()
  const { holdingsMatch, suggestedMatch, totalCount } = useMemo(() => {
    const matches = (t) => {
      if (!qUpper) return true
      return (
        t.symbol.toUpperCase().startsWith(qUpper) ||
        (t.name || '').toUpperCase().includes(qUpper)
      )
    }
    const passFilter = (t) => filter === 'all' || t.type === filter

    const hm = userHoldings.filter(t => matches(t) && passFilter(t))
    // Universo de sugeridos: POPULAR_TICKERS (curado, es lo que se ve SIN query).
    // Con query sumamos TODOS los CEDEARs del allowlist (CEDEAR_SEARCH) para que
    // cualquier CEDEAR sea encontrable (antes solo el subset de POPULAR_TICKERS →
    // CAT/HON/etc. no aparecían). Dedup por símbolo; el cap de 8 evita inundar.
    const universe = qUpper
      ? [...POPULAR_TICKERS,
         ...[...CEDEAR_SEARCH, ...AR_STOCK_SEARCH, ...US_SEARCH].filter(c => !POPULAR_TICKERS.some(p => p.symbol === c.symbol))]
      : POPULAR_TICKERS
    const sm = universe
      .filter(t => matches(t) && passFilter(t))
      .filter(t => !hm.some(h => h.symbol === t.symbol))
      .slice(0, qUpper ? 8 : 30) // sin query: hasta 30 para que ETFs/Bonos enteros se vean

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

  // Toggle: si ya está → DELETE; si no → POST. El backend es idempotente en
  // ambos lados, así que duplicar clicks no es problema. Dispara broadcast
  // para que el componente <Watchlist> en /home actualice sin reload.
  async function toggleWatchlist(symbol) {
    if (!symbol) return
    const isIn = watchlist.includes(symbol)
    setAddingSymbol(symbol)
    try {
      if (isIn) {
        await api.delete(`/watchlist/${encodeURIComponent(symbol)}`)
        setWatchlist(prev => prev.filter(s => s !== symbol))
        notifyWatchlistChanged({ symbol, removed: true })
      } else {
        await api.post('/watchlist', { symbol })
        setWatchlist(prev => [...prev, symbol])
        notifyWatchlistChanged({ symbol, added: true })
      }
    } catch {
      // silent fail
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
      else toggleWatchlist(target.symbol)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <>
      <div ref={containerRef} className="relative w-full max-w-[420px]">
        {/* INPUT */}
        <div className="flex items-center gap-2 bg-bg-2 border border-line rounded-xl px-3 py-2 focus-within:border-ink-2 transition-colors">
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
        {open && (
          <div className="absolute top-full right-0 mt-1 w-[min(640px,calc(100vw-2rem))] bg-bg-1 border border-line rounded-xl shadow-2xl z-50 overflow-hidden">
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
              <span className="text-[12.5px] text-ink-2 flex-shrink-0 font-medium">
                {totalCount} {totalCount === 1 ? 'resultado' : 'resultados'} · {elapsedMs}ms
              </span>
            </div>

            {totalCount === 0 ? (
              <div className="px-4 py-6 text-center">
                {qUpper ? (
                  <>
                    <p className="text-xs text-ink-2 mb-1">Sin resultados para <span className="font-mono text-ink-0">{qUpper}</span></p>
                    <p className="text-[11px] text-ink-3">Probá con el símbolo exacto (ej. "AAPL", "AL30", "GGAL")</p>
                  </>
                ) : (
                  <p className="text-[11px] text-ink-3">Sin tickers en esta categoría todavía.</p>
                )}
              </div>
            ) : (
              <div className="max-h-[480px] overflow-y-auto">
                {/* SECCIÓN: EN TU PORTFOLIO */}
                {holdingsMatch.length > 0 && (
                  <section>
                    <SectionHeader
                      label="En tu cartera"
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
                            inWatchlist={inWatchlist}
                            actionDisabled={addingSymbol === t.symbol}
                            onAction={() => toggleWatchlist(t.symbol)}
                          />
                        )
                      })}
                    </div>
                  </section>
                )}
              </div>
            )}

            {/* FOOTER: atajos */}
            <div className="px-3 py-2 border-t border-line/60 flex items-center gap-4 text-[12.5px] text-ink-2 bg-bg-2/40 font-medium">
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
      <span className="text-[12.5px] text-ink-2 font-medium">
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

function ResultRow({ ticker, active, highlight, onPick, onHover, inWatchlist = false, actionDisabled = false, onAction }) {
  return (
    <div
      onMouseEnter={onHover}
      className={`relative flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-colors group ${
        active ? 'bg-bg-2' : 'hover:bg-bg-2/60'
      } ${highlight ? 'border-l-2 border-rendi-pos' : 'border-l-2 border-transparent'}`}
      onClick={() => onPick(ticker.symbol)}
    >
      {/* Logo del activo (cae a iniciales con color hash si no hay archivo) */}
      <AssetLogo asset={logoSymbolFor(ticker.symbol)} size={28} className="flex-shrink-0" />

      {/* Meta */}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-sm font-mono text-ink-0">{ticker.symbol}</span>
          <span className="text-xs text-ink-2 truncate">{ticker.name}</span>
          <AssetTypeBadge type={ticker.type} className="self-center" />
          {ticker.exchange && (
            <span className="text-[12.5px] text-ink-2 font-medium">
              · {ticker.exchange}
            </span>
          )}
        </div>
        {ticker.fromUser && (
          <div className="text-[12.5px] text-ink-2 mt-0.5 font-medium">
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
          className="flex-shrink-0 text-[12px] text-ink-2 hover:text-ink-0 border border-line bg-bg-2 hover:bg-bg-3 px-2 py-1 rounded-sm transition-colors font-medium"
        >
          Ver posición
        </button>
      ) : onAction ? (
        <WatchlistToggleButton
          inWatchlist={inWatchlist}
          disabled={actionDisabled}
          onClick={(e) => { e.stopPropagation(); if (!actionDisabled) onAction() }}
        />
      ) : null}
    </div>
  )
}

// Botón con toggle visual: si NO está en watchlist muestra "+ WATCHLIST",
// si está muestra "✓ EN WATCHLIST" verde y en hover cambia a "× QUITAR" rojo
// para indicar que el click va a removerlo.
function WatchlistToggleButton({ inWatchlist, disabled, onClick }) {
  if (!inWatchlist) {
    return (
      <button
        onClick={onClick}
        disabled={disabled}
        className="flex-shrink-0 text-[12px] px-2 py-1 rounded-sm border border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3 disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-1 font-medium"
      >
        <Plus size={9} strokeWidth={2.25} />
        + Watchlist
      </button>
    )
  }
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title="Quitar de watchlist"
      className="flex-shrink-0 text-[12px] px-2 py-1 rounded-sm border border-rendi-pos/30 bg-rendi-pos/10 text-rendi-pos hover:border-rendi-neg/40 hover:bg-rendi-neg/10 hover:text-rendi-neg disabled:opacity-40 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-1 font-medium"
    >
      <Check size={9} strokeWidth={2.25} className="group-hover:hidden inline-block" />
      <X size={9} strokeWidth={2.25} className="hidden group-hover:inline-block" />
      <span className="group-hover:hidden">En watchlist</span>
      <span className="hidden group-hover:inline">Quitar</span>
    </button>
  )
}
