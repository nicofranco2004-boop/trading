// bondSchedule.js — cronograma de pagos + TIR estimada por bono.
// ════════════════════════════════════════════════════════════════════════════
// Fase 2 del Bonos MVP. Consume el bondMeta y genera, por ticker, la lista
// completa de payments (cupones + amortizaciones + face return al vencimiento)
// expresada en "USD por 100 nominal" (o ARS por 100 si el bono es ARS).
//
// Tres comportamientos según el tipo de bono:
//   • Amortizante (sovereign con amortStart/amortCount): el face se devuelve
//     en cuotas iguales semestrales arrancando en amortStart. El cupón se
//     calcula sobre el face REMANENTE — así el flujo cupón decrece a medida
//     que las amortizaciones devuelven principal.
//   • Bullet (corporate/cer sin amort): pagos de cupón a la frecuencia
//     correspondiente, y la última fecha (maturity) suma 100 al face.
//   • Zero-cupón (couponFreq='none'): un único pago = 100 al vencimiento.
//   • ETF de bonos (sin maturity): retorna null — no hay schedule definido.
//
// Convención: el schedule expresa todo POR 100 de face value original
// (estándar de mercado: precios y cupones se cotizan por 100 nominal).
// Para el monto que recibirá una posición específica, multiplicar por
// (quantity / 100). Si el user maneja "nominales" donde 1 unit = 1 USD
// face, entonces el factor es quantity * payment_per_100 / 100.
//
// La TIR se estima con Newton-Raphson sobre los flujos remanentes. Una vez
// vencido el bono o sin flujos futuros, devuelve null. Para valores razonables
// converge en ~10 iteraciones; cap a 100 por seguridad.

import { getBondMeta } from './bondMeta'

const ISO_RE = /^\d{4}-\d{2}-\d{2}$/

// Días entre 2 fechas ISO (yyyy-mm-dd). Robusto frente a DST: comparamos en
// UTC midnight, así que el resultado es siempre días enteros.
function diffDays(a, b) {
  const ta = Date.UTC(+a.slice(0, 4), +a.slice(5, 7) - 1, +a.slice(8, 10))
  const tb = Date.UTC(+b.slice(0, 4), +b.slice(5, 7) - 1, +b.slice(8, 10))
  return Math.round((tb - ta) / (1000 * 60 * 60 * 24))
}

// Suma N meses a una fecha ISO conservando el día. Si el día no existe en el
// mes destino (e.g. 31 de enero + 1 mes = 28 de feb), cae al último día del
// mes destino. Aproximación suficiente para schedules semestrales/anuales.
export function addMonths(iso, months) {
  if (!ISO_RE.test(iso)) return null
  const y = +iso.slice(0, 4)
  const m = +iso.slice(5, 7)
  const d = +iso.slice(8, 10)
  // Trabajamos en UTC para evitar problemas de timezone
  const date = new Date(Date.UTC(y, m - 1, d))
  const targetMonth = (m - 1) + months
  date.setUTCFullYear(y + Math.floor(targetMonth / 12))
  date.setUTCMonth(((targetMonth % 12) + 12) % 12)
  // Si el día se "fue" al mes siguiente por overflow, ajustamos al último día del mes
  const targetMonthIdx = ((m - 1 + months) % 12 + 12) % 12
  if (date.getUTCMonth() !== targetMonthIdx) {
    date.setUTCDate(0)  // último día del mes anterior
  }
  return date.toISOString().slice(0, 10)
}

// Meses entre pagos según la frecuencia del cupón.
function monthsForFreq(freq) {
  switch (freq) {
    case 'monthly':    return 1
    case 'quarterly':  return 3
    case 'semiannual': return 6
    case 'annual':     return 12
    default:           return null  // 'none' o desconocido
  }
}

// Genera el cronograma COMPLETO (todos los pagos históricos + futuros) para
// el ticker dado. Devuelve null si el bono no tiene metadata o no aplica
// (ej: ETF sin maturity).
//
// Cada entry: { date, coupon, amort, total }
//   • date: 'YYYY-MM-DD'
//   • coupon: monto del cupón en esa fecha, por 100 face original
//   • amort: monto de amortización en esa fecha, por 100 face original
//   • total: coupon + amort (conveniencia)
//
// La última fecha es siempre maturity. Para bonos bullet, esa fecha incluye
// face=100 en el campo amort. Para zero-coupon, esa fecha incluye sólo amort=100.
export function generateSchedule(ticker) {
  const meta = getBondMeta(ticker)
  if (!meta) return null
  if (!meta.maturity) return null  // ETFs sin maturity → no schedule
  const { maturity, couponRate, couponFreq, amortStart, amortCount } = meta

  // Caso zero-cupón: pago único = 100 al vencimiento
  if (couponFreq === 'none' || !couponRate) {
    return [{ date: maturity, coupon: 0, amort: 100, total: 100 }]
  }

  const months = monthsForFreq(couponFreq)
  if (months == null) return null  // freq desconocida

  // Para amortizing bonds, la primera fecha del schedule es la fecha más
  // antigua entre (maturity - N*months hasta cubrir hasta amortStart) y un
  // mínimo razonable (5 años antes de maturity).
  // Para bullet bonds, contamos hacia atrás desde maturity.
  // El payment grid son fechas EQUIESPACIADAS a `months` desde maturity hacia atrás,
  // limitado por (5 años antes de maturity) o (amortStart - una freq) según corresponda.

  // Construimos la grilla hacia atrás desde maturity hasta cubrir al menos
  // ~5 años (suficiente para el histórico de cobranzas + futuro relevante).
  // Si hay amortStart, garantizamos que la grilla incluya esa fecha y todas
  // las posteriores.
  const dates = [maturity]
  // Mínimo: maturity menos 5 años (60 meses). Si hay amortStart anterior,
  // arrancamos antes para cubrirlo también.
  const minBack = amortStart || addMonths(maturity, -60)
  let cursor = maturity
  while (true) {
    const prev = addMonths(cursor, -months)
    if (!prev || prev < minBack) break
    dates.unshift(prev)
    cursor = prev
  }

  // Si hay amortStart pero no quedó en la grilla (puede pasar si los meses
  // no caen exactos), lo metemos a mano. Esto es defensivo: en la práctica
  // amortStart cae en la grilla porque los amorts son semestrales en las
  // mismas fechas que los cupones.
  if (amortStart && !dates.includes(amortStart)) {
    dates.push(amortStart)
    dates.sort()
  }

  // Construimos los pagos, calculando face remanente paso a paso.
  // - Face inicial = 100
  // - En cada fecha amort, devolvemos amortAmount = 100/amortCount
  // - El cupón en esa fecha = (couponRate / freq) × face_remanente_pre_amort
  // - Después del último amort, face = 0
  // - Si es bullet (sin amortStart): face permanece 100 hasta maturity,
  //   donde se devuelve.
  const couponPerPeriod = couponRate / (12 / months)  // % anual / # periodos por año
  const isAmortizing = !!(amortStart && amortCount)
  const amortAmount = isAmortizing ? 100 / amortCount : 0
  const amortDates = isAmortizing
    ? dates.filter(d => d >= amortStart).slice(0, amortCount)
    : [maturity]  // bullet: face vuelve en maturity

  let face = 100
  const schedule = []
  for (const date of dates) {
    // Pre-amort face (para el cupón): es lo que QUEDA antes de pagar el amort de hoy
    const couponAmount = +(couponPerPeriod * face / 100).toFixed(6)
    let amortOnThisDate = 0
    if (amortDates.includes(date)) {
      if (isAmortizing) {
        amortOnThisDate = amortAmount
      } else {
        // Bullet: maturity devuelve todo el face remanente
        amortOnThisDate = face
      }
    }
    schedule.push({
      date,
      coupon: couponAmount,
      amort: +amortOnThisDate.toFixed(6),
      total: +(couponAmount + amortOnThisDate).toFixed(6),
    })
    face = Math.max(0, face - amortOnThisDate)
  }

  // Sanity: si después de todos los pagos sobró face (puede pasar por
  // approximations de fechas), forzar que el último pago devuelva lo que queda.
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

// TIR estimada (yield to maturity) anualizada en decimal. Newton-Raphson sobre
// los flujos remanentes vs el precio actual (precio por 100 face, mismo
// convención que el schedule).
//
// Devuelve null si:
//   • No hay schedule para el ticker
//   • No quedan pagos futuros (bono ya venció)
//   • El precio es ≤ 0
//   • Newton no converge
//
// Inputs:
//   ticker: string
//   pricePer100: precio actual del bono "por 100 face". Si el broker reporta
//     un precio "por 1 nominal" (e.g. 0.715), multiplicar por 100 antes.
//   from: fecha base (opcional, default hoy). El tiempo a cada flujo se
//     calcula en años decimales (días / 365.25).
export function estimateYield(ticker, pricePer100, from) {
  if (!pricePer100 || pricePer100 <= 0) return null
  const rest = getRemainingPayments(ticker, from)
  if (!rest || rest.length === 0) return null
  const base = from || todayIso()

  // Cashflows: [{ t_years, amount_per_100 }, ...]
  const cashflows = rest
    .map(p => ({ t: diffDays(base, p.date) / 365.25, amount: p.total }))
    .filter(cf => cf.t > 0 && cf.amount > 0)
  if (cashflows.length === 0) return null

  // Newton-Raphson. f(r) = sum(amount_i / (1+r)^t_i) - price = 0
  //                  f'(r) = sum(-t_i * amount_i / (1+r)^(t_i+1))
  let r = 0.10  // initial guess: 10%
  for (let i = 0; i < 100; i++) {
    let f = -pricePer100
    let df = 0
    for (const cf of cashflows) {
      const v = cf.amount / Math.pow(1 + r, cf.t)
      f += v
      df += -cf.t * v / (1 + r)
    }
    if (!isFinite(f) || !isFinite(df) || Math.abs(df) < 1e-12) return null
    const delta = f / df
    r = r - delta
    if (!isFinite(r)) return null
    // Bound r en [-0.99, 10] (TIRs absurdas indican input mal o no converge)
    if (r < -0.99) r = -0.99
    if (r > 10) r = 10
    if (Math.abs(delta) < 1e-8) return r
  }
  // No convergió — devolvemos null en lugar de un número engañoso
  return null
}

// Para una posición de bono con `quantity` (en nominales, donde 1 nominal = 1
// unidad de face value), devuelve el monto del próximo pago en moneda del
// bono. Útil para mostrar al user "tu próximo cobro estimado".
export function nextPaymentForPosition(ticker, quantity, from) {
  const next = getNextPayment(ticker, from)
  if (!next || !quantity) return null
  // next.total está expresado por 100 face. Si qty=1000 nominales (=1000 face),
  // el monto recibido = qty × total / 100.
  return {
    date: next.date,
    coupon: +(next.coupon * quantity / 100).toFixed(2),
    amort: +(next.amort * quantity / 100).toFixed(2),
    total: +(next.total * quantity / 100).toFixed(2),
    isPureAmort: next.coupon === 0 && next.amort > 0,
    isPureCoupon: next.amort === 0 && next.coupon > 0,
  }
}
