// TickerSearch — autocomplete focalizado para la página Fundamentals.
// ═══════════════════════════════════════════════════════════════════════════
// Distinto de components/home/SearchBar.jsx (que abre un modal/quickview de
// watchlist): este es un input simple que, al elegir un ticker, dispara
// onSelect(symbol, opcion) y deja que la página cargue la ficha de fundamentals.
// `opcion` es la sugerencia elegida ({symbol, name, type}: su tipo dice si GGAL
// es la acción argentina), o undefined si se tomó el texto escrito.
//
// Reusa POPULAR_TICKERS de utils/tickers.js + filtrado por symbol/name.
// Keyboard: ↑↓ navega, ↩ selecciona, ESC cierra. Con el cuadro vacío, ↩ elige
// sólo si antes se navegó con las flechas: si no, sumaba el primero de los
// populares (AAPL) sin que nadie lo eligiera. Era el arreglo de Tu lista, hecho
// en quien llama y no acá: «Una cartera» sumaba AAPL al 100 % con un Enter
// (auditoría 05/11, M4). Para un lector de pantalla es un combobox con su lista.
//
// También es el buscador de «Tu lista» en Análisis técnico (pages/TuLista.jsx),
// que suma a la watchlist: ahí recibe otro catálogo (`universo`: el del
// buscador del inicio, utils/tickers.catalogoDelBuscador), sus palabras y
// `marca(t)`, que dice si un activo ya está en tu cartera o en tu watchlist.
// Un solo cuadro con autocompletado y búsqueda por nombre en el servidor.

import { useState, useRef, useEffect, useMemo, useId } from 'react'
import { Search, CornerDownLeft } from 'lucide-react'
import { POPULAR_TICKERS } from '../../utils/tickers'
import { api } from '../../utils/api'
import AssetLogo from '../AssetLogo'
import AssetTypeBadge from '../AssetTypeBadge'

const MAX_RESULTS = 8

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

export default function TickerSearch({
  onSelect, autoFocus = false, universo = filterTickers,
  placeholder = 'Buscá una acción (ej. NVDA, Apple, MELI…)', etiqueta = 'Buscar ticker', pista = 'para ver',
  marca = null, textoLibre = true,
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(0)
  // ¿Se movió con las flechas desde lo último que se escribió?
  const [navego, setNavego] = useState(false)
  const lista = useId()
  const inputRef = useRef(null)
  const containerRef = useRef(null)

  const locales = useMemo(() => universo(query).slice(0, MAX_RESULTS), [universo, query])
  const [remotos, setRemotos] = useState([])

  // POPULAR_TICKERS tiene 104 símbolos y apenas 21 acciones US. Un usuario
  // reportó que no podía comparar AMD contra INTEL: la gente escribe el NOMBRE
  // ("intel", "uber"), eso no está en la lista, y sin sugerencias el Enter
  // mandaba el texto crudo como ticker — "UBER" acertaba de casualidad, "INTEL"
  // no existe (es INTC). El backend nunca fue el límite: acepta cualquier
  // símbolo. Así que la lista local sirve para responder al instante, y para
  // todo lo demás se pregunta.
  useEffect(() => {
    const q = query.trim()
    if (q.length < 2) { setRemotos([]); return }
    let vivo = true
    const id = setTimeout(() => {
      api.get(`/tickers/search?q=${encodeURIComponent(q)}`)
        .then(r => { if (vivo) setRemotos(r?.results || []) })
        .catch(() => { if (vivo) setRemotos([]) })
    }, 250)   // debounce: no una request por tecla
    return () => { vivo = false; clearTimeout(id) }
  }, [query])

  // Locales primero (instantáneos y con logo/badge), después los del server sin
  // repetir símbolos.
  const results = useMemo(() => {
    const vistos = new Set(locales.map(t => t.symbol.toUpperCase()))
    const extra = remotos
      .filter(r => !vistos.has(r.symbol.toUpperCase()))
      .map(r => ({ symbol: r.symbol, name: r.name, type: 'stock_us', remoto: true }))
    return [...locales, ...extra].slice(0, MAX_RESULTS)
  }, [locales, remotos])

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
  useEffect(() => { setHighlight(0); setNavego(false) }, [query])

  function choose(symbol, opcion) {
    setOpen(false)
    setQuery('')
    if (inputRef.current) inputRef.current.blur()
    onSelect?.(symbol, opcion)
  }

  function onKeyDown(e) {
    // Enter sin sugerencias: tomar el texto crudo (permite tickers no listados)
    if (e.key === 'Enter') {
      e.preventDefault()
      // Con el cuadro vacío, Enter no elige nada salvo que se haya navegado con
      // las flechas: antes sumaba el primero de los populares (AAPL) sin que nadie
      // lo eligiera (Tu lista, 22/10; para todos, 05/11).
      if (!query.trim() && !navego) return
      if (open && results[highlight]) {
        choose(results[highlight].symbol, results[highlight])
      } else if (textoLibre) {
        // `textoLibre` en false (sumar a la watchlist): un texto que no es
        // ninguna sugerencia no se guarda como si fuera un ticker («INTEL»).
        const raw = query.trim().toUpperCase()
        if (raw) choose(raw)
      }
      return
    }
    if (!open) {
      if (e.key === 'ArrowDown') { setOpen(true); setNavego(true); return }
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setNavego(true)
      setHighlight(h => Math.min(h + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setNavego(true)
      setHighlight(h => Math.max(h - 1, 0))
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="flex items-center gap-2 bg-bg-2 border border-line rounded px-3 py-2.5 focus-within:border-data-violet/60 transition-colors">
        <Search size={16} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          className="flex-1 min-w-0 bg-transparent text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none"
          aria-label={etiqueta}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open && results.length > 0}
          aria-controls={lista}
          aria-activedescendant={open && results[highlight] ? `${lista}-${highlight}` : undefined}
          autoComplete="off"
          spellCheck={false}
        />
        <span className="hidden sm:inline-flex items-center gap-1 text-[10px] font-mono text-ink-3">
          <CornerDownLeft size={11} /> {pista}
        </span>
      </div>

      {open && results.length > 0 && (
        <div id={lista} role="listbox" aria-label={etiqueta}
          className="absolute z-30 left-0 right-0 mt-1.5 bg-bg-raised border border-line rounded-lg overflow-hidden">
          {results.map((t, i) => (
            <button
              key={t.symbol}
              id={`${lista}-${i}`}
              type="button"
              role="option"
              aria-selected={i === highlight}
              onClick={() => choose(t.symbol, t)}
              onMouseEnter={() => setHighlight(i)}
              className={`w-full flex items-center justify-between gap-3 px-3 py-2 text-left transition-colors ${
                i === highlight ? 'bg-bg-1' : 'hover:bg-bg-1'
              }`}
            >
              <span className="flex items-center gap-2 min-w-0">
                <AssetLogo asset={t.symbol} size={28} className="flex-shrink-0" />
                <span className="flex items-baseline gap-2 min-w-0">
                  <span className="font-mono text-sm font-semibold text-ink-0 tabular">{t.symbol}</span>
                  <span className="text-xs text-ink-3 truncate">{t.name}</span>
                </span>
              </span>
              <span className="flex items-center gap-2 flex-shrink-0">
                {marca?.(t) && <span className="text-[11.5px] text-ink-2 whitespace-nowrap">{marca(t)}</span>}
                <AssetTypeBadge type={t.type} />
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
