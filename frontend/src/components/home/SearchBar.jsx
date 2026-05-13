// SearchBar — buscador global de activos (header del Home).
//
// V1: autocomplete simple contra:
//   1. Tickers que el user YA tiene en posiciones (más relevante).
//   2. Top S&P 500 + cripto top 10 (fallback).
// Al seleccionar → abre AssetQuickView.
//
// V2: backend index con búsqueda fuzzy.

import { useState, useEffect, useRef } from 'react'
import { Search, X } from 'lucide-react'
import { api } from '../../utils/api'
import AssetQuickView from './AssetQuickView'

// Lista fallback de tickers populares para autocomplete cuando no hay match
// en los holdings del user. Subset chico para no inflar el bundle.
const POPULAR_TICKERS = [
  { symbol: 'AAPL',  name: 'Apple' },
  { symbol: 'MSFT',  name: 'Microsoft' },
  { symbol: 'NVDA',  name: 'NVIDIA' },
  { symbol: 'GOOGL', name: 'Alphabet' },
  { symbol: 'AMZN',  name: 'Amazon' },
  { symbol: 'META',  name: 'Meta' },
  { symbol: 'TSLA',  name: 'Tesla' },
  { symbol: 'JPM',   name: 'JPMorgan' },
  { symbol: 'V',     name: 'Visa' },
  { symbol: 'WMT',   name: 'Walmart' },
  { symbol: 'BTC',   name: 'Bitcoin' },
  { symbol: 'ETH',   name: 'Ethereum' },
  { symbol: 'SPY',   name: 'S&P 500 ETF' },
  { symbol: 'QQQ',   name: 'Nasdaq 100 ETF' },
  { symbol: 'VOO',   name: 'Vanguard S&P 500' },
]

export default function SearchBar() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [userTickers, setUserTickers] = useState([])
  const [selected, setSelected] = useState(null)
  const inputRef = useRef(null)
  const containerRef = useRef(null)

  // Fetch los tickers del user una vez
  useEffect(() => {
    api.get('/positions')
      .then(d => {
        const tickers = [...new Set(
          (d || [])
            .filter(p => !p.is_cash && p.asset)
            .map(p => ({ symbol: p.asset.toUpperCase(), name: p.asset, fromUser: true }))
        )]
        // dedupe por symbol
        const seen = new Set()
        const unique = []
        for (const t of tickers) {
          if (!seen.has(t.symbol)) { seen.add(t.symbol); unique.push(t) }
        }
        setUserTickers(unique)
      })
      .catch(() => setUserTickers([]))
  }, [])

  // Click-outside: cierra dropdown
  useEffect(() => {
    function onClick(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  // Filtrado: priorizamos holdings del user, después populares
  const qUpper = q.trim().toUpperCase()
  let results = []
  if (qUpper.length > 0) {
    const userMatches = userTickers.filter(t =>
      t.symbol.startsWith(qUpper) || t.name.toUpperCase().includes(qUpper)
    )
    const popularMatches = POPULAR_TICKERS.filter(t =>
      (t.symbol.startsWith(qUpper) || t.name.toUpperCase().includes(qUpper))
      && !userMatches.some(u => u.symbol === t.symbol)
    )
    results = [...userMatches, ...popularMatches].slice(0, 8)
  }

  function pick(sym) {
    setSelected(sym)
    setOpen(false)
    setQ('')
  }

  return (
    <>
      <div ref={containerRef} className="relative">
        <div className="flex items-center gap-2 bg-bg-2 border border-line rounded-sm px-3 py-2 min-w-[280px] focus-within:border-ink-2 transition-colors">
          <Search size={14} className="text-ink-3 flex-shrink-0" strokeWidth={1.75} aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={q}
            onChange={e => { setQ(e.target.value); setOpen(true) }}
            onFocus={() => setOpen(true)}
            onKeyDown={e => {
              if (e.key === 'Enter' && qUpper && results.length > 0) pick(results[0].symbol)
              if (e.key === 'Escape') setOpen(false)
            }}
            placeholder="Buscar ticker (AAPL, BTC, ...)"
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

        {open && qUpper.length > 0 && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-bg-1 border border-line rounded-sm shadow-xl max-h-80 overflow-y-auto z-50">
            {results.length === 0 ? (
              <div className="px-3 py-2.5 text-xs text-ink-3">
                Sin resultados. Probá con el ticker exacto (e.j. "AAPL").
              </div>
            ) : (
              <ul>
                {results.map(r => (
                  <li key={r.symbol}>
                    <button
                      onClick={() => pick(r.symbol)}
                      className="w-full flex items-center justify-between gap-2 px-3 py-2 hover:bg-bg-2 text-left"
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-mono text-ink-0">{r.symbol}</div>
                        <div className="text-[10px] text-ink-3 truncate">{r.name}</div>
                      </div>
                      {r.fromUser && (
                        <span className="text-[9px] uppercase tracking-wider text-rendi-pos bg-rendi-pos/10 border border-rendi-pos/20 px-1.5 py-0.5 rounded-sm flex-shrink-0">
                          Tenés
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {selected && (
        <AssetQuickView symbol={selected} onClose={() => setSelected(null)} />
      )}
    </>
  )
}
