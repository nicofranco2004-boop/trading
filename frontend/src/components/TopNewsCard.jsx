// TopNewsCard — card "Lo que pasó hoy en tu cartera" para /home.
// ════════════════════════════════════════════════════════════════════════════
// Muestra hasta 3 noticias recientes de los tickers del user. Si no hay
// noticias personalizadas, NO se renderea — el dashboard no se inunda.
//
// Link "Ver todas" → /novedades?tab=noticias.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Newspaper, ArrowRight, ExternalLink } from 'lucide-react'
import AssetLogo from './AssetLogo'
import { api } from '../utils/api'

const MAX_ITEMS = 3

export default function TopNewsCard() {
  const [news, setNews] = useState([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    api.get(`/news/portfolio?limit=${MAX_ITEMS * 2}`)
      .then(r => setNews((r?.news || []).slice(0, MAX_ITEMS)))
      .catch(() => setNews([]))
      .finally(() => setLoaded(true))
  }, [])

  if (!loaded || news.length === 0) return null

  return (
    <div className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-line bg-slate-50/40 dark:bg-bg-2/40 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Newspaper size={14} strokeWidth={1.75} className="text-rendi-accent" />
          <span className="text-sm font-semibold text-ink-0">Lo que pasó hoy en tu cartera</span>
        </div>
        <Link
          to="/novedades?tab=noticias"
          className="text-[11px] text-rendi-accent hover:text-rendi-accent/80 font-mono inline-flex items-center gap-0.5"
        >
          Ver todas <ArrowRight size={11} strokeWidth={1.75} />
        </Link>
      </div>
      <ul className="divide-y divide-slate-100 dark:divide-line/40">
        {news.map(n => <NewsRow key={n.url} news={n} />)}
      </ul>
    </div>
  )
}

function NewsRow({ news }) {
  const { title, url, published_at, ticker } = news
  const lastDashIdx = title.lastIndexOf(' - ')
  const cleanTitle = lastDashIdx > 0 ? title.slice(0, lastDashIdx) : title
  const sourceName = lastDashIdx > 0 ? title.slice(lastDashIdx + 3) : null

  return (
    <li>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="block px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-bg-2/40 transition"
      >
        <div className="flex items-start gap-3">
          {ticker && <AssetLogo asset={ticker} size={28} />}
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2 mb-0.5">
              {ticker && (
                <span className="text-xs font-semibold text-ink-0 font-mono">{ticker}</span>
              )}
              {sourceName && (
                <span className="text-[10px] text-ink-3 font-mono">· {sourceName}</span>
              )}
              <span className="text-[10px] text-ink-3 font-mono">· {formatNewsDate(published_at)}</span>
            </div>
            <p className="text-sm text-ink-0 leading-snug line-clamp-2">{cleanTitle}</p>
          </div>
          <ExternalLink size={12} strokeWidth={1.5} className="text-ink-3 shrink-0 mt-1" />
        </div>
      </a>
    </li>
  )
}

function formatNewsDate(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const diffMs = Date.now() - d.getTime()
    const diffMin = Math.round(diffMs / 60000)
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
