import { useEffect, useState, useRef } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie, Legend } from 'recharts'
import StatCard from '../components/StatCard'
import { usd, pct, colorClass, MONTHS } from '../utils/format'
import { api } from '../utils/api'

const PIE_COLORS = ['#3b82f6', '#8b5cf6', '#22c55e', '#f59e0b', '#ef4444', '#06b6d4']
const REFRESH_MS = 90_000

export default function Dashboard() {
  const [positions, setPositions] = useState([])
  const [monthly, setMonthly] = useState([])
  const [config, setConfig] = useState({ tc_mep: 1415, tc_blue: 1415 })
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const latestRef = useRef({})

  useEffect(() => {
    loadAll()
    const id = setInterval(() => {
      const { pos, cfg, bkrs } = latestRef.current
      if (pos) loadPrices(pos, cfg, bkrs)
    }, REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  async function loadAll() {
    const [pos, mon, cfg, bkrs] = await Promise.all([
      api.get('/positions'),
      api.get('/monthly'),
      api.get('/config'),
      api.get('/brokers'),
    ])
    setPositions(pos)
    setMonthly(mon)
    setConfig(cfg)
    setBrokers(bkrs)
    latestRef.current = { pos, cfg, bkrs }
    await loadPrices(pos, cfg, bkrs)
    setLoading(false)
  }

  async function loadPrices(pos, cfg, bkrs) {
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

  // Calculate value per broker
  function brokerValue(brokerName, currency) {
    const bpos = positions.filter(p => p.broker === brokerName)
    let value = 0, invested = 0

    for (const p of bpos) {
      if (currency === 'ARS') {
        if (p.is_cash) {
          const usdVal = (p.invested || 0) / tcBlue
          value += usdVal
          invested += usdVal
        } else {
          const priceArs = p.price_override ?? prices[p.asset + '.BA']
          const invUsd = (p.invested || 0) / (p.tc_compra || tcBlue)
          invested += invUsd
          value += priceArs != null ? (priceArs * (p.quantity || 0)) / tcBlue : invUsd
        }
      } else {
        if (p.is_cash) {
          value += p.invested || 0
          invested += p.invested || 0
        } else {
          const price = p.price_override ?? prices[p.asset]
          if (price != null) {
            value += price * (p.quantity || 0)
            invested += p.invested || 0
          } else {
            value += p.invested || 0
            invested += p.invested || 0
          }
        }
      }
    }
    return { value, invested }
  }

  const brokerTotals = brokers.map(b => ({ ...b, ...brokerValue(b.name, b.currency) }))
  const totalValue = brokerTotals.reduce((s, b) => s + b.value, 0)
  const totalInvested = brokerTotals.reduce((s, b) => s + b.invested, 0)
  const totalPnl = totalValue - totalInvested
  const totalPct = totalInvested > 0 ? totalPnl / totalInvested : 0

  const globalMonthly = monthly.filter(m => m.broker === 'global').sort((a, b) =>
    a.year !== b.year ? a.year - b.year : a.month - b.month
  )
  const chartData = globalMonthly.map(m => {
    const net = m.deposits - m.withdrawals
    const ret = m.capital_inicio > 0 ? (m.capital_final - m.capital_inicio - net) / m.capital_inicio : 0
    return {
      name: `${MONTHS[m.month - 1].slice(0, 3)} ${m.year !== new Date().getFullYear() ? m.year : ''}`.trim(),
      ret: +(ret * 100).toFixed(2),
    }
  })

  const pieData = brokerTotals.filter(b => b.value > 0).map(b => ({
    name: b.name,
    value: +b.value.toFixed(2),
  }))

  if (loading) return <div className="pt-20 text-center text-slate-400">Cargando...</div>

  return (
    <div className="pt-20 px-6 pb-10 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-slate-100">Dashboard</h1>
        {lastUpdated && (
          <span className="text-xs text-slate-600">
            Precios: {lastUpdated.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>

      {/* Top stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-4">
        <StatCard label="Portfolio Total" value={`$${usd(totalValue)}`} sub="Valor actual estimado" />
        <StatCard label="Capital Invertido" value={`$${usd(totalInvested)}`} sub="Sin contar P&L no realizado" />
        <div className="col-span-2 md:col-span-1 flex justify-center">
          <div className="w-1/2 md:w-full">
            <StatCard label="P&L No Realizado" value={`$${usd(totalPnl)}`} sub={pct(totalPct)} positive={totalPnl >= 0} />
          </div>
        </div>
      </div>

      {/* Per-broker cards */}
      {brokers.length > 0 && (
        <div className={`grid gap-4 mb-8 ${brokers.length === 1 ? 'grid-cols-1 max-w-xs' : brokers.length === 2 ? 'grid-cols-2' : 'grid-cols-2 md:grid-cols-3'}`}>
          {brokerTotals.map(b => (
            <StatCard
              key={b.id}
              label={b.name}
              value={`$${usd(b.value)}`}
              sub={`Inv: $${usd(b.invested)} · P&L: $${usd(b.value - b.invested)}`}
              positive={b.value >= b.invested}
            />
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        {/* Monthly returns chart */}
        <div className="md:col-span-2 bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
          <p className="text-sm font-medium text-slate-300 mb-4">Retorno mensual (%)</p>
          {chartData.length === 0 ? (
            <p className="text-slate-500 text-sm text-center py-8">Sin datos mensuales aún</p>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={chartData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} width={40} />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                  labelStyle={{ color: '#f1f5f9' }}
                  formatter={(v) => [`${v}%`, 'Retorno']}
                />
                <Bar dataKey="ret" radius={[4, 4, 0, 0]}>
                  {chartData.map((d, i) => <Cell key={i} fill={d.ret >= 0 ? '#22c55e' : '#ef4444'} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Allocation pie */}
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
          <p className="text-sm font-medium text-slate-300 mb-2">Distribución</p>
          {pieData.length === 0 ? (
            <p className="text-slate-500 text-sm text-center py-8">Sin datos</p>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={75} dataKey="value" paddingAngle={3}>
                  {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Legend formatter={(v) => <span className="text-slate-300 text-xs">{v}</span>} iconType="circle" iconSize={8} />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                  formatter={(v) => [`$${usd(v)}`, '']}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Monthly table */}
      {globalMonthly.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/50">
            <p className="text-sm font-medium text-slate-300">Resumen mensual — Global (USD)</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700/50">
                  {['Mes', 'Depósitos', 'Retiros', 'P&L Real.', 'P&L No Real.', 'Cap. Inicio', 'Cap. Final', 'Ret. $', 'Ret. %'].map(h => (
                    <th key={h} className="px-4 py-2 text-left text-xs text-slate-500 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {globalMonthly.map(m => {
                  const net = m.deposits - m.withdrawals
                  const ret = m.capital_final - m.capital_inicio - net
                  const retPct = m.capital_inicio > 0 ? ret / m.capital_inicio : 0
                  return (
                    <tr key={m.id} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                      <td className="px-4 py-2 font-medium text-slate-200">{MONTHS[m.month - 1]} {m.year}</td>
                      <td className="px-4 py-2 text-slate-300">${usd(m.deposits)}</td>
                      <td className="px-4 py-2 text-slate-300">${usd(m.withdrawals)}</td>
                      <td className={`px-4 py-2 ${colorClass(m.pnl_realized)}`}>${usd(m.pnl_realized)}</td>
                      <td className={`px-4 py-2 ${colorClass(m.pnl_unrealized)}`}>${usd(m.pnl_unrealized)}</td>
                      <td className="px-4 py-2 text-slate-300">${usd(m.capital_inicio)}</td>
                      <td className="px-4 py-2 text-slate-300">${usd(m.capital_final)}</td>
                      <td className={`px-4 py-2 font-medium ${colorClass(ret)}`}>${usd(ret)}</td>
                      <td className={`px-4 py-2 font-medium ${colorClass(retPct)}`}>{pct(retPct)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
