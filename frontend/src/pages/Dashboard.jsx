import { useEffect, useMemo, useState, useRef } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { TrendingUp, TrendingDown, Wallet, PiggyBank, Activity, CircleDollarSign, Upload, ArrowRight } from 'lucide-react'
import StatCard from '../components/StatCard'
import MonthlyTeaser from '../components/MonthlyTeaser'
import UpcomingEventsCard from '../components/UpcomingEventsCard'
import TopNewsCard from '../components/TopNewsCard'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import { DashboardSkeleton } from '../components/Skeleton'
import InsightLine from '../components/InsightLine'
import RangeTabs, { RANGES } from '../components/RangeTabs'
import { usd, ars, fmtUsd, fmtArs, pct, pctSigned, usdCompact } from '../utils/format'
import { api } from '../utils/api'
import { computeBrokerValue } from '../utils/valuation'
import { buildPortfolioValueSeries } from '../utils/evolution'
import { buildDashboardInsight } from '../utils/insights'

const REFRESH_MS = 90_000

export default function Dashboard() {
  const [positions, setPositions] = useState([])
  const [monthly, setMonthly] = useState([])
  const [config, setConfig] = useState({ tc_mep: 1415, tc_blue: 1415 })
  const [dolar, setDolar] = useState(null)
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [snapshots, setSnapshots] = useState([])
  const [loading, setLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const [range, setRange] = useState('1M')
  const latestRef = useRef({})

  useEffect(() => {
    loadAll()
    const id = setInterval(() => {
      const { pos, cfg, bkrs } = latestRef.current
      if (pos) loadPrices(pos, cfg, bkrs)
      api.get('/dolar').then(setDolar).catch(() => {})
    }, REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  async function loadAll() {
    try {
      const [pos, mon, cfg, bkrs, dol, snaps] = await Promise.all([
        api.get('/positions'),
        api.get('/monthly'),
        api.get('/config'),
        api.get('/brokers'),
        api.get('/dolar').catch(() => null),
        api.get('/snapshots?days=3650').catch(() => []),
      ])
      setPositions(pos)
      setMonthly(mon)
      setConfig(cfg)
      setBrokers(bkrs)
      setDolar(dol)
      setSnapshots(snaps || [])
      latestRef.current = { pos, cfg, bkrs }
      setLoading(false)
      loadPrices(pos, cfg, bkrs).catch(() => {})
    } catch (e) {
      console.error('Dashboard loadAll error:', e)
      setLoading(false)
    }
  }

  async function loadPrices(pos, cfg, bkrs) {
    const arsBrokers = new Set(bkrs.filter(b => b.currency === 'ARS').map(b => b.name))
    // Todo lo que no sea ARS (USDT, USD) se valúa directo en USD sin conversión
    const usdtBrokers = new Set(bkrs.filter(b => b.currency !== 'ARS').map(b => b.name))

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

  const tcBlue = dolar?.blue?.venta || config.tc_blue || 1415

  const brokerTotals = brokers.map(b => ({ ...b, ...computeBrokerValue(positions, prices, b, tcBlue) }))
  const totalValue = brokerTotals.reduce((s, b) => s + b.value, 0)
  const totalCostBasis = brokerTotals.reduce((s, b) => s + b.invested, 0)
  const totalPnl = totalValue - totalCostBasis
  const totalPct = totalCostBasis > 0 ? totalPnl / totalCostBasis : 0

  // Capital aportado real = capital_inicio del PRIMER mes (lo que ya tenías en la
  // cuenta cuando empezaste a trackear) + acumulado de depósitos − retiros.
  // Sin la baseline, el % "sobre lo aportado" se infla porque divide por un
  // monto chiquito (solo los flujos explícitos, no la plata que ya estaba).
  // Mismo criterio que usa Insights para la curva de evolución.
  const netDeposited = useMemo(() => {
    const globals = monthly
      .filter(m => m.broker === 'global')
      .sort((a, b) => a.year !== b.year ? a.year - b.year : a.month - b.month)
    if (globals.length === 0) return 0
    const baseline = globals[0].capital_inicio || 0
    const flows = globals.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)
    return baseline + flows
  }, [monthly])

  // Realized P&L (cumulative across all months from monthly_entries global)
  const realizedPnl = monthly
    .filter(m => m.broker === 'global')
    .reduce((s, m) => s + (m.pnl_realized || 0), 0)

  // Total return = market value vs net deposited (so deposits aren't counted as performance)
  const totalReturnUsd = totalValue - netDeposited
  const totalReturnPct = netDeposited > 0 ? totalReturnUsd / netDeposited : 0

  const portfolioTotal = totalValue

  // Dynamic insight line — uses largest gainers/losers from open positions
  const arsBrokerNames = useMemo(() => new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name)), [brokers])
  const positionsForInsight = useMemo(() => {
    return positions.filter(p => !p.is_cash).map(p => {
      const isARS = arsBrokerNames.has(p.broker)
      // Cost basis económico = invested + buy commissions (igual que valuation.js).
      const realCost = (p.invested || 0) + (p.commissions || 0)
      let valueUsd = null
      let pnlUsd = null
      if (isARS) {
        const priceArs = p.price_override ?? prices[p.asset + '.BA']
        if (priceArs != null) {
          valueUsd = (priceArs * (p.quantity || 0)) / tcBlue
          // FX-phantom fix: cost basis USD al blue actual (no al tc_compra)
          const invUsd = realCost / tcBlue
          pnlUsd = valueUsd - invUsd
        }
      } else {
        const price = p.price_override ?? prices[p.asset]
        if (price != null) {
          valueUsd = price * (p.quantity || 0)
          pnlUsd = valueUsd - realCost
        }
      }
      const invForPct = isARS ? realCost / tcBlue : realCost
      const pnlPct = pnlUsd != null && invForPct > 0 ? pnlUsd / invForPct : null
      return { asset: p.asset, value_usd: valueUsd, pnl_usd: pnlUsd, pnl_pct: pnlPct }
    })
  }, [positions, prices, tcBlue, arsBrokerNames])

  const insight = useMemo(() => buildDashboardInsight({ totalValue, netDeposited, positions: positionsForInsight }), [totalValue, netDeposited, positionsForInsight])

  // ── Snapshot 1×/day (only when real prices loaded) ──────────────────────────
  useEffect(() => {
    if (loading || !lastUpdated || totalValue <= 0) return
    const hasRealPrices = positions.some(p => !p.is_cash && (p.price_override != null || prices[p.asset] != null || prices[p.asset + '.BA'] != null))
    if (!hasRealPrices) return
    const today = new Date().toISOString().slice(0, 10)
    const key = 'rendi_snapshot_date'
    if (localStorage.getItem(key) === today) return
    api.post('/snapshots', { total_value: totalValue, total_invested: totalCostBasis, net_deposited: netDeposited })
      .then(() => localStorage.setItem(key, today))
      .catch(() => {})
  }, [loading, lastUpdated, totalValue, totalCostBasis, netDeposited, positions, prices])

  // ── Sync pnl_unrealized for current month ───────────────────────────────────
  useEffect(() => {
    if (loading || !lastUpdated || totalValue <= 0) return
    const hasRealPrices = positions.some(
      p => !p.is_cash && (p.price_override != null || prices[p.asset] != null || prices[p.asset + '.BA'] != null)
    )
    if (!hasRealPrices) return

    let globalPnlUsd = 0
    brokers.forEach(b => {
      const bpos = positions.filter(p => p.broker === b.name)
      let pnlForBroker = 0
      let pnlForGlobal = 0

      if (b.currency === 'ARS') {
        let pnlArs = 0
        for (const p of bpos) {
          if (p.is_cash) continue
          const priceArs = p.price_override ?? prices[p.asset + '.BA']
          if (priceArs == null) continue
          // Cost basis ARS = invested + commissions (ambos en pesos para broker ARS)
          const costArs = (p.invested || 0) + (p.commissions || 0)
          pnlArs += priceArs * (p.quantity || 0) - costArs
          // FX-phantom fix: ambos lados al blue actual → P&L USD == P&L ARS / tcBlue
          // Sin esto, los pesos quietos generaban "ganancia/pérdida fantasma" por
          // movimientos del blue aunque el activo no se hubiera movido.
        }
        pnlForBroker = pnlArs / tcBlue
        pnlForGlobal = pnlArs / tcBlue
      } else {
        for (const p of bpos) {
          if (p.is_cash) continue
          const price = p.price_override ?? prices[p.asset]
          if (price == null) continue
          // Cost basis USD = invested + commissions
          const costUsd = (p.invested || 0) + (p.commissions || 0)
          pnlForBroker += price * (p.quantity || 0) - costUsd
        }
        pnlForGlobal = pnlForBroker
      }

      globalPnlUsd += pnlForGlobal
      api.post('/monthly/sync-unrealized', { broker: b.name, pnl_unrealized_usd: +pnlForBroker.toFixed(4) }).catch(() => {})
    })
    api.post('/monthly/sync-unrealized', { broker: 'global', pnl_unrealized_usd: +globalPnlUsd.toFixed(4) }).catch(() => {})
  }, [loading, lastUpdated]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Portfolio evolution series (depends on range) ───────────────────────────
  const rangeDays = RANGES.find(r => r.id === range)?.days
  const evoSeries = useMemo(() => {
    return buildPortfolioValueSeries(snapshots, rangeDays ?? null, totalValue > 0 ? totalValue : null, netDeposited)
  }, [snapshots, rangeDays, totalValue, netDeposited])

  // For chart Y-axis nice domain
  const chartMin = useMemo(() => {
    if (evoSeries.length === 0) return 0
    return Math.min(...evoSeries.map(p => Math.min(p.valueUsd, p.netDeposited)))
  }, [evoSeries])
  const chartMax = useMemo(() => {
    if (evoSeries.length === 0) return 0
    return Math.max(...evoSeries.map(p => Math.max(p.valueUsd, p.netDeposited)))
  }, [evoSeries])

  // Period change (start → end of visible range)
  const periodChange = useMemo(() => {
    if (evoSeries.length < 2) return null
    const first = evoSeries[0].valueUsd
    const last = evoSeries[evoSeries.length - 1].valueUsd
    const delta = last - first
    const dPct = first > 0 ? delta / first : 0
    return { delta, pct: dPct }
  }, [evoSeries])

  if (loading) return <DashboardSkeleton />

  const meta = lastUpdated ? `Precios · ${lastUpdated.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}` : null

  return (
    <div className="page-shell">
      <PageHeader
        eyebrow="Dashboard"
        title="Estado del portfolio"
        meta={meta}
      />

      {positions.filter(p => !p.is_cash).length === 0 && !loading && (
        <Card className="mb-6">
          <div className="flex flex-col sm:flex-row sm:items-center gap-4">
            <div className="flex-1">
              <h2 className="font-semibold text-ink-0 mb-1">
                Empezá importando tu historial
              </h2>
              <p className="text-sm text-ink-2">
                Andá a <strong>Configuración</strong> y subí un CSV con tus operaciones. Reconstruimos tu portfolio en segundos — vas a poder revisar fila por fila antes de guardar.
              </p>
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              {/* CTA principal — usa rendi-pos como verde de marca/CTA */}
              <a
                href="/config"
                className="inline-flex items-center justify-center gap-1.5 text-sm bg-rendi-accent text-white hover:bg-rendi-accent/90 px-4 py-2 rounded-sm font-semibold transition"
              >
                <Upload size={14} strokeWidth={1.5} /> Ir a Configuración
              </a>
              <a
                href="/posiciones"
                className="inline-flex items-center justify-center gap-1.5 text-sm text-ink-2 hover:text-ink-0 dark:hover:text-ink-0 px-3 py-2 transition"
              >
                Cargar manualmente <ArrowRight size={12} strokeWidth={1.5} />
              </a>
            </div>
          </div>
        </Card>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          HERO — la cifra única de la pantalla. Instrument Serif italic 64-84px.
          Solo 1 hero por página (audit rule).
          ══════════════════════════════════════════════════════════════════════ */}
      <div className="mb-6 sm:mb-8">
        <StatCard
          tone="hero"
          label="Valor actual"
          value={fmtUsd(portfolioTotal)}
          tooltip={
            <>
              <p className="font-semibold text-ink-0">Valor de mercado de tu portfolio</p>
              <p>Suma del cash + posiciones abiertas valuadas a precios actuales del mercado.</p>
              <p className="text-ink-3">Para brokers ARS, la conversión a USD se hace al blue actual.</p>
            </>
          }
          sub={
            <span className="inline-flex items-center gap-3 flex-wrap">
              <span className="text-ink-2">
                {totalReturnUsd >= 0 ? 'Ganancia total' : 'Pérdida total'}
              </span>
              <span className={`inline-flex items-center gap-1 font-semibold ${totalReturnUsd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                {totalReturnUsd >= 0 ? <TrendingUp size={14} strokeWidth={1.5} /> : <TrendingDown size={14} strokeWidth={1.5} />}
                USD {usd(Math.abs(totalReturnUsd))}
              </span>
              <span className={`tabular ${totalReturnUsd >= 0 ? 'text-rendi-pos/80' : 'text-rendi-neg/80'}`}>
                ({pctSigned(totalReturnPct)})
              </span>
            </span>
          }
          hint={`≈ ${fmtArs(portfolioTotal * tcBlue)} al blue ${tcBlue} · sobre los ${fmtUsd(netDeposited)} de capital aportado`}
        />
      </div>

      {/* InsightLine — diagnóstico breve dinámico */}
      {insight && (
        <div className="mb-6">
          <InsightLine tone={insight.tone} icon={insight.tone === 'negative' ? <TrendingDown size={14} /> : insight.tone === 'positive' ? <TrendingUp size={14} /> : <Activity size={14} />}>
            {insight.text}
          </InsightLine>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          KPI STRIP V2 — celdas densas mono caps + divisor 1px (audit pattern).
          ══════════════════════════════════════════════════════════════════════ */}
      <div className="border border-line rounded bg-bg-1 flex flex-wrap mb-8">
        <KpiCell
          first
          label="Capital aportado"
          value={fmtUsd(netDeposited)}
          sub="depósitos netos"
        />
        <KpiCell
          label="Resultado total"
          value={fmtUsd(totalReturnUsd)}
          tone={totalReturnUsd >= 0 ? 'pos' : 'neg'}
          sub={`${pctSigned(totalReturnPct)} desde el inicio`}
        />
        <KpiCell
          label="P&L realizado"
          value={fmtUsd(realizedPnl)}
          tone={realizedPnl >= 0 ? 'pos' : 'neg'}
          sub="operaciones cerradas"
        />
        <KpiCell
          label="P&L no realizado"
          value={fmtUsd(totalPnl)}
          tone={totalPnl >= 0 ? 'pos' : 'neg'}
          sub={`${pctSigned(totalPct)} sobre costo`}
        />
      </div>

      {/* ── Portfolio Evolution chart ────────────────────────────────────────── */}
      <Card className="mb-8">
        <div className="flex items-start justify-between gap-3 flex-wrap mb-5">
          <div>
            <p className="eyebrow mb-1">Evolución</p>
            <h2 className="text-lg font-semibold text-ink-0 leading-tight">Performance del portfolio</h2>
            <p className="text-xs text-ink-2 mt-1 max-w-md">
              Rendimiento ajustado por flujos de capital — aportes y retiros se neutralizan para reflejar performance pura.
            </p>
            {periodChange && (
              <p className="text-sm mt-3 tabular">
                <span className={`font-semibold ${periodChange.delta >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                  {periodChange.delta >= 0 ? '+' : '−'}USD {usd(Math.abs(periodChange.delta))}
                </span>
                <span className={`ml-2 ${periodChange.delta >= 0 ? 'text-rendi-pos/80' : 'text-rendi-neg/80'}`}>
                  {pctSigned(periodChange.pct)}
                </span>
                <span className="ml-2 text-ink-2">en {rangeLabel(range)}</span>
              </p>
            )}
          </div>
          <RangeTabs value={range} onChange={setRange} />
        </div>

        {evoSeries.length < 2 ? (
          <EmptyState
            icon={<TrendingUp size={20} />}
            title="Todavía no hay historial suficiente"
            description="Vamos a registrar el valor de tu portfolio cada vez que entres al Dashboard. Con dos días registrados ya podemos mostrar la evolución."
          />
        ) : (
          (() => {
            // Color condicional: verde solo si el portfolio gana, rojo si pierde.
            // Audit visual: verde es semántico, no decorativo.
            const isProfit = totalReturnUsd >= 0
            const lineColor = isProfit ? '#21D07A' : '#FF5360'
            const fillId = isProfit ? 'grad-value-pos' : 'grad-value-neg'
            return (
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={evoSeries} margin={{ top: 10, right: 8, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={lineColor} stopOpacity={0.18} />
                      <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#1B2230" strokeOpacity={0.6} strokeDasharray="2 4" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fill: '#8B8D8A', fontSize: 11, fontFamily: 'JetBrains Mono' }}
                    axisLine={false}
                    tickLine={false}
                    minTickGap={28}
                  />
                  <YAxis
                    tick={{ fill: '#8B8D8A', fontSize: 11, fontFamily: 'JetBrains Mono' }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={v => usdCompact(v)}
                    domain={[chartMin > 0 ? chartMin * 0.97 : 0, chartMax * 1.02]}
                    width={56}
                  />
                  <Tooltip
                    cursor={{ stroke: '#5A5C5B', strokeWidth: 1, strokeDasharray: '3 3' }}
                    contentStyle={{
                      background: '#101218',
                      border: '1px solid #2C3142',
                      borderRadius: 10,
                      padding: '10px 12px',
                      boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
                      fontFamily: 'JetBrains Mono'
                    }}
                    labelStyle={{ color: '#8B8D8A', fontSize: 10, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.12em' }}
                    itemStyle={{ color: '#F4F4F0', fontSize: 12, padding: '2px 0' }}
                    formatter={(v, name) => [fmtUsd(v), name === 'valueUsd' ? 'Valor' : 'Aportado']}
                    labelFormatter={l => l}
                  />
                  <Area
                    type="monotone"
                    dataKey="netDeposited"
                    stroke="#3A4256"
                    strokeWidth={1.5}
                    strokeDasharray="4 4"
                    fill="none"
                    dot={false}
                    activeDot={false}
                  />
                  <Area
                    type="monotone"
                    dataKey="valueUsd"
                    stroke={lineColor}
                    strokeWidth={1.75}
                    fill={`url(#${fillId})`}
                    dot={false}
                    activeDot={{ r: 4, fill: lineColor, stroke: '#0A0B0E', strokeWidth: 2 }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )
          })()
        )}

        {evoSeries.length >= 2 && (
          <div className="flex items-center gap-4 text-xs text-ink-2 mt-3 pt-3 border-t border-line font-mono">
            <span className="inline-flex items-center gap-1.5">
              <span
                className="inline-block w-3 h-0.5 rounded-full"
                style={{ background: totalReturnUsd >= 0 ? '#21D07A' : '#FF5360' }}
              />
              Valor del portfolio
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block w-3 h-px border-t border-dashed border-ink-3" /> Capital aportado
            </span>
          </div>
        )}
      </Card>

      {/* ── Per-broker grid ──────────────────────────────────────────────────── */}
      {brokers.length > 0 && (
        <div className="mb-8">
          <div className="mb-4">
            <p className="eyebrow mb-1">Brokers</p>
            <h3 className="text-base font-semibold text-ink-0 leading-tight">Detalle por cuenta</h3>
          </div>
          <div className={`grid gap-3 ${brokers.length === 1 ? 'grid-cols-1 max-w-sm' : brokers.length === 2 ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-2 md:grid-cols-3'}`}>
            {brokerTotals.map(b => {
              const isARS = b.currency === 'ARS'
              if (isARS) {
                const pnlArs = b.valueArs - b.invArs
                const pnlPctArs = b.invArs > 0 ? pnlArs / b.invArs : 0
                return (
                  <StatCard
                    key={b.id}
                    label={`${b.name} · ARS`}
                    value={fmtArs(b.valueArs)}
                    sub={`Inv ${fmtArs(b.invArs)} · P&L: ${pnlArs >= 0 ? '+' : '−'}ARS ${ars(Math.abs(pnlArs))} (${pctSigned(pnlPctArs)})`}
                    pnlPositive={pnlArs >= 0}
                  />
                )
              }
              const pnlUsd = b.value - b.invested
              const pnlPctUsd = b.invested > 0 ? pnlUsd / b.invested : 0
              return (
                <StatCard
                  key={b.id}
                  label={`${b.name} · USD`}
                  value={fmtUsd(b.value)}
                  sub={`Inv ${fmtUsd(b.invested)} · P&L: ${pnlUsd >= 0 ? '+' : '−'}USD ${usd(Math.abs(pnlUsd))} (${pctSigned(pnlPctUsd)})`}
                  pnlPositive={pnlUsd >= 0}
                />
              )
            })}
          </div>
        </div>
      )}

      {/* Próximos eventos del portfolio + noticias recientes.
          Cada card se renderea sólo si tiene contenido — el dashboard no
          se inunda con cards vacías. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <UpcomingEventsCard positions={positions} />
        <TopNewsCard />
      </div>

      <MonthlyTeaser />
    </div>
  )
}

function rangeLabel(id) {
  switch (id) {
    case '1D': return 'el día'
    case '1W': return 'la semana'
    case '1M': return 'el mes'
    case '6M': return '6 meses'
    case '1Y': return '1 año'
    case 'MAX': return 'todo el período'
    default: return id
  }
}

// KPI cell denso V2: label mono uppercase + value tabular + sub mono caps.
function KpiCell({ label, value, sub, tone, first }) {
  const valueColor =
    tone === 'pos' ? 'text-rendi-pos' :
    tone === 'neg' ? 'text-rendi-neg' :
    'text-ink-0'
  return (
    <div className={`px-4 py-3 flex-1 min-w-[160px] ${first ? '' : 'border-l border-line/50'}`}>
      <div className="text-[10px] font-mono uppercase tracking-label text-ink-3 leading-none">{label}</div>
      <div className={`mt-2 font-medium tabular num leading-none text-2xl tracking-tight ${valueColor}`}>{value}</div>
      <div className="text-[10px] font-mono text-ink-3 mt-1.5 leading-none truncate uppercase tracking-caps">{sub}</div>
    </div>
  )
}
