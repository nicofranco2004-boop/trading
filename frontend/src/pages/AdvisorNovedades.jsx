// AdvisorNovedades — el radar cross-cliente del asesor (nav Fase 2).
// ═══════════════════════════════════════════════════════════════════════════
// Se renderiza DESDE Novedades.jsx (misma ruta /novedades) cuando isAdvisor &&
// !clientCtx — el asesor no tiene cartera propia, así que su radar son los
// eventos/noticias de CUALQUIER activo que tenga CUALQUIERA de sus clientes,
// con atribución: "GGAL reporta el jueves — lo tienen 3 de tus clientes".
//
// Data: GET /advisor/radar/events + /advisor/radar/news (backend agrega el
// universo de tickers del libro y devuelve `clients` por item). Adentro de un
// cliente, /novedades sigue mostrando el radar normal de ESA cartera.

import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Calendar, Newspaper, Users, ExternalLink } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import AssetLogo from '../components/AssetLogo'
import { api } from '../utils/api'
import {
  eventTypeLabel, eventTypeIcon, eventCategoryColor, eventCategoryLabel,
  formatRelativeDate,
} from '../utils/upcomingEvents'

const SECTIONS = [
  { value: 'eventos',  label: 'Eventos',  icon: Calendar },
  { value: 'noticias', label: 'Noticias', icon: Newspaper },
]
const DEFAULT_SECTION = 'eventos'

const BADGE_TONE = {
  purple: 'text-purple-300 bg-purple-400/10',
  blue:   'text-sky-300 bg-sky-400/10',
  amber:  'text-amber-300 bg-amber-400/10',
  green:  'text-emerald-300 bg-emerald-400/10',
  gray:   'text-ink-2 bg-bg-2',
}

export default function AdvisorNovedades() {
  const [searchParams, setSearchParams] = useSearchParams()
  const t = searchParams.get('tab')
  const section = SECTIONS.find(s => s.value === t) ? t : DEFAULT_SECTION

  const [events, setEvents] = useState(null)   // null = cargando
  const [news, setNews] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.get('/advisor/radar/events?days=90').catch(() => null),
      api.get('/advisor/radar/news?limit=30').catch(() => null),
    ]).then(([ev, nw]) => {
      if (cancelled) return
      setEvents(ev?.events ?? [])
      setNews(nw?.news ?? [])
      setError(!ev && !nw)
    })
    return () => { cancelled = true }
  }, [])

  function selectSection(value) {
    const next = new URLSearchParams(searchParams)
    next.set('tab', value)
    setSearchParams(next, { replace: true })
  }

  return (
    <div className="page-shell-wide">
      <PageHeader
        eyebrow="Plan Asesor"
        title="Novedades"
        subtitle="Eventos y noticias de los activos que tienen tus clientes — con quiénes los tienen."
      />

      {/* Tabs Eventos / Noticias — misma convención ?tab= que Novedades */}
      <div className="flex items-center gap-1.5 mb-5">
        {SECTIONS.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            type="button"
            onClick={() => selectSection(value)}
            className={`inline-flex items-center gap-1.5 text-[13px] font-medium rounded-md px-3 py-2 transition-colors ${
              section === value
                ? 'text-ink-0 bg-bg-2'
                : 'text-ink-2 hover:text-ink-0 hover:bg-bg-1'
            }`}
          >
            <Icon size={14} strokeWidth={1.75} />
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-4 text-[12px] text-ink-2 bg-bg-1 border border-line/60 rounded-md px-3 py-2">
          No pudimos cargar el radar recién. Recargá la página para reintentar.
        </div>
      )}

      {section === 'eventos'
        ? <EventsList events={events} />
        : <NewsList news={news} />}
    </div>
  )
}

// Badge "quiénes lo tienen": hasta 2 labels + "+N más". El punto del radar es
// exactamente este dato — sin la atribución sería el radar de cualquiera.
function ClientsBadge({ clients }) {
  if (!clients?.length) return null
  const shown = clients.slice(0, 2).map(c => c.label).join(', ')
  const extra = clients.length - 2
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-data-violet bg-data-violet/10 rounded px-2 py-0.5 max-w-full">
      <Users size={10} strokeWidth={2} className="flex-shrink-0" />
      <span className="truncate">
        {clients.length === 1 ? shown : `${clients.length} clientes: ${shown}${extra > 0 ? ` +${extra}` : ''}`}
      </span>
    </span>
  )
}

function EventsList({ events }) {
  if (events === null) {
    return (
      <div className="space-y-2">
        {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}
      </div>
    )
  }
  if (events.length === 0) {
    return (
      <div className="border border-dashed border-line rounded-xl p-10 text-center">
        <Calendar size={28} strokeWidth={1.5} className="mx-auto text-ink-3 mb-3" />
        <h3 className="text-sm font-semibold text-ink-0 mb-1">Sin eventos próximos</h3>
        <p className="text-xs text-ink-2 max-w-sm mx-auto">
          Cuando algún activo de tus clientes tenga un reporte, dividendo u
          otro evento en los próximos 90 días, aparece acá.
        </p>
      </div>
    )
  }
  return (
    <div className="bg-bg-1 border border-line/60 rounded-xl divide-y divide-line/40">
      {events.map((ev, i) => {
        const tone = BADGE_TONE[eventCategoryColor(ev.event_type)] || BADGE_TONE.gray
        return (
          <div key={`${ev.ticker}-${ev.event_type}-${ev.event_date}-${i}`} className="flex items-center gap-3 px-4 py-3 flex-wrap">
            <AssetLogo asset={ev.ticker} size={28} className="flex-shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-ink-0">
                <span className="font-semibold">{ev.ticker}</span>
                <span className="text-ink-2"> · {eventTypeIcon(ev.event_type)} {eventTypeLabel(ev.event_type)}</span>
                {!ev.confirmed && <span className="text-[10.5px] text-ink-3"> (estimado)</span>}
              </p>
              <div className="mt-1">
                <ClientsBadge clients={ev.clients} />
              </div>
            </div>
            <div className="text-right flex-shrink-0">
              <span className={`inline-block text-[10px] font-medium uppercase tracking-wide rounded px-1.5 py-0.5 ${tone}`}>
                {eventCategoryLabel(ev.event_type)}
              </span>
              <p className="text-xs text-ink-1 font-medium mt-1 tabular-nums">
                {formatRelativeDate(ev.event_date)}
              </p>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function NewsList({ news }) {
  const [tickerFilter, setTickerFilter] = useState(null)

  // Chips por ticker presentes en las noticias (los más frecuentes primero)
  const tickers = useMemo(() => {
    const count = new Map()
    for (const n of news || []) {
      if (n.ticker) count.set(n.ticker, (count.get(n.ticker) || 0) + 1)
    }
    return [...count.entries()].sort((a, b) => b[1] - a[1])
  }, [news])

  if (news === null) {
    return (
      <div className="space-y-2">
        {[...Array(5)].map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
      </div>
    )
  }
  if (news.length === 0) {
    return (
      <div className="border border-dashed border-line rounded-xl p-10 text-center">
        <Newspaper size={28} strokeWidth={1.5} className="mx-auto text-ink-3 mb-3" />
        <h3 className="text-sm font-semibold text-ink-0 mb-1">Sin noticias todavía</h3>
        <p className="text-xs text-ink-2 max-w-sm mx-auto">
          Buscamos noticias de los activos que tienen tus clientes — si acabás
          de cargar carteras, dale unos minutos y recargá.
        </p>
      </div>
    )
  }

  const visible = tickerFilter ? news.filter(n => n.ticker === tickerFilter) : news

  return (
    <div>
      {tickers.length > 1 && (
        <div className="flex items-center gap-1.5 flex-wrap mb-3">
          <button
            type="button"
            onClick={() => setTickerFilter(null)}
            className={`text-[11px] font-medium rounded px-2 py-1 transition-colors ${
              !tickerFilter ? 'text-ink-0 bg-bg-2' : 'text-ink-2 hover:text-ink-0 bg-bg-1'
            }`}
          >
            Todas ({news.length})
          </button>
          {tickers.slice(0, 12).map(([t, count]) => (
            <button
              key={t}
              type="button"
              onClick={() => setTickerFilter(tickerFilter === t ? null : t)}
              className={`text-[11px] font-medium rounded px-2 py-1 transition-colors ${
                tickerFilter === t ? 'text-ink-0 bg-bg-2' : 'text-ink-2 hover:text-ink-0 bg-bg-1'
              }`}
            >
              {t} ({count})
            </button>
          ))}
        </div>
      )}
      <div className="bg-bg-1 border border-line/60 rounded-xl divide-y divide-line/40">
        {visible.map((n, i) => {
          const { cleanTitle, sourceName } = splitTitleSource(n.title)
          return (
            <a
              key={`${n.url}-${i}`}
              href={n.url}
              target="_blank"
              rel="noopener noreferrer"
              className="block px-4 py-3 hover:bg-bg-2/50 transition-colors group"
            >
              <p className="text-sm text-ink-0 leading-snug group-hover:text-data-violet transition-colors">
                {cleanTitle || n.title}
                <ExternalLink size={11} strokeWidth={1.75} className="inline-block ml-1.5 -mt-0.5 text-ink-3" />
              </p>
              <div className="mt-1.5 flex items-center gap-2 flex-wrap text-[11px] text-ink-3">
                {n.ticker && <span className="font-medium text-ink-1">{n.ticker}</span>}
                {sourceName && <span>· {sourceName}</span>}
                {n.published_at && <span>· {formatNewsDate(n.published_at)}</span>}
                <ClientsBadge clients={n.clients} />
              </div>
            </a>
          )
        })}
      </div>
    </div>
  )
}

// Google News añade " - <Medio>" al final de cada título (misma convención
// que News.jsx).
function splitTitleSource(title) {
  if (!title) return { cleanTitle: '', sourceName: null }
  const idx = title.lastIndexOf(' - ')
  if (idx <= 0) return { cleanTitle: title, sourceName: null }
  return { cleanTitle: title.slice(0, idx), sourceName: title.slice(idx + 3) }
}

// Mismo formato relativo que News/TopNewsCard ("hace 2h", "hace 3d", "20 may").
function formatNewsDate(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const diffMin = Math.round((Date.now() - d.getTime()) / 60000)
    if (diffMin < 60) return `hace ${diffMin}m`
    const diffHr = Math.round(diffMin / 60)
    if (diffHr < 24) return `hace ${diffHr}h`
    const diffDays = Math.round(diffHr / 24)
    if (diffDays < 7) return `hace ${diffDays}d`
    return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short' })
  } catch {
    return iso
  }
}
