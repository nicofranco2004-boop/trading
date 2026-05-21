import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import {
  PieChart, Pie, Cell, Legend, Tooltip, LineChart, Line,
  AreaChart, Area, XAxis, YAxis, CartesianGrid, ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { TrendingUp, TrendingDown, AlertTriangle, Info, Activity, Trophy, Target, Layers, Clock, Stethoscope, BarChart3, Scale, PiggyBank, Wallet, CircleDollarSign, Building2, BarChart2 } from 'lucide-react'
import AICoach from '../components/AICoach'
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
  computeInflationCumulative,
} from '../utils/benchmarkSim'
import { selectDiagnostics } from '../utils/diagnostics'
import AssetLogo from '../components/AssetLogo'
import { useAuth } from '../contexts/AuthContext'

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
  const [loading, setLoading] = useState(true)
  // Comisiones: fuente de verdad es el endpoint que suma operation_type='FEE'
  // de import_normalized_tx (con conversión ARS→USD). No usamos op.commissions
  // del operations table porque queda contaminado por imports viejos con bugs.
  const [commissionsApi, setCommissionsApi] = useState(null)

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    try {
      const [mon, pos, bkrs, b, snaps, dol, ops, comm] = await Promise.all([
        api.get('/monthly'),
        api.get('/positions'),
        api.get('/brokers'),
        api.get('/benchmarks').catch(() => null),
        api.get('/snapshots?days=30').catch(() => []),
        api.get('/dolar').catch(() => null),
        api.get('/operations').catch(() => []),
        api.get('/insights/commissions').catch(() => null),
      ])
      setMonthly(mon); setPositions(pos); setBrokers(bkrs); setBench(b); setSnapshots(snaps); setDolar(dol); setOperations(ops); setCommissionsApi(comm)

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

      // Modified Dietz USD
      const isImportInitial = isFirst && ci === 0 && net > 0
      const avgCap = isImportInitial ? net : ci + 0.5 * net
      const rRaw = avgCap > 0 ? (cf - ci - net) / avgCap : 0
      const r = Math.max(rRaw, -0.99)
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
    const firstMk = monthKey(globalMonthly[0].year, globalMonthly[0].month)
    out.push({ key: firstMk, label: benchLabel(firstMk), total: 0, realized: 0 })
    for (const m of globalMonthly) {
      netFlows += (m.deposits || 0) - (m.withdrawals || 0)
      cumRealized += (m.pnl_realized || 0)
      const invested = baseline + netFlows
      const rawTotal = invested > 0 ? ((m.capital_final - invested) / invested) * 100 : 0
      const total = Math.max(rawTotal, -99)
      const real  = invested > 0 ? (cumRealized / invested) * 100 : 0
      const k = monthKey(m.year, m.month)
      out.push({ key: k, label: benchLabel(k), total: +total.toFixed(2), realized: +real.toFixed(2) })
    }
    // Punto "Hoy"
    if (totalPortfolio > 0) {
      const invested = baseline + netFlows
      const rawTotal = invested > 0 ? ((totalPortfolio - invested) / invested) * 100 : 0
      const total = Math.max(rawTotal, -99)
      const real  = invested > 0 ? (cumRealized / invested) * 100 : 0
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
    out.push({ key: firstKey, label: benchLabel(firstKey), total: 0, realized: 0 })

    for (const [k, m] of arsMonths) {
      const fx = lookupBlue(k) || blueBase
      const net = (m.deposits || 0) - (m.withdrawals || 0)
      netFlowsPesos += net * fx
      cumRealizedPesos += (m.pnl_realized || 0) * fx
      const investedPesos = baselinePesos + netFlowsPesos
      const valuePesos    = (m.capital_final || 0) * fx
      const rawTotal   = investedPesos > 0 ? ((valuePesos - investedPesos) / investedPesos) * 100 : 0
      const total      = Math.max(rawTotal, -99)
      const real       = investedPesos > 0 ? (cumRealizedPesos / investedPesos) * 100 : 0
      out.push({ key: k, label: benchLabel(k), total: +total.toFixed(2), realized: +real.toFixed(2) })
    }
    // Punto "Hoy" — valor live de posiciones ARS al blue actual
    const arsLiveUsd = brokers
      .filter(b => arsBrokerNames.has(b.name))
      .reduce((s, b) => s + computeBrokerValue(positions, prices, b, tcBlue).value, 0)
    if (arsLiveUsd > 0) {
      const valueNow = arsLiveUsd * tcBlue
      const investedPesos = baselinePesos + netFlowsPesos
      const rawTotal = investedPesos > 0 ? ((valueNow - investedPesos) / investedPesos) * 100 : 0
      const total = Math.max(rawTotal, -99)
      const real  = investedPesos > 0 ? (cumRealizedPesos / investedPesos) * 100 : 0
      out.push({ key: 'today', label: 'Hoy', total: +total.toFixed(2), realized: +real.toFixed(2) })
    }
    // Deduplicar
    const seen = new Set()
    return out.filter(p => { if (seen.has(p.key)) return false; seen.add(p.key); return true })
  })()

  // Selector de serie para el gráfico de benchmarks
  const activeSeries = currency === 'USD' ? benchSeriesUsd : benchSeriesArs
  const benchmarkKey = currency === 'USD' ? 'S&P 500' : 'Inflación AR'

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
    const spKeys = bench?.sp500 ? Object.keys(bench.sp500).sort() : []
    const rawFirstKey = (windowSeries.find(x => x.key !== 'today') || windowSeries[0]).key
    const windowFirstMonthKey = monthKeyOf(rawFirstKey)

    // Lookup sp500 con fallback al mes anterior disponible
    const spLookup = (key) => {
      if (key === 'today') return bench.sp500[spKeys[spKeys.length - 1]]
      const mk = monthKeyOf(key)
      if (bench.sp500[mk]) return bench.sp500[mk]
      // fallback: último mes <= mk
      let found = null
      for (const k of spKeys) { if (k <= mk) found = k; else break }
      return found ? bench.sp500[found] : null
    }

    // ── Shadow S&P 500 portfolio ───────────────────────────────────────────
    // Simulamos: "qué pasaría si los mismos depósitos/retiros del usuario
    // hubieran ido a S&P 500 en vez de su cartera real". Para cada mes con
    // flow != 0, compramos/vendemos units al precio del S&P de ese mes. El
    // resultado HOY es shadow_value = total_units × precio_actual.
    //
    // Esto reemplaza la línea azul "lump sum from day 1" (que comparaba peras
    // con manzanas: pura apreciación de mercado vs cartera con flows reales).
    // Con shadow portfolio, ambas líneas reflejan las mismas decisiones de
    // capital — sólo difieren en QUÉ activos compraron.
    const shadowPctByKey = new Map()
    if (currency === 'USD' && bench?.sp500 && globalMonthly.length > 0) {
      let units = 0
      let cumNetDep = 0
      let peakNetDep = 0
      // Denominador estable: si el net dep actual cae por debajo del 60% del
      // peak (señal de un retiro grande), usamos el peak. Sin esto, el ratio
      // shadow_value / cumNetDep explota cuando cumNetDep se achica — el
      // mismo bug del % realized de la línea verde, pero en el bench.
      const stableDenom = (cur, peak) =>
        (cur >= peak * 0.6 && cur > 1000) ? cur : peak

      for (const m of globalMonthly) {
        const mk = monthKey(m.year, m.month)
        const spPrice = spLookup(mk)
        const flow = (m.deposits || 0) - (m.withdrawals || 0)
        cumNetDep += flow
        if (cumNetDep > peakNetDep) peakNetDep = cumNetDep
        if (spPrice && flow !== 0) units += flow / spPrice
        const denom = stableDenom(cumNetDep, peakNetDep)
        if (spPrice && denom > 0) {
          const value = units * spPrice
          shadowPctByKey.set(mk, +(((value / denom) - 1) * 100).toFixed(2))
        }
      }
      // Punto "Hoy" — precio más reciente disponible
      const latestSp = bench.sp500[spKeys[spKeys.length - 1]]
      const denomToday = stableDenom(cumNetDep, peakNetDep)
      if (latestSp && denomToday > 0) {
        const value = units * latestSp
        shadowPctByKey.set('today', +(((value / denomToday) - 1) * 100).toFixed(2))
      }
    }

    const withBench = windowSeries.map(s => {
      let benchPct = null
      if (currency === 'USD' && bench?.sp500) {
        const mk = monthKeyOf(s.key)
        if (shadowPctByKey.has(mk)) {
          benchPct = shadowPctByKey.get(mk)
        } else if (shadowPctByKey.size > 0) {
          // Fallback: usar el último mes disponible <= mk (cobre snapshots
          // diarios entre meses sin entry monthly).
          const sortedSk = [...shadowPctByKey.keys()].filter(k => k !== 'today').sort()
          let found = null
          for (const k of sortedSk) { if (k <= mk) found = k; else break }
          if (found) benchPct = shadowPctByKey.get(found)
        }
      } else if (currency === 'ARS' && bench?.inflation_ar) {
        // windowSeries ya es mensual — componer IPC desde el segundo mes.
        let cum = 1
        let started = false
        for (const b of windowSeries) {
          if (b.key === 'today') break
          if (!started) { started = true; continue } // saltar primer mes (base = 0%)
          const inf = bench.inflation_ar[monthKeyOf(b.key)]
          if (inf != null) cum *= 1 + inf / 100
          if (b.key === s.key) break
        }
        benchPct = +((cum - 1) * 100).toFixed(2)
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
  //  hubiera ido a S&P 500 / dólares cash / pesos cash."
  // Cada uno devuelve { finalValue, series, finalUnits } o null si faltan datos.
  const sp500Sim = simulateSp500(globalMonthly, bench?.sp500)
  const dolarCashSim = simulateDolarCash(globalMonthly)
  const arsCashSim = simulateArsCash(globalMonthly, bench?.dolar_blue)
  const inflationCum = computeInflationCumulative(globalMonthly, bench?.inflation_ar)

  // Helper para deltas: cuánto rindió mi portfolio vs el benchmark.
  // Tomamos el "valor final" del benchmark contra `totalPortfolio` (live).
  function compareToMine(benchmarkFinal) {
    if (benchmarkFinal == null || !(totalPortfolio > 0)) return null
    const delta = totalPortfolio - benchmarkFinal
    const pct = benchmarkFinal > 0 ? (delta / benchmarkFinal) * 100 : 0
    return { delta, pct }
  }
  const vsSp500 = sp500Sim ? compareToMine(sp500Sim.finalValue) : null
  const vsDolar = dolarCashSim ? compareToMine(dolarCashSim.finalValue) : null
  const vsArs   = arsCashSim ? compareToMine(arsCashSim.finalValue) : null

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

  // ── Preguntas dinámicas para el AICoach ────────────────────────────────────
  // En lugar de chips genéricos ('¿Cómo está mi portfolio?'), generamos
  // Preguntas data-driven basadas en lo que el portfolio realmente muestra
  // hoy. Cada regla aporta 1 candidata; cortamos en 12 para tener buena
  // variedad sin saturar el UI.
  const aiSuggested = (() => {
    const out = []
    const top = aiPositions[0]
    const top3 = aiPositions.slice(0, 3)
    const bestPos = aiPositions.find(p => (p.pnl_pct ?? 0) > 20)
    const worstPos = aiPositions.find(p => (p.pnl_pct ?? 0) < -15)

    // ── Concentración / composición ─────────────────────────────────────────
    if (top && top.pct_of_portfolio > 30) {
      out.push(`${top.asset} es el ${top.pct_of_portfolio.toFixed(0)}% de mi portfolio — ¿es demasiada concentración?`)
    }
    if (top3.length === 3) {
      const top3Pct = top3.reduce((s, p) => s + (p.pct_of_portfolio || 0), 0)
      if (top3Pct > 60) {
        out.push(`Mi top 3 holdings concentra ${top3Pct.toFixed(0)}% del portfolio — ¿es saludable?`)
      }
    }
    if (cashRatio > 25) {
      out.push(`Tengo ${cashRatio.toFixed(0)}% en cash — ¿estoy perdiendo oportunidades?`)
    } else if (cashRatio < 3) {
      out.push('Tengo casi nada de cash — ¿debería liberar buffer para correcciones?')
    }

    // ── Performance + drawdown ──────────────────────────────────────────────
    if (drawdown?.current && drawdown.current < -10) {
      out.push(`Estoy en un drawdown del ${Math.abs(drawdown.current).toFixed(0)}% — ¿qué hago?`)
    }
    if (drawdown?.max && drawdown.max < -20) {
      out.push(`Mi peor caída histórica fue ${Math.abs(drawdown.max).toFixed(0)}% — ¿es excesivo para mi perfil?`)
    }
    if (totalResult < 0) {
      out.push('¿Por qué estoy perdiendo plata y cómo lo reviero?')
    }
    if (totalResult > 0 && winRate >= 0.5 && (drawdown?.current ?? 0) >= -5) {
      out.push('¿Cómo está mi portfolio en general? ¿Hay algo a optimizar?')
    }

    // ── Benchmarks ──────────────────────────────────────────────────────────
    if (vsSp500 != null && vsSp500 < -5) {
      out.push(`Estoy rindiendo ${Math.abs(vsSp500).toFixed(1)}% peor que el S&P 500 — ¿por qué?`)
    } else if (vsSp500 != null && vsSp500 > 5) {
      out.push(`Le estoy ganando al S&P 500 por ${vsSp500.toFixed(1)}% — ¿qué lo explica?`)
    }
    if (currency === 'ARS' || cashRatio > 10) {
      out.push('¿Mi cartera le gana a la inflación argentina?')
    }

    // ── Trading: win rate + activos puntuales ───────────────────────────────
    if (winRate != null && winRate < 0.5) {
      out.push(`Mi win rate es ${(winRate * 100).toFixed(0)}% — ¿cómo puedo mejorarlo?`)
    }
    if (winRate != null && winRate >= 0.6) {
      out.push(`Tengo ${(winRate * 100).toFixed(0)}% de win rate — ¿es sostenible?`)
    }
    if (worstPos && worstPos.asset) {
      out.push(`${worstPos.asset} viene ${Math.abs(worstPos.pnl_pct).toFixed(0)}% en rojo — ¿la mantengo o salgo?`)
    }
    if (bestPos && bestPos.asset) {
      out.push(`${bestPos.asset} viene +${bestPos.pnl_pct.toFixed(0)}% — ¿conviene tomar ganancia parcial?`)
    }
    if (topContribNeg.length > 0) {
      const worst = topContribNeg[0]
      if (worst && worst.asset) {
        out.push(`¿Vendo ${worst.asset}? Es el activo que más me hace perder.`)
      }
    }

    // ── Estrategia general ──────────────────────────────────────────────────
    out.push('¿Qué riesgos detectás en mi cartera?')
    out.push('¿Mi diversificación está bien?')
    out.push('¿Detectás algún sesgo en mi forma de operar?')
    out.push('¿Qué métrica debería empezar a monitorear y todavía no miro?')
    out.push('Si tuvieras que mejorar UNA cosa de mi cartera, ¿cuál sería?')
    out.push('¿Mi exposure por sector/región está equilibrado?')

    return [...new Set(out)].slice(0, 12)
  })()

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
          ? 'Evolución en USD vs S&P 500, profundidad de drawdowns y atribución del crecimiento.'
          : 'Evolución en pesos vs inflación INDEC, profundidad de drawdowns y atribución del crecimiento.'}
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
              {currency === 'USD' ? 'Portfolio vs S&P 500 (USD)' : 'Portfolio vs Inflación (ARS)'}
            </h2>
            <InfoTooltip>
              <p className="font-semibold text-ink-0">Time-Weighted Return (TWRR)</p>
              <p>Rendimiento <strong>independiente del timing</strong> de tus aportes y retiros — mide solamente cómo performeó el capital invertido. Es la métrica estándar de la industria (la que usa el S&P 500 para reportar).</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Las 3 líneas</p>
              <p><span className="inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle" style={{background:'#21D07A'}}/><strong>P/L total</strong> (verde sólido): rendimiento de tu cartera, incluye realizado + no realizado.</p>
              <p><span className="inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle" style={{background:'#E8B14A'}}/><strong>P/L realizado</strong> (amarillo punteado): solo lo ya cobrado (ventas + dividendos + intereses), excluye plusvalía no realizada.</p>
              <p><span className="inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle" style={{background: currency === 'USD' ? '#46C6E0' : '#8B7DFF'}}/><strong>{currency === 'USD' ? 'S&P 500' : 'Inflación ARS'}</strong>: benchmark de comparación.</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="text-ink-3">
                Puede no coincidir con "Resultado total / Capital aportado" del Dashboard:
                el Dashboard mide cuánto creció tu plata neta; el chart compone rendimientos mes a mes
                — un crash temprano cuesta más en TWRR porque después tenés que recuperar desde una base chica.
              </p>
              {currency === 'USD'
                ? <p className="text-ink-3">Todas las líneas arrancan en 0% al inicio del período seleccionado para comparación directa.</p>
                : <p className="text-ink-3">Fijado a los últimos 12 meses. Períodos más extensos pierden comparabilidad por la hiperinflación previa.</p>
              }
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
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p>Distancia mensual respecto al máximo histórico (HWM) del rendimiento acumulado.</p>
              <p>0% indica que estás en máximos. -10% significa que caíste 10% desde el pico anterior.</p>
              <p className="text-ink-3">Calculado sobre TWRR: los depósitos y retiros no afectan el drawdown.</p>
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
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p><span className="font-medium">Win rate:</span> porcentaje de operaciones cerradas con P&L positivo.</p>
              <p><span className="font-medium">Profit factor:</span> ganancia bruta total dividida por pérdida bruta total.</p>
              <p className="text-ink-3">Excluimos trades con |P&L| &lt; $1.5 USD para evitar el ruido de bots y fees parciales de futuros que destruyen el win rate sin reflejar decisiones reales del trader.</p>
              <p className="text-ink-3">Un win rate alto con ganancias pequeñas puede tener profit factor &lt; 1 (resultado neto negativo aunque aciertes más seguido). Las dos métricas se interpretan en conjunto.</p>
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
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p>Porcentaje del portfolio concentrado en los 3 activos más grandes (excluyendo cash).</p>
              <p className="text-ink-3">Cuanto más alto, mayor el riesgo idiosincrático: una caída en uno solo de esos activos impacta de forma directa.</p>
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
              <p className="font-semibold text-ink-0">Cómo se calcula</p>
              <p>Suma de las filas del CSV importadas explícitamente como "Comisión" / "Fee" (funding fees de futures, withdrawal fees, etc).</p>
              <p className="text-ink-3">Si tu broker es en ARS, convertimos a USD al tipo de cambio blue. Si el fee va embebido en el precio o en otra fila (spread, fee de un trade), no aparece acá.</p>
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
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <BenchmarkCard
                label="vs S&P 500"
                hint="Índice global de referencia · USD"
                disabled={!sp500Sim}
                disabledHint="Datos del S&P 500 no disponibles."
                myValue={totalPortfolio}
                benchmarkValue={sp500Sim?.finalValue}
                delta={vsSp500}
                amt={amt}
              />
              <BenchmarkCard
                label="vs Dólar cash"
                hint="Si los dólares hubieran quedado en efectivo"
                disabled={false}
                myValue={totalPortfolio}
                benchmarkValue={dolarCashSim?.finalValue}
                delta={vsDolar}
                amt={amt}
              />
              <BenchmarkCard
                label="vs Pesos cash"
                hint="Si cada aporte se hubiera convertido a pesos al blue"
                disabled={!arsCashSim}
                disabledHint="Datos históricos del blue no disponibles."
                myValue={totalPortfolio}
                benchmarkValue={arsCashSim?.finalValue}
                delta={vsArs}
                amt={amt}
              />
              <InflationCard inflation={inflationCum} />
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
