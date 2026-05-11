// bondSchedule.js — cronograma de pagos + TIR estimada por bono.
// ════════════════════════════════════════════════════════════════════════════
// Orchestrator: arma el schedule de cashflows por ticker (a partir del bondMeta)
// y delega la matemática pura a bondPricing.js (day-count, accrued, YTM).
//
// Soporta DOS formas de definir el bono:
//
//   FORMA RICA (preferida — Fase 3B en adelante):
//     bondMeta puede incluir:
//       • couponSchedule: [{ from, to, rate }] — step-up con rates por período.
//         La fecha de pago N usa el rate del período que CONTIENE esa fecha.
//       • amortSchedule: [{ date, pct }] — fechas exactas y % de amort por
//         cuota. Suma debe ser 100 (validable). Si está presente, ignora
//         amortStart/amortCount.
//       • issueDate: 'YYYY-MM-DD' — la primera fecha de cupón se calcula
//         hacia atrás desde maturity, pero issueDate se usa para accrued
//         si el asOf está antes del primer pago del schedule generado.
//       • dayCount: '30/360' | 'ACT/365' | etc. — convención del prospecto.
//         Si no se especifica, default 'ACT/365.25' (legacy).
//
//   FORMA LEGACY (compat con Fase 1-2):
//     bondMeta solo tiene couponRate (escalar) y opcionalmente amortStart/
//     amortCount. El schedule se genera con cupón constante y amorts iguales
//     en grilla retro desde maturity.
//
// Convención: el schedule expresa todo POR 100 de face value original
// (estándar de mercado). Para el monto que recibirá una posición específica,
// multiplicar por (quantity / 100).

import { getBondMeta } from './bondMeta'
import {
  dayCountFraction,
  computeAccrued,
  yieldToMaturity,
  cleanToDirty,
} from './bondPricing'

const ISO_RE = /^\d{4}-\d{2}-\d{2}$/

function diffDays(a, b) {
  const ta = Date.UTC(+a.slice(0, 4), +a.slice(5, 7) - 1, +a.slice(8, 10))
  const tb = Date.UTC(+b.slice(0, 4), +b.slice(5, 7) - 1, +b.slice(8, 10))
  return Math.round((tb - ta) / (1000 * 60 * 60 * 24))
}

// Suma N meses a una fecha ISO. Si el día destino no existe (31 enero + 1 mes),
// cae al último día del mes destino. Para schedules semestrales del canje AR
// 2020 (siempre día 9), esta aproximación es exacta.
//
// NOTA: no aplica business-day adjustment. Bonos del canje 2020 caen siempre
// en hábiles AR (9 ene / 9 jul son hábiles en la mayoría de los años). Para
// bonos con fechas de prospecto no-regulares se debe usar `amortSchedule`
// explícito con fechas adjusted. Fase 3B agregará esos hardcoded.
export function addMonths(iso, months) {
  if (!ISO_RE.test(iso)) return null
  const y = +iso.slice(0, 4)
  const m = +iso.slice(5, 7)
  const d = +iso.slice(8, 10)
  const date = new Date(Date.UTC(y, m - 1, d))
  const targetMonth = (m - 1) + months
  date.setUTCFullYear(y + Math.floor(targetMonth / 12))
  date.setUTCMonth(((targetMonth % 12) + 12) % 12)
  const targetMonthIdx = ((m - 1 + months) % 12 + 12) % 12
  if (date.getUTCMonth() !== targetMonthIdx) {
    date.setUTCDate(0)
  }
  return date.toISOString().slice(0, 10)
}

function monthsForFreq(freq) {
  switch (freq) {
    case 'monthly':    return 1
    case 'quarterly':  return 3
    case 'semiannual': return 6
    case 'annual':     return 12
    default:           return null
  }
}

// Devuelve el rate efectivo % anual aplicable a una fecha dada.
// Si meta tiene `couponSchedule` (forma rica), busca el período que contiene
// la fecha. Si no, devuelve `couponRate` constante (forma legacy).
function getRateForDate(meta, date) {
  if (meta.couponSchedule && Array.isArray(meta.couponSchedule)) {
    const period = meta.couponSchedule.find(p => date >= p.from && date <= p.to)
    if (period) return period.rate
    // Si el asOfDate está fuera de todos los períodos definidos, fallback al
    // último período o al couponRate como proxy.
    return meta.couponRate || 0
  }
  return meta.couponRate || 0
}

// Genera el cronograma COMPLETO (todos los pagos históricos + futuros) para
// el ticker dado. Devuelve null si el bono no tiene metadata o no aplica
// (ej: ETF sin maturity).
//
// Cada entry: { date, coupon, amort, total, rate }
//   • date: 'YYYY-MM-DD'
//   • coupon: monto del cupón en esa fecha, por 100 face original
//   • amort: monto de amortización en esa fecha, por 100 face original
//   • total: coupon + amort (conveniencia)
//   • rate: rate anual % aplicable en ese período (para display + debug)
export function generateSchedule(ticker) {
  const meta = getBondMeta(ticker)
  if (!meta) return null
  if (!meta.maturity) return null  // ETFs sin maturity → no schedule
  const { maturity, couponRate, couponFreq } = meta

  // ── Caso zero-cupón: pago único = 100 al vencimiento ─────────────────────
  if (couponFreq === 'none' || !couponRate) {
    return [{ date: maturity, coupon: 0, amort: 100, total: 100, rate: 0 }]
  }

  const months = monthsForFreq(couponFreq)
  if (months == null) return null

  // ── Resolver amortSchedule (forma rica) o derivar de amortStart/Count ────
  let isAmortizing = false
  let amortMap = new Map()  // date → amortPct
  if (meta.amortSchedule && Array.isArray(meta.amortSchedule) && meta.amortSchedule.length > 0) {
    isAmortizing = true
    for (const a of meta.amortSchedule) amortMap.set(a.date, a.pct)
  } else if (meta.amortStart && meta.amortCount) {
    isAmortizing = true
    const amortPct = 100 / meta.amortCount
    // Generamos las fechas amort a partir de amortStart, espaciadas a couponFreq.
    let d = meta.amortStart
    for (let i = 0; i < meta.amortCount; i++) {
      amortMap.set(d, amortPct)
      d = addMonths(d, months)
    }
  }

  // ── Generar grilla de fechas de pago (retrocediendo desde maturity) ──────
  // Cubrimos: desde maturity hacia atrás cada `months` meses hasta llegar a
  // (issueDate si existe) o (la primera amort si amortiza) o (5 años atrás).
  const dates = [maturity]
  let minBack
  if (meta.issueDate) minBack = meta.issueDate
  else if (isAmortizing && amortMap.size > 0) minBack = [...amortMap.keys()].sort()[0]
  else minBack = addMonths(maturity, -60)

  let cursor = maturity
  while (true) {
    const prev = addMonths(cursor, -months)
    if (!prev || prev < minBack) break
    dates.unshift(prev)
    cursor = prev
  }

  // Garantizar que TODAS las fechas amort estén en la grilla (defensivo).
  for (const aDate of amortMap.keys()) {
    if (!dates.includes(aDate)) {
      dates.push(aDate)
    }
  }
  dates.sort()

  // ── Construir los pagos, calculando face remanente paso a paso ───────────
  // Face inicial = 100. En cada fecha:
  //   1. Cupón = rate_aplicable / freq × face_pre_amort
  //   2. Amort = amortMap.get(date) (si está); para bullet, todo en maturity
  //   3. Face siguiente = face_actual − amort_de_hoy
  let face = 100
  const schedule = []
  for (const date of dates) {
    const rateAnnual = getRateForDate(meta, date)
    const couponPerPeriod = rateAnnual / (12 / months)
    const couponAmount = +(couponPerPeriod * face / 100).toFixed(6)

    let amortOnThisDate = 0
    if (isAmortizing) {
      amortOnThisDate = amortMap.get(date) || 0
    } else if (date === maturity) {
      // Bullet: maturity devuelve todo el face remanente
      amortOnThisDate = face
    }

    schedule.push({
      date,
      coupon: couponAmount,
      amort: +amortOnThisDate.toFixed(6),
      total: +(couponAmount + amortOnThisDate).toFixed(6),
      rate: rateAnnual,
    })
    face = Math.max(0, face - amortOnThisDate)
  }

  // Sanity: si después de todos los pagos sobró face, lo devolvemos en el
  // último pago. Esto puede ocurrir por floor en pct con amortCount no
  // divisible (ej: 100/13 = 7.6923... × 13 = 99.9999).
  if (face > 0.001 && schedule.length > 0) {
    const last = schedule[schedule.length - 1]
    last.amort = +(last.amort + face).toFixed(6)
    last.total = +(last.coupon + last.amort).toFixed(6)
  }

  return schedule
}

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

// Devuelve sólo los pagos futuros (date > from). Si from no se pasa, usa hoy.
export function getRemainingPayments(ticker, from) {
  const sched = generateSchedule(ticker)
  if (!sched) return null
  const cutoff = from || todayIso()
  return sched.filter(p => p.date > cutoff)
}

// El próximo pago, o null si ya venció.
export function getNextPayment(ticker, from) {
  const rest = getRemainingPayments(ticker, from)
  if (!rest || rest.length === 0) return null
  return rest[0]
}

// Suma total a cobrar de acá hasta maturity (por 100 face).
export function totalRemainingPayout(ticker, from) {
  const rest = getRemainingPayments(ticker, from)
  if (!rest) return null
  return rest.reduce((s, p) => s + p.total, 0)
}

// ─── TIR estimada ─────────────────────────────────────────────────────────────
// Versión mejorada (PR #8 / Fase 3A):
//   • Usa bondPricing.yieldToMaturity (bracket + bisect + Newton, robusto).
//   • Respeta el day-count del bono si está definido en bondMeta.dayCount;
//     fallback a 'ACT/365.25' (legacy).
//   • Por default trata el `price` input como CLEAN price y calcula accrued
//     internamente. Si el caller ya tiene dirty, pasar `{ priceIsDirty: true }`.
//   • Devuelve objeto rico para diagnóstico: { ytm, converged, method,
//     iterations, accrued, dirty, clean, dayCount }.
//
// Mantenemos también el output legacy (sólo `ytm` como number) vía wrapper
// `estimateYield(ticker, price, from)` para no romper consumers existentes.

export function estimateYieldDetailed(ticker, priceInput, from, options = {}) {
  const { priceIsDirty = false } = options
  if (!priceInput || priceInput <= 0) {
    return { ytm: null, converged: false, method: 'invalid_price', accrued: 0, dirty: null, clean: null }
  }
  const meta = getBondMeta(ticker)
  if (!meta) return { ytm: null, converged: false, method: 'no_meta', accrued: 0 }

  const sched = generateSchedule(ticker)
  if (!sched) return { ytm: null, converged: false, method: 'no_schedule', accrued: 0 }

  const base = from || todayIso()
  const rest = sched.filter(p => p.date > base)
  if (rest.length === 0) {
    return { ytm: null, converged: false, method: 'matured', accrued: 0, dayCount: meta.dayCount || 'ACT/365.25' }
  }

  const dayCount = meta.dayCount || 'ACT/365.25'

  // Accrued sólo aplica si el caller pasó clean. Si pasó dirty, accrued se
  // reporta para info pero no se modifica el precio.
  const accrued = computeAccrued(sched, base, dayCount, meta.issueDate)
  const clean = priceIsDirty ? (priceInput - accrued) : priceInput
  const dirty = priceIsDirty ? priceInput : (priceInput + accrued)

  // Construir cashflows con t calculado vía el day-count del bono.
  const cashflows = rest.map(p => ({
    t: dayCountFraction(base, p.date, dayCount),
    amount: p.total,
  }))

  const result = yieldToMaturity({ dirtyPrice: dirty, cashflows })
  return {
    ...result,
    accrued,
    clean,
    dirty,
    dayCount,
  }
}

// Backwards-compat: API original devuelve sólo el número (null si falla).
export function estimateYield(ticker, pricePer100, from) {
  // ATENCIÓN: en PR #8 cambiamos la semántica del input — antes se trataba
  // como dirty (sin accrued); ahora por default se trata como CLEAN y se
  // computa el accrued internamente. Esto es una CORRECCIÓN del hallazgo C4
  // del audit: el yield para bonos mid-period sube ~50-200 bps (era under-
  // stated). Test bullet-a-la-par sigue dando ≈ couponRate.
  const r = estimateYieldDetailed(ticker, pricePer100, from)
  return r.ytm
}

// Para una posición de bono con `quantity` (en nominales, donde 1 nominal = 1
// unidad de face value), devuelve el monto del próximo pago en moneda del
// bono. Útil para mostrar al user "tu próximo cobro estimado".
export function nextPaymentForPosition(ticker, quantity, from) {
  const next = getNextPayment(ticker, from)
  if (!next || !quantity) return null
  return {
    date: next.date,
    coupon: +(next.coupon * quantity / 100).toFixed(2),
    amort: +(next.amort * quantity / 100).toFixed(2),
    total: +(next.total * quantity / 100).toFixed(2),
    isPureAmort: next.coupon === 0 && next.amort > 0,
    isPureCoupon: next.amort === 0 && next.coupon > 0,
  }
}

// ─── Helpers para BondDetailRow (Phase 3E preview) ───────────────────────────
// Estos helpers expone el accrued y la "convención usada" para que la UI
// pueda mostrar metadata transparente: "TIR 12.5% efectiva anual · 30/360 ·
// dirty 73.2 (clean 71.5 + accrued 1.7)".

export function getAccruedInterest(ticker, asOfDate) {
  const meta = getBondMeta(ticker)
  if (!meta) return 0
  const sched = generateSchedule(ticker)
  if (!sched) return 0
  const dayCount = meta.dayCount || 'ACT/365.25'
  const base = asOfDate || todayIso()
  return computeAccrued(sched, base, dayCount, meta.issueDate)
}

// Re-exports para que BondDetailRow no tenga que importar bondPricing directo
// (mantiene a bondSchedule.js como una API consolidada).
export { cleanToDirty, yieldToMaturity }
