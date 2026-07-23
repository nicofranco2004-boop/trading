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
import EventBadge from './EventBadge'
import { api } from '../utils/api'
import {
  upcomingBondEvents,
  normalizeBackendEvents,
  mergeEvents,
  formatRelativeDate,
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
    <div className="bg-white dark:bg-bg-1 border border-line rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-line bg-bg-2/40 dark:bg-bg-2/40 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Calendar size={14} strokeWidth={1.75} className="text-rendi-accent" />
          <span className="text-sm font-semibold text-ink-0">Próximos eventos</span>
          <span className="text-[11px] text-ink-3">· próximos {WINDOW_DAYS} días</span>
        </div>
        <Link
          to="/novedades?tab=eventos"
          className="text-[11.5px] font-medium text-rendi-accent hover:text-rendi-accent/80 inline-flex items-center gap-0.5"
        >
          Ver todos <ArrowRight size={11} strokeWidth={1.75} />
        </Link>
      </div>
      <ul className="divide-y divide-line/50 dark:divide-line/40">
        {events.map((ev, i) => (
          <EventRow key={`${ev.ticker}:${ev.eventType}:${ev.eventDate}:${i}`} event={ev} />
        ))}
      </ul>
    </div>
  )
}

function EventRow({ event }) {
  const { ticker, eventType, eventDate, confirmed } = event
  return (
    <li className="px-4 py-2.5 flex items-center gap-3 hover:bg-bg-2 dark:hover:bg-bg-2/40">
      <AssetLogo asset={ticker} size={28} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-ink-0 text-sm tabular">{ticker}</span>
          <EventBadge eventType={eventType} />
        </div>
        <RowAmount event={event} />
      </div>
      <span className="text-[11px] font-medium text-ink-2 bg-bg-2 border border-line/60 rounded-full px-2 py-0.5 whitespace-nowrap shrink-0">
        {formatRelativeDate(eventDate)}
        {!confirmed && <span className="text-ink-3"> · est.</span>}
      </span>
    </li>
  )
}

// Sub-línea de contexto: para cobros (bonos, dividendos) va en cyan — es el
// "qué significa para vos" (mismo código de color que la agenda de Novedades).
function RowAmount({ event }) {
  const { eventType, details } = event
  if (eventType.startsWith('bond_') && details?.total != null) {
    const currency = details.currency || 'USD'
    return (
      <p className="text-[11.5px] text-data-cyan tabular mt-0.5">
        cobrás ~+{currency} {details.total.toFixed(2)}
      </p>
    )
  }
  if (eventType === 'ex_dividend' && details?.dividend_per_share != null) {
    return (
      <p className="text-[11.5px] text-data-cyan tabular mt-0.5">
        ${details.dividend_per_share}/acción
      </p>
    )
  }
  if (eventType === 'earnings' && details?.eps_estimate != null) {
    return (
      <p className="text-[11.5px] text-ink-2 tabular mt-0.5">
        EPS esperado ${details.eps_estimate}
      </p>
    )
  }
  return null
}
