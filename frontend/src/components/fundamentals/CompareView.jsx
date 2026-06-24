// CompareView — vista "Comparar" de Fundamentals (hasta 5 acciones lado a lado).
// ═══════════════════════════════════════════════════════════════════════════
// Flujo:
//   1. Selector: chips removibles (AssetLogo + symbol + ×) + TickerSearch para
//      agregar (cap 5) + "N de 5 seleccionadas". La lista se persiste en
//      ?cmp=NVDA,MSFT,… (compartible).
//   2. Fetch GET /fundamentals/{t} en paralelo por ticker. available:false →
//      aviso chico. Skeletons mientras carga.
//   3. RANKING: header "X lidera con score N — gana en M de T métricas" + cards
//      por ticker (ordenadas por overall desc, rank badge, ScoreGauge, label,
//      "⚡ Gana N métricas", top-3 métricas, star toggle).
//   4. GANADOR POR CATEGORÍA: 4 pilares.
//   5. DETALLE MÉTRICA POR MÉTRICA: tablas colapsables por categoría con celda
//      ganadora resaltada (trofeo + barra relativa + hint de dirección).
//
// Toda la lógica de "quién gana" es pura → utils/fundamentalsCompare.js.

import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  X, Plus, Zap, Trophy, ChevronDown, ChevronRight, Layers, AlertCircle,
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
import ScoreGauge from './ScoreGauge'
import StarToggle from './StarToggle'
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

  // Fetch de los tickers que faltan / sin resolver.
  useEffect(() => {
    let cancelled = false
    const missing = selected.filter(t => !results[t])
    if (missing.length === 0) return
    setResults(prev => {
      const next = { ...prev }
      for (const t of missing) next[t] = { loading: true, data: null, error: null }
      return next
    })
    for (const t of missing) {
      api.get('/fundamentals/' + encodeURIComponent(t))
        .then(res => {
          if (cancelled) return
          setResults(prev => ({ ...prev, [t]: { loading: false, data: res, error: null } }))
        })
        .catch(e => {
          if (cancelled) return
          setResults(prev => ({ ...prev, [t]: { loading: false, data: null, error: e?.message || 'Error' } }))
        })
    }
    return () => { cancelled = true }
  }, [selected]) // eslint-disable-line react-hooks/exhaustive-deps

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
            description="Buscá tickers arriba (NVDA, MSFT, MELI…). Vamos a rankearlas por score, mostrar quién gana cada categoría y el detalle métrica por métrica."
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
          <RankingBlock comparison={comparison} watchlist={watchlist} onOpenTicker={onOpenTicker} />
          <CategoryWinners comparison={comparison} />
          <MetricDetail comparison={comparison} />
        </>
      )}
    </div>
  )
}

// ─── RANKING ──────────────────────────────────────────────────────────────
function RankingBlock({ comparison, watchlist, onOpenTicker }) {
  const { leader, comparableCount, ranking, winsByTicker } = comparison
  const leaderRow = ranking[0]

  return (
    <section>
      <div className="mb-3">
        <p className="text-[11px] font-mono uppercase tracking-label text-ink-2 mb-1">Ranking</p>
        {leader && (
          <p className="text-sm text-ink-1 leading-snug">
            <span className="font-semibold text-ink-0">{leader.ticker}</span> lidera con un score de{' '}
            <span className="font-semibold text-rendi-pos tabular">{leader.overall ?? '—'}</span>
            {' '}— gana en{' '}
            <span className="font-semibold text-ink-0 tabular">{leader.wins}</span> de{' '}
            <span className="tabular">{comparableCount}</span> métricas comparables.
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {ranking.map((r, idx) => {
          const isLeader = idx === 0
          const d = r.data
          const top3 = topMetricsFor(d, 3)
          return (
            <Panel
              key={r.ticker}
              padding="md"
              accent={isLeader}
              className={isLeader ? 'bg-rendi-pos/[0.04]' : ''}
            >
              <div className="flex items-start justify-between gap-2 mb-3">
                <button
                  type="button"
                  onClick={() => onOpenTicker?.(r.ticker)}
                  className="flex items-center gap-2 min-w-0 text-left group"
                  title={`Ver ${r.ticker} en Analizar`}
                >
                  <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-[11px] font-mono font-semibold flex-shrink-0 ${
                    isLeader ? 'bg-rendi-pos/15 text-rendi-pos' : 'bg-bg-2 text-ink-2'
                  }`}>
                    {idx + 1}
                  </span>
                  <AssetLogo asset={r.ticker} size={24} />
                  <span className="min-w-0">
                    <span className="block font-mono text-sm font-semibold text-ink-0 group-hover:text-data-violet transition-colors truncate">
                      {r.ticker}
                    </span>
                    <span className="block text-[11px] text-ink-3 truncate">
                      {d.company_name || d.sector || ''}
                    </span>
                  </span>
                </button>
                {watchlist && (
                  <StarToggle active={watchlist.has(r.ticker)} onToggle={() => watchlist.toggle(r.ticker)} size={15} />
                )}
              </div>

              <div className="flex items-center gap-4">
                <ScoreGauge score={r.overall} label={r.label} size={92} />
                <div className="min-w-0 space-y-2">
                  <span className="inline-flex items-center gap-1 text-[11px] font-mono text-rendi-pos bg-rendi-pos/10 border border-rendi-pos/25 rounded-sm px-1.5 py-0.5">
                    <Zap size={11} strokeWidth={2} /> Gana {winsByTicker[r.ticker] || 0} métricas
                  </span>
                  <ul className="space-y-1">
                    {top3.map(m => (
                      <li key={m.key} className="flex items-center justify-between gap-2 text-[11px]">
                        <span className="text-ink-3 truncate">{m.label}</span>
                        <span className="font-mono text-ink-1 tabular flex-shrink-0">{m.value_label}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </Panel>
          )
        })}
      </div>
    </section>
  )
}

// ─── GANADOR POR CATEGORÍA ──────────────────────────────────────────────────
function CategoryWinners({ comparison }) {
  const { categoryWinner } = comparison
  return (
    <section>
      <p className="text-[11px] font-mono uppercase tracking-label text-ink-2 mb-3">Ganador por categoría</p>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {CATEGORY_ORDER.map(cat => {
          const Icon = CATEGORY_ICON[cat]
          const w = categoryWinner[cat]
          return (
            <Panel key={cat} padding="md">
              <div className="flex items-center gap-1.5 text-ink-3 mb-3">
                {Icon && <Icon size={14} strokeWidth={1.75} />}
                <span className="text-[11px] font-medium text-ink-2">{CATEGORY_LABELS[cat]}</span>
              </div>
              {w ? (
                <>
                  <div className="flex items-center gap-2 mb-1.5">
                    <AssetLogo asset={w.ticker} size={22} />
                    <span className="font-mono text-sm font-semibold text-ink-0">{w.ticker}</span>
                    <Trophy size={14} className="text-rendi-pos" strokeWidth={1.75} />
                  </div>
                  {w.metricLabel && (
                    <p className="text-[11px] text-ink-3">
                      {w.metricLabel}:{' '}
                      <span className="font-mono text-rendi-pos tabular">{w.metricValueLabel}</span>
                    </p>
                  )}
                </>
              ) : (
                <p className="text-[11px] text-ink-3">Sin datos suficientes</p>
              )}
            </Panel>
          )
        })}
      </div>
    </section>
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
              <tr className="border-b border-line/40">
                <th className="text-left font-normal text-[10px] font-mono uppercase tracking-caps text-ink-3 px-4 py-2">
                  Métrica
                </th>
                {tickers.map(t => (
                  <th key={t} className="text-right font-mono text-xs font-semibold text-ink-1 px-3 py-2 whitespace-nowrap">
                    {t}
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
              {isWinner && <Trophy size={12} className="text-rendi-pos flex-shrink-0" strokeWidth={1.75} />}
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
