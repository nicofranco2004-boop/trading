import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2, RefreshCw, AlertCircle } from 'lucide-react'
import Modal from '../components/Modal'
import { usd, ars, pct, colorClass } from '../utils/format'

const EMPTY_POS = {
  broker: 'binance', asset: '', is_cash: false,
  buy_price: '', quantity: '', invested: '', tc_compra: '', price_override: '', notes: ''
}

export default function Positions() {
  const [positions, setPositions] = useState([])
  const [prices, setPrices] = useState({})
  const [config, setConfig] = useState({ tc_mep: 1415, tc_blue: 1415 })
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(EMPTY_POS)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    const [pos, cfg] = await Promise.all([
      fetch('/api/positions').then(r => r.json()),
      fetch('/api/config').then(r => r.json()),
    ])
    setPositions(pos)
    setConfig(cfg)
    await fetchPrices(pos, cfg)
  }

  async function fetchPrices(pos, cfg) {
    setRefreshing(true)
    const stocks = [...new Set(pos.filter(p => p.broker === 'cocos' && !p.is_cash).map(p => p.asset + '.BA'))]
    const cryptos = [...new Set(pos.filter(p => p.broker === 'binance' && !p.is_cash && p.asset !== 'USDT').map(p => p.asset))]
    const all = [...stocks, ...cryptos].join(',')
    if (!all) { setRefreshing(false); return }
    try {
      const data = await fetch(`/api/prices?symbols=${all}`).then(r => r.json())
      // Keep keys as-is: "MSFT.BA" (ARS), "BTC" (USD)
      setPrices(data)
    } catch {}
    setRefreshing(false)
  }

  const tcMep = config.tc_mep || 1415
  const tcBlue = config.tc_blue || 1415

  function openAdd(broker) { setForm({ ...EMPTY_POS, broker }); setModal('add') }
  function openEdit(p) {
    setForm({
      ...p,
      is_cash: !!p.is_cash,
      buy_price: p.buy_price ?? '',
      quantity: p.quantity ?? '',
      invested: p.invested ?? '',
      tc_compra: p.tc_compra ?? '',
      price_override: p.price_override ?? '',
      notes: p.notes ?? '',
    })
    setModal('edit')
  }

  async function save() {
    const body = {
      ...form,
      buy_price: form.buy_price !== '' ? +form.buy_price : null,
      quantity: form.quantity !== '' ? +form.quantity : null,
      invested: form.invested !== '' ? +form.invested : null,
      tc_compra: form.tc_compra !== '' ? +form.tc_compra : null,
      price_override: form.price_override !== '' ? +form.price_override : null,
    }
    if (modal === 'edit') {
      await fetch(`/api/positions/${form.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    } else {
      await fetch('/api/positions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    }
    setModal(null)
    loadAll()
  }

  async function del(id) {
    if (!confirm('¿Eliminar posición?')) return
    await fetch(`/api/positions/${id}`, { method: 'DELETE' })
    loadAll()
  }

  // Cash rows anchored at the bottom of each broker section
  const sortCash = (arr) => [...arr.filter(p => !p.is_cash), ...arr.filter(p => p.is_cash)]
  const binance = sortCash(positions.filter(p => p.broker === 'binance'))
  const cocos = sortCash(positions.filter(p => p.broker === 'cocos'))

  function calcBinance(p) {
    if (p.is_cash) return { value: p.invested, pnl: 0, pnlPct: 0, price: null }
    const price = p.price_override ?? prices[p.asset]
    if (price == null) return { value: null, pnl: null, pnlPct: null, price: null }
    const value = price * p.quantity
    const pnl = value - p.invested
    return { value, pnl, pnlPct: p.invested > 0 ? pnl / p.invested : 0, price }
  }

  function calcCocos(p) {
    if (p.is_cash) {
      return { valueArs: p.invested, valueUsd: p.invested / tcBlue, pnlArs: 0, pnlUsd: 0, pnlPct: 0, priceArs: null }
    }
    // price_override = ARS price (manual); prices["MSFT.BA"] = ARS price from BCBA
    const priceArs = p.price_override ?? prices[p.asset + '.BA']
    if (priceArs == null) return { valueArs: null, valueUsd: null, pnlArs: null, pnlUsd: null, pnlPct: null, priceArs: null }
    const valueArs = priceArs * p.quantity
    const pnlArs = valueArs - p.invested
    const pnlUsd = pnlArs / tcBlue
    const invUsd = p.invested / (p.tc_compra || tcBlue)
    return { valueArs, valueUsd: valueArs / tcBlue, pnlArs, pnlUsd, pnlPct: p.invested > 0 ? pnlArs / p.invested : 0, priceArs, invUsd }
  }

  const binanceTotals = binance.reduce((acc, p) => {
    const c = calcBinance(p)
    const val = c.value != null ? c.value : (p.invested || 0)
    const inv = p.invested || 0
    return {
      value: acc.value + val,
      invested: acc.invested + inv,
      pnl: acc.pnl + (c.pnl != null ? c.pnl : 0),
    }
  }, { value: 0, invested: 0, pnl: 0 })

  const cocosTotals = cocos.reduce((acc, p) => {
    if (p.is_cash) {
      const usdVal = (p.invested || 0) / tcBlue
      return { ...acc, invArs: acc.invArs + (p.invested || 0), invUsd: acc.invUsd + usdVal, valueArs: acc.valueArs + (p.invested || 0), valueUsd: acc.valueUsd + usdVal }
    }
    const c = calcCocos(p)
    const inv = (p.invested || 0) / (p.tc_compra || tcBlue)
    return {
      invArs: acc.invArs + (p.invested || 0),
      invUsd: acc.invUsd + inv,
      valueArs: acc.valueArs + (c.valueArs != null ? c.valueArs : (p.invested || 0)),
      valueUsd: acc.valueUsd + (c.valueUsd != null ? c.valueUsd : inv),
      pnlArs: acc.pnlArs + (c.pnlArs != null ? c.pnlArs : 0),
      pnlUsd: acc.pnlUsd + (c.pnlUsd != null ? c.pnlUsd : 0),
    }
  }, { invArs: 0, invUsd: 0, valueArs: 0, valueUsd: 0, pnlArs: 0, pnlUsd: 0 })

  const thClass = 'px-3 py-2 text-left text-xs text-slate-500 font-medium whitespace-nowrap'
  const tdClass = 'px-3 py-2 text-sm whitespace-nowrap'

  return (
    <div className="pt-20 px-6 pb-10 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-slate-100">Posiciones Activas</h1>
        <button onClick={() => fetchPrices(positions, config)} className="flex items-center gap-2 text-sm text-slate-400 hover:text-slate-200">
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          Actualizar precios
        </button>
      </div>

      {/* Binance section */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden mb-6">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
          <div>
            <span className="font-semibold text-blue-400">Binance</span>
            <span className="text-slate-500 text-sm ml-2">— USD</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-slate-300 text-sm">
              Valor: <span className="font-semibold text-slate-100">${usd(binanceTotals.value)}</span>
              <span className={`ml-3 text-xs ${colorClass(binanceTotals.value - binanceTotals.invested)}`}>
                {binanceTotals.value > 0 ? pct((binanceTotals.value - binanceTotals.invested) / binanceTotals.invested) : ''}
              </span>
            </span>
            <button onClick={() => openAdd('binance')} className="flex items-center gap-1 text-xs bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 px-2 py-1 rounded-md transition-colors">
              <Plus size={12} /> Agregar
            </button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/30">
                <th className={thClass}>Activo</th>
                <th className={thClass}>P. Compra</th>
                <th className={thClass}>Cantidad</th>
                <th className={thClass}>Invertido</th>
                <th className={thClass}>Precio Actual</th>
                <th className={thClass}>Valor Actual</th>
                <th className={thClass}>P&L $</th>
                <th className={thClass}>P&L %</th>
                <th className={thClass}></th>
              </tr>
            </thead>
            <tbody>
              {binance.map(p => {
                const c = calcBinance(p)
                return (
                  <tr key={p.id} className="border-b border-slate-700/20 hover:bg-slate-700/20">
                    <td className={`${tdClass} font-semibold text-slate-200`}>
                      {p.asset}
                      {!!p.is_cash && <span className="ml-1 text-xs text-slate-500">(Cash)</span>}
                      {!!p.price_override && <span className="ml-1 text-xs text-amber-400">●</span>}
                    </td>
                    <td className={`${tdClass} text-slate-300`}>{p.buy_price ? `$${usd(p.buy_price)}` : '—'}</td>
                    <td className={`${tdClass} text-slate-300`}>{p.quantity ?? '—'}</td>
                    <td className={`${tdClass} text-slate-300`}>${usd(p.invested)}</td>
                    <td className={`${tdClass} text-slate-300`}>{c.price != null ? `$${usd(c.price)}` : '—'}</td>
                    <td className={`${tdClass} text-slate-200 font-medium`}>{c.value != null ? `$${usd(c.value)}` : '—'}</td>
                    <td className={`${tdClass} font-medium ${colorClass(c.pnl)}`}>{c.pnl != null ? `$${usd(c.pnl)}` : '—'}</td>
                    <td className={`${tdClass} font-medium ${colorClass(c.pnlPct)}`}>{c.pnlPct != null ? pct(c.pnlPct) : '—'}</td>
                    <td className={tdClass}>
                      <div className="flex gap-2">
                        <button onClick={() => openEdit(p)} className="text-slate-400 hover:text-slate-200"><Pencil size={13} /></button>
                        <button onClick={() => del(p.id)} className="text-slate-400 hover:text-red-400"><Trash2 size={13} /></button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-slate-600 bg-slate-700/30">
                <td colSpan={3} className="px-3 py-2.5 text-xs font-bold text-slate-300 uppercase tracking-wider">TOTAL</td>
                <td className="px-3 py-2.5 text-xs font-bold text-slate-200">${usd(binanceTotals.invested)}</td>
                <td className="px-3 py-2.5 text-xs text-slate-500">—</td>
                <td className="px-3 py-2.5 text-xs font-bold text-slate-100">${usd(binanceTotals.value)}</td>
                <td className={`px-3 py-2.5 text-xs font-bold ${colorClass(binanceTotals.pnl)}`}>${usd(binanceTotals.pnl)}</td>
                <td className={`px-3 py-2.5 text-xs font-bold ${colorClass(binanceTotals.pnl)}`}>
                  {binanceTotals.invested > 0 ? pct(binanceTotals.pnl / binanceTotals.invested) : '—'}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* Cocos section */}
      <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
          <div>
            <span className="font-semibold text-violet-400">Cocos Capital</span>
            <span className="text-slate-500 text-sm ml-2">— ARS → USD · TC MEP: {tcMep} · TC Blue: {tcBlue}</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-slate-300 text-sm">
              Valor: <span className="font-semibold text-slate-100">${usd(cocosTotals.valueUsd)}</span>
              <span className={`ml-3 text-xs ${colorClass(cocosTotals.valueUsd - cocosTotals.invUsd)}`}>
                {cocosTotals.invUsd > 0 ? pct((cocosTotals.valueUsd - cocosTotals.invUsd) / cocosTotals.invUsd) : ''}
              </span>
            </span>
            <button onClick={() => openAdd('cocos')} className="flex items-center gap-1 text-xs bg-violet-600/20 text-violet-400 hover:bg-violet-600/30 px-2 py-1 rounded-md transition-colors">
              <Plus size={12} /> Agregar
            </button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/30">
                <th className={thClass}>Activo</th>
                <th className={thClass}>P. Compra ARS</th>
                <th className={thClass}>Cantidad</th>
                <th className={thClass}>Inv. ARS</th>
                <th className={thClass}>TC Compra</th>
                <th className={thClass}>Inv. USD</th>
                <th className={thClass}>Precio USD</th>
                <th className={thClass}>Precio ARS</th>
                <th className={thClass}>Valor ARS</th>
                <th className={thClass}>P&L ARS</th>
                <th className={thClass}>P&L USD</th>
                <th className={thClass}>P&L %</th>
                <th className={thClass}></th>
              </tr>
            </thead>
            <tbody>
              {cocos.map(p => {
                const c = calcCocos(p)
                return (
                  <tr key={p.id} className="border-b border-slate-700/20 hover:bg-slate-700/20">
                    <td className={`${tdClass} font-semibold text-slate-200`}>
                      {p.asset}
                      {!!p.is_cash && <span className="ml-1 text-xs text-slate-500">(Cash)</span>}
                      {!!p.price_override && <span className="ml-1 text-xs text-amber-400" title="Precio manual">●</span>}
                    </td>
                    <td className={`${tdClass} text-slate-300`}>{p.buy_price ? ars(p.buy_price) : '—'}</td>
                    <td className={`${tdClass} text-slate-300`}>{p.quantity ?? '—'}</td>
                    <td className={`${tdClass} text-slate-300`}>{ars(p.invested)}</td>
                    <td className={`${tdClass} text-slate-400 text-xs`}>{p.tc_compra ?? '—'}</td>
                    <td className={`${tdClass} text-slate-300`}>{c.invUsd != null ? `$${usd(c.invUsd)}` : '—'}</td>
                    <td className={`${tdClass} text-slate-300`}>{c.priceArs != null ? `$${usd(c.priceArs / tcBlue)}` : '—'}</td>
                    <td className={`${tdClass} text-slate-300`}>{c.priceArs != null ? ars(c.priceArs) : '—'}</td>
                    <td className={`${tdClass} text-slate-200 font-medium`}>{c.valueArs != null ? ars(c.valueArs) : '—'}</td>
                    <td className={`${tdClass} font-medium ${colorClass(c.pnlArs)}`}>{c.pnlArs != null ? ars(c.pnlArs) : '—'}</td>
                    <td className={`${tdClass} font-medium ${colorClass(c.pnlUsd)}`}>{c.pnlUsd != null ? `$${usd(c.pnlUsd)}` : '—'}</td>
                    <td className={`${tdClass} font-medium ${colorClass(c.pnlPct)}`}>{c.pnlPct != null ? pct(c.pnlPct) : '—'}</td>
                    <td className={tdClass}>
                      <div className="flex gap-2">
                        <button onClick={() => openEdit(p)} className="text-slate-400 hover:text-slate-200"><Pencil size={13} /></button>
                        <button onClick={() => del(p.id)} className="text-slate-400 hover:text-red-400"><Trash2 size={13} /></button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-slate-600 bg-slate-700/30">
                <td colSpan={3} className="px-3 py-2.5 text-xs font-bold text-slate-300 uppercase tracking-wider">TOTAL</td>
                <td className="px-3 py-2.5 text-xs font-bold text-slate-200">{ars(cocosTotals.invArs)}</td>
                <td className="px-3 py-2.5 text-xs text-slate-500">—</td>
                <td className="px-3 py-2.5 text-xs font-bold text-slate-200">${usd(cocosTotals.invUsd)}</td>
                <td colSpan={2} className="px-3 py-2.5 text-xs text-slate-500">—</td>
                <td className="px-3 py-2.5 text-xs font-bold text-slate-100">{ars(cocosTotals.valueArs)}</td>
                <td className={`px-3 py-2.5 text-xs font-bold ${colorClass(cocosTotals.pnlArs)}`}>{ars(cocosTotals.pnlArs)}</td>
                <td className={`px-3 py-2.5 text-xs font-bold ${colorClass(cocosTotals.pnlUsd)}`}>${usd(cocosTotals.pnlUsd)}</td>
                <td className={`px-3 py-2.5 text-xs font-bold ${colorClass(cocosTotals.pnlUsd)}`}>
                  {cocosTotals.invUsd > 0 ? pct(cocosTotals.pnlUsd / cocosTotals.invUsd) : '—'}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* Precio manual note */}
      <p className="text-slate-600 text-xs mt-2 flex items-center gap-1">
        <span className="text-amber-400">●</span> = precio manual override
      </p>

      {/* Modal */}
      {modal && (
        <Modal title={modal === 'edit' ? 'Editar posición' : 'Nueva posición'} onClose={() => setModal(null)}>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Broker</label>
                <select
                  value={form.broker}
                  onChange={e => setForm(f => ({ ...f, broker: e.target.value }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200"
                >
                  <option value="binance">Binance</option>
                  <option value="cocos">Cocos</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Activo</label>
                <input value={form.asset} onChange={e => setForm(f => ({ ...f, asset: e.target.value.toUpperCase() }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200" placeholder="BTC, MSFT..." />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
              <input type="checkbox" checked={form.is_cash} onChange={e => setForm(f => ({ ...f, is_cash: e.target.checked }))} />
              Es cash
            </label>
            {!form.is_cash && (
              <div className="grid grid-cols-2 gap-3">
                <Field label="Precio de compra" value={form.buy_price} onChange={v => setForm(f => ({ ...f, buy_price: v }))} />
                <Field label="Cantidad" value={form.quantity} onChange={v => setForm(f => ({ ...f, quantity: v }))} />
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <Field label={form.broker === 'cocos' ? 'Invertido (ARS)' : 'Invertido (USD)'} value={form.invested} onChange={v => setForm(f => ({ ...f, invested: v }))} />
              {form.broker === 'cocos' && (
                <Field label="TC Compra" value={form.tc_compra} onChange={v => setForm(f => ({ ...f, tc_compra: v }))} />
              )}
            </div>
            <Field label="Precio override (opcional)" value={form.price_override} onChange={v => setForm(f => ({ ...f, price_override: v }))}
              hint={form.broker === 'cocos' ? 'ARS — deja vacío para usar precio auto del mercado BCBA' : 'USD — deja vacío para usar precio auto'} />
            <Field label="Notas (opcional)" value={form.notes} onChange={v => setForm(f => ({ ...f, notes: v }))} />
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

function Field({ label, value, onChange, hint }) {
  return (
    <div>
      <label className="block text-xs text-slate-400 mb-1">{label}</label>
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200"
        placeholder="0"
      />
      {hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}
    </div>
  )
}
