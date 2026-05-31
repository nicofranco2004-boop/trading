// OperationsMobile — feed cronológico (Sprint M3, item 15 del audit).
// ═══════════════════════════════════════════════════════════════════════════
// El desktop muestra tabla densa. Mobile: feed apilado por fecha como header
// de grupo, fila por trade con badge de tipo (compra/venta) a la izquierda,
// P/L a la derecha. Patrón timeline.
//
// Filtros en sheet (item 09 del audit, finalmente implementado acá):
// - Result: all / wins / losses
// - Broker: all / cada uno
// - Period: 30d / 90d / 1y / all
//
// Sin edit/delete por fila — para eso van al desktop o tap → modal (futuro).

import { useEffect, useMemo, useState } from 'react'
import { TrendingUp, TrendingDown, Filter, X, ArrowRight, Calendar } from 'lucide-react'
import AssetLogo from '../components/AssetLogo'
import EmptyState from '../components/EmptyState'
import BottomSheet from '../components/mobile/BottomSheet'
import { api } from '../utils/api'
import { usd, pctSigned, colorClass } from '../utils/format'
import { useMoneyFormat } from '../contexts/CurrencyContext'
import { useHistoricalMoney } from '../hooks/useHistoricalMoney'
import { track } from '../utils/track'

const PERIOD_OPTIONS = [
  { id: 'all', label: 'Todo',          days: null },
  { id: '30d', label: 'Último mes',   days: 30 },
  { id: '90d', label: 'Últimos 3M',   days: 90 },
  { id: '1y',  label: 'Último año',   days: 365 },
]
const RESULT_OPTIONS = [
  { id: 'all',    label: 'Todas' },
  { id: 'wins',   label: 'Ganadoras' },
  { id: 'losses', label: 'Perdedoras' },
]

export default function OperationsMobile() {
  // Fase B: P&L respeta el toggle global ARS/USD. Conversión usa tcBlue
  // ACTUAL — para P&L histórico de hace meses, esto significa que un
  // movimiento del blue posterior va a inflar/deflactar el ARS equivalente
  // mostrado. Limitación MVP; Fase C va a trackear TC por fecha.
  const money = useMoneyFormat()
  const [ops, setOps] = useState([])
  const [brokers, setBrokers] = useState([])
  const [loading, setLoading] = useState(true)
  const [filtersOpen, setFiltersOpen] = useState(false)
  // Default 'all' — el user puede acotar a 30d / 90d / 1y desde el sheet de
  // filtros si quiere. Antes default era 90d, pero esto escondía operaciones
  // viejas en users que recién aterrizan y no entendían por qué faltaban.
  const [period, setPeriod] = useState('all')
  const [result, setResult] = useState('all')
  const [broker, setBroker] = useState('all')

  useEffect(() => {
    track('operations_mobile_viewed')
    Promise.all([
      api.get('/operations').catch(() => []),
      api.get('/brokers').catch(() => []),
    ]).then(([o, b]) => {
      setOps(o || [])
      setBrokers(b || [])
    }).finally(() => setLoading(false))
  }, [])

  // Filtros aplicados
  const filtered = useMemo(() => {
    const days = PERIOD_OPTIONS.find(p => p.id === period)?.days
    const cutoff = days ? Date.now() - days * 86400000 : null

    return ops.filter(o => {
      if (cutoff && o.date) {
        const t = new Date(o.date).getTime()
        if (isFinite(t) && t < cutoff) return false
      }
      if (result === 'wins' && !(o.pnl_usd > 0)) return false
      if (result === 'losses' && !(o.pnl_usd < 0)) return false
      if (broker !== 'all' && o.broker !== broker) return false
      return true
    })
  }, [ops, period, result, broker])

  // Agrupar por fecha YYYY-MM-DD
  const grouped = useMemo(() => {
    const groups = new Map()
    for (const op of filtered) {
      const key = op.date || 'sin-fecha'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(op)
    }
    return Array.from(groups.entries())
      .sort((a, b) => (a[0] < b[0] ? 1 : -1))
  }, [filtered])

  const totalPnl = filtered.reduce((s, o) => s + (o.pnl_usd || 0), 0)
  const wins = filtered.filter(o => o.pnl_usd > 0).length
  const losses = filtered.filter(o => o.pnl_usd < 0).length
  const winRate = (wins + losses) > 0 ? wins / (wins + losses) : null

  const activeFiltersCount = (period !== '90d' ? 1 : 0) + (result !== 'all' ? 1 : 0) + (broker !== 'all' ? 1 : 0)

  if (loading) {
    return (
      <div className="px-4 py-8 text-center text-ink-3 text-sm" aria-live="polite">
        Cargando operaciones…
      </div>
    )
  }

  return (
    <div className="pb-8">
      {/* Header sticky con KPIs + filtros */}
      <header className="sticky top-[88px] z-20 bg-bg-0/95 backdrop-blur-md border-b border-line/40 px-4 pt-3 pb-3">
        <div className="flex items-baseline justify-between mb-3">
          <div>
            <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 leading-none mb-1">
              P&L acumulado · {filtered.length} ops
            </div>
            <div className={`text-xl font-medium tabular leading-none ${colorClass(totalPnl)}`}>
              {money.fmtMoney(totalPnl, { signed: true })}
            </div>
          </div>
          {winRate != null && (
            <div className="text-right">
              <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 leading-none mb-1">
                Win rate
              </div>
              <div className="text-xl font-medium tabular text-ink-0 leading-none">
                {(winRate * 100).toFixed(0)}%
              </div>
              <div className="text-[10px] font-mono text-ink-3 leading-none mt-1">
                <span className="text-rendi-pos">{wins}W</span> · <span className="text-rendi-neg">{losses}L</span>
              </div>
            </div>
          )}
        </div>

        <button
          onClick={() => setFiltersOpen(true)}
          className="w-full inline-flex items-center justify-between gap-2 bg-bg-2 border border-line/60 rounded-sm px-3 py-1.5 text-xs text-ink-2 hover:text-ink-0 hover:bg-bg-3 transition-colors"
        >
          <span className="flex items-center gap-1.5">
            <Filter size={11} strokeWidth={1.75} />
            Filtros
            {activeFiltersCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded-sm bg-rendi-accent/20 text-rendi-accent text-[10px] font-mono">
                {activeFiltersCount}
              </span>
            )}
          </span>
          <span className="text-[11px] font-mono uppercase tracking-caps text-ink-2">
            {PERIOD_OPTIONS.find(p => p.id === period)?.label}
            {broker !== 'all' && ` · ${broker}`}
            {result !== 'all' && ` · ${RESULT_OPTIONS.find(r => r.id === result)?.label}`}
          </span>
        </button>
      </header>

      {/* Feed */}
      {grouped.length === 0 ? (
        <div className="px-4 py-10">
          <EmptyState
            title="Sin operaciones en este filtro"
            description="Cambiá el período o limpiá los filtros para ver más."
            action={
              activeFiltersCount > 0 && (
                <button
                  onClick={() => { setPeriod('all'); setResult('all'); setBroker('all') }}
                  className="text-xs font-mono uppercase tracking-caps text-data-blue hover:text-rendi-accent"
                >
                  Limpiar filtros
                </button>
              )
            }
          />
        </div>
      ) : (
        <ul>
          {grouped.map(([date, items]) => (
            <DayGroup key={date} date={date} ops={items} />
          ))}
        </ul>
      )}

      {/* Sheet de filtros */}
      <BottomSheet
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        eyebrow="Filtros"
        title="Refinar operaciones"
      >
        <div className="p-4 space-y-5">
          <FilterGroup
            label="Período"
            options={PERIOD_OPTIONS}
            value={period}
            onChange={setPeriod}
          />
          <FilterGroup
            label="Resultado"
            options={RESULT_OPTIONS}
            value={result}
            onChange={setResult}
          />
          <FilterGroup
            label="Broker"
            options={[{ id: 'all', label: 'Todos' }, ...brokers.map(b => ({ id: b.name, label: b.name }))]}
            value={broker}
            onChange={setBroker}
          />

          <div className="pt-2 flex items-center gap-2">
            <button
              onClick={() => { setPeriod('90d'); setResult('all'); setBroker('all') }}
              className="flex-1 text-xs font-mono uppercase tracking-caps text-ink-2 hover:text-ink-0 border border-line/60 hover:bg-bg-2/60 rounded-sm py-2 transition-colors"
            >
              Restablecer
            </button>
            <button
              onClick={() => setFiltersOpen(false)}
              className="flex-1 text-xs font-mono uppercase tracking-caps bg-rendi-pos/10 text-rendi-pos border border-rendi-pos/30 hover:bg-rendi-pos/15 rounded-sm py-2 transition-colors"
            >
              Aplicar
            </button>
          </div>
        </div>
      </BottomSheet>
    </div>
  )
}

// ─── Day group ────────────────────────────────────────────────────────────

function DayGroup({ date, ops }) {
  // Phase C audit fix H1: el subtotal del DÍA es de operaciones que TODAS
  // tienen la misma fecha → usamos FX histórico de esa fecha. Si las ops
  // tienen fx_to_usd stampeado, sumamos los valores ya convertidos para
  // máxima precisión. Sino, usamos el FX del día (el del primer op como proxy).
  const histMoney = useHistoricalMoney()
  const subtotal = ops.reduce((s, o) => s + (o.pnl_usd || 0), 0)
  const label = formatDateLabel(date)
  // Para el subtotal, usamos la fecha del día (todos los ops la comparten).
  const stampedFx = ops.find(o => o.fx_to_usd && o.fx_to_usd > 0)?.fx_to_usd
  return (
    <li className="border-t border-line/30">
      <div className="flex items-baseline justify-between px-4 py-2 bg-bg-1/50">
        <div className="flex items-center gap-1.5">
          <Calendar size={11} strokeWidth={1.75} className="text-ink-3" />
          <span className="text-[11px] font-mono uppercase tracking-caps text-ink-2">
            {label}
          </span>
          <span className="text-[10px] font-mono text-ink-3">
            · {ops.length} {ops.length === 1 ? 'op' : 'ops'}
          </span>
        </div>
        <span className={`text-[11px] font-mono tabular ${colorClass(subtotal)}`}>
          {histMoney.fmtMoneyCompactAt(subtotal, {
            stampedFx,
            dateIso: date,
            signed: true,
          })}
        </span>
      </div>
      <ul>
        {ops.map(op => <OperationRow key={op.id} op={op} />)}
      </ul>
    </li>
  )
}

// ─── Row ──────────────────────────────────────────────────────────────────

function OperationRow({ op }) {
  // Phase C audit fix H1: cada operación usa su propio FX histórico.
  const histMoney = useHistoricalMoney()
  const isWin = op.pnl_usd != null && op.pnl_usd > 0
  const isLoss = op.pnl_usd != null && op.pnl_usd < 0
  const type = (op.op_type || '').toLowerCase()
  const isBuy = type.includes('compra') || type === 'buy'

  return (
    <li className="flex items-center gap-3 px-4 py-2.5 border-t border-line/20 first:border-t-0">
      <AssetLogo asset={op.asset} size={28} />

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className="text-sm font-semibold text-ink-0 leading-none truncate">
            {op.asset}
          </span>
          <span className="text-[11px] font-mono uppercase tracking-caps text-ink-2 leading-none">
            {op.broker}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-1.5">
          <span className={`inline-flex items-center text-[9px] font-mono uppercase tracking-caps px-1 py-0.5 rounded-sm ${
            isBuy
              ? 'bg-data-blue/10 text-data-blue border border-data-blue/30'
              : 'bg-data-violet/10 text-data-violet border border-data-violet/30'
          }`}>
            {isBuy ? 'Compra' : (op.op_type || 'Venta')}
          </span>
          {op.quantity != null && (
            <span className="text-[10px] font-mono text-ink-3 truncate">
              {formatQty(op.quantity)} u.
            </span>
          )}
        </div>
      </div>

      <div className="flex-shrink-0 text-right">
        {op.pnl_usd != null && (
          <div className={`text-sm font-medium tabular leading-none flex items-center justify-end gap-1 ${colorClass(op.pnl_usd)}`}>
            {isWin ? <TrendingUp size={11} strokeWidth={1.75} /> : isLoss ? <TrendingDown size={11} strokeWidth={1.75} /> : null}
            {histMoney.fmtMoneyCompactAt(op.pnl_usd, {
              stampedFx: op.fx_to_usd,
              dateIso: op.date,
              signed: true,
            })}
          </div>
        )}
        {op.pnl_pct != null && (
          <div className={`text-[10px] font-mono tabular leading-none mt-1.5 ${colorClass(op.pnl_pct)}`}>
            {pctSigned(op.pnl_pct / 100)}
          </div>
        )}
      </div>
    </li>
  )
}

// ─── Filter group ─────────────────────────────────────────────────────────

function FilterGroup({ label, options, value, onChange }) {
  return (
    <div>
      <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">
        {label}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {options.map(o => (
          <button
            key={o.id}
            onClick={() => onChange(o.id)}
            className={`text-xs px-3 py-1.5 rounded-sm border transition-colors ${
              value === o.id
                ? 'bg-rendi-accent/15 text-rendi-accent border-rendi-accent/40'
                : 'bg-bg-2 text-ink-2 border-line/60 hover:bg-bg-3 hover:text-ink-0'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────

const MESES_ES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

function formatDateLabel(date) {
  if (!date || date === 'sin-fecha') return 'Sin fecha'
  // Esperamos YYYY-MM-DD
  const d = new Date(date + 'T00:00:00')
  if (isNaN(d)) return date
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  if (sameDay) return 'Hoy'
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return 'Ayer'
  return `${d.getDate()} ${MESES_ES[d.getMonth()]} ${d.getFullYear()}`
}

function formatQty(q) {
  if (q == null || isNaN(q)) return '—'
  if (Math.abs(q) >= 1000) return Math.round(q).toLocaleString('en-US')
  if (Math.abs(q) >= 1) return q.toFixed(2).replace(/\.00$/, '')
  return q.toFixed(4)
}
