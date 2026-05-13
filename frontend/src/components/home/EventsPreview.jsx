// EventsPreview — próximos 5 eventos económicos / earnings.
// Reusa /api/events/popular. Linkea a /novedades para el calendario completo.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Calendar } from 'lucide-react'
import { api } from '../../utils/api'

const MONTH_NAMES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

function fmtDate(iso) {
  if (!iso) return ''
  const d = new Date(iso + 'T00:00:00')
  return `${d.getDate()} ${MONTH_NAMES[d.getMonth()]}`
}

function daysUntil(iso) {
  if (!iso) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const target = new Date(iso + 'T00:00:00')
  return Math.round((target - today) / 86400000)
}

const TYPE_ICON = {
  macro: '🏛️',
  earnings: '📊',
  ex_dividend: '💰',
  payment_date: '💵',
}

const TYPE_LABEL = {
  macro: 'Macro',
  earnings: 'Earnings',
  ex_dividend: 'Dividendo',
  payment_date: 'Pago dividendo',
}

export default function EventsPreview() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api.get('/events/popular?days=14')
      .then(d => {
        if (cancelled) return
        // Filtrar a los próximos 5
        const list = (d.events || []).slice(0, 5)
        setEvents(list)
      })
      .catch(() => { if (!cancelled) setEvents([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  return (
    <section className="rounded-sm border border-line bg-bg-1 overflow-hidden">
      <header className="px-4 py-3 border-b border-line/40 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-display uppercase tracking-wider text-ink-2">
          <Calendar size={13} strokeWidth={1.75} aria-hidden="true" />
          Próximos eventos
        </h2>
        <Link
          to="/novedades?tab=eventos"
          className="text-[11px] text-ink-3 hover:text-ink-0 inline-flex items-center gap-1"
        >
          Ver calendario <ArrowRight size={11} strokeWidth={1.75} aria-hidden="true" />
        </Link>
      </header>

      {loading ? (
        <div className="p-4 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-10 rounded-sm bg-bg-2 animate-pulse" />
          ))}
        </div>
      ) : events.length === 0 ? (
        <div className="p-4 text-xs text-ink-3">Sin eventos en los próximos días.</div>
      ) : (
        <ul className="divide-y divide-line/30">
          {events.map((e, i) => {
            const du = daysUntil(e.event_date)
            const when = du === 0 ? 'hoy' : du === 1 ? 'mañana' : du > 0 ? `en ${du}d` : fmtDate(e.event_date)
            return (
              <li key={i} className="px-4 py-2.5 flex items-center gap-3">
                <span className="text-base leading-none flex-shrink-0" aria-hidden="true">
                  {TYPE_ICON[e.event_type] || '📅'}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-ink-1 truncate">
                    {e.details?.title || e.ticker || TYPE_LABEL[e.event_type]}
                  </div>
                  <div className="text-[10px] text-ink-3">
                    {TYPE_LABEL[e.event_type] || e.event_type}
                    {e.ticker && e.ticker !== e.details?.title && ` · ${e.ticker}`}
                  </div>
                </div>
                <span className="text-[11px] font-mono tabular text-ink-2 flex-shrink-0">
                  {when}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
