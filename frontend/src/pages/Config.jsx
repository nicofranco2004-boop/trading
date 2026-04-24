import { useEffect, useState } from 'react'
import { Save, Plus, Trash2, Pencil } from 'lucide-react'
import { api } from '../utils/api'

export default function Config() {
  const [cfg, setCfg] = useState({ tc_mep: '', tc_blue: '' })
  const [saved, setSaved] = useState(false)
  const [brokers, setBrokers] = useState([])
  const [newBroker, setNewBroker] = useState({ name: '', currency: 'USDT' })
  const [editingBroker, setEditingBroker] = useState(null)

  useEffect(() => {
    api.get('/config').then(d => setCfg({ tc_mep: d.tc_mep, tc_blue: d.tc_blue }))
    loadBrokers()
  }, [])

  async function loadBrokers() {
    setBrokers(await api.get('/brokers'))
  }

  async function saveCfg(e) {
    e.preventDefault()
    await api.put('/config', { tc_mep: +cfg.tc_mep, tc_blue: +cfg.tc_blue })
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  async function addBroker(e) {
    e.preventDefault()
    if (!newBroker.name.trim()) return
    await api.post('/brokers', { name: newBroker.name.trim(), currency: newBroker.currency })
    setNewBroker({ name: '', currency: 'USDT' })
    loadBrokers()
  }

  async function saveEditBroker(e) {
    e.preventDefault()
    await api.put(`/brokers/${editingBroker.id}`, { name: editingBroker.name, currency: editingBroker.currency })
    setEditingBroker(null)
    loadBrokers()
  }

  async function deleteBroker(id) {
    if (!confirm('¿Eliminar broker? Las posiciones asociadas quedarán sin broker.')) return
    await api.delete(`/brokers/${id}`)
    loadBrokers()
  }

  const inputClass = 'w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-slate-200 text-sm'
  const selectClass = 'bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-slate-200 text-sm'

  return (
    <div className="pt-20 px-6 pb-10 max-w-lg mx-auto space-y-6">
      <h1 className="text-xl font-bold text-slate-100">Configuración</h1>

      {/* Tipos de cambio */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6">
        <h2 className="font-semibold text-slate-200 mb-4">Tipos de cambio</h2>
        <form onSubmit={saveCfg} className="space-y-4">
          <div>
            <label className="block text-sm text-slate-300 mb-1 font-medium">TC MEP (ARS/USD)</label>
            <input
              type="number" step="any"
              value={cfg.tc_mep}
              onChange={e => setCfg(c => ({ ...c, tc_mep: e.target.value }))}
              className={inputClass}
            />
            <p className="text-xs text-slate-500 mt-1">Referencia de tipo de cambio</p>
          </div>
          <div>
            <label className="block text-sm text-slate-300 mb-1 font-medium">TC Blue (ARS/USD)</label>
            <input
              type="number" step="any"
              value={cfg.tc_blue}
              onChange={e => setCfg(c => ({ ...c, tc_blue: e.target.value }))}
              className={inputClass}
            />
            <p className="text-xs text-slate-500 mt-1">Usado para convertir P&L ARS → USD en brokers ARS</p>
          </div>
          <button
            type="submit"
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-md text-sm font-medium transition-colors"
          >
            <Save size={14} />
            {saved ? '✓ Guardado' : 'Guardar'}
          </button>
        </form>
      </div>

      {/* Brokers */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-6">
        <h2 className="font-semibold text-slate-200 mb-4">Mis Brokers</h2>

        {/* Existing brokers */}
        {brokers.length > 0 && (
          <div className="space-y-2 mb-4">
            {brokers.map(b => (
              <div key={b.id}>
                {editingBroker?.id === b.id ? (
                  <form onSubmit={saveEditBroker} className="flex gap-2 items-center">
                    <input
                      value={editingBroker.name}
                      onChange={e => setEditingBroker(eb => ({ ...eb, name: e.target.value }))}
                      className="flex-1 bg-slate-700 border border-slate-600 rounded-md px-3 py-1.5 text-sm text-slate-200"
                    />
                    <select
                      value={editingBroker.currency}
                      onChange={e => setEditingBroker(eb => ({ ...eb, currency: e.target.value }))}
                      className={selectClass}
                    >
                      <option value="USDT">USDT</option>
                      <option value="ARS">ARS</option>
                    </select>
                    <button type="submit" className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md">OK</button>
                    <button type="button" onClick={() => setEditingBroker(null)} className="text-xs text-slate-400 px-2 py-1.5">✕</button>
                  </form>
                ) : (
                  <div className="flex items-center justify-between bg-slate-700/40 rounded-lg px-3 py-2">
                    <div>
                      <span className="text-slate-200 text-sm font-medium">{b.name}</span>
                      <span className={`ml-2 text-xs px-1.5 py-0.5 rounded font-medium ${
                        b.currency === 'ARS'
                          ? 'bg-violet-500/20 text-violet-400'
                          : 'bg-blue-500/20 text-blue-400'
                      }`}>{b.currency}</span>
                    </div>
                    <div className="flex gap-2">
                      <button onClick={() => setEditingBroker({ ...b })} className="text-slate-400 hover:text-slate-200">
                        <Pencil size={13} />
                      </button>
                      <button onClick={() => deleteBroker(b.id)} className="text-slate-400 hover:text-red-400">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Add new broker */}
        <form onSubmit={addBroker} className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="block text-xs text-slate-400 mb-1">Nombre del broker</label>
            <input
              value={newBroker.name}
              onChange={e => setNewBroker(b => ({ ...b, name: e.target.value }))}
              placeholder="ej: Binance, Cocos..."
              className={inputClass}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">Moneda</label>
            <select
              value={newBroker.currency}
              onChange={e => setNewBroker(b => ({ ...b, currency: e.target.value }))}
              className={selectClass}
            >
              <option value="USDT">USDT</option>
              <option value="ARS">ARS</option>
            </select>
          </div>
          <button
            type="submit"
            className="flex items-center gap-1 px-3 py-2 bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 rounded-md text-sm font-medium transition-colors"
          >
            <Plus size={14} /> Agregar
          </button>
        </form>
        <p className="text-xs text-slate-500 mt-3">
          <span className="text-blue-400 font-medium">USDT</span> = precios en USD (Binance, crypto) ·
          <span className="text-violet-400 font-medium ml-1">ARS</span> = precios en pesos, convertidos via TC Blue (Cocos, IOL, etc.)
        </p>
      </div>
    </div>
  )
}
