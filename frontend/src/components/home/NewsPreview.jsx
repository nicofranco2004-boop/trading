// NewsPreview — top 3 noticias del mercado (V2).
// Panel denso. Link a /novedades para deep dive.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Newspaper, ExternalLink } from 'lucide-react'
import { api } from '../../utils/api'
import { safeExternalUrl } from '../../utils/safeUrl'
import Panel from '../Panel'
import Eyebrow from '../Eyebrow'

function fmtTimeAgo(iso) {
  if (!iso) return ''
  const now = new Date()
  const then = new Date(iso)
  const diffMin = Math.floor((now - then) / 60000)
  if (diffMin < 1) return 'ahora'
  if (diffMin < 60) return `hace ${diffMin}m`
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
    <Panel padding="none" className="overflow-hidden">
      <header className="px-3 py-2 border-b border-line flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Newspaper size={12} strokeWidth={1.75} className="text-ink-3" aria-hidden="true" />
          <Eyebrow>Noticias del mercado</Eyebrow>
        </div>
        <Link
          to="/novedades?tab=noticias"
          className="text-[11px] text-ink-2 hover:text-ink-0 inline-flex items-center gap-1 font-mono uppercase tracking-caps"
        >
          Ver todas <ArrowRight size={10} strokeWidth={1.75} aria-hidden="true" />
        </Link>
      </header>

      {loading ? (
        <div className="p-3 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-12 rounded-sm bg-bg-2 animate-pulse" />
          ))}
        </div>
      ) : news.length === 0 ? (
        <div className="p-4 text-xs text-ink-3">Sin noticias disponibles ahora.</div>
      ) : (
        <ul className="divide-y divide-line/40">
          {news.map((n, i) => (
            <li key={i}>
              <a
                href={safeExternalUrl(n.url)}
                target="_blank" rel="noopener noreferrer"
                className="block px-3 py-2.5 hover:bg-bg-2/60 transition-colors"
              >
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-ink-1 leading-snug line-clamp-2">{n.title}</p>
                    <div className="flex items-center gap-1.5 mt-1 text-[10px] text-ink-3 font-mono">
                      <span className="uppercase tracking-caps">{n.source || '—'}</span>
                      <span>·</span>
                      <span>{fmtTimeAgo(n.published_at)}</span>
                    </div>
                  </div>
                  <ExternalLink size={10} className="flex-shrink-0 mt-1 text-ink-3" strokeWidth={1.75} aria-hidden="true" />
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
