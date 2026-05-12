// Events — calendario de eventos financieros del portfolio.
// ════════════════════════════════════════════════════════════════════════════
// Muestra próximos eventos de los activos del user:
//   • Stocks/ETFs/CEDEARs: earnings + ex-dividend (backend yfinance).
//   • Bonos: cupones + amortizaciones + vencimientos (frontend bondSchedule).
//
// Diseño: lista cronológica con filtros por tipo. No es un calendario visual
// estilo Google Calendar — es una lista compacta tipo "agenda".

import { useEffect, useMemo, useState } from 'react'
import { Calendar, Filter, AlertCircle } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import AssetLogo from '../components/AssetLogo'
import { api } from '../utils/api'
import {
  upcomingBondEvents,
  normalizeBackendEvents,
  mergeEvents,
  groupEventsByDate,
  eventTypeLabel,
  eventTypeIcon,
} from '../utils/upcomingEvents'

const WINDOW_OPTIONS = [
  { value: 30,  label: '30 días' },
  { value: 90,  label: '90 días' },
  { value: 180, label: '6 meses' },
  { value: 365, label: '1 año' },
]

const FILTER_OPTIONS = [
  { value: 'all',      label: 'Todos' },
  { value: 'bonds',    label: 'Bonos' },
  { value: 'earnings', label: 'Earnings' },
  { value: 'dividends',label: 'Dividendos' },
]

function matchesFilter(event, filter) {
  if (filter === 'all') return true
  if (filter === 'bonds') return event.eventType.startsWith('bond_')
  if (filter === 'earnings') return event.eventType === 'earnings'
  if (filter === 'dividends') return event.eventType === 'ex_dividend' || event.eventType === 'payment_date'
  return true
}

export default function Events() {
  const [positions, setPositions] = useState([])
  const [backendEvents, setBackendEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [windowDays, setWindowDays] = useState(90)
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState(null)

  useEffect(() => {
    loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [windowDays])

  async function loadAll() {
    setLoading(true)
    setError(null)
    try {
      const [pos, ev] = await Promise.all([
        api.get('/positions'),
        api.get(`/events/portfolio?days=${windowDays}`).catch(e => {
          console.warn('Events fetch failed:', e)
          return { events: [] }
        }),
      ])
      setPositions(pos || [])
      setBackendEvents(ev?.events || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  // Combinamos eventos de bonos (frontend) + stocks (backend).
  const allEvents = useMemo(() => {
    const bondEvents = upcomingBondEvents(positions, { windowDays })
    const stockEvents = normalizeBackendEvents(backendEvents)
    return mergeEvents(bondEvents, stockEvents)
      .filter(e => matchesFilter(e, filter))
  }, [positions, backendEvents, windowDays, filter])

  const byDate = useMemo(() => groupEventsByDate(allEvents), [allEvents])

  return (
    <div className="page-shell-wide">
      <PageHeader
        title="Eventos financieros"
        subtitle="Próximos cupones, amortizaciones, earnings y dividendos de tu portfolio."
      />

      {/* Controles: ventana de tiempo + filtro de tipo */}
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
        <div className="flex items-center gap-2">
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

      {/* Estados */}
      {loading && (
        <p className="text-sm text-ink-2 font-mono">Cargando eventos…</p>
      )}
      {error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-sm bg-rendi-warn/10 text-rendi-warn text-sm">
          <AlertCircle size={14} /> {error}
        </div>
      )}
      {!loading && !error && allEvents.length === 0 && (
        <EmptyState
          icon={<Calendar size={32} />}
          title="Sin eventos próximos"
          subtitle={`No hay pagos, earnings ni dividendos del portfolio en los próximos ${windowDays} días.`}
        />
      )}

      {/* Lista cronológica agrupada por día */}
      {!loading && allEvents.length > 0 && (
        <div className="space-y-4">
          {[...byDate.entries()].map(([date, events]) => (
            <DateGroup key={date} date={date} events={events} />
          ))}
        </div>
      )}

      <p className="mt-6 text-[10px] text-ink-3 font-mono leading-snug">
        Eventos de bonos generados desde el cronograma teórico (bondSchedule).
        Eventos de stocks via yfinance — fechas pueden cambiar hasta confirmación oficial.
        Cantidades calculadas usando tu quantity actual en cartera.
      </p>
    </div>
  )
}

function DateGroup({ date, events }) {
  const dateLabel = formatDateLabel(date)
  const daysAway = events[0]?.daysAway
  return (
    <div className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-200 dark:border-line bg-slate-50/40 dark:bg-bg-2/40 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold text-ink-0">{dateLabel}</span>
          <span className="text-[10px] text-ink-3 font-mono">
            {daysAway === 0 ? 'hoy' :
             daysAway === 1 ? 'mañana' :
             `en ${daysAway} días`}
          </span>
        </div>
        <span className="text-[10px] text-ink-2 font-mono">
          {events.length} {events.length === 1 ? 'evento' : 'eventos'}
        </span>
      </div>
      <ul className="divide-y divide-slate-100 dark:divide-line/40">
        {events.map((ev, i) => (
          <EventItem key={`${ev.ticker}:${ev.eventType}:${ev.eventDate}:${i}`} event={ev} />
        ))}
      </ul>
    </div>
  )
}

function EventItem({ event }) {
  const { ticker, broker, eventType, details, confirmed } = event
  return (
    <li className="px-4 py-3 flex items-center gap-3 hover:bg-slate-50 dark:hover:bg-bg-2/40">
      <AssetLogo asset={ticker} size={32} />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-ink-0 text-sm tabular flex items-center gap-2 flex-wrap">
          {ticker}
          {broker && (
            <span className="text-[10px] font-mono text-ink-2 normal-case">· {broker}</span>
          )}
          <span className="text-[9px] font-mono uppercase tracking-[0.12em] px-1.5 py-0.5 rounded-sm bg-bg-3 border border-line text-ink-2">
            {eventTypeIcon(eventType)} {eventTypeLabel(eventType)}
          </span>
          {!confirmed && (
            <span className="text-[9px] font-mono text-rendi-warn">(estimado)</span>
          )}
        </p>
        <EventDetails event={event} />
      </div>
    </li>
  )
}

function EventDetails({ event }) {
  const { eventType, details } = event
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
  if (eventType.startsWith('bond_')) {
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

// Formato amigable: "Mié 9 de jul 2026"
function formatDateLabel(iso) {
  try {
    const d = new Date(iso + 'T00:00:00')
    return d.toLocaleDateString('es-AR', {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return iso
  }
}
