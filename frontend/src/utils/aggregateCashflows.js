// aggregateCashflows — el calendario de cobros de VARIOS clientes, en el navegador.
// ═══════════════════════════════════════════════════════════════════════════
// El servidor (/advisor/cashflows/positions) entrega qué renta fija tiene cada
// cliente; acá se corre el MISMO motor de cronograma que usa la Cartera
// (`bondSchedule.js` + `bondMeta.js`) una vez por (cliente, ticker) y se suma.
// No hay una segunda copia del cálculo financiero: si el cronograma de un bono
// está mal, está mal en un solo lugar.
//
// Las LETRAS son la excepción al "todo sale del catálogo del frontend": no
// tienen prospecto (devuelven todo junto al vencer, y capitalizan), así que su
// único pago lo calcula el servidor con el precio de mercado y viaja en
// `opts.letras`. Es una ESTIMACIÓN y sale marcada como tal — se muestra, no se
// registra.
//
// Monedas — dos cosas distintas que no se mezclan:
//   • `account_currency` (viene del servidor): la PATA donde está el título. No
//     se usa para convertir nada.
//   • `meta.currency` (catálogo del frontend): en qué PAGA el bono. Es la única
//     que decide si el monto se pasa a dólares con el MEP. Misma regla que la
//     zona Renta Fija de la Cartera (`RentaFijaSections.jsx`).
import { getBondMeta } from './bondMeta'
import { getRemainingPayments, cerOptsFor } from './bondSchedule'
import { hoyISO } from './fecha'

/** Suma días a un ISO sin corrimiento de huso. */
export function addDaysIso(iso, days) {
  const d = new Date(iso + 'T00:00:00')
  d.setDate(d.getDate() + days)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${dd}`
}

/** Fin del rango elegido: 30 / 90 días, o el 31 de diciembre del año en curso. */
export function rangeEnd(range, today = hoyISO()) {
  if (range === 'year') return `${today.slice(0, 4)}-12-31`
  const days = range === '30d' ? 30 : 90
  return addDaysIso(today, days)
}

/** Un fin de semana no acredita: el pago entra el lunes siguiente. */
export function settlementNote(iso) {
  const dow = new Date(iso + 'T00:00:00').getDay()
  if (dow === 6) return 'cae sábado · se acredita el lunes'
  if (dow === 0) return 'cae domingo · se acredita el lunes'
  return null
}

/**
 * Arma el calendario.
 *
 * @param positions  [{client_uid, asset, quantity, account_currency, category}]
 * @param clients    [{client_uid, label}]
 * @param opts       { today, range: '30d'|'90d'|'year', end (ISO, pisa a range), tcMep,
 *                     cerSeries, letras: {TICKER: {maturity, payout_per_100, currency}} }
 * @returns {{
 *   days: [{date, totalUsd, payments: [{asset, kind, totalUsd, totalNative,
 *           payCurrency, estimated, estimateKind: 'cer'|'letra'|null,
 *           holders: [{client_uid, label, amountUsd}]}]}],
 *   byClient: [{client_uid, label, totalUsd, count, assets}],
 *   totals: {usd30, count30, usdRange, countRange},
 *   sinCronograma: [asset],
 *   clientesSinCobros: [{client_uid,label}]
 * }}
 */
export function aggregateCashflows(positions, clients, opts = {}) {
  const today = opts.today || hoyISO()
  const range = opts.range || '90d'
  const end = opts.end || rangeEnd(range, today)
  const in30 = addDaysIso(today, 30)
  const tc = opts.tcMep > 0 ? opts.tcMep : null
  const letras = opts.letras || {}
  const labelOf = new Map((clients || []).map(c => [c.client_uid, c.label]))

  // Un bono en pesos sin cotización no se convierte: mostrar un dólar inventado
  // es peor que decir "en pesos". `toUsd` devuelve null en ese caso y la fila
  // conserva `totalNative` para mostrarlo igual.
  const toUsd = (amount, payCcy) => {
    if (payCcy !== 'ARS') return amount
    return tc ? amount / tc : null
  }

  const byKey = new Map()          // `${date}|${asset}` → payment
  const sinCronograma = new Set()
  const planCache = new Map()      // asset → {sched, payCcy, estimateKind, maturity} | null

  // Plan de pagos de un ticker: del catálogo de bonos, o del de letras que manda
  // el servidor. Una letra no tiene prospecto que catalogar —devuelve todo junto
  // al vencer, y CAPITALIZA— así que su pago lo trae el servidor leído del
  // mercado (`pricing/letras.py`); acá sólo se lo pone en el calendario.
  const planFor = (asset) => {
    if (planCache.has(asset)) return planCache.get(asset)
    let plan = null
    const meta = getBondMeta(asset)
    if (meta?.maturity) {
      const sched = getRemainingPayments(asset, today, cerOptsFor(asset, opts.cerSeries))
      if (sched && sched.length > 0) {
        plan = {
          sched,
          payCcy: meta.currency === 'ARS' ? 'ARS' : 'USD',
          maturity: meta.maturity,
          // CER: el cupón futuro depende de un índice que todavía no existe. Se
          // muestra, pero marcado; con la serie caída ni siquiera está ajustado.
          estimateKind: meta.type === 'cer' ? 'cer' : null,
        }
      }
    } else {
      const l = letras[asset]
      // `> today` como los bonos (`getRemainingPayments`): el cobro de hoy ya no
      // es un cobro por venir. El servidor ya filtra, pero su "hoy" se calculó
      // cuando respondió y este es el del navegador.
      if (l?.maturity && l.payout_per_100 > 0 && l.maturity > today) {
        plan = {
          sched: [{ date: l.maturity, coupon: 0, amort: l.payout_per_100, total: l.payout_per_100 }],
          payCcy: l.currency === 'USD' ? 'USD' : 'ARS',
          maturity: l.maturity,
          estimateKind: 'letra',
        }
      }
    }
    planCache.set(asset, plan)
    return plan
  }

  for (const p of positions || []) {
    const asset = (p.asset || '').toUpperCase()
    const qty = Number(p.quantity) || 0
    if (!asset || qty <= 0) continue
    const plan = planFor(asset)
    if (!plan) { sinCronograma.add(asset); continue }
    const { sched, payCcy, estimateKind } = plan

    for (const s of sched) {
      if (s.date > end) break
      // Misma escala que `nextPaymentForPosition`: el cronograma es por 100 nominales.
      const native = +((s.total * qty) / 100).toFixed(2)
      if (native <= 0) continue
      const key = `${s.date}|${asset}`
      let pay = byKey.get(key)
      if (!pay) {
        const kind = s.coupon > 0 && s.amort > 0 ? 'cupon+amort'
          : s.amort > 0 ? (s.date === plan.maturity ? 'vencimiento' : 'amort')
          : 'cupon'
        pay = { date: s.date, asset, kind, payCurrency: payCcy,
                estimated: !!estimateKind, estimateKind,
                totalNative: 0, totalUsd: 0, holders: [] }
        byKey.set(key, pay)
      }
      pay.totalNative = +(pay.totalNative + native).toFixed(2)
      const usd = toUsd(native, payCcy)
      pay.totalUsd = usd == null ? null : +((pay.totalUsd ?? 0) + usd).toFixed(2)
      const label = labelOf.get(p.client_uid) || `Cliente ${p.client_uid}`
      const h = pay.holders.find(x => x.client_uid === p.client_uid)
      if (h) {
        h.amountNative = +(h.amountNative + native).toFixed(2)
        h.amountUsd = usd == null ? null : +((h.amountUsd ?? 0) + usd).toFixed(2)
      } else {
        pay.holders.push({ client_uid: p.client_uid, label, amountNative: native,
                           amountUsd: usd == null ? null : +usd.toFixed(2) })
      }
    }
  }

  // Días → pagos ordenados por monto; días ordenados por fecha.
  const daysMap = new Map()
  for (const pay of byKey.values()) {
    pay.holders.sort((a, b) => (b.amountUsd ?? 0) - (a.amountUsd ?? 0) || a.label.localeCompare(b.label))
    let d = daysMap.get(pay.date)
    if (!d) { d = { date: pay.date, totalUsd: 0, payments: [], note: settlementNote(pay.date) }; daysMap.set(pay.date, d) }
    d.payments.push(pay)
    if (pay.totalUsd != null) d.totalUsd = +(d.totalUsd + pay.totalUsd).toFixed(2)
  }
  const days = [...daysMap.values()].sort((a, b) => a.date.localeCompare(b.date))
  for (const d of days) d.payments.sort((a, b) => (b.totalUsd ?? 0) - (a.totalUsd ?? 0) || a.asset.localeCompare(b.asset))

  // Por cliente, sobre el rango.
  const perClient = new Map()
  for (const d of days) for (const pay of d.payments) for (const h of pay.holders) {
    let c = perClient.get(h.client_uid)
    if (!c) { c = { client_uid: h.client_uid, label: h.label, totalUsd: 0, count: 0, assets: new Set() }; perClient.set(h.client_uid, c) }
    if (h.amountUsd != null) c.totalUsd = +(c.totalUsd + h.amountUsd).toFixed(2)
    c.count += 1
    c.assets.add(pay.asset)
  }
  const byClient = [...perClient.values()]
    .map(c => ({ ...c, assets: [...c.assets].sort() }))
    .sort((a, b) => b.totalUsd - a.totalUsd || a.label.localeCompare(b.label))

  const totals = { usd30: 0, count30: 0, usdRange: 0, countRange: 0 }
  for (const d of days) for (const pay of d.payments) {
    totals.countRange += 1
    if (pay.totalUsd != null) totals.usdRange = +(totals.usdRange + pay.totalUsd).toFixed(2)
    if (d.date <= in30) {
      totals.count30 += 1
      if (pay.totalUsd != null) totals.usd30 = +(totals.usd30 + pay.totalUsd).toFixed(2)
    }
  }

  const conCobros = new Set(byClient.map(c => c.client_uid))
  const clientesSinCobros = (clients || []).filter(c => !conCobros.has(c.client_uid))

  return { days, byClient, totals, sinCronograma: [...sinCronograma].sort(), clientesSinCobros, end }
}

/** Agrupa los días por mes 'YYYY-MM' conservando el orden. */
export function groupDaysByMonth(days) {
  const out = []
  for (const d of days) {
    const ym = d.date.slice(0, 7)
    let m = out[out.length - 1]
    if (!m || m.ym !== ym) { m = { ym, totalUsd: 0, days: [] }; out.push(m) }
    m.days.push(d)
    m.totalUsd = +(m.totalUsd + d.totalUsd).toFixed(2)
  }
  return out
}
