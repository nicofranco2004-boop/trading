// UpcomingEventsCard — card de "próximos eventos del portfolio" para /home.
// ════════════════════════════════════════════════════════════════════════════
// Muestra los N próximos eventos (cupones, amortizaciones, earnings, dividendos)
// en formato compacto. Link a /eventos para ver todo.
//
// Filosofía: NO inundar. Mostrar 3-5 eventos máximo. Si no hay, NO mostrar la
// card (vs. mostrar empty state — el dashboard ya tiene mucho contenido).

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Calendar, ArrowRight } from 'lucide-react'
import AssetLogo from './AssetLogo'
import { api } from '../utils/api'
import {
  upcomingBondEvents,
  normalizeBackendEvents,
  mergeEvents,
  eventTypeLabel,
  eventTypeIcon,
} from '../utils/upcomingEvents'

const WINDOW_DAYS = 30  // mostrar sólo el próximo mes en /home
const MAX_ITEMS = 5

export default function UpcomingEventsCard({ positions }) {
  const [backendEvents, setBackendEvents] = useState([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!positions || positions.length === 0) return
    api.get(`/events/portfolio?days=${WINDOW_DAYS}`)
      .then(r => setBackendEvents(r?.events || []))
      .catch(() => setBackendEvents([]))
      .finally(() => setLoaded(true))
  }, [positions])

  const events = useMemo(() => {
    const bonds = upcomingBondEvents(positions || [], { windowDays: WINDOW_DAYS })
    const stocks = normalizeBackendEvents(backendEvents)
    return mergeEvents(bonds, stocks).slice(0, MAX_ITEMS)
  }, [positions, backendEvents])

  // No renderear nada si no hay eventos en el rango — evita inundar el dashboard.
  if (!loaded || events.length === 0) return null

  return (
    <div className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-line bg-slate-50/40 dark:bg-bg-2/40 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Calendar size={14} strokeWidth={1.75} className="text-rendi-accent" />
          <span className="text-sm font-semibold text-ink-0">Próximos eventos</span>
          <span className="text-[10px] text-ink-3 font-mono">· próximos {WINDOW_DAYS} días</span>
        </div>
        <Link
          to="/eventos"
          className="text-[11px] text-rendi-accent hover:text-rendi-accent/80 font-mono inline-flex items-center gap-0.5"
        >
          Ver todos <ArrowRight size={11} strokeWidth={1.75} />
        </Link>
      </div>
      <ul className="divide-y divide-slate-100 dark:divide-line/40">
        {events.map((ev, i) => (
          <EventRow key={`${ev.ticker}:${ev.eventType}:${ev.eventDate}:${i}`} event={ev} />
        ))}
      </ul>
    </div>
  )
}

function EventRow({ event }) {
  const { ticker, eventType, eventDate, details, daysAway, confirmed } = event
  return (
    <li className="px-4 py-2.5 flex items-center gap-3 hover:bg-slate-50 dark:hover:bg-bg-2/40">
      <AssetLogo asset={ticker} size={28} />
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-ink-0 text-sm tabular flex items-center gap-2 flex-wrap">
          {ticker}
          <span className="text-[9px] font-mono uppercase tracking-[0.12em] px-1.5 py-0.5 rounded-sm bg-bg-3 border border-line text-ink-2">
            {eventTypeIcon(eventType)} {eventTypeLabel(eventType)}
          </span>
        </p>
        <p className="text-[11px] text-ink-2 font-mono">
          {eventDate}
          {' · '}
          {daysAway === 0 ? 'hoy' : daysAway === 1 ? 'mañana' : `en ${daysAway} días`}
          {!confirmed && <span className="text-rendi-warn"> · estimado</span>}
        </p>
      </div>
      <RowAmount event={event} />
    </li>
  )
}

function RowAmount({ event }) {
  const { eventType, details } = event
  if (eventType.startsWith('bond_') && details?.total != null) {
    const currency = details.currency || 'USD'
    return (
      <span className="text-xs font-semibold text-rendi-pos tabular shrink-0">
        +{currency} {details.total.toFixed(2)}
      </span>
    )
  }
  if (eventType === 'ex_dividend' && details?.dividend_per_share != null) {
    return (
      <span className="text-xs font-semibold text-rendi-pos tabular shrink-0">
        ${details.dividend_per_share}/acción
      </span>
    )
  }
  if (eventType === 'earnings' && details?.eps_estimate != null) {
    return (
      <span className="text-xs text-ink-2 tabular shrink-0">
        EPS est. ${details.eps_estimate}
      </span>
    )
  }
  return null
}
