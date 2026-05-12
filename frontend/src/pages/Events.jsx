// Events — calendario de eventos financieros con tabs "Para ti" / "Popular".
// ════════════════════════════════════════════════════════════════════════════
// Dos vistas:
//
//   • Para ti: eventos del PORTFOLIO del user. Stocks/ETFs via backend yfinance,
//     bonos via bondSchedule.js. Cada item muestra "impact %" = porcentaje del
//     portfolio que representa esa posición (la diferenciación de Rendi).
//
//   • Popular: eventos del MERCADO en general — earnings de magnificent 7 +
//     ADRs argentinas + macro events (FOMC, CPI, NFP, INDEC). El user puede
//     ver lo que mueve el mercado aunque no tenga esos activos. Si tiene
//     alguno, badge "👁 En tu cartera".

import { useEffect, useMemo, useState } from 'react'
import { Calendar, Filter, AlertCircle, Eye } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import AssetLogo from '../components/AssetLogo'
import EventBadge from '../components/EventBadge'
import { api } from '../utils/api'
import { computeBrokerValue } from '../utils/valuation'
import { fmtUsd, fmtArs, pct } from '../utils/format'
import {
  upcomingBondEvents,
  normalizeBackendEvents,
  mergeEvents,
  groupEventsByDate,
  formatRelativeDate,
  countryFlag,
  isMacroEvent,
} from '../utils/upcomingEvents'

const WINDOW_OPTIONS = [
  { value: 30,  label: '30 días' },
  { value: 90,  label: '90 días' },
  { value: 180, label: '6 meses' },
  { value: 365, label: '1 año' },
]

const FILTER_OPTIONS = [
  { value: 'all',       label: 'Todos' },
  { value: 'macro',     label: 'Económicos' },
  { value: 'earnings',  label: 'Earnings' },
  { value: 'dividends', label: 'Dividendos' },
  { value: 'bonds',     label: 'Bonos' },
]

const TABS = [
  { value: 'portfolio', label: 'Para ti', desc: 'Eventos de los activos de tu portfolio' },
  { value: 'popular',   label: 'Populares', desc: 'Eventos del mercado y empresas top' },
]

function matchesFilter(event, filter) {
  if (filter === 'all') return true
  if (filter === 'bonds') return event.eventType?.startsWith('bond_')
  if (filter === 'earnings') return event.eventType === 'earnings'
  if (filter === 'dividends') return event.eventType === 'ex_dividend' || event.eventType === 'payment_date'
  if (filter === 'macro') return event.eventType === 'macro'
  return true
}

export default function Events() {
  const [tab, setTab] = useState('portfolio')
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
      // Precios para impact% (solo necesario en tab "Para ti")
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

  // Computar el valor total del portfolio en USD (para impact %)
  const tcBlue = dolar?.blue?.venta || config.tc_blue || 1415
  const portfolioTotalUsd = useMemo(() => {
    return brokers.reduce((sum, broker) => {
      const bpos = positions.filter(p => p.broker === broker.name)
      const v = computeBrokerValue(bpos, prices, broker, tcBlue)
      return sum + (v.value || 0)
    }, 0)
  }, [positions, brokers, prices, tcBlue])

  // Cálculo de impact %: valor USD de la posición / valor total del portfolio
  const tickerValueUsd = useMemo(() => {
    const map = new Map()
    for (const broker of brokers) {
      const bpos = positions.filter(p => p.broker === broker.name)
      for (const p of bpos) {
        if (p.is_cash) continue
        const r = computeBrokerValue([p], prices, broker, tcBlue)
        const prev = map.get(p.asset) || 0
        map.set(p.asset, prev + (r.value || 0))
      }
    }
    return map
  }, [positions, brokers, prices, tcBlue])

  // Tickers que el user tiene (para flag en tab Popular)
  const userTickerSet = useMemo(() => {
    return new Set(positions.filter(p => !p.is_cash).map(p => p.asset))
  }, [positions])

  // Eventos según tab seleccionada
  const visibleEvents = useMemo(() => {
    if (tab === 'portfolio') {
      const bonds = upcomingBondEvents(positions, { windowDays })
      const stocks = normalizeBackendEvents(portfolioEvents)
      return mergeEvents(bonds, stocks)
        .filter(e => matchesFilter(e, filter))
    }
    // tab === 'popular'
    return normalizeBackendEvents(popularEvents)
      .map(e => ({ ...e, inPortfolio: userTickerSet.has(e.ticker) }))
      .filter(e => matchesFilter(e, filter))
  }, [tab, positions, portfolioEvents, popularEvents, filter, windowDays, userTickerSet])

  const byDate = useMemo(() => groupEventsByDate(visibleEvents), [visibleEvents])

  return (
    <div className="page-shell-wide">
      <PageHeader
        title="Eventos financieros"
        subtitle="Próximos cupones, earnings, dividendos y eventos macro."
      />

      {/* Tabs Para ti / Popular */}
      <div className="flex items-center gap-1 mb-4 border-b border-slate-200 dark:border-line">
        {TABS.map(t => (
          <button
            key={t.value}
            onClick={() => setTab(t.value)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
              tab === t.value
                ? 'border-rendi-accent text-ink-0'
                : 'border-transparent text-ink-2 hover:text-ink-0'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Subtítulo dinámico de la tab activa */}
      <p className="text-xs text-ink-2 mb-4">
        {TABS.find(t => t.value === tab)?.desc}
      </p>

      {/* Controles: ventana + filtro */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex items-center gap-2">
          <Calendar size={14} strokeWidth={1.75} className="text-ink-2" />
          <span className="text-xs text-ink-2 font-mono">Ventana:</span>
          {WINDOW_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setWindowDays(opt.value)}
              className={`text-xs px-2.5 py-1 rounded-sm border transition ${
                windowDays === opt.value
                  ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40'
                  : 'bg-bg-2 text-ink-2 border-line hover:bg-bg-3'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Filter size={14} strokeWidth={1.75} className="text-ink-2" />
          <span className="text-xs text-ink-2 font-mono">Tipo:</span>
          {FILTER_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setFilter(opt.value)}
              className={`text-xs px-2.5 py-1 rounded-sm border transition ${
                filter === opt.value
                  ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40'
                  : 'bg-bg-2 text-ink-2 border-line hover:bg-bg-3'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <p className="text-sm text-ink-2 font-mono">Cargando eventos…</p>}
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

      {!loading && visibleEvents.length > 0 && (
        <div className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded overflow-hidden">
          {[...byDate.entries()].map(([date, events]) => (
            <DateGroup
              key={date}
              date={date}
              events={events}
              tab={tab}
              tickerValueUsd={tickerValueUsd}
              portfolioTotalUsd={portfolioTotalUsd}
            />
          ))}
        </div>
      )}

      <p className="mt-6 text-[10px] text-ink-3 font-mono leading-snug">
        {tab === 'portfolio'
          ? 'Eventos de bonos desde el cronograma teórico (bondSchedule). Earnings y dividendos via yfinance — fechas pueden cambiar hasta confirmación oficial.'
          : 'Eventos macro hardcoded del calendario oficial (Fed, BLS, INDEC). Earnings via yfinance — fechas estimadas hasta confirmación de la empresa.'}
      </p>
    </div>
  )
}

function DateGroup({ date, events, tab, tickerValueUsd, portfolioTotalUsd }) {
  const relativeLabel = formatRelativeDate(date)
  return (
    <div>
      <div className="sticky top-0 z-10 px-4 py-2 border-b border-slate-200 dark:border-line bg-slate-50/95 dark:bg-bg-2/95 backdrop-blur-sm flex items-baseline justify-between">
        <span className="text-sm font-semibold text-ink-0">{relativeLabel}</span>
        <span className="text-[10px] text-ink-3 font-mono">
          {events.length} {events.length === 1 ? 'evento' : 'eventos'}
        </span>
      </div>
      <ul className="divide-y divide-slate-100 dark:divide-line/40">
        {events.map((ev, i) => (
          <EventItem
            key={`${ev.ticker}:${ev.eventType}:${ev.eventDate}:${i}`}
            event={ev}
            tab={tab}
            tickerValueUsd={tickerValueUsd}
            portfolioTotalUsd={portfolioTotalUsd}
          />
        ))}
      </ul>
    </div>
  )
}

function EventItem({ event, tab, tickerValueUsd, portfolioTotalUsd }) {
  const { ticker, broker, eventType, confirmed, inPortfolio, details } = event
  const isMacro = isMacroEvent(event)
  const country = details?.country
  const macroTitle = details?.title

  // Impact %: valor del ticker / valor total del portfolio
  const impactPct = (tab === 'portfolio' && tickerValueUsd && portfolioTotalUsd > 0)
    ? (tickerValueUsd.get(ticker) || 0) / portfolioTotalUsd
    : null

  return (
    <li className="px-4 py-3 flex items-center gap-3 hover:bg-slate-50 dark:hover:bg-bg-2/40">
      {/* Logo: bandera para macro, AssetLogo para tickers */}
      {isMacro ? (
        <div className="w-8 h-8 rounded-full bg-bg-3 border border-line flex items-center justify-center text-lg flex-shrink-0">
          {countryFlag(country)}
        </div>
      ) : (
        <AssetLogo asset={ticker} size={32} />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap mb-0.5">
          <span className="font-semibold text-ink-0 text-sm tabular">
            {isMacro ? macroTitle || ticker : ticker}
          </span>
          {broker && (
            <span className="text-[10px] font-mono text-ink-2">· {broker}</span>
          )}
          <EventBadge eventType={eventType} />
          {tab === 'popular' && inPortfolio && (
            <span className="text-[9px] font-mono uppercase tracking-[0.12em] px-1.5 py-0.5 rounded-sm bg-rendi-accent/15 text-rendi-accent border border-rendi-accent/40 inline-flex items-center gap-1">
              <Eye size={9} strokeWidth={1.75} />
              EN TU CARTERA
            </span>
          )}
        </div>
        <EventDetails event={event} />
        {/* Impact % en "Para ti" — la diferenciación de Rendi vs Delta */}
        {tab === 'portfolio' && impactPct != null && impactPct > 0.0001 && (
          <p className="text-[10px] text-rendi-accent font-mono mt-0.5">
            {pct(impactPct)} de tu cartera
          </p>
        )}
        {!confirmed && (
          <p className="text-[10px] text-ink-3 font-mono mt-0.5 opacity-70">
            · estimado
          </p>
        )}
      </div>
    </li>
  )
}

function EventDetails({ event }) {
  const { eventType, details } = event
  if (eventType === 'macro') {
    return (
      <p className="text-[11px] text-ink-2 font-mono">
        {details?.country} · {macroCategoryLabel(details?.category)}
      </p>
    )
  }
  if (eventType === 'earnings') {
    return (
      <p className="text-[11px] text-ink-2 font-mono">
        {details?.eps_estimate != null
          ? <>EPS estimado: <span className="text-ink-0 font-semibold">${details.eps_estimate}</span></>
          : 'Reporta resultados trimestrales.'}
      </p>
    )
  }
  if (eventType === 'ex_dividend') {
    return (
      <p className="text-[11px] text-ink-2 font-mono">
        {details?.dividend_per_share != null
          ? <>Dividendo: <span className="text-rendi-pos font-semibold">${details.dividend_per_share}/acción</span></>
          : 'Fecha ex-dividendo'}
      </p>
    )
  }
  if (eventType?.startsWith('bond_')) {
    const currency = details?.currency || 'USD'
    if (details?.coupon > 0 && details?.amort > 0) {
      return (
        <p className="text-[11px] text-ink-2 font-mono">
          Cupón <span className="text-rendi-pos">{currency} {details.coupon.toFixed(2)}</span>
          {' + amort '}
          <span className="text-rendi-accent">{currency} {details.amort.toFixed(2)}</span>
          {' = '}
          <span className="text-ink-0 font-semibold">{currency} {details.total.toFixed(2)}</span>
        </p>
      )
    }
    if (details?.coupon > 0) {
      return (
        <p className="text-[11px] text-ink-2 font-mono">
          Cupón: <span className="text-rendi-pos font-semibold">{currency} {details.coupon.toFixed(2)}</span>
        </p>
      )
    }
    if (details?.amort > 0) {
      const isMaturity = eventType === 'bond_maturity'
      return (
        <p className="text-[11px] text-ink-2 font-mono">
          {isMaturity ? 'Pago final' : 'Amortización'}: <span className="text-rendi-accent font-semibold">{currency} {details.amort.toFixed(2)}</span>
        </p>
      )
    }
  }
  return null
}

// Helpers locales
function macroCategoryLabel(c) {
  switch (c) {
    case 'fed_rate':   return 'Política monetaria'
    case 'cpi':        return 'Inflación'
    case 'employment': return 'Empleo'
    case 'gdp':        return 'PBI'
    default:           return c || 'Evento macro'
  }
}

// Construir lista de symbols para /prices (igual que Positions.jsx)
function collectPriceSymbols(positions, brokers) {
  const arsBrokers = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
  const usdtBrokers = new Set(brokers.filter(b => b.currency !== 'ARS').map(b => b.name))
  const arsSyms = [...new Set(
    positions.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => p.asset + '.BA')
  )]
  const usdtSyms = [...new Set(
    positions.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => p.asset)
  )]
  return [...arsSyms, ...usdtSyms]
}
