import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import Modal from '../components/Modal'
import { usd, pct, colorClass } from '../utils/format'
import StatCard from '../components/StatCard'

const EMPTY = { date: new Date().toISOString().slice(0, 10), broker: 'Binance', asset: '', op_type: '', entry_price: '', exit_price: '', quantity: '', pnl_usd: 0, pnl_pct: '' }

export default function Operations() {
  const [ops, setOps] = useState([])
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(EMPTY)

  useEffect(() => { load() }, [])

  async function load() {
    const data = await fetch('/api/operations').then(r => r.json())
    setOps(data)
  }

  function openAdd() { setForm(EMPTY); setModal('add') }
  function openEdit(op) {
    setForm({ ...op, entry_price: op.entry_price ?? '', exit_price: op.exit_price ?? '', quantity: op.quantity ?? '', pnl_pct: op.pnl_pct ?? '' })
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
    }
    if (modal === 'edit') {
      await fetch(`/api/operations/${form.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    } else {
      await fetch('/api/operations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    }
    setModal(null)
    load()
  }

  async function del(id) {
    if (!confirm('¿Eliminar operación?')) return
    await fetch(`/api/operations/${id}`, { method: 'DELETE' })
    load()
  }

  const totalPnl = ops.reduce((s, o) => s + (o.pnl_usd || 0), 0)
  const wins = ops.filter(o => o.pnl_usd > 0).length
  const losses = ops.filter(o => o.pnl_usd < 0).length
  const winRate = ops.length > 0 ? wins / ops.length : 0

  const thClass = 'px-4 py-2 text-left text-xs text-slate-500 font-medium'
  const tdClass = 'px-4 py-2 text-sm'

  return (
    <div className="pt-20 px-6 pb-10 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-slate-100">Operaciones Cerradas</h1>
        <button onClick={openAdd} className="flex items-center gap-1 text-sm bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 px-3 py-1.5 rounded-md transition-colors">
          <Plus size={14} /> Nueva operación
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="P&L Realizado Total" value={`$${usd(totalPnl)}`} positive={totalPnl >= 0} />
        <StatCard label="Win Rate" value={`${(winRate * 100).toFixed(0)}%`} sub={`${wins}G / ${losses}P`} positive={winRate >= 0.5} />
        <StatCard label="Operaciones" value={ops.length} />
        <StatCard label="Mejor trade" value={ops.length > 0 ? `$${usd(Math.max(...ops.map(o => o.pnl_usd)))}` : '—'} positive />
      </div>

      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className={thClass}>Fecha</th>
                <th className={thClass}>Broker</th>
                <th className={thClass}>Activo</th>
                <th className={thClass}>Tipo</th>
                <th className={thClass}>P. Entrada</th>
                <th className={thClass}>P. Salida</th>
                <th className={thClass}>Cant.</th>
                <th className={thClass}>P&L $</th>
                <th className={thClass}>P&L %</th>
                <th className={thClass}>Resultado</th>
                <th className={thClass}></th>
              </tr>
            </thead>
            <tbody>
              {ops.length === 0 && (
                <tr><td colSpan={11} className="px-4 py-8 text-center text-slate-500">Sin operaciones cerradas aún.</td></tr>
              )}
              {ops.map(op => (
                <tr key={op.id} className="border-b border-slate-700/20 hover:bg-slate-700/20">
                  <td className={`${tdClass} text-slate-300`}>{op.date}</td>
                  <td className={`${tdClass} text-slate-300`}>{op.broker}</td>
                  <td className={`${tdClass} font-semibold text-slate-200`}>{op.asset}</td>
                  <td className={`${tdClass} text-slate-400 text-xs`}>{op.op_type || '—'}</td>
                  <td className={`${tdClass} text-slate-400`}>{op.entry_price != null ? usd(op.entry_price) : '—'}</td>
                  <td className={`${tdClass} text-slate-400`}>{op.exit_price != null ? usd(op.exit_price) : '—'}</td>
                  <td className={`${tdClass} text-slate-400`}>{op.quantity ?? '—'}</td>
                  <td className={`${tdClass} font-semibold ${colorClass(op.pnl_usd)}`}>
                    {op.pnl_usd > 0 ? '+' : ''}{usd(op.pnl_usd)}
                  </td>
                  <td className={`${tdClass} ${colorClass(op.pnl_pct)}`}>{op.pnl_pct != null ? pct(op.pnl_pct / 100) : '—'}</td>
                  <td className={tdClass}>
                    {op.pnl_usd > 0
                      ? <span className="text-emerald-400 text-xs font-medium">✅ GANANCIA</span>
                      : op.pnl_usd < 0
                      ? <span className="text-red-400 text-xs font-medium">❌ PÉRDIDA</span>
                      : <span className="text-slate-400 text-xs">—</span>
                    }
                  </td>
                  <td className={tdClass}>
                    <div className="flex gap-2">
                      <button onClick={() => openEdit(op)} className="text-slate-400 hover:text-slate-200"><Pencil size={13} /></button>
                      <button onClick={() => del(op.id)} className="text-slate-400 hover:text-red-400"><Trash2 size={13} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {modal && (
        <Modal title={modal === 'edit' ? 'Editar operación' : 'Nueva operación'} onClose={() => setModal(null)}>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Fecha</label>
                <input type="date" value={form.date} onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Broker</label>
                <input value={form.broker} onChange={e => setForm(f => ({ ...f, broker: e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Activo</label>
                <input value={form.asset} onChange={e => setForm(f => ({ ...f, asset: e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" placeholder="BTC/USDT" />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Tipo</label>
                <input value={form.op_type} onChange={e => setForm(f => ({ ...f, op_type: e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" placeholder="LONG Futuros" />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">P. Entrada</label>
                <input type="number" step="any" value={form.entry_price} onChange={e => setForm(f => ({ ...f, entry_price: e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">P. Salida</label>
                <input type="number" step="any" value={form.exit_price} onChange={e => setForm(f => ({ ...f, exit_price: e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Cantidad</label>
                <input type="number" step="any" value={form.quantity} onChange={e => setForm(f => ({ ...f, quantity: e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" />
              </div>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">P&L (USD)</label>
              <input type="number" step="any" value={form.pnl_usd} onChange={e => setForm(f => ({ ...f, pnl_usd: e.target.value }))}
                className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button onClick={() => setModal(null)} className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200">Cancelar</button>
              <button onClick={save} className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-md font-medium">Guardar</button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
