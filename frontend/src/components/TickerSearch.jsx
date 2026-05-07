import { useState, useRef, useEffect, useMemo } from 'react'
import { Search, X, TrendingUp, Coins, Building2, Globe, Plus, BarChart3, Layers, Activity } from 'lucide-react'
import {
  CRYPTO,
  STOCKS_US,
  ETFS,
  INDICES,
  CEDEARS_LIST,
  ARG_LIDER,
  ARG_GENERAL,
} from '../utils/tickers'

// Categorías unificadas (mismas para ARS y USDT — el usuario filtra como quiera)
const CATEGORIES = [
  { id: 'all',     label: 'Todos',       icon: Globe,      list: null },
  { id: 'crypto',  label: 'Cripto',      icon: Coins,      list: CRYPTO,        cat: 'CRIPTO',  color: 'amber' },
  { id: 'stocks',  label: 'Acciones',    icon: TrendingUp, list: STOCKS_US,     cat: 'ACCIÓN',  color: 'blue' },
  { id: 'cedears', label: 'CEDEARs',     icon: Layers,     list: CEDEARS_LIST,  cat: 'CEDEAR',  color: 'violet' },
  { id: 'etfs',    label: 'ETFs',        icon: BarChart3,  list: ETFS,          cat: 'ETF',     color: 'cyan' },
  { id: 'indices', label: 'Índices',     icon: Activity,   list: INDICES,       cat: 'ÍNDICE',  color: 'rose' },
  { id: 'ar_lider',label: 'Panel Líder', icon: Building2,  list: ARG_LIDER,     cat: 'AR LÍDER',color: 'emerald' },
  { id: 'ar_gen',  label: 'Panel Gral',  icon: Building2,  list: ARG_GENERAL,   cat: 'AR GRAL', color: 'teal' },
]

// Lista combinada para "Todos" — preserva categoría para badge.
function buildAll() {
  const seen = new Set()
  const out = []
  for (const cat of CATEGORIES.slice(1)) {
    for (const item of cat.list) {
      const key = `${cat.id}:${item.s}`
      if (seen.has(key)) continue
      seen.add(key)
      out.push({ ...item, _cat: cat.id })
    }
  }
  return out
}
const ALL_LIST = buildAll()

const COLOR_CLASS = {
  amber:   'bg-amber-500/15 text-amber-600 dark:text-amber-400',
  blue:    'bg-blue-500/15 text-blue-600 dark:text-blue-400',
  violet:  'bg-violet-500/15 text-violet-600 dark:text-violet-400',
  cyan:    'bg-cyan-500/15 text-cyan-600 dark:text-cyan-400',
  rose:    'bg-rose-500/15 text-rose-600 dark:text-rose-400',
  emerald: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
  teal:    'bg-teal-500/15 text-teal-600 dark:text-teal-400',
}

export default function TickerSearch({ value, onChange, currency = 'ARS', placeholder, className = '' }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState(value || '')
  const [activeCat, setActiveCat] = useState('all')
  const [highlightIdx, setHighlightIdx] = useState(0)
  const wrapRef = useRef(null)
  const inputRef = useRef(null)
  const listRef = useRef(null)

  useEffect(() => { setQuery(value || '') }, [value])

  useEffect(() => {
    function handleClick(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const filtered = useMemo(() => {
    const baseList = activeCat === 'all'
      ? ALL_LIST
      : (CATEGORIES.find(c => c.id === activeCat)?.list || []).map(x => ({ ...x, _cat: activeCat }))
    const q = query.trim().toUpperCase()
    if (!q) return baseList.slice(0, 300)
    // matching: ticker startsWith primero, luego ticker includes, luego name includes
    const startsWith = []
    const ticIncludes = []
    const nameIncludes = []
    for (const item of baseList) {
      if (item.s.startsWith(q)) startsWith.push(item)
      else if (item.s.includes(q)) ticIncludes.push(item)
      else if (item.n && item.n.toUpperCase().includes(q)) nameIncludes.push(item)
    }
    return [...startsWith, ...ticIncludes, ...nameIncludes].slice(0, 300)
  }, [query, activeCat])

  const showManual = query.trim().length > 0 &&
    !filtered.some(f => f.s === query.trim().toUpperCase())

  function pick(ticker) {
    onChange(ticker)
    setQuery(ticker)
    setOpen(false)
  }

  function handleKeyDown(e) {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') {
        setOpen(true)
        e.preventDefault()
      }
      return
    }
    const total = filtered.length + (showManual ? 1 : 0)
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIdx(i => Math.min(total - 1, i + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIdx(i => Math.max(0, i - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (highlightIdx < filtered.length) pick(filtered[highlightIdx].s)
      else if (showManual) pick(query.trim().toUpperCase())
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  useEffect(() => {
    if (!listRef.current) return
    const el = listRef.current.querySelector(`[data-idx="${highlightIdx}"]`)
    if (el) el.scrollIntoView({ block: 'nearest' })
  }, [highlightIdx])

  // Categoría sugerida según moneda del broker (para resaltar pero todas siguen accesibles)
  const suggested = currency === 'ARS' ? ['cedears', 'ar_lider', 'ar_gen'] : ['crypto', 'stocks', 'etfs']

  return (
    <div ref={wrapRef} className={`relative ${className}`}>
      <div className="relative">
        <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500 pointer-events-none" />
        <input
          ref={inputRef}
          value={query}
          onChange={e => {
            const v = e.target.value.toUpperCase()
            setQuery(v)
            onChange(v)
            setOpen(true)
            setHighlightIdx(0)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || 'Buscar por ticker o nombre (ej.: AAPL, Bitcoin, S&P 500)'}
          autoComplete="off"
          spellCheck="false"
          className="w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md pl-8 pr-8 py-2 text-sm text-slate-900 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-rendi-green/40 focus:border-rendi-green/60 transition"
        />
        {query && (
          <button
            type="button"
            onClick={() => { setQuery(''); onChange(''); inputRef.current?.focus() }}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {open && (
        <div className="absolute z-50 mt-1 left-0 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-2xl overflow-hidden w-[min(680px,92vw)] flex flex-col" style={{ maxHeight: '70vh' }}>
          {/* Tabs de categorías — sticky para que no se vayan al scrollear */}
          <div className="flex flex-wrap gap-1.5 p-2.5 bg-slate-50 dark:bg-slate-900/50 border-b border-slate-200 dark:border-slate-700 shrink-0">
            {CATEGORIES.map(cat => {
              const Icon = cat.icon
              const active = activeCat === cat.id
              const isSuggested = suggested.includes(cat.id)
              const count = cat.id === 'all' ? ALL_LIST.length : cat.list.length
              return (
                <button
                  key={cat.id}
                  type="button"
                  onClick={() => { setActiveCat(cat.id); setHighlightIdx(0) }}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition ${
                    active
                      ? 'bg-rendi-green/15 text-rendi-green-dark dark:text-rendi-green ring-1 ring-rendi-green/30'
                      : isSuggested
                      ? 'text-slate-700 dark:text-slate-300 hover:bg-slate-200/60 dark:hover:bg-slate-700/60'
                      : 'text-slate-500 dark:text-slate-400 hover:bg-slate-200/60 dark:hover:bg-slate-700/60'
                  }`}
                >
                  <Icon size={12} />
                  {cat.label}
                  <span className={`text-[10px] tabular-nums ${active ? 'opacity-70' : 'opacity-50'}`}>
                    {count}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Lista — altura mínima 460px para mostrar bastante contenido */}
          <div ref={listRef} className="flex-1 overflow-y-auto" style={{ minHeight: '460px', maxHeight: '460px' }}>
            {filtered.length === 0 && !showManual && (
              <div className="px-3 py-12 text-center text-xs text-slate-400 dark:text-slate-500">
                <Search size={24} className="mx-auto mb-2 opacity-50" />
                Sin resultados para "<span className="font-mono">{query}</span>"
              </div>
            )}
            {filtered.map((item, i) => {
              const catDef = CATEGORIES.find(c => c.id === item._cat)
              const colorClass = catDef ? COLOR_CLASS[catDef.color] : ''
              return (
                <button
                  key={`${item._cat}-${item.s}-${i}`}
                  type="button"
                  data-idx={i}
                  onMouseEnter={() => setHighlightIdx(i)}
                  onClick={() => pick(item.s)}
                  className={`w-full text-left px-3.5 py-2.5 flex items-center justify-between gap-3 transition border-l-2 ${
                    highlightIdx === i
                      ? 'bg-rendi-green/10 border-rendi-green'
                      : 'border-transparent hover:bg-slate-100 dark:hover:bg-slate-700/60'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <span className="font-mono font-semibold text-sm text-slate-900 dark:text-white shrink-0 w-20 truncate">
                      {item.s}
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400 truncate">
                      {item.n}
                    </span>
                  </div>
                  {catDef && (
                    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded shrink-0 ${colorClass}`}>
                      {catDef.cat}
                    </span>
                  )}
                </button>
              )
            })}
            {showManual && (
              <button
                type="button"
                data-idx={filtered.length}
                onMouseEnter={() => setHighlightIdx(filtered.length)}
                onClick={() => pick(query.trim().toUpperCase())}
                className={`w-full text-left px-3 py-2.5 text-sm flex items-center gap-2 border-t border-slate-200 dark:border-slate-700 transition ${
                  highlightIdx === filtered.length
                    ? 'bg-amber-500/10'
                    : 'hover:bg-slate-100 dark:hover:bg-slate-700/60'
                }`}
              >
                <Plus size={14} className="text-amber-500" />
                <span className="text-slate-700 dark:text-slate-300">
                  Usar <span className="font-mono font-semibold text-amber-600 dark:text-amber-400">{query.trim().toUpperCase()}</span> como ticker manual
                </span>
              </button>
            )}
          </div>

          {/* Footer con hint de teclado */}
          <div className="px-3 py-1.5 text-[10px] text-slate-400 dark:text-slate-500 bg-slate-50 dark:bg-slate-900/50 border-t border-slate-200 dark:border-slate-700 flex items-center justify-between">
            <span>{filtered.length} resultados</span>
            <span className="flex items-center gap-2">
              <kbd className="px-1 py-0.5 bg-slate-200 dark:bg-slate-700 rounded">↑↓</kbd>
              navegar
              <kbd className="px-1 py-0.5 bg-slate-200 dark:bg-slate-700 rounded">↵</kbd>
              seleccionar
              <kbd className="px-1 py-0.5 bg-slate-200 dark:bg-slate-700 rounded">esc</kbd>
              cerrar
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
