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
import {
  Calendar, Filter, AlertCircle, Eye, Sparkles,
  BarChart3, CircleDollarSign, Landmark, ReceiptText, ChevronRight, Loader2,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import AssetLogo from '../components/AssetLogo'
import EventBadge from '../components/EventBadge'
import { api } from '../utils/api'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import InlineAIButton from '../components/ai/InlineAIButton'
import { computeBrokerValue, priceSymbol, isArUsdBroker, costInPesos } from '../utils/valuation'
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
      <div className="bg-bg-1 border border-line rounded-xl mb-4 grid grid-cols-3 divide-x divide-line">
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

      {/* Agenda por día (clean pass 2026-07) — reemplaza la tabla densa. */}
      {!loading && visibleEvents.length > 0 && (
        <EventAgenda
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
    <div className="bg-bg-1 border border-line rounded-xl mb-4 p-3 sm:p-4">
      <div className="flex items-center justify-between mb-2">
        <p className="label-mono">{useImpact ? 'Distribución · por impacto' : 'Distribución'}</p>
        <p className="text-[12px] text-ink-3 font-medium">
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
                className="flex-1 min-w-[3px] relative group flex flex-col justify-end h-full"
              >
                {/* Tooltip propio (instantáneo) — qué activos caen en esta barra. */}
                {b.total > 0 && (
                  <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover:block z-20 min-w-[130px] bg-bg-3 border border-line-2 rounded px-2.5 py-1.5 shadow-lg">
                    <div className="text-[12.5px] text-ink-3 mb-1 whitespace-nowrap font-medium">{b.label}</div>
                    <div className="flex flex-col gap-0.5">
                      {b.items.slice(0, 6).map((it, i) => (
                        <div key={i} className="flex items-center gap-1.5 text-[11px] whitespace-nowrap">
                          <span className={`w-1.5 h-1.5 rounded-sm ${it.tone} shrink-0`} />
                          <span className="font-mono font-semibold text-ink-0">{it.ticker}</span>
                          <span className="text-ink-3">{it.typeLabel}</span>
                          {it.impactPct != null && it.impactPct > 0.0001 && (
                            <span className="text-rendi-accent ml-2">{pct(it.impactPct)}</span>
                          )}
                        </div>
                      ))}
                      {b.items.length > 6 && (
                        <div className="text-[10px] text-ink-3">+{b.items.length - 6} más</div>
                      )}
                    </div>
                  </div>
                )}
                <div
                  className={`w-full rounded-sm ${tone} transition-opacity opacity-80 group-hover:opacity-100`}
                  style={{ height: `${h}%` }}
                />
              </div>
            )
          })}
        </div>
        {/* Etiquetas de inicio / mitad / fin */}
        <div className="flex justify-between mt-1 text-[12.5px] text-ink-3 font-medium">
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
      items: [],
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
    const evImpact = hasImpact ? (tickerValueUsd.get(ev.ticker) || 0) / portfolioTotalUsd : null
    if (hasImpact) b.impact += evImpact
    b.items.push({ ticker: ev.ticker, impactPct: evImpact, ...eventMini(ev) })
    if (ev.eventType?.startsWith('bond_')) b.bonds += 1
    else if (ev.eventType === 'earnings') b.earnings += 1
    else if (ev.eventType === 'ex_dividend' || ev.eventType === 'payment_date') b.dividends += 1
    else if (ev.eventType === 'macro') b.macro += 1
  }

  return buckets
}

// Etiqueta + color por evento para el tooltip de la timeline (mismo mapping
// de color que las barras/badges: bono=amber, earnings=purple, dividendo=blue).
function eventMini(ev) {
  const t = ev.eventType || ''
  if (t.startsWith('bond_')) return { typeLabel: 'bono', tone: 'bg-amber-400/80' }
  if (t === 'earnings') return { typeLabel: 'earnings', tone: 'bg-purple-400/80' }
  if (t === 'ex_dividend' || t === 'payment_date') return { typeLabel: 'dividendo', tone: 'bg-blue-400/80' }
  if (t === 'macro') return { typeLabel: 'macro', tone: 'bg-rendi-pos/80' }
  return { typeLabel: t || 'evento', tone: 'bg-ink-3' }
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
    <div className="bg-bg-1 border border-line rounded-xl overflow-hidden">
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


// ─── Agenda por día (clean pass 2026-07) ────────────────────────────────────
// Reemplaza la tabla densa: eventos agrupados por FECHA con riel de días a la
// izquierda y cards con aire. Earnings expandibles → expectativas del consenso
// (fetch on-demand a /events/earnings-expectations, cache server-side).

function groupByDay(events) {
  const sorted = [...events].sort((a, b) => (a.eventDate || '').localeCompare(b.eventDate || ''))
  const map = new Map()
  for (const ev of sorted) {
    const k = ev.eventDate || 'sin-fecha'
    if (!map.has(k)) map.set(k, [])
    map.get(k).push(ev)
  }
  return [...map.entries()].map(([date, evs]) => ({ date, events: evs }))
}

const WEEKDAYS = ['DOM', 'LUN', 'MAR', 'MIÉ', 'JUE', 'VIE', 'SÁB']
const MONTHS_SHORT = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

function dayRail(dateStr) {
  const d = daysUntil(dateStr)
  const dt = dateStr ? new Date(`${dateStr}T12:00:00`) : null
  const sub = dt && !isNaN(dt) ? `${dt.getDate()} ${MONTHS_SHORT[dt.getMonth()]}` : '—'
  if (d === 0) return { top: 'HOY', sub, today: true }
  if (d === 1) return { top: 'MAÑANA', sub, today: false }
  const top = dt && !isNaN(dt) ? WEEKDAYS[dt.getDay()] : '—'
  return { top, sub, today: false }
}

// Ícono + tono por tipo de evento (lucide, sin emojis — pedido de producto).
function eventIconMeta(eventType) {
  if (eventType === 'earnings')    return { Icon: BarChart3,        cls: 'bg-data-violet/12 text-data-violet' }
  if (eventType === 'ex_dividend') return { Icon: CircleDollarSign, cls: 'bg-rendi-pos/10 text-rendi-pos' }
  if (eventType === 'macro')       return { Icon: Landmark,         cls: 'bg-data-cyan/10 text-data-cyan' }
  if (eventType?.startsWith('bond_')) return { Icon: ReceiptText,   cls: 'bg-rendi-warn/10 text-rendi-warn' }
  return { Icon: Calendar, cls: 'bg-bg-2 text-ink-2' }
}

function EventAgenda({ events, tab, tickerValueUsd, portfolioTotalUsd, tickerShares }) {
  const groups = useMemo(() => groupByDay(events), [events])
  return (
    <div>
      {groups.map(g => {
        const rail = dayRail(g.date)
        return (
          <div key={g.date} className="grid gap-4" style={{ gridTemplateColumns: '72px 1fr' }}>
            <div className="text-right pt-4">
              <div className={`text-[12px] font-bold ${rail.today ? 'text-data-violet' : 'text-ink-0'}`}>{rail.top}</div>
              <div className="text-[11.5px] text-ink-3">{rail.sub}</div>
            </div>
            <div className="flex flex-col gap-2.5 border-l-2 border-line/40 pl-4 py-2 pb-5">
              {g.events.map((ev, i) => (
                <AgendaCard
                  key={`${ev.ticker}:${ev.eventType}:${ev.eventDate}:${i}`}
                  event={ev}
                  tab={tab}
                  tickerValueUsd={tickerValueUsd}
                  portfolioTotalUsd={portfolioTotalUsd}
                  tickerShares={tickerShares}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function AgendaCard({ event, tab, tickerValueUsd, portfolioTotalUsd, tickerShares }) {
  const { ticker, eventType, eventDate, confirmed, inPortfolio, details } = event
  const isMacro = isMacroEvent(event)
  const cobro = tab === 'portfolio' ? eventCobro(event, tickerShares) : null
  const impactPct = (tab === 'portfolio' && tickerValueUsd && portfolioTotalUsd > 0)
    ? (tickerValueUsd.get(ticker) || 0) / portfolioTotalUsd
    : null
  const days = daysUntil(eventDate)
  const whenLabel = days == null ? shortDate(eventDate)
    : days === 0 ? 'hoy' : days === 1 ? 'mañana' : `en ${days} días`

  // Expandible: solo earnings (expectativas del consenso vía yfinance).
  const expandable = eventType === 'earnings'
  const [open, setOpen] = useState(false)
  const { Icon, cls } = eventIconMeta(eventType)

  const title = eventType === 'earnings' ? `Earnings de ${ticker}`
    : eventType === 'ex_dividend' ? `Ex-dividendo de ${ticker}`
    : isMacro ? (details?.title || ticker)
    : eventType?.startsWith('bond_') ? `${eventType === 'bond_maturity' ? 'Vencimiento' : 'Pago'} de ${ticker}`
    : ticker

  // Sub-línea: detalle + lo personal (cuánto te toca) en cyan.
  const detail = renderDetail(event)
  const shares = tickerShares?.get?.(ticker) || null
  const personal = cobro?.amount != null
    ? `tenés ${formatCompact(cobro.shares || shares || 0)} nominales → ~+${cobro.currency === 'USD' ? 'US$ ' : `${cobro.currency} `}${formatCompact(cobro.amount)}`
    : (tab === 'portfolio' && shares && impactPct != null && impactPct > 0.0001)
      ? `tenés ${formatCompact(shares)} nominales (${pct(impactPct)} de tu cartera)`
      : (tab === 'popular' && inPortfolio) ? 'está en tu cartera' : null

  return (
    <div className={`bg-bg-1 border border-line rounded-xl overflow-hidden transition-colors ${expandable ? 'cursor-pointer hover:border-ink-3/60' : ''}`}>
      <div
        className="px-4 py-3 flex items-center gap-3"
        onClick={expandable ? () => setOpen(o => !o) : undefined}
        role={expandable ? 'button' : undefined}
        aria-expanded={expandable ? open : undefined}
      >
        {isMacro ? (
          <div className={`w-9 h-9 rounded-xl grid place-items-center flex-none ${cls}`}>
            <Icon size={17} strokeWidth={1.75} aria-hidden="true" />
          </div>
        ) : (
          <AssetLogo asset={ticker} size={36} />
        )}
        <div className="flex-1 min-w-0">
          <div className="text-[14px] font-semibold text-ink-0 truncate">
            {title}
            {!confirmed && <span className="ml-1.5 text-[11px] text-ink-3 font-normal">· est.</span>}
          </div>
          <div className="text-[12.5px] text-ink-3 truncate">
            {detail}
            {personal && <b className="text-data-cyan font-semibold">{detail ? ' · ' : ''}{personal}</b>}
          </div>
        </div>
        {!isMacro && (
          <span onClick={e => e.stopPropagation()}>
            <InlineAIButton
              topic="events.item"
              params={{ ticker, event_type: eventType, event_date: eventDate, details: typeof details === 'string' ? details : (details?.title || '') }}
              subtitle={`${ticker} · ${eventType}`}
              label="Analizar"
            />
          </span>
        )}
        <span className="flex-none text-[11.5px] font-bold text-data-violet bg-data-violet/12 rounded-full px-2.5 py-1 whitespace-nowrap">
          {whenLabel}
        </span>
        {expandable && (
          <ChevronRight size={15} strokeWidth={2} className={`flex-none text-ink-3 transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden="true" />
        )}
      </div>
      {expandable && open && <EarningsExpectations symbol={ticker} />}
    </div>
  )
}

// Panel de expectativas del consenso (on-demand al expandir). Si el backend
// no tiene datos (cripto/ETF/red caída) el panel dice eso y listo — nunca
// inventamos números.
function EarningsExpectations({ symbol }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let cancelled = false
    api.get(`/events/earnings-expectations?symbol=${encodeURIComponent(symbol)}`)
      .then(d => { if (!cancelled) { setData(d); setLoading(false) } })
      .catch(() => { if (!cancelled) { setData(null); setLoading(false) } })
    return () => { cancelled = true }
  }, [symbol])

  if (loading) {
    return (
      <div className="border-t border-line/40 bg-bg-2/40 px-4 py-4 flex items-center gap-2 text-[12.5px] text-ink-3">
        <Loader2 size={13} className="animate-spin" aria-hidden="true" /> Buscando expectativas del consenso…
      </div>
    )
  }
  if (!data?.available) {
    return (
      <div className="border-t border-line/40 bg-bg-2/40 px-4 py-3 text-[12.5px] text-ink-3">
        Sin datos de consenso disponibles para este activo.
      </div>
    )
  }
  const est = data.next_earnings_estimates
  const quarters = (data.last_quarters || []).slice(0, 4)
  return (
    <div className="border-t border-line/40 bg-bg-2/40 px-4 py-4">
      <p className="text-[11px] font-bold text-ink-3 mb-2.5">QUÉ ESPERA EL CONSENSO DE ANALISTAS</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <div className="bg-bg-1 border border-line/50 rounded-xl px-3 py-2.5">
          <div className="text-[11px] text-ink-3 mb-1">EPS esperado</div>
          <div className="text-[15px] font-semibold text-ink-0 num tabular">
            {est?.eps_average != null ? `US$ ${est.eps_average}` : '—'}
          </div>
          {est?.eps_low != null && est?.eps_high != null && (
            <div className="text-[11px] text-ink-3 mt-0.5 num">rango {est.eps_low} – {est.eps_high}</div>
          )}
        </div>
        <div className="bg-bg-1 border border-line/50 rounded-xl px-3 py-2.5">
          <div className="text-[11px] text-ink-3 mb-1">Próximo reporte</div>
          <div className="text-[15px] font-semibold text-ink-0">
            {data.next_earnings_date ? String(data.next_earnings_date).slice(0, 10) : '—'}
          </div>
        </div>
        <div className="bg-bg-1 border border-line/50 rounded-xl px-3 py-2.5">
          <div className="text-[11px] text-ink-3 mb-1">Surprise prom. últimos 4Q</div>
          <div className={`text-[15px] font-semibold num tabular ${data.surprise_avg_last_4q_pct > 0 ? 'text-rendi-pos' : data.surprise_avg_last_4q_pct < 0 ? 'text-rendi-neg' : 'text-ink-0'}`}>
            {data.surprise_avg_last_4q_pct != null ? `${data.surprise_avg_last_4q_pct > 0 ? '+' : ''}${data.surprise_avg_last_4q_pct}%` : '—'}
          </div>
        </div>
      </div>
      {quarters.length > 0 && (
        <div className="flex items-center gap-1.5 mt-3 flex-wrap text-[12px] text-ink-2">
          <span>Últimos trimestres:</span>
          {quarters.map((q, i) => {
            const s = q.surprise_pct
            if (s == null) return null
            const beat = s >= 0
            return (
              <span key={i} className={`text-[10.5px] font-bold rounded-full px-2 py-0.5 ${beat ? 'text-rendi-pos bg-rendi-pos/10' : 'text-rendi-neg bg-rendi-neg/10'}`}>
                {beat ? 'Beat' : 'Miss'} {s > 0 ? '+' : ''}{s}%
              </span>
            )
          })}
        </div>
      )}
    </div>
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
    // .BA por el PADRE (sub-broker AR·USD / lote en pesos); acción AR en broker USD
    // extranjero (Schwab) → ADR NYSE (ticker pelado).
    positions.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => (isArUsdBroker(p.broker) || costInPesos(p)) ? priceSymbol(p.asset, true, p.asset_type) : priceSymbol(p.asset, false, p.asset_type))
  )]
  return [...arsSyms, ...usdtSyms]
}
