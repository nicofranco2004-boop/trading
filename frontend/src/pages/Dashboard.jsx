import { useEffect, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie, Legend } from 'recharts'
import StatCard from '../components/StatCard'
import { usd, pct, colorClass, MONTHS } from '../utils/format'
import { RefreshCw } from 'lucide-react'

const COCOS_STOCKS = ['INTC','MSFT','TSLA','COIN','AMZN','ADBE','MELI','BMA','META','NVDA','NFLX']
const CRYPTO = ['BTC']

export default function Dashboard() {
  const [positions, setPositions] = useState([])
  const [monthly, setMonthly] = useState([])
  const [config, setConfig] = useState({ tc_mep: 1415, tc_blue: 1415 })
  const [prices, setPrices] = useState({})
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    const [pos, mon, cfg] = await Promise.all([
      fetch('/api/positions').then(r => r.json()),
      fetch('/api/monthly').then(r => r.json()),
      fetch('/api/config').then(r => r.json()),
    ])
    setPositions(pos)
    setMonthly(mon)
    setConfig(cfg)
    await loadPrices(pos, cfg)
    setLoading(false)
  }

  async function loadPrices(pos, cfg) {
    setRefreshing(true)
    const cocosStocks = [...new Set(pos.filter(p => p.broker === 'cocos' && !p.is_cash).map(p => p.asset + '.BA'))]
    const cryptos = [...new Set(pos.filter(p => p.broker === 'binance' && !p.is_cash && p.asset !== 'USDT').map(p => p.asset))]
    const all = [...cocosStocks, ...cryptos].join(',')
    if (!all) { setRefreshing(false); return }
    try {
      const data = await fetch(`/api/prices?symbols=${all}`).then(r => r.json())
      const mapped = {}
      // .BA prices → ARS; crypto/USD prices → USD. Keep original key structure.
      for (const [k, v] of Object.entries(data)) {
        mapped[k] = v  // keep "MSFT.BA" and "BTC" as separate keys
      }
      setPrices(mapped)
    } catch {}
    setRefreshing(false)
  }

  const tcMep = config.tc_mep || 1415
  const tcBlue = config.tc_blue || 1415

  const binancePos = positions.filter(p => p.broker === 'binance')
  const cocosPos = positions.filter(p => p.broker === 'cocos')

  let binanceValue = 0, binanceInvested = 0
  for (const p of binancePos) {
    if (p.is_cash) { binanceValue += p.invested || 0; binanceInvested += p.invested || 0; continue }
    const price = p.price_override ?? prices[p.asset]
    if (price != null) {
      binanceValue += price * (p.quantity || 0)
      binanceInvested += p.invested || 0
    } else {
      binanceValue += p.invested || 0
      binanceInvested += p.invested || 0
    }
  }

  let cocosValueUsd = 0, cocosInvestedUsd = 0
  for (const p of cocosPos) {
    if (p.is_cash) {
      const usdVal = (p.invested || 0) / tcBlue
      cocosValueUsd += usdVal
      cocosInvestedUsd += usdVal
      continue
    }
    // prices[asset+".BA"] is already in ARS; price_override is also ARS for Cocos
    const priceArs = p.price_override ?? prices[p.asset + '.BA']
    const invUsd = (p.invested || 0) / (p.tc_compra || tcBlue)
    cocosInvestedUsd += invUsd
    if (priceArs != null) {
      const valueArs = priceArs * (p.quantity || 0)
      cocosValueUsd += valueArs / tcBlue
    } else {
      cocosValueUsd += invUsd
    }
  }

  const totalValue = binanceValue + cocosValueUsd
  const totalInvested = binanceInvested + cocosInvestedUsd
  const totalPnl = totalValue - totalInvested
  const totalPct = totalInvested > 0 ? totalPnl / totalInvested : 0

  const globalMonthly = monthly.filter(m => m.broker === 'global').sort((a, b) => a.month - b.month)
  const chartData = globalMonthly.map(m => {
    const ret = m.capital_inicio > 0
      ? (m.capital_final - m.capital_inicio - (m.deposits - m.withdrawals)) / m.capital_inicio
      : 0
    return { name: MONTHS[m.month - 1].slice(0, 3), ret: +(ret * 100).toFixed(2), pnl: m.capital_final - m.capital_inicio - (m.deposits - m.withdrawals) }
  })

  const pieData = [
    { name: 'Binance', value: +binanceValue.toFixed(2) },
    { name: 'Cocos', value: +cocosValueUsd.toFixed(2) },
  ]
  const PIE_COLORS = ['#3b82f6', '#8b5cf6']

  if (loading) return <div className="pt-20 text-center text-slate-400">Cargando...</div>

  return (
    <div className="pt-20 px-6 pb-10 max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-slate-100">Dashboard</h1>
        <button
          onClick={() => loadPrices(positions, config)}
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          Actualizar precios
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Portfolio Total" value={`$${usd(totalValue)}`} sub="USD estimado" />
        <StatCard label="P&L No Realizado" value={`$${usd(totalPnl)}`} sub={pct(totalPct)} positive={totalPnl >= 0} />
        <StatCard label="Binance" value={`$${usd(binanceValue)}`} sub={`Inv: $${usd(binanceInvested)}`} positive={binanceValue >= binanceInvested} />
        <StatCard label="Cocos" value={`$${usd(cocosValueUsd)}`} sub={`Inv: $${usd(cocosInvestedUsd)}`} positive={cocosValueUsd >= cocosInvestedUsd} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        {/* Monthly returns bar chart */}
        <div className="md:col-span-2 bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
          <p className="text-sm font-medium text-slate-300 mb-4">Retorno mensual (%)</p>
          {chartData.length === 0 ? (
            <p className="text-slate-500 text-sm text-center py-8">Sin datos mensuales aún</p>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={chartData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} width={40} />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                  labelStyle={{ color: '#f1f5f9' }}
                  formatter={(v, name) => [`${v}%`, 'Retorno']}
                />
                <Bar dataKey="ret" radius={[4, 4, 0, 0]}>
                  {chartData.map((d, i) => (
                    <Cell key={i} fill={d.ret >= 0 ? '#22c55e' : '#ef4444'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Allocation pie */}
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
          <p className="text-sm font-medium text-slate-300 mb-2">Distribución</p>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={75} dataKey="value" paddingAngle={3}>
                {pieData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i]} />)}
              </Pie>
              <Legend
                formatter={(v) => <span className="text-slate-300 text-xs">{v}</span>}
                iconType="circle"
                iconSize={8}
              />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                formatter={(v) => [`$${usd(v)}`, '']}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Monthly performance table */}
      {globalMonthly.length > 0 && (
        <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-700/50">
            <p className="text-sm font-medium text-slate-300">Resumen mensual — Global (USD)</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700/50">
                  {['Mes','Depósitos','Retiros','P&L Real.','P&L No Real.','Cap. Inicio','Cap. Final','Ret. $','Ret. %'].map(h => (
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
                      <td className="px-4 py-2 font-medium text-slate-200">{MONTHS[m.month - 1]}</td>
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
