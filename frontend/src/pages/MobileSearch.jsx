// MobileSearch — buscador full-screen para mobile (Sprint M2, item 10).
// ═══════════════════════════════════════════════════════════════════════════
// Pantalla dedicada que reemplaza el dropdown inline del SearchBar desktop.
// Reusa el universo de tickers de SearchBar via import.
//
// UX (audit pattern):
//   ┌── back · input (autofocus) · clear ──┐
//   ├── chips de filtros (mono caps) ──────┤
//   │  EN TU PORTFOLIO                     │
//   │  TICKER · nombre  →                  │
//   │                                      │
//   │  SUGERIDOS                           │
//   │  TICKER · nombre  →                  │
//   └──────────────────────────────────────┘
//
// Sin auto-complete fancy: filtro substring sobre symbol + name.

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowLeft, X, Search as SearchIcon, Star, ChevronRight, Plus, Check } from 'lucide-react'
import AssetLogo from '../components/AssetLogo'
import AssetTypeBadge from '../components/AssetTypeBadge'
import { api } from '../utils/api'
import { useToast } from '../components/Toast'
import { track } from '../utils/track'
import { notifyWatchlistChanged } from '../utils/watchlistEvents'
import { useAuth } from '../contexts/AuthContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { menuVisible, nombreDelCliente } from '../utils/navegacion'
import { destinoDeTicker } from '../utils/buscadorRapido'

// Reusamos los tickers populares + helpers del SearchBar desktop para no
// duplicar el universo. Import statement nombrado — agregamos los exports en
// la otra refactor.
import { POPULAR_TICKERS, FILTERS, inferType } from '../components/home/SearchBar'
import { CEDEAR_SEARCH, AR_STOCK_SEARCH, US_SEARCH } from '../utils/tickers'


export default function MobileSearch() {
  const navigate = useNavigate()
  const toast = useToast()
  // El asesor en su nivel no tiene cartera ni watchlist propias (mismo criterio
  // que le saca el "+" de la barra de abajo): ni "En tu portfolio" ni estrella.
  const { user } = useAuth()
  const { clientCtx } = useAdvisorContext()
  const { atOwnLevel } = menuVisible({ user, clientCtx })
  // A dónde lleva cada fila: la MISMA regla que el ⌘K de la compu
  // (destinoDeTicker, utils/buscadorRapido.js). Iba a `/posiciones#X` y
  // `/posiciones?search=X`, que la Cartera del celular no lee: quedabas arriba
  // de tu lista sin nada abierto. null = no hay pantalla para ese ticker (un
  // bono, una cripto) o es el asesor en su nivel, que no tiene "Calidad de
  // cartera" en su menú: la fila no lleva a ningún lado y queda sólo la estrella.
  const destinoDe = (t) => (atOwnLevel && !t.fromUser) ? null
    : destinoDeTicker(t.symbol, { tuyo: t.fromUser, tipo: t.type })
  const puedeSeguir = !atOwnLevel   // la estrella de watchlist (cuenta propia)
  // Adentro de un cliente, lo que "tenés" es de él.
  const deQuien = clientCtx ? `la cartera de ${nombreDelCliente(clientCtx)}` : 'tu portfolio'
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')
  const [userHoldings, setUserHoldings] = useState([])
  const [watchlist, setWatchlist] = useState([])
  const [adding, setAdding] = useState(null)
  const inputRef = useRef(null)

  useEffect(() => { track('mobile_search_viewed') }, [])

  // Autofocus al montar (sin race con animaciones)
  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 80)
    return () => clearTimeout(t)
  }, [])

  // Cargar holdings + watchlist
  useEffect(() => {
    if (atOwnLevel) { setUserHoldings([]); return }
    api.get('/positions')
      .then(d => {
        const map = new Map()
        for (const p of (d || [])) {
          if (p.is_cash || !p.asset) continue
          const symbol = p.asset.toUpperCase()
          const prev = map.get(symbol)
          const qty = Number(p.quantity || 0)
          if (prev) prev.quantity += qty
          else map.set(symbol, { symbol, name: p.asset, quantity: qty, type: inferType(p.asset), fromUser: true })
        }
        setUserHoldings(Array.from(map.values()))
      })
      .catch(() => setUserHoldings([]))
  }, [atOwnLevel])

  useEffect(() => {
    if (atOwnLevel) { setWatchlist([]); return }
    api.get('/watchlist')
      .then(d => {
        const items = Array.isArray(d) ? d : (d?.items || [])
        setWatchlist(items.map(w => (w.symbol || '').toUpperCase()))
      })
      .catch(() => setWatchlist([]))
  }, [atOwnLevel])

  // Búsqueda y filtros
  const qUpper = q.trim().toUpperCase()
  const tokens = qUpper.split(/\s+/).filter(Boolean)

  const matches = useMemo(() => {
    // 1) Holdings primero si matchean
    const allHoldings = userHoldings
    // Con query, sumamos TODOS los CEDEARs del allowlist (no solo POPULAR_TICKERS)
    // para que cualquier CEDEAR sea encontrable. Dedup por símbolo.
    const allPopular = qUpper
      ? [...POPULAR_TICKERS,
         ...[...CEDEAR_SEARCH, ...AR_STOCK_SEARCH, ...US_SEARCH].filter(c => !POPULAR_TICKERS.some(p => p.symbol === c.symbol))]
      : POPULAR_TICKERS

    function matchesQuery(t) {
      if (tokens.length === 0) return true
      const sym = t.symbol.toUpperCase()
      const nm = (t.name || '').toUpperCase()
      return tokens.every(tok => sym.includes(tok) || nm.includes(tok))
    }
    function matchesFilter(t) {
      if (filter === 'all') return true
      return t.type === filter
    }

    const holdingsMatch = allHoldings.filter(t => matchesQuery(t) && matchesFilter(t))
    const holdingsSyms = new Set(holdingsMatch.map(t => t.symbol))
    const popularMatch = allPopular
      .filter(t => !holdingsSyms.has(t.symbol) && matchesQuery(t) && matchesFilter(t))
      // Una fila que no lleva a ningún lado y no tiene estrella no sirve.
      .filter(t => puedeSeguir || destinoDe(t))
      .slice(0, 30)
    return { holdingsMatch, popularMatch, total: holdingsMatch.length + popularMatch.length }
  }, [qUpper, tokens, userHoldings, filter, atOwnLevel])

  function back() { navigate(-1) }


  async function addToWatchlist(t) {
    setAdding(t.symbol)
    try {
      await api.post('/watchlist', { symbol: t.symbol })
      setWatchlist(prev => [...prev, t.symbol])
      // Notificar a otros componentes (Watchlist en /home) para que actualicen
      // sin requerir recarga manual.
      notifyWatchlistChanged({ symbol: t.symbol, added: true })
      track('watchlist_added', { symbol: t.symbol, source: 'mobile_search' })
      toast?.show?.({ kind: 'success', text: `${t.symbol} agregado a watchlist` })
    } catch (ex) {
      toast?.show?.({ kind: 'error', text: ex?.message || 'Error al agregar' })
    } finally {
      setAdding(null)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[55] bg-bg-0 flex flex-col"
      style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}
    >
      {/* Top bar: back + input + clear */}
      <header className="flex items-center gap-2 px-3 py-2.5 border-b border-line/40 flex-shrink-0">
        <button
          onClick={back}
          aria-label="Volver"
          className="text-ink-2 hover:text-ink-0 p-1.5"
        >
          <ArrowLeft size={18} strokeWidth={1.75} />
        </button>
        <div className="relative flex-1">
          <SearchIcon size={14} strokeWidth={1.75} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
          <input
            ref={inputRef}
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Buscar ticker o nombre…"
            className="w-full bg-bg-2 border border-line/40 rounded-md pl-8 pr-8 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-rendi-accent/40"
          />
          {q && (
            <button
              onClick={() => setQ('')}
              aria-label="Limpiar"
              className="absolute right-1.5 top-1/2 -translate-y-1/2 text-ink-3 hover:text-ink-0 p-1"
            >
              <X size={12} strokeWidth={1.75} />
            </button>
          )}
        </div>
      </header>

      {/* Filter chips */}
      <div className="border-b border-line/40 overflow-x-auto scrollbar-none flex-shrink-0">
        <div className="flex items-center gap-1 px-3 py-2 whitespace-nowrap">
          {FILTERS.map(f => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`text-[10px] px-2.5 py-1 rounded-sm transition-colors ${
                filter === f.id
                  ? 'bg-bg-3 text-ink-0 border border-line-2'
                  : 'text-ink-3 hover:text-ink-1 border border-transparent'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto">
        {matches.total === 0 ? (
          <div className="px-4 py-10 text-center">
            <SearchIcon size={20} strokeWidth={1.5} className="mx-auto mb-3 text-ink-3" />
            {qUpper ? (
              <>
                <p className="text-xs text-ink-2 mb-1">
                  Sin resultados para <span className="font-mono text-ink-0">{qUpper}</span>
                </p>
                <p className="text-[11px] text-ink-3">
                  Probá con el símbolo exacto (ej. "AAPL", "AL30", "BTC")
                </p>
              </>
            ) : (
              <p className="text-xs text-ink-3">
                Empezá a escribir para buscar entre {POPULAR_TICKERS.length}+ tickers.
              </p>
            )}
          </div>
        ) : (
          <>
            {matches.holdingsMatch.length > 0 && (
              <section>
                <SectionHeader label={`En ${deQuien}`} count={matches.holdingsMatch.length} />
                {matches.holdingsMatch.map(t => (
                  <SearchRow
                    key={t.symbol}
                    ticker={t}
                    highlight
                    destino={destinoDe(t)}
                    tuya={clientCtx ? 'En cartera' : 'Tuya'}
                    onAdd={puedeSeguir ? () => addToWatchlist(t) : null}
                    adding={adding === t.symbol}
                    inWatchlist={watchlist.includes(t.symbol)}
                  />
                ))}
              </section>
            )}
            {matches.popularMatch.length > 0 && (
              <section className={matches.holdingsMatch.length > 0 ? 'border-t border-line/40' : ''}>
                <SectionHeader label="Sugeridos" count={matches.popularMatch.length} />
                {matches.popularMatch.map(t => (
                  <SearchRow
                    key={t.symbol}
                    ticker={t}
                    destino={destinoDe(t)}
                    tuya={clientCtx ? 'En cartera' : 'Tuya'}
                    onAdd={puedeSeguir ? () => addToWatchlist(t) : null}
                    adding={adding === t.symbol}
                    inWatchlist={watchlist.includes(t.symbol)}
                  />
                ))}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ─── Subcomponentes ──────────────────────────────────────────────────────

function SectionHeader({ label, count }) {
  return (
    <div className="px-3 pt-3 pb-2 flex items-baseline justify-between">
      <span className="text-[12.5px] text-ink-2 font-medium">
        {label}
      </span>
      <span className="text-[10px] tabular text-ink-3">
        {count}
      </span>
    </div>
  )
}

function SearchRow({ ticker, highlight, destino, tuya, onAdd, adding, inWatchlist }) {
  // Un enlace de verdad (no un botón que navega): se ve a dónde lleva, y una
  // fila sin pantalla para ese ticker no promete nada.
  const Principal = destino ? Link : 'div'
  const alElegir = () => track('mobile_search_pick', { symbol: ticker.symbol })
  return (
    <div
      // Sin destino no se ilumina al tocarla: no va a abrir nada (sólo la estrella).
      className={`flex items-center gap-3 px-3 py-2.5 border-t border-line/30 transition-colors ${destino ? 'hover:bg-bg-2/30 active:bg-bg-3' : ''} ${
        highlight ? 'bg-rendi-pos/[0.02]' : ''
      }`}
    >
      <Principal {...(destino ? { to: destino, onClick: alElegir } : {})} className="flex items-center gap-3 flex-1 min-w-0 text-left">
        <AssetLogo asset={ticker.symbol} size={28} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-sm font-semibold text-ink-0 truncate">{ticker.symbol}</span>
            <AssetTypeBadge type={ticker.type} />
            {ticker.fromUser && (
              <span className="text-[12.5px] text-rendi-pos font-medium">
                {tuya}
              </span>
            )}
          </div>
          <div className="text-[11px] text-ink-3 truncate">
            {ticker.name} {ticker.exchange ? `· ${ticker.exchange}` : ''}
          </div>
        </div>
      </Principal>

      {!ticker.fromUser && onAdd && (
        <button
          onClick={onAdd}
          disabled={inWatchlist || adding}
          aria-label={inWatchlist ? 'Ya está en watchlist' : 'Agregar a watchlist'}
          className={`p-2 rounded-sm border transition-colors flex-shrink-0 ${
            inWatchlist
              ? 'border-rendi-pos/40 bg-rendi-pos/10 text-rendi-pos cursor-default'
              : 'border-line/60 text-ink-3 hover:text-rendi-warn hover:border-rendi-warn/40'
          }`}
        >
          {inWatchlist ? <Check size={12} strokeWidth={1.75} /> : <Star size={12} strokeWidth={1.75} />}
        </button>
      )}

      {destino && (
        <Link to={destino} onClick={alElegir} aria-hidden="true" tabIndex={-1} className="text-ink-3 hover:text-ink-0 p-1 flex-shrink-0">
          <ChevronRight size={14} strokeWidth={1.75} />
        </Link>
      )}
    </div>
  )
}
