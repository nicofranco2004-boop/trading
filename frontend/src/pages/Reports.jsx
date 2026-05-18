// Reports — timeline operativa de Rendi (V2 redesign).
// ════════════════════════════════════════════════════════════════════════════
// Estructura:
//   1. Header compacto (eyebrow + título + broker selector)
//   2. PerformanceCalendar — KPI strip + heatmap anual de meses
//   3. Year selector (tabs) — qué año mirar en detalle
//   4. MonthlyTable — fila por mes del año seleccionado (densa, mono caps)
//   5. MonthCard expandible inline — click en fila → expand
//
// Decisión: el user elige qué mes abrir. Por default nada está expandido.

import { useState, useMemo, Fragment } from 'react'
import { Link } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import { Loader2, FileText, AlertTriangle, ChevronDown, ChevronUp, ArrowRight } from 'lucide-react'
import useReportsTimeline from '../hooks/useReportsTimeline'
import BrokerSelector from '../components/reports/BrokerSelector'
import MonthCard from '../components/reports/MonthCard'
import PerformanceCalendar from '../components/reports/PerformanceCalendar'
import InlineAIButton from '../components/ai/InlineAIButton'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import LockedSection from '../components/plan/LockedSection'
import ExportCsvButton from '../components/plan/ExportCsvButton'
import { usePlanFeatures } from '../hooks/usePlanFeatures'

// ─── helpers ─────────────────────────────────────────────────────────────────

function fmtPct(p) {
  if (p == null) return '—'
  const abs = Math.abs(p)
  const sign = p >= 0 ? '+' : '−'
  return `${sign}${abs.toFixed(abs >= 10 ? 1 : 2)}%`
}

function fmtUsd(v) {
  if (v == null) return '—'
  const abs = Math.abs(v)
  const sign = v >= 0 ? '+' : '−'
  return `${sign}US$${abs.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`
}

function monthNum(period_key) {
  if (!period_key) return null
  const m = period_key.match(/-(\d{1,2})/)
  return m ? parseInt(m[1], 10) : null
}

const MONTH_NAMES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

// ─── Reports root ────────────────────────────────────────────────────────────

export default function Reports() {
  const [broker, setBroker] = useState('global')
  const { loading, error, yearGroups, hasAnyData } = useReportsTimeline(broker, 12)
  const todayYear = new Date().getFullYear()
  const [selectedYear, setSelectedYear] = useState(null)
  const [expandedKey, setExpandedKey] = useState(null)
  const plan = usePlanFeatures()

  // Año seleccionado por default: el actual si existe en yearGroups, sino el más reciente.
  const effectiveYear = useMemo(() => {
    if (!yearGroups.length) return null
    if (selectedYear && yearGroups.some(g => g.year === selectedYear)) return selectedYear
    if (yearGroups.some(g => g.year === todayYear)) return todayYear
    return yearGroups[0].year
  }, [yearGroups, selectedYear, todayYear])

  const yearData = useMemo(
    () => yearGroups.find(g => g.year === effectiveYear) || null,
    [yearGroups, effectiveYear]
  )

  return (
    <div className="page-shell-wide">
      <PageHeader
        eyebrow="Reportes / Mensual"
        title="Performance histórica"
        action={
          <div className="flex items-center gap-2 flex-wrap">
            <AnalyzeButton
              screen="reports"
              params={{ year: effectiveYear }}
              subtitle={`Performance ${effectiveYear}`}
            />
            <ExportCsvButton resource="monthly" label="Exportar mensual" source="reports_header" variant="compact" />
            <BrokerSelector value={broker} onChange={setBroker} />
          </div>
        }
      />

      {error && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-sm bg-rendi-neg/10 border border-rendi-neg/20 text-rendi-neg text-sm">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      {loading && (
        <div className="p-10 text-center text-ink-3">
          <Loader2 size={20} className="animate-spin mx-auto mb-2" aria-hidden="true" />
          <p className="text-sm">Armando tu timeline…</p>
        </div>
      )}

      {!loading && !error && !hasAnyData && (
        <EmptyState
          icon={<FileText size={20} />}
          title="Todavía no hay reportes"
          description="El primer reporte se genera al cerrar tu primer mes con actividad. Si recién importaste tu CSV, esperá al cambio de mes — te avisamos cuando esté listo."
          action={
            <Link
              to="/config"
              className="inline-flex items-center gap-1.5 text-sm bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-4 py-2 rounded-sm transition-colors"
            >
              Importar mi historial
              <ArrowRight size={13} strokeWidth={1.75} />
            </Link>
          }
        />
      )}

      {!loading && !error && hasAnyData && (
        <>
          <PerformanceCalendar yearGroups={yearGroups} />

          {/* GATE Free: solo se muestra el último mes con actividad como teaser.
              Pro/Admin: tabla mensual completa con todos los años cargados. */}
          {plan.can('reportes.historicos') ? (
            <>
              <YearTabs
                years={yearGroups.map(g => g.year)}
                value={effectiveYear}
                onChange={(y) => { setSelectedYear(y); setExpandedKey(null) }}
              />
              {yearData && (
                <MonthlyTable
                  year={yearData.year}
                  months={yearData.months}
                  expandedKey={expandedKey}
                  onToggle={(key) => setExpandedKey(prev => prev === key ? null : key)}
                />
              )}
            </>
          ) : (
            <ReportsFreeTeaser yearGroups={yearGroups} expandedKey={expandedKey} setExpandedKey={setExpandedKey} />
          )}
        </>
      )}
    </div>
  )
}

// ─── Free teaser ─────────────────────────────────────────────────────────────
// Para usuarios Free: muestra solo el último mes con actividad como teaser
// completo, y debajo un placeholder bloqueado para los anteriores.

function ReportsFreeTeaser({ yearGroups }) {
  // Aplastamos todos los meses de todos los años y agarramos el más reciente
  // (que tenga is_relevant). Ese es el teaser visible.
  const { lastMonth, totalHidden } = useMemo(() => {
    const all = []
    for (const g of yearGroups) {
      for (const m of g.months) {
        if (m && m.is_relevant) all.push({ year: g.year, month: m })
      }
    }
    all.sort((a, b) => {
      if (a.year !== b.year) return b.year - a.year
      return monthNum(b.month.period_key) - monthNum(a.month.period_key)
    })
    return {
      lastMonth: all[0] || null,
      totalHidden: Math.max(0, all.length - 1),
    }
  }, [yearGroups])

  if (!lastMonth) return null

  return (
    <div className="space-y-3">
      {/* Teaser del último mes — expandido por default */}
      <div className="border border-line rounded bg-bg-1 overflow-hidden">
        <header className="flex items-center justify-between px-4 py-2.5 border-b border-line">
          <div className="flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-rendi-pos" aria-hidden="true" />
            <span className="text-[11px] font-mono uppercase tracking-label text-ink-0">Tu último mes</span>
          </div>
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">Vista previa Free</span>
        </header>
        <MonthCard month={lastMonth.month} defaultExpanded={true} />
      </div>

      {/* Placeholder de los meses históricos */}
      {totalHidden > 0 && (
        <LockedSection.Placeholder
          feature="reportes.historicos"
          title={`Tenés ${totalHidden} ${totalHidden === 1 ? 'mes' : 'meses'} más en tu historial`}
          description="Reportes históricos completos, comparativas mes a mes, descarga PDF y vista anual. Disponible en Rendi Pro."
          source="reports_historicos"
        />
      )}
    </div>
  )
}

// ─── Year tabs ───────────────────────────────────────────────────────────────

function YearTabs({ years, value, onChange }) {
  if (years.length <= 1) return null
  return (
    <div className="flex items-center gap-2 mb-3">
      <span className="text-[10px] font-mono uppercase tracking-label text-ink-3">Año</span>
      <div className="inline-flex bg-bg-2 border border-line rounded-sm p-0.5">
        {years.map(y => (
          <button
            key={y}
            onClick={() => onChange(y)}
            className={`px-3 py-1 text-xs font-mono tabular tracking-tight rounded-sm transition-colors ${
              value === y
                ? 'bg-bg-3 text-ink-0'
                : 'text-ink-2 hover:text-ink-0'
            }`}
          >
            {y}
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── Monthly table ───────────────────────────────────────────────────────────

function MonthlyTable({ year, months, expandedKey, onToggle }) {
  // Lista ordenada cronológicamente con todos los slots del año (1..12),
  // ya sean activos o "—".
  const rows = useMemo(() => {
    const byNum = new Map(months.map(m => [monthNum(m.period_key), m]))
    const list = []
    for (let i = 1; i <= 12; i++) {
      const m = byNum.get(i)
      list.push({ num: i, name: MONTH_NAMES[i - 1], month: m })
    }
    // Ocultar meses futuros que no existen (después del último relevante)
    const lastIdx = list.reduceRight((acc, r, idx) => acc === -1 && r.month ? idx : acc, -1)
    return list.slice(0, lastIdx === -1 ? 0 : lastIdx + 1)
  }, [months])

  if (rows.length === 0) return null

  return (
    <div className="border border-line rounded bg-bg-1 overflow-hidden">
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-line">
        <div className="flex items-center gap-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-rendi-pos" aria-hidden="true" />
          <span className="text-[11px] font-mono uppercase tracking-label text-ink-0">Tabla mensual</span>
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3 ml-1">/ {year}</span>
        </div>
        <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
          {months.length} {months.length === 1 ? 'mes' : 'meses'} con actividad
        </span>
      </header>

      <table className="w-full">
        <thead>
          <tr className="text-[10px] font-mono uppercase tracking-label text-ink-3 border-b border-line/60">
            <th className="text-left  px-4 py-2 font-medium">Mes</th>
            <th className="text-right px-3 py-2 font-medium">Rendimiento</th>
            <th className="text-right px-3 py-2 font-medium">P&amp;L USD</th>
            <th className="text-right px-3 py-2 font-medium">Trades</th>
            <th className="text-right px-3 py-2 font-medium">Win&nbsp;rate</th>
            <th className="text-right px-3 py-2 font-medium">vs S&amp;P</th>
            <th className="text-left  px-3 py-2 font-medium hidden lg:table-cell">Headline</th>
            <th className="px-2 py-2 w-[34px] font-medium" title="Analizar con IA"></th>
            <th className="px-3 py-2 w-[40px]"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ num, name, month }) => {
            const empty = !month || !month.is_relevant
            const isCurrent = month?.is_current
            const isExpanded = month && expandedKey === month.period_key
            const m = month?.metrics
            const status = month
              ? (isCurrent
                  ? 'en curso'
                  : 'cerrado')
              : 'sin datos'
            const pct = m?.delta_pct
            const usd = m?.delta_usd
            const toneRow = isExpanded
              ? 'bg-bg-2'
              : (pct != null && pct >= 0
                  ? 'hover:bg-rendi-pos/[0.04]'
                  : pct != null
                    ? 'hover:bg-rendi-neg/[0.04]'
                    : 'hover:bg-bg-2/40')
            return (
              <Fragment key={num}>
                <tr
                  onClick={() => month && onToggle(month.period_key)}
                  className={`border-b border-line/30 text-sm transition-colors ${
                    empty ? 'text-ink-3 cursor-default' : 'cursor-pointer'
                  } ${toneRow}`}
                >
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink-1 min-w-[36px]">{name}</span>
                      {isCurrent && (
                        <span className="text-[9px] font-mono uppercase tracking-caps text-rendi-pos border border-rendi-pos/30 bg-rendi-pos/10 px-1.5 py-0.5 rounded-sm">
                          En curso
                        </span>
                      )}
                      {!isCurrent && !empty && (
                        <span className="text-[9px] font-mono uppercase tracking-caps text-ink-3">
                          {status}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono tabular text-sm ${
                    pct == null ? 'text-ink-3' : (pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg')
                  }`}>
                    {fmtPct(pct)}
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono tabular text-xs ${
                    usd == null ? 'text-ink-3' : (usd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg')
                  }`}>
                    {fmtUsd(usd)}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular text-xs text-ink-1">
                    {m?.trades_count != null ? m.trades_count : '—'}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono tabular text-xs text-ink-1">
                    {m?.win_rate != null ? `${m.win_rate.toFixed(0)}%` : '—'}
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono tabular text-xs ${
                    m?.vs_sp500_pct == null ? 'text-ink-3' : (m.vs_sp500_pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg')
                  }`}>
                    {m?.vs_sp500_pct != null ? `${m.vs_sp500_pct >= 0 ? '+' : ''}${m.vs_sp500_pct.toFixed(1)}pp` : '—'}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-ink-2 truncate max-w-[260px] hidden lg:table-cell">
                    {month?.headline || ''}
                  </td>
                  <td className="px-2 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                    {month && !empty && (
                      <InlineAIButton
                        topic="monthly"
                        params={{
                          year: parseInt((month.period_key || '').slice(0, 4), 10),
                          month: parseInt((month.period_key || '').slice(5, 7), 10),
                        }}
                        subtitle={`Mes ${month.period_label}`}
                      />
                    )}
                  </td>
                  <td className="px-2 py-2.5 text-ink-3 text-right">
                    {month && (isExpanded
                      ? <ChevronUp size={14} strokeWidth={1.75} aria-hidden="true" />
                      : <ChevronDown size={14} strokeWidth={1.75} aria-hidden="true" />)}
                  </td>
                </tr>
                {isExpanded && (
                  <tr className="border-b border-line">
                    <td colSpan={9} className="bg-bg-0 p-4">
                      <MonthCard month={month} defaultExpanded={true} />
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
