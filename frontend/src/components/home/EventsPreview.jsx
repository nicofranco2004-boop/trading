// EventsPreview — próximos 5 eventos económicos / earnings (V2).
// Panel denso + DataRow para cada evento.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Calendar, Landmark, BarChart3, Coins, Banknote, CalendarClock } from 'lucide-react'
import { api } from '../../utils/api'
import Panel from '../Panel'
import Eyebrow from '../Eyebrow'
import DataRow from '../DataRow'

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

// Color por tipo: usamos accents fríos del sistema de tokens, NO emojis.
const TYPE_ICON = {
  macro:        { Icon: Landmark,      className: 'text-data-blue' },
  earnings:     { Icon: BarChart3,     className: 'text-data-cyan' },
  ex_dividend:  { Icon: Coins,         className: 'text-rendi-warn' },
  payment_date: { Icon: Banknote,      className: 'text-rendi-pos' },
}
const FALLBACK_ICON = { Icon: CalendarClock, className: 'text-ink-3' }

const TYPE_LABEL = {
  macro: 'Macro',
  earnings: 'Earnings',
  ex_dividend: 'Dividendo',
  payment_date: 'Pago',
}

export default function EventsPreview() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api.get('/events/popular?days=14')
      .then(d => {
        if (cancelled) return
        setEvents((d.events || []).slice(0, 5))
      })
      .catch(() => { if (!cancelled) setEvents([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  return (
    <Panel padding="none" className="overflow-hidden">
      <header className="px-3 py-2 border-b border-line flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Calendar size={12} strokeWidth={1.75} className="text-ink-3" aria-hidden="true" />
          <Eyebrow>Próximos eventos</Eyebrow>
        </div>
        <Link
          to="/novedades?tab=eventos"
          className="text-[10px] text-ink-3 hover:text-ink-0 inline-flex items-center gap-1 font-mono uppercase tracking-caps"
        >
          Calendario <ArrowRight size={10} strokeWidth={1.75} aria-hidden="true" />
        </Link>
      </header>

      {loading ? (
        <div className="p-3 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-10 rounded-sm bg-bg-2 animate-pulse" />
          ))}
        </div>
      ) : events.length === 0 ? (
        <div className="p-4 text-xs text-ink-3">Sin eventos en los próximos días.</div>
      ) : (
        <div className="divide-y divide-line/30">
          {events.map((e, i) => {
            const du = daysUntil(e.event_date)
            const when = du === 0 ? 'hoy' : du === 1 ? 'mañana' : du > 0 ? `en ${du}d` : fmtDate(e.event_date)
            const { Icon, className: iconClass } = TYPE_ICON[e.event_type] || FALLBACK_ICON
            return (
              <DataRow key={i} density="default">
                <span className="flex-shrink-0 inline-flex items-center justify-center w-6 h-6 rounded-sm bg-bg-2" aria-hidden="true">
                  <Icon size={13} strokeWidth={1.75} className={iconClass} />
                </span>
                <DataRow.Cell>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-ink-1 truncate">
                      {e.details?.title || e.ticker || TYPE_LABEL[e.event_type]}
                    </div>
                    <div className="text-[10px] text-ink-3 font-mono uppercase tracking-caps">
                      {TYPE_LABEL[e.event_type] || e.event_type}
                      {e.ticker && e.ticker !== e.details?.title && ` · ${e.ticker}`}
                    </div>
                  </div>
                </DataRow.Cell>
                <DataRow.Cell align="right" width={70} mono tabular muted className="text-[11px]">
                  {when}
                </DataRow.Cell>
              </DataRow>
            )
          })}
        </div>
      )}
    </Panel>
  )
}
