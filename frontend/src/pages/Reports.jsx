// Reports — timeline operativa de Rendi (V3: tabs Día/Semana/Mes/Año).
// ════════════════════════════════════════════════════════════════════════════
// Estructura:
//   1. Header compacto (eyebrow + título + broker selector)
//   2. PerformanceCalendar — KPI strip + heatmap anual de meses
//   3. PeriodTabs: Día / Semana / Mes / Año
//   4. Lista de períodos: en curso arriba + históricos abajo, cards expandibles
//
// Decisión: replace MonthlyTable+desglose-semanal por tabs limpias estilo Braja.
// Cada tab fetcha N períodos hacia atrás y los renderiza como cards consistentes.

import { useState, useMemo, useEffect, Fragment } from 'react'
import { Link } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import { Loader2, FileText, AlertTriangle, ChevronDown, ChevronUp, ArrowRight } from 'lucide-react'
import useReportsTimeline from '../hooks/useReportsTimeline'
import BrokerSelector from '../components/reports/BrokerSelector'
import MonthCard from '../components/reports/MonthCard'
import PerformanceCalendar from '../components/reports/PerformanceCalendar'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import LockedSection from '../components/plan/LockedSection'
import ExportCsvButton from '../components/plan/ExportCsvButton'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { api } from '../utils/api'

// ─── Helpers de fecha / keys ─────────────────────────────────────────────────

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function isoWeekKey(d = new Date()) {
  // ISO week (lunes a domingo). Mismo cálculo que Python date.isocalendar()
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  const dayNum = date.getUTCDay() || 7
  date.setUTCDate(date.getUTCDate() + 4 - dayNum)
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1))
  const weekNo = Math.ceil((((date - yearStart) / 86400000) + 1) / 7)
  return `${date.getUTCFullYear()}-W${String(weekNo).padStart(2, '0')}`
}

function monthKey(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function yearKey(d = new Date()) {
  return String(d.getFullYear())
}

function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

function addWeeks(weekKey, n) {
  // weekKey: "YYYY-Wnn" → restamos n*7 días a un día representativo (lunes)
  const [y, w] = weekKey.split('-W').map(Number)
  // ISO week 1 = semana del primer jueves del año
  const jan4 = new Date(Date.UTC(y, 0, 4))
  const monday = new Date(jan4)
  monday.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() + 6) % 7))
  monday.setUTCDate(monday.getUTCDate() + (w - 1 + n) * 7)
  return isoWeekKey(monday)
}

function addMonths(monthK, n) {
  const [y, m] = monthK.split('-').map(Number)
  const total = y * 12 + (m - 1) + n
  const ny = Math.floor(total / 12)
  const nm = (total % 12) + 1
  return `${ny}-${String(nm).padStart(2, '0')}`
}

// ─── Hook: data por tab ──────────────────────────────────────────────────────
//
// Devuelve la lista de períodos del tab activo, con el `current` primero y
// los históricos abajo. Estrategia por tab:
//   - month: usa useReportsTimeline (que ya devuelve 12 meses con metrics+narrative)
//   - week:  aplana children de los meses del timeline (semanas embedded)
//   - day:   fetches puntuales a /api/reports/period/day/{key} (últimos 7 días)
//   - year:  fetches puntuales a /api/reports/period/year/{key} (años visibles)

function usePeriodItems(tab, broker, timelineData) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    // Reset items y error al cambiar tab/broker — evita ver data stale
    // mientras carga la nueva. (Mes mantiene su lista hasta resetear con
    // nueva data porque viene sync del hook timeline).
    if (tab !== 'month') {
      setItems([])
    }
    setError(null)

    async function load() {
      if (tab === 'month') {
        const all = []
        for (const g of timelineData.yearGroups || []) {
          for (const m of g.months) all.push(m)
        }
        if (!cancelled) setItems(all)
        return
      }

      let endpoint = null
      if (tab === 'week')      endpoint = `/reports/period/week/${isoWeekKey()}`
      else if (tab === 'day')  endpoint = `/reports/period/day/${todayIso()}`
      else if (tab === 'year') endpoint = `/reports/period/year/${new Date().getFullYear()}`
      if (!endpoint) return

      setLoading(true)
      try {
        const result = await api.get(
          `${endpoint}?broker=${encodeURIComponent(broker)}`,
          { signal: controller.signal },
        )
        if (cancelled) return
        setItems(result ? [result] : [])
      } catch (ex) {
        if (cancelled || ex.name === 'AbortError') return
        // Distinguir "sin data" (404/empty) de "error de red".
        // Mensaje genérico — el user puede retry.
        setError(ex?.message || 'No pudimos cargar el período. Reintentá en un momento.')
        setItems([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true; controller.abort() }
  }, [tab, broker, timelineData.yearGroups])

  return { items, loading, error }
}

// ─── Reports root ────────────────────────────────────────────────────────────

export default function Reports() {
  const [broker, setBroker] = useState('global')
  const timelineData = useReportsTimeline(broker, 12)
  const [tab, setTab] = useState('month')
  const [expandedKey, setExpandedKey] = useState(null)
  const plan = usePlanFeatures()

  const { items, loading: loadingItems, error: itemsError } = usePeriodItems(tab, broker, timelineData)

  // Reset expanded key cuando cambia el tab
  useEffect(() => { setExpandedKey(null) }, [tab])

  return (
    <div className="page-shell-wide">
      <PageHeader
        eyebrow="Reportes / Performance"
        title="Performance histórica"
        action={
          <div className="flex items-center gap-2 flex-wrap">
            <AnalyzeButton
              screen="reports"
              params={{ tab }}
              subtitle={`Performance · ${LABELS[tab]}`}
            />
            <ExportCsvButton resource="monthly" label="Exportar mensual" source="reports_header" variant="compact" />
            <BrokerSelector value={broker} onChange={setBroker} />
          </div>
        }
      />

      {timelineData.error && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-sm bg-rendi-neg/10 border border-rendi-neg/20 text-rendi-neg text-sm">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span>{timelineData.error}</span>
        </div>
      )}

      {timelineData.loading && (
        <div className="p-10 text-center text-ink-3">
          <Loader2 size={20} className="animate-spin mx-auto mb-2" aria-hidden="true" />
          <p className="text-sm">Armando tu timeline…</p>
        </div>
      )}

      {!timelineData.loading && !timelineData.error && !timelineData.hasAnyData && (
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

      {!timelineData.loading && !timelineData.error && timelineData.hasAnyData && (
        <>
          <PerformanceCalendar yearGroups={timelineData.yearGroups} />

          {plan.can('reportes.historicos') ? (
            <>
              <PeriodTabs value={tab} onChange={setTab} />
              {itemsError && (
                <div className="mb-3 flex items-start gap-2 px-3 py-2 rounded-sm bg-rendi-neg/10 border border-rendi-neg/20 text-rendi-neg text-xs">
                  <AlertTriangle size={13} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
                  <span>{itemsError}</span>
                </div>
              )}
              {tab === 'day' || tab === 'week' || tab === 'year' ? (
                <CurrentPeriodView
                  period={items[0]}
                  loading={loadingItems}
                  tab={tab}
                  broker={broker}
                />
              ) : (
                <PeriodList
                  items={items}
                  loading={loadingItems}
                  expandedKey={expandedKey}
                  onToggle={(key) => setExpandedKey(prev => prev === key ? null : key)}
                />
              )}
            </>
          ) : (
            <ReportsFreeTeaser yearGroups={timelineData.yearGroups} />
          )}
        </>
      )}
    </div>
  )
}

// ─── Free teaser ─────────────────────────────────────────────────────────────

function ReportsFreeTeaser({ yearGroups }) {
  const { lastMonth, totalHidden } = useMemo(() => {
    const all = []
    for (const g of yearGroups) {
      for (const m of g.months) {
        if (m && m.is_relevant) all.push({ year: g.year, month: m })
      }
    }
    all.sort((a, b) => (b.month.period_start || '').localeCompare(a.month.period_start || ''))
    return { lastMonth: all[0] || null, totalHidden: Math.max(0, all.length - 1) }
  }, [yearGroups])

  if (!lastMonth) return null

  return (
    <div className="space-y-3">
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

// ─── Period tabs ─────────────────────────────────────────────────────────────

const LABELS = {
  day:   'Día',
  week:  'Semana',
  month: 'Mes',
  year:  'Año',
}

function PeriodTabs({ value, onChange }) {
  const tabs = ['day', 'week', 'month', 'year']
  return (
    <div className="flex items-center gap-2 mb-4">
      <span className="text-[10px] font-mono uppercase tracking-label text-ink-3 mr-1">Período</span>
      <div className="inline-flex bg-bg-2 border border-line rounded-sm p-0.5">
        {tabs.map(t => (
          <button
            key={t}
            onClick={() => onChange(t)}
            className={`px-3.5 py-1.5 text-xs font-mono uppercase tracking-label rounded-sm transition-colors ${
              value === t ? 'bg-bg-3 text-ink-0' : 'text-ink-2 hover:text-ink-0'
            }`}
          >
            {LABELS[t]}
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── Lista de períodos ───────────────────────────────────────────────────────

function PeriodList({ items, loading, expandedKey, onToggle }) {
  if (loading && items.length === 0) {
    return (
      <div className="p-10 text-center text-ink-3">
        <Loader2 size={18} className="animate-spin mx-auto mb-2" aria-hidden="true" />
        <p className="text-sm">Cargando…</p>
      </div>
    )
  }

  if (!items || items.length === 0) {
    return (
      <div className="p-10 text-center text-ink-3 border border-line/40 rounded bg-bg-1/40">
        <p className="text-sm">No hay datos para este período todavía.</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {items.map(period => (
        <PeriodRow
          key={period.period_key}
          period={period}
          expanded={expandedKey === period.period_key}
          onToggle={() => onToggle(period.period_key)}
        />
      ))}
    </div>
  )
}

function PeriodRow({ period, expanded, onToggle }) {
  const empty = !period.is_relevant && !period.is_current
  const pct = period?.metrics?.delta_pct
  const usd = period?.metrics?.delta_usd
  const pctColor = pct == null
    ? 'text-ink-3'
    : pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'

  return (
    <div className={`border rounded bg-bg-1/60 overflow-hidden transition-colors ${
      expanded ? 'border-data-violet/30' : 'border-line hover:border-line-3'
    }`}>
      <button
        onClick={onToggle}
        className="w-full px-4 py-3 flex items-center justify-between gap-4 text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="font-medium text-ink-0 text-sm min-w-[110px]">
            {period.period_label}
          </span>
          {period.is_current && (
            <span className="text-[9px] font-mono uppercase tracking-caps text-rendi-pos border border-rendi-pos/30 bg-rendi-pos/10 px-1.5 py-0.5 rounded-sm">
              En curso
            </span>
          )}
          {!empty && period.headline && (
            <span className="text-xs text-ink-3 truncate hidden md:inline">
              {period.headline}
            </span>
          )}
          {empty && (
            <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
              Sin actividad
            </span>
          )}
        </div>

        <div className="flex items-center gap-4 flex-shrink-0">
          {pct != null && (
            <span className={`text-sm font-mono font-semibold tabular ${pctColor}`}>
              {pct >= 0 ? '+' : ''}{pct.toFixed(pct >= 10 || pct <= -10 ? 1 : 2)}%
            </span>
          )}
          {usd != null && (
            <span className={`text-xs font-mono tabular ${pctColor} hidden sm:inline`}>
              {usd >= 0 ? '+' : '−'}US$ {Math.abs(usd).toLocaleString('es-AR', { maximumFractionDigits: 0 })}
            </span>
          )}
          {expanded
            ? <ChevronUp size={14} strokeWidth={1.75} className="text-ink-3" />
            : <ChevronDown size={14} strokeWidth={1.75} className="text-ink-3" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-line/40 bg-bg-0">
          <MonthCard period={period} defaultExpanded={true} />
        </div>
      )}
    </div>
  )
}

// ─── CurrentPeriodView — vista del período en curso con KPIs ricos ──────────
//
// Usado en tabs Día y Mes. Reemplaza la lista clickeable por un solo card
// expandido con un KPI strip arriba y el MonthCard completo abajo.

function CurrentPeriodView({ period, loading, tab, broker = 'global' }) {
  if (loading) {
    return (
      <div className="p-10 text-center text-ink-3">
        <Loader2 size={18} className="animate-spin mx-auto mb-2" aria-hidden="true" />
        <p className="text-sm">Armando el período…</p>
      </div>
    )
  }
  if (!period) {
    return (
      <div className="p-10 text-center text-ink-3 border border-line/40 rounded bg-bg-1/40">
        <p className="text-sm">No hay datos para el período en curso.</p>
      </div>
    )
  }

  const m = period.metrics || {}
  const snap = period.portfolio_snapshot || {}
  const pct = m.delta_pct
  const usd = m.delta_usd
  const isPos = (pct ?? 0) >= 0
  const colorClass = isPos ? 'text-rendi-pos' : 'text-rendi-neg'

  // Detección de "período flat" — sin movimientos, sin trades.
  // En ese caso no mostramos P&L del período (sería engañoso "+US$ 0"),
  // sino que pivot a KPIs estáticos del portfolio actual.
  const isFlat = (
    (m.delta_usd === 0 || m.delta_usd == null) &&
    (m.trades_count === 0 || m.trades_count == null) &&
    !m.deposits && !m.withdrawals
  )

  // KPIs del strip — incluye métricas estáticas del portfolio (cap actual,
  // aportado, # posiciones, # brokers) además del P&L del período.
  const kpis = []

  // Capital actual: snapshot total si lo tenemos, sino end_value del período
  const capitalNow = snap.latest_value != null ? snap.latest_value : m.end_value
  kpis.push({
    label: 'Capital actual',
    value: capitalNow != null ? `US$ ${fmtNum(capitalNow)}` : '—',
    sub: snap.latest_date ? `Al ${formatDateShort(snap.latest_date)}` : null,
  })

  // P&L del período (solo si NO es flat — sino confunde con "+US$ 0")
  if (!isFlat) {
    const periodLabel = tab === 'day' ? 'del día'
    : tab === 'week' ? 'de la semana'
    : tab === 'year' ? 'del año'
    : 'del mes'
    kpis.push({
      label: `P&L ${periodLabel}`,
      value: usd != null ? `${usd >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(usd))}` : '—',
      sub: pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : null,
      tone: isPos ? 'pos' : 'neg',
    })
  }

  if (m.realized_pnl != null && (m.realized_pnl !== 0 || m.trades_count > 0)) {
    kpis.push({
      label: 'P&L realizado',
      value: `${m.realized_pnl >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(m.realized_pnl))}`,
      sub: m.trades_count != null ? `${m.trades_count} op${m.trades_count !== 1 ? 's' : ''} cerrada${m.trades_count !== 1 ? 's' : ''}` : 'operaciones cerradas',
      tone: m.realized_pnl >= 0 ? 'pos' : 'neg',
    })
  }

  if (!isFlat && m.unrealized_pnl != null && m.unrealized_pnl !== 0) {
    kpis.push({
      label: 'P&L no realizado',
      value: `${m.unrealized_pnl >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(m.unrealized_pnl))}`,
      sub: 'mark-to-market',
      tone: m.unrealized_pnl >= 0 ? 'pos' : 'neg',
    })
  }

  // Win rate cuando hay trades
  if (m.trades_count > 0 && m.win_rate != null) {
    kpis.push({
      label: 'Win rate',
      value: `${m.win_rate.toFixed(0)}%`,
      sub: `${m.win_count || 0} ganadas · ${m.loss_count || 0} perdidas`,
      tone: m.win_rate >= 50 ? 'pos' : 'neg',
    })
  }

  // Capital aportado neto (cumulative) — solo en tab Año.
  // El sub-label aclara que el % es sobre lo aportado (NO TWRR), para evitar
  // confusión con el delta_pct del período que sí neutraliza flujos.
  if (tab === 'year' && snap.cum_deposited != null && snap.cum_deposited > 0) {
    kpis.push({
      label: 'Capital aportado',
      value: `US$ ${fmtNum(snap.cum_deposited)}`,
      sub: capitalNow != null
        ? `Retorno sobre aportes: ${capitalNow > snap.cum_deposited ? '+' : '−'}${(((capitalNow - snap.cum_deposited) / snap.cum_deposited) * 100).toFixed(1)}%`
        : 'depósitos netos',
      tone: capitalNow != null
        ? (capitalNow >= snap.cum_deposited ? 'pos' : 'neg')
        : undefined,
    })
  }

  // # posiciones abiertas
  if (snap.positions_count != null && snap.positions_count > 0) {
    kpis.push({
      label: 'Posiciones',
      value: String(snap.positions_count),
      sub: snap.brokers_count > 0 ? `en ${snap.brokers_count} broker${snap.brokers_count !== 1 ? 's' : ''}` : null,
    })
  }

  // Variación vs último cierre — USD arriba (más relevante para retail),
  // % + fecha del snapshot anterior en el subtítulo.
  if (snap.delta_1d) {
    const d = snap.delta_1d
    const pctStr = `${d.pct >= 0 ? '+' : ''}${d.pct.toFixed(2)}%`
    const fechaStr = d.prev_date ? ` · vs ${formatDateShort(d.prev_date)}` : ''
    kpis.push({
      label: 'Δ último cierre',
      value: `${d.usd >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(d.usd))}`,
      sub: pctStr + fechaStr,
      tone: d.pct >= 0 ? 'pos' : 'neg',
    })
  }

  // Variación 7 días — USD arriba, % en sub
  if (snap.delta_7d) {
    const d = snap.delta_7d
    kpis.push({
      label: 'Δ 7 días',
      value: `${d.usd >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(d.usd))}`,
      sub: `${d.pct >= 0 ? '+' : ''}${d.pct.toFixed(2)}%`,
      tone: d.pct >= 0 ? 'pos' : 'neg',
    })
  }

  // Variación 30 días — USD arriba, % en sub
  if (snap.delta_30d) {
    const d = snap.delta_30d
    kpis.push({
      label: 'Δ 30 días',
      value: `${d.usd >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(d.usd))}`,
      sub: `${d.pct >= 0 ? '+' : ''}${d.pct.toFixed(2)}%`,
      tone: d.pct >= 0 ? 'pos' : 'neg',
    })
  }

  // YTD — rendimiento del año en curso (solo en tab Año)
  if (tab === 'year' && snap.ytd) {
    const MESES_FULL = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic']
    const partial = snap.ytd.is_partial_year && snap.ytd.since_month
    const label = partial
      ? `Desde ${MESES_FULL[snap.ytd.since_month - 1]} ${snap.ytd.since_year}`
      : `YTD ${snap.ytd.since_year}`
    kpis.push({
      label,
      value: `${snap.ytd.pct >= 0 ? '+' : ''}${snap.ytd.pct.toFixed(2)}%`,
      sub: `${snap.ytd.usd >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(snap.ytd.usd))}`,
      tone: snap.ytd.pct >= 0 ? 'pos' : 'neg',
    })
  }

  // Última operación cerrada
  if (snap.last_op && snap.last_op.pnl_usd != null) {
    const op = snap.last_op
    kpis.push({
      label: 'Última op cerrada',
      value: `${op.asset} ${op.pnl_usd >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(op.pnl_usd))}`,
      sub: formatDateShort(op.date),
      tone: op.pnl_usd >= 0 ? 'pos' : 'neg',
    })
  }

  // Top holding
  if (snap.top_holdings && snap.top_holdings.length > 0) {
    const t = snap.top_holdings[0]
    kpis.push({
      label: 'Top holding',
      value: t.asset,
      sub: t.broker || null,
    })
  }

  // vs S&P 500 (solo si aplica — mes tiene benchmark)
  if (m.vs_sp500_pct != null) {
    const vs = m.vs_sp500_pct
    kpis.push({
      label: 'vs S&P 500',
      value: `${vs >= 0 ? '+' : ''}${vs.toFixed(1)}pp`,
      sub: vs >= 0 ? 'por encima' : 'por debajo',
      tone: vs >= 0 ? 'pos' : 'neg',
    })
  }

  // Flujos netos
  if ((m.deposits || m.withdrawals) && (m.deposits + m.withdrawals) > 0) {
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    kpis.push({
      label: 'Flujos netos',
      value: `${net >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(net))}`,
      sub: `Aportes US$ ${fmtNum(m.deposits || 0)}`,
    })
  }

  return (
    <div className="space-y-4">
      {/* Header del período */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3 flex-wrap">
          <h3 className="text-lg font-semibold text-ink-0 tracking-tight">{period.period_label}</h3>
          {period.is_current && (
            <span className="text-[9px] font-mono uppercase tracking-caps text-rendi-pos border border-rendi-pos/30 bg-rendi-pos/10 px-1.5 py-0.5 rounded-sm">
              En curso
            </span>
          )}
          {isFlat && (
            <span className="text-[9px] font-mono uppercase tracking-caps text-ink-3 border border-line/60 px-1.5 py-0.5 rounded-sm">
              Sin movimientos
            </span>
          )}
        </div>
        {!isFlat && (
          <div className="flex items-baseline gap-2">
            <span className={`text-2xl font-mono font-semibold tabular ${colorClass}`}>
              {pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : '—'}
            </span>
            <span className={`text-sm font-mono tabular ${colorClass}`}>
              {usd != null ? `${usd >= 0 ? '+' : '−'}US$ ${fmtNum(Math.abs(usd))}` : ''}
            </span>
          </div>
        )}
      </div>

      {isFlat && (
        <div className="border border-line/40 bg-bg-1/40 rounded px-4 py-3 text-xs text-ink-2 leading-relaxed">
          {(m.trades_count === 0 || m.trades_count == null)
            ? `Sin operaciones cerradas en ${tab === 'day' ? 'el día' : tab === 'week' ? 'la semana' : tab === 'year' ? 'el año' : 'el período'}. `
            : 'Sin variación en el valor del portfolio. '}
          Esperando próxima actualización (snapshot diario al cierre del mercado o al
          registrar una operación).
        </div>
      )}

      {broker !== 'global' && (
        <div className="border border-line/40 bg-bg-1/30 rounded px-4 py-2 text-[11px] text-ink-3 leading-relaxed">
          Vista filtrada por broker — algunos KPIs históricos (Δ vs cierres, YTD,
          última op de otros brokers) solo están disponibles en vista global.
        </div>
      )}

      {/* KPI strip */}
      <div className="border border-line rounded bg-bg-1 overflow-hidden">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 divide-x divide-y md:divide-y-0 divide-line/40">
          {kpis.map((k, i) => (
            <div key={i} className="px-4 py-3 min-w-0">
              <div className="text-[10px] font-mono uppercase tracking-label text-ink-3 mb-1.5">{k.label}</div>
              <div className={`text-base font-medium tabular truncate ${
                k.tone === 'pos' ? 'text-rendi-pos' : k.tone === 'neg' ? 'text-rendi-neg' : 'text-ink-0'
              }`}>
                {k.value}
              </div>
              {k.sub && (
                <div className="text-[10px] font-mono text-ink-3 mt-1 truncate" title={k.sub}>{k.sub}</div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Card completo con narrativa, drivers, highlights, insights */}
      <div className="border border-line rounded bg-bg-1 overflow-hidden">
        <MonthCard period={period} defaultExpanded={true} />
      </div>
    </div>
  )
}

// Formato compacto de números — agrupador es-AR con punto.
function fmtNum(n) {
  return Math.round(n).toLocaleString('es-AR', { maximumFractionDigits: 0 })
}

function formatDateShort(iso) {
  const d = new Date(iso + 'T00:00:00')
  const MES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic']
  return `${d.getDate()} ${MES[d.getMonth()]}`
}
