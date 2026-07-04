// Events — calendario de eventos financieros con tabs "Para ti" / "Popular".
// ════════════════════════════════════════════════════════════════════════════
// Diseño fintech denso (no foro):
//
//   ┌───────────────────────────────────────────────────────────────┐
//   │ KPI strip (4 celdas) — próximo, total, cupones, confirmados   │
//   ├───────────────────────────────────────────────────────────────┤
//   │ Controles: ventana | filtro tipo                              │
//   ├───────────────────────────────────────────────────────────────┤
//   │ Timeline strip — barras por día, altura = #eventos            │
//   ├───────────────────────────────────────────────────────────────┤
//   │ Tabla densa — DÍA | ACTIVO | TIPO | DETALLE | MONTO | IMPACT  │
//   └───────────────────────────────────────────────────────────────┘
//
// Dos vistas (sub-tabs):
//   • Para ti: eventos del PORTFOLIO. Impact % = porcentaje del portfolio.
//   • Popular: eventos del MERCADO. Earnings populares + macro.

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSearchParams } from 'react-router-dom'
import { Calendar, Filter, AlertCircle, Eye, Sparkles } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import AssetLogo from '../components/AssetLogo'
import EventBadge from '../components/EventBadge'
import { api } from '../utils/api'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import InlineAIButton from '../components/ai/InlineAIButton'
import { computeBrokerValue, priceSymbol } from '../utils/valuation'
import { pct } from '../utils/format'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'
import {
  upcomingBondEvents,
  normalizeBackendEvents,
  mergeEvents,
  formatRelativeDate,
  countryFlag,
  isMacroEvent,
} from '../utils/upcomingEvents'

const WINDOW_OPTIONS = [
  { value: 30,  label: '30D' },
  { value: 90,  label: '90D' },
  { value: 180, label: '6M' },
  { value: 365, label: '1Y' },
]

const FILTER_OPTIONS = [
  { value: 'all',       label: 'Todos' },
  { value: 'macro',     label: 'Macro' },
  { value: 'earnings',  label: 'Earnings' },
  { value: 'dividends', label: 'Dividendos' },
  { value: 'bonds',     label: 'Bonos' },
]

const TABS = [
  { value: 'portfolio', label: 'Para ti', desc: 'Eventos de los activos de tu portfolio' },
  { value: 'popular',   label: 'Populares', desc: 'Eventos del mercado y empresas top' },
]
const TAB_VALUES = TABS.map(t => t.value)

function matchesFilter(event, filter) {
  if (filter === 'all') return true
  if (filter === 'bonds') return event.eventType?.startsWith('bond_')
  if (filter === 'earnings') return event.eventType === 'earnings'
  if (filter === 'dividends') return event.eventType === 'ex_dividend' || event.eventType === 'payment_date'
  if (filter === 'macro') return event.eventType === 'macro'
  return true
}

// Si `embedded=true`, sin PageHeader y el sub-tab se persiste en URL (?sub=…).
export default function Events({ embedded = false }) {
  const { valuationDollar } = useCurrency()
  const [searchParams, setSearchParams] = useSearchParams()
  const urlSub = searchParams.get('sub')
  const initialTab = embedded && TAB_VALUES.includes(urlSub) ? urlSub : 'portfolio'
  const [tab, setTabState] = useState(initialTab)

  useEffect(() => {
    if (!embedded) return
    const s = searchParams.get('sub')
    if (TAB_VALUES.includes(s) && s !== tab) setTabState(s)
  }, [searchParams, embedded, tab])

  function setTab(value) {
    setTabState(value)
    if (embedded) {
      const next = new URLSearchParams(searchParams)
      next.set('sub', value)
      setSearchParams(next, { replace: true })
    }
  }

  const [windowDays, setWindowDays] = useState(90)
  const [filter, setFilter] = useState('all')
  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [config, setConfig] = useState({ tc_blue: 1415 })
  const [dolar, setDolar] = useState(null)
  const [portfolioEvents, setPortfolioEvents] = useState([])
  const [popularEvents, setPopularEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowDays])

  async function loadAll() {
    setLoading(true)
    setError(null)
    try {
      const [pos, bkrs, cfg, dol, portEv, popEv] = await Promise.all([
        api.get('/positions'),
        api.get('/brokers'),
        api.get('/config'),
        api.get('/dolar').catch(() => null),
        api.get(`/events/portfolio?days=${windowDays}`).catch(() => ({ events: [] })),
        api.get(`/events/popular?days=${windowDays}`).catch(() => ({ events: [] })),
      ])
      setPositions(pos || [])
      setBrokers(bkrs || [])
      setConfig(cfg || { tc_blue: 1415 })
      setDolar(dol)
      setPortfolioEvents(portEv?.events || [])
      setPopularEvents(popEv?.events || [])
      const symList = collectPriceSymbols(pos || [], bkrs || [])
      if (symList.length > 0) {
        try {
          const p = await api.get(`/prices?symbols=${symList.join(',')}`)
          setPrices(p || {})
        } catch {}
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  // Valor total del portfolio en USD (para impact %)
  const tcBlue = pickFinancialRate(dolar, valuationDollar) || config.tc_blue || 1415
  const tcCedear = pickFinancialRate(dolar, valuationDollar) || tcBlue  // dólar financiero p/ CEDEARs
  const tcCripto = dolar?.cripto?.venta
  const portfolioTotalUsd = useMemo(() => {
    return brokers.reduce((sum, broker) => {
      const bpos = positions.filter(p => p.broker === broker.name)
      const v = computeBrokerValue(bpos, prices, broker, tcBlue, tcCedear, tcCripto)
      return sum + (v.value || 0)
    }, 0)
  }, [positions, brokers, prices, tcBlue])

  // Valor USD por ticker
  const tickerValueUsd = useMemo(() => {
    const map = new Map()
    for (const broker of brokers) {
      const bpos = positions.filter(p => p.broker === broker.name)
      for (const p of bpos) {
        if (p.is_cash) continue
        const r = computeBrokerValue([p], prices, broker, tcBlue, tcCedear, tcCripto)
        const prev = map.get(p.asset) || 0
        map.set(p.asset, prev + (r.value || 0))
      }
    }
    return map
  }, [positions, brokers, prices, tcBlue])

  // Acciones (cantidad) por ticker — para "tenés N acc → cobrás $X".
  const tickerShares = useMemo(() => {
    const map = new Map()
    for (const p of positions) {
      if (p.is_cash || !p.quantity) continue
      map.set(p.asset, (map.get(p.asset) || 0) + p.quantity)
    }
    return map
  }, [positions])

  // Tickers que el user tiene (para flag en tab Popular)
  const userTickerSet = useMemo(() => {
    return new Set(positions.filter(p => !p.is_cash).map(p => p.asset))
  }, [positions])

  // Eventos según tab + filter
  const visibleEvents = useMemo(() => {
    if (tab === 'portfolio') {
      const bonds = upcomingBondEvents(positions, { windowDays })
      const stocks = normalizeBackendEvents(portfolioEvents)
      return mergeEvents(bonds, stocks).filter(e => matchesFilter(e, filter))
    }
    return normalizeBackendEvents(popularEvents)
      .map(e => ({ ...e, inPortfolio: userTickerSet.has(e.ticker) }))
      .filter(e => matchesFilter(e, filter))
  }, [tab, positions, portfolioEvents, popularEvents, filter, windowDays, userTickerSet])

  // KPI metrics — calculadas del set de eventos sin filtro (más estable)
  const kpiEvents = useMemo(() => {
    if (tab === 'portfolio') {
      const bonds = upcomingBondEvents(positions, { windowDays })
      const stocks = normalizeBackendEvents(portfolioEvents)
      return mergeEvents(bonds, stocks)
    }
    return normalizeBackendEvents(popularEvents)
      .map(e => ({ ...e, inPortfolio: userTickerSet.has(e.ticker) }))
  }, [tab, positions, portfolioEvents, popularEvents, windowDays, userTickerSet])

  // Spotlight — el próximo evento del portfolio (el más cercano, ya no pasado).
  const nextEvent = useMemo(() => {
    if (tab !== 'portfolio') return null
    const upcoming = visibleEvents
      .filter(e => { const d = daysUntil(e.eventDate); return d != null && d >= 0 })
      .sort((a, b) => (a.eventDate || '').localeCompare(b.eventDate || ''))
    return upcoming[0] || null
  }, [tab, visibleEvents])

  const containerClass = embedded ? '' : 'page-shell-wide'
  return (
    <div className={containerClass}>
      {!embedded && (
        <PageHeader
          title="Eventos financieros"
          subtitle="Próximos cupones, earnings, dividendos y eventos macro."
          action={<AnalyzeButton screen="events" subtitle="Tu calendario completo" />}
        />
      )}

      {/* Sub-tabs Para ti / Popular — pills. */}
      <div
        role="tablist"
        aria-label="Tipo de eventos"
        className="flex items-center gap-1.5 mb-4 flex-wrap"
      >
        {TABS.map(t => {
          const active = tab === t.value
          return (
            <button
              key={t.value}
              role="tab"
              aria-selected={active}
              onClick={() => setTab(t.value)}
              className={`text-xs px-3 py-1.5 rounded-full border transition ${
                active
                  ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40 font-semibold'
                  : 'bg-bg-2 text-ink-2 border-line hover:bg-bg-3'
              }`}
            >
              {t.label}
            </button>
          )
        })}
      </div>

      {/* Briefing de eventos — CTA on-demand. Reusa el topic `events`
          (una sola llamada IA). NO se auto-genera: dispara solo al click. */}
      {embedded && (
        <div className="flex items-center gap-3 bg-bg-1 border border-data-violet/30 rounded-lg p-3.5 mb-4">
          <div className="w-9 h-9 rounded-lg bg-data-violet/15 flex items-center justify-center shrink-0">
            <Sparkles size={18} strokeWidth={1.75} className="text-data-violet" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-ink-0">Briefing de eventos con IA</p>
            <p className="text-xs text-ink-2 mt-0.5">
              Qué se viene en tu cartera y cuáles te pegan más, resumido.
            </p>
          </div>
          <AnalyzeButton screen="events" subtitle="Briefing de eventos" label="Generar briefing" />
        </div>
      )}

      {/* Spotlight — el próximo evento que más te toca, con tu cobro/impacto
          ya calculado. Solo en "Para ti" (portfolio) y si hay evento próximo. */}
      {!loading && nextEvent && (
        <SpotlightHero
          event={nextEvent}
          impactPct={(tickerValueUsd && portfolioTotalUsd > 0)
            ? (tickerValueUsd.get(nextEvent.ticker) || 0) / portfolioTotalUsd
            : null}
          cobro={eventCobro(nextEvent, tickerShares)}
          onView={() => navigate(`/activo/${encodeURIComponent(nextEvent.ticker)}`)}
        />
      )}

      {/* KPI Strip — 3 celdas con divisores. Padding más chico en mobile. */}
      <div className="bg-bg-1 border border-line rounded mb-4 grid grid-cols-3 divide-x divide-line">
        <KpiStripCells events={kpiEvents} tab={tab} windowDays={windowDays} />
      </div>

      {/* Controles: ventana + filtro — compactos, una sola línea cuando hay espacio. */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3 mb-4 px-1">
        <ControlGroup icon={<Calendar size={12} strokeWidth={1.75} />} label="Ventana">
          {WINDOW_OPTIONS.map(opt => (
            <ControlPill
              key={opt.value}
              active={windowDays === opt.value}
              onClick={() => setWindowDays(opt.value)}
            >{opt.label}</ControlPill>
          ))}
        </ControlGroup>
        <ControlGroup icon={<Filter size={12} strokeWidth={1.75} />} label="Tipo">
          {FILTER_OPTIONS.map(opt => (
            <ControlPill
              key={opt.value}
              active={filter === opt.value}
              onClick={() => setFilter(opt.value)}
            >{opt.label}</ControlPill>
          ))}
        </ControlGroup>
      </div>

      {/* Timeline strip — mini-viz de eventos por día. En "Para ti" la altura
          de cada barra pondera el impacto en tu cartera, no solo el conteo. */}
      {!loading && kpiEvents.length > 0 && (
        <TimelineStrip
          events={visibleEvents}
          windowDays={windowDays}
          tab={tab}
          tickerValueUsd={tickerValueUsd}
          portfolioTotalUsd={portfolioTotalUsd}
        />
      )}

      {loading && <EventTableSkeleton />}
      {error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-sm bg-rendi-warn/10 text-rendi-warn text-sm">
          <AlertCircle size={14} /> {error}
        </div>
      )}
      {!loading && !error && visibleEvents.length === 0 && (
        <EmptyState
          icon={<Calendar size={32} />}
          title="Sin eventos en este rango"
          subtitle={tab === 'portfolio'
            ? `No hay pagos, earnings ni dividendos del portfolio en los próximos ${windowDays} días.`
            : `No hay eventos macro ni earnings de tickers populares en los próximos ${windowDays} días.`}
        />
      )}

      {/* Tabla densa — la lista principal. */}
      {!loading && visibleEvents.length > 0 && (
        <EventTable
          events={visibleEvents}
          tab={tab}
          tickerValueUsd={tickerValueUsd}
          portfolioTotalUsd={portfolioTotalUsd}
          tickerShares={tickerShares}
        />
      )}

      <p className="mt-6 text-[10px] text-ink-3 font-mono leading-snug">
        {tab === 'portfolio'
          ? 'Bonos: cronograma teórico (bondSchedule). Earnings/dividendos via yfinance — fechas estimadas hasta confirmación oficial.'
          : 'Macro: calendario oficial (Fed, BLS, INDEC). Earnings via yfinance — estimadas hasta confirmación.'}
      </p>
    </div>
  )
}

// ─── KPI Strip ──────────────────────────────────────────────────────────────

function KpiStripCells({ events, tab, windowDays }) {
  const sorted = useMemo(
    () => [...events].sort((a, b) => (a.eventDate || '').localeCompare(b.eventDate || '')),
    [events]
  )
  const next = sorted[0]
  const total = events.length
  const confirmedCount = events.filter(e => e.confirmed).length
  const confirmedPct = total > 0 ? confirmedCount / total : 0

  // Countdown del próximo evento.
  const daysToNext = next ? daysUntil(next.eventDate) : null
  const nextLabel = daysToNext == null
    ? '—'
    : daysToNext === 0 ? 'HOY'
    : daysToNext === 1 ? 'MAÑANA'
    : `EN ${daysToNext}D`

  const nextSubLabel = next
    ? (isMacroEvent(next) ? (next.details?.title || 'macro') : next.ticker)
    : 'sin eventos próximos'

  // Tercera celda: cambia según tab.
  //   • Portfolio → Confirmados (cuántos eventos están confirmados por la fuente).
  //   • Popular   → En tu cartera (cuántos te impactan).
  const inPortfolioCount = tab === 'popular'
    ? events.filter(e => e.inPortfolio).length
    : null

  return (
    <>
      <KpiCell
        label="Próximo"
        value={nextLabel}
        sub={nextSubLabel}
        tone={daysToNext === 0 || daysToNext === 1 ? 'accent' : 'neutral'}
      />
      <KpiCell
        label={`Total ${windowDays}D`}
        value={total}
        sub={total === 1 ? 'evento' : 'eventos'}
      />
      {tab === 'popular' ? (
        <KpiCell
          label="En tu cartera"
          value={inPortfolioCount}
          sub={`de ${total}`}
          tone={inPortfolioCount > 0 ? 'accent' : 'neutral'}
        />
      ) : (
        <KpiCell
          label="Confirmados"
          value={`${Math.round(confirmedPct * 100)}%`}
          sub={`${confirmedCount}/${total}`}
        />
      )}
    </>
  )
}

function KpiCell({ label, value, sub, tone = 'neutral' }) {
  const valueColor =
    tone === 'pos'    ? 'text-rendi-pos' :
    tone === 'accent' ? 'text-rendi-accent' :
    tone === 'warn'   ? 'text-rendi-warn' :
                        'text-ink-0'
  return (
    <div className="px-3 sm:px-4 py-3 min-w-0">
      <p className="label-mono">{label}</p>
      <p className={`data-hero ${valueColor} mt-1 truncate`}>{value}</p>
      {sub && <p className="mt-0.5 text-[11px] font-mono text-ink-3 truncate">{sub}</p>}
    </div>
  )
}

// ─── Controls ───────────────────────────────────────────────────────────────

function ControlGroup({ icon, label, children }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-ink-3">{icon}</span>
      <span className="label-mono">{label}</span>
      <div className="flex items-center gap-1">{children}</div>
    </div>
  )
}

function ControlPill({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`text-[11px] font-mono px-2 py-1 rounded-sm border transition ${
        active
          ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40'
          : 'bg-bg-2 text-ink-2 border-line hover:bg-bg-3 hover:text-ink-1'
      }`}
    >
      {children}
    </button>
  )
}

// ─── Timeline strip ─────────────────────────────────────────────────────────
//
// Visualización fintech: barras verticales una por día. Altura proporcional
// a #eventos. Color: rendi-accent (bonos/portfolio), purple (earnings),
// blue (dividendos), green/warn (macro). Hover muestra detalle.

function TimelineStrip({ events, windowDays, tab, tickerValueUsd, portfolioTotalUsd }) {
  const buckets = useMemo(
    () => buildDayBuckets(events, windowDays, tickerValueUsd, portfolioTotalUsd),
    [events, windowDays, tickerValueUsd, portfolioTotalUsd]
  )
  if (buckets.every(b => b.total === 0)) return null

  // En "Para ti" la altura pondera el impacto en tu cartera; si no hay impacto
  // (tab popular o tickers sin posición) caemos al conteo de eventos.
  const useImpact = tab === 'portfolio' && buckets.some(b => b.impact > 0)
  const metric = (b) => (useImpact ? b.impact : b.total)
  const maxMetric = Math.max(1e-9, ...buckets.map(metric))

  return (
    <div className="bg-bg-1 border border-line rounded mb-4 p-3 sm:p-4">
      <div className="flex items-center justify-between mb-2">
        <p className="label-mono">{useImpact ? 'Distribución · por impacto' : 'Distribución'}</p>
        <p className="text-[10px] font-mono text-ink-3 tracking-wider uppercase">
          {windowDays} días · {events.length} {events.length === 1 ? 'evento' : 'eventos'}
        </p>
      </div>
      <div className="relative">
        <div className="flex items-end gap-[2px] h-12 sm:h-14">
          {buckets.map(b => {
            const h = b.total > 0 ? Math.max(8, (metric(b) / maxMetric) * 100) : 4
            // Color del segmento más dominante de ese día
            const tone = b.total === 0
              ? 'bg-line/40'
              : dominantTone(b)
            return (
              <div
                key={b.iso}
                title={`${b.label} · ${b.total} ${b.total === 1 ? 'evento' : 'eventos'}`}
                className="flex-1 min-w-[3px] relative group flex flex-col justify-end h-full"
              >
                <div
                  className={`w-full rounded-sm ${tone} transition-opacity opacity-80 group-hover:opacity-100`}
                  style={{ height: `${h}%` }}
                />
              </div>
            )
          })}
        </div>
        {/* Etiquetas de inicio / mitad / fin */}
        <div className="flex justify-between mt-1 text-[9px] font-mono text-ink-3 tracking-wider uppercase">
          <span>Hoy</span>
          <span>+{Math.round(windowDays / 2)}d</span>
          <span>+{windowDays}d</span>
        </div>
      </div>
    </div>
  )
}

function buildDayBuckets(events, windowDays, tickerValueUsd, portfolioTotalUsd) {
  // Resolución adaptativa — si windowDays > 90, agrupamos por semanas para
  // que la barra no se vea como una línea uniforme.
  const bucketSize = windowDays <= 30 ? 1 : windowDays <= 90 ? 2 : 7
  const numBuckets = Math.ceil(windowDays / bucketSize)
  const today = new Date()
  today.setHours(0, 0, 0, 0)

  const buckets = Array.from({ length: numBuckets }, (_, i) => {
    const start = new Date(today.getTime() + i * bucketSize * 86400000)
    return {
      iso: start.toISOString().slice(0, 10),
      label: formatBucketLabel(start, bucketSize),
      total: 0,
      impact: 0,
      bonds: 0,
      earnings: 0,
      dividends: 0,
      macro: 0,
    }
  })

  const hasImpact = tickerValueUsd && portfolioTotalUsd > 0
  for (const ev of events) {
    if (!ev.eventDate) continue
    const d = new Date(ev.eventDate + 'T00:00:00')
    const diff = Math.floor((d.getTime() - today.getTime()) / 86400000)
    if (diff < 0 || diff >= windowDays) continue
    const idx = Math.floor(diff / bucketSize)
    if (idx >= numBuckets) continue
    const b = buckets[idx]
    b.total += 1
    if (hasImpact) b.impact += (tickerValueUsd.get(ev.ticker) || 0) / portfolioTotalUsd
    if (ev.eventType?.startsWith('bond_')) b.bonds += 1
    else if (ev.eventType === 'earnings') b.earnings += 1
    else if (ev.eventType === 'ex_dividend' || ev.eventType === 'payment_date') b.dividends += 1
    else if (ev.eventType === 'macro') b.macro += 1
  }

  return buckets
}

function dominantTone(bucket) {
  // Pick highest-count category for the visual tone.
  const cats = [
    { n: bucket.bonds,     cls: 'bg-amber-500/70  dark:bg-amber-400/70' },
    { n: bucket.earnings,  cls: 'bg-purple-500/70 dark:bg-purple-400/70' },
    { n: bucket.dividends, cls: 'bg-blue-500/70   dark:bg-blue-400/70' },
    { n: bucket.macro,     cls: 'bg-rendi-pos/70' },
  ]
  cats.sort((a, b) => b.n - a.n)
  return cats[0].n > 0 ? cats[0].cls : 'bg-ink-3/30'
}

function formatBucketLabel(date, bucketSize) {
  if (bucketSize === 1) {
    return formatRelativeDate(date.toISOString().slice(0, 10))
  }
  const end = new Date(date.getTime() + (bucketSize - 1) * 86400000)
  const fmt = (d) => d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short' }).replace('.', '')
  return `${fmt(date)} → ${fmt(end)}`
}

// ─── Event Table ────────────────────────────────────────────────────────────

function EventTableSkeleton() {
  return (
    <div className="bg-bg-1 border border-line rounded overflow-hidden">
      <div className="hidden md:grid grid-cols-[80px_180px_100px_1fr_140px_80px] gap-3 px-4 py-2 border-b border-line bg-bg-2/40">
        <div className="label-mono">Fecha</div>
        <div className="label-mono">Activo</div>
        <div className="label-mono">Tipo</div>
        <div className="label-mono">Detalle</div>
        <div className="label-mono text-right">Monto</div>
        <div className="label-mono text-right">Impact</div>
      </div>
      <ul className="divide-y divide-line/40">
        {[1,2,3,4,5,6,7].map(i => (
          <li key={i} className="grid grid-cols-[64px_1fr] md:grid-cols-[80px_180px_100px_1fr_140px_80px] gap-3 px-4 py-3 items-center animate-pulse">
            <div className="h-4 w-12 bg-bg-3 rounded" />
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-sm bg-bg-3" />
              <div className="h-4 w-20 bg-bg-3 rounded" />
            </div>
            <div className="hidden md:block h-4 w-16 bg-bg-3 rounded" />
            <div className="hidden md:block h-3 w-3/4 bg-bg-3/60 rounded" />
            <div className="hidden md:block h-4 w-16 bg-bg-3 rounded ml-auto" />
            <div className="hidden md:block h-3 w-8 bg-bg-3/60 rounded ml-auto" />
          </li>
        ))}
      </ul>
    </div>
  )
}


function EventTable({ events, tab, tickerValueUsd, portfolioTotalUsd, tickerShares }) {
  // Agrupamos por cercanía (Esta semana / 2 semanas / Más adelante) para dar
  // ritmo a la lista en vez de un muro plano ordenado por fecha.
  const groups = useMemo(() => groupByRecency(events), [events])

  return (
    <div className="bg-bg-1 border border-line rounded overflow-hidden">
      {/* Header — pinned, label-mono columns */}
      <div className="hidden md:grid grid-cols-[80px_180px_100px_1fr_140px_80px_96px] gap-3 px-4 py-2 border-b border-line bg-bg-2/40">
        <div className="label-mono">Fecha</div>
        <div className="label-mono">Activo</div>
        <div className="label-mono">Tipo</div>
        <div className="label-mono">Detalle</div>
        <div className="label-mono text-right">Monto</div>
        <div className="label-mono text-right">{tab === 'portfolio' ? 'Impact' : 'Cartera'}</div>
        <div className="label-mono text-right" title="Analizar"></div>
      </div>
      {groups.map(g => (
        <div key={g.label}>
          <div className="px-4 py-1.5 bg-bg-2/30 border-b border-line/50 flex items-center gap-2">
            <span className="text-[11px] font-mono uppercase tracking-wider text-ink-3">{g.label}</span>
            <span className="text-[11px] font-mono text-ink-3/70">· {g.events.length}</span>
          </div>
          <ul className="divide-y divide-line/40">
            {g.events.map((ev, i) => (
              <EventRow
                key={`${ev.ticker}:${ev.eventType}:${ev.eventDate}:${i}`}
                event={ev}
                tab={tab}
                tickerValueUsd={tickerValueUsd}
                portfolioTotalUsd={portfolioTotalUsd}
                tickerShares={tickerShares}
              />
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

function groupByRecency(events) {
  const sorted = [...events].sort((a, b) => (a.eventDate || '').localeCompare(b.eventDate || ''))
  const week = [], twoWeek = [], later = []
  for (const ev of sorted) {
    const d = daysUntil(ev.eventDate)
    if (d != null && d <= 7) week.push(ev)
    else if (d != null && d <= 14) twoWeek.push(ev)
    else later.push(ev)
  }
  return [
    { label: 'Esta semana', events: week },
    { label: 'Próximas 2 semanas', events: twoWeek },
    { label: 'Más adelante', events: later },
  ].filter(g => g.events.length > 0)
}

function EventRow({ event, tab, tickerValueUsd, portfolioTotalUsd, tickerShares }) {
  const { ticker, eventType, eventDate, confirmed, inPortfolio, details } = event
  const isMacro = isMacroEvent(event)
  const cobro = tab === 'portfolio' ? eventCobro(event, tickerShares) : null
  const country = details?.country
  const macroTitle = details?.title

  const impactPct = (tab === 'portfolio' && tickerValueUsd && portfolioTotalUsd > 0)
    ? (tickerValueUsd.get(ticker) || 0) / portfolioTotalUsd
    : null

  const daysToEvent = daysUntil(eventDate)
  // dateTone con guard explícito para null/NaN (eventDate inválido).
  const dateTone =
    daysToEvent == null    ? 'text-ink-3' :
    daysToEvent === 0      ? 'text-rendi-accent' :
    daysToEvent <= 1       ? 'text-ink-0' :
                             'text-ink-2'
  const countdownLabel =
    daysToEvent == null    ? '—' :
    daysToEvent === 0      ? 'HOY' :
    daysToEvent === 1      ? 'MAÑANA' :
                             `+${daysToEvent}D`

  const amountNode = renderAmount(event)
  const detailNode = renderDetail(event)

  return (
    <li className="grid grid-cols-[64px_1fr_auto] md:grid-cols-[80px_180px_100px_1fr_140px_80px_96px] gap-3 px-4 py-3 items-center hover:bg-bg-2/40 transition-colors">
      {/* Fecha — countdown + fecha corta abajo */}
      <div className="flex flex-col">
        <span className={`text-xs font-mono font-semibold uppercase tracking-wider ${dateTone}`}>
          {countdownLabel}
        </span>
        <span className="text-[10px] font-mono text-ink-3 mt-0.5">
          {shortDate(eventDate)}
        </span>
      </div>

      {/* Activo: logo + ticker — en mobile ocupa el resto del row */}
      <div className="flex items-center gap-2.5 min-w-0">
        {isMacro ? (
          <div className="w-7 h-7 rounded-sm bg-bg-3 border border-line flex items-center justify-center text-base flex-shrink-0">
            {countryFlag(country)}
          </div>
        ) : (
          <AssetLogo asset={ticker} size={28} />
        )}
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="font-semibold text-ink-0 text-sm tabular truncate">
              {isMacro ? macroTitle || ticker : ticker}
            </span>
            {tab === 'popular' && inPortfolio && (
              <span title="En tu cartera" className="text-rendi-accent shrink-0">
                <Eye size={11} strokeWidth={2} />
              </span>
            )}
          </div>
          {/* En mobile mostramos tipo + detalle aquí, en desktop van en columnas */}
          <div className="md:hidden flex items-center gap-2 mt-0.5 text-[11px] text-ink-2 font-mono">
            <EventBadge eventType={eventType} />
            <span className="truncate">{detailNode}</span>
          </div>
        </div>
      </div>

      {/* Tipo — solo desktop */}
      <div className="hidden md:flex items-center">
        <EventBadge eventType={eventType} />
      </div>

      {/* Detalle — solo desktop */}
      <div className="hidden md:block text-[12px] text-ink-2 font-mono leading-snug truncate">
        {detailNode}
        {!confirmed && <span className="ml-1 text-ink-3 opacity-70">· est.</span>}
      </div>

      {/* Monto — cobro estimado total si sabemos tus acciones; si no, el
          monto por acción / teórico. */}
      <div className="hidden md:block text-right text-sm font-mono tabular">
        {cobro?.amount != null ? (
          <div className="leading-tight">
            <span className="text-rendi-pos">+{cobro.currency === 'USD' ? '$' : `${cobro.currency} `}{formatCompact(cobro.amount)}</span>
            {cobro.shares ? (
              <div className="text-[10px] text-ink-3">{formatCompact(cobro.shares)} acc</div>
            ) : null}
          </div>
        ) : amountNode}
      </div>

      {/* Impact / Cartera — sólo desktop, sólo si aplica */}
      <div className="hidden md:block text-right text-xs font-mono">
        {tab === 'portfolio' && impactPct != null && impactPct > 0.0001 ? (
          <span className="text-rendi-accent">{pct(impactPct)}</span>
        ) : tab === 'popular' && inPortfolio ? (
          <span className="text-rendi-accent text-[10px] tracking-wider uppercase">SÍ</span>
        ) : (
          <span className="text-ink-3">—</span>
        )}
      </div>

      {/* Mobile: monto + impact en una fila pegada al ticker */}
      <div className="md:hidden col-start-2 -mt-1 flex items-center justify-end gap-2 text-xs font-mono tabular">
        {cobro?.amount != null
          ? <span className="text-rendi-pos">+{cobro.currency === 'USD' ? '$' : `${cobro.currency} `}{formatCompact(cobro.amount)}</span>
          : amountNode}
        {tab === 'portfolio' && impactPct != null && impactPct > 0.0001 && (
          <span className="text-rendi-accent">· {pct(impactPct)}</span>
        )}
      </div>

      {/* Botón ✦ — análisis del evento individual. Solo si no es macro
          (no tenemos contexto de portfolio para macros). */}
      <div className="row-start-1 row-span-2 md:row-auto md:col-start-7 flex items-start md:items-center justify-end">
        {!isMacro && (
          <InlineAIButton
            topic="events.item"
            params={{
              ticker,
              event_type: eventType,
              event_date: eventDate,
              details: typeof details === 'string' ? details : (details?.title || ''),
            }}
            subtitle={`${ticker} · ${eventType}`}
            label="Analizar"
          />
        )}
      </div>
    </li>
  )
}

function renderDetail(event) {
  const { eventType, details } = event
  if (eventType === 'macro') {
    return `${details?.country || ''} · ${macroCategoryLabel(details?.category)}`
  }
  if (eventType === 'earnings') {
    return details?.eps_estimate != null
      ? `EPS est. $${details.eps_estimate}`
      : 'Resultados trimestrales'
  }
  if (eventType === 'ex_dividend') {
    return details?.dividend_per_share != null
      ? `Div $${details.dividend_per_share}/acción`
      : 'Fecha ex-dividendo'
  }
  if (eventType?.startsWith('bond_')) {
    const cur = details?.currency || 'USD'
    if (details?.coupon > 0 && details?.amort > 0) {
      return `Cupón ${cur} ${details.coupon.toFixed(2)} + amort ${cur} ${details.amort.toFixed(2)}`
    }
    if (details?.coupon > 0) return `Cupón ${cur} ${details.coupon.toFixed(2)}`
    if (details?.amort > 0)  return `${eventType === 'bond_maturity' ? 'Vencimiento' : 'Amortización'} ${cur} ${details.amort.toFixed(2)}`
  }
  return ''
}

function renderAmount(event) {
  const { eventType, details } = event
  if (eventType?.startsWith('bond_') && typeof details?.total === 'number') {
    const cur = details.currency || 'USD'
    return (
      <span className="text-rendi-pos">
        +{cur} {formatCompact(details.total)}
      </span>
    )
  }
  if (eventType === 'ex_dividend' && details?.dividend_per_share != null) {
    return (
      <span className="text-rendi-pos">+${details.dividend_per_share}/acc</span>
    )
  }
  if (eventType === 'earnings') {
    return <span className="text-ink-3">—</span>
  }
  if (eventType === 'macro') {
    return <span className="text-ink-3">—</span>
  }
  return <span className="text-ink-3">—</span>
}

// Cobro estimado del evento según tus acciones.
//   • Bono: details.total ya es el total (coupon×qty, calculado en upcomingBondEvents).
//   • Dividendo: dividend_per_share × acciones que tenés.
//   • Otros (earnings, macro): sin cobro.
function eventCobro(event, sharesMap) {
  const { eventType, details, ticker } = event
  if (eventType?.startsWith('bond_') && typeof details?.total === 'number') {
    return { amount: details.total, currency: details.currency || 'USD', shares: sharesMap?.get(ticker) || null }
  }
  if (eventType === 'ex_dividend' && details?.dividend_per_share != null) {
    const shares = sharesMap?.get(ticker) || 0
    if (shares > 0) {
      return { amount: details.dividend_per_share * shares, currency: 'USD', shares, perShare: details.dividend_per_share }
    }
    return { amount: null, currency: 'USD', shares: null, perShare: details.dividend_per_share }
  }
  return null
}

// ─── Spotlight hero ─────────────────────────────────────────────────────────
// El próximo evento que más te toca, arriba de todo, con tu cobro/impacto ya
// calculado. Solo se muestra en "Para ti".
function SpotlightHero({ event, impactPct, cobro, onView }) {
  const days = daysUntil(event.eventDate)
  const countdown = days == null ? '—' : days === 0 ? 'HOY' : days === 1 ? 'MAÑANA' : days
  const detail = renderDetail(event)
  const contextParts = []
  if (detail) contextParts.push(detail)
  if (cobro?.shares) contextParts.push(`tenés ${formatCompact(cobro.shares)} acc`)
  if (impactPct != null && impactPct > 0.0001) contextParts.push(`${pct(impactPct)} de tu cartera`)

  return (
    <div className="bg-bg-1 border border-data-violet/40 rounded-lg p-4 mb-4 flex flex-wrap items-center gap-4">
      {/* Countdown */}
      <div className="text-center shrink-0 pr-4 border-r border-line">
        <p className="label-mono text-data-violet mb-1">Próximo</p>
        <p className="text-2xl font-semibold text-ink-0 leading-none">
          {typeof countdown === 'number'
            ? <>{countdown}<span className="text-sm text-ink-2">d</span></>
            : countdown}
        </p>
        <p className="label-mono mt-1">{shortDate(event.eventDate)}</p>
      </div>
      {/* Activo + contexto */}
      <div className="flex-1 min-w-[160px]">
        <div className="flex items-center gap-2 flex-wrap mb-1">
          {isMacroEvent(event)
            ? <span className="text-lg">{countryFlag(event.details?.country)}</span>
            : <AssetLogo asset={event.ticker} size={26} />}
          <span className="text-base font-semibold text-ink-0">{event.ticker}</span>
          <EventBadge eventType={event.eventType} />
        </div>
        {contextParts.length > 0 && (
          <p className="text-xs text-ink-2 leading-relaxed">{contextParts.join(' · ')}</p>
        )}
      </div>
      {/* Cobro + CTA */}
      <div className="text-right shrink-0">
        {cobro?.amount != null && (
          <>
            <p className="label-mono mb-0.5">Tu cobro est.</p>
            <p className="text-xl font-semibold text-rendi-pos leading-none">
              +{cobro.currency === 'USD' ? '$' : `${cobro.currency} `}{formatCompact(cobro.amount)}
            </p>
          </>
        )}
        <button
          onClick={onView}
          className="mt-2 inline-flex items-center gap-1.5 bg-data-violet hover:bg-rendi-violet-hover text-white text-xs font-medium px-3 py-1.5 rounded-sm transition-colors"
        >
          Ver posición
        </button>
      </div>
    </div>
  )
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function daysUntil(iso) {
  if (!iso) return null
  const d = new Date(iso + 'T00:00:00')
  const t = new Date()
  t.setHours(0, 0, 0, 0)
  return Math.round((d.getTime() - t.getTime()) / 86400000)
}

function shortDate(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso + 'T00:00:00')
    return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short' }).replace('.', '')
  } catch {
    return iso
  }
}

function macroCategoryLabel(c) {
  switch (c) {
    case 'fed_rate':   return 'Política monetaria'
    case 'cpi':        return 'Inflación'
    case 'employment': return 'Empleo'
    case 'gdp':        return 'PBI'
    default:           return c || 'Macro'
  }
}

// Formato compacto para amounts: 1234.56 → "1,234.56" / 1234567 → "1.23M"
function formatCompact(n) {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  if (abs >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (abs >= 10_000)    return (n / 1_000).toFixed(1) + 'K'
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function collectPriceSymbols(positions, brokers) {
  const arsBrokers = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
  const usdtBrokers = new Set(brokers.filter(b => b.currency !== 'ARS').map(b => b.name))
  const arsSyms = [...new Set(
    positions.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => priceSymbol(p.asset, true))
  )]
  const usdtSyms = [...new Set(
    positions.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => priceSymbol(p.asset, false, p.asset_type))
  )]
  return [...arsSyms, ...usdtSyms]
}
