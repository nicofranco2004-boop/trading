// Calidad de cartera — cartera-first, SIN pestañas (a propósito, para no replicar
// la navegación de Vesty: Analizar/Comparar/Favoritos + buscador-héroe).
// ═══════════════════════════════════════════════════════════════════════════
// La página ABRE en tu cartera (CarteraList) + una sección "Que seguís". El
// buscador es una herramienta (overlay command-palette, botón o ⌘K), no la
// portada. El estado vive en la URL:
//   • sin params  → home (tu cartera + seguidas)
//   • ?ticker=X   → ficha de un activo (AnalyzeView, sin su buscador embebido)
//   • ?cmp=A,B    → comparación (CompareView), entrada por selección desde la lista

import { lazy, Suspense, useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Search, ChevronLeft } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { track } from '../utils/track'
import CarteraList from '../components/fundamentals/CarteraList'
import AnalyzeView from '../components/fundamentals/AnalyzeView'
import SearchOverlay from '../components/fundamentals/SearchOverlay'
import useWatchlist from '../components/fundamentals/useWatchlist'

const CompareView = lazy(() => import('../components/fundamentals/CompareView'))

function parseCmp(raw) {
  return (raw || '')
    .split(',')
    .map(s => s.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, 5)
}

export default function Fundamentals() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [searchOpen, setSearchOpen] = useState(false)
  // Cuando se abre el buscador para COMPARAR desde una ficha, guardamos el ticker
  // base; al elegir el segundo, vamos directo a la comparación.
  const [compareFrom, setCompareFrom] = useState(null)

  const ticker = (searchParams.get('ticker') || '').toUpperCase()
  const cmpTickers = parseCmp(searchParams.get('cmp'))
  const mode = ticker ? 'detail' : (cmpTickers.length ? 'compare' : 'home')

  const watchlist = useWatchlist()

  useEffect(() => { track('calidad_cartera_view', { mode }) }, [mode])

  // ⌘K / Ctrl+K abre el buscador.
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Abrir la ficha de un activo (desde la lista, seguidas, comparar o el buscador).
  const openTicker = useCallback((symbol) => {
    const sym = (symbol || '').toUpperCase()
    if (!sym) return
    setSearchParams(prev => {
      const sp = new URLSearchParams(prev)
      sp.set('ticker', sym)
      sp.delete('cmp')
      return sp
    })
  }, [setSearchParams])

  // Ir a comparar una selección de la cartera.
  const openCompare = useCallback((list) => {
    const arr = [...new Set((list || []).map(s => s.toUpperCase()).filter(Boolean))].slice(0, 5)
    if (!arr.length) return
    setSearchParams(prev => {
      const sp = new URLSearchParams(prev)
      sp.set('cmp', arr.join(','))
      sp.delete('ticker')
      return sp
    })
  }, [setSearchParams])

  const setCmpTickers = useCallback((list) => {
    setSearchParams(prev => {
      const sp = new URLSearchParams(prev)
      const arr = (list || []).map(s => s.toUpperCase()).filter(Boolean).slice(0, 5)
      if (arr.length) sp.set('cmp', arr.join(','))
      else sp.delete('cmp')
      return sp
    })
  }, [setSearchParams])

  const goHome = useCallback(() => {
    setSearchParams(prev => {
      const sp = new URLSearchParams(prev)
      sp.delete('ticker')
      sp.delete('cmp')
      return sp
    })
  }, [setSearchParams])

  return (
    <div className="page-shell">
      <PageHeader
        eyebrow="INVESTIGACIÓN"
        title="Calidad de cartera"
        subtitle="Qué tan sólidas son las empresas detrás de tus acciones y CEDEARs, y si el precio de hoy las acompaña."
      />

      {/* Barra de acción: volver (en detalle/compare) + buscar (siempre). Sin pestañas. */}
      <div className="flex items-center justify-between gap-3 mb-5">
        <div className="min-w-0">
          {mode !== 'home' && (
            <button
              type="button"
              onClick={goHome}
              className="inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink-0 transition-colors"
            >
              <ChevronLeft size={16} strokeWidth={2} /> Tu cartera
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={() => setSearchOpen(true)}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-md border border-line bg-bg-1 text-sm text-ink-2 hover:text-ink-0 hover:border-line-2 transition-colors flex-shrink-0"
        >
          <Search size={15} strokeWidth={1.75} /> Buscar activo
          <kbd className="hidden sm:inline-block text-[10px] font-mono text-ink-3 border border-line rounded px-1 py-0.5 ml-0.5">⌘K</kbd>
        </button>
      </div>

      {mode === 'home' && (
        <CarteraList onOpenTicker={openTicker} onCompare={openCompare} watchlist={watchlist} />
      )}

      {mode === 'detail' && (
        <AnalyzeView
          ticker={ticker}
          onSelect={openTicker}
          watchlist={watchlist}
          hideSearch
          onCompareWith={(t) => { setCompareFrom(t); setSearchOpen(true) }}
        />
      )}

      {mode === 'compare' && (
        <Suspense fallback={<div className="text-center py-20 text-ink-3 text-sm">Cargando…</div>}>
          <CompareView
            tickers={cmpTickers}
            onChangeTickers={setCmpTickers}
            onOpenTicker={openTicker}
            watchlist={watchlist}
          />
        </Suspense>
      )}

      {searchOpen && (
        <SearchOverlay
          compareWith={compareFrom}
          onSelect={(t) => {
            setSearchOpen(false)
            if (compareFrom) { openCompare([compareFrom, t]); setCompareFrom(null) }
            else openTicker(t)
          }}
          onClose={() => { setSearchOpen(false); setCompareFrom(null) }}
        />
      )}
    </div>
  )
}
