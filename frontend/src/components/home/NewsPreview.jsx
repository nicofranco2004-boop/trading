// NewsPreview — top 3 noticias del mercado. Linkea a /novedades para deep dive.
// Reusa el endpoint /api/news/market existente.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Newspaper, ExternalLink } from 'lucide-react'
import { api } from '../../utils/api'

function fmtTimeAgo(iso) {
  if (!iso) return ''
  const now = new Date()
  const then = new Date(iso)
  const diffMin = Math.floor((now - then) / 60000)
  if (diffMin < 1) return 'ahora'
  if (diffMin < 60) return `hace ${diffMin} min`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `hace ${diffH}h`
  const diffD = Math.floor(diffH / 24)
  return `hace ${diffD}d`
}

export default function NewsPreview() {
  const [news, setNews] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api.get('/news/market?limit=3')
      .then(d => { if (!cancelled) setNews(d.news || []) })
      .catch(() => { if (!cancelled) setNews([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  return (
    <section className="rounded-sm border border-line bg-bg-1 overflow-hidden">
      <header className="px-4 py-3 border-b border-line/40 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-display uppercase tracking-wider text-ink-2">
          <Newspaper size={13} strokeWidth={1.75} aria-hidden="true" />
          Noticias del mercado
        </h2>
        <Link
          to="/novedades?tab=noticias"
          className="text-[11px] text-ink-3 hover:text-ink-0 inline-flex items-center gap-1"
        >
          Ver todas <ArrowRight size={11} strokeWidth={1.75} aria-hidden="true" />
        </Link>
      </header>

      {loading ? (
        <div className="p-4 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-12 rounded-sm bg-bg-2 animate-pulse" />
          ))}
        </div>
      ) : news.length === 0 ? (
        <div className="p-4 text-xs text-ink-3">Sin noticias disponibles ahora.</div>
      ) : (
        <ul className="divide-y divide-line/30">
          {news.map((n, i) => (
            <li key={i}>
              <a
                href={n.url}
                target="_blank" rel="noopener noreferrer"
                className="block px-4 py-3 hover:bg-bg-2/40 transition-colors"
              >
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-ink-1 leading-snug line-clamp-2">{n.title}</p>
                    <div className="flex items-center gap-2 mt-1 text-[10px] text-ink-3">
                      <span>{n.source || '—'}</span>
                      <span>·</span>
                      <span>{fmtTimeAgo(n.published_at)}</span>
                    </div>
                  </div>
                  <ExternalLink size={11} className="flex-shrink-0 mt-1 text-ink-3" strokeWidth={1.75} aria-hidden="true" />
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
