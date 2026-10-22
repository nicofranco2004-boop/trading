// cobros.js — las cuentas de la pestaña Cobros (Movimientos › Cobros).
// ════════════════════════════════════════════════════════════════════════════
// GET /api/cobros manda los cobros RENGLÓN POR RENGLÓN (backend/cobros.py): las
// mismas filas de Movimientos, cada una en dólares del día en que se cobró. Acá
// viven, en UN solo lugar, todas las cuentas que salen de ahí:
//
//   • LAS SUMAS (`resumirCobros`): por mes, por año, por activo, contra el año
//     anterior. Viven acá y no en el servidor porque una parte de los cupones
//     sólo se puede separar con el cronograma de cada bono, que vive en el
//     frontend (utils/bondSchedule.js, el mismo de Eventos).
//   • EL CUPÓN DE UN PAGO MIXTO (`cuponDelPago`): el broker a veces trae el
//     cupón y la amortización en un renglón ("Renta y Amortización"). La parte
//     de cupón es la proporción cupón / (cupón + amortización) que dice el
//     cronograma para ese pago. Si el cronograma no lo tiene, no se adivina: el
//     pago queda afuera y la pantalla lo dice.
//   • EL ESTIMADO de los próximos 12 meses, con dos fuentes y nada inventado:
//       – Bonos: el cronograma (`upcomingBondEvents`), sólo la parte de CUPÓN.
//       – Acciones, CEDEARs y ETFs que seguís teniendo: lo que te pagaron en los
//         últimos 12 meses, en la misma fecha un año después, AJUSTADO a lo que
//         tenés hoy contra lo que tenías al cobrar (`cantidadEn`). Si la cantidad
//         de entonces no se puede saber, va sin ajustar y la pantalla lo dice.
//   • EL PRÓXIMO COBRO: el más cercano entre el cronograma, los dividendos
//     anunciados (con `eventCobro`, la misma cuenta que la agenda de Eventos) y
//     lo estimado por la historia.
//   • LAS BARRAS por mes, trimestre o año.

import { isBondTicker, cedearEspecieBase } from './tickers'
import { eventCobro } from './upcomingEvents'
import { generateSchedule, cerOptsFor } from './bondSchedule'
import { underlyingShares } from './cedearRatio'
import { esTradeCerrado } from './tradeStats'
import { DATE_TOLERANCE_DAYS } from './pendingCashflows'

export const MESES_CORTOS = ['E', 'F', 'M', 'A', 'M', 'J', 'J', 'A', 'S', 'O', 'N', 'D']
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
  'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
const DIA_MS = 86400000

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

function sumarDias(iso, n) {
  return new Date(Date.parse(iso + 'T00:00:00Z') + n * DIA_MS).toISOString().slice(0, 10)
}

/** Cómo se rotula un activo de la lista: cupón si es un bono, si no por el tipo. */
export function tipoDeCobro(activo, tipos = []) {
  if (!activo) return 'Sin activo'
  if (isBondTicker(activo)) return 'Cupones'
  if (tipos.length === 1 && tipos[0] === 'INTEREST') return 'Intereses'
  if (tipos.includes('INTEREST')) return 'Dividendos e intereses'
  return 'Dividendos'
}

/**
 * La parte de CUPÓN de un pago que el broker trajo junto con la amortización.
 * La proporción sale del cronograma del bono para el pago a ±14 días (la misma
 * tolerancia que la bandeja de cupones, `DATE_TOLERANCE_DAYS`). El ajuste CER
 * multiplica a las dos partes, así que la proporción no cambia; igual se pasa
 * la serie, como en todo lugar que lee el cronograma (cerBasisProps.test.js).
 * @returns {number|null} dólares de cupón, o null si el cronograma no lo respalda.
 */
export function cuponDelPago({ fecha, activo, usd }, cerSeries) {
  const cron = generateSchedule(activo, cerOptsFor(activo, cerSeries))
  if (!cron) return null
  const t = Date.parse(fecha + 'T00:00:00Z')
  const pago = cron.find(p => Math.abs(Date.parse(p.date + 'T00:00:00Z') - t) <= DATE_TOLERANCE_DAYS * DIA_MS)
  if (!pago || !(pago.total > 0)) return null
  return usd * (pago.coupon / pago.total)
}

// ─── LA cuenta de cuánto se cobró ────────────────────────────────────────────
// Movimientos ("Cobrado", el total del filtro Dividendos/Intereses) y la pestaña
// Cobros cuentan con ESTAS dos funciones, sobre las mismas filas: qué fila es un
// cobro lo decide el servidor (`cobros.clase_de_cobro`, viaja como `cobro` en
// cada fila de /api/movements) y cuánto cuenta, `montoCobrado`. Antes Cobros
// separaba el cupón de los pagos mixtos y "Cobrado" no: dos números para lo
// mismo (pedido de Nico, 2026-10-22: que coincidan).

/** Una fila de Movimientos como fila de cobro ({ fecha, activo, tipo, usd }),
 *  con la misma forma que /api/cobros. null si no es un cobro. */
export function filaDeMovimiento(m) {
  // Una respuesta sin `cobro` (servidor anterior a este campo): dividendos e
  // intereses enteros, lo de siempre.
  const clase = m.cobro !== undefined ? m.cobro
    : (m.type === 'DIVIDEND' || m.type === 'INTEREST') ? 'entero' : null
  if (!clase) return null
  const fecha = String(m.date || '').slice(0, 10)
  if (fecha.length !== 10) return null
  const activo = String(m.asset || '').trim().toUpperCase()
  if (clase === 'mixto') return { fecha, activo, tipo: 'MIXTO', usd: Math.abs(Number(m.amount_usd) || 0) }
  return { fecha, activo, tipo: m.type, usd: Number(m.amount_usd) || 0 }
}

/** Cuánto de una fila de cobro es plata cobrada: entera, o la parte de cupón de
 *  un pago mixto. null si es un pago mixto que el cronograma no permite separar
 *  (no se suma). */
export function montoCobrado(fila, cerSeries) {
  if (fila.tipo === 'MIXTO') return cuponDelPago(fila, cerSeries)
  return fila.usd
}

/**
 * Lo cobrado en un conjunto de filas de Movimientos, separado por tipo. El
 * cupón de un pago mixto cuenta como dividendo (es la renta del bono).
 * `sumar(filas, getUsd)` es el de la pantalla: convierte cada fila con el dólar
 * de SU fecha y después suma (en dólares, la suma de siempre).
 * @returns {{ total, DIVIDEND, INTEREST, pagos: {DIVIDEND, INTEREST}, mixtos, sinSeparar }}
 */
export function cobradoDe(movimientos, sumar, { cerSeries } = {}) {
  const usdDe = new Map()
  let mixtos = 0
  let sinSeparar = 0
  for (const m of movimientos) {
    const f = filaDeMovimiento(m)
    if (!f) continue
    const usd = montoCobrado(f, cerSeries)
    if (usd == null) { sinSeparar += 1; continue }
    if (f.tipo === 'MIXTO') mixtos += 1
    usdDe.set(m, { usd, tipo: f.tipo === 'INTEREST' ? 'INTEREST' : 'DIVIDEND' })
  }
  const filas = (tipo) => [...usdDe.keys()].filter(m => usdDe.get(m).tipo === tipo)
  const suma = (tipo) => sumar(filas(tipo), m => usdDe.get(m).usd)
  const DIVIDEND = suma('DIVIDEND')
  const INTEREST = suma('INTEREST')
  return {
    total: DIVIDEND + INTEREST, DIVIDEND, INTEREST,
    pagos: { DIVIDEND: filas('DIVIDEND').length, INTEREST: filas('INTEREST').length },
    mixtos, sinSeparar,
  }
}

/**
 * Las sumas de la pestaña, sobre lo que manda /api/cobros.
 * @returns {{ hoy, anio, total_anio, total_anterior_a_la_fecha, total_anterior,
 *   por_mes, por_anio, por_activo, ultimos_12_meses, mixtos }}
 *   mixtos: { separados, sinSeparar, usdSinSeparar } — los pagos con cupón y
 *   amortización juntos: cuántos se separaron y cuántos no (y cuánta plata).
 */
export function resumirCobros(datos, { cerSeries } = {}) {
  if (!datos) return null
  const hoy = datos.hoy
  const anio = Number(hoy.slice(0, 4))
  const anterior = anio - 1
  const topeAnterior = sumarAnios(hoy, -1)
  const desde12 = sumarDias(hoy, -365)

  const filas = []
  const mixtos = { separados: 0, sinSeparar: 0, usdSinSeparar: 0 }
  const porAnio = new Map((datos.anios_previos || []).map(a => [a.anio, a.usd]))
  for (const f of [...(datos.cobros || []), ...(datos.pagos_mixtos || [])]) {
    const usd = montoCobrado(f, cerSeries)
    if (f.tipo !== 'MIXTO') { filas.push(f); continue }
    if (usd == null) {
      mixtos.sinSeparar += 1
      mixtos.usdSinSeparar += f.usd
      continue
    }
    mixtos.separados += 1
    if (usd > 0) filas.push({ fecha: f.fecha, activo: f.activo, tipo: 'DIVIDEND', usd })
  }

  const porMes = Array.from({ length: 12 }, () => [0, 0])
  const porActivo = new Map()
  let totalAnteriorALaFecha = 0
  const ultimos = []
  for (const c of filas) {
    const y = Number(c.fecha.slice(0, 4))
    const m = Number(c.fecha.slice(5, 7)) - 1
    const activo = claveActivo(c.activo)
    if (y === anio || y === anterior) porAnio.set(y, (porAnio.get(y) || 0) + c.usd)
    if (y === anio) {
      porMes[m][0] += c.usd
      const a = porActivo.get(activo) || { activo, tipos: new Set(), usd: 0, cobros: 0 }
      a.tipos.add(c.tipo)
      a.usd += c.usd
      a.cobros += 1
      porActivo.set(activo, a)
    } else if (y === anterior) {
      porMes[m][1] += c.usd
      if (c.fecha <= topeAnterior) totalAnteriorALaFecha += c.usd
    }
    if (c.fecha > desde12 && c.fecha <= hoy) ultimos.push({ ...c, activo })
  }
  ultimos.sort((a, b) => a.fecha.localeCompare(b.fecha))

  return {
    hoy,
    anio,
    dias_hasta_el_pago: datos.dias_hasta_el_pago,
    total_anio: porAnio.get(anio) || 0,
    total_anterior_a_la_fecha: totalAnteriorALaFecha,
    total_anterior: porAnio.get(anterior) || 0,
    por_mes: porMes.map(([a, b], k) => ({ mes: k + 1, anio: a, anterior: b })),
    por_anio: [...porAnio.entries()].filter(([, v]) => v).sort((a, b) => a[0] - b[0])
      .map(([y, usd]) => ({ anio: y, usd })),
    por_activo: [...porActivo.values()].sort((a, b) => b.usd - a.usd)
      .map(a => ({ ...a, tipos: [...a.tipos].sort() })),
    ultimos_12_meses: ultimos,
    mixtos,
  }
}

/** Cuántas acciones (en la escala de la acción: los CEDEARs convertidos) de la
 *  especie `clave` hay en `lotes`. null si algún lote no se puede convertir. */
function acciones(lotes) {
  let total = 0
  for (const l of lotes) {
    const eq = underlyingShares(l)
    if (!eq) return null
    total += eq.shares
  }
  return total
}

/**
 * Cuántas acciones de la especie tenías el día `fecha`: los lotes abiertos que
 * ya habías comprado más los cerrados que todavía no habías vendido. null si no
 * se puede saber con respaldo (un lote sin fecha de compra o sin equivalencia).
 */
export function cantidadEn(fecha, clave, positions = [], operations = []) {
  const lotes = []
  for (const p of positions) {
    if (p.is_cash || claveActivo(p.asset) !== clave || !(Number(p.quantity) > 0)) continue
    if (!p.entry_date) return null
    if (String(p.entry_date).slice(0, 10) <= fecha) lotes.push(p)
  }
  for (const o of operations) {
    if (claveActivo(o.asset) !== clave || !esTradeCerrado(o) || !(Number(o.quantity) > 0)) continue
    if (!o.entry_date || !o.date) return null
    if (String(o.entry_date).slice(0, 10) <= fecha && String(o.date).slice(0, 10) > fecha) lotes.push(o)
  }
  return acciones(lotes)
}

/** Las especies que tenés hoy (sin el efectivo) y cuántas acciones de cada una. */
function tenenciasDeHoy(positions = []) {
  const porClave = new Map()
  for (const p of positions) {
    if (p.is_cash || !(Number(p.quantity) > 0)) continue
    const k = claveActivo(p.asset)
    if (!porClave.has(k)) porClave.set(k, [])
    porClave.get(k).push(p)
  }
  return new Map([...porClave].map(([k, lotes]) => [k, acciones(lotes)]))
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
 * @param {Array}  p.ultimos12     `ultimos_12_meses` de resumirCobros
 * @param {Array}  p.positions     /api/positions
 * @param {Array}  p.operations    /api/operations (para saber qué tenías al cobrar)
 * @param {Array}  p.eventosBonos  upcomingBondEvents(positions, { windowDays: 365 })
 * @param {Array}  p.anunciados    tickers con un dividendo anunciado (Eventos)
 * @param {number} p.tc            dólar de hoy, para los cupones en pesos
 * @returns {{ total, items, sinHistoria, sinActivoUsd, sinAjustar, cuponesSinDolar }}
 *   items: [{ fecha, activo, usd, fuente: 'cronograma' | 'historia' }]
 *   sinAjustar: especies repetidas sin poder ajustarlas a la tenencia de hoy.
 */
export function estimarProximos12({ ultimos12 = [], positions = [], operations = [], eventosBonos = [], anunciados = [], tc } = {}) {
  const hoyTengo = tenenciasDeHoy(positions)
  const items = []
  const sinAjustar = new Set()
  let sinActivoUsd = 0
  let cuponesSinDolar = 0

  for (const c of ultimos12) {
    if (!c.activo) { sinActivoUsd += c.usd; continue }      // no se sabe si lo seguís teniendo
    const clave = claveActivo(c.activo)
    if (isBondTicker(clave)) continue                        // los bonos van por el cronograma
    if (!hoyTengo.has(clave)) continue                       // ya no lo tenés
    const ahora = hoyTengo.get(clave)
    const entonces = cantidadEn(c.fecha, clave, positions, operations)
    let usd = c.usd
    if (ahora > 0 && entonces > 0) usd = c.usd * (ahora / entonces)
    else sinAjustar.add(clave)
    items.push({ fecha: sumarAnios(c.fecha, 1), activo: clave, usd, fuente: 'historia' })
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
  return { total, items, sinHistoria, sinActivoUsd, sinAjustar: [...sinAjustar].sort(), cuponesSinDolar }
}

/** De los eventos de Eventos, el dividendo anunciado más cercano de cada empresa
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
 *
 * El monto de un evento es `eventCobro`, la misma cuenta que la agenda de
 * Eventos. Si sólo cubre una parte de tu tenencia (`partial`: CEDEARs cuya
 * equivalencia no se sabe), no se publica: sería menos plata de la que te toca.
 * Si de la empresa sólo se conoce el CORTE, la plata entra `diasHastaElPago`
 * días después (regla medida, `dividendos.REGLAS`): ésa es la fecha que ordena.
 *
 * @param {object} cobroCtx  { positions, prices, tc } como el de Events.jsx
 * @returns {{ activo, fecha, usd, fuente, bruto, conAmortizacion, corte, parcial } | null}
 */
export function proximoCobro({ estimado, eventosBonos = [], anunciados = [], cobroCtx = {}, tc, diasHastaElPago = 0 } = {}) {
  const candidatos = []
  for (const e of eventosBonos) {
    const c = eventCobro(e, cobroCtx)
    const usd = aDolares(c?.amount, c?.currency, tc)
    if (!(usd > 0)) continue
    candidatos.push({ activo: e.ticker, fecha: e.eventDate, usd, fuente: 'cronograma',
      conAmortizacion: e.details?.amort > 0 })
  }
  const anunciadosTickers = new Set()
  for (const e of anunciados) {
    anunciadosTickers.add(claveActivo(e.ticker))
    const c = eventCobro(e, cobroCtx)
    const parcial = !!c?.partial
    const esCorte = e.eventType === 'ex_dividend'
    candidatos.push({
      activo: claveActivo(e.ticker),
      fecha: esCorte ? sumarDias(e.eventDate, diasHastaElPago) : e.eventDate,
      corte: esCorte ? e.eventDate : null,
      usd: c?.amount > 0 && !parcial ? c.amount : null,
      parcial,
      fuente: 'anunciado', bruto: true,
    })
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
