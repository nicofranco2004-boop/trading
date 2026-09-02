import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import {
  PieChart, Pie, Cell, Legend, Tooltip, LineChart, Line,
  AreaChart, Area, XAxis, YAxis, CartesianGrid, ResponsiveContainer, ReferenceLine,
  ComposedChart,
} from 'recharts'
import { TrendingUp, TrendingDown, AlertTriangle, Info, Activity, Trophy, Target, Layers, Clock, Stethoscope, BarChart3, Scale, PiggyBank, Wallet, CircleDollarSign, Building2, BarChart2, UserRound, Droplets } from 'lucide-react'
import StatCard from '../components/StatCard'
import PageHeader from '../components/PageHeader'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import AskAIAbout from '../components/ai/AskAIAbout'
import ProfileSummaryBlock from '../components/ai/ProfileSummaryBlock'
import ProfileDashboard from '../components/profile/ProfileDashboard'
import DiagnosticoSummaryBlock from '../components/diagnostico/DiagnosticoSummaryBlock'
import DeltaSinceVisit from '../components/diagnostico/DeltaSinceVisit'
import CompositionByAsset from '../components/diagnostico/CompositionByAsset'
import { buildDiagnosticoLayout } from '../utils/diagnosticoTemplate'
import { useLastVisit } from '../hooks/useLastVisit'
import InsightsKpiStrip from '../components/InsightsKpiStrip'
import ArAlternativesVerdict from '../components/ArAlternativesVerdict'
import Card from '../components/Card'
import InfoTooltip from '../components/InfoTooltip'
import CollapsibleSection from '../components/CollapsibleSection'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { ChevronDown, ChevronUp, Sparkles, X, Lock } from 'lucide-react'
import { usd, fmtUsd, fmtArs, pctSigned, colorClass, MONTHS } from '../utils/format'
import InsightDelDiaHero from '../components/mobile/InsightDelDiaHero'
import { useIsMobile } from '../hooks/useIsMobile'
import { api } from '../utils/api'
import UpgradeModal from '../components/plan/UpgradeModal'
import { track } from '../utils/track'
import { computeBrokerValue, priceSymbol, isArUsdBroker, costInPesos, costInUsd, pesoLotUsd, usdLotValue, isFciSym, trustMktValue } from '../utils/valuation'
import { cedearEspecieBase } from '../utils/tickers'
import { auditPositions, positionPct } from '../utils/valuationGuards'
import { isCrypto, cryptoBrokerFactor } from '../utils/crypto'
import CompositionDonut, { UnclassifiedNote } from '../components/CompositionDonut'
import { computeClassBreakdown } from '../utils/assetClass'
import { computeSectorBreakdown } from '../utils/assetSector'
import { toDistributionAiParams } from '../utils/distributionAi'
import { usePfRollup, pfUsd } from '../hooks/usePfRollup'
import { lookupHistoricalDolar } from '../utils/fx'
import { buildEvolutionFromSnapshots } from '../utils/evolution'
import {
  buildCumulativeReturnSeries,
  drawdownFromPerf,
  cortarPorTramo,
  totalDePunto,
  partirMedidoYEstimado,
  acumuladoPublicado,
  rellenarTimestamps,
  resolucionDeSerie,
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
  monthlyReturnArs,
  applyMtmToMonthly,
  acumuladoDeVentana,
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
import { resolveTierShown, computeDismiss } from '../utils/diagnosticsRotation'
import { computeProMetrics } from '../utils/insightsMetrics'
import AssetLogo from '../components/AssetLogo'
import { useAuth } from '../contexts/AuthContext'
import { pickFinancialRate, useCurrency } from '../contexts/CurrencyContext'
import {
  computeAllocationMatch,
  computeObjectiveCoherence,
  computeHorizonComposition,
  computeDrawdownTolerance,
  computeConcentrationVsProfile,
  computeStyleCoherence,
  computeLiquidityRisk,
  computeReturnExpectation,
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

const MES_CORTO = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']

// Por qué el toggle Certero/Estimado está apagado en pesos. Dice qué falta, no cómo
// está implementado: al usuario no le sirve "arsMonthly no pasa por applyMtmToMonthly".
const MOTIVO_TOGGLE_ARS =
  'Todavía no hay una serie medida de esta cuenta para reconstruir los dos modos'

/**
 * DotSolo — dibuja un punto SÓLO cuando quedó solo en su segmento.
 *
 * ⚠️ POR QUÉ EXISTE. Recharts necesita dos puntos para trazar un path, así que un
 * segmento de UN punto con `dot={false}` no dibuja ni un píxel. Al usuario del caso
 * 452 —cuya única medición a mercado es un punto— el gráfico le quedaba vacío: la
 * ronda 9 le devolvió la historia a la banda y le sacó de la vista el único dato
 * que sí midió. El resto de los puntos siguen sin dot (con cientos, el dot tapa la
 * línea); devolvemos r=0 en vez de null porque Recharts espera un elemento SVG.
 */
function DotSolo({ cx, cy, payload, fill, opacity = 1 }) {
  const visible = !!payload?.solo && cx != null && cy != null
  return <circle cx={cx} cy={cy} r={visible ? 3.5 : 0} fill={fill} fillOpacity={opacity} />
}

export default function Insights({ _embeddedTab }) {
  // Estructura única para desktop y mobile. La diferencia se maneja con
  // useIsMobile() abajo: en mobile mostramos la card "Insight del día" como
  // hero al top y ocultamos la curva de drawdown (decisión del producto:
  // demasiado denso para mobile).
  //
  // _embeddedTab: si el componente se embebe dentro de /analisis (page wrapper),
  // este prop define qué subsección renderizar:
  //   • 'diagnostico' → el Diagnóstico (incluye las métricas de riesgo/retorno
  //                     como cards del grid; la ex-pestaña "Métricas" se fusionó)
  //   • 'perfil'      → solo el Perfil del inversor
  //   • undefined     → render completo (modo standalone, ya casi no se usa)
  // El render condicional se hace inline abajo con `shouldRender()`.
  return <InsightsDesktop _embeddedTab={_embeddedTab} />
}

function InsightsDesktop({ _embeddedTab }) {
  const isMobile = useIsMobile()
  const { user } = useAuth()
  const { valuationDollar, currency, costBasis } = useCurrency()
  const plan = usePlanFeatures()
  // Plazos fijos: viven en otra tabla y no entran en `positions`. Los traemos
  // para que la torta de distribución sume el mismo patrimonio que el Dashboard.
  // OJO: va acá arriba y no abajo con el resto de los cálculos — más abajo hay
  // un `if (loading) return` y un hook después de un return condicional cambia
  // la cantidad de hooks entre renders (React tira y salta el error boundary).
  const pfTotals = usePfRollup()
  // "Desde tu última visita" — el hook va ARRIBA (antes del guard de loading);
  // el delta se computa con record(snapshot) más abajo, cuando la data existe.
  const lastVisit = useLastVisit(`diagnostico:${user?.email ?? 'anon'}`)
  // Flags de renderizado condicional cuando se embebe dentro de /analisis.
  // Standalone (sin _embeddedTab) → renderiza TODO.
  // En tab 'diagnostico' → todo menos "Perfil del inversor".
  // En tab 'perfil'      → solo la sección "Perfil del inversor".
  const showDiagnostico = !_embeddedTab || _embeddedTab === 'diagnostico'
  const showPerfil      = !_embeddedTab || _embeddedTab === 'perfil'
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
  // Moneda de visualización: viene del RIEL global (CurrencyContext), no de un
  // toggle local. USD (MEP/CCL) → vista USD / S&P 500; ARS (Pesos) → vista ARS /
  // Inflación. Antes era un useState local con su propio toggle (unificado 2026-07).
  const [chartRange, setChartRange] = useState(12) // months; null = MAX

  // Selector de benchmark del chart — uno por moneda, persisted en localStorage.
  // Keys del SELECTOR (no incluimos benchmarks que dan 0% siempre — ej. "Dólar
  // quieto" rinde 0% por definición → línea plana sin info. Esas opciones
  // siguen apareciendo en las CARDS de comparativa de abajo donde sí aportan
  // el monto absoluto). Si llega un value viejo de localStorage que ya no es
  // válido (e.g. 'dolar_cash'), caemos al default.
  const VALID_USD_BENCH = ['sp500', 'tbill', 'gold']
  const VALID_ARS_BENCH = ['inflation', 'merval', 'plazo_fijo', 'pesos_cash', 'sp500']
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
  // El selector usa nombres de producto; el backend, los de la fuente de datos.
  const BENCH_API_KEY = {
    sp500: 'sp500', tbill: 'shv', gold: 'gld',
    inflation: 'inflation_ar', merval: 'merval', plazo_fijo: 'plazo_fijo',
  }
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
  // ── LA fuente de Performance (FASE 4) ──────────────────────────────────────
  // `/insights/performance` sirve la curva del usuario Y el benchmark recortado
  // al MISMO rango, calculados en Python sobre `twr.serie_medible`. Esta página
  // ya NO arma esos números: había tres motores propios produciendo el mismo
  // acantilado (`insightsModel.js:106`, el `benchSeries` de acá abajo y
  // `evolution.js:234/:317`), y ninguno miraba en qué BASE estaba cada punta.
  // Mientras el cálculo viva en JS sobre la cadena contable, cualquier guard
  // nuevo en Python se queda corto — que es literalmente lo que ya pasó.
  const [perf, setPerf] = useState(null)
  // ⚠️ §7.2 · EN ESTIMADO ESA SERIE **NO ES UN TOTAL**, Y EL ARREGLO ES DE RÓTULO.
  //
  // La cadena contable fuerza `pnl_unrealized = 0` en todos sus meses — verificado
  // en la cuenta demo: Σ realizado = +2.640 y Σ no realizado = 0 en los 12 meses de
  // `monthly_entries`, mientras la cartera arrastra ~54 mil de pérdida NO realizada
  // que la cadena no ve. O sea: en modo estimado la línea rotulada "P/L total" es
  // realizado con otro nombre, y el usuario lee "total" sobre un número al que le
  // falta justamente lo que más pesa.
  //
  // ⚠️ NO se arregla sumando el no-realizado: ese dato NO EXISTE hacia atrás (en
  // producción sólo 84 de 34.032 filas lo tienen, y las 84 son del mes en curso).
  // Reconstruirlo es Fase 3 + Fase 4. Inventarlo sería exactamente el bug que las
  // once rondas anteriores vinieron a matar.
  const _perfContable = perf?.base_del_twr === 'contable'
  // CERTERO (default) vs ESTIMADO. La línea divisoria no es "foto del cron vs
  // reconstrucción" —reconstruir un CEDEAR o una acción es EXACTO— sino
  // "valuado a precio real vs valuado al costo".
  const [modoPerf, setModoPerf] = useState('certero')
  // En pesos el toggle se DIBUJA pero no se puede usar (ver el comentario largo en
  // el control). El motivo viaja en el `title` para que el usuario se entere de que
  // el modo existe y de qué le falta para usarlo.
  // ⚠️ EN PESOS EL TOGGLE YA FUNCIONA. Estuvo apagado mientras la línea en pesos
  // la armaba el frontend sobre la cadena contable de los brokers ARS (sin modo
  // certero posible: `arsMonthly` nunca pasaba por `applyMtmToMonthly` y el
  // re-anclaje necesita snapshots por broker). Ahora la serie sale del mismo
  // motor que en dólares, medida en pesos, así que los dos modos existen. Sólo
  // queda apagado si el motor no devolvió curva para esta cuenta.
  const togglePerfDeshabilitado = currency !== 'USD' && !(perf?.curva || []).length
  // ⚠️ QUIÉN LLEVA LA EXPLICACIÓN DEL CHIP. Hay dos chips "Medido desde": el de la
  // tarjeta de Performance y el del encabezado de la curva de drawdown. La frase va
  // UNA sola vez por pantalla — dos veces sería ruido.
  // El de Performance sólo se dibuja en USD, porque describe la serie de Performance
  // y en pesos esa serie no existe. Eso dejaba a los usuarios de ARS —758 de 854,
  // el 89%— con el chip del drawdown SOLO en pantalla y sin explicar nada: la fecha
  // pelada que hace pensar que se perdió el historial, que es justo lo que la frase
  // vino a evitar.
  // Por eso la condición no es "en qué tarjeta estoy" sino "¿soy el único chip?".
  const chipPerfVisible = currency === 'USD' || (perf?.curva || []).length > 0

  useEffect(() => { loadAll() }, [])

  // El valor de HOY de la cartera, para que la curva cierre en "hoy" y el benchmark
  // termine el MISMO día (`valor_live` en `/insights/performance`). Sin esto la
  // curva terminaba en la foto de anoche y el S&P en el cierre de hoy: un día de
  // desfasaje sistemático en la punta. Va ANTES del `if (loading) return` porque
  // es un hook; se redondea para no refetchear por cada centavo que se mueve.
  const liveUsdPerf = useMemo(() => {
    try {
      const tb = pickFinancialRate(dolar, valuationDollar) || 1415
      const tcr = dolar?.cripto?.venta
      return (brokers || []).reduce((s, b) =>
        s + (computeBrokerValue(positions, prices, b, tb, tb, tcr, costBasis).value || 0), 0)
    } catch { return 0 }
  }, [brokers, positions, prices, dolar, valuationDollar, costBasis])
  // ⚠️ RECIÉN CUANDO TERMINÓ DE CARGAR. Con `positions` ya en memoria y `prices`
  // todavía vacío, la valuación cae al costo y mandaba un `valor_live` de otro
  // orden (medido: 70.983 en una cartera de 16.595) durante un render, con su
  // fetch y su curva mal cerrada hasta la respuesta siguiente.
  const liveKeyPerf = loading ? 0 : Math.round(liveUsdPerf || 0)

  // El benchmark se recorta al rango del usuario EN EL BACKEND, así que cambiar
  // el selector es una consulta nueva — no un re-slice de una serie ya traída.
  useEffect(() => {
    const k = BENCH_API_KEY[selectedBench]
    if (!k) return
    let vivo = true
    const live = liveKeyPerf > 0 ? `&valor_live=${liveKeyPerf}` : ''
    // ⚠️ LA MONEDA VIAJA AL MOTOR. En pesos NO alcanza con dividir la curva de
    // dólares: el retorno en pesos incluye la devaluación, y si el TC se aplica a
    // las dos puntas por igual se cancela y publica el retorno en dólares con
    // otro rótulo. El backend mide cada punta al TC de SU fecha.
    const mon = currency === 'ARS' ? '&moneda=ars' : ''
    api.get(`/insights/performance?bench=${k}&modo=${modoPerf}${live}${mon}`)
      .then(r => { if (vivo) setPerf(r) })
      .catch(() => {})
    return () => { vivo = false }
  }, [selectedBench, modoPerf, liveKeyPerf, currency])

  async function loadAll() {
    try {
      const [mon, pos, bkrs, b, snaps, dol, ops, comm, prof, pf] = await Promise.all([
        api.get('/monthly'),
        api.get('/positions'),
        api.get('/brokers'),
        api.get('/benchmarks').catch(() => null),
        // Historia completa, no 30 días: los snapshots son la serie a valor de
        // MERCADO y ahora corrigen toda la cadena mensual (applyMtmToMonthly),
        // no solo el detalle diario del último mes.
        api.get('/snapshots?days=3650').catch(() => []),
        api.get('/dolar').catch(() => null),
        api.get('/operations').catch(() => []),
        api.get('/insights/commissions').catch(() => null),
        api.get('/auth/investor-profile').catch(() => ({})),
        api.get('/insights/performance').catch(() => null),
      ])
      setMonthly(mon); setPositions(pos); setBrokers(bkrs); setBench(b); setSnapshots(snaps); setDolar(dol); setOperations(ops); setCommissionsApi(comm); setInvestorProfile(prof || {}); setPerf(pf)

      const arsBrokers = new Set(bkrs.filter(x => x.currency === 'ARS').map(x => x.name))
      // Todo lo que no sea ARS (USDT, USD) se valúa directo en USD sin conversión
      const usdtBrokers = new Set(bkrs.filter(x => x.currency !== 'ARS').map(x => x.name))
      const arsSyms = [...new Set(pos.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => priceSymbol(p.asset, true, p.asset_type)))]
      // En un sub-broker AR "· USD" todo es de BYMA (CEDEARs + acciones AR como
      // PAMP/YPFD): se pide el símbolo local .BA. En un broker USD real (Schwab)
      // se pide el ticker US pelado. priceSymbol(asset, true, …) fuerza el .BA.
      const usdtSyms = [...new Set(pos.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT')
        .map(p => isArUsdBroker(p.broker)
          ? priceSymbol(p.asset, true, p.asset_type)
          : priceSymbol(p.asset, false, p.asset_type)))]
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
  const tcBlue = pickFinancialRate(dolar, valuationDollar) || 1415
  const tcCedear = pickFinancialRate(dolar, valuationDollar) || tcBlue  // dólar financiero p/ CEDEARs
  const tcCripto = dolar?.cripto?.venta  // dólar cripto (~5% sobre spot) p/ cripto en broker AR
  // Brokers que son exchange (Binance, Ripio…): la cripto se valúa a spot (factor 1).
  // En un broker AR (Cocos, Balanz…) la cripto se valúa al dólar cripto (MEP-like).
  const exchangeBrokers = new Set((brokers || []).filter(b => b.is_exchange).map(b => b.name))
  const pieData = brokers
    .map(b => ({ name: b.name, value: +computeBrokerValue(positions, prices, b, tcBlue, tcCedear, tcCripto, costBasis).value.toFixed(2) }))
    .filter(x => x.value > 0)
  const totalPortfolio = pieData.reduce((s, x) => s + x.value, 0)

  // Valor USD de UNA tenencia (no-cash), con el MISMO clamp anti-distorsión que
  // computeBrokerValue (trustMktValue): un bono/ON con precio ABSURDO (per-100, o un
  // ticker que no reconocemos) NO se confía → cae a costo. Antes estas valuaciones
  // por-activo (assetPieData / buckets / snapshot IA) NO clampeaban y divergían del
  // total por-broker → un bono podía mostrarse como >100% de la cartera (ej. un dual
  // recién comprado a 689%). Fuente única de verdad = misma lógica que computeBrokerValue.
  const holdingValueUsd = (p) => {
    const broker = brokers.find(b => b.name === p.broker)
    const realCost = (p.invested || 0) + (p.commissions || 0)
    const f = cryptoBrokerFactor(p.asset, exchangeBrokers.has(p.broker), p.price_override != null, tcCripto, tcCedear)
    // Espejo de costInPesos: lote de COSTO EN DÓLARES (bono/ON/FCI-USD, o CEDEAR
    // comprado en dólar-MEP → currency='USD') que vive en un broker ARS (Balanz).
    // El costo YA está en USD; el valor va por el tipo de instrumento (usdLotValue,
    // que ya clampea). Sin esto, la rama ARS de abajo dividía por el blue → colapsaba
    // y esta tenencia dólar desaparecía de la torta/atribución por-activo. Gateado a
    // broker ARS: una acción US genuina (currency='USD' en Schwab/IBKR) NO entra acá
    // (usdLotValue le armaría 'AAPL.BA', inexistente en un broker USD) → va al else.
    if (broker?.currency === 'ARS' && costInUsd(p)) {
      return usdLotValue(p, prices, tcCedear).valueUsd
    }
    if (broker?.currency === 'ARS') {
      const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true)]
      const mktArs = priceArs != null ? priceArs * (p.quantity || 0) : null
      return (mktArs != null && trustMktValue(mktArs, realCost, p.asset_type, p.price_override != null))
        ? mktArs / tcBlue : realCost / tcBlue
    }
    if (costInPesos(p)) {
      // Mismo clamp anti-distorsión que el resto de las ramas: un bono/activo en
      // pesos con precio .BA absurdo (convención per-100 tomada como per-1 → ×100)
      // no se confía → cae a costo (P&L 0). Sin esto, un dual en pesos alojado en
      // un broker USD se inflaba ×100 SOLO acá (el total lo salvaba por otra vía),
      // apareciendo como "689% de la cartera" y una atribución P&L fantasma.
      const { investedUsd, valueUsd } = pesoLotUsd(p, prices, tcCedear)
      return trustMktValue(valueUsd, investedUsd, p.asset_type, p.price_override != null)
        ? valueUsd : investedUsd
    }
    if ((p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && !isFciSym(p.asset) && p.price_override == null && !isCrypto(p.asset)) {
      // El FCI-USD NO entra: su precio es el NAV en USD (va al else, sin ÷MEP).
      const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
      const mktArs = priceArs != null ? priceArs * (p.quantity || 0) : null
      return (mktArs != null && trustMktValue(mktArs, realCost, p.asset_type))
        ? mktArs / tcCedear : realCost
    }
    // Key normalizada primero (la que pide el fetch: 'BRK.B' se pide como
    // 'BRK-B'), con fallback a la cruda para el last-known del cron y los
    // payloads legacy. Leer sólo la cruda dejaba el lote al costo, P&L 0.
    const price = p.price_override ?? prices[priceSymbol(p.asset, false, p.asset_type)] ?? prices[p.asset]
    const mkt = price != null ? price * (p.quantity || 0) : null
    return ((mkt != null && trustMktValue(mkt, realCost, p.asset_type, p.price_override != null)) ? mkt : realCost) * f
  }

  const assetPieData = (() => {
    if (!positions.length || totalPortfolio <= 0) return []
    const arsBrokerNames = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
    const valuesByAsset = {}
    for (const p of positions) {
      if (p.is_cash) continue
      const val = holdingValueUsd(p)   // clamp anti-distorsión incluido (fuente única)
      // Contexto AR/BYMA: colapsamos la especie a su canónico (la pata pesos 'SI' y la
      // dólar 'SID' del CEDEAR de CSN → UN activo). Espeja Calidad de cartera.
      const onBA = arsBrokerNames.has(p.broker) || isArUsdBroker(p.broker) || costInPesos(p)
      const k = onBA ? cedearEspecieBase(p.asset) : (p.asset || '').toUpperCase()
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
  //
  // FIX 2026-05-27: las posiciones cash (USDT en Binance, ARS en Cocos)
  // tienen quantity=0 y el monto real vive en `invested`. Antes leíamos
  // `quantity` directamente y caía a 0, dejando todos los cash fuera del
  // bucket. Eso rompía la card de Liquidez (mostraba 0% en cash+RF cuando
  // el user tenía miles en USDT/ARS). Ahora alineado con el patrón de
  // aiCash (línea ~1203): leer `invested`, convertir si el broker es ARS.
  const positionsWithValue = (() => {
    return positions.map(p => {
      if (p.is_cash) {
        // Cash: el monto real está en `invested` (la quantity suele ser 0
        // porque el cash se modeló como un saldo, no como N unidades).
        const broker = brokers.find(b => b.name === p.broker)
        const amount = p.invested || 0
        const val = broker?.currency === 'ARS' ? amount / tcBlue : amount
        return { ...p, value_usd: val }
      }
      const val = holdingValueUsd(p)   // clamp anti-distorsión incluido (fuente única)
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
  // Cards nuevas (2026-05-27): cruce de las dimensiones del test que antes no
  // se cruzaban con la realidad. `styleCard` necesita operations (más abajo),
  // `liquidityCard` ya tiene todo lo que necesita.
  const liquidityCard = computeLiquidityRisk(investorProfile, positionsWithValue, brokers)

  // Cost basis y P&L no realizado (live, sobre posiciones abiertas).
  const totalCostBasis = brokers.reduce((s, b) => {
    return s + computeBrokerValue(positions, prices, b, tcBlue, tcCedear, tcCripto, costBasis).invested
  }, 0)
  const unrealizedPnl = totalPortfolio - totalCostBasis

  // ── Cumulative performance series (monthly + today) ──
  // ÚNICO punto de entrada de la cadena mensual: todo lo de abajo (las 4 series,
  // Sharpe/CAGR/vol/Sortino, drawdown, mejor/peor mes, los shadows de benchmark)
  // se deriva de acá. Por eso la corrección a valor de mercado se aplica UNA vez,
  // en el origen, en vez de parchear cada consumidor.
  const globalMonthly = applyMtmToMonthly(
    [...monthly.filter(m => m.broker === 'global')].sort((a, b) =>
      a.year !== b.year ? a.year - b.year : a.month - b.month
    ),
    snapshots,
    undefined,
    // El cierre del mes EN CURSO tiene que ser el valor de mercado, NO el
    // capital_final de la contabilidad: ese incluye la ganancia ya retirada.
    // Misma base que snapshot.total_value (posiciones + cash).
    totalPortfolio,
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
    let fxPrevChart = fxBase   // el fx del mes anterior — sin esto el fx se cancela
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
      // SIN TECHO. El `Math.min(..., 0.5)` que estaba acá limitaba las subidas de la
      // CARTERA a +50% por mes y NO le aplicaba nada al BENCHMARK: el sesgo iba
      // sistematicamente en contra del usuario y se componia mes a mes. Un +80% en
      // cripto o post-devaluacion es perfectamente posible. El piso de -99% si
      // queda: no se puede perder mas que todo. Mismo criterio que `twr.dietz`
      // (backend/twr.py:215), cuyo docstring explica por que.
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

      // ARS: mismo TWR pero con el capital inicial al fx del mes ANTERIOR. Si los
      // tres términos van al fx del MISMO mes, el fx se cancela en el cociente y
      // esta línea "en pesos" es la línea en dólares. Ver monthlyReturnArs().
      if (fxBase && bench?.dolar_blue) {
        const fx = lookupDolar(monthKey(m.year, m.month)) || fxBase
        const rArs = monthlyReturnArs({ ci, cf, net, fxPrev: fxPrevChart, fx, isImportInitial }) ?? 0
        fxPrevChart = fx
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

      // ARS "Hoy" — el cierre del último mes vale a SU fx, el valor de hoy al de
      // hoy. Los dos al mismo tcBlue (como estaba) hacía que el tramo final
      // tampoco viera la devaluación.
      // Los dos lados salen del mapa `dolar_blue`, NO de tcBlue: tcBlue es el MEP
      // (pickFinancialRate), y como lo que mueve el retorno es el cociente
      // fx_hoy/fx_últimoMes, mezclar rieles metería un salto espurio del tamaño
      // del cambio de la brecha blue-MEP.
      const fxHoyChart = dolarKeys.length ? bench.dolar_blue[dolarKeys[dolarKeys.length - 1]] : null
      if (fxBase && fxHoyChart) {
        const lastCfArs = lastCf * fxPrevChart
        const valueArsLive = totalPortfolio * fxHoyChart
        if (lastCfArs > 0) {
          const rLiveArs = (valueArsLive - lastCfArs) / lastCfArs
          const rLiveArsClamped = Math.max(rLiveArs, -0.99)
          cumIdxArs *= (1 + rLiveArsClamped)
        }
        const totalArsLive = +((cumIdxArs - 1) * 100).toFixed(2)
        // Mismo riel que el numerador (cumRealizedArs se acumuló al blue de cada mes).
        const denomArsLive = safeDenom(cumNetDeposits, peakNetDeposits) * fxHoyChart
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

  // Entradas mensuales de los brokers ARS, agregadas por mes (suma si hay varios)
  // en la MISMA forma que globalMonthly (valores en USD). Fuente ÚNICA que
  // comparten la línea del portfolio ARS (benchSeriesArs) y los shadows de
  // benchmark en pesos — así ambos corren sobre EXACTAMENTE los mismos flujos.
  const arsMonthly = (() => {
    if (arsBrokerNames.size === 0) return []
    const byMk = {}
    for (const m of monthly) {
      if (!arsBrokerNames.has(m.broker)) continue
      const k = monthKey(m.year, m.month)
      if (!byMk[k]) byMk[k] = { year: m.year, month: m.month, capital_inicio: 0, capital_final: 0, deposits: 0, withdrawals: 0, pnl_realized: 0 }
      byMk[k].capital_inicio += m.capital_inicio || 0
      byMk[k].capital_final  += m.capital_final || 0
      byMk[k].deposits       += m.deposits || 0
      byMk[k].withdrawals    += m.withdrawals || 0
      byMk[k].pnl_realized   += m.pnl_realized || 0
    }
    return Object.values(byMk).sort((a, b) => (a.year - b.year) || (a.month - b.month))
  })()

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

  // benchSeriesUsd — LA LÍNEA DEL PORTFOLIO EN USD, ahora servida por el backend.
  //
  // Acá vivía el segundo de los tres motores que fabricaban el acantilado: armaba
  // el índice con Modified Dietz sobre `capital_inicio`/`capital_final` de
  // `monthly_entries` —la cadena CONTABLE— y lo cerraba con `totalPortfolio`, que
  // es valor de MERCADO. Las dos puntas en bases distintas: la caída vertical del
  // final no era del mercado, era la brecha entre dos formas de medir. Encima
  // truncaba las subidas a +50% mensual sin aplicarle nada al benchmark.
  //
  // Ahora los puntos salen de `twr.curva_indexada`, que sólo encadena bordes que
  // están en base de mercado (medidos por el cron o reconstruidos a precio real
  // con cobertura suficiente) y no deja que un punto no medido fije un pico.
  //
  // El efecto lateral que importa: como la serie ahora arranca en la primera
  // MEDICIÓN, la ventana del chart arranca ahí, y el rebase de `chartData`
  // ancla el benchmark en ese mismo punto. La cartera y el S&P pasan a arrancar
  // en la misma fecha sin tocar el pipeline del gráfico.
  //
  // `realized` sigue siendo contable a propósito: "cuánto de lo ganado ya está
  // realizado" ES una pregunta contable. Se mapea por mes sobre las fechas de la
  // curva medida, sin mezclarse nunca con el índice.
  const benchSeriesUsd = (() => {
    const curva = perf?.curva || []
    if (curva.length === 0) return []

    let cum = 0
    const realizedByMonth = new Map()
    let cumNet = 0, peakNet = globalMonthly[0]?.capital_inicio || 0
    const netByMonth = new Map()
    for (const m of globalMonthly) {
      cum += (m.pnl_realized || 0)
      cumNet += (m.deposits || 0) - (m.withdrawals || 0)
      if (cumNet > peakNet) peakNet = cumNet
      const k = monthKey(m.year, m.month).slice(0, 7)
      realizedByMonth.set(k, cum)
      netByMonth.set(k, { net: cumNet, peak: peakNet })
    }
    const mesesOrd = [...realizedByMonth.keys()].sort()
    const alMes = (map, mk) => {
      if (map.has(mk)) return map.get(mk)
      let found = null
      for (const k of mesesOrd) { if (k <= mk) found = k; else break }
      return found ? map.get(found) : null
    }
    const safeDenom = (netDep, peakDep) =>
      netDep >= peakDep * 0.6 && netDep > 1000 ? netDep : peakDep

    // Cada punto viaja con SU TRAMO. El corte de la línea NO se inserta acá: si se
    // mete un punto sintético antes del resampleo mensual, su clave ('corte-…')
    // cae en el bucket 'corte-2' de `s.key.slice(0,7)` y después ordena AL FINAL
    // (porque 'c' > '2' comparando strings), con lo cual los dos tramos terminan
    // dibujados pegados — exactamente lo que el corte venía a impedir. Se inserta
    // después de resamplear, sobre `windowSeries`.
    // `perf.benchmark` trae UN punto por cada punto de `curva`, en el mismo orden,
    // indexado a 1,0 en la primera fecha de la curva y resuelto POR FECHA (el
    // cierre de ese día). Se alinea por posición, no por mes: es lo que hace que
    // la línea del S&P deje de ser una escalera mensual sobre una curva diaria.
    const benchPts = perf?.benchmark || []
    const out = []
    curva.forEach((pt, i) => {
      const esHoy = pt.date === 'hoy'
      const mk = esHoy ? (mesesOrd[mesesOrd.length - 1] || '') : pt.date.slice(0, 7)
      const bp = benchPts[i]
      const benchIdx = (bp && bp.date === pt.date && typeof bp.index === 'number') ? bp.index : null
      const nd = alMes(netByMonth, mk)
      const rz = alMes(realizedByMonth, mk) || 0
      const denom = nd ? safeDenom(nd.net, nd.peak) : 0
      out.push({
        key: esHoy ? 'today' : pt.date,
        label: esHoy ? 'Hoy' : benchLabel(pt.date.slice(0, 7)),
        // ⚠️ Con la serie ya diaria, una etiqueta mes/año repite: el eje mostraba
        // «Jul '26 · Jul '26 · Jul '26 · … · Ago '26 · Ago '26», nueve repetidas de
        // once. Ningún número está mal, pero es lo primero que se ve.
        labelDia: esHoy ? 'Hoy' : `${pt.date.slice(8, 10)}/${pt.date.slice(5, 7)}`,
        // Todos los puntos se dibujan; los no medidos, punteados. Ver
        // `totalDePunto` y `partirMedidoYEstimado` (insightsModel.js).
        total: totalDePunto(pt),
        estimado: !!pt.estimado,
        realized: denom > 0 ? +((rz / denom) * 100).toFixed(2) : 0,
        // El benchmark de ESTA fecha (índice 1,0 = primera fecha de la curva), o
        // null si el índice no tiene cierre todavía para esa fecha.
        bench: benchIdx,
        // ¿Puede ser punta de un número? Y el índice PUBLICADO (apto→apto), que es
        // lo que el KPI rebasea: `total` es la FORMA (encadena la intradía).
        apto: !!pt.apto,
        ip: (typeof pt.index_publicado === 'number') ? pt.index_publicado : null,
        tramo: pt.tramo,
        // El SEGMENTO DIBUJADO: más fino que el tramo, porque también se parte
        // donde cambia la base de valuación. Es por acá que se corta la línea.
        segmento: pt.segmento,
        // Con qué REGLA está valuado el punto. Viaja para que `resolucionChart`
        // pueda distinguir la parte que también existe en certero (mercado) de la
        // que sólo aparece en estimado (la cadena contable). Ver el comentario de
        // `resolucionChart` más abajo.
        base: pt.base,
      })
    })
    return out
  })()

  // benchSeriesArs — solo brokers ARS, capital en pesos (USD × blue del mes) en % acumulado MWR.
  // Además expone, vía closures de scope externo:
  //   • portfolioReturnArsPctRaw — el retorno acumulado en pesos del último punto
  //     SIN el clamp [-99, +200] que aplica el chart. El diagnóstico beat/lose_inflation
  //     compara contra inflación SIN clampear, así que debe usar este crudo.
  //   • arsWindowFirstKey / arsWindowLastKey — rango [firstKey..lastKey] real de la
  //     serie ARS, para deflactar por la inflación de EXACTAMENTE ese rango.
  let portfolioReturnArsPctRaw = null
  let arsWindowFirstKey = null
  let arsWindowLastKey = null
  const benchSeriesArs = (() => {
    if (arsBrokerNames.size === 0 || !bench?.dolar_blue) return []
    // Flujos mensuales de los brokers ARS (fuente compartida con los shadows).
    if (arsMonthly.length === 0) return []

    const firstKey = monthKey(arsMonthly[0].year, arsMonthly[0].month)
    const blueBase = lookupBlue(firstKey)
    if (!blueBase) return []
    // Rango real de la serie ARS — se usa para recortar la inflación al mismo período.
    arsWindowFirstKey = firstKey
    arsWindowLastKey = monthKey(arsMonthly[arsMonthly.length - 1].year, arsMonthly[arsMonthly.length - 1].month)

    const out = []
    const baselinePesos = arsMonthly[0].capital_inicio * blueBase
    let netFlowsPesos = 0, cumRealizedPesos = 0
    let cumIdxArs = 1.0
    // Mismo treatment de peak-stable denom que benchSeriesUsd (ver arriba) — solo
    // para el realized% (la línea total ahora es TWR, no necesita denom).
    let peakInvestedPesos = baselinePesos > 0 ? baselinePesos : 0
    const stableInvestedPesos = (cur, peak) =>
      (cur >= peak * 0.6 && cur > 1000) ? cur : peak
    out.push({ key: firstKey, label: benchLabel(firstKey), total: 0, realized: 0 })

    let idxArs = 0
    // El FX del mes ANTERIOR: sin esto el retorno "en pesos" era el retorno en
    // dólares (el fx se cancelaba arriba y abajo). Ver monthlyReturnArs().
    let fxPrevArs = blueBase
    for (const m of arsMonthly) {
      const isFirst = idxArs === 0
      idxArs++
      const k = monthKey(m.year, m.month)
      const fx = lookupBlue(k) || blueBase
      const net = (m.deposits || 0) - (m.withdrawals || 0)
      const ci = m.capital_inicio || 0
      const cf = m.capital_final || 0
      // TWR en pesos: el capital inicial vale al FX del mes anterior y los flujos
      // a mitad de período, así el salto de devaluación entra como retorno.
      const isImportInitial = isFirst && ci === 0 && net > 0
      const rArs = monthlyReturnArs({ ci, cf, net, fxPrev: fxPrevArs, fx, isImportInitial }) ?? 0
      const netArs = net * Math.sqrt(fxPrevArs * fx)
      fxPrevArs = fx
      // El mes-1 es el ancla (0%) — no se cuenta su retorno intra-mes (ver benchSeriesUsd).
      if (!isFirst) cumIdxArs *= (1 + rArs)
      // Realized% (MWR sobre denom estable — secundario, línea punteada)
      netFlowsPesos += netArs
      cumRealizedPesos += (m.pnl_realized || 0) * fx
      const investedNowPesos = baselinePesos + netFlowsPesos
      if (investedNowPesos > peakInvestedPesos) peakInvestedPesos = investedNowPesos
      const denomP = stableInvestedPesos(investedNowPesos, peakInvestedPesos)
      const total = +((cumIdxArs - 1) * 100).toFixed(2)
      const real  = denomP > 0 ? (cumRealizedPesos / denomP) * 100 : 0
      portfolioReturnArsPctRaw = total  // TWR acumulado — para el diagnóstico de inflación
      out.push({ key: k, label: benchLabel(k), total, realized: +real.toFixed(2) })
    }
    // Punto "Hoy" — valor live de posiciones ARS al blue actual (extiende el TWR)
    const arsLiveUsd = brokers
      .filter(b => arsBrokerNames.has(b.name))
      .reduce((s, b) => s + computeBrokerValue(positions, prices, b, tcBlue, tcCedear, tcCripto, costBasis).value, 0)
    // ⚠️ EL TRAMO FINAL COMPARABA MERCADO CONTRA CONTABILIDAD. `valueNowArs`
    // sale de `computeBrokerValue` (posiciones × precio: MERCADO) y `lastCfArs`
    // de `lastM.capital_final`, que en la rama ARS es la CADENA CONTABLE pelada:
    // `arsMonthly` se arma leyendo `monthly` crudo y NUNCA pasa por
    // `applyMtmToMonthly`, que es el único lugar del frontend que re-ancla la
    // cadena a los snapshots. O sea: la línea USD se arregló y la ARS quedó al
    // costo, y este último tramo publicaba la brecha entre las dos reglas como
    // si fuera el rendimiento de los últimos días. Va derecho al veredicto
    // "¿le ganaste a la inflación?" (`portfolioReturnArsPct`, :2224).
    //
    // El marcador es el que `applyMtmToMonthly` ya estampa: `mtm: 'ambos'` o
    // `'inicio'` en las filas que sí re-ancló. Sin él, el cierre del último mes
    // no está medido y no se puede extender la serie sin mezclar. La condición
    // se escribe por el HECHO y no por "la rama ARS nunca se ancla", así que el
    // día que existan snapshots por broker esto se prende solo.
    //
    // No se puede arreglar aplicando `applyMtmToMonthly` acá: esa función
    // re-ancla contra los snapshots GLOBALES y `arsMonthly` es un SUBCONJUNTO
    // (sólo brokers ARS). Los snapshots no se desagregan por broker.
    const _lastArs = arsMonthly[arsMonthly.length - 1]
    const _cierreArsMedido = !!(_lastArs && _lastArs.mtm)
    if (arsLiveUsd > 0 && _cierreArsMedido) {
      const lastM = _lastArs
      // El punto "Hoy" tenía el MISMO bug que el loop: los dos lados al mismo
      // tcBlue ⇒ el FX se cancelaba y el tramo final tampoco veía la devaluación.
      // El cierre del último mes vale a SU FX; el valor de hoy, al de hoy.
      // Los dos salen del riel `dolar_blue` a propósito: lo que mueve el retorno
      // es el cociente fx_hoy/fx_últimoMes, y mezclar rieles (tcBlue es MEP)
      // metería un salto espurio del tamaño de la brecha.
      const fxHoy = blueKeys.length ? bench.dolar_blue[blueKeys[blueKeys.length - 1]] : null
      const lastCfArs = (lastM.capital_final || 0) * fxPrevArs
      const valueNowArs = arsLiveUsd * (fxHoy || fxPrevArs)
      if (lastCfArs > 0) {
        const rLiveArs = (valueNowArs - lastCfArs) / lastCfArs
        cumIdxArs *= (1 + Math.max(rLiveArs, -0.99))
      }
      const total = +((cumIdxArs - 1) * 100).toFixed(2)
      const investedNowPesos = baselinePesos + netFlowsPesos
      const denomP = stableInvestedPesos(investedNowPesos, peakInvestedPesos)
      const real  = denomP > 0 ? (cumRealizedPesos / denomP) * 100 : 0
      // El punto "Hoy" es el último de la serie → su TWR es el retorno final.
      portfolioReturnArsPctRaw = total
      arsWindowLastKey = 'today'
      out.push({ key: 'today', label: 'Hoy', total, realized: +real.toFixed(2) })
    }
    // Deduplicar
    const seen = new Set()
    return out.filter(p => { if (seen.has(p.key)) return false; seen.add(p.key); return true })
  })()

  // ── FASE 5 · UI de la calidad del dato ─────────────────────────────────────
  // Chip permanente sobre el gráfico. No es una advertencia de error: es el
  // encabezado honesto de qué período está efectivamente medido. El usuario del
  // caso 452 dedujo solo que el arranque era falso ("yo nunca llegué tan
  // arriba"); esto se lo dice antes de que tenga que deducirlo.
  const fmtFecha = (iso) => {
    if (!iso) return ''
    const [y, m, d] = String(iso).split('-')
    return `${d}/${m}/${y}`
  }
  // `explica` agrega, al lado del chip, la frase que evita la conclusión equivocada
  // ("perdí mi historial"). Va sólo en la tarjeta de Performance: en el encabezado
  // de la curva de drawdown la misma frase, en la misma pantalla, sería ruido.
  const ChipMedido = ({ explica = false }) => {
    if (!perf) return null
    const cob = perf.cobertura_reconstruccion
    const partida = !!perf.serie_partida
    const alCosto = perf.instrumentos_al_costo || []

    // ── FASE 2 · el chip del modo ESTIMADO ───────────────────────────────────
    // El modo estimado publica un número que el certero no puede dar, y a cambio
    // tiene un sesgo que hay que declarar EN PANTALLA, no en un tooltip escondido:
    // la cadena contable fuerza `pnl_unrealized = 0`, así que NO cuenta lo que
    // todavía no vendiste. Una cartera que se duplicó sin vender nada sale ~0%.
    // El sesgo va SIEMPRE para el mismo lado (en contra del usuario), y por eso la
    // frase tiene que estar junto al número y no en la letra chica: el usuario está
    // por comparar esto contra el S&P.
    // ⚠️ SÓLO SI HAY NÚMERO. `base_del_twr` dice con qué regla se calculó, y vale
    // 'contable' en modo estimado AUNQUE no haya nada que publicar (152 de los 822
    // no tienen una sola fila de snapshot). Sin este chequeo, esos usuarios leerían
    // "Recreado de tu contabilidad" sobre un gráfico vacío: un cartel que describe
    // un número que no existe. Ésos caen al estado vacío de abajo, que es el suyo.
    if (perf.base_del_twr === 'contable' && perf.twr != null) {
      return (
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/30 whitespace-nowrap">
            {/* Con mediciones reales la línea tiene DOS partes y el chip lo dice: la
                contable (punteada) hasta la primera foto del cron, la medida
                (llena) desde ahí. "Sólo se mueve cuando vendés" describe la
                primera; decirlo sobre una línea que sigue con mediciones diarias
                era falso para la mitad del gráfico. */}
            Recreado de tu contabilidad
            {perf.ventana_desde ? ` · desde ${fmtFecha(perf.ventana_desde)}` : ''}
            {perf.medido_desde
              ? ` · medido a mercado desde ${fmtFecha(perf.medido_desde)}`
              : (perf.excluye_no_realizado ? ' · sólo se mueve cuando vendés' : '')}
          </span>
          <InfoTooltip>
            <p className="font-semibold text-ink-0">Qué estás viendo</p>
            <p>La historia completa reconstruida de tu contabilidad: aportes, retiros
               y lo que ya vendiste. Llega más atrás que la medición a precio real,
               y a cambio es aproximada.</p>
            <div className="border-t border-line/60 my-1.5" />
            <p className="font-semibold text-ink-0">Por qué esta línea puede no parecerse a la del modo Certero</p>
            <p className="text-ink-3">La parte <strong>punteada</strong> es la contabilidad y
               <strong> sólo se mueve cuando vendés</strong>: no refleja lo que pasa con lo
               que todavía tenés. Si tus posiciones abiertas suben o caen, esa parte
               no se entera — se queda quieta hasta que realizás. Por eso puede
               mostrar una recta donde el modo Certero muestra un pozo. Desde la
               primera medición a mercado, la línea sigue <strong>llena</strong> con
               las mismas mediciones del Certero, encadenadas a lo anterior.</p>
            <p className="text-ink-3">Ojo: <strong>sí baja</strong> cuando vendés con pérdida.
               No es una línea que sólo sube.</p>
            <div className="border-t border-line/60 my-1.5" />
            <p className="font-semibold text-ink-0">Por qué acá no hay drawdown ni pico</p>
            <p className="text-ink-3">Una caída desde el máximo necesita el CAMINO de
               los precios, y la contabilidad es un saldo mensual, no un recorrido.
               Su máximo nunca fue un precio: nadie te pagó eso. Para eso está el
               modo <strong>Certero</strong>.</p>
          </InfoTooltip>
        </div>
      )
    }
    // ⚠️ SIN `medido_desde` el chip TAMBIÉN se muestra. Antes devolvía null, así
    // que el cartel que explicaría por qué no hay curva desaparecía junto con la
    // curva: quedaba un gráfico en blanco y un toggle sin ninguna pista de que
    // ahí está la respuesta.
    if (!perf.medido_desde) {
      return (
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] px-2 py-0.5 rounded-full bg-bg-2 text-ink-2 border border-line">
            Sin mediciones todavía
          </span>
          <InfoTooltip>
            <p className="font-semibold text-ink-0">Por qué no hay curva</p>
            <p>{perf.motivo_texto || 'Todavía no hay mediciones a mercado de esta cuenta.'}</p>
            {/* ⚠️ NO ACONSEJAR UN MODO QUE NO SE PUEDE USAR. `modoPerf === 'certero'`
                solo era SIEMPRE VERDADERO en pesos: ahí el modo es certero de fábrica
                y el toggle está deshabilitado, así que el usuario leía "Probá el modo
                Estimado" con el botón Estimado en gris y `cursor-not-allowed` a diez
                píxeles. Son 184 usuarios —los que tienen broker en pesos Y ninguna
                fila apta—, uno de cada cinco.
                Lo destapó la ronda anterior: antes el toggle en pesos no se dibujaba,
                así que el consejo apuntaba a un control invisible. Hacerlo visible
                volvió visible la contradicción. Lo que sobra es el consejo, no el
                gate: en ARS el estimado no se puede construir hoy. */}
            {modoPerf === 'certero' && !togglePerfDeshabilitado && (
              <p className="text-ink-3">Probá el modo <strong>Estimado</strong>: incluye
                 tu historia contable, que es aproximada pero te deja ver la forma.</p>
            )}
            {/* Y el de pesos no se queda con el cartel mudo: sin esto le quedaba
                "Sin mediciones todavía", el motivo, y ninguna salida. */}
            {togglePerfDeshabilitado && (
              <p className="text-ink-3">El modo <strong>Estimado</strong> —la alternativa
                 cuando todavía no hay mediciones— por ahora sólo funciona en dólares.
                 Podés cambiar la moneda desde <strong>Configuración</strong>.</p>
            )}
          </InfoTooltip>
        </div>
      )
    }
    return (
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[11px] px-2 py-0.5 rounded-full bg-bg-2 text-ink-2 border border-line whitespace-nowrap">
          Medido desde {fmtFecha(perf.medido_desde)}
          {/* La cobertura, VISIBLE — no escondida en el tooltip. Era el punto:
              mostrar la curva y declarar qué parte es estimada. */}
          {cob != null && cob < 0.999 && ` · ${(cob * 100).toFixed(0)}% a precio real`}
          {partida && ' · con un hueco'}
        </span>
        {/* ⚠️ LA FECHA SOLA NO ALCANZA. "Medido desde 29/06/2026" es cierto y deja al
            usuario concluyendo que perdió su historia — le pasó al dueño, que escribió
            el producto. Y no es su cuenta: NINGUNO de los 649 usuarios con historial
            tiene más de tres meses medidos, porque el cron recién empezó a estampar
            los campos que el clasificador necesita. La feature no está mal hecha,
            nació hace poco.
            ⚠️ NO VA NINGUNA FECHA NI PLAZO ACÁ. La única fecha que se muestra es
            `perf.medido_desde`, que es de este usuario; escribir "desde mayo" sería
            pasarle la fecha de OTRO, y "dos años" salió de una expectativa, no de una
            medición. La frase explica el MECANISMO, que es verdad para siempre y no
            envejece. */}
        {explica && (
          <span className="text-[11px] text-ink-3 leading-snug">
            No perdiste historial — antes de esa fecha no hay precios guardados con qué
            medir, y la ventana crece todos los días.
          </span>
        )}
        <InfoTooltip>
          <p className="font-semibold text-ink-0">Desde cuándo esto es una medición</p>
          <p>Antes de esa fecha no hay fotos de mercado de tu cartera: lo que existe
             es la reconstrucción contable (aportes + lo ya vendido), que no baja
             cuando baja el mercado y por eso da más alto que el valor real.</p>
          <p>Se dibuja aparte, en gris, y nunca cuenta como un máximo.</p>
          <p className="text-ink-3">Que esta ventana sea corta no significa que falte
             nada tuyo: tus operaciones y tus aportes están todos. Lo que empieza en
             esa fecha es el registro de PRECIOS con el que se puede medir, y suma un
             día por día.</p>
          {cob != null && (
            <>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Cuánto está valuado a precio real</p>
              <p className="text-ink-3">
                {(cob * 100).toFixed(0)}% de tu cartera valuada a precio real
                {alCosto.length > 0
                  ? ` · el resto (${alCosto.slice(0, 4).join(', ')}${alCosto.length > 4 ? '…' : ''}) va al costo`
                  : ''}.
              </p>
              <p className="text-ink-3">Los bonos y los FCI no tienen serie histórica
                 confiable, así que se valúan al costo. Los CEDEARs y las acciones sí:
                 para ésos la reconstrucción es exacta, no una estimación.</p>
            </>
          )}
          {partida && (
            <>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Hay un hueco en el medio</p>
              <p className="text-ink-3">Cada tramo se mide solo y la línea se corta
                 donde falta la medición. No se encadenan: no se sabe qué pasó en el
                 medio, y suponerlo sería inventarlo. Por eso el acumulado y el
                 drawdown de punta a punta aparecen como "—".</p>
            </>
          )}
        </InfoTooltip>
      </div>
    )
  }
  // Estado vacío explicado. El copy vive en el backend (`twr.MOTIVO_TEXTO`) para
  // que el asesor y el usuario final lean exactamente lo mismo.
  const SinMediciones = () => (
    <div className="text-center py-10 text-ink-3 text-sm">
      <Activity size={20} className="mx-auto mb-2 opacity-50" />
      <p className="max-w-md mx-auto">{perf?.motivo_texto ||
        'Todavía no hay mediciones a mercado de esta cuenta.'}</p>
      <p className="mt-1 text-xs text-ink-3/80">
        En cuanto haya dos fotos de mercado, la curva aparece sola.
      </p>
    </div>
  )

  // ── La banda gris: la RECONSTRUCCIÓN CONTABLE ─────────────────────────────
  // El usuario importó esta historia y tiene derecho a verla — pero va en su
  // propio panel, con su propio eje y en dólares crudos, NUNCA como continuación
  // de la línea medida ni dentro del índice. Es la parte que no baja cuando baja
  // el mercado: si se la deja tocar el índice, vuelve a poner un pico que nadie
  // alcanzó, que es exactamente lo que el usuario del caso reportó.
  // ⚠️ `value_no_medible`, no `value`. El backend renombró la clave a propósito
  // (ronda 11): la banda es la colección de lo que NO mide, y mientras el número
  // crudo se llamara `value` el error seguía siendo escribible justo ahí —
  // `contable[-1].value / medibles[-1].value - 1` daba el −47,26% del caso 452 sin
  // un solo error. Se deja el fallback a `value` para no romper con un backend viejo.
  const contableSeries = (perf?.contable || []).map(p => ({
    key: p.date,
    label: `${MES_CORTO[+p.date.slice(5, 7) - 1] || ''} '${p.date.slice(2, 4)}`,
    usd: +Number(p.value_no_medible ?? p.value ?? 0).toFixed(2),
  }))

  // Selector de serie del portfolio y label del benchmark.
  // ⚠️ EN PESOS LA SERIE ES LA MISMA QUE EN DÓLARES, MEDIDA EN PESOS. `benchSeriesUsd`
  // se arma sobre `perf.curva`, y `perf` ya viene en la moneda de la vista (el
  // fetch manda `moneda=ars`), así que sirve para las dos. `benchSeriesArs` —el
  // motor viejo, sólo brokers ARS sobre la cadena contable— queda de RESPALDO para
  // las cuentas a las que el motor no les puede dar curva: son 196 de los 758
  // usuarios con broker en pesos, y perderla sería cambiarles un gráfico por nada.
  // Medido en producción: con la serie del motor, 445 usuarios ganan el modo
  // certero en pesos, que hoy no existe para nadie.
  const usaPerfEnPesos = currency !== 'USD' && benchSeriesUsd.length > 0
  const activeSeries = currency === 'USD' || usaPerfEnPesos ? benchSeriesUsd : benchSeriesArs

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
    { key: 'sp500',      label: 'S&P 500',         available: hasData(bench?.sp500) },
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
  // La resolución la decide lo MEDIDO, no el botón de rango: ver
  // `resolucionDeSerie` (insightsModel.js). Con 45 días de datos, agrupar por mes
  // tira el 95% de la información y convierte el gráfico en una recta.
  // ⚠️ EL SPAN SE MIDE SOBRE LA PARTE MEDIDA, NO SOBRE LA SERIE ENTERA.
  //
  // EL INVARIANTE: el estimado tiene que ser un SUPERCONJUNTO del certero. Si un
  // dato está en el certero tiene que estar en el estimado, porque el estimado es
  // lo que se sabe MÁS lo que se puede estimar. No puede faltarle nada.
  //
  // Se rompía acá, y es el patrón de las once rondas otra vez: la decisión de la
  // línea de abajo ("la resolución la decide lo MEDIDO, no el botón de rango") era
  // CORRECTA mientras la serie FUERA la parte medida. La Fase 2 le agregó la
  // cadena contable por delante y estiró el span de 45 días a 329 — y
  // `resolucionDeSerie`, que mira el span completo, dependía de esa propiedad.
  // El arreglo cambió una propiedad de la que dependía otro consumidor.
  //
  // Medido en la cuenta demo (45 medidos + 11 contables), antes → después:
  //     1M   estimado    1 pt (mensual) → 29 pts (diaria)   faltaban 27 del certero
  //     3M   estimado    3 pts          → 48 pts            faltaban 44
  //     1A   estimado   12 pts          → 56 pts            faltaban 44
  //     MAX  estimado   12 pts          → 56 pts            faltaban 44
  // El pozo del 07/08 (−8,3%) existía en certero y en estimado no.
  //
  // ⚠️ EL FILTRO ES POR `base`, NO POR `apto`. Lo que hay que excluir del span es
  // "lo que SÓLO existe en estimado" = la cadena contable. Con `apto` se caerían
  // también las fotos INTRADIA, que en certero SÍ están: eso movería el span del
  // certero y rompería la propiedad que este archivo tiene que preservar intacta.
  // Como en certero no hay ni un punto `base='costo'`, este filtro es un no-op ahí
  // — el modo certero queda idéntico POR CONSTRUCCIÓN, no por suerte.
  //
  // La serie queda MIXTA a propósito: la parte contable es mensual porque no
  // existe nada más fino (son cierres de mes) y la medida es diaria. Forzar una
  // sola resolución sobre las dos tira información real de un lado sin poder
  // inventarla del otro.
  //
  // ⚠️ Y SI NO HAY NADA MEDIDO, NO FILTRES. Sacar la cadena contable de una serie
  // que es 100% contable deja la lista VACÍA, y una lista vacía también resuelve
  // 'diaria' — pero por ausencia de datos, no porque haya días. Ese camino cambia
  // el recorte de los rangos (de "los últimos N puntos mensuales" a "los últimos
  // N meses por fecha") en 177 usuarios de producción que no tienen ni un punto
  // medido: 243 combinaciones usuario×rango perdían puntos, hasta 18 en el peor
  // caso. Esos usuarios no tienen certero, así que el invariante ni los toca:
  // era radio de explosión gratis. Con la guarda, sólo cambian las series MIXTAS
  // — que son exactamente las que tenían el bug.
  const clavesMedidas = activeSeries
    .filter(s => s.key !== 'today' && s.base !== 'costo')
    .map(s => s.key)
  const resolucionChart = resolucionDeSerie(
    clavesMedidas.length
      ? clavesMedidas
      : activeSeries.filter(s => s.key !== 'today').map(s => s.key))

  // El texto de una marca del eje X. Antes lo ponía el eje de categoría tomando
  // `labelDia`/`label` de la fila; con el eje en tiempo las marcas ya no caen
  // necesariamente sobre una fila, así que el texto se arma del instante. Mismos
  // dos formatos de siempre: día/mes cuando se dibuja por día, mes/año cuando no.
  const fmtMarcaEje = (t) => {
    const d = new Date(t)
    if (Number.isNaN(d.getTime())) return ''
    if (resolucionChart === 'diaria') {
      return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`
    }
    const MON = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    return `${MON[d.getMonth()]} '${String(d.getFullYear()).slice(2)}`
  }

  const activeSeriesMonthly = (() => {
    const historical = activeSeries.filter(s => s.key !== 'today')
    const today = activeSeries.find(s => s.key === 'today')
    if (resolucionChart === 'diaria') {
      return today ? [...historical, today] : historical
    }
    // Agrupar por mes (YYYY-MM) y quedarse con el último punto de cada mes.
    const byMonth = {}
    for (const s of historical) {
      const mk = s.key.slice(0, 7)
      byMonth[mk] = s  // overwrite → se queda con el último del mes
    }
    const sortedMonthly = Object.values(byMonth).sort((a, b) => a.key < b.key ? -1 : 1)
    return today ? [...sortedMonthly, today] : sortedMonthly
  })()

  // ARS con el motor viejo sigue clavado en 12 meses (más atrás, la inflación
  // histórica hacía el gráfico inútil). Con la serie del motor el usuario elige,
  // igual que en dólares: la curva ya está medida y cortada donde corresponde.
  const effectiveRange = (currency === 'ARS' && !usaPerfEnPesos) ? 12 : chartRange

  // Filtrar al rango — ahora slice(-N) sobre datos mensuales = N meses correctos.
  const windowSeries = (() => {
    if (!effectiveRange || activeSeriesMonthly.length === 0) return activeSeriesMonthly
    const historical = activeSeriesMonthly.filter(s => s.key !== 'today')
    const today = activeSeriesMonthly.find(s => s.key === 'today')
    let sliced
    if (resolucionChart === 'diaria') {
      // Con puntos diarios, `slice(-N)` daría N DÍAS donde N son meses.
      const corte = new Date()
      corte.setMonth(corte.getMonth() - effectiveRange)
      const iso = corte.toISOString().slice(0, 10)
      sliced = historical.filter(s => s.key >= iso)
      if (sliced.length < 2) sliced = historical
    } else {
      sliced = historical.slice(-effectiveRange)
    }
    return today ? [...sliced, today] : sliced
  })()

  // ⚠️ EL CORTE ENTRE TRAMOS VA ACÁ: después de resamplear y ordenar.
  // El índice se reinicia en cada tramo (twr.py) porque el derrumbe que pasó
  // dentro del hueco no se puede componer. Dibujados seguido, el salto de +20% a
  // 0% se lee como "volví a break-even" cuando la cartera se partió al medio. Un
  // punto en null hace que Recharts deje el hueco a la vista, que es la verdad.
  // Insertado acá el punto ya no pasa por el bucketing mensual, así que aterriza
  // EN SU FECHA y no al final del gráfico.
  // ⚠️ POR `segmento`, NO POR `tramo`. El tramo sólo conoce el hueco; el segmento
  // conoce además el CAMBIO DE BASE. Sin esto la línea unía las fotos al costo con
  // la primera medición a mercado y dibujaba la caída del 47% que el header se
  // niega a publicar — el usuario veía el desplome igual, en el gráfico.
  // ⚠️ B-5 · UN SEGMENTO DE UN PUNTO DIBUJA CERO PÍXELES. Una `<Line dot={false}>`
  // necesita dos puntos para trazar un path, así que el usuario del caso 452 —cuya
  // única medición a mercado es un punto— abría el gráfico y no veía NADA. Se marca
  // el punto solitario para dibujarle un punto de verdad; el resto sigue sin dots.
  const windowSeriesSolo = (() => {
    const cuenta = new Map()
    for (const s of windowSeries) {
      if (s?.segmento == null) continue
      cuenta.set(s.segmento, (cuenta.get(s.segmento) || 0) + 1)
    }
    return windowSeries.map(s => ({ ...s, solo: s?.segmento != null && cuenta.get(s.segmento) === 1 }))
  })()
  const windowSeriesCortada = cortarPorTramo(windowSeriesSolo, undefined, 'segmento')

  // Construir chartData rebased: ambas líneas arrancan en 0% en el primer
  // punto de la ventana — permite comparación justa en cualquier sub-período.
  // Fórmula de rebase (chain-linking TWRR):
  //   rebased = ((100 + current) / (100 + base) − 1) × 100
  //
  // NOTA: cuando hay snapshots, las keys de la serie son "YYYY-MM-DD" (diarias),
  // pero bench.sp500 y bench.inflation_ar son mensuales ("YYYY-MM").
  // Normalizamos siempre con monthKeyOf(key) = key.slice(0,7) para el lookup.
  // El nombre de la serie principal ES su rótulo en la leyenda del chart (Recharts
  // usa el `dataKey`), así que cambiarlo acá cambia lo que el usuario lee.
  const claveCartera = _perfContable
    ? `${userName} P/L vendido`
    : `${userName} P/L total`
  const chartData = (() => {
    const monthKeyOf = k => (k === 'today' ? k : k.slice(0, 7))

    // En ARS los benchmarks corren sobre los flujos de los brokers ARS (los
    // mismos que la línea del portfolio) y se miden EN PESOS; en USD, sobre
    // globalMonthly en USD. Así la comparación es apples-to-apples en la moneda
    // que se está viendo, sin mezclar retorno-en-pesos con retorno-en-dólares.
    const isArs = currency === 'ARS'
    const simMonthly = isArs ? arsMonthly : globalMonthly

    // Skeleton de meses para dibujar SOLO el benchmark cuando la serie del
    // portfolio (windowSeries) viene vacía — p.ej. en ARS sin dolar_blue, donde
    // benchSeriesArs no se puede construir. El benchmark (inflación/Merval/S&P)
    // se calcula aparte, así que puede dibujarse igual con el portfolio en null
    // en lugar de colapsar TODO el gráfico (ver más abajo).
    const buildBenchOnlySkeleton = () => {
      if (simMonthly.length === 0) return []
      const byMonth = {}
      for (const m of simMonthly) {
        const k = monthKey(m.year, m.month)
        byMonth[k.slice(0, 7)] = { key: k, label: benchLabel(k), total: null, realized: null }
      }
      let monthlyPts = Object.values(byMonth).sort((a, b) => a.key < b.key ? -1 : 1)
      if (effectiveRange) monthlyPts = monthlyPts.slice(-effectiveRange)
      monthlyPts.push({ key: 'today', label: 'Hoy', total: null, realized: null })
      return monthlyPts
    }

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

    // Retorno SIMPLE del índice: (price[k] / price[primer mes] − 1) × 100. Es el
    // retorno TIME-WEIGHTED del benchmark — "¿cuánto rindió el S&P?" — igual que el
    // broker. Antes era flow-matched (gain/invested ponderado por TUS aportes), que
    // subestimaba el S&P cuando el user aportaba cerca del pico (ej. +8,3% vs el
    // +18,57% real). NO clampeamos el acumulado-desde-el-inicio: el rebase a la
    // ventana (chain-link) necesita el valor crudo para dar el % correcto del período.
    function buildShadowFromSim(simResult, latestBenchPrice) {
      const result = new Map()
      const ps = simResult && simResult.priceSeries
      const firstPrice = simResult && simResult.firstPrice
      if (!ps || ps.length === 0 || !firstPrice || firstPrice <= 0) return result
      for (const p of ps) {
        if (p.price == null || p.price <= 0) continue
        result.set(p.key, +((p.price / firstPrice - 1) * 100).toFixed(4))
      }
      // "Today": precio MÁS RECIENTE del benchmark si lo hay (el user puede no haber
      // cargado el mes en curso pero el índice ya tiene precio actualizado); si no,
      // el último mes disponible.
      const lastPrice = ps[ps.length - 1].price
      const todayPrice = (latestBenchPrice != null && latestBenchPrice > 0) ? latestBenchPrice : lastPrice
      if (todayPrice != null && todayPrice > 0) {
        result.set('today', +((todayPrice / firstPrice - 1) * 100).toFixed(4))
      }
      return result
    }

    // Versión en PESOS del shadow — espejo exacto de benchSeriesArs. El simulador
    // devuelve valores USD-equiv; acá los pasamos a pesos (× blue del mes) y
    // medimos el retorno contra el capital aportado en pesos (flows × blue del
    // mes). Se usa en modo ARS para que el benchmark sea comparable a la línea
    // del portfolio, que también es retorno-en-pesos. Sin esto, comparábamos
    // retorno-en-pesos (cartera) contra retorno-en-dólares (benchmark).
    function buildShadowFromSimArs(simResult, latestBenchPrice) {
      const result = new Map()
      if (!simResult || arsMonthly.length === 0) return result
      const firstK = monthKey(arsMonthly[0].year, arsMonthly[0].month)
      const blueBase = lookupBlue(firstK)
      if (!blueBase) return result

      // Camino preferido: retorno SIMPLE del índice en PESOS — (price[k]×blue[k]) /
      // (price[first]×blue[first]) − 1, time-weighted, sin ponderar por los flujos.
      // Aplica a los benchmarks que exponen priceSeries (S&P/T-Bills/Oro/dólar-cash).
      const ps = simResult.priceSeries
      if (ps && ps.length > 0 && simResult.firstPrice > 0) {
        const priceByKey = {}
        for (const p of ps) priceByKey[p.key] = p.price
        const priceBase = priceByKey[firstK] ?? simResult.firstPrice
        if (priceBase > 0) {
          const basePesos = priceBase * blueBase
          for (const m of arsMonthly) {
            const mk = monthKey(m.year, m.month)
            const price = priceByKey[mk]
            if (price == null || price <= 0) continue
            const fx = lookupBlue(mk) || blueBase
            result.set(mk, +(((price * fx) / basePesos - 1) * 100).toFixed(4))
          }
          // "Today": precio MÁS fresco del índice (latestBenchPrice, igual que el
          // path USD) × blue actual. Usar ps[last] dejaba el "hoy" del benchmark
          // congelado en el último mes cargado mientras la cartera live ya reflejaba
          // el movimiento del índice → el benchmark se veía peor de lo real.
          const lastPrice = ps[ps.length - 1].price
          const todayIdx = (latestBenchPrice != null && latestBenchPrice > 0) ? latestBenchPrice : lastPrice
          if (todayIdx != null && todayIdx > 0) {
            result.set('today', +((((todayIdx * tcBlue) / basePesos) - 1) * 100).toFixed(4))
          }
          return result
        }
      }

      // Fallback (benchmarks ARS-nativos SIN priceSeries: Merval / plazo fijo /
      // pesos cash): método flow-matched anterior. TODO: portarlos a índice simple.
      if (!simResult.series || simResult.series.length === 0) return result
      const baselinePesos = (arsMonthly[0].capital_inicio || 0) * blueBase
      let netFlowsPesos = 0
      let peakInvestedPesos = baselinePesos > 0 ? baselinePesos : 0

      const simByKey = {}
      for (const p of simResult.series) simByKey[p.key] = p.value // USD-equiv

      for (const m of arsMonthly) {
        const mk = monthKey(m.year, m.month)
        const fx = lookupBlue(mk) || blueBase
        netFlowsPesos += ((m.deposits || 0) - (m.withdrawals || 0)) * fx
        const investedNowPesos = baselinePesos + netFlowsPesos
        if (investedNowPesos > peakInvestedPesos) peakInvestedPesos = investedNowPesos
        const denomP = stableInv(investedNowPesos, peakInvestedPesos)
        const shadowUsd = simByKey[mk]
        if (shadowUsd == null) continue
        const gainP = (shadowUsd * fx) - investedNowPesos
        const pct = denomP > 0 ? (gainP / denomP) * 100 : 0
        result.set(mk, +Math.min(Math.max(pct, -99), 200).toFixed(2))
      }

      // "Today": último valor del sim al blue ACTUAL — igual que el punto Hoy del
      // portfolio (valor live × tcBlue), para que ambos reciban el mismo salto de FX.
      const last = simResult.series[simResult.series.length - 1]
      const investedNowPesos = baselinePesos + netFlowsPesos
      const denomP = stableInv(investedNowPesos, peakInvestedPesos)
      const gainP = (last.value * tcBlue) - investedNowPesos
      const pct = denomP > 0 ? (gainP / denomP) * 100 : 0
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

    function buildInflationCumPct(monthlyArr) {
      // Inflación: % macro acumulativo, NO portfolio. cum = Π(1 + ipc_m).
      //
      // Componemos TODOS los meses del INDEC entre el primer y último mes del
      // usuario, NO solo los meses que el usuario tiene cargados. Si el user
      // tiene gaps (ej. cargó Ene y Jun pero no Feb-May), saltear esos meses
      // subestima la inflación acumulada del benchmark (la inflación corrió
      // igual aunque el user no haya registrado el mes). Reconstruimos la
      // serie mes a mes sobre el rango completo usando las claves 'YYYY-MM'
      // de bench.inflation_ar. El rango se toma de monthlyArr (en ARS = los
      // meses de los brokers ARS, mismo span que la línea del portfolio).
      const result = new Map()
      if (!bench?.inflation_ar || monthlyArr.length === 0) return result

      const firstMk = monthKey(monthlyArr[0].year, monthlyArr[0].month)
      const lastM = monthlyArr[monthlyArr.length - 1]
      const lastMk = monthKey(lastM.year, lastM.month)

      // Itera mes a mes entre firstMk y lastMk (inclusive), avanzando el
      // calendario con aritmética de meses (no depende de qué meses cargó el user).
      let cum = 1
      let [yr, mo] = firstMk.split('-').map(Number)
      while (true) {
        const mk = `${yr}-${String(mo).padStart(2, '0')}`
        if (mk === firstMk) {
          result.set(mk, 0)  // primer mes = base 0%
        } else {
          const ipc = bench.inflation_ar[mk]
          if (ipc != null) cum *= 1 + ipc / 100
          result.set(mk, +((cum - 1) * 100).toFixed(2))
        }
        if (mk === lastMk) break
        mo += 1
        if (mo > 12) { mo = 1; yr += 1 }
      }

      // Today: mismo valor que el último mes (inflación es histórica, no live)
      result.set('today', result.get(lastMk) ?? +((cum - 1) * 100).toFixed(2))
      return result
    }

    // Dispatcher: cada benchmark calcula su propio shadowPctByMonth. En ARS los
    // simuladores corren sobre simMonthly (= flujos de brokers ARS) y el shadow
    // se mide en PESOS (buildShadowFromSimArs); en USD, sobre globalMonthly en
    // dólares (buildShadowFromSim, con latestPrice para extrapolar el "today").
    const buildShadow = (sim, latestPrice) =>
      isArs ? buildShadowFromSimArs(sim, latestPrice) : buildShadowFromSim(sim, latestPrice)

    let shadowPctByMonth = new Map()
    if (selectedBench === 'sp500' && bench?.sp500) {
      shadowPctByMonth = buildShadow(simulateSp500(simMonthly, bench.sp500), latestPriceOf(bench.sp500))
    } else if (selectedBench === 'tbill' && bench?.shv) {
      shadowPctByMonth = buildShadow(simulateShv(simMonthly, bench.shv), latestPriceOf(bench.shv))
    } else if (selectedBench === 'gold' && bench?.gld) {
      shadowPctByMonth = buildShadow(simulateGold(simMonthly, bench.gld), latestPriceOf(bench.gld))
    } else if (selectedBench === 'dolar_cash') {
      shadowPctByMonth = buildShadow(simulateDolarCash(simMonthly))
    } else if (selectedBench === 'inflation') {
      shadowPctByMonth = buildInflationCumPct(simMonthly)
    } else if (selectedBench === 'merval' && bench?.merval && bench?.dolar_blue) {
      shadowPctByMonth = buildShadow(simulateMerval(simMonthly, bench.merval, bench.dolar_blue))
    } else if (selectedBench === 'plazo_fijo' && bench?.uva && bench?.dolar_blue) {
      shadowPctByMonth = buildShadow(simulatePlazoFijoUva(simMonthly, bench.uva, bench.dolar_blue))
    } else if (selectedBench === 'pesos_cash' && bench?.dolar_blue) {
      shadowPctByMonth = buildShadow(simulateArsCash(simMonthly, bench.dolar_blue))
    }

    // DESACOPLE: el benchmark no depende de la serie del portfolio. Si el
    // portfolio en pesos no se pudo armar (windowSeries vacío) pero hay un
    // benchmark para dibujar, usamos un skeleton de meses y dejamos la línea
    // del portfolio en null — así inflación/Merval/S&P siguen apareciendo en
    // vez de colapsar el gráfico al empty-state.
    let series = windowSeriesCortada
    let skeleton = false
    if (series.length === 0) {
      // ⚠️ Si SABEMOS por qué falta la línea del usuario, no se dibuja el
      // benchmark solo. El skeleton existe para el caso "el portfolio en pesos no
      // se pudo armar", no para tapar un motivo conocido: a una cuenta recién
      // importada le dibujaba el S&P solo, sin la cartera y sin ninguna
      // explicación, y si el benchmark tampoco cargaba el copy le echaba la culpa
      // al benchmark. El usuario tiene que leer POR QUÉ falta su línea.
      if (perf?.motivo) return []
      if (shadowPctByMonth.size === 0) return []
      series = buildBenchOnlySkeleton()
      skeleton = true
    }
    if (series.length === 0) return []

    const withBench = series.map(s => {
      let benchPct = null
      // ⚠️ B-6 · EL PUNTO DE CORTE NO TIENE MES. Su clave es `corte-2026-08-24`, y
      // `monthKeyOf` la recorta a 'corte-2'; como 'c' > '2', el fallback `k <= mk`
      // matchea TODOS los meses y se queda con el ÚLTIMO — así que en cada corte el
      // benchmark saltaba a su valor más reciente y volvía. La fila de corte existe
      // para dejar un hueco: tiene que estar vacía en TODAS las series, no sólo en
      // la del portfolio.
      const esCorte = typeof s.key === 'string' && s.key.startsWith('corte-')
      // ⚠️ EN USD EL BENCHMARK ES EL DEL BACKEND, POR FECHA. El shadow mensual de
      // abajo queda para ARS (donde la línea del usuario no sale de `perf.curva`) y
      // para el esqueleto sin cartera. Medido en producción: con el shadow mensual
      // la línea del S&P tenía 2 valores distintos sobre 44 filas y en 21 usuarios
      // el signo dado vuelta; y como se resolvía por los meses de `monthly_entries`,
      // 348 usuarios con huecos en la cadena mensual veían el ancla en otro mes
      // ("S&P +35%" donde hizo +3,8%).
      if (!esCorte && (!isArs || usaPerfEnPesos) && !skeleton) {
        benchPct = (typeof s.bench === 'number') ? +((s.bench - 1) * 100).toFixed(4) : null
      } else if (!esCorte && shadowPctByMonth.size > 0) {
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
    // ⚠️ EL ANCLA DEL BENCHMARK ES LA PRIMERA FILA QUE TIENE DATO, no la primera a
    // secas. Con `first.benchPct ?? 0`, 11 usuarios de producción cuya primera fila
    // caía antes del primer cierre disponible veían el S&P dibujado relativo a un 0
    // que no era su valor (plano en 0% toda la ventana).
    const _primeraConBench = withBench.find(s => s.benchPct != null)
    const baseBench = _primeraConBench ? _primeraConBench.benchPct : 0

    const filas = withBench.map(s => {
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
        labelDia: s.labelDia ?? s.label,
        // La CLAVE viaja para que `rellenarTimestamps` pueda ubicar la fila en el
        // tiempo. `label`/`labelDia` son texto de presentación: `labelDia` ni
        // siquiera lleva año, así que en una vista multi-año '30/09' se repite y
        // no alcanza para ordenar nada. Aditivo: nadie más las lee.
        key: s.key,
        estimado: !!s.estimado,
        solo: !!s.solo,
        // El acumulado CRUDO del punto —`(index − 1)·100`, ya relativo al arranque
        // de SU segmento—. Viaja además del rebaseado porque `acumuladoDeVentana`
        // lo necesita: el rebase es contra el borde de la ventana, y el número que
        // el KPI tiene que publicar es el del segmento, que es el único que no
        // cruza un cambio de regla de valuación. Ningún consumidor del chart lo
        // lee (Recharts usa las claves con nombre), así que es aditivo.
        total: s.total ?? null,
        // Para el KPI: el índice PUBLICADO, si el punto puede ser punta, y su base
        // (en estimado un punto contable también es punta de la cadena publicada).
        ip: (typeof s.ip === 'number') ? s.ip : null,
        apto: !!s.apto,
        base: s.base ?? null,
        [claveCartera]: rebaseTotal,
        [`${userName} P/L realizado`]: rebaseRealized,
        [benchmarkKey]: rebaseBench,
      }
    })
    // La parte no medida va en su propia clave, para dibujarla punteada.
    // `rellenarTimestamps` va ANTES de partir: necesita la serie entera y en
    // orden para poder poner los cortes en el punto medio de sus vecinas.
    return partirMedidoYEstimado(
      rellenarTimestamps(filas), claveCartera, `${userName} estimado`)
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
  // ⚠️ EL DRAWDOWN YA NO SE CALCULA ACÁ. Salía de `buildCumulativeReturnSeries`,
  // que en `insightsModel.js:106` hace
  //     capFinal = (isLast && liveValue > 0) ? liveValue : m.capital_final
  // sin mirar `m.mtm` — o sea cierra el último mes a valor de MERCADO contra un
  // arranque que puede venir de la cadena CONTABLE. Trece líneas más arriba, el
  // guard de `applyMtmToMonthly` (:592-597, :621, :653) dice textual que las dos
  // puntas tienen que estar en la misma base; esa línea lo desarmaba entero.
  // Medido con los datos del user 452: −47,3% donde lo real era ~0.
  // Ahora manda `twr.curva_indexada`, que descarta lo que no es base de mercado
  // y NUNCA deja que un punto no medido fije un pico.
  // La tira de KPIs (`InsightsKpiStrip`) espera {currentPct, maxPct}: es EL lugar
  // donde el usuario leyó "Drawdown actual −45,0% / peak histórico −85,0%". Se le
  // da la misma forma, con los números del backend.
  // El gate vive en `drawdownFromPerf` (insightsModel.js) para que esté cubierto
  // por test: exige los DOS campos no-null. El `|| 0` que estaba acá re-fabricaba
  // del lado del cliente el 0,0% que el backend acababa de dejar de publicar.
  const drawdownTwrr = drawdownFromPerf(perf)
  const drawdown = drawdownTwrr ? {
    max: drawdownTwrr.maxPct,
    current: drawdownTwrr.currentPct,
    peakReturnPct: null,
    troughReturnPct: null,
  } : null

  // Card 3 del perfil del inversor — requiere el drawdown ya computado.
  // Si no hay returnSeries todavía (sin historia mensual) pasamos null y
  // la card cae a no_portfolio.
  const drawdownCard = computeDrawdownTolerance(
    investorProfile,
    drawdown?.max,  // % negativo; la función hace Math.abs()
  )
  // Card nueva (2026-05-27): estilo declarado vs trade frequency real. Usa
  // operations (todas las ops del user) y la función filtra a SELLs adentro.
  const styleCard = computeStyleCoherence(investorProfile, operations)

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
  // Solo consumimos topAsset.asset y topAsset.pnl (snapshot del Coach IA, abajo).
  // NO calculamos pct/invested: sumar entry_price*quantity de operaciones en
  // monedas mezcladas (ARS de CEDEARs + USD) daría un denominador corrupto y un
  // pct sin sentido. Como ese pct no se usa en ningún lado, lo eliminamos en vez
  // de arrastrar un número equivocado.
  let topAsset = null
  if (operations.length > 0) {
    const byAsset = {}
    for (const op of operations) {
      const k = (op.asset || '').toUpperCase()
      if (!k) continue
      if (!byAsset[k]) byAsset[k] = { asset: k, pnl: 0, trades: 0 }
      byAsset[k].pnl += op.pnl_usd || 0
      byAsset[k].trades += 1
    }
    const arr = Object.values(byAsset).sort((a, b) => b.pnl - a.pnl)
    const best = arr[0]
    if (best && best.pnl > 0) {
      topAsset = { ...best, runnerUp: arr[1] || null }
    } else if (best) {
      topAsset = { ...best, runnerUp: arr[1] || null, allNegative: true }
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
    // Impuestos/retenciones (Ganancias/IIBB/BBPP) — separados de comisiones: el
    // backend los devuelve aparte (operation_type='IMPUESTO'). Antes se contaban
    // como comisión → la card inflada con impuestos + ajustes de cambio.
    commissionsStats = {
      total, count, avgPerTrade: total / count, pctOfGrossWin,
      taxes: commissionsApi.taxes_usd ?? 0,
      taxesCount: commissionsApi.taxes_count ?? 0,
    }
  }

  // ── Insight 6: Concentración (top 3 activos sobre portfolio total) ──
  // Reutiliza assetPieData (ya agregado por activo, excluyendo cash).
  let concentration = null
  if (assetPieData.length > 0 && totalPortfolio > 0) {
    const top3 = assetPieData.slice(0, 3).map(x => ({ asset: x.name, value: x.value }))
    const top3Sum = top3.reduce((s, x) => s + x.value, 0)
    concentration = {
      top3,
      // La concentración no puede superar el 100%; un leve excedente (~101%) es
      // divergencia de valuación/redondeo (Σ holdings vs total por-broker) → clamp.
      sharePct: Math.min((top3Sum / totalPortfolio) * 100, 100),
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
    // Cripto en broker AR se valúa al dólar cripto; en exchange, a spot (factor 1).
    // El factor escala value E invested por igual → el P&L% no cambia.
    const f = cryptoBrokerFactor(p.asset, exchangeBrokers.has(p.broker), p.price_override != null, tcCripto, tcCedear)
    // valueUsd usa el helper compartido (con clamp anti-distorsión). investedUsd
    // queda por-rama (el costo no se clampea).
    const valueUsd = holdingValueUsd(p)
    let investedUsd
    if (isARS && costInUsd(p)) {
      // Lote de COSTO EN DÓLARES en un broker ARS (Balanz): el costo YA está en USD
      // → sin ÷blue (va antes que isARS, que sí divide y colapsaría el costo). Gateado
      // a broker ARS para no pisar una acción US genuina en broker USD (esa cae al
      // else → realCost, sincronizada con holdingValueUsd que también va al else USD).
      investedUsd = realCost
    } else if (isARS) {
      investedUsd = realCost / tcBlue
    } else if (costInPesos(p)) {
      investedUsd = pesoLotUsd(p, prices, tcCedear).investedUsd
    } else if ((p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && !isFciSym(p.asset) && p.price_override == null && !isCrypto(p.asset)) {
      investedUsd = realCost
    } else {
      investedUsd = realCost * f
    }
    const pnlUsd = valueUsd - investedUsd
    return {
      broker: p.broker,
      asset: p.asset,
      asset_type: p.asset_type,
      qty: p.quantity,
      entry_date: p.entry_date,
      invested_usd: +investedUsd.toFixed(2),
      value_usd: +valueUsd.toFixed(2),
      pnl_usd: +pnlUsd.toFixed(2),
      pnl_pct: investedUsd > 0 ? +((pnlUsd / investedUsd) * 100).toFixed(2) : null,
      pct_of_portfolio: totalPortfolio > 0 ? +((valueUsd / totalPortfolio) * 100).toFixed(2) : null,
    }
  }).sort((a, b) => (b.value_usd || 0) - (a.value_usd || 0))
  // Cinturón anti-inconsistencia (dev-only): alerta si alguna posición del snapshot
  // no cierra (value/pnl vs %) o huele a inflado — sin cambiar ningún valor.
  // aiPositions.pnl_pct viene en percent (×100) → se lo declaramos al guard.
  auditPositions(aiPositions, 'Insights.aiPositions', { pct: 'percent' })

  // Agregado POR ACTIVO: varios lotes/brokers del mismo activo → una sola fila. El %
  // se DERIVA del agregado con positionPct (NUNCA el del primer lote — ese era el bug
  // GOOGL). Lo usan las alertas de concentración/pérdida y el best/worst por activo,
  // que antes tomaban el % de un lote suelto como si fuera el del activo entero.
  const aiByAsset = Object.values(aiPositions.reduce((acc, p) => {
    const k = (p.asset || '').toUpperCase()
    if (!k) return acc
    const cur = acc[k] || { asset: p.asset, value_usd: 0, invested_usd: 0, pnl_usd: 0, pct_of_portfolio: 0, is_cash: false }
    cur.value_usd += p.value_usd || 0
    cur.invested_usd += p.invested_usd || 0
    cur.pnl_usd += p.pnl_usd || 0
    cur.pct_of_portfolio += p.pct_of_portfolio || 0
    acc[k] = cur
    return acc
  }, {})).map(a => {
    const r = positionPct(a.value_usd, a.pnl_usd)                        // ratio agregado
    return { ...a, pnl_pct: r != null ? +(r * 100).toFixed(2) : null }   // percent (×100), como aiPositions
  }).sort((a, b) => (b.value_usd || 0) - (a.value_usd || 0))
  auditPositions(aiByAsset, 'Insights.aiByAsset', { pct: 'percent' })

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
  const openExtremes = computeOpenPositionExtremes(aiByAsset)
  // Consistencia mensual — % meses positivos + std dev del retorno mensual.
  const consistency = computeMonthlyConsistency(returnSeries)
  // Drawdown como serie temporal (para chart underwater).
  // Curva de drawdown: los puntos que el backend marcó como base de mercado. Un
  // punto no-apto no aparece — no puede ser el fondo de una caída que nadie midió.
  // El mismo corte que la línea principal: sin él, el primer punto del tramo 2
  // vale 0% de drawdown y pegado al tramo 1 se lee como "recuperé todo".
  const drawdownSeries = cortarPorTramo(
    (perf?.curva || [])
      .filter(p => p.apto && p.drawdown != null)
      .map(p => ({
        key: p.date,
        tramo: p.tramo,
        label: p.date === 'hoy' ? 'Hoy'
          : `${MES_CORTO[+p.date.slice(5, 7) - 1] || ''} '${p.date.slice(2, 4)}`,
        ddPct: +(p.drawdown * 100).toFixed(2),
      })),
    { ddPct: null })
  // Concentración por broker — pieData ya está calculado arriba.
  const brokerConcentration = computeBrokerConcentration(pieData)
  // Distribución por tipo de activo: combinamos posiciones abiertas + cash.
  // Spread completo en vez de elegir campos a mano: la versión anterior
  // enumeraba {asset, asset_type, broker, is_cash, value_usd} y se comía el
  // `pnl_usd` que aiPositions SÍ trae resuelto (:1448) — sin él, la torta se
  // quedaba sin la pata de resultado no realizado y el "Resultado" del
  // desplegable solo aparecía en las clases que tuvieran ventas. El Dashboard
  // mostraba el número y Métricas no.
  // Los campos de más son inertes para los consumidores (leen por nombre).
  const positionsForType = [
    ...aiPositions.map(p => ({ ...p, is_cash: false })),
    ...aiCash.map(c => ({ ...c, is_cash: true })),
  ]
  const assetTypeBreakdown = computeAssetTypeBreakdown(positionsForType, brokers)
  // Los dos ejes de la torta de distribución. MISMOS agregadores que el
  // Dashboard — el objetivo es que las dos pantallas no puedan dar números
  // distintos. El plazo fijo entra como porción sintética, igual que allá.
  const pfRollup = pfUsd(pfTotals, tcBlue)
  const pfSliceUsd = pfRollup.valueUsd
  const pfPnl = { total: pfRollup.pnlUsd, cost: pfRollup.investedUsd }
  const classBreakdown = computeClassBreakdown(
    positionsForType, brokers,
    pfSliceUsd > 0 ? [{ key: 'plazo_fijo', value: pfSliceUsd, pnl: pfPnl }] : [],
    operations,
  )
  const sectorBreakdown = computeSectorBreakdown(
    positionsForType, brokers,
    pfSliceUsd > 0 ? [{ key: 'renta_fija', value: pfSliceUsd, pnl: pfPnl }] : [],
    operations,
  )

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
  // Mínimo 2 meses para que arranque CAGR; el resto de métricas tienen sus
  // propios thresholds adentro (3 meses para Sharpe/Sortino/Vol, 6 para Alpha/IR).
  // Pasamos el drawdown max para que Calmar Ratio (CAGR / |maxDD|) se compute.
  const proMetrics = computeProMetrics(globalMonthly, bench, drawdown?.max)

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

  // ── Inflación acumulada recortada a la ventana de benchSeriesArs ──────────
  // El diagnóstico beat/lose_inflation_ars compara portfolioReturnArsPct (retorno
  // de la cartera EN PESOS, calculado sobre el rango de meses de brokers ARS)
  // contra la inflación. inflationCum global se computa sobre globalMonthly (TODOS
  // los brokers), un rango potencialmente distinto → comparar dos rangos invalida
  // el veredicto. Acá recortamos la inflación a EXACTAMENTE [firstKey..lastKey] de
  // benchSeriesArs. Si lastKey es 'today', el tope efectivo es el último IPC
  // disponible (la fecha live ≈ presente).
  const inflationCumArsWindow = (() => {
    if (!bench?.inflation_ar || !arsWindowFirstKey || !arsWindowLastKey) return null
    const lastKeyEff = arsWindowLastKey === 'today'
      ? (inflKeys.length ? inflKeys[inflKeys.length - 1] : null)
      : arsWindowLastKey
    if (!lastKeyEff) return null
    let cum = 1, count = 0
    for (const k of inflKeys) {
      if (k <= arsWindowFirstKey) continue
      if (k > lastKeyEff) break
      const ipc = bench.inflation_ar[k]
      if (ipc != null) { cum *= 1 + ipc / 100; count += 1 }
    }
    if (count === 0) return null
    return { cumPct: (cum - 1) * 100, monthsCounted: count, fromKey: arsWindowFirstKey, toKey: lastKeyEff }
  })()

  // Card de perfil "Expectativa de retorno" — cruza la expectativa declarada en
  // el test contra el retorno REAL (neto de inflación, pesos) de la ventana ARS.
  // Se computa acá (no junto a las otras cards de perfil) porque necesita el
  // retorno en pesos + la inflación recortada a la misma ventana, disponibles
  // recién en este punto. Mismo criterio de moneda que el diagnóstico de
  // inflación: retorno-pesos vs inflación-pesos (NUNCA mezclar con USD).
  const returnExpectationCard = (() => {
    // Con la serie del motor, el retorno en pesos es el que publica el motor
    // (`perf.twr`), no el del armado viejo: si no, el veredicto compara contra la
    // inflación un número que el gráfico de arriba no muestra.
    const ret = (usaPerfEnPesos && perf?.twr != null)
      ? perf.twr * 100 : portfolioReturnArsPctRaw
    const infl = inflationCumArsWindow?.cumPct
    const realReturnPct = (ret != null && isFinite(ret) && infl != null)
      ? ((1 + ret / 100) / (1 + infl / 100) - 1) * 100
      : null
    return computeReturnExpectation(investorProfile, {
      portfolioReturnPct: ret,
      inflationPct: infl ?? null,
      realReturnPct,
      monthsCounted: inflationCumArsWindow?.monthsCounted ?? null,
    })
  })()

  // ── Diagnóstico general — motor data-driven (utils/diagnostics.js) ────────
  // Existen muchos generadores; cada uno mira un aspecto distinto del
  // portfolio y emite un bullet solo si su condición aplica. Cada día se
  // muestran los más relevantes (severidad alta primero) con una rotación
  // estable dentro del día para dar variedad sin perder lo importante.
  const diagnosisPool = selectDiagnostics({
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
    // inflationCum global (sobre globalMonthly) se usa en otros lugares de la UI,
    // pero para el diagnóstico beat/lose_inflation_ars pasamos la inflación
    // RECORTADA a la ventana de benchSeriesArs (mismo rango que el retorno en pesos).
    // Esos dos son los únicos generadores que consumen `inflationCum`.
    inflationCum: inflationCumArsWindow,
    // Retorno acumulado de la cartera EN PESOS (MWR) del último punto de benchSeriesArs,
    // SIN el clamp [-99, +200] que aplica el chart (ese clamp distorsiona la comparación
    // contra inflación no-clampeada y podía invertir el veredicto). Se compara contra la
    // inflación INDEC (pesos): NUNCA mezclar retorno-USD con inflación-pesos.
    // null si no hay serie ARS computable → los guards del diagnóstico lo ocultan.
    portfolioReturnArsPct: portfolioReturnArsPctRaw,
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
    commissionsStats,     // { total, count, avgPerTrade, pctOfGrossWin } — costos de operar
    proMetrics,           // vol/beta/sharpe/sortino/alpha/IR/CAGR/calmar (ex Métricas Pro)
    isFree: plan.isFree,  // Free ve las métricas BLOQUEADAS (teaser → upsell Plus)
  }, 999)  // pool COMPLETO: la grilla adaptativa rota/reemplaza sobre todos los
           // aplicables; el KPI/featured usan diagnosis.slice(0,12) abajo.
  // Vista capada (12) para el KPI strip y el featured — no cambia su comportamiento.
  const diagnosisTop = diagnosisPool.slice(0, 12)

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
  if (aiByAsset.length > 0) {
    const top = aiByAsset[0]
    if (top?.pct_of_portfolio > 40) {
      alerts.push({
        level: 'warning',
        category: 'Concentración',
        title: `${top.asset} representa el ${top.pct_of_portfolio.toFixed(0)}% de la cartera`,
        text: 'Concentración elevada en un único activo. Una caída significativa de ese instrumento impactaría de forma desproporcionada en el resultado total.',
      })
    }
  }

  // D2: drawdown activo > 15%
  if (drawdown && drawdown.current < -15) {
    alerts.push({
      level: 'warning',
      category: 'Drawdown',
      title: `La cartera está ${Math.abs(drawdown.current).toFixed(1)}% por debajo de su máximo histórico`,
      text: 'Tu cartera atraviesa un drawdown. Es momento de revisar si los fundamentos de tu estrategia siguen siendo válidos.',
    })
  }

  // D3: posición con pérdida > 25%
  const bigLosers = aiByAsset.filter(p => p.pnl_pct != null && p.pnl_pct < -25)
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
      // El MEP que la IA cita tiene que ser el mismo con el que la app valúa (el
      // medio), no la punta de compra — si no, sus números no cuadran con la tabla.
      dolar_mep_venta: (dolar?.mep?.medio ?? dolar?.mep?.venta) || null,
    },
  }

  // Banner: faltan precios → muchos cálculos quedan en cost basis (P&L = 0).
  // Detectamos esto preguntando si hay alguna posición no-cash sin precio
  // resuelto (override o fetch). Si sí, mostramos warning visible.
  const missingPriceTickers = positions
    .filter(p => !p.is_cash && p.price_override == null &&
      prices[p.asset] == null && prices[priceSymbol(p.asset, true)] == null)
    .map(p => String(p.asset || '').toUpperCase())
    .filter(Boolean)
  const hasMissingPrices = missingPriceTickers.length > 0

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
        <div className="border border-line rounded-xl bg-bg-1 px-6 py-12 text-center max-w-2xl mx-auto">
          <Activity size={28} strokeWidth={1.5} className="mx-auto mb-3 text-ink-3" />
          <h2 className="text-base font-medium text-ink-0 mb-1.5">Todavía no podemos analizar tu cartera</h2>
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

  // ── Diagnóstico adaptativo (2026-07-17) ─────────────────────────────────
  // Motor de la plantilla: clasifica el arquetipo y decide orden/visibilidad
  // de los slots. La IA (DiagnosticoSummaryBlock) narra arriba; nunca decide
  // el layout ni los números (mismo espíritu que el Perfil).

  // Veredicto comparativo — items que también muestra ArAlternativesVerdict.
  // Los extraemos a una const para reusarlos en el render Y en los params IA.
  // Las tres celdas responden preguntas DISTINTAS con matemáticas distintas, y
  // hasta acá se veían iguales: mismo formato, mismo "Le ganás", mismo % grande.
  // Poner tres números no comparables uno al lado del otro es justamente lo que
  // hace que alguien reste "17,2 − 8,8" y saque una conclusión que no se sostiene.
  // Cada una lleva ahora su base escrita.
  const verdictItems = [
    // La UNIDAD va escrita: el UVA se simula EN PESOS (capitaliza con el
    // coeficiente) y recién después se pasa a dólares al blue de cada mes
    // (`simulatePlazoFijoUva`, índice uva/blue). La cuenta es correcta, pero sin
    // decir "medido en dólares" cualquiera lee "me comparan mi rendimiento en USD
    // contra una tasa en pesos" y desconfía del número — pasó.
    {
      key: 'plazo_fijo', label: 'Plazo fijo UVA', pct: vsPlazoFijo?.pct ?? null,
      nota: 'tu patrimonio de hoy vs la misma plata en UVA · medido en dólares',
    },
    {
      key: 'dolar', label: 'Dólar', pct: vsDolar?.pct ?? null,
      nota: 'tu patrimonio de hoy vs la misma plata en dólares',
    },
    {
      key: 'inflacion',
      label: 'Inflación',
      pct: (portfolioReturnArsPctRaw != null && isFinite(portfolioReturnArsPctRaw) && inflationCumArsWindow?.cumPct != null)
        ? ((1 + portfolioReturnArsPctRaw / 100) / (1 + inflationCumArsWindow.cumPct / 100) - 1) * 100
        : null,
      // Otra pregunta y otra base: es el retorno REAL (time-weighted) de la pata
      // en PESOS, no una comparación de patrimonios. Y solo cubre los brokers en
      // pesos — callarlo hace creer que habla de toda la cartera.
      nota: `retorno real de tus brokers en pesos${inflationCumArsWindow?.monthsCounted
        ? ` · ${inflationCumArsWindow.monthsCounted} ${inflationCumArsWindow.monthsCounted === 1 ? 'mes' : 'meses'}` : ''}`,
    },
  ]

  // Composición POR ACTIVO (incluye cash) — % de cada activo sobre el total.
  // Top 7 + cola agrupada en "Otros N activos". Estándar para todos.
  const compositionRows = (() => {
    const byAsset = {}
    let total = 0
    for (const p of positionsWithValue) {
      const v = p.value_usd
      if (v == null || v <= 0) continue
      const name = p.is_cash ? 'Efectivo' : String(p.asset || '').toUpperCase()
      if (!name) continue
      if (!byAsset[name]) byAsset[name] = { value: 0, cash: !!p.is_cash }
      byAsset[name].value += v
      total += v
    }
    if (total <= 0) return []
    const rows = Object.entries(byAsset)
      .map(([name, o]) => ({ name, value: o.value, pct: Math.round((o.value / total) * 100), cash: o.cash }))
      .sort((a, b) => b.value - a.value)
    const TOP = 7
    if (rows.length <= TOP) return rows.map(({ value, ...r }) => r)
    // Cola: sumamos VALORES crudos y redondeamos una vez (sumar %-ya-redondeados
    // daba 0% con muchas posiciones chicas → escondía cartera real).
    const tailValue = rows.slice(TOP).reduce((s, r) => s + r.value, 0)
    const tailPct = Math.round((tailValue / total) * 100)
    return [...rows.slice(0, TOP).map(({ value, ...r }) => r), { name: `Otros ${rows.length - TOP} activos`, pct: tailPct, cash: false }]
  })()

  const hasVerdicts = verdictItems.some(v => v.pct != null)

  const cryptoSharePct = assetTypeBreakdown.find(d => d.type === 'Cripto')?.sharePct || 0
  const rentaFijaSharePct = (() => {
    if (totalPortfolio <= 0) return 0
    const rf = positionsWithValue.reduce((s, p) => {
      const t = String(p.asset_type || '').toUpperCase()
      return (t === 'BOND' || t === 'ON' || t === 'FUND') ? s + (p.value_usd || 0) : s
    }, 0)
    return (rf / totalPortfolio) * 100
  })()

  // Delta "desde tu última visita" — record() computa y agenda persistencia.
  // Solo en la tab Diagnóstico (Métricas/Perfil son el mismo componente con
  // otro _embeddedTab; sin este guard pisarían la huella de "última visita").
  const { delta: visitDelta } = showDiagnostico
    ? lastVisit.record({ valueUsd: totalPortfolio, findingIds: diagnosisPool.map(d => d.id) })
    : { delta: null }

  const diagLayout = buildDiagnosticoLayout({
    nonCashPositions: positionsWithValue.filter(p => !p.is_cash && (p.value_usd || 0) > 0).length,
    monthsTracked: globalMonthly.length,
    snapshotsCount: snapshots.length,
    cryptoSharePct,
    rentaFijaSharePct,
    hasMissingPrices,
    diagnosisCount: diagnosisPool.length,
    hasFeatured: diagnosisPool.some(d => d.severity === 'urgent' || d.severity === 'warn'),
    hasVerdicts,
    hasContributors: topContribPos.length + topContribNeg.length > 0,
    hasComposition: compositionRows.length > 0,
    hasDrawdown: drawdownSeries.length >= 2,
    isFirstVisit: !!visitDelta?.isFirstVisit,
  })
  // El veredicto se muestra SOLO si el motor no lo suprimió (ej. usuario nuevo
  // sin historial → 'le perdés al plazo fijo' sobre días de ruido). Y va ARRIBA
  // (antes del KPI) para el conservador AR / cripto — su pregunta central.
  const verdictVisible = diagLayout.slots.includes('verdict') && hasVerdicts
  const verdictFirst = verdictVisible &&
    diagLayout.slots.indexOf('verdict') < diagLayout.slots.indexOf('kpi')
  const verdictNode = verdictVisible ? <ArAlternativesVerdict items={verdictItems} /> : null
  // El motor también decide si la curva de drawdown se muestra (se suprime sin
  // ≥2 meses de serie, en vez de un placeholder "necesitás 2 meses").
  // ⚠️ FASE 2 · EN MODO ESTIMADO NO HAY CARD DE DRAWDOWN.
  //
  // El KPI de arriba ya dice "—" porque el backend devuelve `drawdown_maximo:
  // null` en estimado, pero la CARD seguía dibujándose: `drawdownSeries` se arma
  // de `perf.curva` filtrando `p.apto`, así que en estimado quedaba una curva
  // hecha sólo con el pedacito medido, colgada de un chip que dice "Recreado de tu
  // contabilidad". El usuario leía "Drawdown actual —" y tres cards más abajo una
  // curva de drawdown que baja a −12%: la pantalla contradiciéndose sola.
  //
  // Y es la mitad que importa del guard: publicar el acumulado contable SIN sacar
  // el drawdown es exactamente cómo vuelve "Su ganancia cayó 167% desde el mejor
  // momento". El drawdown vive en el modo Certero, que es donde hay camino de
  // precios para medirlo.
  const showDrawdown = diagLayout.slots.includes('drawdown')
    && perf?.base_del_twr !== 'contable'

  // Params para la lectura IA — le pasamos lo que el frontend YA muestra
  // (archetype + findings + verdicts) para que no contradiga la pantalla.
  const diagAiParams = {
    archetype: diagLayout.archetype,
    findings: diagnosisTop.slice(0, 3).map(d => ({ category: d.category, severity: d.severity, text: d.text })),
    verdicts: verdictItems.filter(v => v.pct != null).map(v => ({ label: v.label, pct: Math.round(v.pct * 10) / 10 })),
    months_tracked: globalMonthly.length,
    missing_prices: [...new Set(missingPriceTickers)].slice(0, 12),
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
          </div>
        }
      />

      {/* ╔═══════════════════════════════════════════════════════════════════╗
          ║ BLOQUE DIAGNÓSTICO — visible en tab 'diagnostico' y standalone.   ║
          ║ Las métricas de riesgo/retorno (vol/beta/Sharpe/Sortino/alfa/IR/  ║
          ║ CAGR/Calmar) ya no viven en una sección aparte: son generadores   ║
          ║ de diagnóstico (utils/diagnostics.js) y entran a la grilla 3×3.   ║
          ╚═══════════════════════════════════════════════════════════════════╝ */}
      {showDiagnostico && (<>

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

      {/* ── Desde tu última visita — el gancho de retención ─────────────────── */}
      {visitDelta && !visitDelta.isFirstVisit && (
        <section className="bg-white dark:bg-bg-1 border border-line rounded-xl p-4">
          <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
            <p className="eyebrow">Desde tu última visita</p>
            {visitDelta.sinceLabel && (
              <span className="text-[12.5px] text-ink-3 font-medium">{visitDelta.sinceLabel}</span>
            )}
          </div>
          <DeltaSinceVisit delta={visitDelta} />
        </section>
      )}

      {/* ── Tu lectura personalizada (IA) — arriba del tablero ───────────────── */}
      <DiagnosticoSummaryBlock params={diagAiParams} />

      {/* Veredicto ARRIBA para el conservador AR / cripto (su pregunta central). */}
      {verdictFirst && verdictNode}

      {/* ── KPI strip overview (V2) ─────────────────────────────────────────── */}
      {(() => {
        const lastRow = chartData[chartData.length - 1] || {}
        // ── FASE 2 · el KPI del modo ESTIMADO ────────────────────────────────
        //
        // `partirMedidoYEstimado` reparte la serie en DOS claves para dibujar lo no
        // medido punteado. Para un usuario 100% contable TODOS los puntos caen en
        // la clave estimada y NINGUNO en la medida, así que este KPI leía `null` y
        // publicaba "—" **al lado de su propia curva dibujada**.
        //
        // ⚠️ EL MODO CERTERO NO SE TOCA, Y ES A PROPÓSITO. Sigue siendo
        // literalmente la misma expresión de antes. Medido sobre los 822: con la
        // regla nueva aplicada a certero, 6 usuarios PERDÍAN su número (los que
        // tienen una sola fila, donde el viejo publicaba "0,0%") y 2 lo GANABAN
        // (los que terminan en un punto no medido, que es justo lo que el certero
        // no debe publicar). Las dos diferencias son discutibles y ninguna es de
        // esta ronda: el certero queda congelado y se verifica usuario por usuario.
        const _kTotal = claveCartera
        const _kEstimado = `${userName} estimado`
        const _modoEstimado = perf?.base_del_twr === 'contable'
        // ⚠️ EN ESTIMADO EL KPI TAMBIÉN LEE LA CADENA PUBLICADA (`ip` = idx_est,
        // la del chip), entre la primera y la última punta de la ventana —
        // contable o medida—. Antes leía `total` (la FORMA), que además encadena
        // la intradía: medido, 85 de 655 usuarios tenían el fin de la línea ≠ el
        // chip. Si la ventana cruza un corte, cae al de antes (la última corrida
        // homogénea, con "parcial").
        const _pubEst = _modoEstimado
          ? acumuladoPublicado(chartData, benchmarkKey, { contable: true }) : null
        const _acum = _modoEstimado
          ? (_pubEst
              ? { pct: _pubEst.pct, parcial: false, desde: _pubEst.desde }
              : acumuladoDeVentana(chartData, _kTotal, _kEstimado))
          : null
        // ⚠️ EN CERTERO EL KPI LEE EL ÍNDICE PUBLICADO, NO EL DIBUJADO. `lastRow[_kTotal]`
        // es `(index − 1)·100` rebaseado, y `index` es la FORMA: encadena las fotos
        // intradía y no tiene el guard del cero absorbente. Medido en producción:
        // 20 de 480 usuarios veían acá un número >5 pp distinto del `perf.twr` que
        // el backend afirma (uid 745: +642,9% contra +6,6%), y 11 veían un número
        // donde el backend publica None (serie partida: el rebase unía los dos
        // tramos). `acumuladoPublicado` rebasea `index_publicado` entre el primer y
        // el último punto APTO de la ventana, y da null si hay un corte en el medio.
        // En ARS la serie no sale de `perf.curva` y no trae `ip`: cae al de antes.
        const _pub = (!_modoEstimado && (currency === 'USD' || usaPerfEnPesos))
          ? acumuladoPublicado(chartData, benchmarkKey) : null
        const cumulativeReturnPct = _modoEstimado
          ? (_acum ? _acum.pct : null)
          : (currency === 'USD' ? (_pub ? _pub.pct : null) : (lastRow[_kTotal] ?? null))
        // El benchmark del KPI, entre LAS MISMAS DOS FECHAS que el acumulado — es
        // lo que "mismo período" tiene que significar.
        const benchmarkReturnPct = (_pub && _pub.benchPct != null)
          ? _pub.benchPct
          : (_pub ? null : (lastRow[benchmarkKey] ?? null))
        // Label dinámico = el mismo nombre del benchmark seleccionado (chart legend).
        // Antes estaba hardcodeado a S&P 500 / Inflación AR e ignoraba la selección.
        const benchmarkLabel = benchmarkKey
        return (
          <InsightsKpiStrip
            diagnosis={diagnosisTop}
            assetPieData={assetPieData}
            drawdownTwrr={drawdownTwrr}
            winRate={winRate}
            cumulativeReturnPct={cumulativeReturnPct}
            benchmarkReturnPct={benchmarkReturnPct}
            benchmarkLabel={benchmarkLabel}
            ventanaMeses={effectiveRange}
            currency={currency}
            /* Un +16,9% reconstruido no puede verse igual que uno medido: el chip
               del gráfico ya dice "Recreado de tu contabilidad", y el KPI tiene que
               ser coherente con eso en vez de quedar mudo. `parcial` avisa cuando
               el número arranca DESPUÉS del borde de la ventana, que es lo que pasa
               cuando hay un corte de regla en el medio. */
            acumuladoEstimado={_modoEstimado && _acum ? {
              parcial: _acum.parcial, desde: _acum.desde,
              medidoDesde: perf?.medido_desde || null,
            } : null}
          />
        )
      })()}

      {/* Veredicto vs alternativas argentinas — de-buried: reusa las comparaciones
          flow-matched ya computadas. Si el arquetipo lo priorizó, ya se mostró
          arriba (verdictFirst); si no, va acá, después del KPI. */}
      {!verdictFirst && verdictNode}

      {/* ══════════════════════════════════════════════════════════════════════
          HERO — Diagnóstico con divulgación progresiva (2026-06-12).
          1 hallazgo DESTACADO arriba ("Lo que más importa") + el resto en 2
          secciones colapsables: "Requiere atención" y "Lo que va bien".
          Cantidad visible por tier: Free N (gateado), Plus/Pro todas.
          Ver <DiagnosisSection> para la lógica completa.
          ══════════════════════════════════════════════════════════════════════ */}
      {diagnosisPool.length > 0 && (
        <DiagnosisSection diagnosis={diagnosisPool} plan={plan} userKey={`diag:${(user?.email || 'anon').toLowerCase()}`} />
      )}

      {/* ── Distribución de activos — estándar, incluye cash. Movida arriba
          (era "Por activo" en Distribución, gateada Pro). El cruce por CLASE
          de activo vive ahora en el Perfil del inversor. ──────────────────── */}
      {compositionRows.length > 0 && (
        <section className="bg-white dark:bg-bg-1 border border-line rounded-xl p-4 sm:p-5">
          <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
            <p className="eyebrow">Distribución de activos</p>
            <span className="text-xs text-ink-2">
              Cash: <span className={`font-semibold tabular ${cashRatio >= 30 ? 'text-rendi-warn' : 'text-ink-1'}`}>{cashRatio.toFixed(1)}%</span>
            </span>
          </div>
          <CompositionByAsset rows={compositionRows} />
        </section>
      )}

      {/* ── Los otros dos ejes de la misma cartera ──────────────────────────
          Arriba está "en qué activos estoy"; acá "en qué clase de instrumento"
          y "a qué parte de la economía". Mismo componente y mismos agregadores
          que el Dashboard: si divergen los números, divergen en los dos lados
          a la vez. ────────────────────────────────────────────────────────── */}
      {classBreakdown.items.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <AskAIAbout
            topic="portfolio.distribution_type"
            params={toDistributionAiParams(classBreakdown)}
            subtitle="Distribución por tipo de activo"
            rounded={false}
          >
          <CompositionDonut
            title="Distribución por tipo de activo"
            items={classBreakdown.items}
            fmt={amt}
            height={230}
            info={
              <>
                <p className="font-semibold text-ink-0">Cómo se calcula</p>
                <p>
                  Primero dónde cotiza la posición (BYMA o exterior), después qué
                  ticker es. Por eso AAPL en un broker argentino cuenta como CEDEAR
                  y en uno del exterior como la acción US.
                </p>
                <p className="text-ink-3">
                  Incluye efectivo y plazos fijos: la torta suma tu patrimonio.
                </p>
              </>
            }
            footnote={<UnclassifiedNote data={classBreakdown.unclassified} kind="tipo" />}
          />
          </AskAIAbout>
          <AskAIAbout
            topic="portfolio.distribution_sector"
            params={toDistributionAiParams(sectorBreakdown)}
            subtitle="Distribución por sector"
            rounded={false}
          >
          <CompositionDonut
            title="Distribución por sector"
            items={sectorBreakdown.items}
            fmt={amt}
            height={230}
            info={
              <>
                <p className="font-semibold text-ink-0">Cómo se calcula</p>
                <p>
                  A qué parte de la economía estás expuesto. Un CEDEAR cuenta en el
                  sector de su empresa: un CEDEAR de NVDA es exposición a
                  semiconductores.
                </p>
                <p className="text-ink-3">
                  Bonos, letras, FCI, plazos fijos y efectivo no tienen sector
                  económico — van a su propia porción.
                </p>
              </>
            }
            footnote={<UnclassifiedNote data={sectorBreakdown.unclassified} kind="sector" />}
          />
          </AskAIAbout>
        </div>
      )}

      {/* ── Alertas críticas (danger) — solo lo más urgente arriba ─────────── */}
      {criticalAlerts.length > 0 && (
        <Section title="Requiere atención" subtitle="Situaciones críticas detectadas en tu cartera.">
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
      <div className="bg-white dark:bg-bg-1 border border-line rounded-xl p-5">
        <div className="flex items-start justify-between mb-3 flex-wrap gap-3">
          {/* ⚠️ EL CHIP VA EN SU PROPIO RENGLÓN, Y NO ES COSMÉTICO.
              Antes el título, el chip y el toggle compartían UNA fila flex, así que
              el ancho del chip —que cambia con el modo— empujaba al toggle.
              Medido en el browser a 840px de ancho, en esta misma cuenta:
                CERTERO   chip 153px → borde derecho del toggle en 744  (dentro)
                ESTIMADO  chip 385px → borde derecho del toggle en 918  (la tarjeta
                                        termina en 786: se salía 132px)
              O sea: el control se corría 174px al tocarlo, y en estimado quedaba
              fuera de su propia tarjeta. Un control que se mueve solo cuando lo
              usás es peor que uno feo.
              Con el chip abajo, la posición del toggle depende sólo del título,
              que es idéntico en los dos modos. */}
          <div className="min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <h2 className="font-semibold text-ink-0">
              {currency === 'USD' ? `Cartera vs ${benchmarkKey} (USD)` : `Cartera vs ${benchmarkKey} (ARS)`}
            </h2>
            {/* ⚠️ EN PESOS SE VE DESHABILITADO, NO DESAPARECE. Antes esto estaba
                envuelto en `currency === 'USD' &&`: en ARS el control no se dibujaba
                y el usuario no tenía forma de enterarse de que el otro modo existe.
                Un control ausente se lee como una app incompleta; uno deshabilitado
                con el motivo se lee como una app honesta. Y son 758 de 854 usuarios
                (89%) los que tienen al menos un broker en pesos.
                El GATE NO SE SACA: en ARS el modo estimado no se puede construir hoy
                —`arsMonthly` no pasa por `applyMtmToMonthly`, y el re-anclaje usa
                snapshots GLOBALES mientras la serie en pesos es un subconjunto—, y
                eso necesita snapshots por broker, que es un cambio de modelo de datos.
                ⚠️ En USD el markup tiene que quedar IDÉNTICO: con `deshabilitado`
                en false, el ternario devuelve exactamente las clases de antes y
                `disabled={false}` no emite atributo. */}
            <div className="flex gap-1 bg-bg-2 dark:bg-bg-1/60 rounded-lg p-0.5 ml-1">
              {[
                // El toggle es la decisión del usuario, así que los títulos dicen
                // qué GANA y qué PIERDE en cada posición — no cómo está
                // implementado. "Menos historial pero el número está bien" vs
                // "más historial con riesgo de error" es literalmente el trade-off
                // que el modo ofrece.
                { k: 'certero', t: 'Certero',
                  h: 'Menos historial, número exacto: sólo lo valuado a precio real. Incluye drawdown y pico.' },
                { k: 'estimado', t: 'Estimado',
                  h: 'Más historial, aproximado: reconstruido de tu contabilidad. Sólo se mueve cuando vendés — no refleja lo que pasa con lo que todavía tenés. No puede dar drawdown ni pico.' },
              ].map(({ k, t, h }) => (
                <button
                  key={k}
                  title={togglePerfDeshabilitado ? MOTIVO_TOGGLE_ARS : h}
                  disabled={togglePerfDeshabilitado}
                  onClick={() => setModoPerf(k)}
                  className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                    togglePerfDeshabilitado
                      // ⚠️ `text-ink-3` PELADO, NO `/50`. Con media opacidad sobre un
                      // token que ya arranca bajo, el control apagado se dibujaba a
                      // 1,67:1 —rgb(52,59,72) sobre rgb(14,18,24), en 11px—: la MITAD
                      // del contraste del estado habilitado más tenue (3,16:1). Un
                      // control que nadie ve es el vacío de antes con más HTML, y el
                      // objetivo de la ronda era justamente que el usuario se entere
                      // de que el modo existe. Sin el /50 queda en 3,16:1, el mismo
                      // que el botón no seleccionado en dólares.
                      // Sigue leyéndose como apagado porque lo que comunica el estado
                      // es el `cursor-not-allowed` y la ausencia de la píldora azul,
                      // no la opacidad.
                      ? 'text-ink-3 cursor-not-allowed'
                      : modoPerf === k
                        ? 'bg-blue-600 text-white'
                        : 'text-ink-3 hover:text-ink-0 dark:hover:text-ink-0'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
            <InfoTooltip>
              {/* §5.2 · La explicación del dueño, arriba de todo: es mejor que
                  cualquier cosa que hubiera en pantalla, y contesta la pregunta que
                  el usuario se hace al ver el toggle ("¿cuál de los dos me creo?").
                  ⚠️ Y deja dicho que el benchmark es EXACTO en los dos modos: es lo
                  único de esta pantalla que se sabe entero, y es el ancla fija
                  contra la cual leer el cambio de modo. */}
              {currency === 'USD' && (
                <>
                  <p className="font-semibold text-ink-0">Los dos modos</p>
                  <p>Tu rendimiento lo puedo medir de dos maneras: una de la que estoy
                     seguro pero con menos historial, y otra que te da más meses pero
                     es aproximada. El benchmark es el mismo y es exacto en las dos.</p>
                  <div className="border-t border-line/60 my-1.5" />
                </>
              )}
              {/* Medir en pesos NO es dividir el número de dólares: incluye la
                  devaluación, que es justamente lo que separa las dos monedas.
                  Sin decirlo, el usuario ve dos números distintos para la misma
                  cartera y no sabe cuál creer — los dos son correctos, contestan
                  preguntas distintas. */}
              {currency === 'ARS' && !togglePerfDeshabilitado && (
                <>
                  <p className="font-semibold text-ink-0">Estás viendo en pesos</p>
                  <p>Es la <strong>misma cartera</strong> que en dólares, medida en pesos:
                     cada punta al tipo de cambio de su fecha. Por eso este número
                     <strong> incluye la devaluación</strong> y no coincide con el de
                     dólares — las dos cosas son ciertas y contestan preguntas
                     distintas: cuántos dólares más tenés, y cuántos pesos más tenés.</p>
                  <p className="text-ink-3">El benchmark también se mide en pesos: al S&P
                     se le aplica el mismo tipo de cambio, así que la comparación es
                     pareja. La inflación y el Merval ya están en pesos.</p>
                  <div className="border-t border-line/60 my-1.5" />
                </>
              )}
              {/* En pesos el toggle se ve pero está apagado: acá va el porqué, para
                  que el control deshabilitado no sea otro vacío sin explicación. */}
              {togglePerfDeshabilitado && (
                <>
                  <p className="font-semibold text-ink-0">Por qué el toggle está apagado</p>
                  <p>Los dos modos necesitan una serie de tu cartera, y esta cuenta
                     todavía no tiene ninguna: ni fotos a precio real ni contabilidad
                     suficiente para reconstruirla. En cuanto haya, el toggle se
                     enciende solo.</p>
                  <div className="border-t border-line/60 my-1.5" />
                </>
              )}
              <p className="font-semibold text-ink-0">Qué mostramos</p>
              <p>Tu cartera comparada contra un benchmark, ambos en % desde el inicio del rango visible (las 3 líneas arrancan en 0%).</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">{_perfContable ? 'Las 2 líneas' : 'Las 3 líneas'}</p>
              <p><span className="inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle" style={{background:'#21D07A'}}/><strong>Verde sólido</strong>: {_perfContable
                ? 'lo que ya vendiste, reconstruido de tu contabilidad. NO incluye la ganancia o pérdida de lo que todavía tenés abierto — ese dato no existe hacia atrás.'
                : 'tu cartera total (lo cerrado + lo abierto).'}</p>
              {!_perfContable && (
                <p><span className="inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle" style={{background:'#E8B14A'}}/><strong>Amarillo punteado</strong>: solo lo cobrado (ventas + dividendos + intereses). Sin la plusvalía abierta.</p>
              )}
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
          {/* El chip, en su propio renglón: puede crecer todo lo que necesite sin
              mover un control. */}
          {chipPerfVisible && (
            <div className="mt-1.5"><ChipMedido explica /></div>
          )}
          </div>

          {/* Range tabs — solo en USD; ARS es siempre 12 meses */}
          {(currency === 'USD' || usaPerfEnPesos) && (() => {
            const RANGOS = [
              // 1M y 3M existen para el que recién empieza a medirse: con 45
              // días de historia, "1A" y "MAX" son la misma recta.
              { label: '1M', months: 1 },
              { label: '3M', months: 3 },
              { label: '1A', months: 12 },
              { label: '2A', months: 24 },
              { label: '5A', months: 60 },
              { label: 'MAX', months: null },
            ]
            // ⚠️ EL RANGO ES UN TOPE, NO UN ESTIRAMIENTO. Con 11 meses de historia,
            // 1A ya muestra todo y 2A/5A/MAX dibujan exactamente lo mismo; sin
            // decirlo, el usuario cambia de tab, no ve nada distinto y piensa que
            // el gráfico está roto (pasó). Se calcula el rango más chico que ya
            // contiene la primera fecha de la serie, y desde ahí se avisa.
            const _keys = activeSeries.filter(s => s?.key && s.key !== 'today').map(s => s.key).sort()
            const primerFechaSerie = _keys[0] || null
            const cutoffIso = (months) => {
              if (!months) return null
              const c = new Date(); c.setMonth(c.getMonth() - months)
              return c.toISOString().slice(0, 10)
            }
            const rangoCompleto = primerFechaSerie
              ? RANGOS.find(r => r.months == null || cutoffIso(r.months) <= primerFechaSerie) : null
            const rangoActual = RANGOS.find(r => r.months === chartRange) || null
            const muestraTodo = !!(rangoCompleto && rangoActual && (rangoActual.months == null
              || (rangoCompleto.months != null && rangoActual.months >= rangoCompleto.months)))
            const esRedundante = (r) => !!(rangoCompleto && r.months !== rangoCompleto.months
              && (r.months == null || (rangoCompleto.months != null && r.months > rangoCompleto.months)))
            const desde = primerFechaSerie ? fmtFecha(primerFechaSerie) : ''
            return (
            <div className="flex flex-col items-end gap-1">
              <div className="flex gap-1 bg-bg-2 dark:bg-bg-1/60 rounded-lg p-1">
                {RANGOS.map(({ label, months }) => (
                  <button
                    key={label}
                    onClick={() => setChartRange(months)}
                    title={esRedundante({ label, months })
                      ? `Muestra lo mismo que ${rangoCompleto.label}: tu historial empieza el ${desde}`
                      : undefined}
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
              {muestraTodo && (
                <span className="text-[11px] text-ink-3" data-testid="rango-completo">
                  {rangoActual.months === rangoCompleto.months
                    ? `${rangoActual.label} ya muestra todo tu historial · desde ${desde}`
                    : `Igual que ${rangoCompleto.label}: tu historial empieza el ${desde}`}
                </span>
              )}
            </div>
            )
          })()}
          {currency === 'ARS' && !usaPerfEnPesos && (
            <span className="text-xs text-ink-3 bg-bg-2 dark:bg-bg-1/60 px-2.5 py-1 rounded-lg">
              Últimos 12 meses
            </span>
          )}
        </div>

        {/* Selector de benchmark — segunda fila debajo del título.
            Opciones cambian según moneda (USD vs ARS). Persisted en localStorage. */}
        <div className="flex items-center gap-2 flex-wrap mb-4 -mt-1">
          <span className="text-[13px] text-ink-2 font-medium mr-1">
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

        {/* ⚠️ EL HUECO TIENE QUE VERSE, NO SÓLO EXISTIR. Con la serie partida el
            header publica "—" y la línea, resampleada a meses, se lee continua: el
            usuario no tiene forma de saber por qué no hay número. Son 167 usuarios
            reales del padrón. El texto sale de `twr.MOTIVO_TEXTO`, o sea el mismo
            que lee el asesor — no una redacción paralela. */}
        {perf?.serie_partida && chartData.length > 0 && (() => {
          // ⚠️ EL AVISO ES DE LA SERIE; EL KPI, DE LA VENTANA. `serie_partida` dice que
          // en ALGÚN lado la serie tiene un corte (un hueco de 45 días, un cambio de
          // regla o una foto que no cierra). Si ese corte cae fuera del rango visible
          // —1M después de una foto rota del mes anterior—, el acumulado de ESTA
          // ventana sí se mide (`acumuladoPublicado`, entre dos puntos aptos del mismo
          // tramo) y el KPI lo publica. Un aviso que diga "no se publica" al lado de
          // un KPI con número es una contradicción en pantalla, así que la frase
          // mira dónde está el corte. Y una foto dudosa no es un hueco: el titular
          // también lo distingue.
          const corteEnVentana = chartData.some(r => String(r?.key || '').startsWith('corte-'))
          const titular = perf.motivo === 'medicion_dudosa' ? 'Hay una foto que no cierra.'
            : perf.motivo === 'cadena_implausible' ? 'Tu contabilidad no coincide con lo medido.'
            : 'La medición tiene un hueco.'
          return (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-line bg-bg-2/60 px-3 py-2">
            <Info size={14} className="mt-0.5 shrink-0 text-ink-3" />
            <p className="text-[12px] leading-snug text-ink-2">
              <span className="font-semibold text-ink-0">{titular}</span>{' '}
              {perf.motivo_texto || 'Los tramos de cada lado se miden solos, pero no se pueden encadenar.'}{' '}
              <span className="text-ink-3">{corteEnVentana
                ? 'Por eso el porcentaje de punta a punta no se publica y la línea aparece cortada.'
                : 'En el rango que estás viendo no cae ningún corte: el acumulado de esta ventana sí se mide. El de punta a punta, no.'}</span>
            </p>
          </div>
          )
        })()}

        {chartData.length === 0 ? (
          perf?.motivo_texto ? (
            // El motivo REAL, del backend (`twr.MOTIVO_TEXTO`). Antes este lugar
            // decía "los datos del benchmark no están disponibles" — le echaba la
            // culpa al benchmark cuando lo que falta es la medición del usuario.
            <SinMediciones />
          ) : (
            <div className="text-center py-10 text-ink-3 text-sm mt-4">
              <Info size={20} className="mx-auto mb-2 opacity-50" />
              {globalMonthly.length === 0
                ? 'Cargá al menos un mes en Resumen Mensual para visualizar la evolución.'
                : 'Cargando la comparativa… si no aparece, los datos del benchmark no están disponibles por ahora.'}
            </div>
          )
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            {/* Clean pass 2026-07: área con gradiente bajo la línea principal,
                grilla suave solo horizontal, ejes sans, benchmark punteado,
                tooltip estilo card. ComposedChart para mezclar Area + Line. */}
            <ComposedChart data={chartData} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="portGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#21D07A" stopOpacity={0.20} />
                  <stop offset="100%" stopColor="#21D07A" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1B2230" strokeOpacity={0.35} vertical={false} />
              {/* ⚠️ EJE DE TIEMPO, NO DE CATEGORÍA. Un eje de categoría reparte los
                  puntos en partes iguales por índice y no mira la fecha: mientras la
                  serie tuvo una sola densidad no se notaba, pero desde que conviven
                  la cadena contable (un punto por cierre de mes) y las mediciones
                  (uno por día), diez meses de historia entraban en la quinta parte
                  del ancho — medido acá: 17,6 veces más apretado del lado izquierdo
                  que del derecho. La parte contable se leía como un pico casi
                  vertical que nunca ocurrió.
                  El instante de cada fila lo pone `rellenarTimestamps` (`ts`), que
                  también le da lugar a las filas de CORTE — las que van vacías para
                  que quede el hueco a la vista donde cambia la regla de valuación. */}
              <XAxis dataKey="ts" type="number" scale="time" domain={['dataMin', 'dataMax']}
                     tickFormatter={fmtMarcaEje}
                     tick={{ fill: '#7C8698', fontSize: 12 }} axisLine={false} tickLine={false} minTickGap={40} dy={4} />
              <YAxis tick={{ fill: '#7C8698', fontSize: 12 }} axisLine={false} tickLine={false} tickFormatter={v => `${v > 0 ? '+' : ''}${v}%`} width={44} />
              <ReferenceLine y={0} stroke="#3A4256" strokeOpacity={0.5} strokeDasharray="2 4" />
              <Tooltip
                contentStyle={{ background: '#10151F', border: '1px solid #262E40', borderRadius: 12, fontSize: 12.5, padding: '10px 14px', boxShadow: '0 12px 32px -12px rgba(0,0,0,.6)' }}
                labelStyle={{ color: '#E6EAF2', fontSize: 12, fontWeight: 600, marginBottom: 4 }}
                formatter={(v) => [v != null ? `${v > 0 ? '+' : ''}${v.toFixed(1)}%` : '—', '']}
                // Con el eje en tiempo el `label` que recibe el tooltip es el
                // timestamp. El encabezado sigue siendo el rótulo de la fila —el
                // mismo texto que mostraba antes—, no el número.
                labelFormatter={(t, payload) => {
                  const row = payload && payload[0] && payload[0].payload
                  if (row) return (resolucionChart === 'diaria' ? row.labelDia : row.label) ?? fmtMarcaEje(t)
                  return fmtMarcaEje(t)
                }}
              />
              {/* Las dos series de la cartera comparten color; el ícono de la
                  leyenda es el mismo punto verde para las dos. El texto dice cuál
                  es la punteada, que es lo único que las distingue a simple vista. */}
              <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12.5, paddingTop: 8 }}
                      formatter={(v) => v === `${userName} estimado` ? `${v} (línea punteada)` : v} />
              <Area type="monotone" dataKey={claveCartera} stroke="#21D07A" strokeWidth={2.5} fill="url(#portGrad)" dot={<DotSolo fill="#21D07A" />} activeDot={{ r: 4 }} />
              {/* Lo NO medido: misma curva, punteada y en un tono apagado. Es lo
                  que comunica "esta parte es estimada" sin esconderla. */}
              <Line type="monotone" dataKey={`${userName} estimado`} stroke="#21D07A" strokeOpacity={0.55} strokeWidth={2} strokeDasharray="3 4" dot={<DotSolo fill="#21D07A" opacity={0.55} />} />
              {/* ⚠️ EN ESTIMADO ESTA SEGUNDA LÍNEA SE OCULTA, y es la respuesta a
                  "¿sigue teniendo sentido o es redundante?".
                  En CERTERO las dos dicen cosas distintas: la verde es la cartera
                  TOTAL (lo cerrado + lo abierto) y la amarilla sólo lo COBRADO.
                  En ESTIMADO la verde ya no tiene "lo abierto" —`pnl_unrealized = 0`
                  en toda la cadena—, así que las dos son realizado, y quedaban en
                  la leyenda como "P/L vendido" y "P/L realizado": dos sinónimos,
                  que es una versión chica del mismo problema de rótulo.
                  Medí que numéricamente NO son idénticas (difieren hasta 69px en el
                  trazado, porque una encadena Modified Dietz y la otra es un
                  cociente sobre el capital) — pero esa diferencia es metodológica,
                  no información sobre la plata del usuario. Dos curvas casi iguales
                  con nombres sinónimos confunden más de lo que aportan. */}
              {!_perfContable && (
                <Line type="monotone" dataKey={`${userName} P/L realizado`} stroke="#E8B14A" strokeWidth={1.5} strokeDasharray="2 5" dot={false} />
              )}
              <Line type="monotone" dataKey={benchmarkKey} stroke={currency === 'USD' ? '#46C6E0' : '#8B7DFF'} strokeWidth={1.75} strokeDasharray="5 5" dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
      </AskAIAbout>

      {currency === 'USD' && contableSeries.length >= 2 && (
        <div className="bg-white dark:bg-bg-1 border border-line rounded-xl p-5 mt-6">
          <div className="flex items-center gap-1.5 mb-1">
            <h2 className="font-semibold text-ink-0">Reconstrucción contable</h2>
            <InfoTooltip>
              <p className="font-semibold text-ink-0">Qué es esta banda</p>
              <p>La parte de tu historia que no tiene precio de mercado: se arma con
                 lo que aportaste más lo que ya vendiste. No es necesariamente el
                 principio — puede haber tramos así en el medio, cuando el precio de
                 esos días no se pudo reconstruir.</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Por qué va aparte</p>
              <p>No baja cuando baja el mercado, así que da más alto que el valor
                 real. Mezclarla con la línea medida ponía un máximo que nunca
                 existió, y todo lo que viniera después parecía una caída.</p>
              <p className="text-ink-3">Por eso se dibuja en su propio eje, en
                 dólares, y nunca cuenta como pico ni entra en el % acumulado.</p>
            </InfoTooltip>
          </div>
          <p className="text-xs text-ink-3 mb-4">
            Los tramos de tu historia sin precio de mercado. Es contabilidad, no
            mercado — mirala como referencia, no como rendimiento.
          </p>
          <ResponsiveContainer width="100%" height={160}>
            <ComposedChart data={contableSeries} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#1B2230" strokeOpacity={0.35} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#7C8698', fontSize: 12 }} axisLine={false} tickLine={false} minTickGap={40} dy={4} />
              <YAxis tick={{ fill: '#7C8698', fontSize: 12 }} axisLine={false} tickLine={false} width={56}
                     tickFormatter={v => `US$${Math.round(v / 1000)}k`} />
              <Tooltip
                contentStyle={{ background: '#10151F', border: '1px solid #262E40', borderRadius: 12, fontSize: 12.5, padding: '10px 14px' }}
                labelStyle={{ color: '#E6EAF2', fontSize: 12, fontWeight: 600, marginBottom: 4 }}
                formatter={(v) => [`US$${Number(v).toLocaleString('es-AR', { maximumFractionDigits: 0 })}`, 'Reconstrucción contable']}
              />
              <Line type="monotone" dataKey="usd" name="Reconstrucción contable"
                    stroke="#7C8698" strokeWidth={1.75} strokeDasharray="4 4" dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Drawdown curve (underwater chart) — visualiza la profundidad
          y duración de las caídas sobre el rendimiento ajustado por flujos.
          El motor la suprime sin ≥2 meses de serie (no placeholder). */}
      {showDrawdown && (
      <AskAIAbout
        topic="insights.drawdown"
        params={{ window_days: 365 }}
        subtitle="Drawdown de la cartera"
      >
      <div className="bg-white dark:bg-bg-1 border border-line rounded-xl p-5 mt-6">
        <div className="flex items-start justify-between gap-2 mb-1 flex-wrap">
          <div className="flex items-center gap-1.5">
            <h2 className="font-semibold text-ink-0">Curva de drawdown</h2>
            {/* Explica sólo cuando el de Performance no está — en pesos, donde éste
                es el único chip de la pantalla. En USD son dos y la frase va arriba. */}
            <ChipMedido explica={!chipPerfVisible} />
            <InfoTooltip>
              <p className="font-semibold text-ink-0">Qué es</p>
              <p>Cuánto bajaste desde tu mejor momento histórico. Si llegaste a +20% y ahora estás en +10%, tu drawdown es −10%.</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="font-semibold text-ink-0">Cómo leerlo</p>
              <p><span className="text-ink-1">0%</span>: estás en tu máximo histórico.</p>
              <p><span className="text-rendi-warn">−10%</span>: caíste 10% desde el pico.</p>
              <p><span className="text-rendi-neg">&lt; −25%</span>: drawdown serio — recuperar +25% requiere +33% de retorno.</p>
              <div className="border-t border-line/60 my-1.5" />
              <p className="text-ink-3">Calculado sobre el rendimiento ajustado por flujos (TWRR) — depósitos y retiros no se cuentan como subida/bajada de la cartera.</p>
            </InfoTooltip>
          </div>
          {drawdown && (
            <div className="flex gap-3 text-xs">
              <span className="text-ink-3">Actual: <span className={`font-semibold tabular ${drawdown.current < -5 ? 'text-rendi-neg' : 'text-rendi-pos'}`}>{drawdown.current.toFixed(1)}%</span></span>
              <span className="text-ink-3">Máx histórico: <span className="font-semibold tabular text-rendi-neg">{drawdown.max.toFixed(1)}%</span></span>
            </div>
          )}
        </div>
        <p className="text-xs text-ink-3 mb-4">Profundidad y duración de las caídas. El área negativa representa los períodos por debajo del máximo histórico.</p>
        {drawdownSeries.length < 2 ? (
          <SinMediciones />
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={drawdownSeries} margin={{ top: 10, right: 10, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%"  stopColor="#FF5360" stopOpacity={0} />
                  <stop offset="100%" stopColor="#FF5360" stopOpacity={0.35} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#1B2230" strokeOpacity={0.35} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: '#7C8698', fontSize: 12 }} axisLine={false} tickLine={false} minTickGap={40} dy={4} />
              <YAxis tick={{ fill: '#7C8698', fontSize: 12 }} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} domain={['auto', 0]} width={44} />
              <ReferenceLine y={0} stroke="#3A4256" strokeOpacity={0.5} />
              <Tooltip
                contentStyle={{ background: '#10151F', border: '1px solid #262E40', borderRadius: 12, fontSize: 12.5, padding: '10px 14px', boxShadow: '0 12px 32px -12px rgba(0,0,0,.6)' }}
                labelStyle={{ color: '#E6EAF2', fontSize: 12, fontWeight: 600, marginBottom: 4 }}
                formatter={(v) => [`${v.toFixed(2)}%`, 'Drawdown']}
              />
              <Area type="monotone" dataKey="ddPct" stroke="#FF5360" strokeWidth={2} fill="url(#ddGrad)" dot={false} activeDot={{ r: 4 }} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
      </AskAIAbout>
      )}

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

      {/* ── Atribución por activo — qué explica tu P&L (cerradas + abiertas) ── */}
      {(topContribPos.length > 0 || topContribNeg.length > 0) && (
        <Section
          id="atribucion"
          title="Atribución por activo"
          subtitle={`Activos que más impactan tu P&L total — cerradas + abiertas, en ${currency}.`}
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <ContribList tone="positive" title="A favor" items={topContribPos} fmt={amt} />
            <ContribList tone="negative" title="En contra" items={topContribNeg} fmt={amt} />
          </div>
        </Section>
      )}

      {/* ── Distribución por broker — solo con ≥2 brokers (si no, es una torta
          de una sola porción que no aporta). ─────────────────────────────── */}
      {pieData.length >= 2 && (
        <Section title="Distribución por broker" subtitle="Cómo se reparte tu capital entre brokers.">
          <div className="bg-white dark:bg-bg-1 border border-line rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-ink-0">Por broker</h2>
              {brokerConcentration && (
                <span className="text-xs text-ink-3">
                  Top: <span className="font-medium text-ink-1">{brokerConcentration.top.name}</span> ({brokerConcentration.top.sharePct.toFixed(0)}%)
                </span>
              )}
            </div>
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
          </div>
        </Section>
      )}


      {/* Cierro el bloque "Diagnóstico". La ex-sección "Métricas Pro" se
          fusionó como generadores de diagnóstico (ver utils/diagnostics.js),
          por eso ya no hay un bloque separado acá abajo. */}
      </>)}


      {/* ══════════════════════════════════════════════════════════════════════
          PERFIL DEL INVERSOR — cruza el test (perfil declarado) con la cartera
          real. Solo descriptivo: presenta el dato, no juzga. Si el user no
          completó el test → CTA al test (lo muestra ProfileInvestorBlock).
          ──
          Restructure 2026-05-27: esta sección ahora se muestra en la tab
          "Perfil del inversor" de /analisis. El tab muestra el test arriba
          (input) y estas cards abajo (output). FUERA del wrap `showDiagnostico`
          porque en tab 'perfil' showDiagnostico=false pero showPerfil=true.
          ══════════════════════════════════════════════════════════════════════ */}
      {showPerfil && (
      <Section
        title={_embeddedTab === 'perfil' ? 'Diagnóstico vs. perfil declarado' : 'Perfil de inversor'}
        subtitle="Cómo se alinea tu cartera real con lo que declaraste en el test."
      >
        {/* Lectura IA holística — solo si hay test hecho (si no, la CTA a
            completar el test la muestra el propio ProfileInvestorBlock). */}
        {investorProfile && Object.keys(investorProfile).length > 0 && (
          <ProfileSummaryBlock />
        )}
        <ProfileInvestorBlock
          allocationCard={allocationCard}
          objectiveCard={objectiveCard}
          horizonCard={horizonCard}
          drawdownCard={drawdownCard}
          concentrationCard={concentrationCard}
          styleCard={styleCard}
          liquidityCard={liquidityCard}
          returnExpectationCard={returnExpectationCard}
          positions={positionsWithValue}
        />
      </Section>
      )}


    </div>
  )
}

function BenchmarkCard({ label, hint, disabled, disabledHint, myValue, benchmarkValue, delta, amt }) {
  // Tarjeta de comparación contra un benchmark simulado.
  // Muestra: valor del benchmark, delta vs mi portfolio (USD y %).
  // Verde si gano al benchmark, rojo si pierdo.
  if (disabled || benchmarkValue == null || delta == null) {
    return (
      <div className="bg-white dark:bg-bg-1 border border-line rounded-xl p-5">
        <p className="text-xs font-semibold text-ink-3">{label}</p>
        <p className="text-sm text-ink-3 mt-2">{disabledHint || 'Datos insuficientes para calcular.'}</p>
      </div>
    )
  }
  const gano = delta.delta >= 0
  const accentBorder = gano ? 'border-rendi-pos/40' : 'border-rendi-neg/40'
  const accentText = gano ? 'text-rendi-pos' : 'text-rendi-neg'
  return (
    <div className={`bg-white dark:bg-bg-2/60 border ${accentBorder} rounded-xl shadow-sm dark:shadow-none p-5`}>
      <p className="text-xs font-semibold text-ink-3">{label}</p>
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
      <div className="bg-white dark:bg-bg-1 border border-line rounded-xl p-5">
        <p className="text-xs font-semibold text-ink-3">Inflación AR</p>
        <p className="text-sm text-ink-3 mt-2">No hay datos de IPC suficientes para el período seleccionado.</p>
      </div>
    )
  }
  return (
    <div className="bg-white dark:bg-bg-1 border border-rendi-warn/30 rounded p-5">
      <p className="text-xs font-semibold text-ink-3">Inflación AR (período)</p>
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
    <div className="bg-white dark:bg-bg-1 border border-line rounded-xl p-5 mt-6">
      <div className="flex items-start justify-between gap-2 mb-1 flex-wrap">
        <div className="flex items-center gap-1.5">
          <h2 className="font-semibold text-ink-0">Atribución del crecimiento</h2>
          <InfoTooltip>
            <p className="font-semibold text-ink-0">Cómo se calcula</p>
            <p>La cartera crece o decrece por dos vías: <span className="font-medium">aportes netos</span> (depósitos menos retiros) y <span className="font-medium">rendimiento del mercado</span> (P&L mensual).</p>
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
          ? 'La cartera creció principalmente por nuevos aportes, no por rendimiento. La rentabilidad real depende de lo que genere el capital ya invertido.'
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
    <div className="bg-white dark:bg-bg-1 border border-line rounded-xl p-5">
      <div className="flex items-center gap-2 mb-3 text-ink-3">
        {isPos ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
        <span className="text-xs font-semibold">{title}</span>
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

// Título corto de un item de diagnóstico para el preview colapsado del acordeón.
// Mismo parseo que DiagnosisCard/FeaturedFinding: quita markdown bold y toma la
// 1ª oración como título. Lo extraemos en un helper para reusarlo en el preview.
function diagnosisShortTitle(d) {
  const plain = (d.text || '').replace(/\*\*/g, '')
  const parts = plain.split(/\.\s+/)
  return parts[0] + (parts.length > 1 ? '.' : '')
}

// ─── DiagnosisSection — Diagnóstico como grilla 3×3 adaptativa ───────────────
// 1 hallazgo DESTACADO arriba ("Lo que más importa") + grilla 3×3 por SEVERIDAD
// (3 atención · 3 diagnóstico · 3 positivo), todo abierto, con "No me interesa"
// por card (reemplazo por-slot + ciclo, ver utils/diagnosticsRotation.js).
//
// El array `diagnosis` ya viene priorizado desde selectDiagnostics():
// SEVERITY_RANK = urgent(0) < warn(1) < positive(2) < info(3), tie-break estable
// por día → diagnosis[0] es el de mayor prioridad. El destacado es el primer
// urgent/warn (o diagnosis[0] si no hay atención); se EXCLUYE de la grilla.
//
// Gating (monetización): TODOS los tiers ven la grilla completa. El gancho a
// Plus ya no es "cuántos diagnósticos ves" sino "cuántas veces personalizás":
// el "No me interesa" tiene cuota semanal (Free 2/sem, server-side; plus/pro/
// admin ilimitado). Al agotarla, el dismiss abre el UpgradeModal a Plus.
// Persistencia del "no me interesa" — en localStorage guardamos DOS cosas por
// user: (1) `dismissed`, el Set de ids que el user marcó como "no me interesa"
// (skip-list para elegir reemplazos); (2) `slots`, las ids VISIBLES por tier en
// orden — así al descartar UNA tile reemplazamos sólo ESA (identidad de slot
// estable) y en un refresh se ven las mismas 3. Al agotar un tier, se resetean
// SOLO sus ids descartadas (cicla y vuelve a la primera).
const DIAG_DISMISS_PREFIX = 'rendi_diag_dismissed_'
function readDiagState(key) {
  try {
    const raw = localStorage.getItem(DIAG_DISMISS_PREFIX + key)
    if (!raw) return { dismissed: new Set(), slots: {} }
    const parsed = JSON.parse(raw)
    // Formato viejo: array plano de ids descartadas (sin slots).
    if (Array.isArray(parsed)) return { dismissed: new Set(parsed), slots: {} }
    return { dismissed: new Set(parsed.dismissed || []), slots: parsed.slots || {} }
  } catch { return { dismissed: new Set(), slots: {} } }
}
function writeDiagState(key, dismissed, slots) {
  try {
    localStorage.setItem(DIAG_DISMISS_PREFIX + key, JSON.stringify({ dismissed: [...dismissed], slots }))
  } catch { /* modo privado */ }
}
// resolveTierShown / computeDismiss viven en utils/diagnosticsRotation.js (puros
// + testeados). Acá sólo los conectamos al estado del componente.

// Tiers de display por SEVERIDAD (no por categoría): la card ya muestra su badge.
const DIAG_TIERS = [
  { key: 'atencion',    match: d => d.severity === 'urgent' || d.severity === 'warn' },
  { key: 'diagnostico', match: d => d.severity === 'info' },
  { key: 'positivo',    match: d => d.severity === 'positive' },
]

function DiagnosisSection({ diagnosis, plan, userKey = 'anon' }) {
  // state ({dismissed, slots}) + collapsed ANTES de cualquier early return
  // (Rules of Hooks). `slots` = ids visibles por tier → reemplazo por-slot estable.
  const [state, setState] = useState(() => readDiagState(userKey))
  const { dismissed, slots } = state
  const [collapsed, setCollapsed] = useState(false)  // abierto por defecto
  // Cuota semanal del "No me interesa" (solo Free). ddUsage = usage del backend
  // para el hint "N/2 esta semana"; upsell = payload del 429 → UpgradeModal.
  const [ddUsage, setDdUsage] = useState(null)
  const [upsell, setUpsell] = useState(null)
  const inflightRef = useRef(new Set())  // ids con un POST de dismiss en vuelo (anti doble-click)
  const isFree = !!plan.isFree

  // Free: traer el uso una vez al montar para mostrar el contador restante.
  useEffect(() => {
    if (!isFree) return
    let alive = true
    api.get('/ai/usage')
      .then(u => { if (alive) setDdUsage(u) })
      .catch(() => {})  // el hint es opcional; si falla, no se muestra
    return () => { alive = false }
  }, [isFree])

  if (!diagnosis || diagnosis.length === 0) return null

  // Todos los tiers ven la grilla 3×3 completa (antes era Pro/Admin only). El
  // gancho a Plus ya no es "cuántos diagnósticos ves" sino "cuántas veces podés
  // personalizarla con No me interesa" (Free 2/sem, Plus+ ilimitado).

  // Hallazgo destacado: primer urgent/warn; si no hay, el primero del pool. NO
  // debería ser una métrica bloqueada (teaser) → preferimos un hallazgo real.
  const featured = diagnosis.find(d => (d.severity === 'urgent' || d.severity === 'warn') && !d.locked)
    || diagnosis.find(d => !d.locked)
    || diagnosis[0]
  const rest = diagnosis.filter(d => d.id !== featured.id)

  // ── Grilla 3×3 ADAPTATIVA — 3 atención · 3 diagnóstico · 3 positivo, todo
  // junto y abierto. "No me interesa" descarta y trae otra del mismo tier; al
  // agotar el tier, vuelve a la primera (cicla). ────────────────────────────
  // applyDismiss: la rotación LOCAL (reemplaza SOLO la tile tocada; los otros 2
  // slots quedan intactos). `rest` es puro de props → seguro en el updater.
  const applyDismiss = (tierKey, id) => {
    setState(prev => {
      const tier = DIAG_TIERS.find(t => t.key === tierKey)
      const pool = rest.filter(tier.match)
      const poolIds = pool.map(d => d.id)
      const current = resolveTierShown(pool, poolIds, prev.slots[tierKey], prev.dismissed)
      const { nextShown, nextDismissed } = computeDismiss(pool, poolIds, current, id, prev.dismissed)
      if (nextShown === current && nextDismissed === prev.dismissed) return prev  // no-op
      const nextSlots = { ...prev.slots, [tierKey]: nextShown }
      writeDiagState(userKey, nextDismissed, nextSlots)
      return { dismissed: nextDismissed, slots: nextSlots }
    })
  }

  // dismiss: para Free, descuenta la cuota semanal server-side ANTES de rotar.
  //  - 200 → rota + actualiza el contador.
  //  - 429 de CUOTA (detail.error === 'diag_dismiss_quota_exceeded') → upsell a
  //    Plus (no rota).
  //  - 429 de rate-limit (detail string) → no rota, no modal (respeta el límite).
  //  - Error de red / 5xx → fail-open (rota igual, no castigamos por conexión).
  // Paid → rota directo (ilimitado, sin round-trip). Guard anti doble-click: un
  // 2º click sobre la MISMA tile mientras hay un POST en vuelo se ignora (si no,
  // gasta 2 de las 2 cuotas semanales por 1 sola rotación).
  const dismiss = async (tierKey, id) => {
    if (!isFree) { applyDismiss(tierKey, id); return }
    const key = `${tierKey}:${id}`
    if (inflightRef.current.has(key)) return
    inflightRef.current.add(key)
    try {
      const res = await api.post('/diagnostics/dismiss')  // { ok, usage }
      if (res?.usage) setDdUsage(res.usage)
      applyDismiss(tierKey, id)
    } catch (err) {
      const detail = err?.status === 429 ? err.payload?.detail : null
      if (detail && typeof detail === 'object' && detail.error === 'diag_dismiss_quota_exceeded') {
        if (detail.usage) setDdUsage(detail.usage)
        setUpsell(detail)
        track('feature_blocked_clicked', {
          feature: 'insights.diagnostic.dismiss', source: 'insights_diagnostic_dismiss',
        })
        // NO rota — la tile queda; el user ve el modal.
      } else if (err?.status === 429) {
        // rate-limit (u otro 429 sin payload de cuota) → no rota, no modal.
      } else {
        applyDismiss(tierKey, id)  // fail-open ante error de red / 5xx
      }
    } finally {
      inflightRef.current.delete(key)
    }
  }

  const tierRows = DIAG_TIERS.map(tier => {
    const pool = rest.filter(tier.match)          // candidatos del tier (sin el featured)
    if (pool.length === 0) return null
    const poolIds = pool.map(d => d.id)
    const byId = new Map(pool.map(d => [d.id, d]))
    const shown = resolveTierShown(pool, poolIds, slots[tier.key], dismissed)
      .map(sid => byId.get(sid)).filter(Boolean)
    // "No me interesa" solo si hay MÁS de 3 → hay un 4º real para traer.
    return { key: tier.key, shown, canRotate: pool.length > 3 }
  }).filter(Boolean)

  if (tierRows.length === 0) {
    return (
      <section id="diagnostico" className="scroll-mt-20 space-y-4">
        <FeaturedFinding d={featured} />
      </section>
    )
  }

  return (
    <section id="diagnostico" className="scroll-mt-20 space-y-4">
      <FeaturedFinding d={featured} />
      <div className="border border-line/70 dark:border-line rounded-lg bg-white/40 dark:bg-bg-1/40 overflow-hidden">
        <button
          type="button"
          onClick={() => setCollapsed(c => !c)}
          aria-expanded={!collapsed}
          className="w-full flex items-center justify-between gap-3 px-4 py-3.5 text-left group cursor-pointer hover:bg-bg-2/60 dark:hover:bg-bg-2/30 transition-colors"
        >
          <h3 className="font-semibold text-ink-0 group-hover:text-rendi-accent transition-colors">Diagnóstico de tu cartera</h3>
          <span className="flex items-center gap-1.5 text-xs text-ink-2">
            {collapsed ? 'Ver' : 'Ocultar'}
            {collapsed ? <ChevronDown size={16} strokeWidth={2} /> : <ChevronUp size={16} strokeWidth={2} />}
          </span>
        </button>
        {!collapsed && (
          <div className="px-4 pb-4 space-y-4">
            {/* Hint de cuota (solo Free): cuántas personalizaciones usó esta
                semana + gancho a Plus. Solo si hay algún tier rotable (botón). */}
            {isFree && ddUsage?.diag_dismiss_limit != null && tierRows.some(r => r.canRotate) && (
              <p className="text-xs text-ink-3">
                Usaste <span className="text-ink-1 font-medium">{ddUsage.diag_dismiss_count}/{ddUsage.diag_dismiss_limit}</span> personalizaciones (“No me interesa”) esta semana.{' '}
                <Link to="/planes" className="text-rendi-accent hover:underline">Con Plus, sin límite.</Link>
              </p>
            )}
            {tierRows.map(row => (
              <div key={row.key} className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {row.shown.map(d => (
                  <DiagnosisCard
                    key={d.id}
                    d={d}
                    onDismiss={row.canRotate ? () => dismiss(row.key, d.id) : undefined}
                  />
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
      {upsell && (
        <UpgradeModal
          title="Personalizá tu diagnóstico sin límite"
          message={upsell.message}
          feature="insights.diagnostic.dismiss"
          source="insights_diagnostic_dismiss"
          benefits={upsell.upgrade?.benefits}
          onClose={() => setUpsell(null)}
        />
      )}
    </section>
  )
}


// FeaturedFinding — el hallazgo #1 ("Lo que más importa"), destacado con borde
// de realce + ícono de alerta. Reusa SEVERITY_BADGE/ctaForCategory/DiagnosticText
// del mismo patrón que DiagnosisCard, sin reescribir la card.
function FeaturedFinding({ d }) {
  const sev = SEVERITY_BADGE[d.severity] || SEVERITY_BADGE.info
  const cta = ctaForCategory(d.category)
  // Mismo parseo que DiagnosisCard: 1ª oración = título, resto = contexto.
  const plainText = (d.text || '').replace(/\*\*/g, '')
  const parts = plainText.split(/\.\s+/)
  const title = parts[0] + (parts.length > 1 ? '.' : '')
  const context = parts.slice(1).join('. ').trim()
  // Tono del realce según severidad: rojo si es riesgo alto, ámbar para el
  // resto (lo destacado casi siempre es atención). Verde solo si no hubiera
  // ningún hallazgo de atención y caímos a un positivo.
  const tone = d.severity === 'urgent'
    ? 'border-rendi-neg/40 bg-rendi-neg/[0.05] dark:bg-rendi-neg/[0.07] text-rendi-neg'
    : d.severity === 'positive'
    ? 'border-rendi-pos/40 bg-rendi-pos/[0.05] dark:bg-rendi-pos/[0.07] text-rendi-pos'
    : 'border-rendi-warn/40 bg-rendi-warn/[0.05] dark:bg-rendi-warn/[0.07] text-rendi-warn'
  const HeroIcon = d.severity === 'positive' ? Sparkles : AlertTriangle
  return (
    <div>
      <p className="eyebrow mb-3">Lo que más importa</p>
      <div className={`rounded-lg border p-5 ${tone}`}>
        <div className="flex items-center gap-2 mb-3">
          <HeroIcon size={16} strokeWidth={2} className="flex-shrink-0" />
          <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${sev.badgeCls}`}>
            {sev.label}
          </span>
        </div>
        <p className="text-base font-semibold leading-snug text-ink-0">
          <DiagnosticText text={title} />
        </p>
        {context && (
          <p className="text-sm text-ink-2 mt-1.5 leading-relaxed max-w-2xl">
            <DiagnosticText text={context} />
          </p>
        )}
        {cta && (
          cta.href.startsWith('#') ? (
            <a href={cta.href} className="inline-flex items-center gap-1.5 mt-4 text-sm font-semibold text-rendi-accent hover:underline">
              {cta.label} <ArrowRight size={14} strokeWidth={2} />
            </a>
          ) : (
            <Link to={cta.href} className="inline-flex items-center gap-1.5 mt-4 text-sm font-semibold text-rendi-accent hover:underline">
              {cta.label} <ArrowRight size={14} strokeWidth={2} />
            </Link>
          )
        )}
      </div>
    </div>
  )
}

function DiagnosisCard({ d, onDismiss }) {
  const sev = SEVERITY_BADGE[d.severity] || SEVERITY_BADGE.info
  // Botón "No me interesa" — compartido entre la card normal y la bloqueada.
  const dismissBtn = onDismiss ? (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); e.preventDefault(); onDismiss() }}
      className="self-start inline-flex items-center gap-1 max-w-[calc(100%_-_1.5rem)] mb-2.5 text-[10px] font-medium leading-tight px-2 py-0.5 rounded-sm border border-rendi-accent/30 bg-rendi-accent/10 text-[#1857B8] dark:text-rendi-accent hover:bg-rendi-accent/20 hover:border-rendi-accent/50 transition-colors"
      title="Ocultar este análisis y mostrar otro del mismo tipo"
    >
      <X size={11} strokeWidth={2.25} aria-hidden="true" className="flex-shrink-0" /> No me interesa
    </button>
  ) : null

  // Métrica bloqueada (Free): mostramos el TÍTULO + "desbloqueá con Plus", SIN el
  // valor → teaser de conversión. Sigue siendo descartable ("No me interesa").
  if (d.locked) {
    return (
      <div className="bg-white dark:bg-bg-1 p-5 flex flex-col h-full">
        {dismissBtn}
        <div className="flex items-center gap-2 mb-3">
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full border border-data-violet/30 bg-data-violet/10 text-data-violet">
            <Lock size={9} strokeWidth={2.5} aria-hidden="true" /> Métrica · Plus
          </span>
        </div>
        <p className="text-sm font-medium leading-snug text-ink-0 mb-2">{d.lockedLabel}</p>
        <p className="text-xs text-ink-2 leading-relaxed flex-1">
          Métrica de riesgo avanzada. Desbloqueala con Plus para ver el valor y qué significa para tu cartera.
        </p>
        <div className="mt-4">
          <Link
            to="/planes"
            onClick={() => track('feature_blocked_clicked', { feature: 'insights.metric.locked', source: 'insights_metric_locked' })}
            className="inline-flex items-center gap-1 text-xs font-medium text-data-violet hover:underline"
          >
            Desbloqueá con Plus <ArrowRight size={11} strokeWidth={1.75} />
          </Link>
        </div>
      </div>
    )
  }

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
        {/* "No me interesa" ARRIBA del badge (dismissBtn compartido). En su
            propia fila no compite por ancho con el badge ni se corta en cards
            angostas; reserva la banda del ✦ flotante con max-width. */}
        {dismissBtn}
        <div className="flex items-center gap-2 mb-3">
          <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${sev.badgeCls}`}>
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
          <div className="mt-4 flex items-center">
            {cta.href.startsWith('#') ? (
              <a href={cta.href} className="inline-flex items-center gap-1 text-xs text-rendi-accent hover:underline">
                {cta.label} <ArrowRight size={11} strokeWidth={1.75} />
              </a>
            ) : (
              <Link to={cta.href} className="inline-flex items-center gap-1 text-xs text-rendi-accent hover:underline">
                {cta.label} <ArrowRight size={11} strokeWidth={1.75} />
              </Link>
            )}
          </div>
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
          <span className={`inline-block text-[12.5px] font-semibold tracking-[0.1em] px-1.5 py-0.5 rounded border mr-2 align-middle ${s.badge}`}>
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
        <span className="text-xs font-medium flex-1">{title}</span>
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
  styleCard, liquidityCard, returnExpectationCard, positions = [],
}) {
  // Si las cards basadas en perfil NO tienen perfil utilizable, mostramos
  // un CTA único en vez de 9 módulos bloqueados.
  const noProfileAtAll =
    (allocationCard?.status === 'no_profile' || allocationCard?.status === 'no_data') &&
    (objectiveCard?.status === 'no_profile' || objectiveCard?.status === 'no_data') &&
    (horizonCard?.status === 'no_profile' || horizonCard?.status === 'no_data')

  if (noProfileAtAll) {
    // Empty state cuando el user no completó el test. El test se migró a
    // Configuración › Test de inversor (2026-07-14) — ya no vive en esta
    // página —, así que el CTA linkea allá.
    return (
      <div className="bg-white dark:bg-bg-1 border border-line/80 dark:border-line rounded p-6 flex flex-col items-start gap-3">
        <div className="flex items-center gap-2 text-ink-3">
          <UserRound size={18} />
          <span className="text-xs font-medium">Completá tu test de inversor</span>
        </div>
        <p className="text-sm text-ink-1 leading-snug max-w-xl">
          El test de inversor define tu perfil (conservador / moderado / agresivo)
          y nos permite mostrarte acá cómo se alinea tu cartera real con lo que declarás.
        </p>
        <Link
          to="/config?tab=test"
          className="inline-flex items-center gap-1.5 text-xs font-medium bg-data-violet/15 hover:bg-data-violet/25 text-data-violet border border-data-violet/40 rounded-sm px-3 py-2 transition-colors"
        >
          Completar test de inversor →
        </Link>
      </div>
    )
  }

  // ── Tablero adaptativo (2026-07-15) ─────────────────────────────────────
  // Reemplaza al featured-hero + acordeón: los 9 cruces como módulos VISUALES
  // ordenados por relevancia (motor determinístico en utils/profileDashboard).
  // Cada usuario ve primero lo que más le importa; lo que no tiene data queda
  // bloqueado con su cómo-desbloquearlo. La lectura IA vive arriba de este
  // bloque (ProfileSummaryBlock) y narra sobre estos mismos números.
  return (
    <ProfileDashboard
      cards={{
        allocation: allocationCard,
        objective: objectiveCard,
        horizon: horizonCard,
        drawdown: drawdownCard,
        concentration: concentrationCard,
        style: styleCard,
        liquidity: liquidityCard,
        return_exp: returnExpectationCard,
      }}
      positions={positions}
    />
  )
}


// AccordionSection — header clickeable (título + count + preview + acción + chevron)
// con contenido colapsable. Reusable para las secciones de divulgación
// progresiva del perfil del inversor Y del diagnóstico. El contenido se desmonta
// al colapsar (mismo patrón que CollapsibleSection) — evita render de cards no
// visibles.
//
// Affordance de "clickeable" (2026-06-13): colapsadas, estas secciones parecían
// títulos estáticos. Para que el header "pida" el click y no sea un blind box:
//   • cursor-pointer + hover state visible en TODO el header (bg + borde acento).
//   • Una etiqueta de acción explícita "Ver" (colapsada) → "Ocultar" (abierta)
//     junto al chevron, que se lee como acción y no como decoración.
//   • Preview del contenido cuando está COLAPSADA, para sacar el "blind box":
//     - `previewItems` (array de strings) → renderiza los títulos de las cards
//       unidos con " · ", truncado a 1 línea (caso Diagnóstico).
//     - `summary` (string) → mini-resumen pre-armado por el caller (caso Perfil,
//       que ya trae "N de M alineadas"). Si vienen ambos, gana `summary` para no
//       recargar el header del Perfil.
//   El preview/summary se oculta al expandir (ya se ve el contenido real).
function AccordionSection({ title, count, summary, previewItems, open, onToggle, children }) {
  // Preview colapsado: preferimos el `summary` pre-armado (Perfil); si no hay,
  // derivamos un preview de los títulos de los items (Diagnóstico). Cortamos a
  // ~3 títulos + "…" para que entre en una sola línea.
  const previewText = summary || (
    Array.isArray(previewItems) && previewItems.length
      ? previewItems.slice(0, 3).join(' · ') + (previewItems.length > 3 ? '…' : '')
      : null
  )
  return (
    <section className="border border-line/70 dark:border-line rounded-lg overflow-hidden bg-white/40 dark:bg-bg-1/40 transition-colors hover:border-rendi-accent/40">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center justify-between gap-3 px-4 py-3.5 text-left group cursor-pointer hover:bg-bg-2/60 dark:hover:bg-bg-2/30 transition-colors"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5 min-w-0 flex-wrap">
            <h3 className="font-semibold text-ink-0 group-hover:text-rendi-accent transition-colors">{title}</h3>
            {count != null && (
              <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-bg-2 dark:bg-bg-2/60 text-ink-2">
                {count}
              </span>
            )}
          </div>
          {/* Preview SOLO colapsado: títulos de items (Diagnóstico) o mini-resumen (Perfil). */}
          {previewText && !open && (
            <p className="text-ink-3 text-xs truncate mt-1">{previewText}</p>
          )}
        </div>
        {/* Acción explícita "Ver/Ocultar" + chevron — se lee como botón. */}
        <span className="flex-shrink-0 flex items-center gap-1.5 text-ink-3 group-hover:text-rendi-accent transition-colors">
          <span className="text-xs font-semibold">{open ? 'Ocultar' : 'Ver'}</span>
          {open ? <ChevronUp size={18} strokeWidth={2.25} /> : <ChevronDown size={18} strokeWidth={2.25} />}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-4 pt-1">
          {children}
        </div>
      )}
    </section>
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
// Card: Expectativa de retorno declarada vs retorno real (neto de inflación).
function ProfileReturnExpectationCard({ data }) {
  if (!data || data.status !== 'ready') return null
  const { realReturnPct, portfolioReturnPct, inflationPct, monthsCounted } = data.actual
  const realPos = realReturnPct >= 0
  const verdictText = data.comparison === 'above'
    ? 'Tu retorno real va por encima de esa expectativa.'
    : data.comparison === 'in_line'
      ? 'Tu retorno real va en línea con esa expectativa.'
      : 'Por ahora tu retorno real está por debajo de esa expectativa.'
  const tooltip = (
    <>
      <p className="font-semibold text-ink-0">Cómo se calcula</p>
      <p>El test pregunta qué esperás que rinda tu plata (preservar / ganarle a la inflación / crecer / maximizar). Lo cruzamos con tu retorno REAL: el rendimiento de tu cartera en pesos (TWR) neto de la inflación INDEC, sobre la misma ventana de meses.</p>
      <p className="text-ink-3">La vara de cada expectativa (retorno real orientativo) es heurística — no es un objetivo prometido ni un pronóstico.</p>
    </>
  )
  return (
    <InsightCard icon={<Target size={18} />} title="Retorno esperado vs real" tooltip={tooltip}>
      <p className="text-sm text-ink-1 leading-snug">
        Buscás <span className="font-semibold text-ink-0">{data.declared.expectationLabel}</span>.
      </p>
      <div className="mt-3 flex items-baseline gap-3">
        <p className={`text-2xl font-bold tabular ${realPos ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
          {realReturnPct > 0 ? '+' : ''}{realReturnPct}%
        </p>
        <p className="text-xs text-ink-3">
          retorno real (neto de inflación){monthsCounted ? `, ${monthsCounted} meses` : ''}
        </p>
      </div>
      {portfolioReturnPct != null && inflationPct != null && (
        <p className="text-xs text-ink-3 mt-1 leading-snug tabular">
          Cartera {portfolioReturnPct > 0 ? '+' : ''}{portfolioReturnPct}% en pesos · Inflación {inflationPct}%
        </p>
      )}
      <p className="text-xs text-ink-2 mt-3 leading-snug">{verdictText}</p>
    </InsightCard>
  )
}


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
      <p>Suma del % que representan tus 3 activos más grandes (por valor en USD, agregando entre brokers) sobre el total de la cartera. Excluye cash.</p>
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


// ─── Card 6 (nueva 2026-05-27): Estilo declarado vs trade frequency real ──
// Cruza profile.style (passive/active/mixed) contra la cantidad de SELLs
// promedio por mes durante los últimos 6 meses. Usa rangos típicos.
function ProfileStyleCard({ data }) {
  if (!data || data.status === 'no_profile' || data.status === 'no_data') return null
  const tooltip = (
    <>
      <p className="font-semibold text-ink-0">Cómo se calcula</p>
      <p>Cuenta las operaciones cerradas (SELL) de los últimos 6 meses y calcula promedio por mes.</p>
      <p className="text-ink-3">Bandas de referencia: Pasivo (0-2 trades/mes), Mixto (3-8), Activo (9+).</p>
      <p className="text-ink-3">No incluye depósitos, retiros, dividendos ni compras — solo ventas (trades cerrados).</p>
    </>
  )

  return (
    <InsightCard
      icon={<Activity size={18} />}
      title="Estilo declarado vs actividad real"
      tooltip={tooltip}
    >
      <p className="text-sm text-ink-1 leading-snug">
        Declaraste estilo <span className="font-semibold text-ink-0">{data.declared.styleLabel}</span>{' '}
        (típico: {data.declared.typicalRange.min}
        {data.declared.typicalRange.max === Infinity ? '+' : `-${data.declared.typicalRange.max}`} trades/mes).
      </p>
      <div className="mt-3 flex items-baseline gap-3">
        <p className="text-2xl font-bold text-ink-0 tabular">
          {data.actual.tradesPerMonth}
          <span className="text-xs font-normal text-ink-3 ml-1">/mes</span>
        </p>
        <p className="text-xs text-ink-3">
          en los últimos {data.actual.monthsWindow} meses
        </p>
      </div>
      <p className="text-xs text-ink-2 mt-3 leading-snug">
        {data.comparison === 'aligned' ? (
          `Tu actividad real coincide con un estilo ${data.actual.inferredStyleLabel.toLowerCase()}.`
        ) : data.comparison === 'mismatch_more_active' ? (
          <>Tu actividad real es más cercana a{' '}
          <span className="font-medium text-ink-0">{data.actual.inferredStyleLabel}</span> que a lo declarado. Estás operando más de lo que tu perfil sugiere.</>
        ) : (
          <>Tu actividad real es más cercana a{' '}
          <span className="font-medium text-ink-0">{data.actual.inferredStyleLabel}</span> que a lo declarado. Estás operando menos de lo que tu perfil sugiere.</>
        )}
      </p>
    </InsightCard>
  )
}


// ─── Card 7 (nueva 2026-05-27): Liquidez declarada vs volatilidad real ────
// La card de mayor impacto educativo: si el user dijo que necesita la plata
// en 12-24 meses pero el grueso está en activos volátiles, está expuesto a
// vender en un drawdown. Lo dice de forma descriptiva, no alarmista.
function ProfileLiquidityCard({ data }) {
  if (!data || data.status === 'no_profile' || data.status === 'no_data') return null

  const tooltip = (
    <>
      <p className="font-semibold text-ink-0">Cómo se calcula</p>
      <p>Suma el % de tu cartera en activos "seguros" (cash + renta fija) vs "volátiles" (acciones, CEDEARs, ETFs, cripto).</p>
      <p className="text-ink-3">Cuanto más cerca necesites la plata, más conviene tener proporción en activos no volátiles para no tener que vender en un drawdown.</p>
      <p className="text-ink-3">Umbrales de referencia: si declarás "Sí" necesito en 2 años → ideal +70% en cash/RF. "Parcial" → +40%. "No" → cualquier mix funciona.</p>
    </>
  )

  return (
    <InsightCard
      icon={<Droplets size={18} />}
      title="Liquidez declarada vs cartera"
      tooltip={tooltip}
      accent={data.comparison === 'mismatch_severe'}
    >
      {data.status === 'no_portfolio' ? (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Declaraste: <span className="font-semibold text-ink-0">{data.declared.liquidityLabel}</span>.
            {data.declared.safeMinPct > 0 && (
              <> Recomendación de referencia: tener al menos{' '}
              <span className="text-ink-0 tabular">{data.declared.safeMinPct}%</span> en cash/RF.</>
            )}
          </p>
          <p className="text-xs text-ink-3 mt-3 leading-snug">
            Cargá posiciones para ver tu exposición real.
          </p>
        </>
      ) : (
        <>
          <p className="text-sm text-ink-1 leading-snug">
            Declaraste: <span className="font-semibold text-ink-0">{data.declared.liquidityLabel}</span>.
          </p>
          <div className="mt-3 flex items-baseline gap-3">
            <p className={`text-2xl font-bold tabular ${
              data.comparison === 'aligned' ? 'text-rendi-pos'
              : data.comparison === 'mismatch_risky' ? 'text-rendi-warn'
              : data.comparison === 'mismatch_severe' ? 'text-rendi-neg'
              : 'text-ink-0'
            }`}>
              {data.actual.safePct}%
            </p>
            <p className="text-xs text-ink-3">
              en cash + renta fija · <span className="tabular">{data.actual.volatilePct}%</span> en volátiles
            </p>
          </div>
          <p className="text-xs text-ink-2 mt-3 leading-snug">
            {data.comparison === 'aligned' && data.declared.liquidity === 'no' && (
              'Como no necesitás liquidez en el corto plazo, cualquier mix de cartera te sirve.'
            )}
            {data.comparison === 'aligned' && data.declared.liquidity !== 'no' && (
              `Tu mix actual te deja buffer suficiente si necesitás retirar parte de la plata en el plazo declarado.`
            )}
            {data.comparison === 'mismatch_risky' && (
              <>Tenés menos del recomendado (<span className="tabular">{data.declared.safeMinPct}%</span> en cash/RF) para cubrir la necesidad declarada. Una caída de mercado podría obligarte a vender activos volátiles en el peor momento.</>
            )}
            {data.comparison === 'mismatch_severe' && (
              <>Tu exposición a volatilidad es alta para una necesidad de liquidez en 12-24 meses. Si el mercado cae justo cuando necesitás retirar, estarías vendiendo al fondo.</>
            )}
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
        <span className="text-[13px] text-ink-2 font-medium">{label}</span>
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
