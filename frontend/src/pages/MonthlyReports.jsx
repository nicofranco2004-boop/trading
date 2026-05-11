// MonthlyReports — la pantalla "fintech" del histórico mensual.
// ════════════════════════════════════════════════════════════════════════════
// Diseño separado en 2 jobs (audit interno mayo 2026):
//   • /reportes  → ESTA PANTALLA. Lectura, narrativa, drivers e insights.
//   • /mensual   → Cierre mensual administrativo (data entry).
//
// Funciona para todos los usuarios, incluso recién importados:
//   • Si el user cerró meses → los muestra con full data (source: 'manual')
//   • Si solo importó operations → derivamos pnl_realized desde ops
//     (source: 'derived'), con CTA "Cerrar este mes →" para completar
//
// Fase A: cards expandibles por año + cards compactas de mes.
// Fase B (próxima): modal de detalle con drivers + benchmarks + insights.
// Por ahora el modal muestra info básica.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  TrendingUp, TrendingDown, ArrowRight, ChevronDown, ChevronUp,
  X, Sparkles, Settings, AlertCircle,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import EmptyState from '../components/EmptyState'
import MiniSparkline from '../components/MiniSparkline'
import { usd, fmtUsd, pctSigned } from '../utils/format'
import useMonthlyData from '../hooks/useMonthlyData'

// ════════════════════════════════════════════════════════════════════════════
// Status config — bucket visual del mes
// ════════════════════════════════════════════════════════════════════════════
const STATUS = {
  excellent: { label: 'Excelente', badge: 'bg-rendi-pos/15 text-rendi-pos border-rendi-pos/30' },
  positive:  { label: 'Positivo',  badge: 'bg-rendi-pos/10 text-rendi-pos/80 border-rendi-pos/20' },
  neutral:   { label: 'Neutro',    badge: 'bg-bg-3 text-ink-2 border-line' },
  difficult: { label: 'Negativo',  badge: 'bg-rendi-neg/10 text-rendi-neg border-rendi-neg/30' },
}

const SOURCE_BADGE = {
  manual:  null,
  partial: { label: 'Sin cerrar', cls: 'bg-rendi-warn/10 text-rendi-warn border-rendi-warn/30' },
  derived: { label: 'Estimado',   cls: 'bg-bg-3 text-ink-2 border-line' },
}

function deltaColor(deltaUsd) {
  if (deltaUsd > 50) return 'text-rendi-pos'
  if (deltaUsd < -50) return 'text-rendi-neg'
  return 'text-ink-1'
}

// ════════════════════════════════════════════════════════════════════════════
// Componente principal
// ════════════════════════════════════════════════════════════════════════════
export default function MonthlyReports() {
  const { loading, error, years, hasAnyData } = useMonthlyData()
  // Año actual (más reciente) arranca expandido
  const [expandedYear, setExpandedYear] = useState(null)
  const [selectedMonth, setSelectedMonth] = useState(null)

  // Una vez cargados los años, expandimos el primero por default
  // (solo la primera vez — si el user los colapsa, respetamos)
  const effectiveExpanded = expandedYear ?? (years[0]?.year ?? null)

  if (loading) {
    return (
      <div className="page-shell">
        <PageHeader title="Reportes mensuales" subtitle="Cargando histórico…" />
        <div className="space-y-3" aria-busy="true" aria-live="polite">
          {[0, 1, 2].map(i => (
            <div key={i} className="bg-bg-1 border border-line rounded h-20 animate-pulse motion-reduce:animate-none" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="page-shell">
        <PageHeader title="Reportes mensuales" />
        <div className="flex items-start gap-2.5 px-3 py-2 rounded-sm border border-rendi-neg/25 bg-rendi-neg/[0.06] text-rendi-neg text-xs">
          <AlertCircle size={14} strokeWidth={1.75} className="flex-shrink-0 mt-0.5" />
          <span><b>Error cargando reportes.</b> {error}</span>
        </div>
      </div>
    )
  }

  if (!hasAnyData) {
    return (
      <div className="page-shell">
        <PageHeader title="Reportes mensuales" subtitle="Tu histórico mensual aparece acá una vez que hayas registrado operaciones o cerrado tu primer mes." />
        <EmptyState
          icon={<Settings size={20} />}
          title="Todavía no hay reportes"
          description="Importá tu historial desde Configuración o registrá tu primer mes desde Cierre mensual para empezar a ver el detalle de cada período."
          action={
            <div className="flex gap-2 justify-center">
              <Link to="/imports" className="inline-flex items-center gap-1.5 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white px-4 py-2 rounded-sm font-semibold transition">
                Importar historial
              </Link>
              <Link to="/mensual" className="inline-flex items-center gap-1.5 text-sm bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 px-4 py-2 rounded-sm transition">
                Cerrar primer mes
              </Link>
            </div>
          }
        />
      </div>
    )
  }

  // Hero: año más reciente
  const currentYear = years[0]
  const hasManualData = currentYear.manualCount > 0

  return (
    <div className="page-shell">
      <PageHeader
        title="Reportes mensuales"
        subtitle="Cómo se comportó tu portfolio mes a mes — performance, drivers e insights por período."
        action={
          <Link
            to="/mensual"
            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-sm bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 transition"
          >
            <Settings size={12} strokeWidth={1.75} aria-hidden="true" />
            Cerrar mes en curso
          </Link>
        }
      />

      {/* ─── HERO YTD del año actual ────────────────────────────────── */}
      {hasManualData && (
        <div className="mb-8">
          <StatCard
            tone="hero"
            label={`Rendimiento ${currentYear.year}`}
            value={fmtUsd(currentYear.endUsd)}
            sub={
              <span className="inline-flex items-center gap-3 flex-wrap">
                <span className="text-ink-2">YTD</span>
                <span className={`inline-flex items-center gap-1 font-semibold ${currentYear.ytdUsd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                  {currentYear.ytdUsd >= 0 ? <TrendingUp size={14} strokeWidth={1.5} aria-hidden="true" /> : <TrendingDown size={14} strokeWidth={1.5} aria-hidden="true" />}
                  {currentYear.ytdUsd >= 0 ? '+' : '−'}USD {usd(Math.abs(currentYear.ytdUsd))}
                </span>
                <span className={`tabular ${currentYear.ytdUsd >= 0 ? 'text-rendi-pos/80' : 'text-rendi-neg/80'}`}>
                  ({pctSigned(currentYear.ytdPct / 100)})
                </span>
              </span>
            }
            hint={(() => {
              const startStr = fmtUsd(currentYear.startUsd).replace('+', '')
              const endStr = fmtUsd(currentYear.endUsd).replace('+', '')
              const liveTag = currentYear.endSource === 'live' ? ' · live' : ''
              const flowsTag = currentYear.flowsYear !== 0
                ? ` · ${currentYear.flowsYear >= 0 ? 'aportes netos' : 'retiros netos'} ${fmtUsd(Math.abs(currentYear.flowsYear)).replace('+', '')}`
                : ''
              const bestTag = currentYear.bestMonth
                ? ` · mejor: ${currentYear.bestMonth.name} (${pctSigned(currentYear.bestMonth.pct / 100)})`
                : ''
              return `De ${startStr} a ${endStr}${liveTag}${flowsTag}${bestTag}`
            })()}
          />
        </div>
      )}

      {/* Aviso si hay meses derivados sin cerrar */}
      {currentYear.derivedCount > 0 && (
        <div className="mb-6 flex items-start gap-2.5 px-3 py-2 rounded-sm border border-rendi-warn/25 bg-rendi-warn/[0.06] text-rendi-warn text-xs">
          <AlertCircle size={14} strokeWidth={1.75} className="flex-shrink-0 mt-0.5" />
          <span>
            <b>{currentYear.derivedCount} {currentYear.derivedCount === 1 ? 'mes está' : 'meses están'} estimados</b> a partir de tus operaciones.
            Para ver delta real, capital invertido y rendimiento porcentual,
            <Link to="/mensual" className="underline ml-1">cerrá el mes desde aquí</Link>.
          </span>
        </div>
      )}

      {/* ─── LISTA DE AÑOS ──────────────────────────────────────────── */}
      <div className="space-y-4">
        {years.map(yr => (
          <YearCard
            key={yr.year}
            year={yr}
            isExpanded={effectiveExpanded === yr.year}
            onToggle={() => setExpandedYear(effectiveExpanded === yr.year ? -1 : yr.year)}
            onMonthClick={setSelectedMonth}
          />
        ))}
      </div>

      {/* ─── MODAL DETALLE MENSUAL (Fase B: drivers + benchmarks) ──── */}
      {selectedMonth && (
        <MonthDetailModal month={selectedMonth} onClose={() => setSelectedMonth(null)} />
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// YearCard
// ════════════════════════════════════════════════════════════════════════════
function YearCard({ year, isExpanded, onToggle, onMonthClick }) {
  const hasYtd = year.manualCount > 0

  return (
    <section className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-4 px-5 py-4 hover:bg-slate-50 dark:hover:bg-bg-2/50 transition-colors text-left"
        aria-expanded={isExpanded}
      >
        <div className="flex items-baseline gap-4 min-w-0 flex-wrap">
          <span className="font-display text-3xl text-ink-0 tracking-tight">{year.year}</span>
          {hasYtd ? (
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 min-w-0">
              <span className={`text-base font-semibold tabular ${year.ytdUsd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                {pctSigned(year.ytdPct / 100)}
              </span>
              <span className={`text-sm tabular ${year.ytdUsd >= 0 ? 'text-rendi-pos/70' : 'text-rendi-neg/70'}`}>
                {year.ytdUsd >= 0 ? '+' : '−'}USD {usd(Math.abs(year.ytdUsd))}
              </span>
              <span className="text-xs text-ink-2 font-mono">
                {year.months.length} {year.months.length === 1 ? 'mes' : 'meses'}
                {year.bestMonth && ` · mejor: ${year.bestMonth.name}`}
              </span>
            </div>
          ) : (
            <span className="text-xs text-ink-2 font-mono">
              {year.months.length} {year.months.length === 1 ? 'mes' : 'meses'} sin cerrar
            </span>
          )}
        </div>
        <div className="flex-shrink-0 text-ink-3">
          {isExpanded ? <ChevronUp size={16} strokeWidth={1.75} aria-hidden="true" /> : <ChevronDown size={16} strokeWidth={1.75} aria-hidden="true" />}
        </div>
      </button>

      {isExpanded && (
        <div className="border-t border-slate-200 dark:border-line p-4 sm:p-5 bg-slate-50/40 dark:bg-bg-2/30">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {year.months.map(m => (
              <MonthCard key={m.period} month={m} onClick={() => onMonthClick(m)} />
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// MonthCard — vista compacta de cada mes
// ════════════════════════════════════════════════════════════════════════════
function MonthCard({ month, onClick }) {
  const status = STATUS[month.status] || STATUS.neutral
  const sourceBadge = SOURCE_BADGE[month.source]
  const isPositive = month.deltaUsd >= 0
  const showPct = month.source !== 'derived'  // derived no tiene baseline
  const hasSparkline = Array.isArray(month.sparkline) && month.sparkline.length >= 2

  return (
    <button
      onClick={onClick}
      className="text-left bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded p-4 hover:border-rendi-accent/40 dark:hover:border-rendi-accent/40 transition-colors group flex flex-col"
      aria-label={`Ver reporte de ${month.name} ${month.year}`}
    >
      <div className="flex items-center justify-between mb-2 gap-2">
        <span className="label-mono inline-flex items-center gap-1.5">
          {month.name}
          {month.isLive && (
            <span
              className="inline-flex items-center gap-1 text-[8px] font-mono uppercase tracking-[0.12em] px-1 py-0.5 rounded-sm bg-rendi-accent/15 text-rendi-accent border border-rendi-accent/30"
              title="El valor del mes refleja el último snapshot del portfolio (post-cierre)"
            >
              <span className="w-1 h-1 rounded-full bg-rendi-accent animate-pulse motion-reduce:animate-none" />
              Live
            </span>
          )}
        </span>
        {sourceBadge ? (
          <span
            className={`text-[9px] font-mono uppercase tracking-[0.12em] px-1.5 py-0.5 rounded-sm border ${sourceBadge.cls}`}
            title={month.source === 'derived' ? 'Mes derivado de tus operaciones — falta cerrar' : 'Mes sin cerrar formalmente'}
          >
            {sourceBadge.label}
          </span>
        ) : (
          <span className={`text-[9px] font-mono uppercase tracking-[0.12em] px-1.5 py-0.5 rounded-sm border ${status.badge}`}>
            {status.label}
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-2 mb-1">
        <span className={`text-xl font-medium num tabular tracking-tight ${deltaColor(month.deltaUsd)}`}>
          {isPositive ? '+' : '−'}USD {usd(Math.abs(month.deltaUsd))}
        </span>
      </div>
      {showPct ? (
        <div className={`text-xs font-mono ${isPositive ? 'text-rendi-pos/80' : month.deltaUsd < 0 ? 'text-rendi-neg/80' : 'text-ink-3'}`}>
          {pctSigned(month.deltaPct / 100)}
        </div>
      ) : (
        <div className="text-xs font-mono text-ink-3">
          P&amp;L realizado · sin baseline
        </div>
      )}

      {/* Sparkline del mes (opcional — depende de tener snapshots diarios) */}
      {hasSparkline && (
        <div className="mt-3 -mx-1 h-8" title={`Evolución diaria · ${month.sparkline.length} puntos`}>
          <MiniSparkline data={month.sparkline} positive={isPositive} />
        </div>
      )}

      <div className={`${hasSparkline ? 'mt-2' : 'mt-3'} pt-3 border-t border-slate-100 dark:border-line/50 flex items-center justify-between text-[10px] font-mono text-ink-3`}>
        <span>
          {month.source === 'manual'
            ? `${fmtUsd(month.startUsd).replace('+', '')} → ${fmtUsd(month.endUsd).replace('+', '')}`
            : month.source === 'derived'
            ? 'Sin cerrar'
            : 'Datos parciales'}
        </span>
        <ArrowRight size={11} strokeWidth={1.75} className="text-ink-3 group-hover:text-rendi-accent transition-colors" aria-hidden="true" />
      </div>
    </button>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// MonthDetailModal (Fase A: solo el resumen base; drivers/benchmarks/chart
// llegan en Fase B cuando tengamos los cálculos por mes)
// ════════════════════════════════════════════════════════════════════════════
function MonthDetailModal({ month, onClose }) {
  const isPositive = month.deltaUsd >= 0
  const isManual = month.source === 'manual'

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded-t-2xl sm:rounded w-full max-w-2xl shadow-2xl max-h-[95vh] sm:max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-slate-200 dark:border-line flex-shrink-0">
          <div className="min-w-0">
            <p className="eyebrow mb-1">Reporte mensual</p>
            <h2 className="text-xl font-semibold text-ink-0">{month.name} {month.year}</h2>
          </div>
          <button onClick={onClose} className="text-ink-3 hover:text-ink-0 -mt-1 -mr-1 p-1" aria-label="Cerrar reporte">
            <X size={18} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>

        <div className="overflow-y-auto flex-1 p-5 space-y-6">

          {/* Hero del mes */}
          <div className="flex items-start gap-4">
            <div className={`flex-shrink-0 w-10 h-10 rounded-sm flex items-center justify-center ${
              isPositive ? 'bg-rendi-pos/15 text-rendi-pos' : 'bg-rendi-neg/15 text-rendi-neg'
            }`}>
              {isPositive ? <TrendingUp size={20} strokeWidth={1.75} aria-hidden="true" /> : <TrendingDown size={20} strokeWidth={1.75} aria-hidden="true" />}
            </div>
            <div className="flex-1 min-w-0">
              <p className={`text-2xl font-medium num tabular tracking-tight ${deltaColor(month.deltaUsd)}`}>
                {isPositive ? '+' : '−'}USD {usd(Math.abs(month.deltaUsd))}
                {isManual && (
                  <span className={`ml-3 text-base ${isPositive ? 'text-rendi-pos/80' : 'text-rendi-neg/80'}`}>
                    ({pctSigned(month.deltaPct / 100)})
                  </span>
                )}
              </p>
              {isManual ? (
                <p className="text-xs text-ink-2 mt-1 font-mono">
                  {fmtUsd(month.startUsd).replace('+', '')} → {fmtUsd(month.endUsd).replace('+', '')} · aportes netos {fmtUsd(month.deposits - month.withdrawals)}
                </p>
              ) : (
                <p className="text-xs text-ink-2 mt-1 font-mono">
                  P&amp;L realizado a partir de tus operaciones
                </p>
              )}
            </div>
          </div>

          {/* Métricas básicas */}
          <section>
            <p className="eyebrow mb-3">Resultado del mes</p>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Metric label="Patrimonio inicial" value={isManual ? fmtUsd(month.startUsd).replace('+', '') : '—'} />
              <Metric label="Patrimonio final"   value={isManual ? fmtUsd(month.endUsd).replace('+', '') : '—'} />
              <Metric label="P&L realizado"       value={fmtUsd(month.pnlRealized)} positive={month.pnlRealized >= 0} />
              <Metric label="P&L no realizado"    value={isManual ? fmtUsd(month.pnlUnrealized) : '—'} positive={month.pnlUnrealized >= 0} />
              <Metric label="Depósitos"           value={fmtUsd(month.deposits).replace('+', '')} />
              <Metric label="Retiros"             value={fmtUsd(month.withdrawals).replace('+', '')} />
            </div>
          </section>

          {/* Si es derived: CTA para cerrar el mes */}
          {!isManual && (
            <div className="px-4 py-3 rounded-sm bg-rendi-warn/[0.06] border border-rendi-warn/25">
              <div className="flex items-start gap-2.5">
                <AlertCircle size={14} strokeWidth={1.75} className="flex-shrink-0 mt-0.5 text-rendi-warn" aria-hidden="true" />
                <div className="flex-1 text-xs text-ink-1">
                  <p className="font-medium mb-1">Este mes está estimado.</p>
                  <p className="text-ink-2">Para ver delta real, capital invertido y rendimiento porcentual, cerrá el mes desde Cierre mensual.</p>
                </div>
                <Link
                  to="/mensual"
                  className="flex-shrink-0 inline-flex items-center gap-1 text-xs text-rendi-accent hover:underline"
                  onClick={onClose}
                >
                  Cerrar mes <ArrowRight size={11} strokeWidth={1.75} aria-hidden="true" />
                </Link>
              </div>
            </div>
          )}

          {/* Placeholder Fase B */}
          <section className="opacity-60">
            <div className="flex items-center gap-2 mb-3">
              <p className="eyebrow">Drivers y benchmarks</p>
              <span className="text-[9px] font-mono uppercase tracking-[0.12em] px-1.5 py-0.5 rounded-sm border bg-bg-3 text-ink-2 border-line">
                Próximamente
              </span>
            </div>
            <p className="text-xs text-ink-2 leading-relaxed">
              En la próxima fase agregamos: top contribuyentes, peores posiciones, comparación
              vs S&amp;P 500 / inflación, y 2-3 insights data-driven específicos del mes.
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value, positive }) {
  const color = positive == null ? 'text-ink-1' : positive ? 'text-rendi-pos' : 'text-rendi-neg'
  return (
    <div className="bg-slate-50/40 dark:bg-bg-2/40 border border-slate-200 dark:border-line rounded p-3">
      <p className="label-mono mb-1">{label}</p>
      <p className={`text-sm font-semibold tabular ${color}`}>{value}</p>
    </div>
  )
}
