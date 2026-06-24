// Fundamentals — ficha de fundamentales de acciones (Rendi Score).
// ═══════════════════════════════════════════════════════════════════════════
// Sub-nav "Analizar · Comparar · Favoritos" sincronizada con ?view=
// (analizar = default). Dentro de Analizar, ?ticker= elige la acción; dentro de
// Comparar, ?cmp=NVDA,MSFT,… persiste la lista comparada.
//
//   • Analizar  → scorecard de una acción (search + chips + gauge + IA). Wave 1.
//   • Comparar  → hasta 5 acciones lado a lado: ranking, ganador por categoría,
//                 detalle métrica por métrica. Wave 2 (lazy).
//   • Favoritos → grid de las equities en watchlist con su score. Wave 2 (lazy).
//
// El patrón de tabs (pill filled, violet en la activa) copia pages/Analisis.jsx.

import { lazy, Suspense, useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Gauge, Layers, Star } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { track } from '../utils/track'
import AnalyzeView from '../components/fundamentals/AnalyzeView'
import useWatchlist from '../components/fundamentals/useWatchlist'

const CompareView = lazy(() => import('../components/fundamentals/CompareView'))
const FavoritesView = lazy(() => import('../components/fundamentals/FavoritesView'))

const TABS = [
  { id: 'analizar',  label: 'Analizar',  icon: Gauge },
  { id: 'comparar',  label: 'Comparar',  icon: Layers },
  { id: 'favoritos', label: 'Favoritos', icon: Star },
]
const VALID_VIEWS = new Set(TABS.map(t => t.id))
const DEFAULT_VIEW = 'analizar'

function parseCmp(raw) {
  return (raw || '')
    .split(',')
    .map(s => s.trim().toUpperCase())
    .filter(Boolean)
    .slice(0, 5)
}

export default function Fundamentals() {
  const [searchParams, setSearchParams] = useSearchParams()

  const urlView = searchParams.get('view')
  const view = urlView && VALID_VIEWS.has(urlView) ? urlView : DEFAULT_VIEW
  const ticker = (searchParams.get('ticker') || '').toUpperCase()
  const cmpTickers = parseCmp(searchParams.get('cmp'))

  // Watchlist compartida entre las 3 vistas (un solo fetch + sync por eventos).
  const watchlist = useWatchlist()

  useEffect(() => {
    track('fundamentals_view_changed', { view })
  }, [view])

  // ── Helpers de URL ──────────────────────────────────────────────────────
  const setView = useCallback((next) => {
    setSearchParams(prev => {
      const sp = new URLSearchParams(prev)
      if (next === DEFAULT_VIEW) sp.delete('view')
      else sp.set('view', next)
      return sp
    })
  }, [setSearchParams])

  // Selección de ticker dentro de Analizar (mantiene ?view= si está presente).
  const selectTicker = useCallback((symbol) => {
    const sym = (symbol || '').toUpperCase()
    setSearchParams(prev => {
      const sp = new URLSearchParams(prev)
      if (sym) sp.set('ticker', sym)
      else sp.delete('ticker')
      return sp
    })
  }, [setSearchParams])

  // Abrir un ticker desde Comparar/Favoritos → ir a Analizar con ?ticker=.
  const openTickerInAnalyze = useCallback((symbol) => {
    const sym = (symbol || '').toUpperCase()
    setSearchParams(prev => {
      const sp = new URLSearchParams(prev)
      sp.delete('view') // analizar = default
      if (sym) sp.set('ticker', sym)
      return sp
    })
  }, [setSearchParams])

  // Cambiar la lista comparada → ?cmp=
  const setCmpTickers = useCallback((list) => {
    setSearchParams(prev => {
      const sp = new URLSearchParams(prev)
      const arr = (list || []).map(s => s.toUpperCase()).filter(Boolean).slice(0, 5)
      if (arr.length) sp.set('cmp', arr.join(','))
      else sp.delete('cmp')
      return sp
    })
  }, [setSearchParams])

  return (
    <div className="page-shell">
      <PageHeader
        eyebrow="INVESTIGACIÓN"
        title="Fundamentals"
        subtitle="Buscá una acción, mirá qué tan sólidos son sus fundamentals, compará varias y seguí tus favoritas."
      />

      {/* Sub-nav — pills filled con violet en la activa (patrón Analisis.jsx) */}
      <div className="inline-flex flex-wrap gap-2 mb-5">
        {TABS.map(t => {
          const Icon = t.icon
          const active = view === t.id
          return (
            <button
              key={t.id}
              onClick={() => setView(t.id)}
              className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-md border transition-all ${
                active
                  ? 'bg-data-violet/15 text-data-violet border-data-violet/40 shadow-sm'
                  : 'bg-bg-1 text-ink-2 border-line hover:text-ink-0 hover:border-line-2 hover:bg-bg-2'
              }`}
              aria-pressed={active}
            >
              <Icon size={15} strokeWidth={1.75} aria-hidden="true" />
              {t.label}
            </button>
          )
        })}
      </div>

      {/* Analizar — siempre montado (ligero, conserva estado del scorecard) */}
      <div className={view === 'analizar' ? '' : 'hidden'}>
        <AnalyzeView ticker={ticker} onSelect={selectTicker} watchlist={watchlist} />
      </div>

      {/* Comparar / Favoritos — lazy, solo se montan al entrar a su tab */}
      <Suspense fallback={<div className="text-center py-20 text-ink-3 text-sm">Cargando…</div>}>
        {view === 'comparar' && (
          <CompareView
            tickers={cmpTickers}
            onChangeTickers={setCmpTickers}
            onOpenTicker={openTickerInAnalyze}
            watchlist={watchlist}
          />
        )}
        {view === 'favoritos' && (
          <FavoritesView watchlist={watchlist} onOpenTicker={openTickerInAnalyze} />
        )}
      </Suspense>
    </div>
  )
}
