// useMonthlyData — fuente única para los reportes mensuales.
// ════════════════════════════════════════════════════════════════════════════
// Combina 3 fuentes para que la pantalla "Reportes mensuales" funcione tanto
// para usuarios que cerraron meses manualmente como para usuarios nuevos
// que solo importaron operaciones históricas:
//
//   1. monthly_entries WHERE broker='global'  — source of truth si existen
//   2. operations cerradas por mes            — derivamos pnl_realized
//   3. snapshots                              — sparkline por mes + valor
//      live del portfolio para alinear el YTD del año en curso
//      con el Dashboard (en lugar de quedarse en el último capital_final)
//
// Cada mes resultante lleva un campo `source`:
//   • 'manual'   — proviene de monthly_entries con capital_inicio + final
//   • 'derived'  — solo tenemos pnl_realized desde operations (mes parcial)
//   • 'partial'  — entry existe pero falta capital_inicio o final
//
// Output:
//   {
//     loading, error,
//     years: [
//       {
//         year, ytdUsd, ytdPct, startUsd, endUsd,
//         bestMonth, worstMonth,
//         months: [
//           { period, name, deltaUsd, deltaPct, startUsd, endUsd,
//             deposits, withdrawals, pnlRealized, pnlUnrealized,
//             source, status }
//         ]
//       },
//       ...
//     ],
//     hasAnyData: bool
//   }

import { useEffect, useMemo, useState } from 'react'
import { api } from '../utils/api'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'
import { computeBrokerValue, priceSymbol, isArUsdBroker, setBrokersRegistry } from '../utils/valuation'
import { computeBestWorstClosedOp } from '../utils/insightsModel'
import { esApto, esDibujable, baseIncomparable } from '../utils/evolution'

const MONTH_NAMES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                     'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

// Determinamos si una operación cuenta como trade cerrado (suma a pnl_realized).
// Espejo de la lógica que ya usa Insights.jsx para el cálculo de win rate.
function isTradeOp(op) {
  const t = (op.op_type || '').trim()
  if (!t) return false
  if (t === 'Dividendo' || t === 'Interés' || t === 'Compra') return false
  if (t.startsWith('CONVERSION') || t.startsWith('Conversión')) return false
  return true
}

// Status del mes en función del delta porcentual.
// Coincide con los buckets que usa el preview visual.
function statusFromPct(deltaPct) {
  if (deltaPct == null || isNaN(deltaPct)) return 'neutral'
  if (deltaPct >= 10)   return 'excellent'
  if (deltaPct >= 0.5)  return 'positive'
  if (deltaPct >= -0.5) return 'neutral'
  return 'difficult'
}

// Período YYYY-MM anterior (Enero → 'YYYY(prev)-12')
function prevPeriodOf(period) {
  const [y, m] = period.split('-').map(Number)
  if (m === 1) return `${y - 1}-12`
  return `${y}-${String(m - 1).padStart(2, '0')}`
}

/**
 * Calcula drivers del mes:
 *   • bestOp / worstOp     → mejor/peor operación cerrada del mes (asset + pnl_usd)
 *   • vsSp500              → diferencia entre rendimiento del mes y el del S&P 500
 *                            (en puntos porcentuales)
 *   • vsInflation          → idem vs inflación INDEC (solo si hay exposure ARS)
 *
 * @param {object} ctx
 *   monthOps: ops del mes ya filtradas por broker y período
 *   deltaPct: rendimiento del mes (en %)
 *   sp500Map: dict { 'YYYY-MM': close }
 *   inflationMap: dict { 'YYYY-MM': pct }
 *   period: 'YYYY-MM'
 *   showInflation: bool (si la cartera tiene exposure a ARS)
 */
function computeDriversForMonth({ monthOps, deltaPct, sp500Map, inflationMap, period, showInflation }) {
  // Mejor / peor operación cerrada del mes (solo trades, sin compras/dividendos/etc)
  const tradesInMonth = (monthOps || []).filter(isTradeOp).filter(o => o.pnl_usd != null)
  let bestOp = null, worstOp = null
  if (tradesInMonth.length > 0) {
    const bw = computeBestWorstClosedOp(tradesInMonth)
    if (bw) {
      // Pasamos los thresholds que ya usa el sistema en otras alertas:
      // ignoramos PNL muy chicos (≤ $1) para evitar ruido.
      if (bw.best.pnl_usd > 1) bestOp = { asset: bw.best.asset, pnl: bw.best.pnl_usd }
      if (bw.worst.pnl_usd < -1) worstOp = { asset: bw.worst.asset, pnl: bw.worst.pnl_usd }
    }
  }

  // S&P 500: (close_mes / close_mes_anterior - 1) * 100
  let vsSp500 = null
  if (sp500Map && deltaPct != null) {
    const curr = sp500Map[period]
    const prev = sp500Map[prevPeriodOf(period)]
    if (curr && prev) {
      const sp500Pct = ((curr / prev) - 1) * 100
      vsSp500 = deltaPct - sp500Pct
    }
  }

  // Inflación: el map ya viene como % del mes directamente.
  // Si showInflation === true pero el mes aún no tiene dato publicado
  // (lag típico INDEC ~14 días), devolvemos pending=true en lugar de
  // ocultar la fila — así el usuario entiende que la métrica existe pero
  // todavía no hay data oficial. Si showInflation === false (cartera sin
  // ARS), vsInflation queda null y la fila se oculta como hasta ahora.
  let vsInflation = null
  let vsInflationPending = false
  if (showInflation && deltaPct != null) {
    const inflPct = inflationMap?.[period]
    if (inflPct != null) {
      vsInflation = deltaPct - inflPct
    } else {
      vsInflationPending = true
    }
  }

  return { bestOp, worstOp, vsSp500, vsInflation, vsInflationPending }
}

/**
 * Hook principal del módulo de reportes mensuales.
 * Acepta un filtro por broker para que el usuario pueda alternar entre:
 *   • 'global'     → rollup de todos los brokers (default)
 *   • 'Binance'    → solo ese broker
 *   • 'Cocos'      → etc.
 *
 * Cuando el broker es individual, el cálculo del live value usa
 * computeBrokerValue (no el snapshot global). Snapshots solo se desglosan
 * por día a nivel portfolio, así que las sparklines por broker no son
 * posibles hoy — quedan ocultas (sprint aparte agrega snapshot_per_broker).
 */
export default function useMonthlyData({ broker = 'global' } = {}) {
  const { valuationDollar } = useCurrency()
  const [monthly, setMonthly] = useState([])
  const [operations, setOperations] = useState([])
  const [snapshots, setSnapshots] = useState([])
  // Para el live por broker
  const [positions, setPositions] = useState([])
  const [prices, setPrices] = useState({})
  const [brokers, setBrokers] = useState([])
  const [tcValuacion, setTcValuacion] = useState(1415)
  // dólar-MEP (la plata local) para valuar CEDEARs/acciones AR "· USD" en USD.
  const [tcCedear, setTcCedear] = useState(1415)
  // dólar-cripto: la cripto de un broker AR se valúa al MEP (~5% sobre spot).
  const [tcCripto, setTcCripto] = useState(null)
  // Benchmarks históricos (S&P 500 + inflación AR) para drivers por mes
  const [bench, setBench] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [mon, ops, snaps, pos, bkrs, cfg, dol, bnch] = await Promise.all([
          api.get('/monthly').catch(() => []),
          api.get('/operations').catch(() => []),
          // 3650 días = ~10 años. Necesitamos toda la historia para sparkline
          // por mes y para que el snapshot 'más reciente' siempre sea live.
          api.get('/snapshots?days=3650').catch(() => []),
          api.get('/positions').catch(() => []),
          api.get('/brokers').catch(() => []),
          api.get('/config').catch(() => ({ tc_blue: 1415 })),
          api.get('/dolar').catch(() => null),
          api.get('/benchmarks').catch(() => null),
        ])
        if (cancelled) return
        setMonthly(mon || [])
        setOperations(ops || [])
        setSnapshots(snaps || [])
        setPositions(pos || [])
        setBrokers(bkrs || [])
        setBrokersRegistry(bkrs || [])   // parent-aware isArUsdBroker (robusto al rename)
        setBench(bnch)
        const tc = pickFinancialRate(dol, valuationDollar) || cfg?.tc_blue || 1415
        setTcValuacion(tc)
        setTcCedear(pickFinancialRate(dol, valuationDollar) || tc)
        setTcCripto(dol?.cripto?.venta ?? null)
        // Cargar precios para que el live value por broker sea exacto
        const arsBrokers = new Set((bkrs || []).filter(b => b.currency === 'ARS').map(b => b.name))
        const usdtBrokers = new Set((bkrs || []).filter(b => b.currency !== 'ARS').map(b => b.name))
        const arsSyms = [...new Set((pos || []).filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => priceSymbol(p.asset, true, p.asset_type)))]
        // Sub-brokers "· USD" piden el .BA (BYMA); brokers USD reales el ticker US pelado.
        const usdtSyms = [...new Set((pos || []).filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => isArUsdBroker(p.broker) ? priceSymbol(p.asset, true, p.asset_type) : priceSymbol(p.asset, false, p.asset_type)))]
        const all = [...arsSyms, ...usdtSyms].join(',')
        if (all) {
          try {
            const px = await api.get(`/prices?symbols=${all}`)
            if (!cancelled) setPrices(px || {})
          } catch {}
        }
        if (!cancelled) setLoading(false)
      } catch (e) {
        if (cancelled) return
        setError(e.message || 'No pudimos cargar los reportes')
        setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
    // valuationDollar en deps: al cambiar MEP/CCL re-deriva tc/tcCedear (vía
    // re-fetch; no hay flash de loading porque no reseteamos loading=true acá).
  }, [valuationDollar])

  // Brokers disponibles para el selector (excluye 'global' que es siempre default)
  const availableBrokers = useMemo(() => {
    const set = new Set()
    for (const m of monthly) {
      if (m.broker && m.broker !== 'global') set.add(m.broker)
    }
    return [...set].sort()
  }, [monthly])

  const data = useMemo(
    () => buildMonthlyReports(monthly, operations, snapshots, broker, {
      positions, prices, brokers, tcValuacion, tcCedear, tcCripto, bench,
    }),
    [monthly, operations, snapshots, broker, positions, prices, brokers, tcValuacion, tcCedear, tcCripto, bench]
  )

  return { loading, error, ...data, availableBrokers }
}

// ────────────────────────────────────────────────────────────────────────────
// Lógica pura — testeable y separada del fetching
// ────────────────────────────────────────────────────────────────────────────

export function buildMonthlyReports(monthly, operations, snapshots = [], selectedBroker = 'global', context = {}) {
  // 1. Filtrar entries según el broker activo. 'global' = rollup, otros son
  // los brokers individuales que el usuario configuró.
  const globalEntries = (monthly || []).filter(m => m.broker === selectedBroker)

  // 2. Indexar por 'YYYY-MM' para lookup O(1)
  const entriesByPeriod = new Map()
  for (const e of globalEntries) {
    const period = `${e.year}-${String(e.month).padStart(2, '0')}`
    entriesByPeriod.set(period, e)
  }

  // 3. Calcular pnl_realized derivado por mes desde operations.
  // Si el filtro es un broker individual, solo contamos ops de ese broker.
  // Para 'global' usamos todas las ops (rollup).
  const opsForBroker = selectedBroker === 'global'
    ? (operations || [])
    : (operations || []).filter(o => o.broker === selectedBroker)
  const tradeOps = opsForBroker.filter(isTradeOp)
  const realizedByPeriod = new Map()
  for (const op of tradeOps) {
    if (!op.date || op.pnl_usd == null) continue
    const period = op.date.slice(0, 7)  // 'YYYY-MM'
    const prev = realizedByPeriod.get(period) || 0
    realizedByPeriod.set(period, prev + (op.pnl_usd || 0))
  }

  // 4. Unión de períodos: meses con entry O con ops cerradas
  const allPeriods = new Set([...entriesByPeriod.keys(), ...realizedByPeriod.keys()])
  if (allPeriods.size === 0) {
    return { years: [], hasAnyData: false, selectedBroker, liveValue: null, liveDate: null }
  }

  // 4.5. Indexar ops POR PERÍODO (no solo realizedByPeriod) — necesitamos
  // las ops completas para computar mejor/peor operación por mes.
  const opsByPeriod = new Map()
  for (const op of opsForBroker) {
    if (!op.date) continue
    const period = op.date.slice(0, 7)
    if (!opsByPeriod.has(period)) opsByPeriod.set(period, [])
    opsByPeriod.get(period).push(op)
  }

  // 4.6. Decidir si mostramos la comparación con inflación AR. Regla:
  //   • Filter 'global'  → sí, si el user tiene al menos un broker ARS
  //   • Filter individual → sí, solo si ese broker tiene currency ARS
  // Esto cumple con: "comparación inflación solo cuando hay inversión ARS".
  let showInflation = false
  if (context.brokers && context.brokers.length > 0) {
    if (selectedBroker === 'global') {
      showInflation = context.brokers.some(b => b.currency === 'ARS')
    } else {
      const bObj = context.brokers.find(b => b.name === selectedBroker)
      showInflation = bObj?.currency === 'ARS'
    }
  }

  const sp500Map = context.bench?.sp500 || null
  const inflationMap = context.bench?.inflation_ar || null

  // 5. Indexar snapshots por mes para sparklines + lookup del valor live.
  // Cada snapshot tiene shape { date: 'YYYY-MM-DD', total_value, ... }.
  // OJO: los snapshots son del portfolio TOTAL (no desglosados por broker).
  // Cuando hay filtro de broker individual, NO podemos usar snapshots
  // porque serían engañosos (mostrarían evolución global, no del broker).
  // En ese caso pasamos un map vacío para que las sparklines no se rendereen.
  const snapsByMonth = new Map()
  if (selectedBroker === 'global') {
    // `snapsByMonth` alimenta DOS cosas con exigencias distintas: la sparkline
    // del mes (dibujo) y el par baseSnap/lastSnap (medición). Acá se aplica la
    // regla floja —la de dibujar—, y la exigente se aplica sobre el resultado,
    // donde se usa. Meter las dos en un mismo array fue parte del enredo.
    for (const s of (snapshots || [])) {
      if (!s.date || s.total_value == null) continue
      if (!esDibujable(s)) continue
      const period = s.date.slice(0, 7)
      if (!snapsByMonth.has(period)) snapsByMonth.set(period, [])
      snapsByMonth.get(period).push(s)
    }
    for (const arr of snapsByMonth.values()) {
      arr.sort((a, b) => a.date.localeCompare(b.date))
    }
  }

  // 6. Construir lista de meses
  const months = [...allPeriods].sort().map(period => {
    const [year, month] = period.split('-').map(Number)
    const entry = entriesByPeriod.get(period)
    const realizedFromOps = realizedByPeriod.get(period) || 0

    // Sparkline: serie de valores diarios del portfolio durante el mes.
    // Si solo hay 1 snapshot, no alcanza para trazar línea — devolvemos null
    // y el componente no renderiza la sparkline.
    const monthSnaps = snapsByMonth.get(period) || []
    const sparkline = monthSnaps.length >= 2
      ? monthSnaps.map(s => ({ date: s.date, value: s.total_value }))
      : null

    let startUsd, endUsd, deposits, withdrawals, pnlRealized, pnlUnrealized, source

    if (entry) {
      startUsd = entry.capital_inicio || 0
      endUsd = entry.capital_final || 0
      deposits = entry.deposits || 0
      withdrawals = entry.withdrawals || 0
      pnlRealized = entry.pnl_realized || 0
      pnlUnrealized = entry.pnl_unrealized || 0
      // Si el entry no tiene capital_inicio o capital_final completo, lo
      // marcamos como parcial — visualmente igual que derived pero distinto.
      const hasCapital = (entry.capital_inicio || 0) > 0 && (entry.capital_final || 0) > 0
      source = hasCapital ? 'manual' : 'partial'
    } else {
      // Mes sin entry pero con activity en operations.
      // Solo tenemos pnl_realized; el resto queda en cero hasta que el user
      // cierre el mes formalmente.
      startUsd = 0
      endUsd = 0
      deposits = 0
      withdrawals = 0
      pnlRealized = realizedFromOps
      pnlUnrealized = 0
      source = 'derived'
    }

    // Delta del mes:
    //   manual / partial  → capital_final − capital_inicio − flows netos
    //   derived           → solo pnl_realized (no tenemos capital tracking)
    //
    // % usa Modified Dietz como denominador: (startUsd + 0.5*flows).
    // Esto evita dos modos de error del divisor `startUsd`:
    //   • startUsd=0 con depósito mid-mes y ganancia → daba 0%, ahora da el %
    //     real time-weighted.
    //   • startUsd muy chico vs un depósito gigante → inflaba el % a cientos
    //     (e.g. start=$1k, deposit=$50k, pnl=$2k → vieja fórmula daba 200%,
    //     Modified Dietz da 2k/26k ≈ 7.7%, que refleja la exposure promedio).
    const flows = deposits - withdrawals
    // Denominador: capital expuesto promedio durante el mes
    // (asume flujos uniformes → peso 0.5).
    const avgCapital = (startUsd || 0) + 0.5 * flows
    let deltaUsd, deltaPct
    if (source === 'manual') {
      deltaUsd = endUsd - startUsd - flows
      deltaPct = avgCapital > 0 ? (deltaUsd / avgCapital) * 100 : 0
    } else if (source === 'partial') {
      // Falta data — usamos pnl_realized + pnl_unrealized como proxy
      deltaUsd = pnlRealized + pnlUnrealized
      deltaPct = avgCapital > 0 ? (deltaUsd / avgCapital) * 100 : 0
    } else {
      // derived
      deltaUsd = pnlRealized
      deltaPct = 0   // sin baseline, no calculamos %
    }

    // ── Quick-win C1: rendimiento del MES EN CURSO sin discontinuidad de base ──
    // El delta del mes vivo se calculaba como capital_final − capital_inicio, pero
    // capital_final ya es mark-to-market (el unrealized se sincroniza desde el
    // frontend) mientras capital_inicio viene del chain cost-basis del mes anterior.
    // Esa mezcla de bases produce un "rendimiento" fantasma (ej. −64.9%) que en
    // realidad es la diferencia entre las dos valuaciones, no performance real.
    // Para el mes en curso recomputamos el delta PURO-MtM desde los snapshots del
    // portfolio (misma base en ambas puntas). Si no hay baseline MtM, no mostramos
    // un % fantasma (queda null → el banner muestra "en curso" sin número).
    // Fix de raíz (backlog): sellar capital_final con MtM en el backend.
    const _now = new Date()
    const isLiveMonth = (source === 'manual' || source === 'partial')
      && selectedBroker === 'global'
      && year === _now.getFullYear() && month === (_now.getMonth() + 1)
    if (isLiveMonth) {
      const monthStart = `${period}-01`
      // Base = último snapshot ANTES del mes (= valor MtM al cierre del mes
      // anterior). Si no hay (cuenta recién importada), el primer snapshot DENTRO
      // del mes como fallback.
      // ⚠️ `esApto` EN LAS DOS PUNTAS. Éste es el bloque que produjo el número
      // reclamado, y la ironía es que se escribió para matarlo: el comentario de
      // acá arriba ya dice "esa mezcla de bases produce un rendimiento fantasma
      // (ej. −64,9%)". Elegía `baseSnap` como el último snapshot anterior al mes
      // SIN MIRAR si era una medición, y el fantasma volvía por esa puerta.
      //
      // Reproducido al centavo contra la copia de producción del 16/08 (uid 452):
      //     baseSnap = 2026-07-31  196.631,56  source='import'  ← AL COSTO
      //     lastSnap = 2026-08-16   67.214,75  source='cron'    ← A MERCADO
      //     deltaUsd = 67.214,75 − 196.631,56 − 0 = −129.416,82
      //     deltaPct = −129.416,82 / 196.631,56  = −65,82%
      // Nadie perdió 129 mil dólares: la cartera nunca valió 196.631,56 a precio
      // de mercado. Ese número es el capital_final de la cadena contable.
      let baseSnap = null
      for (const s of (snapshots || [])) {
        if (s.total_value == null || !s.date || s.date >= monthStart) continue
        if (!esApto(s)) continue
        if (!baseSnap || s.date > baseSnap.date) baseSnap = s
      }
      const monthAptos = monthSnaps.filter(esApto)
      if (!baseSnap && monthAptos.length >= 2) baseSnap = monthAptos[0]
      const lastSnap = monthAptos.length ? monthAptos[monthAptos.length - 1] : null
      if (baseSnap && lastSnap && baseSnap.total_value > 0 && baseSnap.date < lastSnap.date) {
        const mtmStart = baseSnap.total_value
        const mtmEnd = lastSnap.total_value
        const avgMtm = mtmStart + 0.5 * flows
        deltaUsd = mtmEnd - mtmStart - flows
        deltaPct = avgMtm > 0 ? (deltaUsd / avgMtm) * 100 : 0
      } else {
        // Sin baseline MtM no se puede calcular el rendimiento del mes sin mezclar
        // bases → no inventamos un número.
        deltaUsd = null
        deltaPct = null
      }
    }

    // Drivers del mes: mejor/peor operación + vs benchmarks
    const monthOps = opsByPeriod.get(period) || []
    const drivers = computeDriversForMonth({
      monthOps,
      deltaPct,
      sp500Map,
      inflationMap,
      period,
      showInflation,
    })

    return {
      period,
      year,
      month,
      name: MONTH_NAMES[month - 1] || '—',
      startUsd,
      endUsd,
      deposits,
      withdrawals,
      pnlRealized,
      pnlUnrealized,
      deltaUsd,
      deltaPct,
      source,
      status: statusFromPct(deltaPct),
      sparkline,
      drivers,
    }
  })

  // 7. Agrupar por año
  const byYear = new Map()
  for (const m of months) {
    if (!byYear.has(m.year)) byYear.set(m.year, [])
    byYear.get(m.year).push(m)
  }

  // 8. Live value:
  //   • Broker 'global'   → snapshot más reciente (consistente con Dashboard)
  //   • Broker individual → computeBrokerValue del broker en USD
  //                         (requiere positions + prices + tcValuacion del context)
  let liveValue = null
  let liveDate = null
  if (selectedBroker === 'global') {
    // ⚠️ EL BORDE DE CIERRE TAMBIÉN SE FILTRA. Sin `esApto`, el día que el
    // usuario importa el "valor live" ES la cadena contable: la fila que el
    // import acaba de fabricar es la más nueva y gana el sort. De ahí sale el
    // fantasma con el signo dado vuelta (un +96% en vez de un −65%), que es por
    // qué nadie lo fue a buscar. En la copia de producción son 180 usuarios (22%)
    // cuya última fila no es una medición.
    const latestSnap = (snapshots || [])
      .filter(s => s.date && s.total_value != null && esApto(s))
      .sort((a, b) => b.date.localeCompare(a.date))[0]
    liveValue = latestSnap?.total_value ?? null
    liveDate = latestSnap?.date ?? null
  } else if (context.positions && context.brokers && context.tcValuacion) {
    const brokerObj = context.brokers.find(b => b.name === selectedBroker)
    if (brokerObj) {
      try {
        const r = computeBrokerValue(context.positions, context.prices || {}, brokerObj, context.tcValuacion, context.tcCedear || context.tcValuacion, context.tcCripto ?? null)
        liveValue = r.value
        // No tenemos liveDate por broker (sería del momento del fetch),
        // así que lo dejamos null y la UI no muestra fecha en ese caso.
      } catch {
        liveValue = null
      }
    }
  }
  const todayYear = new Date().getFullYear()

  // Pre-cómputo: capital aportado acumulado al cierre de cada año.
  // = Σ(deposits − withdrawals) desde el inicio de la historia hasta Dic de
  // ese año. Sirve para mostrar la métrica alternativa "YTD sobre capital
  // aportado total", más conservadora/intuitiva que el TWRR para usuarios
  // retail. La métrica primaria sigue siendo TWRR (ver `ytdPct`).
  const cumNetDepByYear = new Map()
  let cumNetDep = 0
  for (const m of months) {
    cumNetDep += (m.deposits || 0) - (m.withdrawals || 0)
    cumNetDepByYear.set(m.year, cumNetDep)   // sobreescribe → queda el último (Dic)
  }

  // 9. Construir struct anual con summary del año
  const years = [...byYear.entries()]
    .sort((a, b) => b[0] - a[0])  // años descendentes (lista vertical: actual arriba)
    .map(([year, monthsInYear]) => {
      // Orden interno: cronológico (Enero → Diciembre, lectura natural).
      // Antes era inverso — feedback del usuario.
      const sorted = [...monthsInYear].sort((a, b) => a.month - b.month)

      // startUsd / endUsd del año
      const oldestWithCapital = sorted.find(m => m.source === 'manual')          // primero del array (más viejo)
      const newestWithCapital = [...sorted].reverse().find(m => m.source === 'manual')  // último (más reciente)
      const startUsd = oldestWithCapital?.startUsd || 0

      // Para el año actual, si tenemos snapshot live, lo usamos como endUsd.
      // Eso asegura que el YTD coincida con el valor que muestra el Dashboard
      // (valor live − capital aportado), no con el último capital_final cerrado
      // que puede ser de hace varios meses.
      let endUsd, endSource
      const isCurrentYear = year === todayYear
      if (isCurrentYear && liveValue != null) {
        endUsd = liveValue
        endSource = 'live'
      } else {
        endUsd = newestWithCapital?.endUsd || 0
        endSource = 'manual'
      }

      // CONSISTENCY FIX: si el año en curso usa liveValue como endUsd, el
      // YTD del Hero incluye lo que pasó DESPUÉS del último capital_final
      // cerrado (gap entre 'cierre de mayo' y 'hoy'). Sin este fix, la
      // suma de delta por mes ≠ YTD. Solución: actualizamos el endUsd del
      // último mes manual del año en curso para que refleje el live, y
      // recalculamos su delta. Marcamos con isLive=true para que la UI
      // muestre un badge sutil 'LIVE'.
      if (isCurrentYear && endSource === 'live' && newestWithCapital) {
        const gap = liveValue - (newestWithCapital.endUsd || 0)
        if (Math.abs(gap) > 0.01) {
          // Mutamos el mes en su lugar dentro de `sorted` (es el mismo objeto).
          newestWithCapital.endUsd = liveValue
          newestWithCapital.isLive = true

          // ⚠️ ACÁ SE PISABA EL FIX DE 130 LÍNEAS MÁS ARRIBA. Esto es lo que hizo
          // que las rondas anteriores fueran INVISIBLES en pantalla: el bloque
          // `isLiveMonth` calculaba con cuidado un delta de bases homogéneas (o
          // se negaba a calcularlo), y acá el MISMO archivo lo sobrescribía con
          //     deltaUsd = liveValue − startUsd − flows
          // donde `startUsd` es `capital_inicio` de `monthly_entries`, o sea LA
          // CADENA CONTABLE. Mercado menos contabilidad, publicado como
          // rendimiento del mes: exactamente el bug que el otro bloque acababa
          // de matar.
          //
          // La base tiene que ser una MEDICIÓN, igual que la punta. Si no la hay,
          // no hay número — y eso es una respuesta, no una falla.
          // ⚠️ Y TIENE QUE ESTAR PEGADA AL ARRANQUE DEL MES. Sin el piso de
          // antigüedad, este loop agarraba la medición más reciente ANTERIOR al
          // mes por vieja que fuera: si la última era del 31 de diciembre, el
          // delta de "este mes" arrancaba en diciembre y se comía dos meses de
          // mercado ajeno presentándolos como el mes en curso.
          // Es el mismo `_border_is_fresh` / `_BORDER_MAX_LAG_DAYS = 5` que el
          // backend ya aplica en la rama del mes en curso
          // (`reporting/builder.py`, `bordes_mercado_periodo`). Mismo número a
          // propósito: si se separan, uno de los dos está mal.
          const _mStart = `${newestWithCapital.period}-01`
          const _pisoBase = new Date(new Date(`${_mStart}T00:00:00Z`).getTime() - 5 * 86400000)
            .toISOString().slice(0, 10)
          let _baseMed = null
          for (const s of (snapshots || [])) {
            if (s.total_value == null || !s.date || s.date >= _mStart) continue
            if (s.date < _pisoBase) continue
            if (!esApto(s)) continue
            if (!_baseMed || s.date > _baseMed.date) _baseMed = s
          }
          const flows = (newestWithCapital.deposits || 0) - (newestWithCapital.withdrawals || 0)
          // Con cierre medido, ése manda. Sin él queda la cadena contable, y ahí
          // decide el MISMO guard que ya usa el backend (`baseIncomparable`): si
          // el período está dominado por dinero nuevo el número se publica igual
          // —es el onboarding, y es correcto—; si la base contable es casi todo,
          // no hay número.
          const _start = (_baseMed && _baseMed.total_value > 0)
            ? _baseMed.total_value
            : (newestWithCapital.startUsd || 0)
          const _startEsMedido = !!(_baseMed && _baseMed.total_value > 0)
          if (_start > 0 && !baseIncomparable(_startEsMedido, _start,
                                              newestWithCapital.deposits, newestWithCapital.withdrawals)) {
            const avgCap = _start + 0.5 * flows
            newestWithCapital.deltaUsd = liveValue - _start - flows
            newestWithCapital.deltaPct = avgCap > 0
              ? (newestWithCapital.deltaUsd / avgCap) * 100
              : 0
            newestWithCapital.status = statusFromPct(newestWithCapital.deltaPct)
          } else {
            // Sin base medida y con la cadena pesando de más: no se puede medir
            // el mes. Se deja el valor live (que es un dato honesto) y se calla
            // el porcentaje. `sinBaseMedida` es lo que la UI usa para explicar
            // POR QUÉ no hay número, en vez de un "—" mudo.
            newestWithCapital.deltaUsd = null
            newestWithCapital.deltaPct = null
            newestWithCapital.status = null
            newestWithCapital.sinBaseMedida = true
          }
        }
      }

      // Flujos netos del año (desde monthly_entries solamente — los derived
      // no tienen flow tracking porque no hay entry global)
      const flowsYear = sorted.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)

      // YTD del año.
      //
      // USD: dividir el resultado anual por el `startUsd` del primer mes era
      // engañoso cuando el capital crecía mucho durante el año (e.g. start=$5k,
      // deposits totales=$50k → cualquier ganancia se mostraba ÷ $5k inflando
      // el % a cientos). Ahora computamos el % vía TWRR (Time-Weighted Return):
      // chain-link de los rendimientos mensuales. Es la única forma correcta
      // de agregar retornos a través de períodos donde la base cambia mucho
      // por aportes/retiros.
      //
      //   ytdPct = (∏ (1 + deltaPct_mes / 100)) - 1) * 100
      //
      // El ytdUsd absoluto sigue siendo `endUsd - startUsd - flowsYear` (es
      // lo que coincide con el Hero del Dashboard). El % no es ytdUsd/startUsd.
      let ytdUsd, ytdPct
      let ytdSinBaseMedida = false
      // ⚠️ MISMA RESTA, UN NIVEL MÁS ARRIBA. Con `endSource === 'live'`, `endUsd`
      // es el valor a MERCADO y `startUsd` es el `capital_inicio` del mes más
      // viejo del año — la cadena CONTABLE. Restarlos publica en el Hero el
      // mismo fantasma que el bloque del mes acaba de tapar, así que el guard va
      // en los dos o el arreglo se ve por una pantalla y se escapa por la otra.
      // (Con `endSource === 'manual'` las dos puntas son contables: homogéneo,
      // no hay nada que guardar.)
      //
      // El criterio NO es nuevo: es el que `_ytd_delta` ya aplica en el backend
      // (`main.py:31908-31914`) — el arranque del año tiene que ser un cierre
      // MEDIDO, y sin él no hay YTD. Acá se agrega la única concesión que el
      // repo ya se había hecho (`baseIncomparable`), para no borrarle el número
      // al onboarding.
      let _ytdStart = startUsd
      if (endSource === 'live') {
        const _yrStart = `${year}-01-01`
        let _snapStart = null
        for (const s of (snapshots || [])) {
          if (s.total_value == null || !s.date || s.date >= _yrStart) continue
          if (!esApto(s)) continue
          if (!_snapStart || s.date > _snapStart.date) _snapStart = s
        }
        if (_snapStart && _snapStart.total_value > 0) {
          _ytdStart = _snapStart.total_value
        } else if (baseIncomparable(false, startUsd, flowsYear > 0 ? flowsYear : 0,
                                    flowsYear < 0 ? -flowsYear : 0)) {
          ytdSinBaseMedida = true
        }
      }
      if (ytdSinBaseMedida) {
        // Sin cierre medido al arranque del año no hay YTD. Se deja en null
        // —NO en 0 y NO en un fallback fabricado— y `ytdSinBaseMedida` es lo que
        // la UI usa para decir por qué.
        ytdUsd = null
      } else if (_ytdStart > 0 && endUsd > 0) {
        ytdUsd = endUsd - _ytdStart - flowsYear
      } else {
        // Fallback: suma de deltaUsd por mes (incluye manual + partial + derived)
        ytdUsd = sorted.reduce((s, m) => s + m.deltaUsd, 0)
      }
      // TWRR chain-link sobre meses con % válido (manual/partial — los
      // derived no tienen baseline por construcción, sus deltaPct=0).
      const monthsForTwrr = sorted.filter(m => m.source !== 'derived' && m.deltaPct != null)
      if (monthsForTwrr.length > 0) {
        let cum = 1
        for (const m of monthsForTwrr) {
          cum *= 1 + (m.deltaPct || 0) / 100
        }
        ytdPct = (cum - 1) * 100
      } else {
        ytdPct = 0
      }

      // Métrica alternativa: YTD sobre capital aportado acumulado al cierre
      // del año (más conservadora; útil para que el user no se confunda con
      // un TWRR de +115% post-crash). Si el cap. aportado es 0 o negativo,
      // queda null (no tiene sentido el ratio).
      const cumNetDepEnd = cumNetDepByYear.get(year) || 0
      // ⚠️ `ytdUsd` puede ser null (sin base medida) y en JS `null / 500 * 100`
      // es 0, no null: sin este chequeo el guard de arriba se convierte en un
      // "0,0%" publicado, que es peor que el número que vino a tapar porque se
      // lee como "el año estuvo plano".
      const ytdPctOverContrib = (cumNetDepEnd > 0 && ytdUsd != null)
        ? (ytdUsd / cumNetDepEnd) * 100
        : null

      // Best / worst del año (solo entre meses con deltaPct válido — manual/partial)
      const withPct = sorted.filter(m => m.source !== 'derived')
      const bestMonth = withPct.length > 0
        ? [...withPct].sort((a, b) => b.deltaPct - a.deltaPct)[0]
        : null
      const worstMonth = withPct.length > 0
        ? [...withPct].sort((a, b) => a.deltaPct - b.deltaPct)[0]
        : null

      return {
        year,
        ytdUsd,
        ytdPct,
        ytdSinBaseMedida,        // true → no hay cierre medido al arranque del año (la UI explica el vacío)
        ytdPctOverContrib,       // % alternativo: ytdUsd / capital aportado total al cierre
        capContribAtYearEnd: cumNetDepEnd,
        startUsd,
        endUsd,
        endSource,
        liveDate: endSource === 'live' ? liveDate : null,
        flowsYear,
        bestMonth: bestMonth ? { name: bestMonth.name, pct: bestMonth.deltaPct } : null,
        worstMonth: worstMonth ? { name: worstMonth.name, pct: worstMonth.deltaPct } : null,
        months: sorted,
        derivedCount: sorted.filter(m => m.source === 'derived').length,
        manualCount: sorted.filter(m => m.source === 'manual').length,
      }
    })

  return {
    years,
    hasAnyData: years.length > 0,
    liveValue,
    liveDate,
    selectedBroker,
  }
}
