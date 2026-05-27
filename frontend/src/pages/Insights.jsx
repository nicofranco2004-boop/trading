import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import {
  PieChart, Pie, Cell, Legend, Tooltip, LineChart, Line,
  AreaChart, Area, XAxis, YAxis, CartesianGrid, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { TrendingUp, TrendingDown, AlertTriangle, Info, Activity, Trophy, Target, Layers, Clock, Stethoscope, BarChart3, Scale, PiggyBank, Wallet, CircleDollarSign, Building2, BarChart2, UserRound } from 'lucide-react'
import StatCard from '../components/StatCard'
import PageHeader from '../components/PageHeader'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import AskAIAbout from '../components/ai/AskAIAbout'
import InsightsKpiStrip from '../components/InsightsKpiStrip'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import InfoTooltip from '../components/InfoTooltip'
import CollapsibleSection from '../components/CollapsibleSection'
import LockedSection from '../components/plan/LockedSection'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react'
import { usd, fmtUsd, fmtArs, pctSigned, colorClass, MONTHS } from '../utils/format'
import InsightDelDiaHero from '../components/mobile/InsightDelDiaHero'
import { useIsMobile } from '../hooks/useIsMobile'
import { api } from '../utils/api'
import { computeBrokerValue } from '../utils/valuation'
import { lookupHistoricalDolar } from '../utils/fx'
import { buildEvolutionFromSnapshots } from '../utils/evolution'
import {
  buildCumulativeReturnSeries,
  computeDrawdownOnReturns,
  computeBestWorstMonth,
  computeAssetContribution,
  computeBestWorstClosedOp,
  computeProfitFactor,
  computeMonthlyConsistency,
  buildDrawdownTimeSeries,
  computeOpenPositionExtremes,
  computeBrokerConcentration,
  computeAssetTypeBreakdown,
  netCapitalContributed,
} from '../utils/insightsModel'
import {
  simulateSp500,
  simulateDolarCash,
  simulateArsCash,
  simulateShv,
  simulateGold,
  simulateMerval,
  simulatePlazoFijoUva,
  computeInflationCumulative,
  lookupMonthly,
} from '../utils/benchmarkSim'
import { selectDiagnostics } from '../utils/diagnostics'
import { computeProMetrics } from '../utils/insightsMetrics'
import AssetLogo from '../components/AssetLogo'
import { useAuth } from '../contexts/AuthContext'
import {
  computeAllocationMatch,
  computeObjectiveCoherence,
  computeHorizonComposition,
  computeDrawdownTolerance,
  computeConcentrationVsProfile,
} from '../utils/profileMatch'

const MONTH_NAMES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
const monthName = (m) => MONTH_NAMES[(m - 1) % 12] || ''

// Paleta v2: signal + data accents. Cero neón.
const PIE_COLORS = ['#21D07A', '#46C6E0', '#4E83FF', '#E8B14A', '#FF5360', '#8B7DFF']

// Severity → badge styling para las tarjetas de Diagnóstico (audit pattern).
// La severidad solo se codifica en el badge, no en todo el bloque, para
// mantener el peso visual del contenido.
const SEVERITY_BADGE = {
  urgent:   { label: 'Riesgo alto',      badgeCls: 'bg-rendi-neg/15 text-rendi-neg border-rendi-neg/30' },
  warn:     { label: 'Atención',         badgeCls: 'bg-rendi-warn/15 text-rendi-warn border-rendi-warn/30' },
  positive: { label: 'Insight positivo', badgeCls: 'bg-rendi-pos/15 text-rendi-pos border-rendi-pos/30' },
  info:     { label: 'Diagnóstico',      badgeCls: 'bg-bg-3 text-ink-2 border-line' },
}

// CTA por categoría — TODAS las categorías existentes tienen CTA propio.
// Si el href empieza con '#', es un anchor a una sección dentro de la misma
// página y se renderiza como <a> en lugar de <Link> para que el browser
// scrollee al elemento (react-router no hace ese scroll por defecto).
function ctaForCategory(cat) {
  const map = {
    'Riesgo':             { label: 'Ver posiciones',      href: '/posiciones' },
    'Performance':        { label: 'Ver atribución',      href: '#atribucion' },
    'Comportamiento':     { label: 'Revisar operaciones', href: '/operaciones' },
    'Moneda':             { label: 'Ver brokers',         href: '/posiciones' },
    'Posiciones abiertas': { label: 'Ver posición',       href: '/posiciones' },
  }
  // Fallback genérico en lugar de null — preferible que TODAS las cards
  // tengan CTA visible para mantener la simetría visual del audit.
  return map[cat] || { label: 'Ver detalle', href: '#diagnostico' }
}

// Balanced picker — toma 1 de cada nivel (urgent / warn / positive) si
// existen, antes de repetir el mismo nivel. Garantiza variedad visual:
// el usuario ve 'Riesgo alto + Atención + Insight positivo' en lugar de
// 3 urgentes seguidas. Si falta algún nivel, rellena con la severidad
// más alta disponible (round-robin entre los buckets restantes).
function pickBalancedDiagnosis(diagnosis, n = 3) {
  const buckets = ['urgent', 'warn', 'positive', 'info'].map(
    sev => diagnosis.filter(d => d.severity === sev)
  )
  const picked = []
  const seen = new Set()
  let pass = 0
  while (picked.length < n) {
    let added = false
    for (const bucket of buckets) {
      if (picked.length >= n) break
      const item = bucket[pass]
      if (item && !seen.has(item.id)) {
        picked.push(item)
        seen.add(item.id)
        added = true
      }
    }
    if (!added) break
    pass++
  }
  return picked
}

export default function Insights() {
  // Estructura única para desktop y mobile. La diferencia se maneja con
  // useIsMobile() abajo: en mobile mostramos la card "Insight del día" como
  // hero al top y ocultamos la curva de drawdown (decisión del producto:
  // demasiado denso para mobile).
  return <InsightsDesktop />
}

function InsightsDesktop() {
  const isMobile = useIsMobile()
  const { user } = useAuth()
  const plan = usePlanFeatures()
  // Truncar y sanitizar para usarlo como dataKey de Recharts (un solo nombre, máx 12 chars).
  // Si el "name" es un email, agarrar la parte antes del @.
  const userName = (() => {
    const raw = (user?.name || 'Vos').toString().trim()
    const base = raw.includes('@') ? raw.split('@')[0] : raw.split(' ')[0]
    return base.slice(0, 12) || 'Vos'
  })()
  const [monthly, setMonthly] = useState([])
  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [bench, setBench] = useState(null)
  const [snapshots, setSnapshots] = useState([])
  const [operations, setOperations] = useState([])
  const [dolar, setDolar] = useState(null)
  const [currency, setCurrency] = useState('USD')
  const [chartRange, setChartRange] = useState(12) // months; null = MAX

  // Selector de benchmark del chart — uno por moneda, persisted en localStorage.
  // Keys del SELECTOR (no incluimos benchmarks que dan 0% siempre — ej. "Dólar
  // quieto" rinde 0% por definición → línea plana sin info. Esas opciones
  // siguen apareciendo en las CARDS de comparativa de abajo donde sí aportan
  // el monto absoluto). Si llega un value viejo de localStorage que ya no es
  // válido (e.g. 'dolar_cash'), caemos al default.
  const VALID_USD_BENCH = ['sp500', 'tbill', 'gold']
  const VALID_ARS_BENCH = ['inflation', 'merval', 'plazo_fijo', 'pesos_cash']
  const [benchUsd, setBenchUsd] = useState(() => {
    try {
      const v = localStorage.getItem('rendi_insights_bench_usd')
      return VALID_USD_BENCH.includes(v) ? v : 'sp500'
    } catch { return 'sp500' }
  })
  const [benchArs, setBenchArs] = useState(() => {
    try {
      const v = localStorage.getItem('rendi_insights_bench_ars')
      return VALID_ARS_BENCH.includes(v) ? v : 'inflation'
    } catch { return 'inflation' }
  })
  useEffect(() => {
    try { localStorage.setItem('rendi_insights_bench_usd', benchUsd) } catch {}
  }, [benchUsd])
  useEffect(() => {
    try { localStorage.setItem('rendi_insights_bench_ars', benchArs) } catch {}
  }, [benchArs])
  const selectedBench = currency === 'USD' ? benchUsd : benchArs
  const setSelectedBench = (key) => currency === 'USD' ? setBenchUsd(key) : setBenchArs(key)
  const [loading, setLoading] = useState(true)
  // Investor profile — perfil del test (7 preguntas). Lo usamos para cruzarlo
  // contra la cartera real y mostrar match/objective coherence cards.
  // Si el user no completó el test, es {} (no null) — eso permite distinguir
  // "no data yet" de "skipped the test".
  const [investorProfile, setInvestorProfile] = useState({})
  // Comisiones: fuente de verdad es el endpoint que suma operation_type='FEE'
  // de import_normalized_tx (con conversión ARS→USD). No usamos op.commissions
  // del operations table porque queda contaminado por imports viejos con bugs.
  const [commissionsApi, setCommissionsApi] = useState(null)

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    try {
      const [mon, pos, bkrs, b, snaps, dol, ops, comm, prof] = await Promise.all([
        api.get('/monthly'),
        api.get('/positions'),
        api.get('/brokers'),
        api.get('/benchmarks').catch(() => null),
        api.get('/snapshots?days=30').catch(() => []),
        api.get('/dolar').catch(() => null),
        api.get('/operations').catch(() => []),
        api.get('/insights/commissions').catch(() => null),
        api.get('/auth/investor-profile').catch(() => ({})),
      ])
      setMonthly(mon); setPositions(pos); setBrokers(bkrs); setBench(b); setSnapshots(snaps); setDolar(dol); setOperations(ops); setCommissionsApi(comm); setInvestorProfile(prof || {})

      const arsBrokers = new Set(bkrs.filter(x => x.currency === 'ARS').map(x => x.name))
      // Todo lo que no sea ARS (USDT, USD) se valúa directo en USD sin conversión
      const usdtBrokers = new Set(bkrs.filter(x => x.currency !== 'ARS').map(x => x.name))
      const arsSyms = [...new Set(pos.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => p.asset + '.BA'))]
      const usdtSyms = [...new Set(pos.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => p.asset))]
      const all = [...arsSyms, ...usdtSyms].join(',')
      if (all) {
        try { setPrices(await api.get(`/prices?symbols=${all}`)) } catch {}
      }
    } catch (e) {
      console.error('Insights loadAll error:', e)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className="page-shell text-center text-ink-3" aria-live="polite">Cargando…</div>

  // ── Distribution ──
  // pieData    → por broker (gráfico de torta "Por broker", concentración por broker).
  // assetPieData → por activo (gráfico "Por activo", diagnóstico de concentración por
  //                instrumento). Agrega posiciones del mismo asset entre brokers/lotes.
  //                Excluye cash. Esto es lo que un usuario espera ver al preguntarse
  //                "¿qué tan expuesto estoy a un único activo?".
  const tcBlue = dolar?.blue?.venta || 1415
  const pieData = brokers
    .map(b => ({ name: b.name, value: +computeBrokerValue(positions, prices, b, tcBlue).value.toFixed(2) }))
    .filter(x => x.value > 0)
  const totalPortfolio = pieData.reduce((s, x) => s + x.value, 0)

  const assetPieData = (() => {
    if (!positions.length || totalPortfolio <= 0) return []
    const valuesByAsset = {}
    for (const p of positions) {
      if (p.is_cash) continue
      const broker = brokers.find(b => b.name === p.broker)
      let val = 0
      if (broker?.currency === 'ARS') {
        const priceArs = p.price_override ?? prices[p.asset + '.BA']
        val = priceArs != null ? (priceArs * (p.quantity || 0)) / tcBlue : (p.invested || 0) / tcBlue
      } else {
        const price = p.price_override ?? prices[p.asset]
        val = price != null ? price * (p.quantity || 0) : (p.invested || 0)
      }
      const k = (p.asset || '').toUpperCase()
      valuesByAsset[k] = (valuesByAsset[k] || 0) + val
    }
    return Object.entries(valuesByAsset)
      .map(([asset, v]) => ({ name: asset, value: +v.toFixed(2) }))
      .filter(x => x.value > 0)
      .sort((a, b) => b.value - a.value)
  })()

  // Positions con value_usd resuelto — necesario para los cards de perfil
  // del inversor (classifyAssetBucket + computeAllocationBuckets). Misma
  // lógica de valuación que assetPieData arriba.
  const positionsWithValue = (() => {
    return positions.map(p => {
      if (p.is_cash) {
        // Cash: el value es la quantity directamente (en la currency del broker).
        // Si broker ARS, convertimos a USD.
        const broker = brokers.find(b => b.name === p.broker)
        const qty = p.quantity || 0
        const val = broker?.currency === 'ARS' ? qty / tcBlue : qty
        return { ...p, value_usd: val }
      }
      const broker = brokers.find(b => b.name === p.broker)
      let val = 0
      if (broker?.currency === 'ARS') {
        const priceArs = p.price_override ?? prices[p.asset + '.BA']
        val = priceArs != null ? (priceArs * (p.quantity || 0)) / tcBlue : (p.invested || 0) / tcBlue
      } else {
        const price = p.price_override ?? prices[p.asset]
        val = price != null ? price * (p.quantity || 0) : (p.invested || 0)
      }
      return { ...p, value_usd: val }
    })
  })()

  // Card data del perfil del inversor — cruzan profile con cartera real.
  // Devuelven status='ready' | 'no_profile' | 'no_portfolio' | 'no_data' y
  // los datos necesarios para que el componente UI renderice texto descriptivo.
  // El drawdown real lo pasamos como número absoluto (computeDrawdownOnReturns
  // devuelve negativo); se computa más abajo en `drawdown`.
  const allocationCard = computeAllocationMatch(investorProfile, positionsWithValue, brokers)
  const objectiveCard = computeObjectiveCoherence(investorProfile, positionsWithValue, brokers)
  const horizonCard = computeHorizonComposition(investorProfile, positionsWithValue, brokers)
  const concentrationCard = computeConcentrationVsProfile(investorProfile, positionsWithValue, brokers)

  // Cost basis y P&L no realizado (live, sobre posiciones abiertas).
  const totalCostBasis = brokers.reduce((s, b) => {
    return s + computeBrokerValue(positions, prices, b, tcBlue).invested
  }, 0)
  const unrealizedPnl = totalPortfolio - totalCostBasis

  // ── Cumulative performance series (monthly + today) ──
  const globalMonthly = [...monthly.filter(m => m.broker === 'global')].sort((a, b) =>
    a.year !== b.year ? a.year - b.year : a.month - b.month
  )
  const monthKey = (y, m) => `${y}-${String(m).padStart(2, '0')}`

  // ── Hero: métricas macro del portfolio ────────────────────────────────────
  // Capital aportado consolidado (mismo criterio que Dashboard).
  const capitalContributed = netCapitalContributed(globalMonthly)
  // P&L realizado acumulado = Σ pnl_realized de las entradas globales.
  const realizedPnl = globalMonthly.reduce((s, m) => s + (m.pnl_realized || 0), 0)
  // Resultado total = Valor actual − Capital aportado (incluye realizado y no realizado).
  const totalResult = totalPortfolio - capitalContributed
  const totalResultPct = capitalContributed > 0 ? (totalResult / capitalContributed) * 100 : 0

  // ── Money-Weighted Return (MWR) ──
  // Coherente con el dashboard (que muestra `(valor − aportado) / aportado`).
  // Para cada punto t:
  //   net_flows_t = Σ(deposits − withdrawals) hasta el mes t
  //   invested_t  = baseline + net_flows_t
  //   value_t     = capital_final del mes (cierra con realized para meses
  //                 cerrados; con realized + unrealized para el mes en curso)
  //   total %     = (value_t − invested_t) / invested_t
  //   realized %  = (Σ pnl_realized hasta t) / invested_t
  //
  // Clamp inferior a −99% por seguridad — si `value_t < 0` por data corrupta
  // (residuos de imports antiguos), el % no se va a < −100% y no rompe el
  // rebase chain-linked del chart de benchmarks.
  //
  // ARS: convertir value_t e invested_t a pesos usando el dólar blue del mes
  // correspondiente (los flujos quedan al fx de cuando ocurrieron — aproximación).
  const seriesUsd = []
  const seriesArs = []

  // ── Phase 7 — Daily granularity from snapshots when available ──
  // ≥2 snapshots → daily evolution (Total Return %, realized step-matched
  // from monthly_entries). Else fallback al cómputo mensual de abajo.
  const dailyEvo = buildEvolutionFromSnapshots(snapshots, globalMonthly, bench, tcBlue)
  if (dailyEvo) {
    seriesUsd.push(...dailyEvo.seriesUsd)
    seriesArs.push(...dailyEvo.seriesArs)
  } else if (globalMonthly.length > 0) {
    const baseline = globalMonthly[0].capital_inicio || 0
    const firstKey = monthKey(globalMonthly[0].year, globalMonthly[0].month)

    const dolarKeys = bench?.dolar_blue ? Object.keys(bench.dolar_blue).sort() : []
    const lookupDolar = (key) => {
      if (!bench?.dolar_blue) return null
      if (bench.dolar_blue[key]) return bench.dolar_blue[key]
      let found = null
      for (const k of dolarKeys) {
        if (k <= key) found = k
        else break
      }
      if (!found) found = dolarKeys[0]
      return found ? bench.dolar_blue[found] : null
    }
    const fxBase = lookupDolar(firstKey)

    // Punto inicial = 0%
    seriesUsd.push({
      key: firstKey,
      label: `${MONTHS[globalMonthly[0].month - 1].slice(0, 3)} ${String(globalMonthly[0].year).slice(2)}`,
      realized: 0, total: 0,
    })
    seriesArs.push({
      key: firstKey,
      label: `${MONTHS[globalMonthly[0].month - 1].slice(0, 3)} ${String(globalMonthly[0].year).slice(2)}`,
      realized: 0, total: 0,
    })

    // TWR chain-linked vía Modified Dietz — mismo método que
    // buildEvolutionFromSnapshots() usa cuando hay daily granularity.
    //
    // Bug fix: la fórmula vieja (dollar-weighted: (value - invested) / invested)
    // se rompe cuando hay retiros grandes. Caso real: el user retira US$ 177k
    // para impuestos personales y queda con US$ 65k invertidos. La fórmula vieja
    // dividía por ese 65k y mostraba "+94% mes" cuando en realidad la cartera
    // siguió rindiendo normal — el spike es artefacto del denominador chico
    // post-withdrawal, no rendimiento real.
    //
    // TWR neutraliza flujos: el retiro NO afecta el % reportado. Es la métrica
    // correcta para comparar contra SPY (que tampoco tiene flujos).
    //
    // Para cada mes:
    //   net_flow     = deposits - withdrawals
    //   avg_capital  = cap_inicio + 0.5 × net_flow  (Modified Dietz)
    //   period_ret   = (cap_final - cap_inicio - net_flow) / avg_capital
    //   idx_t        = idx_(t-1) × (1 + period_ret)
    //
    // Caso especial: primer mes con cap_inicio=0 y depósito grande (típico
    // de imports iniciales) usa el depósito como capital base completo en
    // lugar de avg, para evitar inflar 2x el retorno del mes.
    let cumIdx = 1.0
    let cumRealized = 0
    let cumIdxArs = 1.0
    let cumRealizedArs = 0
    const baselineArs = baseline * (fxBase || 0)
    // Capital aportado NETO (deposits - withdrawals) acumulado. Coincide
    // con lo que muestra el Dashboard. Si Pablo deposita $200k y retira
    // $180k para impuestos, cum_net queda en $20k (no $200k del bruto).
    let cumNetDeposits = baseline
    // Peak histórico del net acumulado. Usamos esto como denominador
    // SAFE cuando hay retiros temporales — evita que el realized% spikee
    // a 90% post-withdrawal (cuando el net actual queda muy chico).
    // Cuando el net vuelve a niveles normales, retomamos el net actual.
    let peakNetDeposits = baseline

    // Función para denominador estable: usa net actual si está al menos
    // al 60% del peak; sino, usa peak (el capital que TUVO el portfolio
    // en su mejor momento — el retiro fue ruido temporal).
    const safeDenom = (netDep, peakDep) =>
      netDep >= peakDep * 0.6 && netDep > 1000 ? netDep : peakDep

    for (let i = 0; i < globalMonthly.length; i++) {
      const m = globalMonthly[i]
      const isFirst = i === 0
      const ci = m.capital_inicio || 0
      const cf = m.capital_final || 0
      const net = (m.deposits || 0) - (m.withdrawals || 0)
      cumRealized += (m.pnl_realized || 0)
      cumNetDeposits += net
      if (cumNetDeposits > peakNetDeposits) peakNetDeposits = cumNetDeposits

      // Modified Dietz USD con heurística big-withdrawal: cuando el flow
      // negativo supera 30% del capital inicial, asumimos que pasó al final
      // del período (usamos ci como denom) en vez de mid-period (avgCap chico
      // que infla el ratio). Evita spikes artificiales cuando el user retira
      // plata grande el mismo mes que cierra una posición ganadora.
      const isImportInitial = isFirst && ci === 0 && net > 0
      const flowRatio = ci > 0 ? Math.abs(net) / ci : 0
      const isBigWithdraw = net < 0 && flowRatio > 0.3
      const avgCap = isImportInitial ? net : (isBigWithdraw ? ci : ci + 0.5 * net)
      const rRaw = avgCap > 0 ? (cf - ci - net) / avgCap : 0
      const r = Math.min(Math.max(rRaw, -0.99), 0.5)
      cumIdx *= (1 + r)

      const totalPct = +((cumIdx - 1) * 100).toFixed(2)
      const denom = safeDenom(cumNetDeposits, peakNetDeposits)
      const realPct = denom > 0 ? +((cumRealized / denom) * 100).toFixed(2) : 0

      seriesUsd.push({
        key: monthKey(m.year, m.month),
        label: `${MONTHS[m.month - 1].slice(0, 3)} ${String(m.year).slice(2)}`,
        realized: realPct,
        total: totalPct,
      })

      // ARS: misma fórmula TWR, con flujos al fx del mes
      if (fxBase && bench?.dolar_blue) {
        const fx = lookupDolar(monthKey(m.year, m.month)) || fxBase
        const ciArs = ci * fx
        const cfArs = cf * fx
        const netArs = net * fx
        const avgArs = isImportInitial ? netArs : ciArs + 0.5 * netArs
        const rArsRaw = avgArs > 0 ? (cfArs - ciArs - netArs) / avgArs : 0
        const rArs = Math.max(rArsRaw, -0.99)
        cumIdxArs *= (1 + rArs)
        cumRealizedArs += (m.pnl_realized || 0) * fx

        const totalPctArs = +((cumIdxArs - 1) * 100).toFixed(2)
        const denomArs = safeDenom(cumNetDeposits, peakNetDeposits) * fx
        const realPctArs = denomArs > 0 ? +((cumRealizedArs / denomArs) * 100).toFixed(2) : 0
        seriesArs.push({
          key: monthKey(m.year, m.month),
          label: `${MONTHS[m.month - 1].slice(0, 3)} ${String(m.year).slice(2)}`,
          realized: realPctArs,
          total: totalPctArs,
        })
      }
    }

    // Punto "Hoy" — extiende el último mes con live portfolio.
    if (totalPortfolio > 0 && globalMonthly.length > 0) {
      const lastM = globalMonthly[globalMonthly.length - 1]
      const lastCf = lastM.capital_final || 0
      if (lastCf > 0) {
        const rLive = (totalPortfolio - lastCf) / lastCf
        const rLiveClamped = Math.max(rLive, -0.99)
        cumIdx *= (1 + rLiveClamped)
      }
      const totalLive = +((cumIdx - 1) * 100).toFixed(2)
      const denomLive = safeDenom(cumNetDeposits, peakNetDeposits)
      const realLive = denomLive > 0 ? +((cumRealized / denomLive) * 100).toFixed(2) : 0
      seriesUsd.push({ key: 'today', label: 'Hoy', realized: realLive, total: totalLive })

      // ARS "Hoy" — extiende cumIdxArs igual que en USD
      if (fxBase && tcBlue) {
        const lastCfArs = lastCf * tcBlue
        const valueArsLive = totalPortfolio * tcBlue
        if (lastCfArs > 0) {
          const rLiveArs = (valueArsLive - lastCfArs) / lastCfArs
          const rLiveArsClamped = Math.max(rLiveArs, -0.99)
          cumIdxArs *= (1 + rLiveArsClamped)
        }
        const totalArsLive = +((cumIdxArs - 1) * 100).toFixed(2)
        const denomArsLive = safeDenom(cumNetDeposits, peakNetDeposits) * tcBlue
        const realArsLive = denomArsLive > 0 ? +((cumRealizedArs / denomArsLive) * 100).toFixed(2) : 0
        seriesArs.push({ key: 'today', label: 'Hoy', realized: realArsLive, total: totalArsLive })
      }
    }
  }

  // ── Series dedicadas para el gráfico de benchmarks ─────────────────────────
  // Siempre se construyen desde el loop mensual (NUNCA desde dailyEvo) para:
  //  1. Cubrir toda la historia desde el primer mes registrado, no solo 30 días
  //  2. Garantizar que los puntos son "YYYY-MM", coincidiendo con bench.sp500
  //     y bench.inflation_ar que también son mensuales.
  //  3. USD: globalMonthly (total en USD — incluye ARS brokers convertidos al blue del mes)
  //  4. ARS: solo brokers ARS, convertidos a pesos × blue del mes, comparados con inflación.
  //     No tiene sentido mezclar posiciones USD al tipo de cambio → inflación.
  const arsBrokerNames = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))

  // Label legible para una clave "YYYY-MM" o 'today'
  const benchLabel = (k) => {
    if (k === 'today') return 'Hoy'
    const [yr, mo] = k.split('-')
    const MON = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']
    return `${MON[(+mo) - 1]} '${yr.slice(2)}`
  }

  // Lookup dolar blue con fallback (reutilizable en ambas series)
  const blueKeys = bench?.dolar_blue ? Object.keys(bench.dolar_blue).sort() : []
  const lookupBlue = (mk) => {
    if (!bench?.dolar_blue) return null
    if (bench.dolar_blue[mk]) return bench.dolar_blue[mk]
    let found = null
    for (const k of blueKeys) { if (k <= mk) found = k; else break }
    if (!found && blueKeys.length) found = blueKeys[0]
    return found ? bench.dolar_blue[found] : null
  }

  // benchSeriesUsd — portfolio total en USD (globalMonthly) en % MWR acumulado.
  // Misma fórmula que seriesUsd arriba (consistente con el dashboard).
  const benchSeriesUsd = (() => {
    if (globalMonthly.length === 0) return []
    const out = []
    const baseline = globalMonthly[0].capital_inicio || 0
    let netFlows = 0, cumRealized = 0
    // Peak portfolio value y peak invested capital — usados como denominador
    // estable cuando hay retiros grandes. Sin esto, un withdraw que achica
    // `invested` (deposits - withdrawals) hace explotar el ratio
    // (value - invested) / invested. Caso real: papá retira \$70k de \$100k,
    // cierra una posición con +\$20k → invested cae a -\$50k → ratio explota.
    let peakInvested = baseline > 0 ? baseline : 0
    let peakValue = baseline > 0 ? baseline : 0

    // Si current_invested cae bajo 60% del peak (señal de retiro grande),
    // usamos el peak como base "real" del capital que llegó a trabajar.
    const stableInvested = (cur, peak) =>
      (cur >= peak * 0.6 && cur > 1000) ? cur : peak

    const firstMk = monthKey(globalMonthly[0].year, globalMonthly[0].month)
    out.push({ key: firstMk, label: benchLabel(firstMk), total: 0, realized: 0 })
    for (const m of globalMonthly) {
      netFlows += (m.deposits || 0) - (m.withdrawals || 0)
      cumRealized += (m.pnl_realized || 0)
      const investedNow = baseline + netFlows
      if (investedNow > peakInvested) peakInvested = investedNow
      if ((m.capital_final || 0) > peakValue) peakValue = m.capital_final || 0

      // Numerador: gain REAL = value - investedNow (P&L = lo que tenés menos
      // lo que está aportado neto AHORA). Si retirás \$70k, investedNow baja
      // y capital_final también — pero la diferencia (el "gain") refleja
      // correctamente solo las ganancias.
      // Denominador: stableInvested usa peak cuando investedNow se achicó por
      // un withdraw, así no inflamos el % al dividir por número chico.
      const gain = (m.capital_final || 0) - investedNow
      const denom = stableInvested(investedNow, peakInvested)
      const rawTotal = denom > 0 ? (gain / denom) * 100 : 0
      const total = Math.min(Math.max(rawTotal, -99), 200)
      const real  = denom > 0 ? (cumRealized / denom) * 100 : 0
      const k = monthKey(m.year, m.month)
      out.push({ key: k, label: benchLabel(k), total: +total.toFixed(2), realized: +real.toFixed(2) })
    }
    // Punto "Hoy"
    if (totalPortfolio > 0) {
      if (totalPortfolio > peakValue) peakValue = totalPortfolio
      const investedNow = baseline + netFlows
      if (investedNow > peakInvested) peakInvested = investedNow
      const gain = totalPortfolio - investedNow
      const denom = stableInvested(investedNow, peakInvested)
      const rawTotal = denom > 0 ? (gain / denom) * 100 : 0
      const total = Math.min(Math.max(rawTotal, -99), 200)
      const real  = denom > 0 ? (cumRealized / denom) * 100 : 0
      out.push({ key: 'today', label: 'Hoy', total: +total.toFixed(2), realized: +real.toFixed(2) })
    }
    // Deduplicar por key (el primer mes aparece 2 veces: punto base + primera iteración del loop)
    const seen = new Set()
    return out.filter(p => { if (seen.has(p.key)) return false; seen.add(p.key); return true })
  })()

  // benchSeriesArs — solo brokers ARS, capital en pesos (USD × blue del mes) en % acumulado MWR.
  const benchSeriesArs = (() => {
    if (arsBrokerNames.size === 0 || !bench?.dolar_blue) return []
    // Agrupar monthly entries de brokers ARS por mes (suma si hay varios brokers)
    const byMk = {}
    for (const m of monthly) {
      if (!arsBrokerNames.has(m.broker)) continue
      const k = monthKey(m.year, m.month)
      if (!byMk[k]) byMk[k] = { year: m.year, month: m.month, capital_inicio: 0, capital_final: 0, deposits: 0, withdrawals: 0, pnl_realized: 0 }
      byMk[k].capital_inicio  += m.capital_inicio || 0
      byMk[k].capital_final   += m.capital_final || 0
      byMk[k].deposits        += m.deposits || 0
      byMk[k].withdrawals     += m.withdrawals || 0
      byMk[k].pnl_realized    += m.pnl_realized || 0
    }
    const arsMonths = Object.entries(byMk).sort(([a], [b]) => a < b ? -1 : 1)
    if (arsMonths.length === 0) return []

    const firstKey = arsMonths[0][0]
    const blueBase = lookupBlue(firstKey)
    if (!blueBase) return []

    const out = []
    const baselinePesos = arsMonths[0][1].capital_inicio * blueBase
    let netFlowsPesos = 0, cumRealizedPesos = 0
    // Mismo treatment de peak-stable denom que benchSeriesUsd (ver arriba)
    let peakInvestedPesos = baselinePesos > 0 ? baselinePesos : 0
    const stableInvestedPesos = (cur, peak) =>
      (cur >= peak * 0.6 && cur > 1000) ? cur : peak
    out.push({ key: firstKey, label: benchLabel(firstKey), total: 0, realized: 0 })

    for (const [k, m] of arsMonths) {
      const fx = lookupBlue(k) || blueBase
      const net = (m.deposits || 0) - (m.withdrawals || 0)
      netFlowsPesos += net * fx
      cumRealizedPesos += (m.pnl_realized || 0) * fx
      const investedNowPesos = baselinePesos + netFlowsPesos
      if (investedNowPesos > peakInvestedPesos) peakInvestedPesos = investedNowPesos
      const denomP = stableInvestedPesos(investedNowPesos, peakInvestedPesos)
      const valuePesos = (m.capital_final || 0) * fx
      const gainPesos = valuePesos - investedNowPesos
      const rawTotal   = denomP > 0 ? (gainPesos / denomP) * 100 : 0
      const total      = Math.min(Math.max(rawTotal, -99), 200)
      const real       = denomP > 0 ? (cumRealizedPesos / denomP) * 100 : 0
      out.push({ key: k, label: benchLabel(k), total: +total.toFixed(2), realized: +real.toFixed(2) })
    }
    // Punto "Hoy" — valor live de posiciones ARS al blue actual
    const arsLiveUsd = brokers
      .filter(b => arsBrokerNames.has(b.name))
      .reduce((s, b) => s + computeBrokerValue(positions, prices, b, tcBlue).value, 0)
    if (arsLiveUsd > 0) {
      const valueNow = arsLiveUsd * tcBlue
      const investedNowPesos = baselinePesos + netFlowsPesos
      if (investedNowPesos > peakInvestedPesos) peakInvestedPesos = investedNowPesos
      const denomP = stableInvestedPesos(investedNowPesos, peakInvestedPesos)
      const gainPesos = valueNow - investedNowPesos
      const rawTotal = denomP > 0 ? (gainPesos / denomP) * 100 : 0
      const total = Math.min(Math.max(rawTotal, -99), 200)
      const real  = denomP > 0 ? (cumRealizedPesos / denomP) * 100 : 0
      out.push({ key: 'today', label: 'Hoy', total: +total.toFixed(2), realized: +real.toFixed(2) })
    }
    // Deduplicar
    const seen = new Set()
    return out.filter(p => { if (seen.has(p.key)) return false; seen.add(p.key); return true })
  })()

  // Selector de serie del portfolio (USD vs ARS) y label del benchmark.
  const activeSeries = currency === 'USD' ? benchSeriesUsd : benchSeriesArs

  // Labels visibles del benchmark seleccionado (para legend del chart).
  const BENCHMARK_LABELS = {
    sp500:      'S&P 500',
    tbill:      'T-Bills USD',
    gold:       'Oro',
    dolar_cash: 'Dólar quieto',
    inflation:  'Inflación AR',
    merval:     'Merval',
    plazo_fijo: 'Plazo fijo UVA',
    pesos_cash: 'Pesos cash (blue)',
  }
  const benchmarkKey = BENCHMARK_LABELS[selectedBench] || 'Benchmark'

  // Opciones del selector según moneda. Cada una marca `available` según si
  // tenemos data del backend (gracias al fire-and-forget el bench puede llegar
  // tarde y algunas opciones aparecen disabled al inicio).
  // AUDIT FIX 2026-05-26: chequeamos Object.keys().length > 0 (no solo `!!`)
  // porque si yfinance falla y devuelve {}, !!{} es true pero el chart queda
  // vacío. El check más estricto evita habilitar opciones sin data real.
  const hasData = (map) => !!map && Object.keys(map).length > 0
  // Dólar quieto NO está en el selector porque su línea es siempre 0% (rinde
  // 0% por definición — no aporta info en el chart). Sigue apareciendo en las
  // cards de "Comparativa con benchmarks" donde sí muestra el monto absoluto.
  const BENCHMARK_OPTIONS_USD = [
    { key: 'sp500',      label: 'S&P 500',         available: hasData(bench?.sp500) },
    { key: 'tbill',      label: 'T-Bills USD',     available: hasData(bench?.shv) },
    { key: 'gold',       label: 'Oro (GLD)',       available: hasData(bench?.gld) },
  ]
  const BENCHMARK_OPTIONS_ARS = [
    { key: 'inflation',  label: 'Inflación AR',    available: hasData(bench?.inflation_ar) },
    { key: 'merval',     label: 'Merval',          available: hasData(bench?.merval) && hasData(bench?.dolar_blue) },
    { key: 'plazo_fijo', label: 'Plazo fijo UVA',  available: hasData(bench?.uva) && hasData(bench?.dolar_blue) },
    { key: 'pesos_cash', label: 'Pesos cash (blue)', available: hasData(bench?.dolar_blue) },
  ]
  const benchmarkOptions = currency === 'USD' ? BENCHMARK_OPTIONS_USD : BENCHMARK_OPTIONS_ARS

  // Para el gráfico de benchmarks siempre usamos granularidad MENSUAL:
  // 1. Los datos de sp500 e inflation_ar son mensuales — comparar con puntos
  //    diarios da una curva de inflación rara (escalones dentro del mes).
  // 2. effectiveRange=N significa "últimos N meses", no "últimos N puntos".
  //    Con data diaria, slice(-12) daría 12 días en lugar de 12 meses.
  //
  // Resampleo: para cada mes conservamos el ÚLTIMO punto del mes (el más
  // reciente), que representa el cierre mensual. "today" se mantiene aparte.
  const activeSeriesMonthly = (() => {
    const historical = activeSeries.filter(s => s.key !== 'today')
    const today = activeSeries.find(s => s.key === 'today')
    // Agrupar por mes (YYYY-MM) y quedarse con el último punto de cada mes.
    const byMonth = {}
    for (const s of historical) {
      const mk = s.key.slice(0, 7)
      byMonth[mk] = s  // overwrite → se queda con el último del mes
    }
    const sortedMonthly = Object.values(byMonth).sort((a, b) => a.key < b.key ? -1 : 1)
    return today ? [...sortedMonthly, today] : sortedMonthly
  })()

  // ARS always capped at 12 months (más atrás = inflación histórica hace el gráfico inútil).
  // USD: el usuario elige el rango con los tabs.
  const effectiveRange = currency === 'ARS' ? 12 : chartRange

  // Filtrar al rango — ahora slice(-N) sobre datos mensuales = N meses correctos.
  const windowSeries = (() => {
    if (!effectiveRange || activeSeriesMonthly.length === 0) return activeSeriesMonthly
    const historical = activeSeriesMonthly.filter(s => s.key !== 'today')
    const today = activeSeriesMonthly.find(s => s.key === 'today')
    const sliced = historical.slice(-effectiveRange)
    return today ? [...sliced, today] : sliced
  })()

  // Construir chartData rebased: ambas líneas arrancan en 0% en el primer
  // punto de la ventana — permite comparación justa en cualquier sub-período.
  // Fórmula de rebase (chain-linking TWRR):
  //   rebased = ((100 + current) / (100 + base) − 1) × 100
  //
  // NOTA: cuando hay snapshots, las keys de la serie son "YYYY-MM-DD" (diarias),
  // pero bench.sp500 y bench.inflation_ar son mensuales ("YYYY-MM").
  // Normalizamos siempre con monthKeyOf(key) = key.slice(0,7) para el lookup.
  const chartData = (() => {
    if (windowSeries.length === 0) return []

    const monthKeyOf = k => (k === 'today' ? k : k.slice(0, 7))
    const rawFirstKey = (windowSeries.find(x => x.key !== 'today') || windowSeries[0]).key
    const windowFirstMonthKey = monthKeyOf(rawFirstKey)

    // ── Shadow portfolio del benchmark seleccionado ──────────────────────
    // Apples-to-apples: aplicamos TUS flows reales al benchmark elegido.
    // No es "lump sum desde día 1" — los flows se ejecutan al precio del mes.
    //
    // Fórmula (misma que la línea verde del portfolio):
    //   gain = shadow_value - investedNow
    //   pct  = gain / stableInvested(investedNow, peakInvested) × 100
    //
    // Safeguards:
    //   1. Peak-stable denom: si invested cae < 60% del peak (retiro grande),
    //      usamos peak como base — evita inflar % por retiros que achican
    //      el denominador.
    //   2. Clamp [-99, 200] para evitar outliers visuales.
    //
    // Cada benchmark tiene su simulador en benchmarkSim.js — cada uno maneja
    // su propio lookup interno con fallback al mes anterior disponible.
    const stableInv = (cur, peak) => (cur >= peak * 0.6 && cur > 1000) ? cur : peak

    function buildShadowFromSim(simResult, latestBenchPrice) {
      const result = new Map()
      if (!simResult || !simResult.series || simResult.series.length === 0) return result
      const baselineUsd = globalMonthly[0]?.capital_inicio || 0
      let netFlows = 0
      let peakInvested = baselineUsd > 0 ? baselineUsd : 0

      // Index sim.series por key para lookup O(1).
      const simByKey = {}
      for (const p of simResult.series) simByKey[p.key] = p.value

      for (const m of globalMonthly) {
        const mk = monthKey(m.year, m.month)
        netFlows += (m.deposits || 0) - (m.withdrawals || 0)
        const investedNow = baselineUsd + netFlows
        if (investedNow > peakInvested) peakInvested = investedNow
        const denom = stableInv(investedNow, peakInvested)
        const shadowValue = simByKey[mk]
        if (shadowValue == null) continue
        const gain = shadowValue - investedNow
        const pct = denom > 0 ? (gain / denom) * 100 : 0
        result.set(mk, +Math.min(Math.max(pct, -99), 200).toFixed(2))
      }

      // "Today": para benchmarks tipo S&P/SHV/GLD (con finalUnits), si tenemos
      // un precio MÁS RECIENTE que el último mes del user, lo usamos para
      // extrapolar al estado actual. Si no, usamos el último value del sim.
      //
      // Cubre el caso donde el user no cargó la entry del mes en curso pero
      // el bench ya tiene precio actualizado.
      const last = simResult.series[simResult.series.length - 1]
      const investedNow = baselineUsd + netFlows
      const denom = stableInv(investedNow, peakInvested)
      const todayShadowValue =
        (latestBenchPrice != null && simResult.finalUnits != null && latestBenchPrice > 0)
          ? simResult.finalUnits * latestBenchPrice
          : last.value
      const gain = todayShadowValue - investedNow
      const pct = denom > 0 ? (gain / denom) * 100 : 0
      result.set('today', +Math.min(Math.max(pct, -99), 200).toFixed(2))
      return result
    }

    // Helper para obtener el último precio disponible del map del benchmark
    // (usado en el "today" — extrapola si el bench tiene data más reciente
    // que la última entry del user).
    function latestPriceOf(priceMap) {
      if (!priceMap) return null
      const keys = Object.keys(priceMap).sort()
      return keys.length > 0 ? priceMap[keys[keys.length - 1]] : null
    }

    function buildInflationCumPct() {
      // Inflación: % macro acumulativo, NO portfolio. cum = Π(1 + ipc_m)
      const result = new Map()
      if (!bench?.inflation_ar) return result
      let cum = 1
      let firstSeen = false
      for (const m of globalMonthly) {
        const mk = monthKey(m.year, m.month)
        if (!firstSeen) {
          result.set(mk, 0)  // primer mes = base 0%
          firstSeen = true
          continue
        }
        const ipc = bench.inflation_ar[mk]
        if (ipc != null) cum *= 1 + ipc / 100
        result.set(mk, +((cum - 1) * 100).toFixed(2))
      }
      // Today: mismo valor que el último mes (inflación es histórica, no live)
      const allKeys = [...result.keys()]
      if (allKeys.length > 0) {
        result.set('today', result.get(allKeys[allKeys.length - 1]))
      }
      return result
    }

    // Dispatcher: cada benchmark seleccionado calcula su propio shadowPctByMonth.
    // Para benchmarks con finalUnits (S&P, SHV, GLD), pasamos latestBenchPrice
    // para que el "today" del shadow extrapole al precio actual del benchmark
    // (caso del audit M3: user que no cargó mes en curso pero el bench sí lo tiene).
    let shadowPctByMonth = new Map()
    if (selectedBench === 'sp500' && bench?.sp500) {
      shadowPctByMonth = buildShadowFromSim(
        simulateSp500(globalMonthly, bench.sp500),
        latestPriceOf(bench.sp500),
      )
    } else if (selectedBench === 'tbill' && bench?.shv) {
      shadowPctByMonth = buildShadowFromSim(
        simulateShv(globalMonthly, bench.shv),
        latestPriceOf(bench.shv),
      )
    } else if (selectedBench === 'gold' && bench?.gld) {
      shadowPctByMonth = buildShadowFromSim(
        simulateGold(globalMonthly, bench.gld),
        latestPriceOf(bench.gld),
      )
    } else if (selectedBench === 'dolar_cash') {
      shadowPctByMonth = buildShadowFromSim(simulateDolarCash(globalMonthly))
    } else if (selectedBench === 'inflation') {
      shadowPctByMonth = buildInflationCumPct()
    } else if (selectedBench === 'merval' && bench?.merval && bench?.dolar_blue) {
      // Merval no usa finalUnits porque la conversión USD-ARS es compleja —
      // dejamos el último value del sim como "today".
      shadowPctByMonth = buildShadowFromSim(
        simulateMerval(globalMonthly, bench.merval, bench.dolar_blue),
      )
    } else if (selectedBench === 'plazo_fijo' && bench?.uva && bench?.dolar_blue) {
      shadowPctByMonth = buildShadowFromSim(
        simulatePlazoFijoUva(globalMonthly, bench.uva, bench.dolar_blue),
      )
    } else if (selectedBench === 'pesos_cash' && bench?.dolar_blue) {
      shadowPctByMonth = buildShadowFromSim(
        simulateArsCash(globalMonthly, bench.dolar_blue),
      )
    }

    const withBench = windowSeries.map(s => {
      let benchPct = null
      if (shadowPctByMonth.size > 0) {
        const mk = monthKeyOf(s.key)
        if (shadowPctByMonth.has(mk)) {
          benchPct = shadowPctByMonth.get(mk)
        } else if (s.key === 'today' && shadowPctByMonth.has('today')) {
          benchPct = shadowPctByMonth.get('today')
        } else {
          // Fallback: último mes <= mk (cubre snapshots diarios entre meses)
          const sortedSk = [...shadowPctByMonth.keys()].filter(k => k !== 'today').sort()
          let found = null
          for (const k of sortedSk) { if (k <= mk) found = k; else break }
          if (found) benchPct = shadowPctByMonth.get(found)
        }
      }
      return { ...s, benchPct }
    })

    const first = withBench[0]
    const baseTotal = first.total ?? 0
    const baseRealized = first.realized ?? 0
    const baseBench = first.benchPct ?? 0

    return withBench.map(s => {
      const rebaseTotal = s.total != null
        ? +((((100 + s.total) / (100 + baseTotal)) - 1) * 100).toFixed(2) : null
      const rebaseRealized = s.realized != null
        ? +((((100 + s.realized) / (100 + baseRealized)) - 1) * 100).toFixed(2) : null
      // Rebasear el benchmark al inicio del rango visible para que ambas
      // líneas arranquen en 0%. Sin esto, si el user mira "2A" pero el shadow
      // portfolio ya acumuló +20% antes del inicio del rango, la línea bench
      // arrancaría en +20% (inconsistente con la portfolio del user que sí
      // arranca en 0%).
      const rebaseBench = s.benchPct != null
        ? +((((100 + s.benchPct) / (100 + baseBench)) - 1) * 100).toFixed(2) : null
      return {
        label: s.label,
        [`${userName} P/L total`]: rebaseTotal,
        [`${userName} P/L realizado`]: rebaseRealized,
        [benchmarkKey]: rebaseBench,
      }
    })
  })()

  // ── Insight: Mejor / Peor mes ──
  // Ahora excluye el mes calendario actual (incompleto) — comparar un mes a
  // medio camino contra meses cerrados es injusto.
  const bestWorstMonth = computeBestWorstMonth(globalMonthly)

  // ── Insight 2: Max drawdown — sobre TWRR (rendimiento ajustado por flujos) ──
  // Reemplaza el cálculo viejo sobre valor absoluto, que reportaba retiros
  // grandes como caídas y depósitos como recuperaciones falsas.
  // Ahora el drawdown refleja únicamente movimientos de mercado.
  const returnSeries = buildCumulativeReturnSeries(globalMonthly, totalPortfolio > 0 ? totalPortfolio : null)
  const drawdownTwrr = computeDrawdownOnReturns(returnSeries)
  // Mantenemos la forma del objeto para compatibilidad con código que ya
  // lo lee (alertas D2, AICoach snapshot). max y current siguen siendo % negativos.
  const drawdown = drawdownTwrr ? {
    max: drawdownTwrr.maxPct,
    current: drawdownTwrr.currentPct,
    peakReturnPct: drawdownTwrr.peakReturnPct,
    troughReturnPct: drawdownTwrr.troughReturnPct,
  } : null

  // Card 3 del perfil del inversor — requiere el drawdown ya computado.
  // Si no hay returnSeries todavía (sin historia mensual) pasamos null y
  // la card cae a no_portfolio.
  const drawdownCard = computeDrawdownTolerance(
    investorProfile,
    drawdown?.max,  // % negativo; la función hace Math.abs()
  )

  // ── Insight 3: Deposit discipline ──
  let discipline = null
  if (globalMonthly.length > 0) {
    const totalDeposits = globalMonthly.reduce((s, m) => s + m.deposits, 0)
    const totalWithdrawals = globalMonthly.reduce((s, m) => s + m.withdrawals, 0)
    const netDeposits = totalDeposits - totalWithdrawals
    // P&L real por mes = capital_final - capital_inicio - aportes_netos
    // (NO sumar pnl_unrealized mes a mes: es snapshot acumulado, se cuenta N veces)
    const totalPnl = globalMonthly.reduce((s, m) => {
      const net = (m.deposits || 0) - (m.withdrawals || 0)
      return s + ((m.capital_final || 0) - (m.capital_inicio || 0) - net)
    }, 0)
    const totalGrowth = netDeposits + totalPnl
    discipline = {
      deposits: netDeposits,
      pnl: totalPnl,
      total: totalGrowth,
      pnlShare: totalGrowth !== 0 ? (totalPnl / Math.abs(totalGrowth)) * 100 : 0,
    }
  }

  // ── Cash ratio — % del portfolio en cash (todas las monedas convertidas a USD)
  // Para ARS cash, computeBrokerValue ya hace la conversión vía tcBlue.
  const cashUsd = brokers.reduce((s, b) => {
    const cashPositions = positions.filter(p => p.is_cash && p.broker === b.name)
    if (b.currency === 'ARS') {
      // ARS cash: invested está en pesos → dividir por tcBlue para USD
      return s + cashPositions.reduce((sum, p) => sum + (p.invested || 0) / tcBlue, 0)
    }
    return s + cashPositions.reduce((sum, p) => sum + (p.invested || 0), 0)
  }, 0)
  const cashRatio = totalPortfolio > 0 ? (cashUsd / totalPortfolio) * 100 : 0

  // ── Insight 4: Top performing asset (legacy — solo operaciones cerradas) ──
  // Conservamos esta variable porque la consumen alertas y AICoach. La card
  // visible de "Activo estrella" la reemplazamos abajo por dos cards más
  // completas (total y mejor operación cerrada).
  let topAsset = null
  if (operations.length > 0) {
    const byAsset = {}
    for (const op of operations) {
      const k = (op.asset || '').toUpperCase()
      if (!k) continue
      if (!byAsset[k]) byAsset[k] = { asset: k, pnl: 0, trades: 0, invested: 0 }
      byAsset[k].pnl += op.pnl_usd || 0
      byAsset[k].trades += 1
      if (op.entry_price && op.quantity) byAsset[k].invested += op.entry_price * op.quantity
    }
    const arr = Object.values(byAsset).sort((a, b) => b.pnl - a.pnl)
    const best = arr[0]
    if (best && best.pnl > 0) {
      const pct = best.invested > 0 ? (best.pnl / best.invested) * 100 : null
      topAsset = { ...best, pct, runnerUp: arr[1] || null }
    } else if (best) {
      const pct = best.invested > 0 ? (best.pnl / best.invested) * 100 : null
      topAsset = { ...best, pct, runnerUp: arr[1] || null, allNegative: true }
    }
  }

  // ── Filtro de operaciones para métricas de trader ──
  // Win rate / profit factor / hold time / best-worst trade reflejan decisiones
  // de trading: solo Venta y Futuros cuentan. Dividendos/Intereses son retorno
  // pasivo (contarlos como "wins" infla el win rate artificialmente). Las
  // Conversiones FX son cambios de moneda, no trades.
  const isTradeOp = (op) => {
    const t = (op.op_type || '').trim()
    if (!t) return false
    if (t === 'Dividendo' || t === 'Interés' || t === 'Compra') return false
    if (t.startsWith('CONVERSION') || t.startsWith('Conversión')) return false
    return true
  }
  const tradeOps = operations.filter(isTradeOp)

  // ── Filtro de micro-trades para las stats de calidad ──────────────────────
  // Bots de DCA / grid trading / fees parciales de futuros generan decenas o
  // cientos de trades con |pnl| < $1.5 que no reflejan habilidad del trader y
  // destruyen el win rate. Para las stats (win rate, profit factor, hold time,
  // best/worst) excluimos esos micro-trades; siguen visibles en /operaciones
  // y se cuentan correctamente en el P&L acumulado.
  const MICRO_TRADE_PNL_THRESHOLD = 1.5
  const significantTradeOps = tradeOps.filter(o => Math.abs(o.pnl_usd || 0) >= MICRO_TRADE_PNL_THRESHOLD)
  const microTradeCount = tradeOps.length - significantTradeOps.length

  // Mejor operación cerrada individual (la card nueva).
  const bestWorstOp = computeBestWorstClosedOp(significantTradeOps)

  // ── Insight 5: Win rate + profit factor ──
  // Win rate solo no es suficiente: 5 ganadoras chicas + 2 perdedoras grandes
  // pueden dar 71% WR y aún así perder plata. Profit factor (gross win / gross
  // loss) captura esa asimetría.
  let winRate = null
  if (significantTradeOps.length > 0) {
    const wins = significantTradeOps.filter(o => (o.pnl_usd || 0) > 0).length
    const losses = significantTradeOps.filter(o => (o.pnl_usd || 0) < 0).length
    const total = wins + losses
    if (total > 0) {
      const avgWin = wins > 0 ? significantTradeOps.filter(o => o.pnl_usd > 0).reduce((s, o) => s + o.pnl_usd, 0) / wins : 0
      const avgLoss = losses > 0 ? significantTradeOps.filter(o => o.pnl_usd < 0).reduce((s, o) => s + o.pnl_usd, 0) / losses : 0
      winRate = {
        pct: (wins / total) * 100,
        wins, losses, total,
        avgWin, avgLoss,
        ratio: avgLoss !== 0 ? Math.abs(avgWin / avgLoss) : null,
        microExcluded: microTradeCount,
      }
    }
  }
  const profitFactor = computeProfitFactor(significantTradeOps)

  // ── Insight: Hold time promedio (días entre entry_date y date de cada operación) ──
  let holdTime = null
  if (significantTradeOps.length > 0) {
    const days = []
    for (const op of significantTradeOps) {
      if (!op.entry_date || !op.date) continue
      const entry = new Date(op.entry_date)
      const exit = new Date(op.date)
      if (isNaN(entry) || isNaN(exit)) continue
      const d = Math.max(0, Math.round((exit - entry) / (1000 * 60 * 60 * 24)))
      days.push({ d, pnl: op.pnl_usd || 0, asset: op.asset })
    }
    if (days.length > 0) {
      const avg = days.reduce((s, x) => s + x.d, 0) / days.length
      const wins = days.filter(x => x.pnl > 0)
      const losses = days.filter(x => x.pnl < 0)
      const avgWin = wins.length > 0 ? wins.reduce((s, x) => s + x.d, 0) / wins.length : null
      const avgLoss = losses.length > 0 ? losses.reduce((s, x) => s + x.d, 0) / losses.length : null
      holdTime = { avg, avgWin, avgLoss, count: days.length }
    }
  }

  // ── Insight: Comisiones totales ──
  // Fuente: endpoint /api/insights/commissions que suma operation_type='FEE'
  // de import_normalized_tx (con conversión ARS→USD). Solo cuenta lo que el
  // CSV trajo EXPLÍCITAMENTE marcado como comisión/fee.
  let commissionsStats = null
  if (commissionsApi && commissionsApi.total_usd > 0 && commissionsApi.count > 0) {
    const total = commissionsApi.total_usd
    const count = commissionsApi.count
    const grossWin = profitFactor?.grossWin ?? null
    const pctOfGrossWin = grossWin && grossWin > 0 ? (total / grossWin) * 100 : null
    commissionsStats = { total, count, avgPerTrade: total / count, pctOfGrossWin }
  }

  // ── Insight 6: Concentración (top 3 activos sobre portfolio total) ──
  // Reutiliza assetPieData (ya agregado por activo, excluyendo cash).
  let concentration = null
  if (assetPieData.length > 0 && totalPortfolio > 0) {
    const top3 = assetPieData.slice(0, 3).map(x => ({ asset: x.name, value: x.value }))
    const top3Sum = top3.reduce((s, x) => s + x.value, 0)
    concentration = {
      top3,
      sharePct: (top3Sum / totalPortfolio) * 100,
      totalAssets: assetPieData.length,
    }
  }

  // ── Weekly Total Return variation from snapshots ──
  // Phase 6 — pnl = total_value − net_deposited (Total Return on principal).
  // Snapshots legacy (anteriores a Phase 6) tienen net_deposited=0 por DEFAULT;
  // en ese caso fallback a total_invested (cost basis) para no romper el chart.
  const snapChart = snapshots.slice(-7).map(s => {
    const baseline = (s.net_deposited && s.net_deposited > 0) ? s.net_deposited : s.total_invested
    return {
      date: s.date.slice(5),
      pnl: +(s.total_value - baseline).toFixed(2),
      value: +s.total_value.toFixed(2),
    }
  })
  let dailyVariation = null
  if (snapChart.length >= 2) {
    const last = snapChart[snapChart.length - 1].pnl
    const prev = snapChart[snapChart.length - 2].pnl
    const first = snapChart[0].pnl
    dailyVariation = {
      vsYesterday: last - prev,
      vsWeek: last - first,
    }
  }

  // ── Snapshot RICO del portfolio para el Coach IA ──
  // Incluye summary, posiciones individuales con %, operaciones, mensual, brokers.
  const arsBrokerSet = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))

  const aiPositions = positions.filter(p => !p.is_cash).map(p => {
    const isARS = arsBrokerSet.has(p.broker)
    // Cost basis económico = invested + buy commissions (igual que valuation.js).
    const realCost = (p.invested || 0) + (p.commissions || 0)
    let valueUsd, investedUsd
    if (isARS) {
      const priceArs = p.price_override ?? prices[p.asset + '.BA']
      valueUsd = priceArs != null ? (priceArs * (p.quantity || 0)) / tcBlue : realCost / tcBlue
      investedUsd = realCost / tcBlue
    } else {
      const price = p.price_override ?? prices[p.asset]
      valueUsd = price != null ? price * (p.quantity || 0) : realCost
      investedUsd = realCost
    }
    const pnlUsd = valueUsd - investedUsd
    return {
      broker: p.broker,
      asset: p.asset,
      qty: p.quantity,
      entry_date: p.entry_date,
      invested_usd: +investedUsd.toFixed(2),
      value_usd: +valueUsd.toFixed(2),
      pnl_usd: +pnlUsd.toFixed(2),
      pnl_pct: investedUsd > 0 ? +((pnlUsd / investedUsd) * 100).toFixed(2) : null,
      pct_of_portfolio: totalPortfolio > 0 ? +((valueUsd / totalPortfolio) * 100).toFixed(2) : null,
    }
  }).sort((a, b) => (b.value_usd || 0) - (a.value_usd || 0))

  const aiCash = positions.filter(p => p.is_cash).map(p => ({
    broker: p.broker,
    asset: p.asset,
    amount: p.invested,
    currency: brokers.find(b => b.name === p.broker)?.currency || 'USDT',
    value_usd: arsBrokerSet.has(p.broker) ? +((p.invested || 0) / tcBlue).toFixed(2) : +(p.invested || 0).toFixed(2),
  }))

  // ── Mejor activo total (realized + unrealized) ──
  // Usa aiPositions porque ya tiene pnl_usd resuelto con la lógica de moneda.
  // Esta es la nueva métrica que reemplaza visualmente "Activo estrella":
  // si tu mejor activo todavía está abierto, ahora aparece.
  const assetContribFull = computeAssetContribution(operations, aiPositions)
  const topAssetTotal = assetContribFull.length > 0 ? assetContribFull[0] : null
  const worstAssetTotal = assetContribFull.length > 0 ? assetContribFull[assetContribFull.length - 1] : null

  // ── Concentración de ganancias — qué % del P&L positivo viene del top contributor.
  // Distinto de "concentración por valor" (cuánto pesa el activo en el portfolio).
  // Acá miramos quién generó más ganancia (realizada + no realizada combinada).
  const gainConcentration = (() => {
    const positives = assetContribFull.filter(x => x.pnl > 0)
    if (positives.length === 0) return null
    const totalGains = positives.reduce((s, x) => s + x.pnl, 0)
    const top = positives[0]
    return {
      topAsset: top.asset,
      topGain: top.pnl,
      totalGains,
      sharePct: totalGains > 0 ? (top.pnl / totalGains) * 100 : 0,
      contributorCount: positives.length,
    }
  })()

  // ── Phase 3: nuevas métricas de portfolio ─────────────────────────────────
  // Mejor / peor posición abierta — pnl_usd live de aiPositions.
  const openExtremes = computeOpenPositionExtremes(aiPositions)
  // Consistencia mensual — % meses positivos + std dev del retorno mensual.
  const consistency = computeMonthlyConsistency(returnSeries)
  // Drawdown como serie temporal (para chart underwater).
  const drawdownSeries = buildDrawdownTimeSeries(returnSeries)
  // Concentración por broker — pieData ya está calculado arriba.
  const brokerConcentration = computeBrokerConcentration(pieData)
  // Distribución por tipo de activo: combinamos posiciones abiertas + cash.
  const positionsForType = [
    ...aiPositions.map(p => ({ asset: p.asset, broker: p.broker, is_cash: false, value_usd: p.value_usd })),
    ...aiCash.map(c => ({ asset: c.asset, broker: c.broker, is_cash: true, value_usd: c.value_usd })),
  ]
  const assetTypeBreakdown = computeAssetTypeBreakdown(positionsForType, brokers)

  // ── Phase 4: simulación de benchmarks con flujos sincronizados ────────────
  // "Qué hubiera pasado si la misma plata, con los mismos aportes y retiros,
  //  hubiera ido a S&P 500 / T-Bills / Oro / dólares cash / Merval / Plazo Fijo /
  //  pesos cash."
  // Cada uno devuelve { finalValue, series, finalUnits } o null si faltan datos.
  const sp500Sim     = simulateSp500(globalMonthly, bench?.sp500)
  const shvSim       = simulateShv(globalMonthly, bench?.shv)
  const goldSim      = simulateGold(globalMonthly, bench?.gld)
  const dolarCashSim = simulateDolarCash(globalMonthly)
  const mervalSim    = simulateMerval(globalMonthly, bench?.merval, bench?.dolar_blue)
  const plazoFijoSim = simulatePlazoFijoUva(globalMonthly, bench?.uva, bench?.dolar_blue)
  const arsCashSim   = simulateArsCash(globalMonthly, bench?.dolar_blue)
  const inflationCum = computeInflationCumulative(globalMonthly, bench?.inflation_ar)

  // ── Métricas pro: Sharpe Ratio + Volatilidad anualizada ────────────────────
  // Calculadas sobre returns TWRR mensuales (Modified Dietz) — ya descuentan
  // depósitos/retiros. Risk-free rate derivada de SHV (T-Bills USD).
  // Mínimo 3 meses para que las estadísticas sean confiables.
  const proMetrics = computeProMetrics(globalMonthly, bench)

  // Helper para deltas: cuánto rindió mi portfolio vs el benchmark.
  // Tomamos el "valor final" del benchmark contra `totalPortfolio` (live).
  function compareToMine(benchmarkFinal) {
    if (benchmarkFinal == null || !(totalPortfolio > 0)) return null
    const delta = totalPortfolio - benchmarkFinal
    const pct = benchmarkFinal > 0 ? (delta / benchmarkFinal) * 100 : 0
    return { delta, pct }
  }
  const vsSp500     = sp500Sim     ? compareToMine(sp500Sim.finalValue)     : null
  const vsShv       = shvSim       ? compareToMine(shvSim.finalValue)       : null
  const vsGold      = goldSim      ? compareToMine(goldSim.finalValue)      : null
  const vsDolar     = dolarCashSim ? compareToMine(dolarCashSim.finalValue) : null
  const vsMerval    = mervalSim    ? compareToMine(mervalSim.finalValue)    : null
  const vsPlazoFijo = plazoFijoSim ? compareToMine(plazoFijoSim.finalValue) : null
  const vsArs       = arsCashSim   ? compareToMine(arsCashSim.finalValue)   : null

  const aiOperations = operations.slice(0, 30).map(o => ({
    date: o.date,
    broker: o.broker,
    asset: o.asset,
    type: o.op_type,
    qty: o.quantity,
    entry_price: o.entry_price,
    exit_price: o.exit_price,
    pnl_usd: o.pnl_usd != null ? +o.pnl_usd.toFixed(2) : null,
    pnl_pct: o.pnl_pct != null ? +o.pnl_pct.toFixed(2) : null,
    entry_date: o.entry_date,
  }))

  const aiMonthly = globalMonthly.map(m => {
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    const pnlPct = m.capital_inicio > 0 ? ((m.capital_final - m.capital_inicio - net) / m.capital_inicio) * 100 : null
    return {
      period: `${m.year}-${String(m.month).padStart(2, '0')}`,
      capital_inicio: m.capital_inicio,
      capital_final: m.capital_final,
      deposits: m.deposits,
      withdrawals: m.withdrawals,
      pnl_realized: m.pnl_realized,
      pnl_pct: pnlPct != null ? +pnlPct.toFixed(2) : null,
    }
  })

  // ── Benchmarks para el snapshot del coach ──
  const spKeys = bench?.sp500 ? Object.keys(bench.sp500).sort() : []
  const spYtd = (() => {
    if (!bench?.sp500 || spKeys.length < 2) return null
    const thisYear = new Date().getFullYear()
    const startKey = `${thisYear}-01`
    const spBase = bench.sp500[startKey] || bench.sp500[spKeys.find(k => k >= startKey)]
    const spEnd = bench.sp500[spKeys[spKeys.length - 1]]
    return spBase && spEnd ? +((spEnd / spBase - 1) * 100).toFixed(2) : null
  })()
  const inflKeys = bench?.inflation_ar ? Object.keys(bench.inflation_ar).sort() : []
  const inflLast12 = (() => {
    if (!bench?.inflation_ar || inflKeys.length < 3) return null
    const recent = inflKeys.slice(-12)
    let cum = 1
    for (const k of recent) if (bench.inflation_ar[k] != null) cum *= 1 + bench.inflation_ar[k] / 100
    return +((cum - 1) * 100).toFixed(2)
  })()
  const inflLastMonth = inflKeys.length > 0 ? bench.inflation_ar[inflKeys[inflKeys.length - 1]] : null

  // ── Diagnóstico general — motor data-driven (utils/diagnostics.js) ────────
  // Existen muchos generadores; cada uno mira un aspecto distinto del
  // portfolio y emite un bullet solo si su condición aplica. Cada día se
  // muestran los más relevantes (severidad alta primero) con una rotación
  // estable dentro del día para dar variedad sin perder lo importante.
  const diagnosis = selectDiagnostics({
    // Diagnósticos de concentración por activo (concentration_extreme/high/few_assets)
    // necesitan datos por instrumento, no por broker. brokerPieData se usa solo para
    // diagnósticos que filtran por moneda del broker (high_ars_exposure).
    pieData: assetPieData,
    brokerPieData: pieData,
    totalPortfolio,
    concentration,
    brokerConcentration,
    assetTypeBreakdown,
    discipline,
    assetContribFull,
    totalResult,
    vsSp500,
    vsArs,
    inflationCum,
    currency,
    drawdown,
    winRate,
    profitFactor,
    holdTime,
    openExtremes,
    positions,
    brokers,
    tcBlue,
    // Variables nuevas para reglas de comportamiento, costos y consistencia.
    operations,           // todas las operaciones (trade + cash flow)
    tradeOps,             // solo trades cerrados (sell)
    bestWorstOp,          // { best, worst } operación cerrada
    realizedPnl,          // P&L acumulado realizado
    unrealizedPnl,        // P&L abierto
    globalMonthly,        // meses globales para streak/consistency
  }, 12)

  // ── Qué explica tu resultado: principales contribuyentes ──────────────────
  // Reusa assetContribFull (computeAssetContribution) para que esta sección y
  // las cards "Mejor activo total" miren la misma fuente — antes había dos
  // implementaciones inline que podían divergir.
  const significant = assetContribFull.filter(x => Math.abs(x.pnl) >= 1)
  const topContribPos = significant.filter(x => x.pnl > 0).slice(0, 3)
  const topContribNeg = significant.filter(x => x.pnl < 0).reverse().slice(0, 3)

  // ── Alertas inteligentes (D) — reglas sin IA, no consumen créditos ──
  const todayMs = Date.now()
  const alerts = []

  // D1: activo individual con alta concentración
  if (aiPositions.length > 0) {
    const top = aiPositions[0]
    if (top?.pct_of_portfolio > 40) {
      alerts.push({
        level: 'warning',
        category: 'Concentración',
        title: `${top.asset} representa el ${top.pct_of_portfolio.toFixed(0)}% del portfolio`,
        text: 'Concentración elevada en un único activo. Una caída significativa de ese instrumento impactaría de forma desproporcionada en el resultado total.',
      })
    }
  }

  // D2: drawdown activo > 15%
  if (drawdown && drawdown.current < -15) {
    alerts.push({
      level: 'warning',
      category: 'Drawdown',
      title: `El portfolio está ${Math.abs(drawdown.current).toFixed(1)}% por debajo de su máximo histórico`,
      text: 'Tu portfolio atraviesa un drawdown. Es momento de revisar si los fundamentos de tu estrategia siguen siendo válidos.',
    })
  }

  // D3: posición con pérdida > 25%
  const bigLosers = aiPositions.filter(p => p.pnl_pct != null && p.pnl_pct < -25)
  if (bigLosers.length > 0) {
    const worst = bigLosers.reduce((a, b) => a.pnl_pct < b.pnl_pct ? a : b)
    alerts.push({
      level: 'danger',
      category: 'Riesgo',
      title: `${worst.asset} registra una pérdida del ${Math.abs(worst.pnl_pct).toFixed(0)}%`,
      text: `Pérdida no realizada de ${fmtUsd(Math.abs(worst.pnl_usd))}. Conviene revisar si las razones que originaron la inversión siguen vigentes.`,
    })
  }

  // D4: win rate bajo con muestra suficiente
  if (winRate && winRate.total >= 10 && winRate.pct < 40) {
    alerts.push({
      level: 'warning',
      category: 'Comportamiento',
      title: `Win rate del ${winRate.pct.toFixed(0)}% en ${winRate.total} operaciones`,
      text: 'Más operaciones perdedoras que ganadoras. Conviene revisar los criterios de entrada del sistema de trading.',
    })
  }

  // D5: expectancy negativa
  if (winRate && winRate.total >= 10 && winRate.avgWin != null && winRate.avgLoss != null) {
    const wr = winRate.pct / 100
    const expectancy = wr * Math.abs(winRate.avgWin) - (1 - wr) * Math.abs(winRate.avgLoss)
    if (expectancy < 0) {
      alerts.push({
        level: 'danger',
        category: 'Comportamiento',
        title: 'Expectativa matemática negativa',
        text: `El sistema pierde ${fmtUsd(Math.abs(expectancy))} en promedio por operación. La estrategia tiene un resultado neto negativo, aunque algunas operaciones individuales sean exitosas.`,
      })
    }
  }

  // D6: posición en pérdida con holding > 180 días
  const stuckPositions = aiPositions.filter(p => {
    if (!p.entry_date || p.pnl_pct == null || p.pnl_pct >= -10) return false
    const days = Math.round((todayMs - new Date(p.entry_date).getTime()) / 86400000)
    return days > 180
  })
  if (stuckPositions.length > 0) {
    const s = stuckPositions[0]
    const days = Math.round((todayMs - new Date(s.entry_date).getTime()) / 86400000)
    alerts.push({
      level: 'info',
      category: 'Oportunidad de revisión',
      title: `${s.asset} acumula ${days} días con un rendimiento de ${s.pnl_pct.toFixed(0)}%`,
      text: 'Conviene evaluar si los fundamentos de la inversión siguen siendo válidos o si hay mejores alternativas para reasignar el capital.',
    })
  }

  // Separamos alertas críticas (danger) de las warnings/info — las críticas
  // van arriba del fold para que el usuario las vea apenas entra; el resto
  // va dentro de "Análisis avanzado" para no abrumar.
  const criticalAlerts = alerts.filter(a => a.level === 'danger')
  const otherAlerts = alerts.filter(a => a.level !== 'danger')

  const aiSnapshot = {
    summary: {
      total_usd: +(totalPortfolio || 0).toFixed(2),
      pnl_total_usd: seriesUsd.length > 0 ? +(seriesUsd[seriesUsd.length - 1].total).toFixed(2) : 0,
      pnl_total_pct: seriesUsd.length > 0 ? +(seriesUsd[seriesUsd.length - 1].total).toFixed(2) : 0,
      months_tracked: globalMonthly.length,
      drawdown_max_pct: drawdown ? +drawdown.max.toFixed(2) : null,
      drawdown_current_pct: drawdown ? +drawdown.current.toFixed(2) : null,
      best_month_pct: bestWorstMonth ? +bestWorstMonth.best.pct.toFixed(2) : null,
      best_month_period: bestWorstMonth ? `${bestWorstMonth.best.year}-${String(bestWorstMonth.best.month).padStart(2,'0')}` : null,
      worst_month_pct: bestWorstMonth ? +bestWorstMonth.worst.pct.toFixed(2) : null,
      worst_month_period: bestWorstMonth ? `${bestWorstMonth.worst.year}-${String(bestWorstMonth.worst.month).padStart(2,'0')}` : null,
      win_rate_pct: winRate ? +winRate.pct.toFixed(2) : null,
      total_trades: winRate ? winRate.total : 0,
      avg_win_usd: winRate?.avgWin != null ? +winRate.avgWin.toFixed(2) : null,
      avg_loss_usd: winRate?.avgLoss != null ? +winRate.avgLoss.toFixed(2) : null,
      payoff_ratio: winRate?.ratio != null ? +winRate.ratio.toFixed(2) : null,
      top_asset: topAsset ? topAsset.asset : null,
      top_asset_pnl: topAsset ? +topAsset.pnl.toFixed(2) : null,
      concentration_top3_pct: concentration ? +concentration.sharePct.toFixed(2) : null,
      concentration_top3_assets: concentration ? concentration.top3.map(t => t.asset) : null,
      avg_hold_days: holdTime ? +holdTime.avg.toFixed(1) : null,
      tc_blue_ars: tcBlue,
      // Pro metrics (calculadas en frontend con TWRR Modified Dietz + CAPM).
      // El Coach puede usarlas para diagnósticos tipo "tu Sharpe bajó de 1.4 a
      // 0.8 los últimos 3 meses" o "tu Beta de 1.6 indica que sos más agresivo
      // que el S&P, esperás drawdowns más grandes en correcciones".
      pro_metrics: proMetrics ? {
        volatility_annual_pct: proMetrics.volatility != null ? +(proMetrics.volatility * 100).toFixed(2) : null,
        sharpe_ratio: proMetrics.sharpe ? +proMetrics.sharpe.sharpe.toFixed(2) : null,
        return_annual_pct: proMetrics.sharpe ? +(proMetrics.sharpe.returnAnnual * 100).toFixed(2) : null,
        rf_annual_pct: proMetrics.sharpe ? +(proMetrics.sharpe.rfAnnual * 100).toFixed(2) : null,
        sortino_ratio: proMetrics.sortino ? +proMetrics.sortino.sortino.toFixed(2) : null,
        downside_dev_annual_pct: proMetrics.sortino ? +(proMetrics.sortino.downsideDev * 100).toFixed(2) : null,
        alpha_annual_pct: proMetrics.alphaBeta ? +(proMetrics.alphaBeta.alphaAnnual * 100).toFixed(2) : null,
        beta_vs_sp500: proMetrics.alphaBeta ? +proMetrics.alphaBeta.beta.toFixed(2) : null,
        r_squared_pct: proMetrics.alphaBeta ? +(proMetrics.alphaBeta.rSquared * 100).toFixed(0) : null,
        info_ratio: proMetrics.infoRatio ? +proMetrics.infoRatio.infoRatio.toFixed(2) : null,
        active_return_annual_pct: proMetrics.infoRatio ? +(proMetrics.infoRatio.activeReturn * 100).toFixed(2) : null,
        tracking_error_annual_pct: proMetrics.infoRatio ? +(proMetrics.infoRatio.trackingError * 100).toFixed(2) : null,
        months_data: proMetrics.sharpe ? proMetrics.sharpe.months : null,
      } : null,
    },
    positions: aiPositions,
    cash: aiCash,
    operations: aiOperations,
    monthly: aiMonthly,
    brokers: brokers.map(b => ({ name: b.name, currency: b.currency })),
    benchmarks: {
      sp500_ytd_pct: spYtd,
      sp500_last_close: spKeys.length > 0 ? bench?.sp500[spKeys[spKeys.length - 1]] : null,
      inflation_ar_last_12m_pct: inflLast12,
      inflation_ar_last_month_pct: inflLastMonth,
      dolar_blue_venta: tcBlue,
      dolar_mep_venta: dolar?.mep?.venta || null,
    },
  }

  // Banner: faltan precios → muchos cálculos quedan en cost basis (P&L = 0).
  // Detectamos esto preguntando si hay alguna posición no-cash sin precio
  // resuelto (override o fetch). Si sí, mostramos warning visible.
  const hasMissingPrices = positions.some(p => {
    if (p.is_cash) return false
    if (p.price_override != null) return false
    return prices[p.asset] == null && prices[p.asset + '.BA'] == null
  })

  // Helper de moneda activa: convierte un monto USD al ARS actual cuando el
  // toggle global está en ARS. Las métricas son globales (no las podemos
  // imputar a un FX histórico exacto), así que usamos el blue actual.
  function amt(usdValue, opts = {}) {
    if (usdValue == null || isNaN(usdValue)) return '—'
    const sign = opts.signed ? (usdValue >= 0 ? '+' : '-') : ''
    const abs = Math.abs(usdValue)
    if (currency === 'ARS') {
      const arsValue = abs * tcBlue
      return `${sign}ARS ${arsValue.toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
    }
    return `${sign}USD ${abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }

  // NOTA: removida la variable `aiSuggested` con 12 preguntas data-driven —
  // era dead code (audit #3 B6). Si en el futuro se reactiva el chat con
  // chips dinámicos en Insights, ojo: las preguntas dinámicas NO matchean
  // _FREE_QUESTIONS_WHITELIST del backend, así que cualquier click va a dar
  // 403 para Free/Plus. Si se reactiva, hay dos opciones:
  //   (a) hacer que los chips dinámicos solo se rendereen para tier=pro
  //   (b) ampliar la whitelist del backend con un mecanismo data-driven
  //       (ej. firma HMAC del chip generada por el server, válida 1h)

  // Early return: si el user no tiene positions, mostramos solo el header
  // y un empty state grande. El resto del análisis (KPIs / charts / tables)
  // no tiene sentido con 0 holdings y muestra "—" en todos lados.
  const hasAnyPositions = positions.filter(p => !p.is_cash).length > 0
  if (!hasAnyPositions) {
    return (
      <div className="page-shell space-y-6">
        <PageHeader
          eyebrow="Análisis"
          title="Insights"
          subtitle="Análisis profundo de tu performance, riesgo y comportamiento como inversor."
        />
        <div className="border border-line rounded bg-bg-1 px-6 py-12 text-center max-w-2xl mx-auto">
          <Activity size={28} strokeWidth={1.5} className="mx-auto mb-3 text-ink-3" />
          <h2 className="text-base font-medium text-ink-0 mb-1.5">Todavía no podemos analizar tu portfolio</h2>
          <p className="text-sm text-ink-2 leading-relaxed mb-4 max-w-md mx-auto">
            Los insights de concentración, drawdown y atribución necesitan al menos 30 días de historial. Importá tu CSV para empezar.
          </p>
          <Link
            to="/config"
            className="inline-flex items-center gap-1.5 text-sm bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-4 py-2 rounded-sm transition-colors"
          >
            Importar mi historial
            <ArrowRight size={13} strokeWidth={1.75} />
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page-shell space-y-8">
      <PageHeader
        eyebrow="Análisis"
        title="Insights"
        subtitle="Análisis profundo de tu performance, riesgo y comportamiento como inversor."
        action={
          <div className="flex items-center gap-2 flex-wrap">
            <AnalyzeButton
              screen="insights"
              params={{ window_days: 365 }}
              subtitle="Tu performance del último año"
            />
            <div className="inline-flex bg-bg-2 border border-line p-0.5 rounded-sm" title="Cambiar moneda de visualización">
              {['USD', 'ARS'].map(c => (
                <button
                  key={c}
                  onClick={() => setCurrency(c)}
                  className={`px-3 py-1 text-xs rounded-sm font-mono uppercase tracking-label transition-colors ${
                    currency === c
                      ? 'bg-bg-3 text-ink-0'
                      : 'text-ink-2 hover:text-ink-0'
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>
        }
      />

      {/* Insight del día — solo en mobile, como hero por encima del análisis. */}
      {isMobile && <InsightDelDiaHero />}

      {hasMissingPrices && (
        <div className="flex items-start gap-2.5 px-3 py-2 rounded-sm border border-rendi-warn/25 bg-rendi-warn/[0.08] text-rendi-warn text-xs">
          <AlertTriangle size={14} strokeWidth={1.75} className="flex-shrink-0 mt-0.5" />
          <span>
            <span className="font-semibold">Cargando cotizaciones de mercado.</span> Algunos cálculos pueden mostrar valores parciales hasta completar la sincronización.
          </span>
        </div>
      )}

      {monthly.length < 2 && (
        <div className="flex items-start gap-2.5 px-3 py-2.5 rounded-sm border border-data-cyan/25 bg-data-cyan/[0.06] text-xs">
          <Info size={14} strokeWidth={1.75} className="flex-shrink-0 mt-0.5 text-data-cyan" />
          <div className="text-ink-1">
            <span className="font-medium text-ink-0">Esperá unos días.</span> Los insights más valiosos (drawdown, atribución, comparación) se vuelven precisos con al menos 30 días de historial.
          </div>
        </div>
      )}

      {/* ── KPI strip overview (V2) ─────────────────────────────────────────── */}
      {(() => {
        const lastRow = chartData[chartData.length - 1] || {}
        const cumulativeReturnPct = lastRow[`${userName} P/L total`] ?? null
        const benchmarkReturnPct = lastRow[benchmarkKey] ?? null
        const benchmarkLabel = currency === 'USD' ? 'S&P 500' : 'Inflación AR'
        return (
          <InsightsKpiStrip
            diagnosis={diagnosis}
            assetPieData={assetPieData}
            drawdownTwrr={drawdownTwrr}
            winRate={winRate}
            cumulativeReturnPct={cumulativeReturnPct}
            benchmarkReturnPct={benchmarkReturnPct}
            benchmarkLabel={benchmarkLabel}
            currency={currency}
          />
        )
      })()}

      {/* ══════════════════════════════════════════════════════════════════════
          HERO — Diagnóstico como 3 tarjetas accionables (audit pattern).
          Cada tarjeta: badge de severidad + título corto + contexto + CTA.
          Severidad codificada solo en el BADGE, no en todo el bloque.
          'Resultado del portfolio' eliminado (duplicaba Dashboard).
          ══════════════════════════════════════════════════════════════════════ */}
      {diagnosis.length > 0 && (() => {
        const balanced = pickBalancedDiagnosis(diagnosis, 3)
        const balancedIds = new Set(balanced.map(d => d.id))
        // Truncamos al múltiplo de 3 inmediatamente inferior. Si quedan
        // 1-2 observaciones huérfanas en la última fila quedaba un hueco
        // visual feo — preferimos no mostrar esas en lugar de arruinar la
        // grilla. Las que se truncan vuelven a aparecer otro día gracias
        // a la rotación diaria del selector.
        const allRest = diagnosis.filter(d => !balancedIds.has(d.id))
        const restItems = allRest.slice(0, allRest.length - (allRest.length % 3))

        // GATE Free: solo N observaciones visibles (default 3). El resto
        // del diagnóstico queda blureado al final con CTA upgrade.
        const visibleLimit = plan.limit('insights_diagnostic_visible')
        const isLimited = !plan.hasFullAccess && typeof visibleLimit === 'number'
        const visibleBalanced = isLimited ? balanced.slice(0, visibleLimit) : balanced
        const hiddenBalanced = isLimited ? balanced.slice(visibleLimit) : []
        const totalHidden = hiddenBalanced.length + (isLimited ? restItems.length : 0)

        return (
          <section id="diagnostico" className="scroll-mt-20">
            <p className="eyebrow mb-3">
              Diagnóstico · {visibleBalanced.length} {visibleBalanced.length === 1 ? 'observación' : 'observaciones'} priorizadas
            </p>
            <DiagnosisGrid items={visibleBalanced} />

            {isLimited && totalHidden > 0 && (
              <div className="mt-4">
                <LockedSection.BlurredList
                  feature="insights.diagnostic.full"
                  hiddenCount={totalHidden}
                  noun="observaciones"
                  source="insights_diagnostic"
                >
                  <DiagnosisGrid items={[...hiddenBalanced, ...restItems].slice(0, 6)} />
                </LockedSection.BlurredList>
              </div>
            )}

            {!isLimited && restItems.length > 0 && (
              <details className="mt-3 group">
                <summary className="cursor-pointer text-xs text-ink-2 hover:text-ink-0 inline-flex items-center gap-1 select-none mb-3">
                  <ChevronDown size={12} strokeWidth={1.75} className="group-open:rotate-180 transition-transform" />
                  Ver {restItems.length} {restItems.length === 1 ? 'observación' : 'observaciones'} más
                </summary>
                <DiagnosisGrid items={restItems} />
              </details>
            )}
          </section>
        )
      })()}

      {/* ── Strip de exposición — cash + clases de activo ─────────────────── */}
      {(assetTypeBreakdown.length > 0 || cashRatio > 0) && (
        <section>
          <div className="bg-white dark:bg-bg-1 border border-line rounded p-4 sm:p-5">
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <p className="eyebrow">Exposición</p>
              <span className="text-xs text-ink-2">
                Cash: <span className={`font-semibold tabular ${cashRatio >= 30 ? 'text-rendi-warn' : 'text-ink-1'}`}>{cashRatio.toFixed(1)}%</span>
              </span>
            </div>
            {assetTypeBreakdown.length > 0 && (
              <div className="flex h-2 rounded-full overflow-hidden bg-bg-2 dark:bg-bg-2">
                {assetTypeBreakdown.map((d, i) => (
                  <div
                    key={d.type}
                    style={{ width: `${d.sharePct}%`, background: PIE_COLORS[i % PIE_COLORS.length] }}
                    title={`${d.type}: ${d.sharePct.toFixed(1)}%`}
                  />
                ))}
              </div>
            )}
            {assetTypeBreakdown.length > 0 && (
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-[11px] font-mono">
                {assetTypeBreakdown.map((d, i) => (
                  <span key={d.type} className="flex items-center gap-1.5 text-ink-2">
                    <span className="inline-block w-2 h-2 rounded-full" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                    {d.type}: <span className="tabular font-medium">{d.sharePct.toFixed(0)}%</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {/* ── Alertas críticas (danger) — solo lo más urgente arriba ─────────── */}
      {criticalAlerts.length > 0 && (
        <Section title="Requiere atención" subtitle="Situaciones críticas detectadas en tu portfolio.">
          <div className="space-y-2">
            {criticalAlerts.map((a, i) => (
              <AlertBanner key={i} level={a.level} category={a.category} title={a.title} text={a.text} />
            ))}
          </div>
        </Section>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          B. PERFORMANCE — cómo evolucionó el portfolio en el tiempo, vs benchmark
             y curva de drawdown. Cierra con la atribución (mercado vs aportes).
          ══════════════════════════════════════════════════════════════════════ */}
      <Section
        title="Performance"
        subtitle={currency === 'USD'
          ? `Evolución en USD vs ${benchmarkKey}, profundidad de drawdowns y atribución del crecimiento.`
          : `Evolución en pesos vs ${benchmarkKey}, profundidad de drawdowns y atribución del crecimiento.`}
      >

      {/* Cumulative performance chart — la moneda viene del toggle global */}
      <AskAIAbout
        topic="insights.evolution"
        params={{ window_days: 365 }}
        subtitle="Tu trayectoria mensual"
      >
      <div className="bg-white dark:bg-bg-1 border border-line rounded p-5">
        <div className="flex items-start justify-between mb-3 flex-wrap gap-3">
          <div className="flex items-center gap-1.5">
            <h2 className="font-semibold text-ink-0">
              {currency === 'USD' ? `Portfolio vs ${benchmarkKey} (USD)` : `Portfolio vs ${benchmarkKey} (ARS)`}
            </h2>
            <InfoTooltip>
              <p className="font-semibold text-ink-0">Qué mostramos</p>
              <p>Tu cartera comparada contra un benchmark, ambos en % desde el inicio del rango visible (las 3 líneas arrancan en 0%).</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Las 3 líneas</p>
              <p><span className="inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle" style={{background:'#21D07A'}}/><strong>Verde sólido</strong>: tu cartera total (lo cerrado + lo abierto).</p>
              <p><span className="inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle" style={{background:'#E8B14A'}}/><strong>Amarillo punteado</strong>: solo lo cobrado (ventas + dividendos + intereses). Sin la plusvalía abierta.</p>
              <p><span className="inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle" style={{background: currency === 'USD' ? '#46C6E0' : '#8B7DFF'}}/><strong>{benchmarkKey}</strong>: {currency === 'USD' ? `cómo iría el ${benchmarkKey} si hubiera recibido tus mismos depósitos y retiros en las mismas fechas.` : 'inflación acumulada del período — para ver si tu cartera mantiene poder de compra en pesos.'}</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-1">Puede no coincidir con el Dashboard</p>
              <p className="text-ink-3">El Dashboard divide por lo que tenés aportado HOY. Este chart divide por el MÁXIMO histórico de capital aportado — más conservador si tuviste retiros grandes. Para flujos normales (depósitos sin retiros importantes), ambos coinciden.</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p className="text-ink-3 font-mono text-[11px]">% = (valor actual − aportado neto) / aportado peak × 100</p>
              <p className="text-ink-3">Usar el "aportado peak" (máximo histórico) evita un bug: si retirás $70k de $100k, el aportado actual cae a $30k y cualquier ganancia chica daría +200% engañoso. Con peak, el % refleja la performance real sobre el capital que llegó a trabajar.</p>
              {currency === 'ARS' && (
                <p className="text-ink-3">Fijado a los últimos 12 meses. Períodos más largos pierden comparabilidad por la hiperinflación previa.</p>
              )}
            </InfoTooltip>
          </div>

          {/* Range tabs — solo en USD; ARS es siempre 12 meses */}
          {currency === 'USD' && (
            <div className="flex gap-1 bg-bg-2 dark:bg-bg-1/60 rounded-lg p-1">
              {[
                { label: '1A', months: 12 },
                { label: '2A', months: 24 },
                { label: '5A', months: 60 },
                { label: 'MAX', months: null },
              ].map(({ label, months }) => (
                <button
                  key={label}
                  onClick={() => setChartRange(months)}
                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                    chartRange === months
                      ? 'bg-blue-600 text-white'
                      : 'text-ink-3 hover:text-ink-0 dark:hover:text-ink-0'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
          {currency === 'ARS' && (
            <span className="text-xs text-ink-3 bg-bg-2 dark:bg-bg-1/60 px-2.5 py-1 rounded-lg">
              Últimos 12 meses
            </span>
          )}
        </div>

        {/* Selector de benchmark — segunda fila debajo del título.
            Opciones cambian según moneda (USD vs ARS). Persisted en localStorage. */}
        <div className="flex items-center gap-2 flex-wrap mb-4 -mt-1">
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mr-1">
            Comparar contra:
          </span>
          {benchmarkOptions.map(opt => (
            <button
              key={opt.key}
              onClick={() => opt.available && setSelectedBench(opt.key)}
              disabled={!opt.available}
              className={`px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
                selectedBench === opt.key
                  ? 'bg-data-violet/20 text-data-violet border border-data-violet/40'
                  : opt.available
                    ? 'text-ink-2 hover:text-ink-0 hover:bg-bg-2/60 border border-line/60'
                    : 'text-ink-3/50 cursor-not-allowed border border-line/30'
              }`}
              title={opt.available ? `Comparar contra ${opt.label}` : `${opt.label}: sin datos disponibles`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {chartData.length === 0 ? (
          <div className="text-center py-10 text-ink-3 text-sm mt-4">
            <Info size={20} className="mx-auto mb-2 opacity-50" />
            Cargá al menos un mes en Resumen Mensual para visualizar la evolución.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={chartData} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#1B2230" strokeOpacity={0.6} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#9CA3B5', fontSize: 11, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} minTickGap={30} />
              <YAxis tick={{ fill: '#9CA3B5', fontSize: 11, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={v => `${v > 0 ? '+' : ''}${v}%`} />
              <ReferenceLine y={0} stroke="#3A4256" strokeOpacity={0.6} strokeDasharray="2 4" />
              <Tooltip
                contentStyle={{ background: '#0E1218', border: '1px solid #262E40', borderRadius: 6, fontSize: 12 }}
                labelStyle={{ color: '#E6EAF2', fontFamily: 'JetBrains Mono', fontSize: 10, textTransform: 'uppercase' }}
                formatter={(v) => [v != null ? `${v > 0 ? '+' : ''}${v.toFixed(1)}%` : '—', '']}
              />
              <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11, fontFamily: 'JetBrains Mono' }} />
              <Line type="monotone" dataKey={`${userName} P/L total`} stroke="#21D07A" strokeWidth={2.25} dot={{ r: 2.5 }} />
              <Line type="monotone" dataKey={`${userName} P/L realizado`} stroke="#E8B14A" strokeWidth={1.5} strokeDasharray="6 4" dot={{ r: 2, fill: '#E8B14A' }} />
              <Line type="monotone" dataKey={benchmarkKey} stroke={currency === 'USD' ? '#46C6E0' : '#8B7DFF'} strokeWidth={1.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      </AskAIAbout>

      {/* Drawdown curve (underwater chart) — visualiza la profundidad
          y duración de las caídas sobre el rendimiento ajustado por flujos.
          Visible en desktop y mobile (paridad de features — la diferencia
          plataforma es de layout, no de contenido). */}
      <AskAIAbout
        topic="insights.drawdown"
        params={{ window_days: 365 }}
        subtitle="Drawdown del portfolio"
      >
      <div className="bg-white dark:bg-bg-1 border border-line rounded p-5 mt-6">
        <div className="flex items-start justify-between gap-2 mb-1 flex-wrap">
          <div className="flex items-center gap-1.5">
            <h2 className="font-semibold text-ink-0">Curva de drawdown</h2>
            <InfoTooltip>
              <p className="font-semibold text-ink-0">Qué es</p>
              <p>Cuánto bajaste desde tu mejor momento histórico. Si llegaste a +20% y ahora estás en +10%, tu drawdown es −10%.</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Cómo leerlo</p>
              <p><span className="text-ink-1">0%</span>: estás en tu máximo histórico.</p>
              <p><span className="text-rendi-warn">−10%</span>: caíste 10% desde el pico.</p>
              <p><span className="text-rendi-neg">&lt; −25%</span>: drawdown serio — recuperar +25% requiere +33% de retorno.</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="text-ink-3">Calculado sobre el rendimiento ajustado por flujos (TWRR) — depósitos y retiros no se cuentan como subida/bajada del portfolio.</p>
            </InfoTooltip>
          </div>
          {drawdownTwrr && (
            <div className="flex gap-3 text-xs">
              <span className="text-ink-3">Actual: <span className={`font-semibold tabular ${drawdownTwrr.currentPct < -5 ? 'text-rendi-neg' : 'text-rendi-pos'}`}>{drawdownTwrr.currentPct.toFixed(1)}%</span></span>
              <span className="text-ink-3">Máx histórico: <span className="font-semibold tabular text-rendi-neg">{drawdownTwrr.maxPct.toFixed(1)}%</span></span>
            </div>
          )}
        </div>
        <p className="text-xs text-ink-3 mb-4">Profundidad y duración de las caídas. El área negativa representa los períodos por debajo del máximo histórico.</p>
        {drawdownSeries.length < 2 ? (
          <div className="text-center py-10 text-ink-3 text-sm">
            <Activity size={20} className="mx-auto mb-2 opacity-50" />
            Se requieren al menos 2 meses de historial para construir la curva.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={drawdownSeries} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"  stopColor="#FF5360" stopOpacity={0} />
                  <stop offset="100%" stopColor="#FF5360" stopOpacity={0.35} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1B2230" strokeOpacity={0.6} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#9CA3B5', fontSize: 11, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} minTickGap={28} />
              <YAxis tick={{ fill: '#9CA3B5', fontSize: 11, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} domain={['auto', 0]} />
              <ReferenceLine y={0} stroke="#3A4256" strokeOpacity={0.6} />
              <Tooltip
                contentStyle={{ background: '#0E1218', border: '1px solid #262E40', borderRadius: 6, fontSize: 12 }}
                labelStyle={{ color: '#E6EAF2', fontFamily: 'JetBrains Mono', fontSize: 10, textTransform: 'uppercase' }}
                formatter={(v) => [`${v.toFixed(2)}%`, 'Drawdown']}
              />
              <Area type="monotone" dataKey="ddPct" stroke="#FF5360" strokeWidth={1.5} fill="url(#ddGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
      </AskAIAbout>

      {/* ── Atribución del crecimiento — mercado vs aportes ─────────────────── */}
      {discipline && discipline.total !== 0 && (
        <AskAIAbout
          topic="insights.attribution"
          subtitle="Qué activos manejaron tu P&L"
        >
          <PerformanceAttribution discipline={discipline} amt={amt} />
        </AskAIAbout>
      )}

      </Section>

      {/* ══════════════════════════════════════════════════════════════════════
          C. COMPORTAMIENTO — quién sos como inversor: win rate, hold time,
             concentración y mejor trade individual.
          ══════════════════════════════════════════════════════════════════════ */}
      <Section title="Comportamiento" subtitle="Tu estilo de inversor: tasa de acierto, horizonte de las posiciones y nivel de concentración.">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">

        {/* Mejor operación cerrada individual */}
        <InsightCard
          icon={<Trophy size={18} />}
          title="Mejor operación cerrada"
          accent={bestWorstOp != null && bestWorstOp.best.pnl_usd > 0}
          tooltip={
            <>
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p>Operación individual cerrada con mayor P&L en USD.</p>
              <p className="text-ink-3">Distinto al "mejor activo total": aquí importa la operación puntual, no el resultado agregado del activo.</p>
            </>
          }
        >
          {!bestWorstOp ? (
            <p className="text-sm text-ink-3">Aún no hay operaciones cerradas.</p>
          ) : (
            <>
              <p className="text-2xl font-bold text-ink-0">
                {bestWorstOp.best.asset}
              </p>
              <p className="text-xs text-ink-3 mt-1">
                <span className={`${colorClass(bestWorstOp.best.pnl_usd)} font-medium`}>
                  {amt(bestWorstOp.best.pnl_usd, { signed: true })}
                </span>
                {bestWorstOp.best.date && (
                  <span className="text-ink-3"> · {bestWorstOp.best.date}</span>
                )}
              </p>
              {bestWorstOp.worst && bestWorstOp.worst.pnl_usd < 0 && (
                <p className="text-xs text-ink-2 mt-3 leading-snug">
                  Peor operación: <span className="font-semibold text-rendi-neg">{bestWorstOp.worst.asset}</span> con <span className={colorClass(bestWorstOp.worst.pnl_usd)}>{amt(bestWorstOp.worst.pnl_usd, { signed: true })}</span>.
                </p>
              )}
            </>
          )}
        </InsightCard>

        {/* Win rate */}
        <InsightCard
          icon={<Target size={18} />}
          title="Win rate y profit factor"
          accent={profitFactor != null && profitFactor.profitFactor >= 1}
          tooltip={
            <>
              <p className="font-semibold text-ink-0">Qué son</p>
              <p><span className="font-medium">Win rate:</span> porcentaje de operaciones cerradas con ganancia.</p>
              <p><span className="font-medium">Profit factor:</span> total ganado dividido total perdido.</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Cómo leer el Profit Factor</p>
              <p><span className="text-rendi-neg">&lt; 1</span>: perdés más de lo que ganás (resultado neto negativo).</p>
              <p><span className="text-ink-2">1.0 – 1.5</span>: marginal — ganás un poco más de lo que perdés.</p>
              <p><span className="text-rendi-pos">1.5 – 2.0</span>: bueno.</p>
              <p><span className="text-rendi-pos">&gt; 2.0</span>: excelente — por cada $1 que perdés, ganás más de $2.</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="text-ink-3">Las dos métricas se leen juntas: un win rate alto con ganancias chiquitas puede tener PF &lt; 1 (perdés en neto aunque aciertes más seguido).</p>
              <p className="text-ink-3">Excluimos micro-trades (&lt; USD 1.5) porque son ruido — fees parciales, ajustes de futuros, redondeos que no reflejan decisiones reales del trader.</p>
            </>
          }
        >
          {!winRate ? (
            <p className="text-sm text-ink-3">Aún no hay operaciones cerradas.</p>
          ) : (
            <>
              <div className="flex items-baseline gap-3">
                <p className="text-2xl font-bold text-ink-0">
                  {winRate.pct.toFixed(0)}%
                </p>
                {profitFactor && (
                  <p className={`text-base font-semibold tabular ${
                    profitFactor.profitFactor === Infinity ? 'text-rendi-pos'
                    : profitFactor.profitFactor >= 1.5 ? 'text-rendi-pos'
                    : profitFactor.profitFactor >= 1 ? 'text-emerald-600/80 dark:text-emerald-400/80'
                    : 'text-rendi-neg'
                  }`}>
                    PF {profitFactor.profitFactor === Infinity ? '∞' : profitFactor.profitFactor.toFixed(2)}
                  </p>
                )}
              </div>
              <p className="text-xs text-ink-3 mt-1">
                <span className="text-emerald-500">{winRate.wins} ganadoras</span> ·
                <span className="text-red-500"> {winRate.losses} perdedoras</span>
                {winRate.ratio != null && <span className="text-ink-3"> · R/R {winRate.ratio.toFixed(2)}x</span>}
              </p>
              {winRate.microExcluded > 0 && (
                <p className="text-[11px] text-ink-3 mt-1 italic">
                  {winRate.microExcluded} {winRate.microExcluded === 1 ? 'trade chico' : 'trades chicos'} (&lt; $1.5) excluidos del cálculo
                </p>
              )}
              <p className="text-xs text-ink-2 mt-3 leading-snug">
                {profitFactor && profitFactor.profitFactor < 1
                  ? `Profit factor < 1: con ${winRate.pct.toFixed(0)}% de aciertos, las pérdidas brutas superan a las ganancias. Resultado neto negativo.`
                  : profitFactor && profitFactor.profitFactor >= 2
                  ? `Por cada dólar perdido, generás ${profitFactor.profitFactor.toFixed(1)}. Expectativa positiva sólida.`
                  : winRate.pct >= 60
                  ? 'Tasa de acierto alta y ganancias promedio mayores a las pérdidas.'
                  : winRate.pct >= 40
                  ? 'Tasa de acierto cercana al 50%. La diferencia entre ganadoras y perdedoras define la rentabilidad.'
                  : 'Más operaciones perdedoras que ganadoras. Conviene revisar los criterios de entrada.'}
              </p>
            </>
          )}
        </InsightCard>

        {/* Concentración */}
        <InsightCard
          icon={<Layers size={18} />}
          title="Concentración (top 3)"
          accent={concentration != null && concentration.sharePct < 70}
          tooltip={
            <>
              <p className="font-semibold text-ink-0">Qué es</p>
              <p>Porcentaje del portfolio concentrado en los 3 activos más grandes (excluyendo cash).</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Cómo leerlo</p>
              <p>Cuanto más alto, más dependés de esos 3 activos. Si uno cae fuerte, te afecta de lleno — no tenés diversificación que amortigüe.</p>
              <p className="text-ink-3">Concentración del 100% en pocos activos = todo el riesgo en pocas apuestas. Diversificación dispersa ese riesgo entre más activos no correlacionados.</p>
            </>
          }
        >
          {!concentration ? (
            <p className="text-sm text-ink-3">Aún no hay posiciones cargadas.</p>
          ) : (
            <>
              <p className="text-2xl font-bold text-ink-0">
                {concentration.sharePct.toFixed(0)}%
              </p>
              <p className="text-xs text-ink-3 mt-1">
                {concentration.top3.map(t => t.asset).join(' · ')}
              </p>
              {gainConcentration && gainConcentration.sharePct >= 40 && (
                <p className="text-xs text-ink-2 mt-3 leading-snug">
                  El <span className="font-semibold text-ink-0 dark:text-white">{gainConcentration.sharePct.toFixed(0)}%</span> de tus ganancias proviene de <span className="font-semibold">{gainConcentration.topAsset}</span>. Sin esa posición, el rendimiento global cambia significativamente.
                </p>
              )}
              {(!gainConcentration || gainConcentration.sharePct < 40) && (
                <p className="text-xs text-ink-2 mt-3 leading-snug">
                  {concentration.sharePct >= 80
                    ? 'Concentración elevada. Una caída en cualquiera de estos activos impacta fuertemente al portfolio.'
                    : concentration.sharePct >= 60
                    ? 'Concentración moderada. Aceptable si tenés convicción y conocimiento sobre los activos.'
                    : 'Cartera diversificada entre varios activos.'}
                </p>
              )}
            </>
          )}
        </InsightCard>

        {/* Hold time promedio */}
        <InsightCard
          icon={<Clock size={18} />}
          title="Hold time promedio"
          accent={holdTime != null}
          tooltip={
            <>
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p>Días promedio transcurridos entre la fecha de compra y la de venta de cada operación cerrada.</p>
              <p className="text-ink-3">Solo se incluyen operaciones con ambas fechas registradas.</p>
            </>
          }
        >
          {!holdTime ? (
            <p className="text-sm text-ink-3">Sin datos suficientes. Se requieren operaciones con fecha de entrada registrada.</p>
          ) : (
            <>
              <p className="text-2xl font-bold text-ink-0">
                {holdTime.avg.toFixed(0)} {holdTime.avg === 1 ? 'día' : 'días'}
              </p>
              <p className="text-xs text-ink-3 mt-1">
                Sobre {holdTime.count} {holdTime.count === 1 ? 'operación' : 'operaciones'} cerradas
              </p>
              <p className="text-xs text-ink-2 mt-3 leading-snug">
                {holdTime.avgWin != null && holdTime.avgLoss != null && (
                  <>Ganadoras: <span className="text-emerald-500 font-medium">{holdTime.avgWin.toFixed(0)}d</span> · Perdedoras: <span className="text-red-500 font-medium">{holdTime.avgLoss.toFixed(0)}d</span>. </>
                )}
                {holdTime.avg < 7
                  ? 'Trading de muy corto plazo. Costos y comisiones tienen alto impacto en este horizonte.'
                  : holdTime.avg < 30
                  ? 'Horizonte semanal — estilo swing trading.'
                  : holdTime.avg < 180
                  ? 'Posiciones de mediano plazo.'
                  : 'Largo plazo: las posiciones se mantienen para capturar tendencias estructurales.'}
              </p>
            </>
          )}
        </InsightCard>

        {/* Comisiones totales pagadas */}
        <InsightCard
          icon={<CircleDollarSign size={18} />}
          title="Comisiones totales"
          accent={false}
          tooltip={
            <>
              <p className="font-semibold text-ink-0">Qué es</p>
              <p>Suma de todas las comisiones que pagaste — fees del broker, comisiones de mercado, costos de extracción, fees de futuros.</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Nota</p>
              <p className="text-ink-3">Si tu broker es en pesos, lo convertimos a USD al blue. Si el fee va embebido en el precio (spread, fee dentro de una compra), no aparece acá.</p>
            </>
          }
        >
          {!commissionsStats ? (
            <p className="text-sm text-ink-3">Aún no hay comisiones registradas.</p>
          ) : (
            <>
              <p className="text-2xl font-bold text-ink-0">
                {amt(commissionsStats.total)}
              </p>
              <p className="text-xs text-ink-3 mt-1">
                Sobre {commissionsStats.count} {commissionsStats.count === 1 ? 'operación' : 'operaciones'} · prom. {amt(commissionsStats.avgPerTrade)}
              </p>
              <p className="text-xs text-ink-2 mt-3 leading-snug">
                {commissionsStats.pctOfGrossWin != null && commissionsStats.pctOfGrossWin >= 1
                  ? <>Equivalen al <span className="font-semibold text-ink-0 dark:text-white">{commissionsStats.pctOfGrossWin.toFixed(1)}%</span> de tus ganancias brutas. {commissionsStats.pctOfGrossWin >= 20 ? 'Peso alto sobre el resultado — revisá si conviene operar menos o cambiar de broker.' : commissionsStats.pctOfGrossWin >= 10 ? 'Peso moderado: vale la pena monitorear que no crezca.' : 'Costo razonable en relación a lo generado.'}</>
                  : 'Costo total de operar tu portfolio.'}
              </p>
            </>
          )}
        </InsightCard>

      </div>

      </Section>

      {/* ══════════════════════════════════════════════════════════════════════
          C1.5 MÉTRICAS PRO — 6 métricas estadísticas estándar de la industria.
               Tier gating:
                 • Plus: Volatilidad + Beta (descriptivas del riesgo)
                 • Pro:  Sharpe + Sortino + Alpha + Information Ratio
                         (skill ajustado por riesgo — métricas premium)
          ══════════════════════════════════════════════════════════════════════ */}
      {proMetrics && proMetrics.sharpe && plan.isPaid && (
        <Section
          title="Métricas pro"
          subtitle="Volatilidad y Beta en Plus; Sharpe, Sortino, Alpha e Information Ratio en Pro."
        >
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {/* ── PLUS — Volatilidad anualizada ─────────────────────────── */}
            <InsightCard
              icon={<Activity size={18} />}
              title="Volatilidad anualizada"
              tooltip={
                <>
                  <p className="font-semibold text-ink-0">Qué es</p>
                  <p>Cuánto varían tus retornos mensualmente, anualizado. Volatilidad alta = más variabilidad mes a mes (más riesgo).</p>
                  <div className="border-t border-line/60 my-1.5" />
                  <p className="font-semibold text-ink-0">Cómo leerlo</p>
                  <p><span className="text-rendi-pos">&lt; 10%</span>: bonos / conservador.</p>
                  <p><span className="text-ink-2">10–20%</span>: equities diversificadas (S&P ≈ 15-18%).</p>
                  <p><span className="text-rendi-warn">20–40%</span>: equities concentradas / sectorial.</p>
                  <p><span className="text-rendi-neg">&gt; 40%</span>: cripto / activos especulativos.</p>
                  <div className="border-t border-line/60 my-1.5" />
                  <p className="font-semibold text-ink-0">Cómo se calcula</p>
                  <p className="text-ink-3 font-mono text-[11px]">σ<sub>anual</sub> = stdev(retornos mensuales) × √12</p>
                  <p className="text-ink-3">Basado en {proMetrics.sharpe.months} meses de retornos ajustados por flujos.</p>
                </>
              }
            >
              <div className="flex items-baseline gap-3">
                <p className={`text-3xl font-bold tabular ${
                  proMetrics.volatility < 0.10 ? 'text-rendi-pos'
                  : proMetrics.volatility < 0.20 ? 'text-ink-1'
                  : proMetrics.volatility < 0.40 ? 'text-rendi-warn'
                  : 'text-rendi-neg'
                }`}>
                  {(proMetrics.volatility * 100).toFixed(1)}%
                </p>
                <p className="text-xs text-ink-3 tabular">
                  {proMetrics.volatility < 0.10 ? 'Baja'
                   : proMetrics.volatility < 0.20 ? 'Moderada'
                   : proMetrics.volatility < 0.40 ? 'Alta'
                   : 'Muy alta'}
                </p>
              </div>
              <p className="text-xs text-ink-3 mt-2 leading-snug">
                Desvío estándar de los retornos mensuales, anualizado. S&P 500 ≈ 15-18%.
              </p>
            </InsightCard>

            {/* ── PLUS — Beta vs S&P 500 ───────────────────────────────── */}
            {proMetrics.alphaBeta && (
              <InsightCard
                icon={<BarChart3 size={18} />}
                title="Beta (vs S&P 500)"
                tooltip={
                  <>
                    <p className="font-semibold text-ink-0">Qué es</p>
                    <p>Sensibilidad de tu cartera al mercado. Cuánto se mueve tu portfolio por cada movimiento del S&P 500.</p>
                    <div className="border-t border-line/60 my-1.5" />
                    <p className="font-semibold text-ink-0">Cómo leerlo</p>
                    <p><span className="text-ink-1">β = 1.0</span>: te movés igual que el S&P.</p>
                    <p><span className="text-rendi-warn">β &gt; 1.0</span>: más volátil (más riesgo de mercado).</p>
                    <p><span className="text-rendi-pos">β &lt; 1.0</span>: más defensivo.</p>
                    <p><span className="text-ink-2">β ≈ 0</span>: no correlacionado.</p>
                    <p><span className="text-rendi-pos">β &lt; 0</span>: hedge (contrario al S&P).</p>
                    <div className="border-t border-line/60 my-1.5" />
                    <p className="font-semibold text-ink-0">Cómo se calcula</p>
                    <p className="text-ink-3 font-mono text-[11px]">β = Cov(R<sub>p</sub>, R<sub>b</sub>) / Var(R<sub>b</sub>)</p>
                    <p className="text-ink-3">Basado en {proMetrics.alphaBeta.months} meses con retornos válidos en ambas series.</p>
                  </>
                }
              >
                <div className="flex items-baseline gap-3">
                  <p className={`text-3xl font-bold tabular ${
                    Math.abs(proMetrics.alphaBeta.beta - 1.0) < 0.15 ? 'text-ink-1'
                    : proMetrics.alphaBeta.beta > 1.0 ? 'text-rendi-warn'
                    : proMetrics.alphaBeta.beta >= 0 ? 'text-rendi-pos'
                    : 'text-rendi-accent'
                  }`}>
                    {proMetrics.alphaBeta.beta.toFixed(2)}
                  </p>
                  <p className="text-xs text-ink-3 tabular">
                    {Math.abs(proMetrics.alphaBeta.beta - 1.0) < 0.15 ? 'Como S&P'
                     : proMetrics.alphaBeta.beta > 1.3 ? 'Agresivo'
                     : proMetrics.alphaBeta.beta > 1.0 ? 'Sobre el S&P'
                     : proMetrics.alphaBeta.beta > 0.5 ? 'Defensivo'
                     : proMetrics.alphaBeta.beta >= 0 ? 'Bajo'
                     : 'Hedge'}
                  </p>
                </div>
                <p className="text-xs text-ink-3 mt-2 leading-snug">
                  Por cada 1% del S&P, tu cartera se mueve{' '}
                  <span className="text-ink-1 font-medium tabular">
                    {proMetrics.alphaBeta.beta.toFixed(2)}%
                  </span>.
                </p>
              </InsightCard>
            )}

            {/* ── PRO — Sharpe Ratio ──────────────────────────────────── */}
            {plan.hasFullAccess ? (
              <InsightCard
                icon={<Target size={18} />}
                title="Sharpe Ratio"
                accent={proMetrics.sharpe.sharpe >= 1}
                tooltip={
                  <>
                    <p className="font-semibold text-ink-0">Qué es</p>
                    <p>Rendimiento ajustado por toda la volatilidad. Mide cuánto extra ganaste sobre la tasa libre de riesgo (T-Bills) por cada unidad de riesgo que asumiste.</p>
                    <div className="border-t border-line/60 my-1.5" />
                    <p className="font-semibold text-ink-0">Cómo leerlo</p>
                    <p><span className="text-rendi-neg">&lt; 0</span>: le perdés a T-Bills (mejor estar en cash USD).</p>
                    <p><span className="text-ink-2">0–1</span>: tomás riesgo pero el premio es bajo.</p>
                    <p><span className="text-rendi-pos">1–2</span>: bueno.</p>
                    <p><span className="text-rendi-pos">&gt; 2</span>: excelente.</p>
                    <div className="border-t border-line/60 my-1.5" />
                    <p className="font-semibold text-ink-0">Cómo se calcula</p>
                    <p className="text-ink-3 font-mono text-[11px]">sharpe = (μ<sub>anual</sub> − rf) / σ<sub>anual</sub></p>
                    <p className="text-ink-3">Retorno anual: {(proMetrics.sharpe.returnAnnual * 100).toFixed(1)}% · Tasa libre: {(proMetrics.sharpe.rfAnnual * 100).toFixed(1)}%</p>
                  </>
                }
              >
                <div className="flex items-baseline gap-3">
                  <p className={`text-3xl font-bold tabular ${
                    proMetrics.sharpe.sharpe >= 2 ? 'text-rendi-pos'
                    : proMetrics.sharpe.sharpe >= 1 ? 'text-emerald-600/80 dark:text-emerald-400/80'
                    : proMetrics.sharpe.sharpe >= 0 ? 'text-ink-1'
                    : 'text-rendi-neg'
                  }`}>
                    {proMetrics.sharpe.sharpe.toFixed(2)}
                  </p>
                  <p className="text-xs text-ink-3 tabular">
                    {proMetrics.sharpe.sharpe >= 2 ? 'Excelente'
                     : proMetrics.sharpe.sharpe >= 1 ? 'Bueno'
                     : proMetrics.sharpe.sharpe >= 0 ? 'Subóptimo'
                     : 'Negativo'}
                  </p>
                </div>
                <p className="text-xs text-ink-3 mt-2 leading-snug">
                  Retorno ajustado por toda la volatilidad. La métrica clásica de skill.
                </p>
              </InsightCard>
            ) : (
              <LockedSection.Placeholder
                feature="insights.metrics_pro_sharpe"
                title="Sharpe Ratio"
                description="Rendimiento ajustado por toda la volatilidad — la métrica clásica de skill. Disponible en Pro."
                source="insights_metrics_pro"
              />
            )}

            {/* ── PRO — Sortino Ratio ─────────────────────────────────── */}
            {plan.hasFullAccess ? (
              proMetrics.sortino ? (
                <InsightCard
                  icon={<TrendingDown size={18} />}
                  title="Sortino Ratio"
                  accent={proMetrics.sortino.sortino >= 1}
                  tooltip={
                    <>
                      <p className="font-semibold text-ink-0">Qué es</p>
                      <p>Como Sharpe pero usa SOLO la volatilidad a la baja. Más justo: cuando tu cartera tiene un mes muy bueno, eso no es "riesgo" — no nos asusta cuando ganamos.</p>
                      <div className="border-t border-line/60 my-1.5" />
                      <p className="font-semibold text-ink-0">Cómo leerlo</p>
                      <p>Mismo rango que Sharpe pero típicamente MÁS ALTO (porque excluye la volatilidad de subida).</p>
                      <p><span className="text-rendi-pos">&gt; 1.5</span>: muy bueno.</p>
                      <div className="border-t border-line/60 my-1.5" />
                      <p className="font-semibold text-ink-0">Cómo se calcula</p>
                      <p className="text-ink-3 font-mono text-[11px]">sortino = (μ<sub>anual</sub> − rf) / σ<sub>downside</sub></p>
                      <p className="text-ink-3">Downside dev anual: {(proMetrics.sortino.downsideDev * 100).toFixed(1)}%.</p>
                    </>
                  }
                >
                  <div className="flex items-baseline gap-3">
                    <p className={`text-3xl font-bold tabular ${
                      proMetrics.sortino.sortino >= 2 ? 'text-rendi-pos'
                      : proMetrics.sortino.sortino >= 1 ? 'text-emerald-600/80 dark:text-emerald-400/80'
                      : proMetrics.sortino.sortino >= 0 ? 'text-ink-1'
                      : 'text-rendi-neg'
                    }`}>
                      {proMetrics.sortino.sortino.toFixed(2)}
                    </p>
                    <p className="text-xs text-ink-3 tabular">
                      {proMetrics.sortino.sortino >= 2 ? 'Excelente'
                       : proMetrics.sortino.sortino >= 1 ? 'Bueno'
                       : proMetrics.sortino.sortino >= 0 ? 'Subóptimo'
                       : 'Negativo'}
                    </p>
                  </div>
                  <p className="text-xs text-ink-3 mt-2 leading-snug">
                    Sharpe variante: solo penaliza volatilidad a la baja.
                  </p>
                </InsightCard>
              ) : (
                <InsightCard icon={<TrendingDown size={18} />} title="Sortino Ratio">
                  <p className="text-sm text-ink-3">Sin volatilidad a la baja para medir aún.</p>
                </InsightCard>
              )
            ) : (
              <LockedSection.Placeholder
                feature="insights.metrics_pro_sortino"
                title="Sortino Ratio"
                description="Variante de Sharpe que penaliza solo la volatilidad a la baja. Disponible en Pro."
                source="insights_metrics_pro"
              />
            )}

            {/* ── PRO — Alpha (Jensen's CAPM) ─────────────────────────── */}
            {plan.hasFullAccess ? (
              proMetrics.alphaBeta ? (
                <InsightCard
                  icon={<TrendingUp size={18} />}
                  title="Alpha (vs S&P 500)"
                  accent={proMetrics.alphaBeta.alphaAnnual > 0}
                  tooltip={
                    <>
                      <p className="font-semibold text-ink-0">Qué es</p>
                      <p>Retorno extra sobre lo que el modelo CAPM predice dado el riesgo de mercado que asumiste (Beta). En cristiano: cuánto le ganaste al S&P teniendo en cuenta cuánto te movés con él.</p>
                      <div className="border-t border-line/60 my-1.5" />
                      <p className="font-semibold text-ink-0">Cómo leerlo</p>
                      <p><span className="text-rendi-pos">&gt; 0</span>: outperformaste el modelo (skill o suerte).</p>
                      <p><span className="text-ink-2">≈ 0</span>: matcheás al CAPM.</p>
                      <p><span className="text-rendi-neg">&lt; 0</span>: underperformaste.</p>
                      <p className="text-ink-3">R² {(proMetrics.alphaBeta.rSquared * 100).toFixed(0)}% — R² alto + α alto = outperform real (no solo desviación aleatoria).</p>
                      <div className="border-t border-line/60 my-1.5" />
                      <p className="font-semibold text-ink-0">Cómo se calcula</p>
                      <p className="text-ink-3 font-mono text-[11px]">α = mean(R<sub>p</sub>) − [Rf + β × (mean(R<sub>b</sub>) − Rf)]</p>
                    </>
                  }
                >
                  <div className="flex items-baseline gap-3">
                    <p className={`text-3xl font-bold tabular ${
                      proMetrics.alphaBeta.alphaAnnual > 0.02 ? 'text-rendi-pos'
                      : proMetrics.alphaBeta.alphaAnnual > -0.02 ? 'text-ink-1'
                      : 'text-rendi-neg'
                    }`}>
                      {proMetrics.alphaBeta.alphaAnnual >= 0 ? '+' : '−'}{Math.abs(proMetrics.alphaBeta.alphaAnnual * 100).toFixed(1)}%
                    </p>
                    <p className="text-xs text-ink-3 tabular">
                      {proMetrics.alphaBeta.alphaAnnual > 0.05 ? 'Outperform alto'
                       : proMetrics.alphaBeta.alphaAnnual > 0 ? 'Outperform'
                       : proMetrics.alphaBeta.alphaAnnual > -0.05 ? 'Matchea CAPM'
                       : 'Underperform'}
                    </p>
                  </div>
                  <p className="text-xs text-ink-3 mt-2 leading-snug">
                    Retorno anual extra vs CAPM. R² {(proMetrics.alphaBeta.rSquared * 100).toFixed(0)}%.
                  </p>
                </InsightCard>
              ) : null
            ) : (
              <LockedSection.Placeholder
                feature="insights.metrics_pro_alpha"
                title="Alpha vs S&P 500"
                description="Retorno extra sobre lo que CAPM predice (Jensen's Alpha). Disponible en Pro."
                source="insights_metrics_pro"
              />
            )}

            {/* ── PRO — Information Ratio ─────────────────────────────── */}
            {plan.hasFullAccess ? (
              proMetrics.infoRatio ? (
                <InsightCard
                  icon={<BarChart2 size={18} />}
                  title="Information Ratio (vs S&P)"
                  accent={proMetrics.infoRatio.infoRatio >= 0.5}
                  tooltip={
                    <>
                      <p className="font-semibold text-ink-0">Qué es</p>
                      <p>Consistencia con la que le ganás al benchmark. Mide cuánto le ganaste al S&P por cada unidad de "diferencia" que tomaste vs el índice (en lugar de calcar el S&P y dormir tranquilo).</p>
                      <div className="border-t border-line/60 my-1.5" />
                      <p className="font-semibold text-ink-0">Cómo leerlo</p>
                      <p><span className="text-ink-2">≈ 0</span>: matcheás al benchmark.</p>
                      <p><span className="text-rendi-pos">&gt; 0.5</span>: consistencia en outperform.</p>
                      <p><span className="text-rendi-pos">&gt; 1.0</span>: excelente (raro mantener sostenido).</p>
                      <p><span className="text-rendi-neg">&lt; 0</span>: underperformance crónica.</p>
                      <div className="border-t border-line/60 my-1.5" />
                      <p className="font-semibold text-ink-0">Cómo se calcula</p>
                      <p className="text-ink-3 font-mono text-[11px]">IR = active_return<sub>anual</sub> / tracking_error<sub>anual</sub></p>
                      <p className="text-ink-3">Active return: {(proMetrics.infoRatio.activeReturn * 100).toFixed(1)}% · Tracking error: {(proMetrics.infoRatio.trackingError * 100).toFixed(1)}%</p>
                    </>
                  }
                >
                  <div className="flex items-baseline gap-3">
                    <p className={`text-3xl font-bold tabular ${
                      proMetrics.infoRatio.infoRatio >= 1 ? 'text-rendi-pos'
                      : proMetrics.infoRatio.infoRatio >= 0.5 ? 'text-emerald-600/80 dark:text-emerald-400/80'
                      : proMetrics.infoRatio.infoRatio >= 0 ? 'text-ink-1'
                      : 'text-rendi-neg'
                    }`}>
                      {proMetrics.infoRatio.infoRatio >= 0 ? '+' : '−'}{Math.abs(proMetrics.infoRatio.infoRatio).toFixed(2)}
                    </p>
                    <p className="text-xs text-ink-3 tabular">
                      {proMetrics.infoRatio.infoRatio >= 1 ? 'Excelente'
                       : proMetrics.infoRatio.infoRatio >= 0.5 ? 'Consistente'
                       : proMetrics.infoRatio.infoRatio >= 0 ? 'Marginal'
                       : 'Underperform'}
                    </p>
                  </div>
                  <p className="text-xs text-ink-3 mt-2 leading-snug">
                    Consistencia del outperformance vs S&P por unidad de tracking error.
                  </p>
                </InsightCard>
              ) : null
            ) : (
              <LockedSection.Placeholder
                feature="insights.metrics_pro_ir"
                title="Information Ratio"
                description="Consistencia del outperformance vs el benchmark por unidad de tracking error. Disponible en Pro."
                source="insights_metrics_pro"
              />
            )}
          </div>
        </Section>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          C2. PERFIL DEL INVERSOR — cruza el test (perfil declarado) con la
              cartera real. Solo descriptivo: presenta el dato, no juzga.
              Si el user no completó el test → un solo CTA al test (no 2
              empty states duplicados).
          ══════════════════════════════════════════════════════════════════════ */}
      <Section
        title="Perfil del inversor"
        subtitle="Cómo se alinea tu cartera real con lo que declaraste en el test."
      >
        <ProfileInvestorBlock
          allocationCard={allocationCard}
          objectiveCard={objectiveCard}
          horizonCard={horizonCard}
          drawdownCard={drawdownCard}
          concentrationCard={concentrationCard}
        />
      </Section>

      {/* Diagnóstico se renderiza arriba como hero — ver bloque al inicio. */}

      {/* Qué explica tu resultado — top contributors + detractors */}
      {(topContribPos.length > 0 || topContribNeg.length > 0) && (
        <Section
          id="atribucion"
          title="Atribución por activo"
          subtitle={`Activos que más impactan tu P&L total — incluye operaciones cerradas y posiciones abiertas, en ${currency}.`}
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ContribList tone="positive" title="A favor" items={topContribPos} fmt={amt} />
            <ContribList tone="negative" title="En contra" items={topContribNeg} fmt={amt} />
          </div>
        </Section>
      )}

      {/* Otras señales (warning / info) — alertas no urgentes */}
      {otherAlerts.length > 0 && (
        <Section title="Otras señales" subtitle="Alertas adicionales y observaciones complementarias.">
          <div className="space-y-2">
            {otherAlerts.map((a, i) => (
              <AlertBanner key={`other-${i}`} level={a.level} category={a.category} title={a.title} text={a.text} />
            ))}
          </div>
        </Section>
      )}

      {/* ── Distribución (broker + activo + tipo) ───────────────────────────── */}
      <Section title="Distribución" subtitle="Cómo se reparte tu capital entre brokers, activos y clases de instrumento.">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Pie chart por broker */}
        <div className="bg-white dark:bg-bg-1 border border-line rounded p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-ink-0">Por broker</h2>
            {brokerConcentration && (
              <span className="text-xs text-ink-3">
                Top: <span className="font-medium text-ink-1">{brokerConcentration.top.name}</span> ({brokerConcentration.top.sharePct.toFixed(0)}%)
              </span>
            )}
          </div>
          {pieData.length === 0 ? (
            <p className="text-ink-3 text-sm text-center py-8">Aún no hay posiciones cargadas.</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={95} dataKey="value" paddingAngle={3}>
                  {pieData.map((_, i) => <Cell key={`pie-d-${i}`} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Legend formatter={(v) => <span className="text-ink-2 text-xs">{v}</span>} iconType="circle" iconSize={8} />
                <Tooltip
                  contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                  formatter={(v) => [`${amt(v)} (${((v / totalPortfolio) * 100).toFixed(1)}%)`, '']}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>

        {plan.can('insights.distribucion_activo') ? (
          <div className="bg-white dark:bg-bg-1 border border-line rounded p-5">
            <h2 className="font-semibold text-ink-0 mb-4">Por activo</h2>
            {assetPieData.length === 0 ? (
              <p className="text-ink-3 text-sm text-center py-8">—</p>
            ) : (
              <div className="space-y-3">
                {assetPieData.map((d, i) => {
                  const p = (d.value / totalPortfolio) * 100
                  return (
                    <div key={d.name}>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-ink-1">{d.name}</span>
                        <span className="text-ink-3 tabular">{amt(d.value)} · {p.toFixed(1)}%</span>
                      </div>
                      <div className="h-2 bg-bg-2 dark:bg-bg-2/40 rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${p}%`, background: PIE_COLORS[i % PIE_COLORS.length] }} />
                      </div>
                    </div>
                  )
                })}
                {assetPieData[0] && assetPieData[0].value / totalPortfolio > 0.6 && (
                  <p className="text-xs text-rendi-warn pt-2 flex items-start gap-1">
                    <AlertTriangle size={13} className="mt-0.5 flex-shrink-0" />
                    Concentración elevada en {assetPieData[0].name} ({((assetPieData[0].value / totalPortfolio) * 100).toFixed(0)}%).
                  </p>
                )}
              </div>
            )}
          </div>
        ) : (
          <LockedSection.Placeholder
            feature="insights.distribucion_activo"
            title="Distribución por activo"
            description="Visualizá cómo se reparte tu capital entre cada activo individual con concentración y alertas. Disponible en Rendi Pro."
            source="insights_distribucion_activo"
            className="min-h-[260px] flex flex-col items-center justify-center"
          />
        )}
      </div>

      {/* Distribución por tipo de activo (cripto / acción / CEDEAR / cash) */}
      <div className="bg-white dark:bg-bg-1 border border-line rounded p-5 mt-6">
        <div className="flex items-center gap-1.5 mb-4">
          <h2 className="font-semibold text-ink-0">Distribución por tipo de activo</h2>
          <InfoTooltip>
            <p className="font-semibold text-ink-0">Cómo se calcula</p>
            <p>Clasificación automática por ticker y broker:</p>
            <p className="text-ink-3">• Cripto: tickers conocidos (BTC, ETH, SOL, etc.).</p>
            <p className="text-ink-3">• CEDEAR/Acciones AR: posiciones en brokers locales.</p>
            <p className="text-ink-3">• Acciones/ETFs: posiciones en brokers USD que no son cripto.</p>
            <p className="text-ink-3">• Cash: posiciones marcadas como efectivo.</p>
          </InfoTooltip>
        </div>
        {assetTypeBreakdown.length === 0 ? (
          <p className="text-ink-3 text-sm text-center py-6">—</p>
        ) : (
          <div className="space-y-3">
            {assetTypeBreakdown.map((d, i) => (
              <div key={d.type}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-ink-1">{d.type}</span>
                  <span className="text-ink-3 tabular">{amt(d.value)} · {d.sharePct.toFixed(1)}%</span>
                </div>
                <div className="h-2 bg-bg-2 dark:bg-bg-2/40 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${d.sharePct}%`, background: PIE_COLORS[i % PIE_COLORS.length] }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      </Section>

      {/* ── Comparativa con benchmarks (simulación con mismos aportes) ─────── */}
      <Section
        title="Comparativa con benchmarks"
        subtitle="Qué hubieras obtenido aplicando los mismos aportes y retiros, en las mismas fechas, a inversiones alternativas."
      >
        {globalMonthly.length === 0 ? (
          <Card>
            <EmptyState
              icon={<Scale size={20} />}
              title="Sin meses registrados"
              description="Cargá al menos un mes en el Resumen Mensual para habilitar las comparativas con benchmarks."
            />
          </Card>
        ) : (
          <>
            {/* Grupo USD: alternativas en dólares */}
            <div className="mb-3">
              <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2">
                Alternativas en USD
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <BenchmarkCard
                  label="vs S&P 500"
                  hint="Índice global de referencia"
                  disabled={!sp500Sim}
                  disabledHint="Datos del S&P 500 no disponibles."
                  myValue={totalPortfolio}
                  benchmarkValue={sp500Sim?.finalValue}
                  delta={vsSp500}
                  amt={amt}
                />
                <BenchmarkCard
                  label="vs T-Bills USD"
                  hint="Tasa libre de riesgo USD (ETF SHV)"
                  disabled={!shvSim}
                  disabledHint="Datos de T-Bills no disponibles."
                  myValue={totalPortfolio}
                  benchmarkValue={shvSim?.finalValue}
                  delta={vsShv}
                  amt={amt}
                />
                <BenchmarkCard
                  label="vs Oro"
                  hint="Hedge contra inflación (ETF GLD)"
                  disabled={!goldSim}
                  disabledHint="Datos del oro no disponibles."
                  myValue={totalPortfolio}
                  benchmarkValue={goldSim?.finalValue}
                  delta={vsGold}
                  amt={amt}
                />
                <BenchmarkCard
                  label="vs Dólar quieto"
                  hint="Si los dólares hubieran quedado en efectivo"
                  disabled={false}
                  myValue={totalPortfolio}
                  benchmarkValue={dolarCashSim?.finalValue}
                  delta={vsDolar}
                  amt={amt}
                />
              </div>
            </div>

            {/* Grupo ARS: alternativas en pesos */}
            <div>
              <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2">
                Alternativas en ARS
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <InflationCard inflation={inflationCum} />
                <BenchmarkCard
                  label="vs Merval"
                  hint="Índice acciones argentinas (en USD-eq)"
                  disabled={!mervalSim}
                  disabledHint="Datos del Merval no disponibles."
                  myValue={totalPortfolio}
                  benchmarkValue={mervalSim?.finalValue}
                  delta={vsMerval}
                  amt={amt}
                />
                <BenchmarkCard
                  label="vs Plazo fijo UVA"
                  hint="PF ajustado por inflación (CER)"
                  disabled={!plazoFijoSim}
                  disabledHint="Datos de UVA no disponibles."
                  myValue={totalPortfolio}
                  benchmarkValue={plazoFijoSim?.finalValue}
                  delta={vsPlazoFijo}
                  amt={amt}
                />
                <BenchmarkCard
                  label="vs Pesos cash"
                  hint="Si cada aporte se hubiera convertido al blue"
                  disabled={!arsCashSim}
                  disabledHint="Datos históricos del blue no disponibles."
                  myValue={totalPortfolio}
                  benchmarkValue={arsCashSim?.finalValue}
                  delta={vsArs}
                  amt={amt}
                />
              </div>
            </div>

            <p className="text-[11px] text-ink-3 mt-3 leading-snug px-1">
              <Info size={11} className="inline -mt-0.5 mr-1" />
              Benchmarks calculados replicando tus depósitos y retiros en las mismas fechas. Datos con periodicidad mensual — algunos meses utilizan el último valor disponible si falta el cierre oficial.
            </p>
          </>
        )}
      </Section>

      {/* Coach IA movido al sidebar (botón "Coach IA" arriba de todo) — abre
          un drawer global accesible desde cualquier página. */}

    </div>
  )
}

function BenchmarkCard({ label, hint, disabled, disabledHint, myValue, benchmarkValue, delta, amt }) {
  // Tarjeta de comparación contra un benchmark simulado.
  // Muestra: valor del benchmark, delta vs mi portfolio (USD y %).
  // Verde si gano al benchmark, rojo si pierdo.
  if (disabled || benchmarkValue == null || delta == null) {
    return (
      <div className="bg-white dark:bg-bg-1 border border-line rounded p-5">
        <p className="text-xs uppercase tracking-wider font-semibold text-ink-3">{label}</p>
        <p className="text-sm text-ink-3 mt-2">{disabledHint || 'Datos insuficientes para calcular.'}</p>
      </div>
    )
  }
  const gano = delta.delta >= 0
  const accentBorder = gano ? 'border-rendi-pos/40' : 'border-rendi-neg/40'
  const accentText = gano ? 'text-rendi-pos' : 'text-rendi-neg'
  return (
    <div className={`bg-white dark:bg-bg-2/60 border ${accentBorder} rounded-xl shadow-sm dark:shadow-none p-5`}>
      <p className="text-xs uppercase tracking-wider font-semibold text-ink-3">{label}</p>
      <p className={`text-2xl font-bold tabular mt-2 ${accentText}`}>
        {gano ? '+' : '-'}{amt(Math.abs(delta.delta))}
      </p>
      <p className={`text-xs tabular mt-0.5 ${accentText}`}>
        {delta.pct >= 0 ? '+' : ''}{delta.pct.toFixed(1)}% {gano ? 'por encima' : 'por debajo'} del benchmark
      </p>
      <p className="text-[11px] text-ink-3 mt-3 leading-snug">
        {hint}: <span className="font-medium text-ink-1">{amt(benchmarkValue)}</span>
      </p>
    </div>
  )
}

function InflationCard({ inflation }) {
  // Card de contexto: inflación INDEC acumulada del período tracked.
  // No es un benchmark simulado — muestra cuánto tenía que rendir el peso
  // para mantener poder de compra.
  if (!inflation) {
    return (
      <div className="bg-white dark:bg-bg-1 border border-line rounded p-5">
        <p className="text-xs uppercase tracking-wider font-semibold text-ink-3">Inflación AR</p>
        <p className="text-sm text-ink-3 mt-2">No hay datos de IPC suficientes para el período seleccionado.</p>
      </div>
    )
  }
  return (
    <div className="bg-white dark:bg-bg-1 border border-rendi-warn/30 rounded p-5">
      <p className="text-xs uppercase tracking-wider font-semibold text-ink-3">Inflación AR (período)</p>
      <p className="text-2xl font-bold tabular mt-2 text-rendi-warn">
        +{inflation.cumPct.toFixed(1)}%
      </p>
      <p className="text-[11px] text-ink-3 mt-3 leading-snug">
IPC acumulado en {inflation.monthsCounted} {inflation.monthsCounted === 1 ? 'mes' : 'meses'}. Rendimiento mínimo necesario en pesos para preservar el poder adquisitivo.
      </p>
    </div>
  )
}

// PerformanceAttribution — descompone el crecimiento del portfolio en
// "lo que pusiste vs lo que ganaste". Responde la pregunta clave:
// "¿crecí porque invierto bien o porque deposité más plata?"
//
// Visual: barra horizontal apilada + números abajo. Usa los datos de `discipline`:
//   deposits = aportes netos
//   pnl      = ganancia/pérdida real del mercado (no incluye flujos)
//   total    = deposits + pnl (cambio total del portfolio)
function PerformanceAttribution({ discipline, amt }) {
  const { deposits, pnl, total } = discipline
  const totalAbs = Math.abs(deposits) + Math.abs(pnl)
  if (totalAbs === 0) return null
  const depShare = (Math.abs(deposits) / totalAbs) * 100
  const pnlShare = (Math.abs(pnl) / totalAbs) * 100
  const pnlPositive = pnl >= 0

  return (
    <div className="bg-white dark:bg-bg-1 border border-line rounded p-5 mt-6">
      <div className="flex items-start justify-between gap-2 mb-1 flex-wrap">
        <div className="flex items-center gap-1.5">
          <h2 className="font-semibold text-ink-0">Atribución del crecimiento</h2>
          <InfoTooltip>
            <p className="font-semibold text-ink-0">Cómo se calcula</p>
            <p>El portfolio crece o decrece por dos vías: <span className="font-medium">aportes netos</span> (depósitos menos retiros) y <span className="font-medium">rendimiento del mercado</span> (P&L mensual).</p>
            <p className="text-ink-3">Si el crecimiento proviene principalmente de aportes, no refleja gestión sino capital nuevo. La performance real es la rentabilidad generada sobre el capital ya invertido.</p>
          </InfoTooltip>
        </div>
        <span className="text-xs text-ink-3 tabular">
          Total: <span className="font-semibold text-ink-1">{amt(total, { signed: true })}</span>
        </span>
      </div>
      <p className="text-xs text-ink-3 mb-4">
        Qué porción del crecimiento proviene del rendimiento del mercado vs nuevos aportes.
      </p>

      {/* Stacked bar */}
      <div className="h-3 bg-bg-2 dark:bg-bg-1/50 rounded-full overflow-hidden flex">
        <div
          className="h-full bg-ink-3/70 dark:bg-bg-20/70 transition-[width] duration-300 ease-out motion-reduce:transition-none"
          style={{ width: `${depShare}%` }}
          title="Aportes netos"
        />
        <div
          className={`h-full transition-[width] duration-300 ease-out motion-reduce:transition-none ${pnlPositive ? 'bg-rendi-pos' : 'bg-rendi-neg'}`}
          style={{ width: `${pnlShare}%` }}
          title={pnlPositive ? 'Rendimiento del mercado' : 'Pérdida del mercado'}
        />
      </div>

      {/* Numeric breakdown */}
      <div className="grid grid-cols-2 gap-4 mt-4">
        <div className="flex items-start gap-2">
          <span className="mt-1 inline-block w-2 h-2 rounded-full bg-ink-3 flex-shrink-0" />
          <div>
            <p className="text-xs text-ink-3">Aportes netos</p>
            <p className="text-lg font-semibold text-ink-1 tabular">{amt(deposits, { signed: true })}</p>
            <p className="text-[11px] text-ink-3">{depShare.toFixed(0)}% del cambio</p>
          </div>
        </div>
        <div className="flex items-start gap-2">
          <span className={`mt-1 inline-block w-2 h-2 rounded-full flex-shrink-0 ${pnlPositive ? 'bg-emerald-500' : 'bg-red-500'}`} />
          <div>
            <p className="text-xs text-ink-3">{pnlPositive ? 'Rendimiento del mercado' : 'Pérdida del mercado'}</p>
            <p className={`text-lg font-semibold tabular ${pnlPositive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{amt(pnl, { signed: true })}</p>
            <p className="text-[11px] text-ink-3">{pnlShare.toFixed(0)}% del cambio</p>
          </div>
        </div>
      </div>

      <p className="text-xs text-ink-2 mt-4 leading-snug">
        {pnlShare >= 60 && pnlPositive
          ? 'Más del 60% del crecimiento proviene del rendimiento del mercado. Indicador positivo de gestión.'
          : depShare >= 70
          ? 'El portfolio creció principalmente por nuevos aportes, no por rendimiento. La rentabilidad real depende de lo que genere el capital ya invertido.'
          : pnlPositive
          ? 'Distribución equilibrada entre aportes y rendimiento del mercado.'
          : 'El mercado generó pérdidas en el período. El crecimiento neto se sostiene únicamente con los aportes.'}
      </p>
    </div>
  )
}

function ContribList({ tone, title, items, fmt }) {
  // Top contributors list — used for "Qué explica tu resultado".
  // tone: 'positive' (verde) | 'negative' (rojo)
  // fmt:  formatter that respects the global currency toggle (signed)
  const isPos = tone === 'positive'
  const accentText = isPos ? 'text-rendi-pos' : 'text-rendi-neg'
  return (
    <div className="bg-white dark:bg-bg-1 border border-line rounded p-5">
      <div className="flex items-center gap-2 mb-3 text-ink-3">
        {isPos ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
        <span className="text-xs font-semibold uppercase tracking-wider">{title}</span>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-ink-3">Sin contribuciones significativas.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((it, i) => (
            <li key={it.asset} className="flex items-center justify-between gap-3 py-1">
              <div className="flex items-center gap-2.5 min-w-0">
                <span className={`tabular text-xs font-semibold w-4 ${isPos ? 'text-rendi-pos/70' : 'text-rendi-neg/70'}`}>{i + 1}</span>
                <AssetLogo asset={it.asset} size={24} />
                <span className="font-semibold text-ink-0">{it.asset}</span>
              </div>
              <span className={`tabular font-bold ${accentText}`}>
                {fmt ? fmt(it.pnl, { signed: true }) : (it.pnl >= 0 ? `+USD ${it.pnl.toFixed(2)}` : `-USD ${Math.abs(it.pnl).toFixed(2)}`)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// DiagnosticText — renderiza bullets de diagnóstico con `**...**` en negrita.
// Mantenemos la sintaxis simple (no es markdown completo): split por **,
// cada índice impar va en <strong>.
function DiagnosticText({ text }) {
  if (!text) return null
  const parts = text.split('**')
  return (
    <>
      {parts.map((part, i) => (
        i % 2 === 1
          ? <strong key={i} className="font-semibold text-ink-0 dark:text-white">{part}</strong>
          : <span key={i}>{part}</span>
      ))}
    </>
  )
}

// Grid de tarjetas accionables (audit pattern). Container con bg-line +
// gap-px crea los divisores 1px sin pelear con first-child en wraps.
// Funciona con cualquier número de items: 1, 3, 4, 6...
function DiagnosisGrid({ items }) {
  if (!items || items.length === 0) return null
  return (
    <div className="bg-bg-2 dark:bg-line border border-line rounded overflow-hidden">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-px">
        {items.map(d => <DiagnosisCard key={d.id} d={d} />)}
      </div>
    </div>
  )
}

function DiagnosisCard({ d }) {
  const sev = SEVERITY_BADGE[d.severity] || SEVERITY_BADGE.info
  const cta = ctaForCategory(d.category)
  // Parse del text: primera oración = título, resto = contexto.
  // Quitamos markdown bold para que el LLM reciba texto plano limpio.
  const plainText = (d.text || '').replace(/\*\*/g, '')
  const parts = plainText.split(/\.\s+/)
  const title = parts[0] + (parts.length > 1 ? '.' : '')
  const context = parts.slice(1).join('. ').trim()
  return (
    <AskAIAbout
      topic="insights.observation"
      params={{
        id: d.id,
        title,
        text: plainText,
        category: d.category,
        level: d.severity,
      }}
      subtitle={title.length > 60 ? title.slice(0, 60) + '…' : title}
      className="h-full"
    >
      <div className="bg-white dark:bg-bg-1 p-5 flex flex-col h-full">
        <div className="flex items-center gap-2 mb-3">
          <span className={`text-[10px] font-mono uppercase tracking-[0.12em] px-2 py-0.5 rounded-sm border ${sev.badgeCls}`}>
            {sev.label}
          </span>
        </div>
        <p className="text-sm font-medium leading-snug text-ink-0 mb-2">
          <DiagnosticText text={title} />
        </p>
        {context && (
          <p className="text-xs text-ink-2 leading-relaxed flex-1">
            <DiagnosticText text={context} />
          </p>
        )}
        {cta && (
          cta.href.startsWith('#') ? (
            <a
              href={cta.href}
              className="inline-flex items-center gap-1 mt-4 text-xs text-rendi-accent hover:underline self-start"
            >
              {cta.label} <ArrowRight size={11} strokeWidth={1.75} />
            </a>
          ) : (
            <Link
              to={cta.href}
              className="inline-flex items-center gap-1 mt-4 text-xs text-rendi-accent hover:underline self-start"
            >
              {cta.label} <ArrowRight size={11} strokeWidth={1.75} />
            </Link>
          )
        )}
      </div>
    </AskAIAbout>
  )
}

function Section({ id, title, subtitle, children }) {
  return (
    <section id={id} className={id ? 'scroll-mt-20' : undefined}>
      <div className="mb-3">
        <h2 className="section-title">{title}</h2>
        {subtitle && <p className="section-subtitle">{subtitle}</p>}
      </div>
      {children}
    </section>
  )
}

function AlertBanner({ level, category, title, text }) {
  const styles = {
    danger:  { wrap: 'bg-red-500/[0.06] border-red-500/25',     iconColor: 'text-rendi-neg',     titleColor: 'text-red-700 dark:text-red-300',     textColor: 'text-red-700/75 dark:text-red-300/80',     badge: 'bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30',           Icon: AlertTriangle },
    warning: { wrap: 'bg-amber-500/[0.06] border-amber-500/25', iconColor: 'text-amber-500 dark:text-amber-400', titleColor: 'text-amber-700 dark:text-amber-300', textColor: 'text-amber-700/75 dark:text-amber-300/80', badge: 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30',  Icon: AlertTriangle },
    info:    { wrap: 'bg-bg-20/[0.06] border-line-2/25', iconColor: 'text-ink-3', titleColor: 'text-ink-0', textColor: 'text-ink-2',     badge: 'bg-bg-20/15 text-ink-1 border-line-2/30',  Icon: Info },
  }
  const s = styles[level] || styles.info
  const Icon = s.Icon
  return (
    <div className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${s.wrap}`}>
      <Icon size={16} className={`${s.iconColor} flex-shrink-0 mt-0.5`} strokeWidth={2.2} />
      <div className="text-sm leading-snug flex-1 min-w-0">
        {category && (
          <span className={`inline-block text-[9px] font-semibold uppercase tracking-[0.1em] px-1.5 py-0.5 rounded border mr-2 align-middle ${s.badge}`}>
            {category}
          </span>
        )}
        <span className={`font-semibold ${s.titleColor}`}>{title}</span>
        <span className={s.textColor}> — {text}</span>
      </div>
    </div>
  )
}

function InsightCard({ icon, title, children, accent, tooltip }) {
  return (
    <div className={`bg-white dark:bg-bg-1 border rounded p-5 ${
      accent ? 'border-rendi-accent/40 dark:border-rendi-accent/30' : 'border-line/80 dark:border-line'
    }`}>
      <div className="flex items-center gap-2 mb-3 text-ink-3">
        {icon}
        <span className="text-xs font-medium uppercase tracking-wide flex-1">{title}</span>
        {tooltip && <InfoTooltip>{tooltip}</InfoTooltip>}
      </div>
      {children}
    </div>
  )
}


// ─── Profile Investor Block ─────────────────────────────────────────────────
// Renderiza las cards del perfil del inversor. Maneja 3 estados globales:
//   • Sin profile (no_profile / no_data): un solo CTA al test (no 2 cards
//     vacías). Mejor UX que duplicar empty states.
//   • Sin cartera: cards muestran lo declarado + CTA a conectar broker.
//   • Ready: 2 cards con datos cruzados.
//
// Tono descriptivo estricto. Sin "deberías", "te conviene", "recomendamos".

function ProfileInvestorBlock({
  allocationCard, objectiveCard, horizonCard, drawdownCard, concentrationCard,
}) {
  // Si las cards basadas en perfil NO tienen perfil utilizable, mostramos
  // un CTA único en vez de 5 empty states duplicados.
  // Chequeamos las cards que dependen de la categoría derivada (allocation +
  // concentration) — si esas dos están sin profile, el resto también lo está.
  const noProfileAtAll =
    (allocationCard?.status === 'no_profile' || allocationCard?.status === 'no_data') &&
    (objectiveCard?.status === 'no_profile' || objectiveCard?.status === 'no_data') &&
    (horizonCard?.status === 'no_profile' || horizonCard?.status === 'no_data')

  if (noProfileAtAll) {
    return (
      <div className="bg-white dark:bg-bg-1 border border-line/80 dark:border-line rounded p-6 flex flex-col items-start gap-3">
        <div className="flex items-center gap-2 text-ink-3">
          <UserRound size={18} />
          <span className="text-xs font-medium uppercase tracking-wide">Completá el test de inversor</span>
        </div>
        <p className="text-sm text-ink-1 leading-snug max-w-xl">
          El test de 7 preguntas define tu perfil (conservador / moderado / agresivo) y nos permite
          mostrarte cómo se alinea tu cartera real con lo que declarás.
        </p>
        <Link
          to="/perfil-inversor"
          className="inline-flex items-center gap-1.5 text-xs font-medium bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 rounded-sm px-3 py-2 transition-colors"
        >
          Hacer el test
          <ArrowRight size={13} strokeWidth={1.75} />
        </Link>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <ProfileAllocationCard data={allocationCard} />
      <ProfileObjectiveCard data={objectiveCard} />
      <ProfileHorizonCard data={horizonCard} />
      <ProfileDrawdownCard data={drawdownCard} />
      <ProfileConcentrationCard data={concentrationCard} />
    </div>
  )
}


// Card 1: Match perfil vs cartera (allocation por bucket).
function ProfileAllocationCard({ data }) {
  const tooltip = (
    <>
      <p className="font-semibold text-ink-0">Cómo se calcula</p>
      <p>Cruza tu perfil declarado en el test (conservador / moderado / agresivo) con la asignación real de tu cartera dividida en 4 buckets: cash, renta fija (bonos AR + LECAPs), renta variable (acciones + CEDEARs + ETFs) y alternativos (crypto).</p>
      <p className="text-ink-3">Asignación sugerida = mediana de lo que publican brokers/bancos AR (Balanz, IOL, Cocos, BBVA, Santander) para cada perfil. Orientativo, no normativo.</p>
    </>
  )

  return (
    <InsightCard
      icon={<Scale size={18} />}
      title="Match perfil vs cartera"
      tooltip={tooltip}
    >
      {data.status === 'no_portfolio' ? (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Tu perfil es <span className="font-semibold text-ink-0">{data.declared.categoryLabel}</span>.
            La asignación de referencia es{' '}
            <span className="text-ink-0">
              {data.declared.suggested.cash}% cash · {data.declared.suggested.fixed_income}% renta fija ·{' '}
              {data.declared.suggested.equity}% renta variable
              {data.declared.suggested.alternative > 0 && (
                <> · {data.declared.suggested.alternative}% alternativos</>
              )}
            </span>.
          </p>
          <p className="text-xs text-ink-3 mt-3 leading-snug">
            Cargá posiciones para ver cómo se compara tu cartera real.
          </p>
        </>
      ) : (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Tu perfil es <span className="font-semibold text-ink-0">{data.declared.categoryLabel}</span>.
          </p>
          <div className="mt-3 space-y-1.5">
            <AllocationRow
              label="Sugerida"
              buckets={data.declared.suggested}
              tone="muted"
            />
            <AllocationRow
              label="Tu cartera"
              buckets={data.actual.buckets}
              tone="primary"
            />
          </div>
          <p className="text-xs text-ink-3 mt-3 leading-snug">
            Desvío total: <span className="text-ink-1 font-semibold">{Math.round(data.comparison.driftPct)}%</span>{' '}
            de tu cartera está en buckets distintos a la asignación de referencia.
          </p>
        </>
      )}
    </InsightCard>
  )
}


// Card 5: Coherencia objetivo declarado.
function ProfileObjectiveCard({ data }) {
  const tooltip = (
    <>
      <p className="font-semibold text-ink-0">Qué es</p>
      <p>Cruza el objetivo que declaraste en el test (jubilación, libertad financiera, compra puntual, etc.) con la composición real de tu cartera.</p>
      <div className="border-t border-line/60 my-1.5" />
      <p className="font-semibold text-ink-0">Qué cuenta como "alineado"</p>
      <p><strong>Corto plazo</strong> (compra puntual, jubilación cercana → &lt; 5 años): cash + renta fija.</p>
      <p><strong>Largo plazo</strong> (libertad financiera, aprender, hobby → &gt; 10 años): renta variable + alternativos (crypto).</p>
      <p className="text-ink-3">Para objetivos de corto plazo, la prioridad es preservar capital. Para largo plazo, es crecer (incluso aceptando volatilidad).</p>
    </>
  )

  return (
    <InsightCard
      icon={<Target size={18} />}
      title="Coherencia objetivo declarado"
      tooltip={tooltip}
    >
      {data.status === 'no_portfolio' ? (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Tu objetivo declarado es <span className="font-semibold text-ink-0">{data.declared.goalLabel}</span>{' '}
            ({data.declared.timeframe}). La asignación alineada con ese objetivo es en{' '}
            <span className="text-ink-0">{data.declared.alignedLabel}</span>.
          </p>
          <p className="text-xs text-ink-3 mt-3 leading-snug">
            Cargá posiciones para ver el porcentaje real.
          </p>
        </>
      ) : (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Marcaste <span className="font-semibold text-ink-0">{data.declared.goalLabel}</span> como objetivo
            principal ({data.declared.timeframe}).
          </p>
          <div className="mt-3 flex items-baseline gap-3">
            <p className="text-2xl font-bold text-ink-0 tabular">
              {data.actual.alignedPct}%
            </p>
            <p className="text-xs text-ink-3">
              de tu cartera está en {data.declared.alignedLabel}
            </p>
          </div>
          <p className="text-xs text-ink-2 mt-3 leading-snug">
            El restante <span className="text-ink-0 tabular">{data.actual.misalignedPct}%</span> está en {data.declared.misalignedLabel}.
          </p>
        </>
      )}
    </InsightCard>
  )
}


// Card 2: Horizonte declarado vs composición.
function ProfileHorizonCard({ data }) {
  const tooltip = (
    <>
      <p className="font-semibold text-ink-0">Qué es</p>
      <p>Cruza el horizonte que declaraste (corto / medio / largo plazo) con la composición real de tu cartera.</p>
      <div className="border-t border-line/60 my-1.5" />
      <p className="font-semibold text-ink-0">Qué cuenta como "consistente"</p>
      <p><strong>Horizonte largo</strong>: renta variable + alternativos (crecimiento — podés esperar a que se recuperen las caídas).</p>
      <p><strong>Horizonte corto</strong>: cash + renta fija (preservación — no podés esperar).</p>
      <div className="border-t border-line/60 my-1.5" />
      <p className="text-ink-3"><strong className="text-ink-1">"Riesgo" acá significa "riesgo de timing"</strong>, no calidad del activo: una buena acción puede estar abajo justo el día que tenés que vender. Para horizonte corto, eso es lo que se quiere evitar.</p>
    </>
  )

  return (
    <InsightCard
      icon={<Clock size={18} />}
      title="Horizonte vs composición"
      tooltip={tooltip}
    >
      {data.status === 'no_portfolio' ? (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Marcaste horizonte <span className="font-semibold text-ink-0">{data.declared.horizonLabel}</span>.
            La composición consistente con ese horizonte es {data.declared.expectedLabel}.
          </p>
          <p className="text-xs text-ink-3 mt-3 leading-snug">
            Cargá posiciones para ver el porcentaje real.
          </p>
        </>
      ) : (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Marcaste horizonte <span className="font-semibold text-ink-0">{data.declared.horizonLabel}</span>.
          </p>
          <div className="mt-3 flex items-baseline gap-3">
            <p className="text-2xl font-bold text-ink-0 tabular">
              {data.actual.expectedPct}%
            </p>
            <p className="text-xs text-ink-3">
              de tu cartera está en {data.declared.expectedLabel}
            </p>
          </div>
          <p className="text-xs text-ink-2 mt-3 leading-snug">
            El restante <span className="text-ink-0 tabular">{data.actual.riskPct}%</span> está en {data.declared.riskLabel}.
          </p>
        </>
      )}
    </InsightCard>
  )
}


// Card 3: Tolerancia drawdown declarada vs drawdown real.
function ProfileDrawdownCard({ data }) {
  const tooltip = (
    <>
      <p className="font-semibold text-ink-0">Cómo se calcula</p>
      <p>El test pregunta qué harías ante un drawdown del 30% (vender todo / vender una parte / mantener / comprar más). Mapeamos esa respuesta a un rango de tolerancia implícita (vender todo ≈ 5-12%, mantener ≈ 20-30%, etc.) y lo cruzamos con el drawdown máximo real de tu cartera en TWRR.</p>
      <p className="text-ink-3">Los rangos son heurísticos basados en literatura de behavioral finance — orientativos, no diagnósticos.</p>
    </>
  )

  return (
    <InsightCard
      icon={<TrendingDown size={18} />}
      title="Drawdown tolerado vs real"
      tooltip={tooltip}
    >
      {data.status === 'no_portfolio' ? (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Ante un drawdown del 30% marcaste que <span className="font-semibold text-ink-0">{data.declared.behaviorLabel}</span>,
            lo que implica una tolerancia aproximada de{' '}
            <span className="text-ink-0 tabular">{data.declared.impliedTolerance.min}-{data.declared.impliedTolerance.max}%</span>.
          </p>
          <p className="text-xs text-ink-3 mt-3 leading-snug">
            Cargá operaciones para ver el drawdown máximo histórico de tu cartera.
          </p>
        </>
      ) : (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Marcaste <span className="font-semibold text-ink-0">{data.declared.behaviorLabel}</span>{' '}
            (tolerancia aprox <span className="tabular">{data.declared.impliedTolerance.min}-{data.declared.impliedTolerance.max}%</span>).
          </p>
          <div className="mt-3 flex items-baseline gap-3">
            <p className="text-2xl font-bold text-ink-0 tabular">
              {data.actual.drawdownPct}%
            </p>
            <p className="text-xs text-ink-3">
              drawdown máximo de tu cartera (TWRR)
            </p>
          </div>
          <p className="text-xs text-ink-2 mt-3 leading-snug">
            {data.comparison === 'within'
              ? `Dentro del rango de tolerancia que declaraste.`
              : data.comparison === 'below'
                ? `Por debajo del rango declarado.`
                : `Por encima del rango declarado.`}
          </p>
        </>
      )}
    </InsightCard>
  )
}


// Card 4: Concentración top 3 vs benchmark del perfil.
function ProfileConcentrationCard({ data }) {
  const tooltip = (
    <>
      <p className="font-semibold text-ink-0">Cómo se calcula</p>
      <p>Suma del % que representan tus 3 activos más grandes (por valor en USD, agregando entre brokers) sobre el total del portfolio. Excluye cash.</p>
      <p className="text-ink-3">Rango típico por perfil: orientativo. Más concentración suele tolerarse en perfiles agresivos (que ya asumen más riesgo). Los rangos son referencia, no diagnóstico.</p>
    </>
  )

  return (
    <InsightCard
      icon={<Layers size={18} />}
      title="Concentración vs perfil"
      tooltip={tooltip}
    >
      {data.status === 'no_portfolio' ? (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Tu perfil es <span className="font-semibold text-ink-0">{data.declared.categoryLabel}</span>.
            La concentración top 3 típica para este perfil está entre{' '}
            <span className="text-ink-0 tabular">{data.declared.typicalRange.min}-{data.declared.typicalRange.max}%</span>.
          </p>
          <p className="text-xs text-ink-3 mt-3 leading-snug">
            Cargá posiciones para ver tu concentración real.
          </p>
        </>
      ) : (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Tu perfil es <span className="font-semibold text-ink-0">{data.declared.categoryLabel}</span>{' '}
            (rango típico top 3: <span className="tabular">{data.declared.typicalRange.min}-{data.declared.typicalRange.max}%</span>).
          </p>
          <div className="mt-3 flex items-baseline gap-3">
            <p className="text-2xl font-bold text-ink-0 tabular">
              {data.actual.top3Pct}%
            </p>
            <p className="text-xs text-ink-3">
              en {data.actual.holdingsCount < 3
                ? `tus ${data.actual.holdingsCount} ${data.actual.holdingsCount === 1 ? 'activo' : 'activos'}`
                : 'tus top 3'}
              {data.actual.top3Assets.length > 0 && (
                <> ({data.actual.top3Assets.join(', ')})</>
              )}
            </p>
          </div>
          <p className="text-xs text-ink-2 mt-3 leading-snug">
            {data.comparison === 'within'
              ? `Dentro del rango típico para perfil ${data.declared.categoryLabel}.`
              : data.comparison === 'below'
                ? `Por debajo del rango típico.`
                : `Por encima del rango típico.`}
          </p>
        </>
      )}
    </InsightCard>
  )
}


// Helper visual: barra horizontal con los 4 buckets de allocation.
// Usado en Card 1 (Match perfil vs cartera) para comparar sugerida vs real
// con jerarquía clara (sugerida = muted, tu cartera = primary).
function AllocationRow({ label, buckets, tone = 'muted' }) {
  const colorByBucket = {
    cash:         tone === 'muted' ? 'bg-ink-3/30' : 'bg-rendi-pos/70',
    fixed_income: tone === 'muted' ? 'bg-ink-3/30' : 'bg-data-blue/70',
    equity:       tone === 'muted' ? 'bg-ink-3/30' : 'bg-data-violet/70',
    alternative:  tone === 'muted' ? 'bg-ink-3/30' : 'bg-data-amber/70',
  }
  const labelByBucket = {
    cash: 'Cash',
    fixed_income: 'Renta fija',
    equity: 'R. variable',
    alternative: 'Alt.',
  }
  return (
    <div>
      <div className="flex items-baseline justify-between mb-0.5">
        <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">{label}</span>
        <span className="text-[10px] font-mono text-ink-3 tabular">
          {buckets.cash}/{buckets.fixed_income}/{buckets.equity}{buckets.alternative > 0 ? `/${buckets.alternative}` : ''}
        </span>
      </div>
      <div className="h-2 flex rounded-sm overflow-hidden bg-bg-2">
        {['cash', 'fixed_income', 'equity', 'alternative'].map((b) => {
          const pct = buckets[b] || 0
          if (pct === 0) return null
          return (
            <div
              key={b}
              className={`${colorByBucket[b]} transition-all`}
              style={{ width: `${pct}%` }}
              title={`${labelByBucket[b]}: ${pct}%`}
            />
          )
        })}
      </div>
    </div>
  )
}
