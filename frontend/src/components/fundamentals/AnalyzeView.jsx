// AnalyzeView — vista "Analizar" de Fundamentals (scorecard de un ticker).
// ═══════════════════════════════════════════════════════════════════════════
// Es el cuerpo de la wave-1 (search + chips de posiciones + scorecard +
// resumen IA), extraído a un componente para convivir con las tabs
// Comparar/Favoritos. El ticker se sincroniza con ?ticker= a través del padre.
//
// props:
//   ticker     — ticker activo (string, upper)
//   onSelect   — (symbol) => void, sube la selección al padre (setea ?ticker=)

import { useState, useEffect } from 'react'
import {
  Search, Tag, TrendingUp, Zap, ShieldCheck, AlertCircle, Gauge, Coins, Scale,
} from 'lucide-react'
import Panel from '../Panel'
import Pill from '../Pill'
import EmptyState from '../EmptyState'
import Skeleton from '../Skeleton'
import AssetLogo from '../AssetLogo'
import { api } from '../../utils/api'
import { inferType } from '../../utils/tickers'
import { track } from '../../utils/track'
import { useCoachDrawer } from '../../contexts/CoachDrawerContext'

import TickerSearch from './TickerSearch'
import CategoryDetail from './CategoryDetail'
import { businessQuality, priceRead, AXIS_TEXT, AXIS_BAR } from './axes'
import DetailPortfolioBlocks from './DetailPortfolioBlocks'
import AnalystConsensus from './AnalystConsensus'
import AISummaryCard from './AISummaryCard'
import StarToggle from './StarToggle'

const CATEGORY_ICON = {
  valuation: Tag,
  growth: TrendingUp,
  profitability: Zap,
  health: ShieldCheck,
  dividends: Coins,
}

// Compacta un market cap a "$10.64B" / "$3.20T" / "$640.0M". null → "—".
function fmtMarketCap(n) {
  if (n == null || Number.isNaN(n)) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '−' : ''
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`
  return `${sign}$${abs.toFixed(0)}`
}

function fmtMultiple(n) {
  if (n == null || Number.isNaN(n)) return '—'
  return `${n.toFixed(2)}x`
}

function fmtPct(n) {
  if (n == null || Number.isNaN(n)) return '—'
  return `${n.toFixed(2)}%`
}

function fmtBeta(n) {
  if (n == null || Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

// FooterStrip — barra full-width de 4 celdas con métricas clave de mercado.
function FooterStrip({ metrics }) {
  const m = metrics || {}
  const cells = [
    { label: 'Market Cap', value: fmtMarketCap(m.market_cap_usd) },
    { label: 'P/E', value: fmtMultiple(m.trailing_pe) },
    { label: 'Div Yield', value: fmtPct(m.dividend_yield_pct) },
    { label: 'Beta', value: fmtBeta(m.beta) },
  ]
  return (
    <Panel padding="none">
      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0 divide-line">
        {cells.map(c => (
          <div key={c.label} className="px-4 py-3 text-center">
            <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1">
              {c.label}
            </p>
            <p className="text-base font-semibold text-ink-0 tabular leading-none">
              {c.value}
            </p>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function AxisCard({ title, read }) {
  return (
    <div className="rounded-lg border border-line bg-bg-1 p-4">
      <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1.5">{title}</p>
      <p className={`text-2xl font-semibold leading-none ${AXIS_TEXT[read.tone] || 'text-ink-0'}`}>
        {read.label}
      </p>
      {read.sub && <p className="text-xs text-ink-2 mt-2 leading-snug">{read.sub}</p>}
      {read.score != null && (
        <div className="mt-3 h-1.5 rounded-full bg-bg-2 overflow-hidden" role="presentation">
          <div className={`h-full rounded-full ${AXIS_BAR[read.tone] || 'bg-ink-3'}`} style={{ width: `${read.score}%` }} />
        </div>
      )}
    </div>
  )
}

export default function AnalyzeView({ ticker, onSelect, watchlist, hideSearch = false, onCompareWith }) {
  const coachDrawer = useCoachDrawer()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [positions, setPositions] = useState([])

  // Chips "Tus posiciones" — solo equities US con fundamentals.
  useEffect(() => {
    let cancelled = false
    api.get('/positions')
      .then(list => {
        if (cancelled) return
        const arr = Array.isArray(list) ? list : (list?.items || [])
        const seen = new Set()
        const equities = []
        for (const p of arr) {
          const asset = (p.asset || '').toUpperCase()
          if (!asset || p.is_cash) continue
          if (inferType(asset) !== 'stock_us') continue
          if (seen.has(asset)) continue
          seen.add(asset)
          equities.push({ asset, is_cash: p.is_cash })
        }
        setPositions(equities)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  // Cargar scorecard cuando cambia el ticker.
  useEffect(() => {
    if (!ticker) { setData(null); return }
    let cancelled = false
    setLoading(true)
    setError(null)
    setData(null)
    api.get('/fundamentals/' + encodeURIComponent(ticker))
      .then(res => {
        if (cancelled) return
        setData(res)
        track('fundamentals_ticker_viewed', { ticker })
      })
      .catch(e => {
        if (cancelled) return
        setError(e?.message || 'No pudimos cargar los fundamentales.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [ticker])

  const categories = data?.available ? (data.score?.categories || []) : []
  const categoriesDetail = data?.available ? (data.categories_detail || []) : []

  return (
    <div>
      {/* Search card + chips de posiciones — se oculta cuando el buscador vive en
          el overlay global (modo detalle de "Calidad de cartera"). */}
      {!hideSearch && (
      <Panel className="mb-6">
        <TickerSearch onSelect={onSelect} autoFocus={!ticker} />

        {positions.length > 0 && (
          <div className="mt-4">
            <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2">
              Tus posiciones
            </p>
            <div className="flex flex-wrap gap-2">
              {positions.map(p => (
                <button
                  key={p.asset}
                  type="button"
                  onClick={() => onSelect(p.asset)}
                  className={`inline-flex items-center gap-2 pl-1.5 pr-3 py-1 rounded-full border transition-colors ${
                    ticker === p.asset
                      ? 'border-data-violet/50 bg-data-violet/10 text-ink-0'
                      : 'border-line bg-bg-2 text-ink-1 hover:border-line-2'
                  }`}
                >
                  <AssetLogo asset={p.asset} isCash={p.is_cash} size={20} />
                  <span className="font-mono text-xs font-medium">{p.asset}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </Panel>
      )}

      {/* Empty state — todavía no eligió ticker */}
      {!ticker && !loading && (
        <Panel padding="lg">
          <EmptyState
            icon={<Gauge size={20} strokeWidth={1.75} />}
            eyebrow="CALIDAD DE CARTERA"
            title="Buscá un activo o tocá una de tus posiciones"
            description="Escribí un ticker (NVDA, AAPL, MELI…) o elegí algo que ya tengas. Vas a ver qué tan sólido es el negocio, si el precio de hoy lo acompaña y un resumen en criollo."
          />
        </Panel>
      )}

      {loading && <ScorecardSkeleton />}

      {!loading && error && ticker && (
        <Panel padding="lg">
          <div className="flex items-start gap-2 text-sm text-rendi-neg">
            <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        </Panel>
      )}

      {/* available:false */}
      {!loading && !error && data && data.available === false && (
        <Panel padding="lg">
          <EmptyState
            icon={<Search size={20} strokeWidth={1.75} />}
            eyebrow={ticker}
            tone="warn"
            title="Para esta acción no tenemos fundamentales"
            description={
              data.reason ||
              'Probá con el ticker en USD. No aplica a cripto ni bonos — esos no tienen estados financieros para puntuar.'
            }
          />
        </Panel>
      )}

      {/* Scorecard OK */}
      {!loading && !error && data && data.available && (
        <div className="space-y-6">
          {/* Header de la acción — con star toggle a favoritos */}
          <div className="flex items-center gap-3 flex-wrap">
            <AssetLogo asset={data.ticker} size={36} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold text-ink-0 leading-tight">
                  {data.company_name || data.ticker}
                </h2>
                <span className="font-mono text-xs text-ink-3">{data.ticker}</span>
                {watchlist && (
                  <StarToggle
                    active={watchlist.has(data.ticker)}
                    onToggle={() => watchlist.toggle(data.ticker)}
                  />
                )}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                {data.sector && <span className="text-xs text-ink-3">{data.sector}</span>}
                {data.currency && (
                  <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
                    {data.currency}
                  </span>
                )}
                {data.stale && <Pill tone="warn">Datos diferidos</Pill>}
              </div>
            </div>
            {onCompareWith && (
              <button
                type="button"
                onClick={() => onCompareWith(data.ticker)}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-semibold bg-data-violet text-white hover:bg-data-violet/90 transition-colors flex-shrink-0"
              >
                <Scale size={15} strokeWidth={2} /> Comparar
              </button>
            )}
          </div>

          {/* Dos ejes separados: el negocio y el precio (sin score único, sin gauge) */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <AxisCard title="El negocio" read={businessQuality(categories)} />
            <AxisCard title="El precio hoy" read={priceRead(categories)} />
          </div>

          {/* Lo que diferencia a Rendi: tu posición (costo/P&L + espectro con tu
              costo) y "¿rinde más que?" vs tus alternativas del inversor AR. */}
          <DetailPortfolioBlocks ticker={data.ticker} data={data} />

          {data.analysts?.available && (
            <AnalystConsensus analysts={data.analysts} />
          )}

          <AISummaryCard ticker={data.ticker} />

          {/* DETALLE POR CATEGORÍA — desglose métrica por métrica (wave 3) */}
          {categoriesDetail.length > 0 && (
            <section className="space-y-3">
              <p className="text-[11px] font-mono uppercase tracking-label text-ink-2">
                Detalle por categoría
              </p>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {categoriesDetail.map(cat => (
                  <CategoryDetail
                    key={cat.key}
                    icon={CATEGORY_ICON[cat.key]}
                    label={cat.label}
                    question={cat.question}
                    score={cat.score}
                    metrics={cat.metrics}
                    onAsk={() => coachDrawer.open(
                      `Sobre ${data.company_name || data.ticker} (${data.ticker}) — ${cat.label}: ${cat.question || ''} `
                      + `Explicámelo en criollo mirando sus números fundamentales y cómo se compara con el resto del sector.`
                    )}
                  />
                ))}
              </div>
              <FooterStrip metrics={data.metrics} />
            </section>
          )}
        </div>
      )}
    </div>
  )
}

function ScorecardSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <div className="flex items-center gap-3">
        <Skeleton className="h-9 w-9 rounded-full" />
        <div className="space-y-2">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-3 w-24" />
        </div>
      </div>
      <Panel padding="lg">
        <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-6 items-center">
          <div className="flex justify-center">
            <Skeleton className="h-40 w-40 rounded-full" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[0, 1, 2, 3].map(i => (
              <Skeleton key={i} className="h-24 w-full rounded" />
            ))}
          </div>
        </div>
      </Panel>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Skeleton className="h-28 w-full rounded" />
        <Skeleton className="h-28 w-full rounded" />
      </div>
    </div>
  )
}
