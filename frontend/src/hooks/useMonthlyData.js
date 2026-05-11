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
import { computeBrokerValue } from '../utils/valuation'

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
  const [monthly, setMonthly] = useState([])
  const [operations, setOperations] = useState([])
  const [snapshots, setSnapshots] = useState([])
  // Para el live por broker
  const [positions, setPositions] = useState([])
  const [prices, setPrices] = useState({})
  const [brokers, setBrokers] = useState([])
  const [tcBlue, setTcBlue] = useState(1415)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [mon, ops, snaps, pos, bkrs, cfg, dol] = await Promise.all([
          api.get('/monthly').catch(() => []),
          api.get('/operations').catch(() => []),
          // 3650 días = ~10 años. Necesitamos toda la historia para sparkline
          // por mes y para que el snapshot 'más reciente' siempre sea live.
          api.get('/snapshots?days=3650').catch(() => []),
          api.get('/positions').catch(() => []),
          api.get('/brokers').catch(() => []),
          api.get('/config').catch(() => ({ tc_blue: 1415 })),
          api.get('/dolar').catch(() => null),
        ])
        if (cancelled) return
        setMonthly(mon || [])
        setOperations(ops || [])
        setSnapshots(snaps || [])
        setPositions(pos || [])
        setBrokers(bkrs || [])
        const tc = dol?.blue?.venta || cfg?.tc_blue || 1415
        setTcBlue(tc)
        // Cargar precios para que el live value por broker sea exacto
        const arsBrokers = new Set((bkrs || []).filter(b => b.currency === 'ARS').map(b => b.name))
        const usdtBrokers = new Set((bkrs || []).filter(b => b.currency === 'USDT').map(b => b.name))
        const arsSyms = [...new Set((pos || []).filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => p.asset + '.BA'))]
        const usdtSyms = [...new Set((pos || []).filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => p.asset))]
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
  }, [])

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
      positions, prices, brokers, tcBlue,
    }),
    [monthly, operations, snapshots, broker, positions, prices, brokers, tcBlue]
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

  // 5. Indexar snapshots por mes para sparklines + lookup del valor live.
  // Cada snapshot tiene shape { date: 'YYYY-MM-DD', total_value, ... }.
  // OJO: los snapshots son del portfolio TOTAL (no desglosados por broker).
  // Cuando hay filtro de broker individual, NO podemos usar snapshots
  // porque serían engañosos (mostrarían evolución global, no del broker).
  // En ese caso pasamos un map vacío para que las sparklines no se rendereen.
  const snapsByMonth = new Map()
  if (selectedBroker === 'global') {
    for (const s of (snapshots || [])) {
      if (!s.date || s.total_value == null) continue
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
    const flows = deposits - withdrawals
    let deltaUsd, deltaPct
    if (source === 'manual') {
      deltaUsd = endUsd - startUsd - flows
      deltaPct = startUsd > 0 ? (deltaUsd / startUsd) * 100 : 0
    } else if (source === 'partial') {
      // Falta data — usamos pnl_realized + pnl_unrealized como proxy
      deltaUsd = pnlRealized + pnlUnrealized
      deltaPct = startUsd > 0 ? (deltaUsd / startUsd) * 100 : 0
    } else {
      // derived
      deltaUsd = pnlRealized
      deltaPct = 0   // sin baseline, no calculamos %
    }

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
  //                         (requiere positions + prices + tcBlue del context)
  let liveValue = null
  let liveDate = null
  if (selectedBroker === 'global') {
    const latestSnap = (snapshots || [])
      .filter(s => s.date && s.total_value != null)
      .sort((a, b) => b.date.localeCompare(a.date))[0]
    liveValue = latestSnap?.total_value ?? null
    liveDate = latestSnap?.date ?? null
  } else if (context.positions && context.brokers && context.tcBlue) {
    const brokerObj = context.brokers.find(b => b.name === selectedBroker)
    if (brokerObj) {
      try {
        const r = computeBrokerValue(context.positions, context.prices || {}, brokerObj, context.tcBlue)
        liveValue = r.value
        // No tenemos liveDate por broker (sería del momento del fetch),
        // así que lo dejamos null y la UI no muestra fecha en ese caso.
      } catch {
        liveValue = null
      }
    }
  }
  const todayYear = new Date().getFullYear()

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
          // Mutamos el mes en su lugar dentro de `sorted` (es el mismo
          // objeto). Recalculamos delta con el live como endUsd.
          newestWithCapital.endUsd = liveValue
          const flows = (newestWithCapital.deposits || 0) - (newestWithCapital.withdrawals || 0)
          newestWithCapital.deltaUsd = liveValue - (newestWithCapital.startUsd || 0) - flows
          newestWithCapital.deltaPct = (newestWithCapital.startUsd || 0) > 0
            ? (newestWithCapital.deltaUsd / newestWithCapital.startUsd) * 100
            : 0
          newestWithCapital.status = statusFromPct(newestWithCapital.deltaPct)
          newestWithCapital.isLive = true
        }
      }

      // Flujos netos del año (desde monthly_entries solamente — los derived
      // no tienen flow tracking porque no hay entry global)
      const flowsYear = sorted.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)

      // YTD del año:
      //   • Si tenemos startUsd (manual) y endUsd (live o manual):
      //     YTD = endUsd − startUsd − flowsYear  ← match exacto con Dashboard
      //   • Sino, fallback a la suma de deltaUsd por mes (legacy)
      let ytdUsd, ytdPct
      if (startUsd > 0 && endUsd > 0) {
        ytdUsd = endUsd - startUsd - flowsYear
        ytdPct = (ytdUsd / startUsd) * 100
      } else {
        // Fallback: suma de deltaUsd por mes (incluye manual + partial + derived)
        ytdUsd = sorted.reduce((s, m) => s + m.deltaUsd, 0)
        ytdPct = startUsd > 0 ? (ytdUsd / startUsd) * 100 : 0
      }

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
