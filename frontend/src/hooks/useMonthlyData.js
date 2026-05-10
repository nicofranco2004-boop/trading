// useMonthlyData — fuente única para los reportes mensuales.
// ════════════════════════════════════════════════════════════════════════════
// Combina 3 fuentes para que la pantalla "Reportes mensuales" funcione tanto
// para usuarios que cerraron meses manualmente como para usuarios nuevos
// que solo importaron operaciones históricas:
//
//   1. monthly_entries WHERE broker='global'  — source of truth si existen
//   2. operations cerradas por mes            — derivamos pnl_realized
//   3. snapshots                              — referencia para capital_final
//      cuando el mes está derivado y no fue cerrado
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

export default function useMonthlyData() {
  const [monthly, setMonthly] = useState([])
  const [operations, setOperations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [mon, ops] = await Promise.all([
          api.get('/monthly').catch(() => []),
          api.get('/operations').catch(() => []),
        ])
        if (cancelled) return
        setMonthly(mon || [])
        setOperations(ops || [])
        setLoading(false)
      } catch (e) {
        if (cancelled) return
        setError(e.message || 'No pudimos cargar los reportes')
        setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  const data = useMemo(() => buildMonthlyReports(monthly, operations), [monthly, operations])

  return { loading, error, ...data }
}

// ────────────────────────────────────────────────────────────────────────────
// Lógica pura — testeable y separada del fetching
// ────────────────────────────────────────────────────────────────────────────

export function buildMonthlyReports(monthly, operations) {
  // 1. Tomar solo entries 'global' (rollup de todos los brokers)
  const globalEntries = (monthly || []).filter(m => m.broker === 'global')

  // 2. Indexar por 'YYYY-MM' para lookup O(1)
  const entriesByPeriod = new Map()
  for (const e of globalEntries) {
    const period = `${e.year}-${String(e.month).padStart(2, '0')}`
    entriesByPeriod.set(period, e)
  }

  // 3. Calcular pnl_realized derivado por mes desde operations
  // (solo trades cerrados — espejo de Insights.jsx)
  const tradeOps = (operations || []).filter(isTradeOp)
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
    return { years: [], hasAnyData: false }
  }

  // 5. Construir lista de meses
  const months = [...allPeriods].sort().map(period => {
    const [year, month] = period.split('-').map(Number)
    const entry = entriesByPeriod.get(period)
    const realizedFromOps = realizedByPeriod.get(period) || 0

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
    }
  })

  // 6. Agrupar por año
  const byYear = new Map()
  for (const m of months) {
    if (!byYear.has(m.year)) byYear.set(m.year, [])
    byYear.get(m.year).push(m)
  }

  // 7. Construir struct anual con summary del año
  const years = [...byYear.entries()]
    .sort((a, b) => b[0] - a[0])  // años descendentes
    .map(([year, monthsInYear]) => {
      // Orden interno: del más reciente al más antiguo (igual al preview)
      const sorted = [...monthsInYear].sort((a, b) => b.month - a.month)

      // YTD: suma de delta de los meses con baseline (no los derived)
      const withBaseline = sorted.filter(m => m.source !== 'derived')
      const ytdUsd = withBaseline.reduce((s, m) => s + m.deltaUsd, 0) +
                     sorted.filter(m => m.source === 'derived').reduce((s, m) => s + m.deltaUsd, 0)

      // startUsd del año = capital_inicio del primer mes (más antiguo) que tenga
      const oldestWithCapital = [...sorted].reverse().find(m => m.source === 'manual')
      const newestWithCapital = sorted.find(m => m.source === 'manual')
      const startUsd = oldestWithCapital?.startUsd || 0
      const endUsd = newestWithCapital?.endUsd || 0

      const ytdPct = startUsd > 0 ? (ytdUsd / startUsd) * 100 : 0

      // Best / worst del año (solo entre meses con deltaPct válido)
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
  }
}
