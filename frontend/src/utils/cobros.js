// cobros.js — las cuentas de la pestaña Cobros (Movimientos › Cobros).
// ════════════════════════════════════════════════════════════════════════════
// Lo COBRADO no se calcula acá: viene armado de GET /api/cobros, que agrupa las
// mismas filas de Movimientos (backend/cobros.py), cada una en dólares del día
// en que se cobró. Acá vive lo que necesita piezas que sólo tiene el frontend:
//
//   • El ESTIMADO de los próximos 12 meses, con dos fuentes y nada inventado:
//       – Bonos: el cronograma (`upcomingBondEvents`, el mismo de Novedades),
//         sólo la parte de CUPÓN. La amortización es capital que vuelve.
//       – Acciones, CEDEARs y ETFs que seguís teniendo: lo que te pagaron en los
//         últimos 12 meses, otra vez en la misma fecha un año después. Es lo
//         único que se puede respaldar: Novedades sólo conoce el PRÓXIMO
//         dividendo de cada empresa, no cuántos paga por año.
//     Lo que no entra se dice (`sinHistoria`, `sinActivoUsd`), no se rellena.
//   • El PRÓXIMO COBRO: el más cercano entre el cronograma de los bonos, los
//     dividendos ya anunciados (`/api/events/portfolio` + `dividendPayout`, la
//     misma cuenta de Novedades) y lo estimado por la historia.
//   • Las BARRAS por mes, trimestre o año.

import { isBondTicker, cedearEspecieBase } from './tickers'
import { dividendPayout } from './upcomingEvents'

export const MESES_CORTOS = ['E', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
  'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']

/** La misma especie con cualquier sufijo: "AAPL.BA", "aapl" y "AAPL" son una. */
export function claveActivo(asset) {
  return cedearEspecieBase(asset || '')
}

/** "14 de noviembre" */
export function fechaLarga(iso) {
  if (!iso) return ''
  const [, m, d] = iso.split('-').map(Number)
  return `${d} de ${MESES[m - 1]}`
}

/** La misma fecha `n` años después. El 29/2 de un año no bisiesto cae al 28. */
export function sumarAnios(iso, n) {
  const y = Number(iso.slice(0, 4)) + n
  const md = iso.slice(5, 10)
  if (md === '02-29' && !((y % 4 === 0 && y % 100 !== 0) || y % 400 === 0)) return `${y}-02-28`
  return `${y}-${md}`
}

/** Cómo se rotula un activo de la lista: cupón si es un bono, si no por el tipo. */
export function tipoDeCobro(activo, tipos = []) {
  if (!activo) return 'Sin activo'
  if (isBondTicker(activo)) return 'Cupones'
  if (tipos.length === 1 && tipos[0] === 'INTEREST') return 'Intereses'
  if (tipos.includes('INTEREST')) return 'Dividendos e intereses'
  return 'Dividendos'
}

/** Los activos que tenés hoy (sin el efectivo), por especie. */
export function tenencias(positions) {
  const out = new Set()
  for (const p of positions || []) {
    if (p.is_cash || !(Number(p.quantity) > 0)) continue
    out.add(claveActivo(p.asset))
  }
  return out
}

/** Un monto del cronograma en dólares. En pesos, con el dólar de hoy (es un
 *  cobro futuro: no hay "dólar de su día" todavía). null si no hay dólar. */
function aDolares(monto, moneda, tc) {
  if (!(monto > 0)) return 0
  if (String(moneda || 'USD').toUpperCase() !== 'ARS') return monto
  return tc > 0 ? monto / tc : null
}

/**
 * El estimado de los próximos 12 meses.
 *
 * @param {object} p
 * @param {Array}  p.ultimos12     `ultimos_12_meses` de /api/cobros
 * @param {Array}  p.positions     /api/positions
 * @param {Array}  p.eventosBonos  upcomingBondEvents(positions, { windowDays: 365 })
 * @param {Array}  p.anunciados    tickers con un dividendo anunciado (Novedades)
 * @param {number} p.tc            dólar de hoy, para los cupones en pesos
 * @returns {{ total, items, sinHistoria, sinActivoUsd, cuponesSinDolar }}
 *   items: [{ fecha, activo, usd, fuente: 'cronograma' | 'historia' }]
 */
export function estimarProximos12({ ultimos12 = [], positions = [], eventosBonos = [], anunciados = [], tc } = {}) {
  const tengo = tenencias(positions)
  const items = []
  let sinActivoUsd = 0
  let cuponesSinDolar = 0

  for (const c of ultimos12) {
    if (!c.activo) { sinActivoUsd += c.usd; continue }      // no se sabe si lo seguís teniendo
    if (isBondTicker(c.activo)) continue                     // los bonos van por el cronograma
    if (!tengo.has(claveActivo(c.activo))) continue          // ya no lo tenés
    items.push({ fecha: sumarAnios(c.fecha, 1), activo: claveActivo(c.activo), usd: c.usd, fuente: 'historia' })
  }

  for (const e of eventosBonos) {
    const usd = aDolares(e.details?.coupon, e.details?.currency, tc)
    if (usd == null) { cuponesSinDolar += 1; continue }
    if (usd > 0) items.push({ fecha: e.eventDate, activo: e.ticker, usd, fuente: 'cronograma' })
  }

  const conHistoria = new Set(items.filter(i => i.fuente === 'historia').map(i => i.activo))
  const sinHistoria = [...new Set(anunciados.map(claveActivo))]
    .filter(t => !conHistoria.has(t) && !isBondTicker(t))
    .sort()

  items.sort((a, b) => a.fecha.localeCompare(b.fecha))
  const total = items.reduce((s, i) => s + i.usd, 0)
  return { total, items, sinHistoria, sinActivoUsd, cuponesSinDolar }
}

/** De los eventos de Novedades, el dividendo anunciado más cercano de cada empresa
 *  (la fecha de PAGO si está; si no, la de corte). */
export function dividendosAnunciados(eventos = [], hoy) {
  const porTicker = new Map()
  for (const e of eventos) {
    if (e.eventType !== 'payment_date' && e.eventType !== 'ex_dividend') continue
    if (!e.eventDate || e.eventDate <= hoy) continue
    const t = claveActivo(e.ticker)
    const prev = porTicker.get(t)
    const mejor = !prev
      || (e.eventType === 'payment_date' && prev.eventType !== 'payment_date')
      || (e.eventType === prev.eventType && e.eventDate < prev.eventDate)
    if (mejor) porTicker.set(t, e)
  }
  return [...porTicker.values()]
}

/**
 * El próximo cobro: el más cercano de los tres orígenes. Un dividendo anunciado
 * manda sobre lo estimado por la historia de esa misma empresa.
 * @returns {{ activo, fecha, usd, fuente, bruto, conAmortizacion } | null}
 */
export function proximoCobro({ estimado, eventosBonos = [], anunciados = [], positions = [], prices, tcCedear, tc } = {}) {
  const candidatos = []
  for (const e of eventosBonos) {
    const usd = aDolares(e.details?.total, e.details?.currency, tc)
    if (!(usd > 0)) continue
    candidatos.push({ activo: e.ticker, fecha: e.eventDate, usd, fuente: 'cronograma',
      conAmortizacion: e.details?.amort > 0 })
  }
  const anunciadosTickers = new Set()
  for (const e of anunciados) {
    anunciadosTickers.add(claveActivo(e.ticker))
    const pago = dividendPayout(e, positions, { prices, tc: tcCedear })
    candidatos.push({ activo: claveActivo(e.ticker), fecha: e.eventDate,
      usd: pago?.amount > 0 ? pago.amount : null, fuente: 'anunciado', bruto: true,
      corte: e.eventType === 'ex_dividend' })
  }
  for (const i of estimado?.items || []) {
    if (i.fuente !== 'historia' || anunciadosTickers.has(i.activo)) continue
    candidatos.push({ ...i })
  }
  if (!candidatos.length) return null
  const orden = { cronograma: 0, anunciado: 1, historia: 2 }
  candidatos.sort((a, b) => a.fecha.localeCompare(b.fecha) || orden[a.fuente] - orden[b.fuente])
  return candidatos[0]
}

/**
 * Las barras del gráfico. Cada una: { clave, etiqueta, cobrado, estimado, anterior }.
 *   'mes'       → los 12 meses del año en curso contra los del año anterior.
 *   'trimestre' → lo mismo, de a tres meses.
 *   'anio'      → un año por barra, desde el primero con cobros (sin comparación).
 * `estimado` es lo que falta del año según el estimado: sólo cae en el mes de hoy
 * y los siguientes, porque sus fechas son todas posteriores a hoy.
 */
export function barras(resumen, estimado, vista = 'mes') {
  if (!resumen) return []
  const anio = resumen.anio
  const estPorMes = Array(12).fill(0)
  for (const i of estimado?.items || []) {
    if (Number(i.fecha.slice(0, 4)) !== anio) continue
    estPorMes[Number(i.fecha.slice(5, 7)) - 1] += i.usd
  }
  const meses = resumen.por_mes.map((m, k) => ({
    clave: `m${m.mes}`, etiqueta: MESES_CORTOS[k],
    cobrado: m.anio, estimado: estPorMes[k], anterior: m.anterior,
  }))
  if (vista === 'mes') return meses
  if (vista === 'trimestre') {
    return [0, 1, 2, 3].map(q => {
      const tres = meses.slice(q * 3, q * 3 + 3)
      const suma = (k) => tres.reduce((s, m) => s + m[k], 0)
      return { clave: `t${q + 1}`, etiqueta: `T${q + 1}`,
        cobrado: suma('cobrado'), estimado: suma('estimado'), anterior: suma('anterior') }
    })
  }
  const porAnio = new Map((resumen.por_anio || []).map(a => [a.anio, a.usd]))
  const primero = Math.min(anio, ...porAnio.keys())
  const out = []
  for (let y = primero; y <= anio; y++) {
    out.push({ clave: `a${y}`, etiqueta: String(y), cobrado: porAnio.get(y) || 0,
      estimado: y === anio ? estPorMes.reduce((s, v) => s + v, 0) : 0, anterior: null })
  }
  return out
}

/** % contra el mismo período del año anterior. null si no hay con qué comparar. */
export function variacionAnual(resumen) {
  const base = resumen?.total_anterior_a_la_fecha
  if (!(base > 0)) return null
  return (resumen.total_anio - base) / base
}
