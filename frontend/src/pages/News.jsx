// News — feed de noticias del mercado + personalizado al portfolio.
// ════════════════════════════════════════════════════════════════════════════
// Dos vistas (tabs):
//
//   • Para ti: noticias de los tickers en el portfolio del user.
//     Source: Google News RSS por ticker, fetcheado server-side.
//
//   • Mercado: noticias macro y de índices populares (S&P, FED, Merval, BCRA).
//     Source: Google News RSS por queries hardcoded.
//
// Diseño minimal: lista, no feed infinito. ~15-20 noticias por tab.
// Click → abre la noticia original en tab nueva.

import { useEffect, useMemo, useState } from 'react'
import { Newspaper, ExternalLink, AlertCircle } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import AssetLogo from '../components/AssetLogo'
import { api } from '../utils/api'

const TABS = [
  { value: 'portfolio', label: 'Para ti',  desc: 'Noticias de los activos de tu cartera' },
  { value: 'market',    label: 'Mercado', desc: 'Noticias macro y de índices populares' },
]

const LIMIT = 25

export default function News() {
  const [tab, setTab] = useState('portfolio')
  const [portfolioNews, setPortfolioNews] = useState([])
  const [marketNews, setMarketNews] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadAll()
  }, [])

  async function loadAll() {
    setLoading(true)
    setError(null)
    try {
      const [pn, mn] = await Promise.all([
        api.get(`/news/portfolio?limit=${LIMIT}`).catch(e => {
          console.warn('Portfolio news fetch failed:', e)
          return { news: [] }
        }),
        api.get(`/news/market?limit=${LIMIT}`).catch(e => {
          console.warn('Market news fetch failed:', e)
          return { news: [] }
        }),
      ])
      setPortfolioNews(pn?.news || [])
      setMarketNews(mn?.news || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const visibleNews = tab === 'portfolio' ? portfolioNews : marketNews

  return (
    <div className="page-shell-wide">
      <PageHeader
        title="Noticias"
        subtitle="Lo que pasa en el mercado y en los activos de tu cartera."
      />

      {/* Tabs */}
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

      <p className="text-xs text-ink-2 mb-4">
        {TABS.find(t => t.value === tab)?.desc}
      </p>

      {loading && <p className="text-sm text-ink-2 font-mono">Cargando noticias…</p>}
      {error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-sm bg-rendi-warn/10 text-rendi-warn text-sm">
          <AlertCircle size={14} /> {error}
        </div>
      )}
      {!loading && !error && visibleNews.length === 0 && (
        <EmptyState
          icon={<Newspaper size={32} />}
          title="Sin noticias por ahora"
          subtitle={tab === 'portfolio'
            ? 'No hay noticias recientes de los activos de tu cartera. Cargá posiciones o probá la pestaña "Mercado".'
            : 'No se pudieron traer noticias macro. Reintentá más tarde.'}
        />
      )}

      {!loading && visibleNews.length > 0 && (
        <ul className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded overflow-hidden divide-y divide-slate-100 dark:divide-line/40">
          {visibleNews.map(n => (
            <NewsItem key={n.url} news={n} tab={tab} />
          ))}
        </ul>
      )}

      <p className="mt-6 text-[10px] text-ink-3 font-mono leading-snug">
        Fuente: Google News RSS. Click sobre la noticia para abrir el artículo en su sitio original.
      </p>
    </div>
  )
}

function NewsItem({ news, tab }) {
  const { title, summary, url, published_at, ticker, query_source, source } = news
  // Sacar el nombre del medio del título — Google News pone " - <Medio>" al final.
  const lastDashIdx = title.lastIndexOf(' - ')
  const cleanTitle = lastDashIdx > 0 ? title.slice(0, lastDashIdx) : title
  const sourceName = lastDashIdx > 0 ? title.slice(lastDashIdx + 3) : null

  return (
    <li>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="block px-4 py-3 hover:bg-slate-50 dark:hover:bg-bg-2/40 transition"
      >
        <div className="flex items-start gap-3">
          {tab === 'portfolio' && ticker && (
            <div className="shrink-0 mt-0.5">
              <AssetLogo asset={ticker} size={32} />
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2 flex-wrap mb-1">
              {tab === 'portfolio' && ticker && (
                <span className="text-xs font-semibold text-ink-0 font-mono">{ticker}</span>
              )}
              {sourceName && (
                <span className="text-[10px] text-ink-3 font-mono">
                  · {sourceName}
                </span>
              )}
              <span className="text-[10px] text-ink-3 font-mono">
                · {formatNewsDate(published_at)}
              </span>
            </div>
            <p className="text-sm text-ink-0 leading-snug">{cleanTitle}</p>
            {summary && (
              <p className="text-[11px] text-ink-2 mt-1 leading-snug line-clamp-2">
                {summary}
              </p>
            )}
          </div>
          <ExternalLink size={14} strokeWidth={1.5} className="text-ink-3 shrink-0 mt-1" />
        </div>
      </a>
    </li>
  )
}

// Fecha relativa simple para noticias: "hace 2h" / "hace 3d" / "12 may"
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
