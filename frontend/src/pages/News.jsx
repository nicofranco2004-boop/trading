// News — feed de noticias del mercado + personalizado al portfolio.
// ════════════════════════════════════════════════════════════════════════════
// Diseño fintech (no foro):
//
//   • KPI strip arriba: total noticias, tickers cubiertos, source spread, último.
//   • Featured "hero" — la noticia más reciente, con tratamiento prominente.
//   • Grid de tiles compactos (2-3 cols) — no lista vertical.
//   • Chips de filtro por ticker (sólo en tab "Para ti").
//
// Dos vistas:
//   • Para ti: noticias de los tickers en el portfolio del user.
//   • Mercado: noticias macro y de índices populares.

import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Newspaper, ExternalLink, AlertCircle, Tag, Sparkles, Target } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import AssetLogo from '../components/AssetLogo'
import NewsTagBadge, { newsTagLabel } from '../components/NewsTagBadge'
import { api } from '../utils/api'
import { safeExternalUrl } from '../utils/safeUrl'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import InlineAIButton from '../components/ai/InlineAIButton'

const TABS = [
  { value: 'portfolio', label: 'Para ti',  desc: 'Noticias de los activos de tu cartera' },
  { value: 'market',    label: 'Mercado', desc: 'Macro, índices y bancos centrales' },
]

const LIMIT = 25
const TAB_VALUES = TABS.map(t => t.value)

// Sentimiento (heurística del backend). Clases literales completas para que el
// purge de Tailwind no las borre.
const SENTIMENT_META = {
  positive: { label: 'POS', dot: 'bg-rendi-pos', text: 'text-rendi-pos', stripe: 'border-l-rendi-pos' },
  negative: { label: 'NEG', dot: 'bg-rendi-neg', text: 'text-rendi-neg', stripe: 'border-l-rendi-neg' },
  neutral:  { label: 'NEU', dot: 'bg-ink-3',     text: 'text-ink-3',     stripe: 'border-l-line-3' },
}
function sentimentMeta(s) { return SENTIMENT_META[s] || SENTIMENT_META.neutral }

// "afecta X% de tu cartera" cuando el backend adjunta weight_pct (top holdings).
function weightLabel(weightPct) {
  if (weightPct == null || weightPct < 0.05) return null
  return `afecta ${weightPct.toFixed(1)}% de tu cartera`
}

export default function News({ embedded = false }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlSub = searchParams.get('sub')
  const initialTab = embedded && TAB_VALUES.includes(urlSub) ? urlSub : 'portfolio'
  const [tab, setTabState] = useState(initialTab)

  useEffect(() => {
    if (!embedded) return
    const s = searchParams.get('sub')
    if (TAB_VALUES.includes(s) && s !== tab) setTabState(s)
  }, [searchParams, embedded, tab])

  function setTab(value) {
    setTabState(value)
    if (embedded) {
      const next = new URLSearchParams(searchParams)
      next.set('sub', value)
      setSearchParams(next, { replace: true })
    }
  }

  const [portfolioNews, setPortfolioNews] = useState([])
  const [marketNews, setMarketNews] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [tickerFilter, setTickerFilter] = useState(null)  // null = sin filtro
  const [tagFilter, setTagFilter] = useState(null)        // null = sin filtro
  const [sentimentFilter, setSentimentFilter] = useState(null)  // null | 'positive' | 'negative'

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

  const rawNews = tab === 'portfolio' ? portfolioNews : marketNews
  const visibleNews = useMemo(() => {
    let list = rawNews
    if (tab === 'portfolio' && tickerFilter) {
      list = list.filter(n => n.ticker === tickerFilter)
    }
    if (tagFilter) {
      list = list.filter(n => Array.isArray(n.tags) && n.tags.includes(tagFilter))
    }
    if (sentimentFilter) {
      list = list.filter(n => (n.sentiment || 'neutral') === sentimentFilter)
    }
    return list
  }, [rawNews, tab, tickerFilter, tagFilter, sentimentFilter])

  // Tags presentes en el feed actual con conteo (para el filtro de chips)
  const availableTags = useMemo(() => {
    const counts = new Map()
    for (const n of rawNews) {
      if (!Array.isArray(n.tags)) continue
      for (const t of n.tags) counts.set(t, (counts.get(t) || 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1])
  }, [rawNews])

  // Lista de tickers presentes en las noticias del portfolio (para chips)
  const portfolioTickers = useMemo(() => {
    const counts = new Map()
    for (const n of portfolioNews) {
      if (!n.ticker) continue
      counts.set(n.ticker, (counts.get(n.ticker) || 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1])
  }, [portfolioNews])

  // KPIs
  const kpi = useMemo(() => computeKpis(rawNews, tab), [rawNews, tab])

  const containerClass = embedded ? '' : 'page-shell-wide'
  return (
    <div className={containerClass}>
      {!embedded && (
        <PageHeader
          title="Noticias"
          subtitle="Lo que pasa en el mercado y en los activos de tu cartera."
          action={<AnalyzeButton screen="news" subtitle="Tu radar de noticias" />}
        />
      )}

      {/* Sub-tabs Para ti / Mercado — pills. */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div
          role="tablist"
          aria-label="Origen de noticias"
          className="flex items-center gap-1.5 flex-wrap"
        >
          {TABS.map(t => {
            const active = tab === t.value
            return (
              <button
                key={t.value}
                role="tab"
                aria-selected={active}
                onClick={() => { setTab(t.value); setTickerFilter(null); setTagFilter(null); setSentimentFilter(null) }}
                className={`text-xs px-3 py-1.5 rounded-full border transition ${
                  active
                    ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40 font-semibold'
                    : 'bg-bg-2 text-ink-2 border-line hover:bg-bg-3'
                }`}
              >
                {t.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Briefing del día — CTA on-demand. Reusa el topic `news` (screen-level):
          una sola llamada IA que sintetiza las noticias pesadas por tu cartera.
          NO se auto-genera — el AnalysisDrawer solo dispara al hacer click. */}
      {embedded && (
        <div className="flex items-center gap-3 bg-bg-1 border border-data-violet/30 rounded-lg p-3.5 mb-4">
          <div className="w-9 h-9 rounded-lg bg-data-violet/15 flex items-center justify-center shrink-0">
            <Sparkles size={18} strokeWidth={1.75} className="text-data-violet" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-ink-0">Briefing del día con IA</p>
            <p className="text-xs text-ink-2 mt-0.5">
              Resumí {kpi.total > 0 ? `las ${kpi.total} noticias` : 'las noticias'} de tu cartera en pocas líneas.
            </p>
          </div>
          <AnalyzeButton screen="news" subtitle="Briefing del día" label="Generar briefing" />
        </div>
      )}

      {/* Clean pass 2026-07: el KPI strip (grilla con divisores, look planilla)
          se retiró — el conteo vive en el briefing y el feed habla solo. */}

      {/* Chips de filtro por ticker — sólo "Para ti" */}
      {tab === 'portfolio' && portfolioTickers.length > 1 && (
        <div className="flex items-center gap-1.5 mb-3 overflow-x-auto -mx-1 px-1 pb-1">
          <span className="label-mono shrink-0 pr-1">Ticker</span>
          <TickerChip
            label="Todos"
            count={portfolioNews.length}
            active={!tickerFilter}
            onClick={() => setTickerFilter(null)}
          />
          {portfolioTickers.slice(0, 12).map(([t, count]) => (
            <TickerChip
              key={t}
              label={t}
              count={count}
              active={tickerFilter === t}
              onClick={() => setTickerFilter(t === tickerFilter ? null : t)}
            />
          ))}
        </div>
      )}

      {/* Chips de filtro por TAG — aplica a ambos tabs */}
      {availableTags.length > 0 && (
        <div className="flex items-center gap-1.5 mb-4 overflow-x-auto -mx-1 px-1 pb-1">
          <Tag size={11} strokeWidth={1.75} className="text-ink-3 shrink-0" />
          <span className="label-mono shrink-0 pr-1">Tipo</span>
          <TickerChip
            label="Todos"
            count={rawNews.length}
            active={!tagFilter}
            onClick={() => setTagFilter(null)}
          />
          {availableTags.map(([t, count]) => (
            <TickerChip
              key={t}
              label={newsTagLabel(t)}
              count={count}
              active={tagFilter === t}
              onClick={() => setTagFilter(t === tagFilter ? null : t)}
            />
          ))}
        </div>
      )}

      {/* Filtro por sentimiento — POS/NEG detectado al ingerir (heurística). */}
      <div className="flex items-center gap-1.5 mb-4 flex-wrap">
        <span className="label-mono shrink-0 pr-1">Ánimo</span>
        {[
          { v: null, l: 'Todos' },
          { v: 'positive', l: 'Positivo', d: 'bg-rendi-pos' },
          { v: 'negative', l: 'Negativo', d: 'bg-rendi-neg' },
        ].map(o => (
          <button
            key={o.l}
            onClick={() => setSentimentFilter(o.v)}
            className={`inline-flex items-center gap-1.5 text-[12.5px] font-medium px-3 py-1.5 rounded-full border transition ${
              sentimentFilter === o.v
                ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40'
                : 'bg-bg-1 text-ink-2 border-line hover:text-ink-0'
            }`}
          >
            {o.d && <span className={`w-1.5 h-1.5 rounded-full ${o.d}`} />}
            {o.l}
          </button>
        ))}
      </div>

      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {[1,2,3,4,5,6].map(i => <NewsTileSkeleton key={i} />)}
        </div>
      )}
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
            ? 'No hay noticias recientes de los activos de tu cartera.'
            : 'No se pudieron traer noticias macro. Reintentá más tarde.'}
        />
      )}

      {!loading && visibleNews.length > 0 && (
        <NewsGrid news={visibleNews} tab={tab} onTagClick={setTagFilter} />
      )}

      <p className="mt-6 text-[12px] text-ink-3 leading-snug font-medium">
        Fuente · Google News RSS · click para abrir el artículo original
      </p>
    </div>
  )
}

// ─── Grid layout ────────────────────────────────────────────────────────────

function NewsGrid({ news, tab, onTagClick }) {
  if (news.length === 0) return null
  // Primera noticia = "featured" (más prominente). El resto se agrupa por
  // frescura (Hoy / Ayer / Esta semana / Antes) para dar ritmo al feed.
  const [featured, ...rest] = news
  const groups = groupByFreshness(rest)

  return (
    <div className="space-y-4">
      <NewsFeatured news={featured} tab={tab} onTagClick={onTagClick} />
      {groups.map(g => (
        <div key={g.label} className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[12.5px] text-ink-3 font-medium">{g.label}</span>
            <span className="h-px flex-1 bg-line" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {g.news.map(n => (
              <NewsTile key={n.url} news={n} tab={tab} onTagClick={onTagClick} />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// Bucket de frescura según published_at (mismo huso que el usuario).
function freshnessBucket(iso) {
  if (!iso) return 'Antes'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return 'Antes'
  const now = new Date()
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const t = d.getTime()
  if (t >= startToday) return 'Hoy'
  if (t >= startToday - 86400000) return 'Ayer'
  if (t >= startToday - 7 * 86400000) return 'Esta semana'
  return 'Antes'
}

function groupByFreshness(items) {
  const order = ['Hoy', 'Ayer', 'Esta semana', 'Antes']
  const map = new Map(order.map(k => [k, []]))
  for (const n of items) map.get(freshnessBucket(n.published_at)).push(n)
  return order.map(k => ({ label: k, news: map.get(k) })).filter(g => g.news.length > 0)
}

function NewsFeatured({ news, tab, onTagClick }) {
  const { title, summary, url, published_at, ticker, tags, sentiment, weight_pct } = news
  const { cleanTitle, sourceName } = splitTitleSource(title)
  const sm = sentimentMeta(sentiment)
  const wLabel = weightLabel(weight_pct)
  return (
    <div className="group relative bg-bg-1 border border-line rounded-xl hover:border-rendi-accent/40 transition">
    <a
      href={safeExternalUrl(url)}
      target="_blank"
      rel="noopener noreferrer"
      className="block p-4 sm:p-5"
    >
      <div className="flex flex-col sm:flex-row gap-4 sm:gap-5">
        {/* Side accent — color por sentimiento (verde/rojo/gris). */}
        <div className="hidden sm:flex flex-col items-center w-1 self-stretch">
          <span className={`block w-[2px] flex-1 ${sm.dot} rounded-full opacity-70`} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className="text-[12.5px] text-rendi-accent font-semibold">
              Destacada
            </span>
            {tab === 'portfolio' && ticker && (
              <span className="flex items-center gap-1.5">
                <AssetLogo asset={ticker} size={18} />
                <span className="text-[11px] font-mono font-semibold text-ink-0">{ticker}</span>
              </span>
            )}
            {sourceName && (
              <span className="text-[12px] text-ink-3">· <b className="text-ink-2 font-semibold">{sourceName}</b></span>
            )}
            <span className="text-[12px] text-ink-3">
              · {formatNewsDate(published_at)}
            </span>
            {sentiment && sentiment !== 'neutral' && (
              <span className={`inline-flex items-center gap-1 text-[12.5px] ${sm.text} font-medium`}>
                <span className={`w-1.5 h-1.5 rounded-full ${sm.dot}`} />{sm.label}
              </span>
            )}
          </div>
          <h3 className="text-base sm:text-lg text-ink-0 font-medium leading-snug group-hover:text-rendi-accent transition-colors">
            {cleanTitle}
          </h3>
          {summary && (
            <p className="text-[12px] text-ink-2 mt-2 leading-snug line-clamp-2">
              {summary}
            </p>
          )}
          {Array.isArray(tags) && tags.length > 0 && (
            <div className="flex items-center gap-1 mt-2.5 flex-wrap">
              {tags.slice(0, 3).map(t => (
                <NewsTagBadge key={t} tag={t} size="lg" onClick={onTagClick} />
              ))}
            </div>
          )}
        </div>

        <ExternalLink size={14} strokeWidth={1.5} className="text-ink-3 shrink-0 mt-1 self-start hidden sm:block" />
      </div>
    </a>
    {/* Pie: "Analizar" on-demand (reemplaza el ✦ flotante). Fuera del <a>
        para no disparar la navegación al pedir el análisis. */}
    {ticker && (
      <div className="px-4 sm:px-5 pb-4 -mt-2 flex items-center justify-between gap-2">
        {wLabel
          ? <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-data-cyan bg-data-cyan/10 rounded-full px-2.5 py-1"><Target size={11} strokeWidth={1.75} />{wLabel}</span>
          : <span />}
        <InlineAIButton
          topic="news.item"
          params={{ ticker, title: cleanTitle || title, source: sourceName, published_at, summary, tags }}
          subtitle={`${ticker} · ${sourceName || 'noticia destacada'}`}
          label="Analizar"
        />
      </div>
    )}
    </div>
  )
}

function NewsTile({ news, tab, onTagClick }) {
  const { title, summary, url, published_at, ticker, tags, sentiment, weight_pct } = news
  const { cleanTitle, sourceName } = splitTitleSource(title)
  const sm = sentimentMeta(sentiment)
  const wLabel = weightLabel(weight_pct)

  return (
    <div className={`group bg-bg-1 border border-line border-l-2 ${sm.stripe} rounded hover:border-rendi-accent/40 transition relative flex flex-col`}>
      <a
        href={safeExternalUrl(url)}
        target="_blank"
        rel="noopener noreferrer"
        className="block p-3.5"
      >
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        {tab === 'portfolio' && ticker && (
          <span className="flex items-center gap-1">
            <AssetLogo asset={ticker} size={16} />
            <span className="text-[10px] font-mono font-semibold text-ink-0">{ticker}</span>
          </span>
        )}
        {sourceName && (
          <span className="text-[11.5px] text-ink-3 font-medium truncate">{sourceName}</span>
        )}
        <span className="ml-auto flex items-center gap-1.5">
          {sentiment && sentiment !== 'neutral' && (
            <span className={`inline-flex items-center gap-1 text-[12.5px] ${sm.text} font-medium`}>
              <span className={`w-1.5 h-1.5 rounded-full ${sm.dot}`} />{sm.label}
            </span>
          )}
          <span className="text-[12.5px] text-ink-3 font-medium">
            {formatNewsDate(published_at)}
          </span>
        </span>
      </div>
      <p className="text-sm text-ink-0 leading-snug font-medium line-clamp-3 group-hover:text-rendi-accent transition-colors min-h-[60px]">
        {cleanTitle}
      </p>
      {summary && (
        <p className="text-[11px] text-ink-2 mt-2 leading-snug line-clamp-2">
          {summary}
        </p>
      )}
      {Array.isArray(tags) && tags.length > 0 && (
        <div className="flex items-center gap-1 mt-2 flex-wrap">
          {tags.slice(0, 2).map(t => (
            <NewsTagBadge key={t} tag={t} onClick={onTagClick} />
          ))}
        </div>
      )}
      <ExternalLink
        size={11}
        strokeWidth={1.5}
        className="text-ink-3 absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity"
      />
      </a>
      {/* Pie: "afecta X% de tu cartera" + "Analizar" on-demand. Fuera del <a>. */}
      {ticker && (
        <div className="px-3.5 pb-3 mt-auto flex items-center justify-between gap-2">
          {wLabel
            ? <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-data-cyan bg-data-cyan/10 rounded-full px-2 py-0.5 truncate"><Target size={10} strokeWidth={1.75} className="shrink-0" />{wLabel}</span>
            : <span />}
          <InlineAIButton
            topic="news.item"
            params={{ ticker, title: cleanTitle || title, source: sourceName, published_at, summary, tags }}
            subtitle={`${ticker} · ${sourceName || 'noticia'}`}
            label="Analizar"
          />
        </div>
      )}
    </div>
  )
}

function NewsTileSkeleton() {
  return (
    <div className="bg-bg-1 border border-line rounded-xl p-3.5 animate-pulse">
      <div className="h-3 w-20 bg-bg-3 rounded mb-3" />
      <div className="h-4 w-full bg-bg-3 rounded mb-2" />
      <div className="h-4 w-3/4 bg-bg-3 rounded mb-3" />
      <div className="h-3 w-full bg-bg-3/60 rounded" />
    </div>
  )
}

// ─── KPI strip ──────────────────────────────────────────────────────────────

function computeKpis(news, tab) {
  const total = news.length
  const tickers = new Set()
  const sources = new Set()
  let todayCount = 0
  const now = Date.now()
  for (const n of news) {
    if (n.ticker) tickers.add(n.ticker)
    const { sourceName } = splitTitleSource(n.title || '')
    if (sourceName) sources.add(sourceName)
    if (n.published_at) {
      const d = new Date(n.published_at)
      if (now - d.getTime() < 24 * 3600 * 1000) todayCount += 1
    }
  }
  const last = news[0]
  const lastRelative = last ? formatNewsDate(last.published_at) : '—'
  const { sourceName: lastSource } = last ? splitTitleSource(last.title || '') : { sourceName: '' }
  return {
    total,
    uniqueTickers: tab === 'portfolio' ? tickers.size : 0,
    uniqueSources: sources.size,
    todayCount,
    lastRelative,
    lastSource,
  }
}

// ─── Chips de ticker ────────────────────────────────────────────────────────

function TickerChip({ label, count, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`shrink-0 inline-flex items-center gap-1.5 text-[12.5px] font-medium px-3 py-1.5 rounded-full border transition ${
        active
          ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40 font-semibold'
          : 'bg-bg-1 text-ink-2 border-line hover:text-ink-0'
      }`}
    >
      <span>{label}</span>
      <span className={active ? 'text-rendi-accent/70' : 'text-ink-3'}>{count}</span>
    </button>
  )
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function splitTitleSource(title) {
  // Google News añade " - <Medio>" al final de cada título.
  if (!title) return { cleanTitle: '', sourceName: null }
  const idx = title.lastIndexOf(' - ')
  if (idx <= 0) return { cleanTitle: title, sourceName: null }
  return { cleanTitle: title.slice(0, idx), sourceName: title.slice(idx + 3) }
}

function formatNewsDate(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    const diffMs = Date.now() - d.getTime()
    const diffMin = Math.round(diffMs / 60000)
    if (diffMin < 60) return `${diffMin}m`
    const diffHr = Math.round(diffMin / 60)
    if (diffHr < 24) return `${diffHr}h`
    const diffDays = Math.round(diffHr / 24)
    if (diffDays < 7) return `${diffDays}d`
    return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short' }).replace('.', '')
  } catch {
    return iso
  }
}
