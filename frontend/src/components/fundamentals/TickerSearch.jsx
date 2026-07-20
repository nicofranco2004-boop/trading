// TickerSearch — autocomplete focalizado para la página Fundamentals.
// ═══════════════════════════════════════════════════════════════════════════
// Distinto de components/home/SearchBar.jsx (que abre un modal/quickview de
// watchlist): este es un input simple que, al elegir un ticker, dispara
// onSelect(symbol) y deja que la página cargue la ficha de fundamentals.
//
// Reusa POPULAR_TICKERS de utils/tickers.js + filtrado por symbol/name.
// Keyboard: ↑↓ navega, ↩ selecciona, ESC cierra.

import { useState, useRef, useEffect, useMemo } from 'react'
import { Search, CornerDownLeft } from 'lucide-react'
import { POPULAR_TICKERS } from '../../utils/tickers'

const MAX_RESULTS = 8

// Etiqueta corta del tipo, para diferenciar visualmente cripto/bono/etc.
const TYPE_LABEL = {
  stock_us: 'Acción US',
  stock_ar: 'Acción AR',
  cedear: 'CEDEAR',
  bond: 'Bono',
  crypto: 'Cripto',
  etf: 'ETF',
}

function filterTickers(q) {
  const query = (q || '').trim().toUpperCase()
  if (!query) {
    // Sin query: sugerimos las acciones US más relevantes (las que tienen
    // fundamentals reales).
    return POPULAR_TICKERS.filter(t => t.type === 'stock_us').slice(0, MAX_RESULTS)
  }
  const starts = []
  const contains = []
  for (const t of POPULAR_TICKERS) {
    const sym = t.symbol.toUpperCase()
    const name = t.name.toUpperCase()
    if (sym.startsWith(query)) starts.push(t)
    else if (sym.includes(query) || name.includes(query)) contains.push(t)
  }
  return [...starts, ...contains].slice(0, MAX_RESULTS)
}

export default function TickerSearch({ onSelect, autoFocus = false }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const inputRef = useRef(null)
  const containerRef = useRef(null)

  const results = useMemo(() => filterTickers(query), [query])

  useEffect(() => {
    if (autoFocus && inputRef.current) inputRef.current.focus()
  }, [autoFocus])

  // Cerrar al click afuera
  useEffect(() => {
    function onDocClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  // Reset highlight cuando cambian resultados
  useEffect(() => { setHighlight(0) }, [query])

  function choose(symbol) {
    setOpen(false)
    setQuery('')
    if (inputRef.current) inputRef.current.blur()
    onSelect?.(symbol)
  }

  function onKeyDown(e) {
    // Enter sin sugerencias: tomar el texto crudo (permite tickers no listados)
    if (e.key === 'Enter') {
      e.preventDefault()
      if (open && results[highlight]) {
        choose(results[highlight].symbol)
      } else {
        const raw = query.trim().toUpperCase()
        if (raw) choose(raw)
      }
      return
    }
    if (!open) {
      if (e.key === 'ArrowDown') { setOpen(true); return }
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlight(h => Math.min(h + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlight(h => Math.max(h - 1, 0))
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="flex items-center gap-2 bg-bg-2 border border-line rounded-xl px-3 py-2.5 focus-within:border-data-violet/60 transition-colors">
        <Search size={16} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Buscá una acción (ej. NVDA, Apple, MELI…)"
          className="flex-1 bg-transparent text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none"
          aria-label="Buscar ticker"
          autoComplete="off"
          spellCheck={false}
        />
        <span className="hidden sm:inline-flex items-center gap-1 text-[10px] font-mono text-ink-3">
          <CornerDownLeft size={11} /> para ver
        </span>
      </div>

      {open && results.length > 0 && (
        <div className="absolute z-30 left-0 right-0 mt-1.5 bg-bg-2 border border-line rounded-lg overflow-hidden">
          {results.map((t, i) => (
            <button
              key={t.symbol}
              type="button"
              onClick={() => choose(t.symbol)}
              onMouseEnter={() => setHighlight(i)}
              className={`w-full flex items-center justify-between gap-3 px-3 py-2 text-left transition-colors ${
                i === highlight ? 'bg-bg-1' : 'hover:bg-bg-1'
              }`}
            >
              <span className="flex items-baseline gap-2 min-w-0">
                <span className="font-mono text-sm font-semibold text-ink-0 tabular">{t.symbol}</span>
                <span className="text-xs text-ink-3 truncate">{t.name}</span>
              </span>
              <span className="text-[12px] text-ink-3 flex-shrink-0 font-medium">
                {TYPE_LABEL[t.type] || t.type}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
