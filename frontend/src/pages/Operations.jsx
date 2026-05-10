import { useEffect, useMemo, useState } from 'react'
import { Plus, Pencil, Trash2, ArrowUpRight, ArrowDownRight, Search, X } from 'lucide-react'
import Modal from '../components/Modal'
import TickerSearch from '../components/TickerSearch'
import DateInput from '../components/DateInput'
import { usd, pct, fmtUsd, pctSigned, colorClass } from '../utils/format'
import StatCard from '../components/StatCard'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import { api } from '../utils/api'

const EMPTY = { date: new Date().toISOString().slice(0, 10), broker: '', asset: '', op_type: '', entry_price: '', exit_price: '', quantity: '', pnl_usd: 0, pnl_pct: '', commissions: '' }

// El persister de imports guarda algunos op_type con strings verbosos
// (ej.: "CONVERSION IMPORT ARS→USDT"). Mapeamos a labels limpios para la UI.
function prettyOpType(raw) {
  if (!raw) return '—'
  const s = String(raw).trim()
  if (s.startsWith('CONVERSION IMPORT ARS→USDT') || s.startsWith('CONVERSION IMPORT ARS→USD')) {
    return 'Conversión ARS→USD'
  }
  if (s.startsWith('CONVERSION IMPORT USDT→ARS') || s.startsWith('CONVERSION IMPORT USD→ARS')) {
    return 'Conversión USD→ARS'
  }
  return s
}

export default function Operations() {
  const [ops, setOps] = useState([])
  const [brokers, setBrokers] = useState([])
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(EMPTY)
  // ── Filtros ────────────────────────────────────────────────────────────────
  const [filterAsset, setFilterAsset] = useState('')
  const [filterBroker, setFilterBroker] = useState('all')
  const [filterResult, setFilterResult] = useState('all') // all | wins | losses
  const [filterYear, setFilterYear] = useState('all')

  useEffect(() => {
    load()
    api.get('/brokers').then(b => { setBrokers(b); })
  }, [])

  async function load() {
    setOps(await api.get('/operations'))
  }

  function openAdd() {
    setForm({ ...EMPTY, broker: brokers[0]?.name ?? '' })
    setModal('add')
  }
  function openEdit(op) {
    setForm({ ...op, entry_price: op.entry_price ?? '', exit_price: op.exit_price ?? '', quantity: op.quantity ?? '', pnl_pct: op.pnl_pct ?? '', commissions: op.commissions ?? '' })
    setModal('edit')
  }

  async function save() {
    const body = {
      ...form,
      entry_price: form.entry_price !== '' ? +form.entry_price : null,
      exit_price: form.exit_price !== '' ? +form.exit_price : null,
      quantity: form.quantity !== '' ? +form.quantity : null,
      pnl_usd: +form.pnl_usd,
      pnl_pct: form.pnl_pct !== '' ? +form.pnl_pct : null,
      commissions: form.commissions !== '' ? +form.commissions : 0,
    }
    if (modal === 'edit') {
      await api.put(`/operations/${form.id}`, body)
    } else {
      await api.post('/operations', body)
    }
    setModal(null)
    load()
  }

  async function del(id) {
    if (!confirm('¿Eliminar esta operación? La acción no se puede deshacer.')) return
    await api.delete(`/operations/${id}`)
    load()
  }

  // KPIs (sobre todas las ops, no filtradas — los stats reflejan el total histórico)
  const totalPnl = ops.reduce((s, o) => s + (o.pnl_usd || 0), 0)
  const wins = ops.filter(o => o.pnl_usd > 0).length
  const losses = ops.filter(o => o.pnl_usd < 0).length
  const winRate = ops.length > 0 ? wins / ops.length : 0
  const bestTrade = ops.length > 0 ? Math.max(...ops.map(o => o.pnl_usd || 0)) : null

  // Años distintos para el selector
  const yearsAvailable = useMemo(() => {
    const set = new Set(ops.map(o => o.date?.slice(0, 4)).filter(Boolean))
    return [...set].sort().reverse()
  }, [ops])

  // Lista filtrada — solo afecta la tabla, no los KPIs
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

  const filtersActive = filterAsset || filterBroker !== 'all' || filterResult !== 'all' || filterYear !== 'all'

  const thClass = 'px-4 py-2 text-left text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider'
  const tdClass = 'px-4 py-2 text-sm'
  const inputClass = 'w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-900 dark:text-slate-200'

  return (
    <div className="page-shell">
      <PageHeader
        title="Operaciones cerradas"
        subtitle="Historial de operaciones realizadas con P&L realizado."
        action={
          <button onClick={openAdd} className="flex items-center gap-1.5 text-sm bg-rendi-accent text-white hover:bg-rendi-accent/90 px-3 py-2 rounded-md font-medium transition-colors">
            <Plus size={14} /> Nueva operación
          </button>
        }
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="P&L realizado" value={fmtUsd(totalPnl)} positive={totalPnl >= 0} sub="Resultado acumulado" />
        <StatCard label="Win rate" value={`${(winRate * 100).toFixed(0)}%`} sub={`${wins} ganadoras · ${losses} perdedoras`} positive={winRate >= 0.5} />
        <StatCard label="Operaciones" value={ops.length} sub="Total cerradas" />
        <StatCard label="Mejor operación" value={bestTrade != null ? fmtUsd(bestTrade) : '—'} sub={bestTrade != null && bestTrade > 0 ? 'P&L individual máximo' : '—'} positive={bestTrade != null && bestTrade > 0} />
      </div>

      {/* Filtros */}
      {ops.length > 0 && (
        <Card padding="sm" className="mb-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[180px]">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500 pointer-events-none" />
              <input
                value={filterAsset}
                onChange={e => setFilterAsset(e.target.value)}
                placeholder="Buscar activo (ej.: BTC, GGAL…)"
                className="w-full bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-700 rounded-md pl-8 pr-3 py-1.5 text-sm text-slate-900 dark:text-slate-200 focus:outline-none focus:border-rendi-accent/50 focus:ring-1 focus:ring-rendi-accent/20"
              />
            </div>
            <FilterPill label="Broker" value={filterBroker} onChange={setFilterBroker}
              options={[{ id: 'all', label: 'Todos' }, ...brokers.map(b => ({ id: b.name, label: b.name }))]} />
            <FilterPill label="Resultado" value={filterResult} onChange={setFilterResult}
              options={[{ id: 'all', label: 'Todos' }, { id: 'wins', label: 'Ganadoras' }, { id: 'losses', label: 'Perdedoras' }]} />
            <FilterPill label="Año" value={filterYear} onChange={setFilterYear}
              options={[{ id: 'all', label: 'Todos' }, ...yearsAvailable.map(y => ({ id: y, label: y }))]} />
            {filtersActive && (
              <button
                onClick={() => { setFilterAsset(''); setFilterBroker('all'); setFilterResult('all'); setFilterYear('all') }}
                className="inline-flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 px-2 py-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700/40 transition"
              >
                <X size={12} /> Limpiar
              </button>
            )}
            <span className="text-xs text-slate-500 dark:text-slate-400 ml-auto tabular">
              {filteredOps.length} de {ops.length}
            </span>
          </div>
        </Card>
      )}

      <Card padding="none">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700/50">
                <th className={thClass}>Fecha</th>
                <th className={thClass}>Broker</th>
                <th className={thClass}>Activo</th>
                <th className={thClass}>Tipo</th>
                <th className={thClass}>P. Entrada</th>
                <th className={thClass}>P. Salida</th>
                <th className={thClass}>Cant.</th>
                <th className={thClass}>P&L USD</th>
                <th className={thClass}>P&L %</th>
                <th className={thClass}>Resultado</th>
                <th className={thClass}></th>
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
                      <button onClick={openAdd} className="inline-flex items-center gap-1.5 text-sm bg-rendi-accent text-white hover:bg-rendi-accent/90 px-3 py-2 rounded-md font-medium transition">
                        <Plus size={14} /> Agregar manualmente
                      </button>
                    }
                  />
                </td></tr>
              )}
              {ops.length > 0 && filteredOps.length === 0 && (
                <tr><td colSpan={11}>
                  <EmptyState
                    title="Sin resultados para los filtros aplicados"
                    description="Ajustá los filtros para ampliar la búsqueda."
                    dense
                  />
                </td></tr>
              )}
              {filteredOps.map(op => (
                <tr key={op.id} className="border-b border-slate-100 dark:border-slate-700/20 hover:bg-slate-50 dark:hover:bg-slate-700/20">
                  <td className={`${tdClass} text-slate-600 dark:text-slate-300 tabular`}>{op.date}</td>
                  <td className={`${tdClass} text-slate-600 dark:text-slate-300`}>{op.broker}</td>
                  <td className={`${tdClass} font-semibold text-slate-800 dark:text-slate-200`}>{op.asset}</td>
                  <td className={`${tdClass} text-slate-500 dark:text-slate-400 text-xs`}>{prettyOpType(op.op_type)}</td>
                  <td className={`${tdClass} text-slate-500 dark:text-slate-400 tabular`}>{op.entry_price != null ? usd(op.entry_price) : '—'}</td>
                  <td className={`${tdClass} text-slate-500 dark:text-slate-400 tabular`}>{op.exit_price != null ? usd(op.exit_price) : '—'}</td>
                  <td className={`${tdClass} text-slate-500 dark:text-slate-400 tabular`}>{op.quantity ?? '—'}</td>
                  <td className={`${tdClass} font-semibold tabular ${colorClass(op.pnl_usd)}`}>
                    {op.pnl_usd > 0 ? '+' : op.pnl_usd < 0 ? '-' : ''}USD {usd(Math.abs(op.pnl_usd || 0))}
                  </td>
                  <td className={`${tdClass} tabular ${colorClass(op.pnl_pct)}`}>{op.pnl_pct != null ? pctSigned(op.pnl_pct / 100) : '—'}</td>
                  <td className={tdClass}><ResultPill pnl={op.pnl_usd} /></td>
                  <td className={tdClass}>
                    <div className="flex gap-2">
                      <button onClick={() => openEdit(op)} className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200" title="Editar" aria-label={`Editar operación ${op.asset}`}><Pencil size={13} aria-hidden="true" /></button>
                      <button onClick={() => del(op.id)} className="text-slate-400 hover:text-rendi-neg" title="Eliminar" aria-label={`Eliminar operación ${op.asset}`}><Trash2 size={13} aria-hidden="true" /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {modal && (
        <Modal title={modal === 'edit' ? 'Editar operación' : 'Nueva operación'} onClose={() => setModal(null)}>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Fecha</label>
                <DateInput value={form.date} onChange={v => setForm(f => ({ ...f, date: v }))} />
              </div>
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Broker</label>
                {brokers.length > 0 ? (
                  <select value={form.broker} onChange={e => setForm(f => ({ ...f, broker: e.target.value }))}
                    className={inputClass}>
                    {brokers.map(b => <option key={b.id} value={b.name}>{b.name}</option>)}
                  </select>
                ) : (
                  <input value={form.broker} onChange={e => setForm(f => ({ ...f, broker: e.target.value }))}
                    className={inputClass} />
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Activo</label>
                <TickerSearch
                  value={form.asset}
                  onChange={v => setForm(f => ({ ...f, asset: v }))}
                  currency={brokers.find(b => b.name === form.broker)?.currency || 'USDT'}
                />
              </div>
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Tipo</label>
                <input value={form.op_type} onChange={e => setForm(f => ({ ...f, op_type: e.target.value }))}
                  className={inputClass} placeholder="Ej.: LONG, SHORT, Futuros" />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">P. Entrada</label>
                <input type="number" step="any" value={form.entry_price} onChange={e => setForm(f => ({ ...f, entry_price: e.target.value }))}
                  className={inputClass} />
              </div>
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">P. Salida</label>
                <input type="number" step="any" value={form.exit_price} onChange={e => setForm(f => ({ ...f, exit_price: e.target.value }))}
                  className={inputClass} />
              </div>
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Cantidad</label>
                <input type="number" step="any" value={form.quantity} onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))}
                  className={inputClass} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">P&L (USD)</label>
                <input type="number" step="any" value={form.pnl_usd} onChange={e => setForm(f => ({ ...f, pnl_usd: e.target.value }))}
                  className={inputClass} />
              </div>
              <div>
                <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Comisiones</label>
                <input type="number" step="any" value={form.commissions} onChange={e => setForm(f => ({ ...f, commissions: e.target.value }))}
                  className={inputClass} placeholder="0" />
              </div>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setModal(null)} className="px-4 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200">Cancelar</button>
              <button onClick={save} className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 text-white rounded-md font-semibold transition">Guardar</button>
            </div>
          </div>
        </Modal>
      )}

    </div>
  )
}

function FilterPill({ label, value, onChange, options }) {
  // Compact native <select> styled to match — no extra deps, accessible by default.
  return (
    <label className="inline-flex items-center gap-1.5 text-xs">
      <span className="text-slate-500 dark:text-slate-400 font-medium">{label}</span>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-700 rounded-md px-2 py-1.5 text-xs text-slate-900 dark:text-slate-200 focus:outline-none focus:border-rendi-accent/50 focus:ring-1 focus:ring-rendi-accent/20"
      >
        {options.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>
  )
}

function ResultPill({ pnl }) {
  if (pnl == null || pnl === 0) {
    return <span className="text-slate-400 text-xs">—</span>
  }
  if (pnl > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
        <ArrowUpRight size={10} /> Ganancia
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20">
      <ArrowDownRight size={10} /> Pérdida
    </span>
  )
}
