// CompareView — vista "Comparar" de Fundamentals (hasta 5 acciones lado a lado).
// ═══════════════════════════════════════════════════════════════════════════
// Flujo:
//   1. Selector: chips removibles (AssetLogo + symbol + ×) + TickerSearch para
//      agregar (cap 5) + "N de 5 seleccionadas". La lista se persiste en
//      ?cmp=NVDA,MSFT,… (compartible).
//   2. Fetch GET /fundamentals/{t} en paralelo por ticker. available:false →
//      aviso chico. Skeletons mientras carga.
//   3. CARDS: por ticker, los dos ejes Negocio / Precio + top-3 métricas + star.
//      Sin gauge, sin "ranking por score", sin trofeos (eso era Vesty).
//   4. DETALLE MÉTRICA POR MÉTRICA: tablas colapsables por categoría con la mejor
//      celda resaltada (check + barra relativa + hint de dirección).
//
// Toda la lógica de "quién gana" es pura → utils/fundamentalsCompare.js.

import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import {
  X, Plus, Zap, Check, ChevronDown, ChevronRight, Layers, AlertCircle,
  Tag, TrendingUp, ShieldCheck,
} from 'lucide-react'
import Panel from '../Panel'
import Pill from '../Pill'
import EmptyState from '../EmptyState'
import Skeleton from '../Skeleton'
import AssetLogo from '../AssetLogo'
import { api } from '../../utils/api'
import { track } from '../../utils/track'
import TickerSearch from './TickerSearch'
import StarToggle from './StarToggle'
import { businessQuality, priceRead, AXIS_PILL } from './axes'
import {
  buildComparison, topMetricsFor, relativeFill,
  CATEGORY_ORDER, CATEGORY_LABELS,
} from '../../utils/fundamentalsCompare'

const MAX = 5

const CATEGORY_ICON = {
  valuation: Tag,
  growth: TrendingUp,
  profitability: Zap,
  health: ShieldCheck,
}

const RANK_LABEL = ['1.º', '2.º', '3.º', '4.º', '5.º']

export default function CompareView({ tickers, onChangeTickers, onOpenTicker, watchlist }) {
  // results: { [ticker]: { loading, data, error } }
  const [results, setResults] = useState({})

  const selected = tickers // array de strings upper, controlado por el padre

  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])

  // Fetch de los tickers que faltan / sin resolver. Dep ESTABLE (join) y SIN
  // cancelar por re-run: `selected` cambia de identidad en cada render (parseCmp
  // del padre), así que un cleanup por-run cancelaría los fetch en vuelo y dejaría
  // skeletons eternos (mismo bug que CarteraList). El filtro `missing` evita pedir
  // dos veces; solo frenamos al desmontar.
  useEffect(() => {
    const missing = selected.filter(t => !results[t])
    if (missing.length === 0) return
    setResults(prev => {
      const next = { ...prev }
      for (const t of missing) next[t] = { loading: true, data: null, error: null }
      return next
    })
    for (const t of missing) {
      api.get('/fundamentals/' + encodeURIComponent(t))
        .then(res => { if (mounted.current) setResults(prev => ({ ...prev, [t]: { loading: false, data: res, error: null } })) })
        .catch(e => { if (mounted.current) setResults(prev => ({ ...prev, [t]: { loading: false, data: null, error: e?.message || 'Error' } })) })
    }
  }, [selected.join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  // Track comparación cuando hay ≥2 con data lista.
  const readyEntries = useMemo(() => selected
    .map(t => ({ ticker: t, ...(results[t] || {}) }))
    .filter(r => r.data && r.data.available)
    .map(r => ({ ticker: r.ticker, data: r.data })),
  [selected, results])

  useEffect(() => {
    if (readyEntries.length >= 2) {
      const ts = readyEntries.map(e => e.ticker)
      track('fundamentals_compared', { tickers: ts, n: ts.length })
    }
  }, [readyEntries.map(e => e.ticker).join(',')]) // eslint-disable-line react-hooks/exhaustive-deps

  function addTicker(symbol) {
    const sym = (symbol || '').toUpperCase()
    if (!sym || selected.includes(sym) || selected.length >= MAX) return
    onChangeTickers([...selected, sym])
  }

  function removeTicker(symbol) {
    onChangeTickers(selected.filter(t => t !== symbol))
  }

  const anyLoading = selected.some(t => results[t]?.loading)
  const unavailable = selected.filter(t => results[t]?.data && results[t].data.available === false)
  const errored = selected.filter(t => results[t]?.error)

  const comparison = useMemo(
    () => (readyEntries.length >= 2 ? buildComparison(readyEntries) : null),
    [readyEntries],
  )

  return (
    <div className="space-y-6">
      {/* ── Selector ───────────────────────────────────────────────────────── */}
      <Panel>
        <div className="flex items-center justify-between gap-3 mb-3">
          <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
            Acciones a comparar
          </p>
          <span className="text-[11px] font-mono text-ink-3 tabular">
            {selected.length} de {MAX} seleccionadas
          </span>
        </div>

        {selected.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {selected.map(t => (
              <span
                key={t}
                className="inline-flex items-center gap-2 pl-1.5 pr-1.5 py-1 rounded-full border border-line bg-bg-2 text-ink-1"
              >
                <AssetLogo asset={t} size={18} />
                <span className="font-mono text-xs font-medium">{t}</span>
                <button
                  type="button"
                  onClick={() => removeTicker(t)}
                  className="text-ink-3 hover:text-rendi-neg p-0.5"
                  aria-label={`Quitar ${t}`}
                >
                  <X size={12} strokeWidth={2} />
                </button>
              </span>
            ))}
          </div>
        )}

        {selected.length < MAX ? (
          <TickerSearch onSelect={addTicker} autoFocus={selected.length === 0} />
        ) : (
          <p className="text-xs text-ink-3 flex items-center gap-1.5">
            <Plus size={13} className="rotate-45" /> Llegaste al máximo de {MAX}. Quitá una para agregar otra.
          </p>
        )}
      </Panel>

      {/* Avisos de tickers sin fundamentales / con error */}
      {(unavailable.length > 0 || errored.length > 0) && (
        <div className="space-y-2">
          {unavailable.map(t => (
            <div key={t} className="flex items-start gap-2 text-xs text-rendi-warn bg-rendi-warn/5 border border-rendi-warn/20 rounded px-3 py-2">
              <AlertCircle size={13} className="mt-0.5 flex-shrink-0" />
              <span><span className="font-mono font-medium">{t}</span> — {results[t].data.reason || 'sin fundamentales para comparar'}.</span>
            </div>
          ))}
          {errored.map(t => (
            <div key={t} className="flex items-start gap-2 text-xs text-rendi-neg bg-rendi-neg/5 border border-rendi-neg/20 rounded px-3 py-2">
              <AlertCircle size={13} className="mt-0.5 flex-shrink-0" />
              <span><span className="font-mono font-medium">{t}</span> — {results[t].error}</span>
            </div>
          ))}
        </div>
      )}

      {/* Empty state — menos de 2 acciones comparables */}
      {readyEntries.length < 2 && !anyLoading && (
        <Panel padding="lg">
          <EmptyState
            icon={<Layers size={20} strokeWidth={1.75} />}
            eyebrow="COMPARAR"
            title="Agregá al menos 2 acciones para comparar"
            description="Buscá tickers arriba (NVDA, MSFT, MELI…). Vas a ver el negocio y el precio de cada una, lado a lado, y el detalle métrica por métrica."
          />
        </Panel>
      )}

      {/* Skeletons mientras carga el primer batch */}
      {anyLoading && readyEntries.length < 2 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {selected.filter(t => results[t]?.loading).map(t => (
            <Skeleton key={t} className="h-44 w-full rounded" />
          ))}
        </div>
      )}

      {/* ── Resultados de comparación ──────────────────────────────────────── */}
      {comparison && (
        <>
          <CompareCards entries={readyEntries} watchlist={watchlist} onOpenTicker={onOpenTicker} />
          <MetricDetail comparison={comparison} />
        </>
      )}
    </div>
  )
}

// ─── Comparación lado a lado: dos ejes (negocio/precio) por acción, sin gauge ──
// Sin "ranking por score" ni "gana X métricas" ni trofeos (eso era Vesty). Cada
// acción muestra su negocio y su precio; quién gana cada métrica vive abajo, en
// la tabla de detalle. Orden = el que las agregaste (sin ranking implícito).
function CompareCards({ entries, watchlist, onOpenTicker }) {
  return (
    <section>
      <p className="text-[11px] font-mono uppercase tracking-label text-ink-2 mb-3">Negocio y precio, lado a lado</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {entries.map(({ ticker, data }) => {
          const cats = data.score?.categories || []
          const top3 = topMetricsFor(data, 3)
          return (
            <Panel key={ticker} padding="md">
              <div className="flex items-start justify-between gap-2 mb-3">
                <button
                  type="button"
                  onClick={() => onOpenTicker?.(ticker)}
                  className="flex items-center gap-2 min-w-0 text-left group"
                  title={`Ver ${ticker} en Explorar`}
                >
                  <AssetLogo asset={ticker} size={26} />
                  <span className="min-w-0">
                    <span className="block font-mono text-sm font-semibold text-ink-0 group-hover:text-data-violet transition-colors truncate">
                      {ticker}
                    </span>
                    <span className="block text-[11px] text-ink-3 truncate">{data.company_name || data.sector || ''}</span>
                  </span>
                </button>
                {watchlist && (
                  <StarToggle active={watchlist.has(ticker)} onToggle={() => watchlist.toggle(ticker)} size={15} />
                )}
              </div>

              <div className="grid grid-cols-2 gap-3 mb-3">
                <AxisMini label="Negocio" read={businessQuality(cats)} />
                <AxisMini label="Precio" read={priceRead(cats)} />
              </div>

              <ul className="space-y-1 border-t border-line/40 pt-2">
                {top3.map(m => (
                  <li key={m.key} className="flex items-center justify-between gap-2 text-[11px]">
                    <span className="text-ink-3 truncate">{m.label}</span>
                    <span className="font-mono text-ink-1 tabular flex-shrink-0">{m.value_label}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          )
        })}
      </div>
    </section>
  )
}

function AxisMini({ label, read }) {
  return (
    <div>
      <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1">{label}</p>
      {read ? <Pill tone={AXIS_PILL[read.tone]}>{read.label}</Pill> : <span className="text-[11px] text-ink-3">—</span>}
    </div>
  )
}

// ─── DETALLE MÉTRICA POR MÉTRICA ────────────────────────────────────────────
function MetricDetail({ comparison }) {
  const { tickers, rowsByCategory } = comparison
  return (
    <section>
      <p className="text-[11px] font-mono uppercase tracking-label text-ink-2 mb-3">Detalle métrica por métrica</p>
      <div className="space-y-3">
        {CATEGORY_ORDER.map(cat => {
          const rows = rowsByCategory[cat] || []
          if (rows.length === 0) return null
          return <CategorySection key={cat} category={cat} rows={rows} tickers={tickers} />
        })}
      </div>
    </section>
  )
}

function CategorySection({ category, rows, tickers }) {
  const [open, setOpen] = useState(true)
  const Icon = CATEGORY_ICON[category]
  return (
    <Panel padding="none" className="overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-2 px-4 py-3 hover:bg-bg-2 transition-colors"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2 text-sm font-medium text-ink-0">
          {Icon && <Icon size={15} strokeWidth={1.75} className="text-ink-3" />}
          {CATEGORY_LABELS[category]}
        </span>
        {open ? <ChevronDown size={16} className="text-ink-3" /> : <ChevronRight size={16} className="text-ink-3" />}
      </button>

      {open && (
        <div className="overflow-x-auto border-t border-line/40">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line bg-bg-2/60">
                <th scope="col" className="text-left font-normal text-[10px] font-mono uppercase tracking-caps text-ink-3 px-4 py-2.5">
                  Métrica
                </th>
                {tickers.map(t => (
                  <th key={t} scope="col" className="px-3 py-2.5 whitespace-nowrap">
                    <span className="flex items-center justify-end gap-1.5">
                      <AssetLogo asset={t} size={18} />
                      <span className="font-mono text-sm font-semibold text-ink-0">{t}</span>
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(row => (
                <MetricRow key={row.key} row={row} tickers={tickers} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

function MetricRow({ row, tickers }) {
  const dirHint = row.direction === 'lower' ? '↓ menor es mejor' : '↑ mayor es mejor'
  return (
    <tr className="border-b border-line/20 last:border-0">
      <td className="px-4 py-2.5 align-middle">
        <div className="text-ink-1 leading-tight">{row.label}</div>
        <div className="text-[10px] text-ink-3 font-mono">{dirHint}</div>
      </td>
      {row.cells.map((cell, i) => {
        const isWinner = row.winnerIndex === i && row.comparable
        const hasVal = typeof cell.value === 'number' && !Number.isNaN(cell.value)
        const fill = hasVal && row.comparable
          ? relativeFill(cell.value, row.min, row.max, row.direction)
          : 0
        return (
          <td
            key={tickers[i]}
            className={`px-3 py-2.5 text-right align-middle ${
              isWinner ? 'bg-rendi-pos/10' : ''
            } ${isWinner ? 'border-l border-r border-rendi-pos/30' : ''}`}
          >
            <div className="flex items-center justify-end gap-1.5">
              {isWinner && <Check size={12} className="text-rendi-pos flex-shrink-0" strokeWidth={2.5} />}
              <span className={`font-mono tabular text-[13px] ${
                !hasVal ? 'text-ink-3' : isWinner ? 'text-rendi-pos font-semibold' : 'text-ink-1'
              }`}>
                {cell.value_label}
              </span>
            </div>
            {hasVal && row.comparable && (
              <div className="mt-1 h-1 w-full rounded-full bg-bg-2 overflow-hidden">
                <div
                  className={`h-full rounded-full ${isWinner ? 'bg-rendi-pos' : 'bg-ink-3/50'}`}
                  style={{ width: `${Math.round(fill * 100)}%` }}
                />
              </div>
            )}
          </td>
        )
      })}
    </tr>
  )
}
