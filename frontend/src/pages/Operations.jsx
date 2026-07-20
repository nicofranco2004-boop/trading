// Operations — historial de operaciones cerradas (V2).
// ════════════════════════════════════════════════════════════════════════════
// Header operativo + KPI strip denso + filtros mono caps + tabla compacta.

import { useEffect, useMemo, useState, Fragment } from 'react'
import { Plus, Pencil, Trash2, ArrowUpRight, ArrowDownRight, Search, X, SlidersHorizontal, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, ArrowDownToLine, ArrowUpFromLine, Coins, Receipt, Repeat } from 'lucide-react'
import Modal from '../components/Modal'
import TickerSearch from '../components/TickerSearch'
import DateInput from '../components/DateInput'
import { usd, fmtUsd as fmtUsdRaw, pctSigned, colorClass } from '../utils/format'
import { track } from '../utils/track'
import { useMoneyFormat } from '../contexts/CurrencyContext'
import { useHistoricalMoney } from '../hooks/useHistoricalMoney'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import EmptyState from '../components/EmptyState'
import InsightLine from '../components/InsightLine'
import { api } from '../utils/api'
import OperationsMobile from './OperationsMobile'
import { useIsMobile } from '../hooks/useIsMobile'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import InlineAIButton from '../components/ai/InlineAIButton'
import ExportCsvButton from '../components/plan/ExportCsvButton'

const PAGE_SIZE = 50

// pnl_usd arranca como string vacío (no 0) para que el form distinga
// "no completado" de "0 USD" — sin esto, el user que quiere cargar un trade
// rápido SÓLO con P&L (sin precios) y deja el campo en blanco, termina
// guardando 0 sin darse cuenta porque el value=0 era el default y "parece
// completado". Lo manejamos abajo en save(): vacío → null al backend.
const EMPTY = { date: new Date().toISOString().slice(0, 10), broker: '', asset: '', op_type: '', entry_price: '', exit_price: '', quantity: '', pnl_usd: '', pnl_pct: '', commissions: '' }

function prettyOpType(raw) {
  if (!raw) return '—'
  const s = String(raw).trim()
  if (s.startsWith('CONVERSION IMPORT ARS→USDT') || s.startsWith('CONVERSION IMPORT ARS→USD')) return 'Conversión ARS→USD'
  if (s.startsWith('CONVERSION IMPORT USDT→ARS') || s.startsWith('CONVERSION IMPORT USD→ARS')) return 'Conversión USD→ARS'
  return s
}

export default function Operations() {
  const isMobile = useIsMobile()
  if (isMobile) return <OperationsMobile />
  return <OperationsDesktop />
}

function OperationsDesktop() {
  // tab: 'trades' = vista actual de operaciones cerradas con KPIs P&L
  //      'all'    = historial unificado (trades + depósitos + retiros + dividendos + intereses + comisiones)
  // Persistimos selección en localStorage para que respete preferencia del user.
  const [tab, setTab] = useState(() => localStorage.getItem('rendi_operations_tab') || 'all')
  useEffect(() => { localStorage.setItem('rendi_operations_tab', tab) }, [tab])
  // Fase B+C: P&L realizado respeta el toggle global ARS/USD. Para operaciones
  // individuales usamos FX HISTÓRICO (op.fx_to_usd stampeado al cierre del
  // trade > lookup por op.date > tcBlue actual). Para los KPIs agregados
  // (totalPnl, bestTrade) que no tienen una fecha única, usamos tcBlue actual
  // via useMoneyFormat — limitación aceptada porque mezclan trades de
  // múltiples fechas.
  const money = useMoneyFormat()
  const histMoney = useHistoricalMoney()
  const fmtUsd = (v) => money.fmtMoney(v, { signed: false })
  const fmtUsdSigned = (v) => money.fmtMoney(v, { signed: true })

  const [ops, setOps] = useState([])
  const [brokers, setBrokers] = useState([])
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [filterAsset, setFilterAsset] = useState('')
  const [filterBroker, setFilterBroker] = useState('all')
  const [filterResult, setFilterResult] = useState('all')
  const [filterYear, setFilterYear] = useState('all')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [page, setPage] = useState(0)
  // Agrupación del tab "Solo P/L". 'asset' por defecto (1 fila por activo,
  // reduce ruido). Estado PROPIO de este tab — no se comparte con MovementsView
  // (que tiene su 'rendi_movements_group'). Persistido en localStorage.
  const [groupBy, setGroupBy] = useState(() => localStorage.getItem('rendi_trades_group') || 'asset')
  useEffect(() => { localStorage.setItem('rendi_trades_group', groupBy) }, [groupBy])
  // Grupos expandidos (Set de keys). Click en la fila-resumen togglea su detalle.
  const [expandedGroups, setExpandedGroups] = useState(() => new Set())
  function toggleGroup(key) {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  useEffect(() => {
    load()
    api.get('/brokers').then(b => setBrokers(b))
  }, [])

  async function load() { setOps(await api.get('/operations')) }

  function openAdd() {
    setForm({ ...EMPTY, broker: brokers[0]?.name ?? '' })
    setModal('add')
  }
  function openEdit(op) {
    // pnl_usd: si la op vino con null, lo mostramos como '' (no como "null"
    // string). Si es 0 deliberado, queda 0 visible en el input.
    setForm({
      ...op,
      entry_price: op.entry_price ?? '',
      exit_price: op.exit_price ?? '',
      quantity: op.quantity ?? '',
      pnl_usd: op.pnl_usd ?? '',
      pnl_pct: op.pnl_pct ?? '',
      commissions: op.commissions ?? '',
    })
    setModal('edit')
  }

  async function save() {
    const body = {
      ...form,
      entry_price: form.entry_price !== '' ? +form.entry_price : null,
      exit_price: form.exit_price !== '' ? +form.exit_price : null,
      quantity: form.quantity !== '' ? +form.quantity : null,
      // P&L USD: si el user lo deja vacío, mandamos null (no 0) — eso
      // significa "no registré la ganancia/pérdida". Backend distingue
      // null vs 0 explícito (un trade flat sí puede tener pnl_usd=0).
      pnl_usd: form.pnl_usd !== '' && form.pnl_usd !== null ? +form.pnl_usd : null,
      pnl_pct: form.pnl_pct !== '' ? +form.pnl_pct : null,
      commissions: form.commissions !== '' ? +form.commissions : 0,
    }
    if (modal === 'edit') await api.put(`/operations/${form.id}`, body)
    else {
      await api.post('/operations', body)
      track('operation_added', {
        mode: body.op_type,
        only_pnl: body.entry_price == null && body.pnl_usd != null,
        broker: body.broker,
      })
    }
    setModal(null)
    load()
  }

  async function del(id) {
    if (!confirm('¿Eliminar esta operación? La acción no se puede deshacer.')) return
    await api.delete(`/operations/${id}`)
    load()
  }

  // KPIs sobre todas las ops, no las filtradas
  const totalPnl = ops.reduce((s, o) => s + (o.pnl_usd || 0), 0)
  const wins = ops.filter(o => o.pnl_usd > 0).length
  const losses = ops.filter(o => o.pnl_usd < 0).length
  const winRate = ops.length > 0 ? wins / ops.length : 0
  const bestTrade = ops.length > 0 ? Math.max(...ops.map(o => o.pnl_usd || 0)) : null

  // Patrones derivados de las operaciones — observaciones escaneables arriba de
  // la tabla. Cálculo inline (diagnostics.js espera el objeto `data` completo
  // del portfolio + rotación por severidad — overkill para 1-2 líneas fijas).
  const patterns = useMemo(() => {
    if (ops.length < 3) return []
    const out = []

    // (1) Activo más operado (cualquier op_type). Solo si hay líder claro.
    const countByAsset = {}
    for (const o of ops) {
      const a = (o.asset || '').trim()
      if (!a) continue
      countByAsset[a] = (countByAsset[a] || 0) + 1
    }
    const ranked = Object.entries(countByAsset).sort((a, b) => b[1] - a[1])
    if (ranked.length > 0 && ranked[0][1] >= 3 && (ranked.length === 1 || ranked[0][1] > ranked[1][1])) {
      out.push({ key: 'most_traded', asset: ranked[0][0], count: ranked[0][1] })
    }

    // (2) Racha ganadora más larga (cronológica, pnl_usd > 0 consecutivos).
    const chron = [...ops]
      .filter(o => o.date && o.pnl_usd != null)
      .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
    let best = 0, cur = 0
    for (const o of chron) {
      if (o.pnl_usd > 0) { cur++; if (cur > best) best = cur }
      else cur = 0
    }
    if (best >= 3) out.push({ key: 'win_streak', streak: best })

    return out
  }, [ops])

  const yearsAvailable = useMemo(() => {
    const set = new Set(ops.map(o => o.date?.slice(0, 4)).filter(Boolean))
    return [...set].sort().reverse()
  }, [ops])

  const filteredOps = useMemo(() => {
    const q = filterAsset.trim().toUpperCase()
    return ops.filter(o => {
      if (q && !(o.asset || '').toUpperCase().includes(q)) return false
      if (filterBroker !== 'all' && o.broker !== filterBroker) return false
      if (filterResult === 'wins' && !(o.pnl_usd > 0)) return false
      if (filterResult === 'losses' && !(o.pnl_usd < 0)) return false
      if (filterYear !== 'all' && !(o.date || '').startsWith(filterYear)) return false
      return true
    })
  }, [ops, filterAsset, filterBroker, filterResult, filterYear])

  const filtersActiveCount =
    (filterAsset ? 1 : 0) +
    (filterBroker !== 'all' ? 1 : 0) +
    (filterResult !== 'all' ? 1 : 0) +
    (filterYear !== 'all' ? 1 : 0)
  const filtersActive = filtersActiveCount > 0

  // Reset a página 0 cuando cambian los filtros, el modo de agrupado, o el
  // dataset cambia de tamaño.
  useEffect(() => {
    setPage(0)
  }, [filterAsset, filterBroker, filterResult, filterYear, groupBy, ops.length])

  const grouped = groupBy !== 'none'

  // Grupos por activo / mes sobre lo YA filtrado (filtramos y después agrupamos,
  // como en MovementsView). Reusa buildGroups module-level: es genérica y las
  // ops del tab trades comparten shape suficiente (date/asset/broker/pnl_usd) —
  // movPnl lee op.pnl_usd, y acá TODAS las filas son trades cerrados con P&L.
  const groups = useMemo(
    () => (grouped ? buildGroups(filteredOps, groupBy) : []),
    [filteredOps, groupBy, grouped]
  )

  // Paginación SOLO en modo 'none' (lista plana). En modo agrupado mostramos
  // todos los grupos sin paginar y ocultamos el control (mismo criterio que
  // MovementsView).
  const totalPages = Math.max(1, Math.ceil(filteredOps.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages - 1)
  const pagedOps = useMemo(
    () => filteredOps.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE),
    [filteredOps, currentPage]
  )

  return (
    <div className="page-shell-wide">
      <PageHeader
        eyebrow="Tu actividad"
        title="Operaciones"
        subtitle={tab === 'trades'
          ? 'Historial de trades cerrados con P&L realizado.'
          : 'Todos los movimientos: trades, depósitos, retiros, dividendos y comisiones.'}
        action={
          <div className="flex items-center gap-2 flex-wrap">
            <AnalyzeButton screen="operations" subtitle="Tu historial completo" />
            <ExportCsvButton resource="operations" source="operations_header" variant="compact" />
            <button
              onClick={openAdd}
              className="inline-flex items-center gap-1.5 text-xs bg-data-violet/10 text-data-violet hover:bg-data-violet/15 border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors font-medium"
            >
              <Plus size={12} strokeWidth={2} /> Nueva operación
            </button>
          </div>
        }
      />

      {/* Tab switcher: Todos los movimientos vs solo Trades — mismo diseño
          que /posiciones y /analisis (filled pills + violet en activa). */}
      <div className="inline-flex flex-wrap gap-2 mb-5">
        <button
          onClick={() => setTab('all')}
          className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-md border transition-all ${
            tab === 'all'
              ? 'bg-data-violet/15 text-data-violet border-data-violet/40 shadow-sm'
              : 'bg-bg-1 text-ink-2 border-line hover:text-ink-0 hover:border-line-2 hover:bg-bg-2'
          }`}
        >
          Todos los movimientos
        </button>
        <button
          onClick={() => setTab('trades')}
          className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-md border transition-all ${
            tab === 'trades'
              ? 'bg-data-violet/15 text-data-violet border-data-violet/40 shadow-sm'
              : 'bg-bg-1 text-ink-2 border-line hover:text-ink-0 hover:border-line-2 hover:bg-bg-2'
          }`}
        >
          Solo P/L
        </button>
      </div>

      {/* Si el user eligió "Todos los movimientos", renderizamos un
          componente aparte que fetcha /api/movements (unificado). El return
          temprano evita renderizar el resto de la página (KPIs de trades,
          tabla, modales) que solo aplica al tab "Solo trades". */}
      {tab === 'all' && <MovementsView />}
      {tab === 'trades' && (
      <>
      {/* KPI strip denso */}
      <div className="border border-line rounded bg-bg-1 flex flex-wrap mb-4">
        <KpiCell
          first
          label="P&L Realizado"
          value={fmtUsd(totalPnl)}
          tone={totalPnl >= 0 ? 'pos' : 'neg'}
          sub="acumulado histórico"
        />
        <KpiCell
          label="Win rate"
          value={ops.length > 0 ? `${(winRate * 100).toFixed(0)}%` : '—'}
          tone={ops.length > 0 ? (winRate >= 0.5 ? 'pos' : 'neg') : null}
          sub={ops.length > 0 ? `${wins} ganadoras · ${losses} perdedoras` : 'sin operaciones'}
        />
        <KpiCell
          label="Operaciones"
          value={ops.length.toLocaleString('es-AR')}
          sub="total cerradas"
        />
        <KpiCell
          label="Mejor trade"
          value={bestTrade != null ? fmtUsd(bestTrade) : '—'}
          tone={bestTrade != null && bestTrade > 0 ? 'pos' : null}
          sub="P&L individual"
        />
      </div>

      {/* Strip de patrones — observaciones derivadas de las operaciones. */}
      {patterns.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          {patterns.map(p => (
            <InsightLine key={p.key} tone="neutral">
              {p.key === 'most_traded' && (
                <>
                  Operaste <strong className="font-semibold text-ink-0">{p.asset}</strong>{' '}
                  <strong className="font-semibold text-ink-0">{p.count} veces</strong> — más que cualquier otro activo.
                </>
              )}
              {p.key === 'win_streak' && (
                <>
                  Tu racha más larga: <strong className="font-semibold text-ink-0">{p.streak} ganadoras seguidas</strong>.
                </>
              )}
            </InsightLine>
          ))}
        </div>
      )}

      {/* Filtros — collapsable, abren con botón */}
      {ops.length > 0 && (
        <div className="mb-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setFiltersOpen(o => !o)}
                className={`inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps px-2.5 py-1.5 rounded-sm border transition-colors ${
                  filtersActive
                    ? 'border-rendi-pos/30 bg-rendi-pos/10 text-rendi-pos'
                    : 'border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3'
                }`}
                aria-expanded={filtersOpen}
              >
                <SlidersHorizontal size={11} strokeWidth={2} aria-hidden="true" />
                Filtros
                {filtersActive && (
                  <span className="ml-1 inline-flex items-center justify-center min-w-[14px] h-[14px] px-1 text-[9px] rounded-sm bg-rendi-pos/20 text-rendi-pos tabular">
                    {filtersActiveCount}
                  </span>
                )}
              </button>
              {filtersActive && (
                <button
                  onClick={() => { setFilterAsset(''); setFilterBroker('all'); setFilterResult('all'); setFilterYear('all') }}
                  className="inline-flex items-center gap-1 text-[12.5px] text-ink-2 hover:text-ink-0 px-2 py-1 rounded-sm hover:bg-bg-2 transition-colors font-medium"
                >
                  <X size={11} strokeWidth={1.75} /> Limpiar
                </button>
              )}
            </div>
            <span className="text-[12.5px] text-ink-2 tabular font-medium">
              {filteredOps.length} de {ops.length}
            </span>
          </div>
          {filtersOpen && (
            <Panel padding="sm" className="mt-2">
              <div className="flex flex-wrap items-center gap-3">
                <div className="relative flex-1 min-w-[220px]">
                  <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3 pointer-events-none" strokeWidth={1.75} />
                  <input
                    value={filterAsset}
                    onChange={e => setFilterAsset(e.target.value)}
                    placeholder="Buscar activo (BTC, GGAL…)"
                    className="w-full bg-bg-2 border border-line rounded-sm pl-8 pr-3 py-1.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2"
                  />
                </div>
                <FilterPill label="Broker" value={filterBroker} onChange={setFilterBroker}
                  options={[{ id: 'all', label: 'Todos' }, ...brokers.map(b => ({ id: b.name, label: b.name }))]} />
                <FilterPill label="Resultado" value={filterResult} onChange={setFilterResult}
                  options={[{ id: 'all', label: 'Todos' }, { id: 'wins', label: 'Ganadoras' }, { id: 'losses', label: 'Perdedoras' }]} />
                <FilterPill label="Año" value={filterYear} onChange={setFilterYear}
                  options={[{ id: 'all', label: 'Todos' }, ...yearsAvailable.map(y => ({ id: y, label: y }))]} />
                <FilterPill label="Agrupar" value={groupBy} onChange={setGroupBy} options={GROUP_OPTIONS} />
              </div>
            </Panel>
          )}
        </div>
      )}

      <Panel padding="none">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-line text-[12.5px] text-ink-2 font-medium">
                <th className="text-left px-4 py-2.5 font-medium">Fecha</th>
                <th className="text-left px-3 py-2.5 font-medium">Broker</th>
                <th className="text-left px-3 py-2.5 font-medium">Activo</th>
                <th className="text-left px-3 py-2.5 font-medium">Tipo</th>
                <th className="text-right px-3 py-2.5 font-medium">P. Entrada</th>
                <th className="text-right px-3 py-2.5 font-medium">P. Salida</th>
                <th className="text-right px-3 py-2.5 font-medium">Cant.</th>
                <th className="text-right px-3 py-2.5 font-medium">P&L USD</th>
                <th className="text-right px-3 py-2.5 font-medium">P&L %</th>
                <th className="px-3 py-2.5 w-[60px]"></th>
                <th className="px-3 py-2.5 w-[28px] text-center font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {ops.length === 0 && (
                <tr><td colSpan={11}>
                  <EmptyState
                    icon={<ArrowUpRight size={20} />}
                    title="Aún no hay operaciones registradas"
                    description="Las ventas realizadas desde Posiciones quedan registradas automáticamente con su P&L realizado. También podés agregar operaciones manualmente."
                    action={
                      <button onClick={openAdd} className="inline-flex items-center gap-1.5 text-xs bg-data-violet/10 text-data-violet hover:bg-data-violet/15 border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors font-medium">
                        <Plus size={12} strokeWidth={2} /> Agregar manualmente
                      </button>
                    }
                  />
                </td></tr>
              )}
              {ops.length > 0 && filteredOps.length === 0 && (
                <tr><td colSpan={11}>
                  <EmptyState title="Sin resultados para los filtros aplicados" description="Ajustá los filtros para ampliar la búsqueda." dense />
                </td></tr>
              )}
              {/* Modo lista plana ('none') — la tabla de siempre, paginada. */}
              {!grouped && pagedOps.map(op => (
                <TradeRow key={op.id} op={op} histMoney={histMoney} onEdit={openEdit} onDelete={del} />
              ))}
              {/* Modo agrupado (por activo / mes) — fila-resumen expandible. */}
              {grouped && groups.map(g => {
                const isOpen = expandedGroups.has(g.key)
                return (
                  <Fragment key={g.key}>
                    <TradeGroupRow
                      group={g}
                      groupBy={groupBy}
                      isOpen={isOpen}
                      onToggle={() => toggleGroup(g.key)}
                      fmtPnl={fmtUsdSigned}
                    />
                    {isOpen && g.rows.map(op => (
                      <TradeRow key={op.id} op={op} histMoney={histMoney} onEdit={openEdit} onDelete={del} indent />
                    ))}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Paginación — oculta en modo agrupado (mismo criterio que MovementsView). */}
        {!grouped && filteredOps.length > PAGE_SIZE && (
          <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-t border-line text-[12.5px] text-ink-3 font-medium">
            <span className="tabular">
              {currentPage * PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PAGE_SIZE, filteredOps.length)} de {filteredOps.length}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage(p => Math.max(0, p - 1))}
                disabled={currentPage === 0}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-sm border border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                aria-label="Página anterior"
              >
                <ChevronLeft size={11} strokeWidth={2} aria-hidden="true" /> Anterior
              </button>
              <span className="px-3 tabular text-ink-2">
                {currentPage + 1} / {totalPages}
              </span>
              <button
                onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                disabled={currentPage >= totalPages - 1}
                className="inline-flex items-center gap-1 px-2 py-1 rounded-sm border border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                aria-label="Página siguiente"
              >
                Siguiente <ChevronRight size={11} strokeWidth={2} aria-hidden="true" />
              </button>
            </div>
          </div>
        )}
      </Panel>

      {modal && (
        <OpFormModal
          mode={modal}
          form={form}
          setForm={setForm}
          brokers={brokers}
          onSave={save}
          onClose={() => setModal(null)}
        />
      )}
      </>
      )}
    </div>
  )
}

// ─── Subcomponentes ──────────────────────────────────────────────────────────

function KpiCell({ label, value, sub, tone, first }) {
  const valueColor =
    tone === 'pos' ? 'text-rendi-pos' :
    tone === 'neg' ? 'text-rendi-neg' :
    'text-ink-0'
  return (
    <div className={`px-4 py-3 flex-1 min-w-[140px] ${first ? '' : 'border-l border-line/50'}`}>
      <div className="text-[12.5px] text-ink-2 leading-none font-medium">{label}</div>
      <div className={`mt-2 font-medium tabular num leading-none text-2xl tracking-tight ${valueColor}`}>{value}</div>
      <div className="text-[12.5px] text-ink-2 mt-1.5 leading-none truncate font-medium">{sub}</div>
    </div>
  )
}

function FilterPill({ label, value, onChange, options }) {
  return (
    <label className="inline-flex items-center gap-1.5 text-xs">
      <span className="text-[12.5px] text-ink-2 font-medium">{label}</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="bg-bg-2 border border-line rounded-sm px-2 py-1 text-xs text-ink-1 font-mono focus:outline-none focus:border-ink-2"
      >
        {options.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>
  )
}

// ─── Filas del tab "Solo P/L" ────────────────────────────────────────────────

// Fila de un trade cerrado en la tabla del tab "Solo P/L". Se usa tanto en la
// lista plana (modo 'none') como en el detalle de un grupo (modo agrupado),
// donde va atenuada/indentada con "└" — mismo recurso visual que MovementRow.
// Mantiene las acciones por-trade (analizar/editar/eliminar) en todos los modos.
function TradeRow({ op, histMoney, onEdit, onDelete, indent = false }) {
  const isWin = op.pnl_usd != null && op.pnl_usd > 0
  const isLoss = op.pnl_usd != null && op.pnl_usd < 0
  const ArrowIcon = isWin ? ArrowUpRight : isLoss ? ArrowDownRight : null
  const arrowColor = isWin ? 'text-rendi-pos' : isLoss ? 'text-rendi-neg' : 'text-ink-3'
  return (
    <tr className={`border-b border-line/30 hover:bg-bg-2/40 transition-colors ${indent ? 'bg-bg-2/15' : ''}`}>
      <td className={`px-4 py-2 text-xs font-mono tabular text-ink-2 ${indent ? 'pl-6 opacity-75' : ''}`}>
        {indent && <span className="text-ink-3 font-mono select-none mr-1" title="Detalle">└</span>}
        {op.date}
      </td>
      <td className={`px-3 py-2 text-xs text-ink-2 ${indent ? 'opacity-75' : ''}`}>{op.broker}</td>
      <td className={`px-3 py-2 text-sm font-medium text-ink-0 ${indent ? 'opacity-75' : ''}`}>{op.asset}</td>
      <td className={`px-3 py-2 text-[12.5px] text-ink-3 ${indent ? 'opacity-75' : ''} font-medium`}>{prettyOpType(op.op_type)}</td>
      <td className={`px-3 py-2 text-xs font-mono tabular text-right text-ink-2 ${indent ? 'opacity-75' : ''}`}>{op.entry_price != null ? usd(op.entry_price) : '—'}</td>
      <td className={`px-3 py-2 text-xs font-mono tabular text-right text-ink-2 ${indent ? 'opacity-75' : ''}`}>{op.exit_price != null ? usd(op.exit_price) : '—'}</td>
      <td className={`px-3 py-2 text-xs font-mono tabular text-right text-ink-2 ${indent ? 'opacity-75' : ''}`}>{op.quantity ?? '—'}</td>
      <td className={`px-3 py-2 text-sm font-mono tabular text-right font-medium ${colorClass(op.pnl_usd)} ${indent ? 'opacity-75' : ''}`}>
        {op.pnl_usd == null
          ? '—'
          : histMoney.fmtMoneyAt(op.pnl_usd, {
              stampedFx: op.fx_to_usd,
              dateIso: op.date,
              signed: true,
            })}
      </td>
      <td className={`px-3 py-2 text-xs font-mono tabular text-right ${colorClass(op.pnl_pct)} ${indent ? 'opacity-75' : ''}`}>
        {op.pnl_pct != null ? pctSigned(op.pnl_pct / 100) : '—'}
      </td>
      <td className="px-3 py-2">
        <div className="flex gap-1 justify-end items-center">
          {op.pnl_usd != null && (
            <InlineAIButton
              topic="operations.trade"
              params={{ operation_id: op.id }}
              subtitle={`${op.asset} · ${op.date}`}
              ariaLabel={`Analizar trade de ${op.asset}`}
            />
          )}
          <button onClick={() => onEdit(op)} className="text-ink-3 hover:text-ink-0 transition-colors p-1" title="Editar" aria-label={`Editar operación ${op.asset}`}>
            <Pencil size={13} strokeWidth={1.75} aria-hidden="true" />
          </button>
          <button onClick={() => onDelete(op.id)} className="text-ink-3 hover:text-rendi-neg transition-colors p-1" title="Eliminar" aria-label={`Eliminar operación ${op.asset}`}>
            <Trash2 size={13} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      </td>
      <td className="pr-4 pl-1 py-2 align-middle text-right">
        {ArrowIcon
          ? <ArrowIcon size={16} strokeWidth={2.25} className={`inline-block ${arrowColor}`} aria-label={isWin ? 'Ganancia' : 'Pérdida'} />
          : <span className="text-ink-3 text-xs">—</span>}
      </td>
    </tr>
  )
}

// Fila-resumen de un grupo de trades (modo agrupado por activo o por mes).
// Click → toggle del detalle. Muestra: etiqueta (ticker o mes) · broker(s) ·
// # de trades · P&L total con flecha ↗/↘. El P&L se formatea con el toggle
// global vía fmtPnl (tcBlue actual — el grupo mezcla trades de distintas
// fechas, igual que los KPIs agregados). Reusa buildGroups → group.pnl ya suma
// los pnl_usd de las filas (acá todas son trades cerrados con P&L).
function TradeGroupRow({ group, groupBy, isOpen, onToggle, fmtPnl }) {
  const { label, count, pnl, brokers } = group
  const Chevron = isOpen ? ChevronUp : ChevronDown
  const hasPnl = pnl !== 0
  const Arrow = pnl > 0 ? ArrowUpRight : pnl < 0 ? ArrowDownRight : null
  const brokersLabel = brokers.length === 0
    ? '—'
    : brokers.length <= 2
    ? brokers.join(' · ')
    : `${brokers.length} brokers`
  return (
    <tr
      className="border-b border-line/40 bg-bg-2/40 hover:bg-bg-2/60 cursor-pointer transition-colors"
      onClick={onToggle}
    >
      {/* Etiqueta del grupo + chevron — ocupa Fecha */}
      <td className="px-4 py-2.5">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onToggle() }}
          className="inline-flex items-center gap-1.5 text-ink-0 font-semibold text-sm"
          aria-expanded={isOpen}
        >
          <Chevron size={13} strokeWidth={2} className="text-ink-3" aria-hidden="true" />
          {label}
        </button>
      </td>
      {/* Broker(s) — solo tiene sentido en agrupado por activo */}
      <td className="px-3 py-2.5 text-ink-3 text-xs">
        {groupBy === 'asset' ? brokersLabel : '—'}
      </td>
      {/* # trades — ocupa Activo … Cant. */}
      <td className="px-3 py-2.5 text-ink-2" colSpan={5}>
        <span className="text-[12.5px] font-medium">
          {count} {count === 1 ? 'trade' : 'trades'}
        </span>
      </td>
      {/* P&L total con flecha — bajo "P&L USD" */}
      <td className={`px-3 py-2.5 text-right font-mono font-semibold tabular ${colorClass(hasPnl ? pnl : null)}`}>
        <span className="inline-flex items-center gap-1 justify-end">
          {Arrow && <Arrow size={13} strokeWidth={2.25} aria-hidden="true" />}
          {hasPnl ? fmtPnl(pnl) : '—'}
        </span>
      </td>
      {/* Resto (P&L % · acciones · flecha) — hint del P&L */}
      <td className="px-3 py-2.5 text-ink-3 text-[12px] text-right font-medium" colSpan={3}>
        {hasPnl ? 'P&L total' : ''}
      </td>
    </tr>
  )
}

// ─── Modal ───────────────────────────────────────────────────────────────────

function OpFormModal({ mode, form, setForm, brokers, onSave, onClose }) {
  const inputClass = 'w-full bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2'
  const labelClass = 'block text-[12.5px] text-ink-2 mb-1 font-medium'
  return (
    <Modal title={mode === 'edit' ? 'Editar operación' : 'Nueva operación'} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelClass}>Fecha</label>
            <DateInput value={form.date} onChange={v => setForm(f => ({ ...f, date: v }))} />
          </div>
          <div>
            <label className={labelClass}>Broker</label>
            {brokers.length > 0 ? (
              <select value={form.broker} onChange={e => setForm(f => ({ ...f, broker: e.target.value }))} className={inputClass}>
                {brokers.map(b => <option key={b.id} value={b.name}>{b.name}</option>)}
              </select>
            ) : (
              <input value={form.broker} onChange={e => setForm(f => ({ ...f, broker: e.target.value }))} className={inputClass} />
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelClass}>Activo</label>
            <TickerSearch
              value={form.asset}
              onChange={v => setForm(f => ({ ...f, asset: v }))}
              currency={brokers.find(b => b.name === form.broker)?.currency || 'USDT'}
            />
          </div>
          <div>
            <label className={labelClass}>Tipo</label>
            <input value={form.op_type} onChange={e => setForm(f => ({ ...f, op_type: e.target.value }))} className={inputClass} placeholder="LONG, SHORT, Futuros…" />
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={labelClass}>P. Entrada</label>
            <input type="number" step="any" value={form.entry_price} onChange={e => setForm(f => ({ ...f, entry_price: e.target.value }))} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>P. Salida</label>
            <input type="number" step="any" value={form.exit_price} onChange={e => setForm(f => ({ ...f, exit_price: e.target.value }))} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Cantidad</label>
            <input type="number" step="any" value={form.quantity} onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))} className={inputClass} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelClass}>P&L (USD)</label>
            <input
              type="number"
              step="any"
              value={form.pnl_usd}
              onChange={e => setForm(f => ({ ...f, pnl_usd: e.target.value }))}
              className={inputClass}
              placeholder="Ej: 150 o -80"
            />
          </div>
          <div>
            <label className={labelClass}>Comisiones</label>
            <input type="number" step="any" value={form.commissions} onChange={e => setForm(f => ({ ...f, commissions: e.target.value }))} className={inputClass} placeholder="0" />
          </div>
        </div>
        <p className="text-[12.5px] text-ink-2 leading-tight font-medium">
          Atajo: si solo querés registrar la ganancia/pérdida (sin precios ni cantidad), completá únicamente P&L USD.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-[12.5px] text-ink-3 hover:text-ink-0 px-3 py-1.5 transition-colors font-medium">
            Cancelar
          </button>
          <button onClick={onSave} className="text-[12.5px] bg-rendi-pos/10 text-rendi-pos hover:bg-rendi-pos/15 border border-rendi-pos/30 px-3 py-1.5 rounded-sm transition-colors font-medium">
            Guardar
          </button>
        </div>
      </div>
    </Modal>
  )
}


// ═══════════════════════════════════════════════════════════════════════════
// MOVEMENTS VIEW — historial unificado (trades + cash flows + dividendos + ...)
// ═══════════════════════════════════════════════════════════════════════════
// Consume /api/movements (endpoint que junta operations + import_normalized_tx
// + monthly_entries en una lista cronológica). Filtros por tipo y broker.
// KPIs adaptativos según el filtro de tipo seleccionado.
//
// Sources del backend:
//   • 'manual' → operations / positions cargadas a mano (editables, pero
//     desde acá NO editamos — el user va a /operaciones?tab=trades)
//   • 'import' → vinieron de un CSV (read-only)
//   • 'monthly' → depósitos/retiros agregados mensualmente en /mensual

const MOVEMENT_TYPES = [
  { id: 'all',      label: 'Todos',        icon: SlidersHorizontal },
  { id: 'BUY',      label: 'Compras',      icon: ArrowUpRight,      tone: 'pos' },
  { id: 'SELL',     label: 'Ventas',       icon: ArrowDownRight,    tone: 'neg' },
  { id: 'DEPOSIT',  label: 'Depósitos',    icon: ArrowDownToLine,   tone: 'pos' },
  { id: 'WITHDRAW', label: 'Retiros',      icon: ArrowUpFromLine,   tone: 'neg' },
  { id: 'DIVIDEND', label: 'Dividendos',   icon: Coins,             tone: 'pos' },
  { id: 'INTEREST', label: 'Intereses',    icon: Coins,             tone: 'pos' },
  { id: 'FEE',      label: 'Comisiones',   icon: Receipt,           tone: 'neg' },
]

const TYPE_META = {
  BUY:      { label: 'Compra',     Icon: ArrowUpRight,     color: 'text-data-blue' },
  SELL:     { label: 'Venta',      Icon: ArrowDownRight,   color: 'text-data-violet' },
  DEPOSIT:  { label: 'Depósito',   Icon: ArrowDownToLine,  color: 'text-rendi-pos' },
  WITHDRAW: { label: 'Retiro',     Icon: ArrowUpFromLine,  color: 'text-rendi-warn' },
  DIVIDEND: { label: 'Dividendo',  Icon: Coins,            color: 'text-rendi-pos' },
  INTEREST: { label: 'Interés',    Icon: Coins,            color: 'text-rendi-pos' },
  FEE:      { label: 'Comisión',   Icon: Receipt,          color: 'text-ink-3' },
}

const MOV_PAGE_SIZE = 50

// Opciones del pill "Agrupar". 'asset' es el default (reduce ruido: 1 fila por
// activo). 'month' agrupa por YYYY-MM (útil para impuestos). 'none' = la lista
// plana cronológica de siempre.
const GROUP_OPTIONS = [
  { id: 'asset', label: 'Activo' },
  { id: 'month', label: 'Mes' },
  { id: 'none',  label: 'Ninguno' },
]

const MONTH_NAMES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

// Etiqueta legible de un YYYY-MM → "Mar 2026". Si no parsea, devuelve el raw.
function prettyMonth(ym) {
  if (!ym || ym.length < 7) return ym || 'Sin fecha'
  const [y, m] = ym.split('-')
  const idx = parseInt(m, 10) - 1
  return idx >= 0 && idx < 12 ? `${MONTH_NAMES[idx]} ${y}` : ym
}

// P&L realizado de un movimiento. Solo las ventas (SELL, vía operations) traen
// `pnl_usd` stampeado; el resto de los tipos (BUY/DEPOSIT/WITHDRAW/DIVIDEND/
// INTEREST/FEE) no aportan P&L realizado y suman 0. Los dividendos/intereses
// importados NO traen pnl_usd (su monto vive en amount_usd como ingreso), así
// que acá cuentan 0 — el P&L realizado refleja estrictamente trades cerrados.
function movPnl(m) {
  return typeof m.pnl_usd === 'number' ? m.pnl_usd : 0
}

// Agrupa movimientos (ya filtrados) por activo o por mes. Devuelve grupos
// { key, label, sublabel, rows, count, pnl } ordenados. Las filas de cada
// grupo van por fecha desc (las movements ya vienen ordenadas así del backend,
// pero re-ordenamos para robustez). El P&L del grupo suma movPnl de sus rows.
function buildGroups(rows, groupBy) {
  const map = new Map()
  for (const m of rows) {
    let key, label, sublabel
    if (groupBy === 'month') {
      key = (m.date || '').slice(0, 7) || 'Sin fecha'
      label = prettyMonth(key)
      sublabel = null
    } else {
      // 'asset' — ops sin activo (depósitos/retiros/conversiones) caen en un
      // grupo "Sin activo" para no perderlas.
      key = (m.asset || '').trim() || '__no_asset__'
      label = key === '__no_asset__' ? 'Sin activo' : key
      sublabel = null
    }
    if (!map.has(key)) map.set(key, { key, label, rows: [], pnl: 0, brokers: new Set() })
    const g = map.get(key)
    g.rows.push(m)
    g.pnl += movPnl(m)
    if (m.broker) g.brokers.add(m.broker)
  }
  const groups = [...map.values()].map(g => ({
    key: g.key,
    label: g.label,
    rows: g.rows.slice().sort((a, b) => (b.date || '').localeCompare(a.date || '')),
    count: g.rows.length,
    pnl: g.pnl,
    brokers: [...g.brokers],
  }))
  // Orden de los grupos: por mes → cronológico desc (más reciente arriba, igual
  // que la lista plana). Por activo → P&L realizado desc (lo más relevante
  // arriba), con desempate por # de movimientos y luego alfabético.
  if (groupBy === 'month') {
    groups.sort((a, b) => b.key.localeCompare(a.key))
  } else {
    groups.sort((a, b) => (b.pnl - a.pnl) || (b.count - a.count) || a.label.localeCompare(b.label))
  }
  return groups
}

function MovementsView() {
  // Fase B: formatter atado al toggle global ARS/USD. Lo bajamos a
  // computeMovementKpis y a MovementRow vía props para evitar shadow.
  // Phase C audit fix H1: el HM (historical money) se usa en MovementRow
  // para cada fila individual (cada movimiento tiene su date). Los KPIs
  // agregados (totales / promedios) usan tcBlue actual via `money` porque
  // mezclan movimientos de múltiples fechas.
  const money = useMoneyFormat()
  const histMoney = useHistoricalMoney()
  const fmtUsd = (v) => money.fmtMoney(v, { signed: false })
  // Variante con signo para el P&L realizado de cada grupo (modo agrupado).
  const fmtUsdSigned = (v) => money.fmtMoney(v, { signed: true })
  const [movements, setMovements] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterType, setFilterType] = useState('all')
  const [filterBroker, setFilterBroker] = useState('all')
  const [filterYear, setFilterYear] = useState('all')
  const [page, setPage] = useState(0)
  // Agrupación de la lista. 'asset' por defecto (reduce ruido). Persistido en
  // localStorage para respetar la preferencia del user entre sesiones.
  const [groupBy, setGroupBy] = useState(() => localStorage.getItem('rendi_movements_group') || 'asset')
  useEffect(() => { localStorage.setItem('rendi_movements_group', groupBy) }, [groupBy])
  // Grupos expandidos (Set de keys). Mismo patrón que expandedTickers en
  // Positions: click en la fila-resumen togglea el despliegue de sus filas.
  const [expandedGroups, setExpandedGroups] = useState(() => new Set())
  function toggleGroup(key) {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
      return next
    })
  }

  const [deletingId, setDeletingId] = useState(null)

  async function load() {
    setLoading(true)
    try {
      setMovements(await api.get('/movements') || [])
      setError(null)
    } catch (ex) {
      setError(ex?.message || 'No pudimos cargar los movimientos.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  // Borrado de UN movimiento (cash-flows) con cascada backend. Confirma → borra →
  // refetch de /movements. Los KPIs de la página se recomputan solos; el gráfico
  // del dashboard/evolución se corrige al navegar/recargar (lo lee del backend).
  async function handleDelete(m) {
    const label = { DEPOSIT: 'depósito', WITHDRAW: 'retiro', DIVIDEND: 'dividendo', INTEREST: 'interés', FEE: 'comisión', IMPUESTO: 'impuesto' }[m.type] || 'movimiento'
    const monto = m.amount_usd ? ` de ${fmtUsd(m.amount_usd)}` : ''
    if (!window.confirm(`¿Borrar este ${label}${monto}?\n\nSe recalculan tu cartera, el capital aportado y la evolución. No se puede deshacer.`)) return
    setDeletingId(m.id)
    try {
      await api.delete(`/movements/${encodeURIComponent(m.id)}`)
      await load()
    } catch (ex) {
      alert(ex?.message || 'No se pudo borrar el movimiento.')
    } finally {
      setDeletingId(null)
    }
  }

  // Reset página al cambiar filtros o el modo de agrupación.
  useEffect(() => { setPage(0) }, [filterType, filterBroker, filterYear, groupBy])

  const filtered = useMemo(() => {
    return movements.filter(m => {
      if (filterType !== 'all' && m.type !== filterType) return false
      if (filterBroker !== 'all' && m.broker !== filterBroker) return false
      if (filterYear !== 'all' && !(m.date || '').startsWith(filterYear)) return false
      return true
    })
  }, [movements, filterType, filterBroker, filterYear])

  // KPIs adaptativos según filtro. fmtUsd se pasa explícito para que
  // computeMovementKpis no dependa del scope module-level (que ya quedó
  // aliased a fmtUsdRaw — desconectado del toggle global).
  // Comisiones TOTALES del scope broker/año (SIN filtrar por tipo, para que
  // clickear el chip COMISIONES no cambie el número): FEE explícitos (amount_usd)
  // + comisión EMBEBIDA en cada trade (fees_usd — Balanz la trae dentro del
  // Importe). Antes la card sumaba solo los FEE explícitos → subcontaba fuerte
  // (santi veía US$24 en vez de ~US$527). Espeja /api/insights/commissions.
  const commTotalUsd = useMemo(() => {
    const scoped = movements.filter(m =>
      (filterBroker === 'all' || m.broker === filterBroker) &&
      (filterYear === 'all' || (m.date || '').startsWith(filterYear)))
    const loose = scoped.reduce((s, m) => m.type === 'FEE' ? s + (m.amount_usd || 0) : s, 0)
    const embedded = scoped.reduce((s, m) =>
      (m.type !== 'FEE' && m.type !== 'IMPUESTO') ? s + (m.fees_usd || 0) : s, 0)
    return loose + embedded
  }, [movements, filterBroker, filterYear])

  const kpis = useMemo(() => computeMovementKpis(filtered, filterType, fmtUsd, commTotalUsd), [filtered, filterType, fmtUsd, commTotalUsd])

  const brokersAvailable = useMemo(() => {
    const set = new Set(movements.map(m => m.broker).filter(Boolean))
    return [...set].sort()
  }, [movements])

  const yearsAvailable = useMemo(() => {
    const set = new Set(movements.map(m => (m.date || '').slice(0, 4)).filter(Boolean))
    return [...set].sort().reverse()
  }, [movements])

  const grouped = groupBy !== 'none'

  // Grupos por activo / mes (sobre lo YA filtrado — filtramos y después
  // agrupamos, como pide el spec). Vacío en modo 'none'.
  const groups = useMemo(
    () => (grouped ? buildGroups(filtered, groupBy) : []),
    [filtered, groupBy, grouped]
  )

  // DECISIÓN PAGINACIÓN: la paginación con MOV_PAGE_SIZE aplica SOLO en modo
  // 'none' (lista plana). En modo agrupado mostramos TODOS los grupos sin
  // paginar — los grupos suelen ser pocos (1 por activo o 1 por mes) y paginar
  // sobre grupos partiría la tabla-resumen de forma confusa. Las filas de
  // detalle dentro de cada grupo tampoco se paginan (se ven al expandir).
  const totalPages = Math.max(1, Math.ceil(filtered.length / MOV_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages - 1)
  const pageRows = grouped
    ? filtered
    : filtered.slice(currentPage * MOV_PAGE_SIZE, (currentPage + 1) * MOV_PAGE_SIZE)

  if (loading) {
    return <div className="text-center py-10 text-ink-3 text-sm" aria-live="polite">Cargando movimientos…</div>
  }
  if (error) {
    return <div className="border border-rendi-neg/30 bg-rendi-neg/[0.06] rounded p-4 text-sm text-rendi-neg">{error}</div>
  }

  return (
    <>
      {/* KPI strip adaptativo */}
      <div className="border border-line rounded bg-bg-1 flex flex-wrap mb-4">
        {kpis.map((k, i) => (
          <KpiCell key={k.label} first={i === 0} label={k.label} value={k.value} sub={k.sub} tone={k.tone} />
        ))}
      </div>

      {/* Selector de tipo (pills) — escaneable */}
      <div className="flex items-center gap-1.5 flex-wrap mb-3">
        {MOVEMENT_TYPES.map(t => {
          const Icon = t.icon
          const count = t.id === 'all' ? movements.length : movements.filter(m => m.type === t.id).length
          if (t.id !== 'all' && count === 0) return null
          const active = filterType === t.id
          return (
            <button
              key={t.id}
              onClick={() => setFilterType(t.id)}
              className={`inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps px-2.5 py-1.5 rounded-sm border transition-colors ${
                active
                  ? 'border-data-violet/40 bg-data-violet/10 text-data-violet'
                  : 'border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3'
              }`}
            >
              <Icon size={11} strokeWidth={2} aria-hidden="true" />
              {t.label}
              <span className="ml-1 tabular text-[10px] opacity-70">{count}</span>
            </button>
          )
        })}
      </div>

      {/* Filtros secundarios (broker, año) + pill Agrupar */}
      <div className="flex items-center gap-2 flex-wrap mb-3">
        {brokersAvailable.length > 1 && (
          <select
            value={filterBroker}
            onChange={e => setFilterBroker(e.target.value)}
            className="text-[12.5px] bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-ink-2 font-medium"
          >
            <option value="all">Todos los brokers</option>
            {brokersAvailable.map(b => <option key={b} value={b}>{b}</option>)}
          </select>
        )}
        {yearsAvailable.length > 1 && (
          <select
            value={filterYear}
            onChange={e => setFilterYear(e.target.value)}
            className="text-[12.5px] bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-ink-2 font-medium"
          >
            <option value="all">Todos los años</option>
            {yearsAvailable.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        )}
        <FilterPill label="Agrupar" value={groupBy} onChange={setGroupBy} options={GROUP_OPTIONS} />
        <span className="text-[11px] text-ink-3 font-mono">
          {filtered.length === movements.length
            ? `${movements.length} movimientos`
            : `${filtered.length} de ${movements.length}`}
        </span>
      </div>

      {/* Tabla */}
      {filtered.length === 0 ? (
        <EmptyState
          icon={<Repeat size={18} />}
          title="No hay movimientos"
          description="No se encontraron movimientos con los filtros aplicados."
        />
      ) : (
        <div className="border border-line rounded overflow-x-auto bg-bg-1">
          <table className="w-full text-sm">
            <thead className="bg-bg-2 text-ink-3 text-[12px] font-medium">
              <tr>
                <th className="text-left px-3 py-2">Fecha</th>
                <th className="text-left px-3 py-2">Tipo</th>
                <th className="text-left px-3 py-2">Broker</th>
                <th className="text-left px-3 py-2">Activo</th>
                <th className="text-right px-3 py-2">Cant.</th>
                <th className="text-right px-3 py-2">Precio</th>
                <th className="text-right px-3 py-2">Monto {money.currency}</th>
                <th className="text-left px-3 py-2">Notas</th>
                <th className="px-3 py-2 w-8" aria-label="Acciones"></th>
              </tr>
            </thead>
            <tbody>
              {!grouped && pageRows.map(m => (
                <MovementRow key={m.id} m={m} onDelete={handleDelete} deleting={deletingId === m.id} />
              ))}
              {grouped && groups.map(g => {
                const isOpen = expandedGroups.has(g.key)
                return (
                  <Fragment key={g.key}>
                    <MovementGroupRow
                      group={g}
                      groupBy={groupBy}
                      isOpen={isOpen}
                      onToggle={() => toggleGroup(g.key)}
                      fmtPnl={fmtUsdSigned}
                    />
                    {isOpen && g.rows.map(m => (
                      <MovementRow key={m.id} m={m} indent onDelete={handleDelete} deleting={deletingId === m.id} />
                    ))}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination — solo en modo lista plana (ver DECISIÓN PAGINACIÓN). */}
      {!grouped && totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 text-xs text-ink-3">
          <span className="font-mono tabular">Página {currentPage + 1} de {totalPages}</span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={currentPage === 0}
              className="p-1.5 rounded-sm border border-line bg-bg-2 hover:bg-bg-3 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={12} />
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={currentPage >= totalPages - 1}
              className="p-1.5 rounded-sm border border-line bg-bg-2 hover:bg-bg-3 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronRight size={12} />
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// Compute KPI strip dinámico. Cada filtro de tipo tiene su set propio de
// métricas relevantes.
//
// SEMÁNTICA "Aportado Neto" (vista all):
// El KPI principal cuando el user mira "Todos los movimientos" es el NETO
// (deposits − withdrawals), no el bruto de cada lado. Razón:
//   • Algunos brokers clasifican P2P trades como DEPOSIT en el CSV. Un user
//     que hace flips (compra USDT con ARS + venta inmediata por ARS) genera
//     $X en deposits Y $X en withdrawals — el bruto infla 2× sin que cambie
//     el capital aportado. El NETO refleja capital nuevo real.
//   • Coincide exactamente con "Capital Aportado" del Dashboard, evitando
//     que el user vea dos números distintos en pantallas distintas.
// El bruto sigue accesible filtrando por DEPÓSITOS o RETIROS individualmente
// (en esa vista mostramos bruto + promedio, que es lo que tiene sentido ahí).
function computeMovementKpis(rows, filterType, fmtUsd, commTotalUsd = 0) {
  const sumByType = (t) => rows.filter(r => r.type === t).reduce((s, r) => s + (r.amount_usd || 0), 0)
  const countByType = (t) => rows.filter(r => r.type === t).length

  if (filterType === 'DEPOSIT' || filterType === 'WITHDRAW') {
    const t = filterType
    const total = sumByType(t)
    const count = countByType(t)
    return [
      {
        label: `Total ${t === 'DEPOSIT' ? 'depositado' : 'retirado'}`,
        value: fmtUsd(total),
        tone: t === 'DEPOSIT' ? 'pos' : 'neg',
        sub: `${count} eventos · bruto histórico`,
      },
      {
        label: 'Promedio',
        value: count > 0 ? fmtUsd(total / count) : '—',
        sub: 'por evento',
      },
    ]
  }
  if (filterType === 'DIVIDEND' || filterType === 'INTEREST') {
    return [
      { label: `Total ${filterType === 'DIVIDEND' ? 'dividendos' : 'intereses'}`, value: fmtUsd(sumByType(filterType)), tone: 'pos', sub: `${countByType(filterType)} pagos` },
    ]
  }
  if (filterType === 'FEE') {
    return [
      { label: 'Total comisiones', value: fmtUsd(commTotalUsd), tone: commTotalUsd > 0 ? 'neg' : null, sub: `${countByType('FEE')} explícitas + embebidas en trades` },
    ]
  }

  // Vista "Todos" o por trade type — KPI principal es el NETO
  const dep = sumByType('DEPOSIT')
  const wit = sumByType('WITHDRAW')
  const neto = dep - wit
  const depCount = countByType('DEPOSIT')
  const witCount = countByType('WITHDRAW')
  const dividendos = sumByType('DIVIDEND') + sumByType('INTEREST')
  const comisiones = commTotalUsd  // FEE explícitos + embebidas en trades (no solo los FEE sueltos)
  return [
    {
      label: 'Aportado neto',
      value: fmtUsd(neto),
      tone: neto > 0 ? 'pos' : neto < 0 ? 'neg' : null,
      sub: `${depCount} depósitos · ${witCount} retiros`,
    },
    { label: 'Cobrado',    value: fmtUsd(dividendos), tone: dividendos > 0 ? 'pos' : null, sub: 'dividendos + intereses' },
    { label: 'Comisiones', value: fmtUsd(comisiones), tone: comisiones > 0 ? 'neg' : null, sub: 'fees totales (incl. embebidas)' },
  ]
}

// indent: cuando la fila es detalle de un grupo (modo agrupado), la atenuamos
// e indentamos la primera celda con un marquito "└" — mismo recurso visual que
// los lotes en Positions.
// Tipos borrables en v1 (cash-flows). Compras/ventas van a fase futura (rebuild
// FIFO) → sin tacho. Alineado con _DELETABLE_CASHFLOW_TYPES del backend.
const DELETABLE_MOVEMENT_TYPES = ['DEPOSIT', 'WITHDRAW', 'DIVIDEND', 'INTEREST', 'FEE', 'IMPUESTO']

function MovementRow({ m, indent = false, onDelete, deleting = false }) {
  // Phase C (audit fix H1): cada movimiento usa SU PROPIO FX histórico para
  // la conversión a ARS. m.fx_to_usd (si stampeado) > lookup por m.date >
  // tcBlue actual. Esto evita que un retiro de $1000 USD en 2024 (blue era
  // 1100) se muestre hoy como $1.466.000 ARS (al blue actual ~1466) cuando
  // en realidad fueron ~$1.100.000 ARS al tipo de cambio del momento.
  const histMoney = useHistoricalMoney()
  const fmtUsd = (v) => histMoney.fmtMoneyAt(v, {
    stampedFx: m.fx_to_usd,
    dateIso: m.date,
    signed: false,
  })
  const meta = TYPE_META[m.type] || { label: m.type, Icon: Repeat, color: 'text-ink-3' }
  const { Icon } = meta
  const isPositive = ['DEPOSIT', 'DIVIDEND', 'INTEREST'].includes(m.type)
  const isNegative = ['WITHDRAW', 'FEE'].includes(m.type)
  const amountClass = isPositive ? 'text-rendi-pos' : isNegative ? 'text-rendi-neg' : 'text-ink-1'
  return (
    <tr className={`border-t border-line/60 hover:bg-bg-2/40 ${indent ? 'bg-bg-2/15' : ''}`}>
      <td className={`px-3 py-2 text-ink-2 tabular text-xs ${indent ? 'pl-6 opacity-75' : ''}`}>
        {indent && <span className="text-ink-3 font-mono select-none mr-1" title="Detalle">└</span>}
        {m.date || '—'}
        {m.approx_date && <span className="ml-1 text-[9px] text-ink-3" title="Fecha aproximada (agregado mensual)">~</span>}
      </td>
      <td className="px-3 py-2">
        <span className={`inline-flex items-center gap-1 text-xs ${meta.color}`}>
          <Icon size={11} strokeWidth={2} aria-hidden="true" />
          {meta.label}
        </span>
      </td>
      <td className="px-3 py-2 text-ink-3 text-xs">{m.broker || '—'}</td>
      <td className="px-3 py-2 font-medium text-ink-0 text-xs">{m.asset || '—'}</td>
      <td className="px-3 py-2 text-right font-mono text-ink-2 tabular text-xs">
        {m.quantity != null ? Number(m.quantity).toLocaleString('es-AR', { maximumFractionDigits: 4 }) : '—'}
      </td>
      <td className="px-3 py-2 text-right font-mono text-ink-2 tabular text-xs">
        {m.unit_price != null ? Number(m.unit_price).toLocaleString('es-AR', { maximumFractionDigits: 2 }) : '—'}
      </td>
      <td className={`px-3 py-2 text-right font-mono font-medium tabular ${amountClass}`}>
        {fmtUsd(m.amount_usd || 0)}
      </td>
      <td className="px-3 py-2 text-ink-3 text-xs max-w-xs truncate" title={m.notes}>
        {m.notes || (m.source === 'monthly' ? 'Agregado mensual' : m.source === 'import' ? 'Desde import CSV' : '')}
      </td>
      <td className="px-2 py-2 text-right">
        {onDelete && DELETABLE_MOVEMENT_TYPES.includes(m.type) && (
          <button
            type="button"
            onClick={() => onDelete(m)}
            disabled={deleting}
            title="Borrar movimiento"
            aria-label="Borrar movimiento"
            className="p-1 rounded-sm text-ink-3 hover:text-rendi-neg hover:bg-rendi-neg/10 disabled:opacity-40 disabled:cursor-wait"
          >
            <Trash2 size={13} strokeWidth={1.75} aria-hidden="true" />
          </button>
        )}
      </td>
    </tr>
  )
}

// Fila-resumen de un grupo (modo agrupado por activo o por mes). Click → toggle
// del despliegue de sus movimientos. Muestra: etiqueta del grupo (ticker o mes)
// · broker(s) · # de movimientos · P&L realizado total con flecha ↗/↘. El P&L
// se formatea con el toggle global vía fmtUsd (tcBlue actual — el grupo mezcla
// movimientos de distintas fechas, igual que los KPIs agregados de arriba).
function MovementGroupRow({ group, groupBy, isOpen, onToggle, fmtPnl }) {
  const { label, count, pnl, brokers } = group
  const Chevron = isOpen ? ChevronUp : ChevronDown
  const hasPnl = pnl !== 0
  const Arrow = pnl > 0 ? ArrowUpRight : pnl < 0 ? ArrowDownRight : null
  const brokersLabel = brokers.length === 0
    ? '—'
    : brokers.length <= 2
    ? brokers.join(' · ')
    : `${brokers.length} brokers`
  return (
    <tr
      className="border-t border-line/60 bg-bg-2/40 hover:bg-bg-2/60 cursor-pointer transition-colors"
      onClick={onToggle}
    >
      {/* Etiqueta del grupo + chevron — ocupa Fecha + Tipo */}
      <td className="px-3 py-2.5" colSpan={2}>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onToggle() }}
          className="inline-flex items-center gap-1.5 text-ink-0 font-semibold text-sm"
          aria-expanded={isOpen}
        >
          <Chevron size={13} strokeWidth={2} className="text-ink-3" aria-hidden="true" />
          {label}
        </button>
      </td>
      {/* Broker(s) */}
      <td className="px-3 py-2.5 text-ink-3 text-xs">
        {groupBy === 'asset' ? brokersLabel : '—'}
      </td>
      {/* # movimientos — bajo "Activo" */}
      <td className="px-3 py-2.5 text-ink-2 text-xs" colSpan={3}>
        <span className="text-[12.5px] font-medium">
          {count} {count === 1 ? 'movimiento' : 'movimientos'}
        </span>
      </td>
      {/* P&L realizado total con flecha — bajo "Monto" */}
      <td className={`px-3 py-2.5 text-right font-mono font-semibold tabular ${colorClass(hasPnl ? pnl : null)}`}>
        <span className="inline-flex items-center gap-1 justify-end">
          {Arrow && <Arrow size={13} strokeWidth={2.25} aria-hidden="true" />}
          {hasPnl ? fmtPnl(pnl) : '—'}
        </span>
      </td>
      {/* Notas — hint del P&L */}
      <td className="px-3 py-2.5 text-ink-3 text-[12px] font-medium">
        {hasPnl ? 'P&L realizado' : ''}
      </td>
    </tr>
  )
}
