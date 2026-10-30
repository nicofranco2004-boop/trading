// diarioOperaciones — el diario de Movimientos › Operaciones cerradas (pieza 11).
// ═══════════════════════════════════════════════════════════════════════════
// Mira el comportamiento DE LA PERSONA: cuánto tuvo cada operación, cuánto
// rindió por año y cómo estaba la tendencia el día que compró. No dice qué
// hacer ni sugiere que la tendencia anticipa: la verificación del 23/10 (70
// activos × 2 años) dio que los indicadores técnicos describen pero no
// anticipan mejor que el azar. Por eso la frase es descriptiva y lleva la
// aclaración abajo.
//
// NO RECALCULA EL RESULTADO. El resultado de cada venta (`pnl_usd`, `pnl_pct`)
// lo escribe una vez la venta FIFO del servidor (o el importador), una fila por
// lote con SU fecha de compra (`entry_date`). Acá se usa tal cual: «Por año»
// anualiza el MISMO % de la columna «P&L %» que está al lado.
//
// QUÉ OPERACIONES. Las de `esTradeCerrado` (la regla del win rate, espejo del
// backend) menos los COBROS (`esCobro`: dividendo, cupón, amortización…) y la
// «venta» con la que Balanz anota una amortización (`amortizacion_importada`):
// plata que entró por tener el activo no tiene «tiempo que la tuviste» ni
// «tendencia al comprar».

import { esTradeCerrado, esCobro } from './tradeStats'
import { esAccionLocal } from './accionLocal'

// Con menos que esto, «Por año» va «—»: pasar a un año un mes bueno infla el
// número (+5 % en 30 días daría +81 % por año).
export const DIAS_MIN_POR_ANIO = 90
const DIAS_MES = 365.25 / 12

/** ¿La operación entra en el diario? (ver «QUÉ OPERACIONES» arriba) */
export function esDelDiario(op) {
  return esTradeCerrado(op) && !esCobro(op?.op_type) && !op?.amortizacion_importada
}

function msDe(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''))
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : null
}

/**
 * Días entre la compra (`entry_date`) y la venta (`date`). null si falta una
 * de las dos o si la venta es anterior a la compra. Espejo de
 * `behavioral._holding_days` del backend (el «disposition effect» de Insights).
 */
export function diasTenida(op) {
  const e = msDe(op?.entry_date), s = msDe(op?.date)
  if (e == null || s == null) return null
  const d = Math.round((s - e) / 86400000)
  return d >= 0 ? d : null
}

/**
 * Rendimiento por año (fracción: 0,18 = +18 %): el `pnl_pct` de la operación
 * llevado a 365 días, con interés compuesto. null con menos de
 * DIAS_MIN_POR_ANIO días o sin %.
 */
export function rendimientoPorAnio(op) {
  const dias = diasTenida(op)
  if (dias == null || dias < DIAS_MIN_POR_ANIO || op?.pnl_pct == null) return null
  const base = 1 + op.pnl_pct / 100
  if (!(base > 0)) return -1
  return Math.pow(base, 365 / dias) - 1
}

const un = (x) => x.toLocaleString('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

/** «12 días» · «5,4 meses» · «2,3 años». */
export function textoTiempo(dias) {
  if (dias == null) return '—'
  if (dias < 31) return `${dias} ${dias === 1 ? 'día' : 'días'}`
  const meses = dias / DIAS_MES
  if (meses < 24) return `${un(meses)} ${un(meses) === '1,0' ? 'mes' : 'meses'}`
  return `${un(dias / 365.25)} años`
}

/** Meses con una decimal, para la tarjeta («7,8 contra 2,6 meses»). */
export function mesesDe(dias) {
  return dias == null ? null : un(dias / DIAS_MES)
}

/**
 * Lo que se le pide al servidor (/api/tecnico/en-fechas): una fila por
 * operación del diario, con la fecha de SU compra y la marca de acción
 * argentina (la misma regla que la ficha). El tope del servidor es 2000.
 */
export function pedidosDeTendencia(ops) {
  return (ops || [])
    .filter(o => esDelDiario(o) && o.entry_date)
    .slice(0, 2000)
    .map(o => ({
      id: String(o.id), asset: o.asset, local: esAccionLocal(o.asset, [o]),
      fecha: String(o.entry_date).slice(0, 10),
    }))
}

// Por qué una operación no tiene tendencia al comprar. Las claves son los
// `motivo` de tecnico.tendencia_del_dia (servidor).
export const MOTIVO_SIN_TENDENCIA = {
  sin_velas: 'No tenemos precios guardados de este activo (pasa con bonos y fondos, y con un activo que recién empezamos a seguir: aparecen al día siguiente).',
  sin_precio: 'No hay precios de ese día: guardamos los últimos 3 años.',
  pocos_dias: 'Ese día todavía no había 200 días de mercado guardados para calcular el promedio.',
  sin_fecha: 'La operación no tiene fecha de compra.',
  tope: 'Miramos la tendencia del día de compra en hasta 200 activos distintos.',
  // No es un motivo del servidor: el pedido falló (o es el demo, que no lo simula).
  sin_respuesta: 'No pudimos traer los precios de cada día. Probá de nuevo en un rato.',
}

/** La tendencia del día de compra de `op`, o {tendencia: null, motivo}. */
export function tendenciaDe(op, tendencias) {
  if (!op?.entry_date) return { tendencia: null, motivo: 'sin_fecha' }
  return tendencias?.[String(op.id)] || null
}

const promedio = (xs) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null)

/**
 * La plata que se puso en la operación, en dólares: el precio de compra por la
 * cantidad. En una venta en pesos, al dólar con que el servidor la pasó a
 * dólares (`fx_to_usd`, pesos por dólar; en una en dólares estampa 1). Sin
 * precio de compra (algunas importadas), en una venta en dólares sale del
 * resultado y su %: 100 ganados al 10 % = 1.000 puestos. null si no se sabe.
 */
export function capitalUsd(op) {
  const enDolares = !op?.currency || op.currency === 'USD' || op.currency === 'USDT'
  const c = Number(op?.entry_price) * Number(op?.quantity)
  if (!(c > 0)) {
    const pct = Number(op?.pnl_pct)
    return enDolares && pct && op.pnl_usd != null ? Math.abs(op.pnl_usd / (pct / 100)) : null
  }
  if (enDolares) return c
  const fx = Number(op.fx_to_usd)
  return fx > 1 ? c / fx : null
}

/**
 * «Rendimiento por año» de la tarjeta, ponderado por plata y tiempo (decisión
 * de Nico, 29/10): todo lo que ganaste y perdiste, en dólares, dividido por la
 * plata que pusiste multiplicada por los años que estuvo puesta. Una venta
 * grande y larga pesa más que una chica y corta, y una de un mes entra con el
 * peso de su mes (no hace falta el piso de 3 meses de la columna).
 *
 * Antes era el promedio simple de los «por año» de cada venta: con una ganancia
 * de US$ 1.400 en 19 meses y una pérdida de US$ 300 en 7, daba −1,0 % al lado de
 * «P&L Realizado US$ 1.100» (auditoría D7). Así da +15,0 %.
 * { valor, n } — null si no hay ninguna con plata y fechas.
 */
export function rendimientoPonderado(filas) {
  let gano = 0, plataPorAnio = 0, n = 0
  for (const o of filas) {
    const dias = diasTenida(o), cap = capitalUsd(o)
    if (dias == null || cap == null || o.pnl_usd == null) continue
    gano += o.pnl_usd
    plataPorAnio += cap * Math.max(dias, 1) / 365
    n++
  }
  return n && plataPorAnio > 0 ? { valor: gano / plataPorAnio, n } : { valor: null, n: 0 }
}

/**
 * Los números de las tarjetas y de la frase, sobre las operaciones del diario.
 * `tendencias`: lo que devolvió /api/tecnico/en-fechas ({id: {tendencia}}).
 */
export function resumenDiario(ops, tendencias = {}) {
  const filas = (ops || []).filter(esDelDiario)
  const gan = filas.filter(o => o.pnl_usd > 0)
  const per = filas.filter(o => o.pnl_usd < 0)
  const dias = (xs) => xs.map(diasTenida).filter(d => d != null)
  const ponderado = rendimientoPonderado(filas)
  const t = (o) => tendenciaDe(o, tendencias)?.tendencia
  const ganConT = gan.filter(o => t(o))
  const perConT = per.filter(o => t(o))
  return {
    cerradas: filas.length,
    ganadas: gan.length,
    perdidas: per.length,
    diasGanadoras: promedio(dias(gan)),
    diasPerdedoras: promedio(dias(per)),
    nGanadorasConDias: dias(gan).length,
    nPerdedorasConDias: dias(per).length,
    porAnio: ponderado.valor,
    nPorAnio: ponderado.n,
    ganadorasConTendencia: ganConT.length,
    ganadorasAFavor: ganConT.filter(o => t(o) === 'alcista').length,
    perdedorasConTendencia: perConT.length,
    perdedorasEnContra: perConT.filter(o => t(o) === 'bajista').length,
  }
}

const VECES = ['', '', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve', 'diez']
// «tres veces» si es casi redondo; si no, «4,5 veces» (redondear 4,48 a
// «cuatro» achica lo que pasó).
function veces(x) {
  const r = Math.round(x)
  if (r >= 2 && r < VECES.length && Math.abs(x - r) < 0.15) return `${VECES[r]} veces`
  return `${un(x)} veces`
}

/**
 * «Lo que dicen tus números»: texto fijo armado con el resumen (sin IA).
 * Describe; nunca aconseja («deberías», «conviene», «vendé»). Devuelve las
 * oraciones, o [] si no hay con qué decir algo (menos de 3 cerradas).
 */
export function fraseDeTusNumeros(r) {
  if (!r || r.cerradas < 3) return []
  const out = []
  const pc = r.perdedorasConTendencia, pe = r.perdedorasEnContra
  if (pc === 1 && r.perdidas === 1) {
    out.push(`La que perdiste la compraste cuando el papel estaba ${pe ? 'debajo' : 'arriba'} de su promedio de 200 días.`)
  } else if (pc > 0) {
    const cuantas = `${pe} ${pe === 1 ? 'la compraste' : 'las compraste'}`
    out.push(pc === r.perdidas
      ? `De las ${pc} que perdiste, ${cuantas} cuando el papel estaba debajo de su promedio de 200 días.`
      : `De las ${r.perdidas} que perdiste hay precios del día de compra de ${pc}: ${cuantas} cuando el papel estaba debajo de su promedio de 200 días.`)
  }
  const g = r.diasGanadoras, p = r.diasPerdedoras
  if (g != null && p != null && g > 0 && p > 0) {
    const ratio = g / p
    if (ratio >= 1.5) out.push(`Las ganadoras las tuviste ${veces(ratio)} más tiempo que las perdedoras.`)
    else if (ratio <= 1 / 1.5) out.push(`Las perdedoras las tuviste ${veces(1 / ratio)} más tiempo que las ganadoras.`)
    else out.push('A las ganadoras y a las perdedoras las tuviste un tiempo parecido.')
  }
  return out
}

/** La aclaración que va siempre debajo de la frase. */
export const ACLARACION_DIARIO =
  'Describe lo que pasó con tus operaciones. Cómo estaba la tendencia el día que compraste no anticipa cómo le va a ir a la próxima.'

/**
 * La tesis que tenía una operación cerrada: la ÚLTIMA versión de la tesis de
 * ese activo escrita hasta el día de la venta. Una tesis escrita después de
 * vender no es «la que tenía» (ver backend/tesis.py: con historia por día).
 * `tesis`: los `items` de /api/tesis.
 */
// La tesis se busca por el nombre EXACTO del papel (el de tus operaciones, como
// lo guarda el servidor). «¿Es el mismo papel con otro nombre?» lo decide la
// ficha antes (esElMismo: llegás por GGAL.BA y te lleva a tu GGAL); acá no se
// adivina: AGRO (Adecoagro) y AGRO.BA (Agrometal) son empresas distintas
// (auditoría D, re-test 29/10: sacarle el «.BA» las mezclaba).
export function tesisDeLaOperacion(tesis, op) {
  let mejor = null
  for (const t of (tesis || [])) {
    if (t.asset !== op?.asset || !op?.date || t.escrita_el > String(op.date).slice(0, 10)) continue
    if (!mejor || t.escrita_el > mejor.escrita_el || (t.escrita_el === mejor.escrita_el && t.id > mejor.id)) mejor = t
  }
  return mejor
}

/** La tesis vigente de un activo (la última escrita). */
export function tesisVigente(tesis, asset) {
  return tesisDeLaOperacion(tesis, { asset, date: '9999-12-31' })
}
