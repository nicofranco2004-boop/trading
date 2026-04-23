import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import Modal from '../components/Modal'
import { usd, ars, pct, colorClass, MONTHS } from '../utils/format'

const EMPTY = { year: 2026, month: 1, broker: 'global', deposits: 0, withdrawals: 0, pnl_realized: 0, pnl_unrealized: 0, capital_inicio: 0, capital_final: 0 }

const BROKER_LABEL = { global: 'Global (USD)', binance: 'Binance (USD)', cocos: 'Cocos (USD aprox.)' }
const BROKER_COLOR = { global: 'text-slate-300', binance: 'text-blue-400', cocos: 'text-violet-400' }

export default function Monthly() {
  const [entries, setEntries] = useState([])
  const [tab, setTab] = useState('global')
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(EMPTY)

  useEffect(() => { load() }, [])

  async function load() {
    const data = await fetch('/api/monthly').then(r => r.json())
    setEntries(data)
  }

  function openAdd() { setForm({ ...EMPTY, broker: tab }); setModal('add') }
  function openEdit(e) { setForm({ ...e }); setModal('edit') }

  async function save() {
    if (modal === 'edit') {
      await fetch(`/api/monthly/${form.id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form)
      })
    } else {
      await fetch('/api/monthly', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form)
      })
    }
    setModal(null)
    load()
  }

  async function del(id) {
    if (!confirm('¿Eliminar entrada?')) return
    await fetch(`/api/monthly/${id}`, { method: 'DELETE' })
    load()
  }

  const tabData = entries.filter(e => e.broker === tab).sort((a, b) => a.year !== b.year ? a.year - b.year : a.month - b.month)

  const totals = tabData.reduce((acc, m) => ({
    deposits: acc.deposits + m.deposits,
    withdrawals: acc.withdrawals + m.withdrawals,
    pnl_realized: acc.pnl_realized + m.pnl_realized,
  }), { deposits: 0, withdrawals: 0, pnl_realized: 0 })

  const thClass = 'px-4 py-2 text-left text-xs text-slate-500 font-medium'
  const tdClass = 'px-4 py-2 text-sm'

  return (
    <div className="pt-20 px-6 pb-10 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-slate-100">Resumen Mensual</h1>
        <button onClick={openAdd} className="flex items-center gap-1 text-sm bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 px-3 py-1.5 rounded-md transition-colors">
          <Plus size={14} /> Agregar mes
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5 bg-slate-800/50 p-1 rounded-lg w-fit">
        {['global', 'binance', 'cocos'].map(b => (
          <button
            key={b}
            onClick={() => setTab(b)}
            className={`px-4 py-1.5 text-sm rounded-md font-medium transition-colors ${
              tab === b ? 'bg-slate-700 text-slate-100' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {BROKER_LABEL[b]}
          </button>
        ))}
      </div>

      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className={thClass}>Mes</th>
                <th className={thClass}>Depósitos</th>
                <th className={thClass}>Retiros</th>
                <th className={thClass}>Neto Dep/Ret</th>
                <th className={thClass}>P&L Realizado</th>
                <th className={thClass}>P&L No Real.</th>
                <th className={thClass}>Cap. Inicio</th>
                <th className={thClass}>Cap. Final</th>
                <th className={thClass}>Ret. $</th>
                <th className={thClass}>Ret. %</th>
                <th className={thClass}>Ret. Real %</th>
                <th className={thClass}></th>
              </tr>
            </thead>
            <tbody>
              {tabData.length === 0 && (
                <tr><td colSpan={12} className="px-4 py-8 text-center text-slate-500">Sin entradas. Agregá el primer mes.</td></tr>
              )}
              {tabData.map(m => {
                const net = m.deposits - m.withdrawals
                const ret = m.capital_final - m.capital_inicio - net
                const retPct = m.capital_inicio > 0 ? ret / m.capital_inicio : 0
                const retReal = m.capital_inicio > 0 ? m.pnl_realized / m.capital_inicio : 0
                return (
                  <tr key={m.id} className="border-b border-slate-700/20 hover:bg-slate-700/20">
                    <td className={`${tdClass} font-medium text-slate-200`}>{MONTHS[m.month - 1]} {m.year}</td>
                    <td className={`${tdClass} text-slate-300`}>{usd(m.deposits)}</td>
                    <td className={`${tdClass} text-slate-300`}>{usd(m.withdrawals)}</td>
                    <td className={`${tdClass} ${colorClass(net)}`}>{usd(net)}</td>
                    <td className={`${tdClass} ${colorClass(m.pnl_realized)}`}>{usd(m.pnl_realized)}</td>
                    <td className={`${tdClass} ${colorClass(m.pnl_unrealized)}`}>{usd(m.pnl_unrealized)}</td>
                    <td className={`${tdClass} text-slate-300`}>{usd(m.capital_inicio)}</td>
                    <td className={`${tdClass} text-slate-300`}>{usd(m.capital_final)}</td>
                    <td className={`${tdClass} font-medium ${colorClass(ret)}`}>{usd(ret)}</td>
                    <td className={`${tdClass} font-medium ${colorClass(retPct)}`}>{pct(retPct)}</td>
                    <td className={`${tdClass} ${colorClass(retReal)}`}>{pct(retReal)}</td>
                    <td className={tdClass}>
                      <div className="flex gap-2">
                        <button onClick={() => openEdit(m)} className="text-slate-400 hover:text-slate-200"><Pencil size={13} /></button>
                        <button onClick={() => del(m.id)} className="text-slate-400 hover:text-red-400"><Trash2 size={13} /></button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
            {tabData.length > 0 && (
              <tfoot>
                <tr className="border-t border-slate-600 bg-slate-700/20">
                  <td className="px-4 py-2 text-xs font-semibold text-slate-400">TOTAL</td>
                  <td className="px-4 py-2 text-xs text-slate-300">{usd(totals.deposits)}</td>
                  <td className="px-4 py-2 text-xs text-slate-300">{usd(totals.withdrawals)}</td>
                  <td className={`px-4 py-2 text-xs ${colorClass(totals.deposits - totals.withdrawals)}`}>{usd(totals.deposits - totals.withdrawals)}</td>
                  <td className={`px-4 py-2 text-xs ${colorClass(totals.pnl_realized)}`}>{usd(totals.pnl_realized)}</td>
                  <td colSpan={7} />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </div>

      {modal && (
        <Modal title={modal === 'edit' ? 'Editar mes' : 'Agregar mes'} onClose={() => setModal(null)}>
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Año</label>
                <input type="number" value={form.year} onChange={e => setForm(f => ({ ...f, year: +e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Mes</label>
                <select value={form.month} onChange={e => setForm(f => ({ ...f, month: +e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200">
                  {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Broker</label>
                <select value={form.broker} onChange={e => setForm(f => ({ ...f, broker: e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200">
                  <option value="global">Global</option>
                  <option value="binance">Binance</option>
                  <option value="cocos">Cocos</option>
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {[
                ['Depósitos', 'deposits'],
                ['Retiros', 'withdrawals'],
                ['P&L Realizado', 'pnl_realized'],
                ['P&L No Realizado', 'pnl_unrealized'],
                ['Capital Inicio', 'capital_inicio'],
                ['Capital Final', 'capital_final'],
              ].map(([label, key]) => (
                <div key={key}>
                  <label className="block text-xs text-slate-400 mb-1">{label}</label>
                  <input type="number" step="any" value={form[key]} onChange={e => setForm(f => ({ ...f, [key]: +e.target.value }))}
                    className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" />
                </div>
              ))}
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
