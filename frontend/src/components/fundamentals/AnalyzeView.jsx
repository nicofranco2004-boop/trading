// AnalyzeView — vista "Analizar" de Fundamentals (scorecard de un ticker).
// ═══════════════════════════════════════════════════════════════════════════
// Es el cuerpo de la wave-1 (search + chips de posiciones + scorecard +
// resumen IA), extraído a un componente para convivir con las tabs
// Comparar/Favoritos. El ticker se sincroniza con ?ticker= a través del padre.
//
// props:
//   ticker     — ticker activo (string, upper)
//   onSelect   — (symbol) => void, sube la selección al padre (setea ?ticker=)
//   enFicha    — se muestra adentro de la ficha del activo (/activo/X), debajo
//                del análisis técnico: la MISMA vista, con tres diferencias. Sin
//                buscador. Sin el resumen con IA, que se pide solo al abrir y
//                gasta el cupo semanal: abriendo fichas desde el mapa de calor
//                se lo comía mirando. Y si la empresa no tiene fundamentales (o
//                no cargan), no ocupa lugar: la ficha sigue con lo demás.
//   alSaberSiHay — (ticker, hay) => void: cuando termina de cargar, avisa si la
//                empresa tiene fundamentales. La ficha lo usa para mostrar el
//                «Ordenar por» sólo si hay algo que ordenar.

import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import SeccionFicha from '../asset/SeccionFicha'
import {
  Search, Tag, TrendingUp, Zap, ShieldCheck, AlertCircle, Gauge, Coins, Scale,
} from 'lucide-react'
import Panel from '../Panel'
import Pill from '../Pill'
import InfoTooltip from '../InfoTooltip'
import EmptyState from '../EmptyState'
import Skeleton from '../Skeleton'
import AssetLogo from '../AssetLogo'
import { cashAssetLabel } from '../../utils/valuation'
import { pctTxt } from '../../utils/format'
import { api } from '../../utils/api'
import { empresaDeTenencias } from '../../utils/buscadorRapido'
import { track } from '../../utils/track'
import { useVoz } from '../../contexts/VozContext'

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
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2).replace('.', ',')}T`
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2).replace('.', ',')}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2).replace('.', ',')}M`
  return `${sign}$${abs.toFixed(0)}`
}

function fmtMultiple(n) {
  if (n == null || Number.isNaN(n)) return '—'
  return `${n.toFixed(2).replace('.', ',')}x`
}

function fmtBeta(n) {
  if (n == null || Number.isNaN(n)) return '—'
  return n.toFixed(2).replace('.', ',')
}

// FooterStrip — barra full-width de 4 celdas con métricas clave de mercado.
// Cada una con su «?» (el mismo InfoTooltip de las métricas de cada categoría):
// los nombres quedan en inglés, como los muestra todo el mundo, y la ayuda dice
// qué son en criollo (Nico, 28/10).
function FooterStrip({ metrics }) {
  const m = metrics || {}
  const cells = [
    { label: 'Market Cap', value: fmtMarketCap(m.market_cap_usd),
      info: 'Cuánto vale toda la empresa en la bolsa: el precio de una acción por la cantidad de acciones. En dólares: M = millones, B = miles de millones, T = millones de millones.' },
    { label: 'P/E', value: fmtMultiple(m.trailing_pe),
      info: 'Cuántos años de ganancia pagás al comprar: el precio de una acción dividido lo que ganó la empresa por acción en los últimos 12 meses. 20x = pagás 20 veces lo que gana en un año. Menor = más barato.' },
    { label: 'Div Yield', value: pctTxt(m.dividend_yield_pct, 2),
      info: 'Cuánto te paga por año en dividendos (la parte de la ganancia que la empresa reparte entre sus accionistas), contra el precio de hoy. 2% = US$ 2 por año por cada US$ 100 de acciones.' },
    { label: 'Beta', value: fmtBeta(m.beta),
      info: 'Cuánto se mueve contra la bolsa de Estados Unidos (el S&P 500). 1 = igual que la bolsa; 1,5 = si la bolsa sube o baja 10%, ésta suele moverse 15%; menos de 1 = más tranquila.' },
  ]
  return (
    <Panel padding="none">
      <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y sm:divide-y-0 divide-line">
        {cells.map(c => (
          <div key={c.label} className="px-4 py-3 text-center">
            <div className="flex items-center justify-center gap-1.5 mb-1">
              <span className="text-[12px] text-ink-3 font-medium">{c.label}</span>
              <InfoTooltip label={c.label} size={12} align="center">
                <p className="text-left">{c.info}</p>
              </InfoTooltip>
            </div>
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
      <p className="text-[12px] text-ink-3 mb-1.5 font-medium">{title}</p>
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

export default function AnalyzeView({ ticker, onSelect, watchlist, hideSearch = false, onCompareWith, enFicha = false, irACalidad = null, alSaberSiHay = null }) {
  const { analizar } = useVoz()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [positions, setPositions] = useState([])

  // Chips "Tus posiciones": la empresa de cada activo tuyo que tiene ficha,
  // con la misma regla que la ficha del activo y el buscador
  // (empresaDeTenencias, que mira en qué mercado está cada lote). Antes sólo
  // salían las acciones de EE.UU. según el ticker: Telecom (TECO2 → TEO) o YPF
  // (YPFD) no aparecían, y el CEDEAR de Disney abría "DISN" en vez de DIS.
  // Con el buscador oculto (hoy: siempre, en "Análisis fundamental") los chips no
  // se muestran y no se pide nada.
  const sinBuscador = hideSearch || enFicha
  const TituloEmpresa = enFicha ? 'h3' : 'h2'
  useEffect(() => {
    if (sinBuscador) return
    let cancelled = false
    Promise.all([api.get('/positions'), api.get('/brokers').catch(() => [])])
      .then(([list, bkrs]) => {
        if (cancelled) return
        const arr = Array.isArray(list) ? list : (list?.items || [])
        const brokers = Array.isArray(bkrs) ? bkrs : (bkrs?.items || [])
        const porActivo = new Map()
        for (const p of arr) {
          const asset = (p.asset || '').toUpperCase()
          if (!asset || p.is_cash) continue
          porActivo.set(asset, [...(porActivo.get(asset) || []), p])
        }
        const vistas = new Set()
        const empresas = []
        for (const [asset, lotes] of porActivo) {
          const empresa = empresaDeTenencias(lotes, brokers)
          if (!empresa || vistas.has(empresa.ticker)) continue
          vistas.add(empresa.ticker)
          empresas.push({ asset: empresa.ticker, tuyo: asset, is_cash: false })
        }
        setPositions(empresas)
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [sinBuscador])

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
        alSaberSiHay?.(ticker, !!res?.available)
        track('fundamentals_ticker_viewed', { ticker })
      })
      .catch(e => {
        if (cancelled) return
        alSaberSiHay?.(ticker, false)
        setError(e?.message || 'No pudimos cargar los fundamentales.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [ticker])

  const categories = data?.available ? (data.score?.categories || []) : []
  const categoriesDetail = data?.available ? (data.categories_detail || []) : []

  // En la ficha: sin fundamentales (cripto, ETF, bono, o no cargaron) no queda
  // un título suelto; con ellos, el título y el camino a "Análisis fundamental"
  // para compararla con otras.
  if (enFicha && !loading && !data?.available) return null

  const cuerpo = (
    <div>
      {/* Search card + chips de posiciones — se oculta cuando el buscador vive en
          el overlay global (modo detalle de "Análisis fundamental"). */}
      {!sinBuscador && (
      <Panel className="mb-6">
        <TickerSearch onSelect={onSelect} autoFocus={!ticker} />

        {positions.length > 0 && (
          <div className="mt-4">
            <p className="text-[12px] text-ink-3 mb-2 font-medium">
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
                  <AssetLogo asset={cashAssetLabel(p)} isCash={p.is_cash} size={20} />
                  <span className="font-mono text-xs font-medium">{p.asset}</span>
                  {p.tuyo.replace(/\.BA$/, '') !== p.asset && (
                    <span className="text-[11px] text-ink-3">tu {p.tuyo}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}
      </Panel>
      )}

      {/* Empty state — todavía no eligió ticker */}
      {!ticker && !loading && !enFicha && (
        <Panel padding="lg">
          <EmptyState
            icon={<Gauge size={20} strokeWidth={1.75} />}
            eyebrow="Análisis fundamental"
            title="Buscá un activo o tocá una de tus posiciones"
            description="Escribí un ticker (NVDA, AAPL, MELI…) o elegí algo que ya tengas. Vas a ver qué tan sólido es el negocio, si el precio de hoy lo acompaña y un resumen en criollo."
          />
        </Panel>
      )}

      {loading && <ScorecardSkeleton />}

      {!loading && error && ticker && !enFicha && (
        <Panel padding="lg">
          <div className="flex items-start gap-2 text-sm text-rendi-neg">
            <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        </Panel>
      )}

      {/* available:false */}
      {!loading && !error && data && data.available === false && !enFicha && (
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
                {/* En la ficha va adentro de la sección «Análisis fundamental» (h2): es un h3. */}
                <TituloEmpresa className="text-lg font-semibold text-ink-0 leading-tight">
                  {data.company_name || data.ticker}
                </TituloEmpresa>
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
                  <span className="text-[12px] text-ink-3 font-medium">
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
          {/* En la ficha (ancha), los dos bloques lado a lado; en Calidad de
              cartera, uno abajo del otro como siempre. */}
          <div className={enFicha ? 'grid grid-cols-1 xl:grid-cols-2 gap-6 xl:items-start' : 'space-y-6'}>
            <DetailPortfolioBlocks ticker={data.ticker} data={data} />
          </div>

          {data.analysts?.available && (
            <AnalystConsensus analysts={data.analysts} />
          )}

          {!enFicha && <AISummaryCard ticker={data.ticker} />}

          {/* DETALLE POR CATEGORÍA — desglose métrica por métrica (wave 3) */}
          {categoriesDetail.length > 0 && (
            <section className="space-y-3">
              <p className="text-[12.5px] text-ink-2 font-medium">
                Detalle por categoría
              </p>
              <div className={`grid grid-cols-1 lg:grid-cols-2 gap-4 ${enFicha ? '2xl:grid-cols-3' : ''}`}>
                {categoriesDetail.map(cat => (
                  <CategoryDetail
                    key={cat.key}
                    icon={CATEGORY_ICON[cat.key]}
                    label={cat.label}
                    question={cat.question}
                    score={cat.score}
                    metrics={cat.metrics}
                    onAsk={() => analizar({
                      screen: 'fundamentals.category',
                      params: { asset: data.ticker, category: cat.key },
                    })}
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
  // En la ficha, la sección con su título (SeccionFicha, la misma de las otras)
  // y el camino a "Análisis fundamental" para compararla con otras.
  if (!enFicha) return cuerpo
  return (
    <SeccionFicha titulo="Análisis fundamental"
      accion={irACalidad && (
        <Link to={irACalidad} className="inline-flex items-center min-h-10 sm:min-h-0 text-[13px] text-data-violet hover:underline">
          Compararla en Análisis fundamental →
        </Link>
      )}>
      {cuerpo}
    </SeccionFicha>
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
