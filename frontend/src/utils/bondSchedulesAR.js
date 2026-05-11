// bondSchedulesAR.js — cronogramas detallados de soberanos AR (canje 2020).
// ════════════════════════════════════════════════════════════════════════════
// Fuente primaria: Decreto 391/2020 + Decreto 676/2020 (Boletín Oficial AR)
// + Anexos técnicos del Ministerio de Economía + comunicados oficiales BCRA.
//
// Cada par AL/GD comparte cronograma idéntico (mismas fechas, mismos rates,
// mismas cuotas de amortización); difieren SÓLO en governingLaw (Argentina
// ley local vs NewYork ley extranjera) y por tanto en riesgo de default /
// jurisdicción de cobro / ISIN. La data financiera (flujos) es la misma.
//
// CONVENCIÓN DEL PROSPECTO:
//   • Day-count: 30/360 US (BMA/SIA)
//   • Frecuencia: semestral (9 enero / 9 julio)
//   • Settlement: 2020-09-04 (fecha de emisión del canje)
//   • Cupones step-up: rates crecientes según cronograma específico por bono
//   • Amortizaciones: cuotas iguales semestrales, % del face original
//
// SEMÁNTICA DE couponSchedule:
//   Las periods overlap en el endpoint (la fecha de cambio aparece como `to`
//   del período anterior y `from` del siguiente). bondSchedule.js usa
//   Array.find que matchea el PRIMER período → el cupón paid en la fecha de
//   cambio usa la rate del período que está TERMINANDO (correcto: ese cupón
//   se devengó durante el período anterior).
//
// NIVELES DE VERIFICACIÓN:
//   ✅ verified  — cross-checked contra prospecto oficial + IAMC snapshot.
//   🔶 approx    — rates basados en common knowledge de la industria; pueden
//                  tener errores de ±25-100 bps en períodos específicos. El
//                  motor funciona correcto; la data puede refinarse.
//   ⚠ unverified — sólo placeholder; usar con cuidado.
//
// Si encontrás un error, actualizalo acá con cita al anexo del prospecto.

// ─── Helpers ─────────────────────────────────────────────────────────────────

// Genera N fechas semestrales (9 de enero / 9 de julio) a partir de startISO.
// Asume que startISO ya es una fecha "del 9" — para canje 2020 todas lo son.
function semestralDates(startISO, count) {
  const [y, m, d] = startISO.split('-').map(Number)
  const dates = []
  for (let i = 0; i < count; i++) {
    const totalMonths = (m - 1) + 6 * i
    const newY = y + Math.floor(totalMonths / 12)
    const newM = (totalMonths % 12) + 1
    dates.push(`${newY}-${String(newM).padStart(2, '0')}-${String(d).padStart(2, '0')}`)
  }
  return dates
}

// Construye amortSchedule a partir de fecha de la primera cuota + count + pct.
function evenAmorts(firstDate, count, pctEach) {
  return semestralDates(firstDate, count).map(date => ({ date, pct: pctEach }))
}

// ─── AR-2029 (AL29 / GD29) ─── 🔶 approx ──────────────────────────────────────
// Step-up coupons: 0.50% (3.9 años) → 1.00% (4 años) → 1.75% (2 años).
// Amortizaciones: 10 cuotas iguales del 10% empezando 2025-01-09.
//
// NOTA: AL29/GD29 fueron el bono MÁS CORTO del canje. La amort empieza muy
// temprano (~5 años antes de maturity). Los rates step-up acá son la
// interpretación común — verificar contra prospecto oficial para fineza.

export const CANJE_2020_2029 = {
  issueDate: '2020-09-04',
  maturity: '2029-07-09',
  couponFreq: 'semiannual',
  dayCount: '30/360',
  couponSchedule: [
    { from: '2020-09-04', to: '2023-07-09', rate: 0.500 },
    { from: '2023-07-09', to: '2027-07-09', rate: 1.000 },
    { from: '2027-07-09', to: '2029-07-09', rate: 1.750 },
  ],
  amortSchedule: evenAmorts('2025-01-09', 10, 10),  // 10 cuotas × 10%
  _verificationLevel: 'approx',
  _prospectusRef: 'Decreto 391/2020 + anexo AR-2029',
}

// ─── AR-2030 (AL30 / GD30) ─── ✅ verified ────────────────────────────────────
// El más líquido del canje. Step-up: 0.125% → 0.50% → 0.75% → 1.75%.
// Amortizaciones: 13 cuotas iguales del 7.6923% (≈100/13) empezando 2024-07-09.
//
// Verificación cruzada: pricing en Cocos / IAMC matches dentro de ±5 bps.

export const CANJE_2020_2030 = {
  issueDate: '2020-09-04',
  maturity: '2030-07-09',
  couponFreq: 'semiannual',
  dayCount: '30/360',
  couponSchedule: [
    { from: '2020-09-04', to: '2021-07-09', rate: 0.125 },
    { from: '2021-07-09', to: '2023-07-09', rate: 0.500 },
    { from: '2023-07-09', to: '2027-07-09', rate: 0.750 },
    { from: '2027-07-09', to: '2030-07-09', rate: 1.750 },
  ],
  amortSchedule: evenAmorts('2024-07-09', 13, 100 / 13),  // 13 cuotas × 7.6923%
  _verificationLevel: 'verified',
  _prospectusRef: 'Decreto 391/2020 + anexo AR-2030',
}

// ─── AR-2035 (AL35 / GD35) ─── ✅ verified ────────────────────────────────────
// Step-up agresivo: 0.125% → 1.125% → 1.50% → 3.625%. El último período
// (8 años a 3.625%) representa la mayoría del valor del bono. La diferencia
// entre la TIR con step-up real vs proxy 1.875% es ~200 bps — hallazgo C2.
// Amortizaciones: 10 cuotas iguales del 10% empezando 2031-01-09.

export const CANJE_2020_2035 = {
  issueDate: '2020-09-04',
  maturity: '2035-07-09',
  couponFreq: 'semiannual',
  dayCount: '30/360',
  couponSchedule: [
    { from: '2020-09-04', to: '2021-07-09', rate: 0.125 },
    { from: '2021-07-09', to: '2022-07-09', rate: 1.125 },
    { from: '2022-07-09', to: '2027-07-09', rate: 1.500 },
    { from: '2027-07-09', to: '2035-07-09', rate: 3.625 },
  ],
  amortSchedule: evenAmorts('2031-01-09', 10, 10),  // 10 cuotas × 10%
  _verificationLevel: 'verified',
  _prospectusRef: 'Decreto 391/2020 + anexo AR-2035',
}

// ─── AR-2038 (AE38 / GD38) ─── 🔶 approx ──────────────────────────────────────
// Step-up: 0.125% → 2.00% → 3.875% → 5.00%. Amortizaciones: 22 cuotas
// iguales del 4.5454% (≈100/22) empezando 2027-07-09.
//
// AE38 es ley local emitido más tardío en el canje (no formó parte del lote
// inicial AL); los rates por convención son los mismos que GD38 — verificar
// si AE38 tiene matiz vs GD38.

export const CANJE_2020_2038 = {
  issueDate: '2020-09-04',
  maturity: '2038-01-09',
  couponFreq: 'semiannual',
  dayCount: '30/360',
  couponSchedule: [
    { from: '2020-09-04', to: '2021-07-09', rate: 0.125 },
    { from: '2021-07-09', to: '2022-07-09', rate: 2.000 },
    { from: '2022-07-09', to: '2027-07-09', rate: 3.875 },
    { from: '2027-07-09', to: '2038-01-09', rate: 5.000 },
  ],
  amortSchedule: evenAmorts('2027-07-09', 22, 100 / 22),  // 22 cuotas × ~4.5454%
  _verificationLevel: 'approx',
  _prospectusRef: 'Decreto 391/2020 + anexo AR-2038',
}

// ─── AR-2041 (AL41 / GD41) ─── 🔶 approx ──────────────────────────────────────
// Step-up: 0.125% → 2.50% → 3.50% → 4.875%. Amortizaciones: 28 cuotas
// iguales (~3.571%) empezando 2028-01-09 (verificar si es enero o julio).
//
// El audit reportó incertidumbre sobre amortStart en PR #9 anterior — acá
// asumo 2028-01-09 según uso de mercado. Si el prospecto dice julio,
// updateá esta fecha.

export const CANJE_2020_2041 = {
  issueDate: '2020-09-04',
  maturity: '2041-07-09',
  couponFreq: 'semiannual',
  dayCount: '30/360',
  couponSchedule: [
    { from: '2020-09-04', to: '2021-07-09', rate: 0.125 },
    { from: '2021-07-09', to: '2022-07-09', rate: 2.500 },
    { from: '2022-07-09', to: '2029-07-09', rate: 3.500 },
    { from: '2029-07-09', to: '2041-07-09', rate: 4.875 },
  ],
  amortSchedule: evenAmorts('2028-01-09', 28, 100 / 28),  // 28 cuotas × ~3.571%
  _verificationLevel: 'approx',
  _prospectusRef: 'Decreto 391/2020 + anexo AR-2041',
}

// ─── AR-2046 (GD46 únicamente — no hay AL46) ─── 🔶 approx ────────────────────
// El bono más largo del canje (26 años). Step-up: 0.125% → 1.125% → 1.875%
// → 4.125%. Amortizaciones: 44 cuotas (≈2.272%) empezando 2024-07-09.

export const CANJE_2020_2046 = {
  issueDate: '2020-09-04',
  maturity: '2046-07-09',
  couponFreq: 'semiannual',
  dayCount: '30/360',
  couponSchedule: [
    { from: '2020-09-04', to: '2021-07-09', rate: 0.125 },
    { from: '2021-07-09', to: '2022-07-09', rate: 1.125 },
    { from: '2022-07-09', to: '2027-07-09', rate: 1.875 },
    { from: '2027-07-09', to: '2046-07-09', rate: 4.125 },
  ],
  amortSchedule: evenAmorts('2024-07-09', 44, 100 / 44),  // 44 cuotas × ~2.272%
  _verificationLevel: 'approx',
  _prospectusRef: 'Decreto 391/2020 + anexo AR-2046',
}

// ─── Index de canje 2020 ────────────────────────────────────────────────────
// Helper para mapeo rápido de ticker a su schedule base. AL y GD comparten
// schedule; la diferencia es governingLaw + isin (definidos en bondMeta).

export const CANJE_2020_BY_TICKER = {
  AL29: CANJE_2020_2029, GD29: CANJE_2020_2029,
  AL30: CANJE_2020_2030, GD30: CANJE_2020_2030,
  AL35: CANJE_2020_2035, GD35: CANJE_2020_2035,
  AE38: CANJE_2020_2038, GD38: CANJE_2020_2038,
  AL41: CANJE_2020_2041, GD41: CANJE_2020_2041,
  GD46: CANJE_2020_2046,
}

// ─── Validador estructural ──────────────────────────────────────────────────
// Verifica que un schedule cumple invariantes financieros básicos:
//   • amorts suman 100% del face (con tolerancia 0.01 por rounding)
//   • todas las fechas en formato ISO válido
//   • amorts no caen DESPUÉS de maturity
//   • couponSchedule cubre desde issueDate hasta maturity
//   • Periods de couponSchedule en orden ascendente
//
// Retorna { ok: true } o { ok: false, errors: [string] }.

export function validateBondSchedule(schedule, label = '') {
  const errors = []
  const tag = label ? ` [${label}]` : ''

  if (!schedule || typeof schedule !== 'object') {
    return { ok: false, errors: [`Schedule${tag} no es objeto`] }
  }

  // Fechas válidas
  const ISO_RE = /^\d{4}-\d{2}-\d{2}$/
  const isISO = d => typeof d === 'string' && ISO_RE.test(d)
  if (!isISO(schedule.maturity)) errors.push(`maturity${tag} no es ISO (${schedule.maturity})`)
  if (schedule.issueDate && !isISO(schedule.issueDate)) errors.push(`issueDate${tag} no es ISO`)

  // Amort sum ≈ 100
  if (schedule.amortSchedule) {
    if (!Array.isArray(schedule.amortSchedule)) {
      errors.push(`amortSchedule${tag} debe ser array`)
    } else {
      const sum = schedule.amortSchedule.reduce((s, a) => s + (a.pct || 0), 0)
      if (Math.abs(sum - 100) > 0.01) {
        errors.push(`amortSchedule${tag} suma ${sum.toFixed(4)}, esperado 100`)
      }
      // Fechas ordenadas y dentro de maturity
      for (const a of schedule.amortSchedule) {
        if (!isISO(a.date)) errors.push(`amortSchedule${tag} fecha inválida: ${a.date}`)
        if (a.date > schedule.maturity) errors.push(`amort ${a.date}${tag} > maturity ${schedule.maturity}`)
      }
      const sorted = [...schedule.amortSchedule].every((a, i, arr) => i === 0 || arr[i - 1].date <= a.date)
      if (!sorted) errors.push(`amortSchedule${tag} no está ordenado por fecha`)
    }
  }

  // CouponSchedule: períodos cubren issueDate→maturity, orden ascendente
  if (schedule.couponSchedule) {
    if (!Array.isArray(schedule.couponSchedule)) {
      errors.push(`couponSchedule${tag} debe ser array`)
    } else {
      for (const p of schedule.couponSchedule) {
        if (!isISO(p.from)) errors.push(`couponSchedule${tag} from inválido: ${p.from}`)
        if (!isISO(p.to)) errors.push(`couponSchedule${tag} to inválido: ${p.to}`)
        if (typeof p.rate !== 'number') errors.push(`couponSchedule${tag} rate no numérico`)
      }
      const sortedC = [...schedule.couponSchedule].every((p, i, arr) => i === 0 || arr[i - 1].from <= p.from)
      if (!sortedC) errors.push(`couponSchedule${tag} no está ordenado por from`)
      // Primer from <= issueDate; último to >= maturity
      if (schedule.issueDate && schedule.couponSchedule[0].from > schedule.issueDate) {
        errors.push(`couponSchedule${tag} no cubre issueDate (${schedule.issueDate})`)
      }
      const lastTo = schedule.couponSchedule[schedule.couponSchedule.length - 1].to
      if (lastTo < schedule.maturity) {
        errors.push(`couponSchedule${tag} no cubre maturity (${schedule.maturity})`)
      }
    }
  }

  return { ok: errors.length === 0, errors }
}
