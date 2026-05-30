// Operations — historial de operaciones cerradas (V2).
// ════════════════════════════════════════════════════════════════════════════
// Header operativo + KPI strip denso + filtros mono caps + tabla compacta.

import { useEffect, useMemo, useState } from 'react'
import { Plus, Pencil, Trash2, ArrowUpRight, ArrowDownRight, Search, X, SlidersHorizontal, ChevronLeft, ChevronRight, ArrowDownToLine, ArrowUpFromLine, Coins, Receipt, Repeat } from 'lucide-react'
import Modal from '../components/Modal'
import TickerSearch from '../components/TickerSearch'
import DateInput from '../components/DateInput'
import { usd, fmtUsd, pctSigned, colorClass } from '../utils/format'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import EmptyState from '../components/EmptyState'
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
    else await api.post('/operations', body)
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

  // Reset a página 0 cuando cambian los filtros o el dataset cambia de tamaño
  useEffect(() => {
    setPage(0)
  }, [filterAsset, filterBroker, filterResult, filterYear, ops.length])

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
              className="inline-flex items-center gap-1.5 text-xs font-mono uppercase tracking-caps bg-data-violet/10 text-data-violet hover:bg-data-violet/15 border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors"
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
          Solo trades
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
                  className="inline-flex items-center gap-1 text-[11px] font-mono uppercase tracking-caps text-ink-2 hover:text-ink-0 px-2 py-1 rounded-sm hover:bg-bg-2 transition-colors"
                >
                  <X size={11} strokeWidth={1.75} /> Limpiar
                </button>
              )}
            </div>
            <span className="text-[11px] font-mono uppercase tracking-caps text-ink-2 tabular">
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
              </div>
            </Panel>
          )}
        </div>
      )}

      <Panel padding="none">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-line text-[11px] font-mono uppercase tracking-label text-ink-2">
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
                      <button onClick={openAdd} className="inline-flex items-center gap-1.5 text-xs font-mono uppercase tracking-caps bg-data-violet/10 text-data-violet hover:bg-data-violet/15 border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors">
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
              {pagedOps.map(op => {
                const isWin = op.pnl_usd != null && op.pnl_usd > 0
                const isLoss = op.pnl_usd != null && op.pnl_usd < 0
                const ArrowIcon = isWin ? ArrowUpRight : isLoss ? ArrowDownRight : null
                const arrowColor = isWin ? 'text-rendi-pos' : isLoss ? 'text-rendi-neg' : 'text-ink-3'
                return (
                  <tr key={op.id} className="border-b border-line/30 hover:bg-bg-2/40 transition-colors">
                    <td className="px-4 py-2 text-xs font-mono tabular text-ink-2">{op.date}</td>
                    <td className="px-3 py-2 text-xs text-ink-2">{op.broker}</td>
                    <td className="px-3 py-2 text-sm font-medium text-ink-0">{op.asset}</td>
                    <td className="px-3 py-2 text-[11px] font-mono uppercase tracking-caps text-ink-3">{prettyOpType(op.op_type)}</td>
                    <td className="px-3 py-2 text-xs font-mono tabular text-right text-ink-2">{op.entry_price != null ? usd(op.entry_price) : '—'}</td>
                    <td className="px-3 py-2 text-xs font-mono tabular text-right text-ink-2">{op.exit_price != null ? usd(op.exit_price) : '—'}</td>
                    <td className="px-3 py-2 text-xs font-mono tabular text-right text-ink-2">{op.quantity ?? '—'}</td>
                    <td className={`px-3 py-2 text-sm font-mono tabular text-right font-medium ${colorClass(op.pnl_usd)}`}>
                      {op.pnl_usd == null
                        ? '—'
                        : `${op.pnl_usd > 0 ? '+' : op.pnl_usd < 0 ? '−' : ''}US$${usd(Math.abs(op.pnl_usd))}`}
                    </td>
                    <td className={`px-3 py-2 text-xs font-mono tabular text-right ${colorClass(op.pnl_pct)}`}>
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
                        <button onClick={() => openEdit(op)} className="text-ink-3 hover:text-ink-0 transition-colors p-1" title="Editar" aria-label={`Editar operación ${op.asset}`}>
                          <Pencil size={13} strokeWidth={1.75} aria-hidden="true" />
                        </button>
                        <button onClick={() => del(op.id)} className="text-ink-3 hover:text-rendi-neg transition-colors p-1" title="Eliminar" aria-label={`Eliminar operación ${op.asset}`}>
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
              })}
            </tbody>
          </table>
        </div>

        {/* Paginación */}
        {filteredOps.length > PAGE_SIZE && (
          <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-t border-line text-[11px] font-mono uppercase tracking-caps text-ink-3">
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
      <div className="text-[11px] font-mono uppercase tracking-label text-ink-2 leading-none">{label}</div>
      <div className={`mt-2 font-medium tabular num leading-none text-2xl tracking-tight ${valueColor}`}>{value}</div>
      <div className="text-[11px] font-mono text-ink-2 mt-1.5 leading-none truncate uppercase tracking-caps">{sub}</div>
    </div>
  )
}

function FilterPill({ label, value, onChange, options }) {
  return (
    <label className="inline-flex items-center gap-1.5 text-xs">
      <span className="text-[11px] font-mono uppercase tracking-caps text-ink-2">{label}</span>
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

// ─── Modal ───────────────────────────────────────────────────────────────────

function OpFormModal({ mode, form, setForm, brokers, onSave, onClose }) {
  const inputClass = 'w-full bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2'
  const labelClass = 'block text-[11px] font-mono uppercase tracking-label text-ink-2 mb-1'
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
        <p className="text-[11px] font-mono uppercase tracking-caps text-ink-2 leading-tight">
          Atajo: si solo querés registrar la ganancia/pérdida (sin precios ni cantidad), completá únicamente P&L USD.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-[11px] font-mono uppercase tracking-caps text-ink-3 hover:text-ink-0 px-3 py-1.5 transition-colors">
            Cancelar
          </button>
          <button onClick={onSave} className="text-[11px] font-mono uppercase tracking-caps bg-rendi-pos/10 text-rendi-pos hover:bg-rendi-pos/15 border border-rendi-pos/30 px-3 py-1.5 rounded-sm transition-colors">
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

function MovementsView() {
  const [movements, setMovements] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterType, setFilterType] = useState('all')
  const [filterBroker, setFilterBroker] = useState('all')
  const [filterYear, setFilterYear] = useState('all')
  const [page, setPage] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.get('/movements')
      .then(d => { if (!cancelled) setMovements(d || []) })
      .catch(ex => { if (!cancelled) setError(ex?.message || 'No pudimos cargar los movimientos.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  // Reset página al cambiar filtros
  useEffect(() => { setPage(0) }, [filterType, filterBroker, filterYear])

  const filtered = useMemo(() => {
    return movements.filter(m => {
      if (filterType !== 'all' && m.type !== filterType) return false
      if (filterBroker !== 'all' && m.broker !== filterBroker) return false
      if (filterYear !== 'all' && !(m.date || '').startsWith(filterYear)) return false
      return true
    })
  }, [movements, filterType, filterBroker, filterYear])

  // KPIs adaptativos según filtro
  const kpis = useMemo(() => computeMovementKpis(filtered, filterType), [filtered, filterType])

  const brokersAvailable = useMemo(() => {
    const set = new Set(movements.map(m => m.broker).filter(Boolean))
    return [...set].sort()
  }, [movements])

  const yearsAvailable = useMemo(() => {
    const set = new Set(movements.map(m => (m.date || '').slice(0, 4)).filter(Boolean))
    return [...set].sort().reverse()
  }, [movements])

  const totalPages = Math.max(1, Math.ceil(filtered.length / MOV_PAGE_SIZE))
  const currentPage = Math.min(page, totalPages - 1)
  const pageRows = filtered.slice(currentPage * MOV_PAGE_SIZE, (currentPage + 1) * MOV_PAGE_SIZE)

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

      {/* Filtros secundarios (broker, año) */}
      <div className="flex items-center gap-2 flex-wrap mb-3">
        {brokersAvailable.length > 1 && (
          <select
            value={filterBroker}
            onChange={e => setFilterBroker(e.target.value)}
            className="text-[11px] font-mono uppercase tracking-caps bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-ink-2"
          >
            <option value="all">Todos los brokers</option>
            {brokersAvailable.map(b => <option key={b} value={b}>{b}</option>)}
          </select>
        )}
        {yearsAvailable.length > 1 && (
          <select
            value={filterYear}
            onChange={e => setFilterYear(e.target.value)}
            className="text-[11px] font-mono uppercase tracking-caps bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-ink-2"
          >
            <option value="all">Todos los años</option>
            {yearsAvailable.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
        )}
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
            <thead className="bg-bg-2 text-ink-3 font-mono uppercase text-[10px] tracking-caps">
              <tr>
                <th className="text-left px-3 py-2">Fecha</th>
                <th className="text-left px-3 py-2">Tipo</th>
                <th className="text-left px-3 py-2">Broker</th>
                <th className="text-left px-3 py-2">Activo</th>
                <th className="text-right px-3 py-2">Cant.</th>
                <th className="text-right px-3 py-2">Precio</th>
                <th className="text-right px-3 py-2">Monto USD</th>
                <th className="text-left px-3 py-2">Notas</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map(m => (
                <MovementRow key={m.id} m={m} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
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
function computeMovementKpis(rows, filterType) {
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
      { label: 'Total comisiones', value: fmtUsd(sumByType('FEE')), tone: 'neg', sub: `${countByType('FEE')} comisiones` },
    ]
  }

  // Vista "Todos" o por trade type — KPI principal es el NETO
  const dep = sumByType('DEPOSIT')
  const wit = sumByType('WITHDRAW')
  const neto = dep - wit
  const depCount = countByType('DEPOSIT')
  const witCount = countByType('WITHDRAW')
  const dividendos = sumByType('DIVIDEND') + sumByType('INTEREST')
  const comisiones = sumByType('FEE')
  return [
    {
      label: 'Aportado neto',
      value: fmtUsd(neto),
      tone: neto > 0 ? 'pos' : neto < 0 ? 'neg' : null,
      sub: `${depCount} depósitos · ${witCount} retiros`,
    },
    { label: 'Cobrado',    value: fmtUsd(dividendos), tone: dividendos > 0 ? 'pos' : null, sub: 'dividendos + intereses' },
    { label: 'Comisiones', value: fmtUsd(comisiones), tone: comisiones > 0 ? 'neg' : null, sub: 'fees totales' },
  ]
}

function MovementRow({ m }) {
  const meta = TYPE_META[m.type] || { label: m.type, Icon: Repeat, color: 'text-ink-3' }
  const { Icon } = meta
  const isPositive = ['DEPOSIT', 'DIVIDEND', 'INTEREST'].includes(m.type)
  const isNegative = ['WITHDRAW', 'FEE'].includes(m.type)
  const amountClass = isPositive ? 'text-rendi-pos' : isNegative ? 'text-rendi-neg' : 'text-ink-1'
  return (
    <tr className="border-t border-line/60 hover:bg-bg-2/40">
      <td className="px-3 py-2 text-ink-2 tabular text-xs">
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
    </tr>
  )
}
