// pendingCashflows.js — detector de cobranzas teóricas pendientes.
// ════════════════════════════════════════════════════════════════════════════
// Phase 3E (Nivel 2 de automatización del MVP de bonos).
//
// Por cada posición de bono, comparamos:
//   • Schedule teórico del bono (bondSchedule.generateSchedule) — fechas y
//     montos esperados según prospecto.
//   • Operations ya registradas (Cupón / Amortización) para ese (broker, asset).
//   • Skips manuales del user (POST /bonds/cashflow/skip) — pagos que el user
//     marcó "no aplica" (ej: bono en default, vendido antes, etc.).
//
// Resultado: lista de pagos teóricos PASADOS que ni están registrados ni
// están skipped — el inbox del user.
//
// Matching teórico ↔ operación registrada:
//   • Mismo broker + asset.
//   • Fecha dentro de ±DATE_TOLERANCE_DAYS de la fecha del prospecto.
//     (El broker puede acreditar T+1/T+2 o incluso semanas tarde.)
//
// IMPORTANTE: los montos son ESTIMACIONES (cronograma teórico × qty actual).
// El user los confirma o ajusta antes de registrar. La función NO produce
// efectos de side-effect ni acredita nada.

import { isBondTicker } from './tickers'
import { generateSchedule, nextPaymentForPosition } from './bondSchedule'
import { getBondMeta } from './bondMeta'

// Tolerancia para matchear una operation con una fecha del prospecto.
// 14 días cubre T+1/T+2 estándar + delays operativos + diferencias de huso
// en data de operaciones cargadas manualmente.
const DATE_TOLERANCE_DAYS = 14

// Cuán atrás miramos. Si un pago del cronograma fue hace más de 2 años y el
// user nunca lo registró ni saltó, asumimos que ya no aplica — probablemente
// el user empezó a usar Rendi después de esa fecha. Evita inundar el inbox
// con históricos al cargar un AL30 que paga semestral desde 2024.
const MAX_BACKLOG_DAYS = 730

// Margen "antes de entry_date" que igualmente consideramos. Si el user cargó
// la posición con entry_date 2026-01-15 pero el último cupón fue 2026-01-09,
// es razonable que ese cupón LE corresponda (lo cobró el vendedor por T+x
// settlement). 7 días de gracia cubre casos normales sin generar ruido.
const ENTRY_DATE_GRACE_DAYS = 7

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function diffDaysAbs(a, b) {
  const pa = a.slice(0, 10).split('-').map(Number)
  const pb = b.slice(0, 10).split('-').map(Number)
  const ta = Date.UTC(pa[0], pa[1] - 1, pa[2])
  const tb = Date.UTC(pb[0], pb[1] - 1, pb[2])
  return Math.abs(Math.round((tb - ta) / 86400000))
}

// Resta N días a una fecha ISO. Útil para aplicar el margen de gracia sobre
// entry_date. Trabaja en UTC para evitar timezone drift.
function subDays(iso, days) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  const date = new Date(Date.UTC(y, m - 1, d))
  date.setUTCDate(date.getUTCDate() - days)
  return date.toISOString().slice(0, 10)
}

// Mira si existe alguna op registrada (Cupón o Amortización) para
// (broker, asset) dentro de DATE_TOLERANCE_DAYS de la fecha teórica.
// `bondOps` es el filtered de operations donde op_type ∈ {'Cupón','Amortización'}.
function findMatchingOp(bondOps, broker, asset, theoreticalDate) {
  return bondOps.find(o =>
    o.broker === broker &&
    o.asset === asset &&
    diffDaysAbs(o.date, theoreticalDate) <= DATE_TOLERANCE_DAYS
  )
}

function findMatchingSkip(skips, broker, asset, theoreticalDate) {
  return skips.find(s =>
    s.broker === broker &&
    s.asset === asset &&
    s.date === theoreticalDate
  )
}

// Detecta cobranzas pendientes (pagos teóricos pasados sin operation ni skip).
//
// Inputs:
//   positions: array de positions (bonds entre ellas)
//   bondOps: array de operations filtradas (op_type ∈ {'Cupón','Amortización'})
//   skips: array de skips ({ broker, asset, date, ... })
//   options:
//     today (ISO opcional) — para tests con fecha fija.
//     maxBacklogDays — override del default de 730.
//
// Output: array de { key, broker, asset, position, date, amount, coupon,
//                    amort, total, kind, daysAgo, currency }
//   ordenado por fecha descendente (más reciente primero).
export function detectPendingCashflows(positions, bondOps, skips = [], options = {}) {
  const today = options.today || todayIso()
  const maxBacklog = options.maxBacklogDays ?? MAX_BACKLOG_DAYS
  const earliestDate = (() => {
    const t = new Date(today)
    t.setDate(t.getDate() - maxBacklog)
    return t.toISOString().slice(0, 10)
  })()

  const pending = []
  for (const p of positions) {
    if (!isBondTicker(p.asset)) continue
    if (p.is_cash) continue
    if (!p.quantity || p.quantity <= 0) continue
    // El schedule necesita meta + maturity. ETFs y otros caen en null.
    const schedule = generateSchedule(p.asset)
    if (!schedule) continue
    const meta = getBondMeta(p.asset)
    const bondCurrency = meta?.currency || 'USD'

    // Mínimo por posición: si tiene entry_date, no sugerimos pagos anteriores
    // a esa fecha (con margen de gracia). Esos pagos NO corresponden al user —
    // los cobró el vendedor previo. Sin entry_date, fallback al backlog global.
    let posMinDate = earliestDate
    if (p.entry_date) {
      const gracedEntry = subDays(p.entry_date, ENTRY_DATE_GRACE_DAYS)
      if (gracedEntry > posMinDate) posMinDate = gracedEntry
    }

    for (const pmt of schedule) {
      if (pmt.date > today) break  // futuro, no nos interesa para el inbox
      if (pmt.date < posMinDate) continue  // antes de entry_date o backlog
      // Pagos teóricos = 0 (caso edge en el schedule) tampoco son útiles.
      if ((pmt.total || 0) <= 0) continue
      // ¿Ya tiene operation registrada?
      if (findMatchingOp(bondOps, p.broker, p.asset, pmt.date)) continue
      // ¿Saltado por el user?
      if (findMatchingSkip(skips, p.broker, p.asset, pmt.date)) continue

      // Pendiente. Escalamos al quantity actual del lote.
      const factor = p.quantity / 100
      pending.push({
        key: `${p.broker}:${p.asset}:${pmt.date}`,
        position: p,
        broker: p.broker,
        asset: p.asset,
        date: pmt.date,
        coupon: +(pmt.coupon * factor).toFixed(2),
        amort: +(pmt.amort * factor).toFixed(2),
        total: +(pmt.total * factor).toFixed(2),
        kind: pmt.amort > 0 && pmt.coupon > 0
          ? 'mixto'
          : pmt.amort > 0
            ? 'amortizacion'
            : 'cupon',
        currency: bondCurrency,
        daysAgo: diffDaysAbs(today, pmt.date),
      })
    }
  }
  // Más reciente primero — el user suele cargar los nuevos antes que los viejos.
  pending.sort((a, b) => b.date.localeCompare(a.date))
  return pending
}

// Convenience: agrupa los pendientes por bono (broker + asset) para mostrar
// summary tipo "AL30 (Cocos): 3 pagos pendientes". Útil si el inbox crece mucho.
export function groupPendingByBond(pending) {
  const map = new Map()
  for (const item of pending) {
    const k = `${item.broker}:${item.asset}`
    if (!map.has(k)) map.set(k, { broker: item.broker, asset: item.asset, items: [], totalCash: 0 })
    const entry = map.get(k)
    entry.items.push(item)
    entry.totalCash += item.total
  }
  return [...map.values()]
}
