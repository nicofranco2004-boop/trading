import { useEffect, useState, useRef } from 'react'
import { Plus, Pencil, Trash2 } from 'lucide-react'
import Modal from '../components/Modal'
import { usd, ars, pct, colorClass } from '../utils/format'
import { api } from '../utils/api'
import { ARS_TICKERS, USDT_TICKERS } from '../utils/tickers'

const REFRESH_MS = 90_000

const EMPTY_POS = {
  broker: '', asset: '', is_cash: false,
  buy_price: '', quantity: '', invested: '', tc_compra: '', price_override: '', notes: ''
}

const BROKER_COLORS = [
  { text: 'text-blue-400', bg: 'bg-blue-600/20', hover: 'hover:bg-blue-600/30' },
  { text: 'text-violet-400', bg: 'bg-violet-600/20', hover: 'hover:bg-violet-600/30' },
  { text: 'text-emerald-400', bg: 'bg-emerald-600/20', hover: 'hover:bg-emerald-600/30' },
  { text: 'text-amber-400', bg: 'bg-amber-600/20', hover: 'hover:bg-amber-600/30' },
  { text: 'text-cyan-400', bg: 'bg-cyan-600/20', hover: 'hover:bg-cyan-600/30' },
]

export default function Positions() {
  const [positions, setPositions] = useState([])
  const [prices, setPrices] = useState({})
  const [config, setConfig] = useState({ tc_mep: 1415, tc_blue: 1415 })
  const [brokers, setBrokers] = useState([])
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(EMPTY_POS)
  const [lastUpdated, setLastUpdated] = useState(null)
  const latestRef = useRef({})

  useEffect(() => {
    loadAll()
    const id = setInterval(() => {
      const { pos, cfg, bkrs } = latestRef.current
      if (pos) fetchPrices(pos, cfg, bkrs)
    }, REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  async function loadAll() {
    const [pos, cfg, bkrs] = await Promise.all([
      api.get('/positions'),
      api.get('/config'),
      api.get('/brokers'),
    ])
    setPositions(pos)
    setConfig(cfg)
    setBrokers(bkrs)
    latestRef.current = { pos, cfg, bkrs }
    await fetchPrices(pos, cfg, bkrs)
  }

  async function fetchPrices(pos, cfg, bkrs) {
    const arsBrokers = new Set(bkrs.filter(b => b.currency === 'ARS').map(b => b.name))
    const usdtBrokers = new Set(bkrs.filter(b => b.currency === 'USDT').map(b => b.name))

    const arsSyms = [...new Set(
      pos.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => p.asset + '.BA')
    )]
    const usdtSyms = [...new Set(
      pos.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => p.asset)
    )]
    const all = [...arsSyms, ...usdtSyms].join(',')
    if (!all) return
    try {
      const data = await api.get(`/prices?symbols=${all}`)
      setPrices(data)
      setLastUpdated(new Date())
    } catch {}
  }

  const tcBlue = config.tc_blue || 1415
  const tcMep = config.tc_mep || 1415

  function openAdd(broker) {
    setForm({ ...EMPTY_POS, broker: broker || (brokers[0]?.name ?? '') })
    setModal('add')
  }
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
      await api.put(`/positions/${form.id}`, body)
    } else {
      await api.post('/positions', body)
    }
    setModal(null)
    loadAll()
  }

  async function del(id) {
    if (!confirm('¿Eliminar posición?')) return
    await api.delete(`/positions/${id}`)
    loadAll()
  }

  const sortCash = arr => [...arr.filter(p => !p.is_cash), ...arr.filter(p => p.is_cash)]

  function calcUSDT(p) {
    if (p.is_cash) return { value: p.invested, pnl: 0, pnlPct: 0, price: null }
    const price = p.price_override ?? prices[p.asset]
    if (price == null) return { value: null, pnl: null, pnlPct: null, price: null }
    const value = price * p.quantity
    const pnl = value - p.invested
    return { value, pnl, pnlPct: p.invested > 0 ? pnl / p.invested : 0, price }
  }

  function calcARS(p) {
    if (p.is_cash) {
      return { valueArs: p.invested, valueUsd: p.invested / tcBlue, pnlArs: 0, pnlUsd: 0, pnlPct: 0, priceArs: null }
    }
    const priceArs = p.price_override ?? prices[p.asset + '.BA']
    if (priceArs == null) return { valueArs: null, valueUsd: null, pnlArs: null, pnlUsd: null, pnlPct: null, priceArs: null }
    const valueArs = priceArs * p.quantity
    const pnlArs = valueArs - p.invested
    const pnlUsd = pnlArs / tcBlue
    const invUsd = p.invested / (p.tc_compra || tcBlue)
    return { valueArs, valueUsd: valueArs / tcBlue, pnlArs, pnlUsd, pnlPct: p.invested > 0 ? pnlArs / p.invested : 0, priceArs, invUsd }
  }

  const thClass = 'px-3 py-2 text-left text-xs text-slate-500 font-medium whitespace-nowrap'
  const tdClass = 'px-3 py-2 text-sm whitespace-nowrap'

  const selectedBrokerCurrency = brokers.find(b => b.name === form.broker)?.currency ?? 'USDT'

  if (brokers.length === 0) {
    return (
      <div className="pt-20 px-6 pb-10 max-w-7xl mx-auto">
        <h1 className="text-xl font-bold text-slate-100 mb-6">Posiciones Activas</h1>
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-8 text-center text-slate-400">
          <p className="mb-2">No tenés brokers configurados todavía.</p>
          <p className="text-sm">Andá a <span className="text-blue-400">Config</span> para agregar tus brokers.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="pt-20 px-6 pb-10 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-slate-100">Posiciones Activas</h1>
        {lastUpdated && (
          <span className="text-xs text-slate-600">
            Precios: {lastUpdated.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>

      {brokers.map((broker, bi) => {
        const color = BROKER_COLORS[bi % BROKER_COLORS.length]
        const bpos = sortCash(positions.filter(p => p.broker === broker.name))
        const isARS = broker.currency === 'ARS'

        if (isARS) {
          const totals = bpos.reduce((acc, p) => {
            if (p.is_cash) {
              const usdVal = (p.invested || 0) / tcBlue
              return { ...acc, invArs: acc.invArs + (p.invested || 0), invUsd: acc.invUsd + usdVal, valueArs: acc.valueArs + (p.invested || 0), valueUsd: acc.valueUsd + usdVal }
            }
            const c = calcARS(p)
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

          return (
            <div key={broker.id} className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden mb-6">
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
                <div>
                  <span className={`font-semibold ${color.text}`}>{broker.name}</span>
                  <span className="text-slate-500 text-sm ml-2">— ARS → USD · TC Blue: {tcBlue}</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-slate-300 text-sm">
                    Valor: <span className="font-semibold text-slate-100">${usd(totals.valueUsd)}</span>
                    <span className={`ml-3 text-xs ${colorClass(totals.valueUsd - totals.invUsd)}`}>
                      {totals.invUsd > 0 ? pct((totals.valueUsd - totals.invUsd) / totals.invUsd) : ''}
                    </span>
                  </span>
                  <button onClick={() => openAdd(broker.name)} className={`flex items-center gap-1 text-xs ${color.bg} ${color.text} ${color.hover} px-2 py-1 rounded-md transition-colors`}>
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
                    {bpos.map(p => {
                      const c = calcARS(p)
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
                      <td className="px-3 py-2.5 text-xs font-bold text-slate-200">{ars(totals.invArs)}</td>
                      <td className="px-3 py-2.5 text-xs text-slate-500">—</td>
                      <td className="px-3 py-2.5 text-xs font-bold text-slate-200">${usd(totals.invUsd)}</td>
                      <td colSpan={2} className="px-3 py-2.5 text-xs text-slate-500">—</td>
                      <td className="px-3 py-2.5 text-xs font-bold text-slate-100">{ars(totals.valueArs)}</td>
                      <td className={`px-3 py-2.5 text-xs font-bold ${colorClass(totals.pnlArs)}`}>{ars(totals.pnlArs)}</td>
                      <td className={`px-3 py-2.5 text-xs font-bold ${colorClass(totals.pnlUsd)}`}>${usd(totals.pnlUsd)}</td>
                      <td className={`px-3 py-2.5 text-xs font-bold ${colorClass(totals.pnlUsd)}`}>
                        {totals.invUsd > 0 ? pct(totals.pnlUsd / totals.invUsd) : '—'}
                      </td>
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )
        }

        // USDT broker
        const totals = bpos.reduce((acc, p) => {
          const c = calcUSDT(p)
          const val = c.value != null ? c.value : (p.invested || 0)
          return {
            value: acc.value + val,
            invested: acc.invested + (p.invested || 0),
            pnl: acc.pnl + (c.pnl != null ? c.pnl : 0),
          }
        }, { value: 0, invested: 0, pnl: 0 })

        return (
          <div key={broker.id} className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden mb-6">
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700/50">
              <div>
                <span className={`font-semibold ${color.text}`}>{broker.name}</span>
                <span className="text-slate-500 text-sm ml-2">— USD</span>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-slate-300 text-sm">
                  Valor: <span className="font-semibold text-slate-100">${usd(totals.value)}</span>
                  <span className={`ml-3 text-xs ${colorClass(totals.value - totals.invested)}`}>
                    {totals.invested > 0 ? pct((totals.value - totals.invested) / totals.invested) : ''}
                  </span>
                </span>
                <button onClick={() => openAdd(broker.name)} className={`flex items-center gap-1 text-xs ${color.bg} ${color.text} ${color.hover} px-2 py-1 rounded-md transition-colors`}>
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
                  {bpos.map(p => {
                    const c = calcUSDT(p)
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
                    <td className="px-3 py-2.5 text-xs font-bold text-slate-200">${usd(totals.invested)}</td>
                    <td className="px-3 py-2.5 text-xs text-slate-500">—</td>
                    <td className="px-3 py-2.5 text-xs font-bold text-slate-100">${usd(totals.value)}</td>
                    <td className={`px-3 py-2.5 text-xs font-bold ${colorClass(totals.pnl)}`}>${usd(totals.pnl)}</td>
                    <td className={`px-3 py-2.5 text-xs font-bold ${colorClass(totals.pnl)}`}>
                      {totals.invested > 0 ? pct(totals.pnl / totals.invested) : '—'}
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>
        )
      })}

      <p className="text-slate-600 text-xs mt-2 flex items-center gap-1">
        <span className="text-amber-400">●</span> = precio manual override
      </p>

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
                  {brokers.map(b => <option key={b.id} value={b.name}>{b.name} ({b.currency})</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Activo</label>
                <input
                  list="asset-suggestions"
                  value={form.asset}
                  onChange={e => setForm(f => ({ ...f, asset: e.target.value.toUpperCase() }))}
                  className="w-full bg-slate-700 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200"
                  placeholder={selectedBrokerCurrency === 'ARS' ? 'MSFT, GGAL, YPF...' : 'BTC, ETH, AAPL...'}
                  autoComplete="off"
                />
                <datalist id="asset-suggestions">
                  {(selectedBrokerCurrency === 'ARS' ? ARS_TICKERS : USDT_TICKERS).map(t => (
                    <option key={t} value={t} />
                  ))}
                </datalist>
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
              <Field
                label={selectedBrokerCurrency === 'ARS' ? 'Invertido (ARS)' : 'Invertido (USD)'}
                value={form.invested}
                onChange={v => setForm(f => ({ ...f, invested: v }))}
              />
              {selectedBrokerCurrency === 'ARS' && (
                <Field label="TC Compra" value={form.tc_compra} onChange={v => setForm(f => ({ ...f, tc_compra: v }))} />
              )}
            </div>
            <Field
              label="Precio override (opcional)"
              value={form.price_override}
              onChange={v => setForm(f => ({ ...f, price_override: v }))}
              hint={selectedBrokerCurrency === 'ARS'
                ? 'ARS — deja vacío para precio auto BCBA'
                : 'USD — deja vacío para precio auto'}
            />
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
