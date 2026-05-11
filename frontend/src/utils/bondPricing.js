// bondPricing.js — primitivas de pricing de renta fija.
// ════════════════════════════════════════════════════════════════════════════
// Capa de matemática pura. NO depende de bondMeta — recibe el schedule ya
// generado (lista de {date, coupon, amort, total} por 100 face) y los inputs
// necesarios. bondSchedule.js es el orchestrator que arma el schedule + llama
// estas primitivas.
//
// Contratos de unidad (estampados en TODOS los inputs/outputs):
//   • Precio: "monto de la moneda del bono por 100 VN" (face value de 100).
//     Si el broker reporta precio por 1 nominal, el caller multiplica × 100
//     ANTES de pasarlo acá.
//   • Cashflows: misma unidad — "monto por 100 face original".
//   • Tasa (yield/TIR): decimal anualizado con compounding correspondiente
//     a la fracción de año del day-count usado. Ej: yield=0.10 con day-count
//     ACT/365 significa "10% efectivo anual sobre días reales / 365".
//   • Fechas: 'YYYY-MM-DD' ISO. Comparaciones lexicográficas son seguras.
//
// Referencias de industria:
//   • ICMA Rule 251 — Day Count Fractions
//   • ISDA 2006 Definitions § 4.16 — Day Count Conventions
//   • Bloomberg DCC reference (BDP DCC field)
//   • Fabozzi, "Bond Markets, Analysis and Strategies" cap. 2-3
//
// Esta capa NO sabe de:
//   • Step-up rates (eso lo resuelve bondSchedule armando el schedule)
//   • CER / inflación (idem)
//   • Monedas / FX (idem — el caller pasa todo en moneda consistente)

const ISO_RE = /^\d{4}-\d{2}-\d{2}$/

function parseIso(iso) {
  if (typeof iso !== 'string' || !ISO_RE.test(iso)) return null
  return [+iso.slice(0, 4), +iso.slice(5, 7), +iso.slice(8, 10)]
}

// Días entre dos fechas ISO (a < b → positivo). Comparación en UTC para que
// no dependa del huso del runtime.
function diffDaysUTC(a, b) {
  const pa = parseIso(a); const pb = parseIso(b)
  if (!pa || !pb) return 0
  const ta = Date.UTC(pa[0], pa[1] - 1, pa[2])
  const tb = Date.UTC(pb[0], pb[1] - 1, pb[2])
  return Math.round((tb - ta) / 86400000)
}

// ─── Day-count conventions ────────────────────────────────────────────────────
// Devuelve la "fracción de año" entre dos fechas según la convención usada
// por el prospecto del bono. Bonos AR canje 2020 usan 30/360 US; muchos
// soberanos US usan ACT/ACT-ISDA; treasuries y eurobonos usan ACT/360 o
// ACT/365 Fixed. Ver ICMA Rule 251.

export function dayCountFraction(from, to, convention = 'ACT/365') {
  if (!from || !to || from === to) return 0
  const pa = parseIso(from); const pb = parseIso(to)
  if (!pa || !pb) return 0

  switch (convention) {
    case '30/360':
    case '30/360 US':
    case 'SIA': {
      // 30/360 US (BMA/SIA): el método más común para bonos USD AR canje 2020.
      // Regla: D1 = min(31, D1) → 30; D2 = 30 si D1 = 30 y D2 = 31, sino D2.
      const [y1, m1, dRaw1] = pa
      const [y2, m2, dRaw2] = pb
      const d1 = Math.min(dRaw1, 30)
      const d2 = (d1 === 30 && dRaw2 === 31) ? 30 : dRaw2
      const days = 360 * (y2 - y1) + 30 * (m2 - m1) + (d2 - d1)
      return days / 360
    }
    case '30E/360':
    case 'ISMA-30/360':
    case 'EUROBOND': {
      // 30E/360 (European): D1 → 30 si D1 = 31; D2 → 30 si D2 = 31. Más simple
      // que 30/360 US, usado en eurobonos.
      const [y1, m1, dRaw1] = pa
      const [y2, m2, dRaw2] = pb
      const d1 = (dRaw1 === 31) ? 30 : dRaw1
      const d2 = (dRaw2 === 31) ? 30 : dRaw2
      const days = 360 * (y2 - y1) + 30 * (m2 - m1) + (d2 - d1)
      return days / 360
    }
    case 'ACT/360':
      return diffDaysUTC(from, to) / 360
    case 'ACT/365':
    case 'ACT/365 Fixed':
      return diffDaysUTC(from, to) / 365
    case 'ACT/365.25':
      // No-standard pero útil para promediar bisiestos sin armar el algoritmo
      // ACT/ACT-ISDA completo. Lo dejamos como backwards-compat (era la
      // convención implícita del estimateYield original).
      return diffDaysUTC(from, to) / 365.25
    case 'ACT/ACT-ISDA':
    case 'ACT/ACT': {
      // ISDA 2006 § 4.16: cada día se cuenta sobre los 365 o 366 días de su
      // propio año. Implementación correcta: partir el período por año
      // calendario y sumar contribuciones.
      const [y1] = pa; const [y2] = pb
      if (y1 === y2) {
        const yLen = isLeap(y1) ? 366 : 365
        return diffDaysUTC(from, to) / yLen
      }
      // Período cruza fronteras de año. Suma:
      //   • Días de `from` a fin de año 1 / días año 1
      //   • Años completos intermedios = 1 cada uno
      //   • Días desde inicio año 2 hasta `to` / días año 2
      const endOfY1 = `${y1}-12-31`
      const startOfY2 = `${y2}-01-01`
      const daysY1 = diffDaysUTC(from, endOfY1) + 1  // incluir 31-dic
      const lenY1 = isLeap(y1) ? 366 : 365
      const daysY2 = diffDaysUTC(startOfY2, to)
      const lenY2 = isLeap(y2) ? 366 : 365
      const yearsMid = (y2 - y1 - 1)
      return (daysY1 / lenY1) + yearsMid + (daysY2 / lenY2)
    }
    default:
      // Convención desconocida → fallback prudente.
      return diffDaysUTC(from, to) / 365
  }
}

function isLeap(y) {
  return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0
}

// ─── Accrued interest ─────────────────────────────────────────────────────────
// Intereses corridos desde el último cupón pagado hasta la fecha de settle.
// Distribución LINEAL del próximo cupón sobre el período corriente, según
// el day-count del prospecto.
//
// Convención: si asOfDate es exactamente fecha de pago, accrued = 0 (post-cupón).
// Si no hay prev (asOfDate antes del primer pago del schedule generado), el
// accrued se calcula desde issueDate si está disponible — sino, devolvemos 0
// con un disclaimer implícito (el caller puede pasar issueDate manualmente).

export function computeAccrued(schedule, asOfDate, convention = '30/360', issueDate = null) {
  if (!schedule || schedule.length === 0 || !asOfDate) return 0
  let prev = null, next = null
  for (const p of schedule) {
    if (p.date <= asOfDate) prev = p
    if (p.date > asOfDate && next == null) next = p
  }
  if (!next) return 0  // Ya venció — no hay siguiente cupón
  const nextCoupon = next.coupon || 0
  if (nextCoupon <= 0) return 0  // Próximo flujo es sólo amort sin cupón

  // Sin prev en el schedule: usar issueDate si fue provisto.
  const periodStart = prev ? prev.date : issueDate
  if (!periodStart) return 0

  const totalPeriod = dayCountFraction(periodStart, next.date, convention)
  const elapsed = dayCountFraction(periodStart, asOfDate, convention)
  if (totalPeriod <= 0) return 0
  // Capear: accrued no puede superar el cupón (el day antes del pago).
  const frac = Math.max(0, Math.min(1, elapsed / totalPeriod))
  return nextCoupon * frac
}

// ─── Yield to Maturity ────────────────────────────────────────────────────────
// Resuelve r tal que sum(cf_i / (1+r)^t_i) = dirtyPrice.
//
// Algoritmo híbrido: bracket → bisect coarse → Newton fine → bisect fine
// fallback. Diseñado para ser ROBUSTO con bond cashflows (siempre positivos,
// NPV monotónicamente decreciente en r) — la combinación garantiza
// convergencia siempre que la raíz esté en el dominio razonable, sin los
// problemas de divergencia que sufre Newton puro.
//
// Inputs:
//   • dirtyPrice: precio sucio (clean + accrued) por 100 face.
//   • cashflows: [{ t, amount }] donde t es la fracción de año al pago (use
//     dayCountFraction para calcular t).
//   • bracket: opcional, default [-0.5, 5.0]. Para bonos en distress se
//     auto-expande hasta [-0.9999, 100].
//   • newtonRelTol: opcional, default 1e-9. Tolerancia sobre Δr para parar.
//
// Output:
//   {
//     ytm: number | null,
//     converged: boolean,
//     method: 'newton' | 'bisect' | 'bracket_failed' | 'no_cashflows' | ...,
//     iterations: number
//   }
//
// El output estructurado permite al caller decidir cuán confiable es y mostrar
// disclaimer si el método no convergió bien (Phase 3E).

export function yieldToMaturity({
  dirtyPrice,
  cashflows,
  bracket = [-0.5, 5.0],
  newtonRelTol = 1e-9,
}) {
  if (typeof dirtyPrice !== 'number' || dirtyPrice <= 0 || !isFinite(dirtyPrice)) {
    return { ytm: null, converged: false, method: 'invalid_price', iterations: 0 }
  }
  if (!cashflows || cashflows.length === 0) {
    return { ytm: null, converged: false, method: 'no_cashflows', iterations: 0 }
  }
  const validCf = cashflows.filter(c =>
    c && typeof c.t === 'number' && typeof c.amount === 'number' &&
    c.t > 0 && c.amount > 0 && isFinite(c.t) && isFinite(c.amount)
  )
  if (validCf.length === 0) {
    return { ytm: null, converged: false, method: 'no_cashflows', iterations: 0 }
  }

  const npv = r => {
    let s = -dirtyPrice
    for (const x of validCf) s += x.amount / Math.pow(1 + r, x.t)
    return s
  }
  const dnpv = r => {
    let s = 0
    for (const x of validCf) s -= x.t * x.amount / Math.pow(1 + r, x.t + 1)
    return s
  }

  // ─── Paso 1: armar bracket con cambio de signo ─────────────────────────────
  let [lo, hi] = bracket
  let fLo = npv(lo); let fHi = npv(hi)

  // Auto-expand si no hay cambio de signo. Bond NPV es monotónicamente
  // decreciente en r, así que:
  //   • si fLo > 0 y fHi > 0: yield mayor a hi → expandir hi (multiplicar).
  //   • si fLo < 0 y fHi < 0: yield menor a lo → expandir lo hacia -1.
  let expansions = 0
  const MAX_EXPANSIONS = 8
  while (fLo * fHi > 0 && expansions < MAX_EXPANSIONS) {
    if (fLo < 0 && fHi < 0) {
      // Necesitamos lo más bajo
      lo = Math.max(-0.9999, lo - (1 + lo) * 0.5)
      if (lo <= -0.9999) {
        fLo = npv(lo); fHi = npv(hi)
        if (fLo * fHi > 0) break  // No hay raíz en dominio razonable
      }
    } else if (fLo > 0 && fHi > 0) {
      // Necesitamos hi más alto
      hi = hi * 2
      if (hi > 100) break  // Yield > 10000% no es bono real
    } else {
      break  // No tiene sentido, monotonicidad rota
    }
    fLo = npv(lo); fHi = npv(hi)
    expansions++
  }
  if (fLo * fHi > 0) {
    return { ytm: null, converged: false, method: 'bracket_failed', iterations: expansions }
  }

  // ─── Paso 2: bisect coarse (10 iter) para tener buen midpoint ──────────────
  for (let i = 0; i < 10; i++) {
    const mid = (lo + hi) / 2
    const fm = npv(mid)
    if (fLo * fm <= 0) { hi = mid; fHi = fm } else { lo = mid; fLo = fm }
  }

  // ─── Paso 3: Newton fine desde el midpoint ─────────────────────────────────
  let r = (lo + hi) / 2
  let newtonIter = 0
  for (let i = 0; i < 50; i++) {
    newtonIter = i + 1
    const f = npv(r)
    if (Math.abs(f) < 1e-10) {
      return { ytm: r, converged: true, method: 'newton', iterations: newtonIter }
    }
    const df = dnpv(r)
    if (!isFinite(df) || Math.abs(df) < 1e-12) break
    let next = r - f / df
    if (!isFinite(next)) break
    // Mantener Newton dentro del bracket — si sale, dar paso pequeño hacia adentro
    if (next < lo) next = (lo + r) / 2
    if (next > hi) next = (hi + r) / 2
    if (Math.abs(next - r) < newtonRelTol) {
      return { ytm: next, converged: true, method: 'newton', iterations: newtonIter }
    }
    r = next
  }

  // ─── Paso 4: bisect fine fallback ──────────────────────────────────────────
  for (let i = 0; i < 80; i++) {
    const mid = (lo + hi) / 2
    const fm = npv(mid)
    if (Math.abs(fm) < 1e-9) {
      return { ytm: mid, converged: true, method: 'bisect', iterations: 10 + newtonIter + i + 1 }
    }
    if (fLo * fm <= 0) { hi = mid; fHi = fm } else { lo = mid; fLo = fm }
  }

  // Convergencia parcial: devolvemos el midpoint pero marcamos converged=false.
  return { ytm: (lo + hi) / 2, converged: false, method: 'max_iter', iterations: 140 }
}

// ─── Conversiones clean ↔ dirty ───────────────────────────────────────────────

export function cleanToDirty(cleanPrice, accrued) {
  if (cleanPrice == null) return null
  return cleanPrice + (accrued || 0)
}

export function dirtyToClean(dirtyPrice, accrued) {
  if (dirtyPrice == null) return null
  return dirtyPrice - (accrued || 0)
}

// ─── Conversión TIR semestral ↔ efectiva anual ────────────────────────────────
// Para bonos semestrales con TIR de mercado expresada habitualmente en TNA
// (nominal anual = TIR semestral × 2), convertir a EAR (effective annual rate)
// es: (1 + r_sem)^2 − 1. Útil para reportar la TIR de forma comparable a un
// plazo fijo (que usa TNA con capitalización 30 días) o un FCI (que reporta
// rendimiento histórico efectivo).

export function semiAnnualToEffectiveAnnual(rSemi) {
  if (rSemi == null || !isFinite(rSemi)) return null
  return Math.pow(1 + rSemi, 2) - 1
}

export function effectiveAnnualToSemiAnnual(rEar) {
  if (rEar == null || !isFinite(rEar)) return null
  return Math.pow(1 + rEar, 0.5) - 1
}
