// radiografia.js — la lectura técnica de cada fila de la Cartera (y de «Tu lista»).
// ════════════════════════════════════════════════════════════════════════════
// Dos fuentes, ninguna recalculada acá:
//   · los NÚMEROS técnicos vienen de POST /api/tecnico/cartera (backend/tecnico.py,
//     la misma `lectura` que la ficha de cada activo);
//   · las PALABRAS («Alcista», «Toma fuerza») son las de la ficha
//     (`tarjetas` y `veredictoRsi` de utils/tecnico.js): un activo no puede
//     decir «Alcista» en la Cartera y «Bajista» en su ficha.
// El % de tu plata en tendencia alcista YA NO se cuenta acá (28/10): lo arma el
// servidor una sola vez (senales_semana.reparto) para la Cartera, el Panorama,
// la pestaña Señales y el mail de los sábados.

import { fciLabel, isFciSym, isFixedIncome } from './valuation'
import { esLoteLocal, esAccionLocal } from './accionLocal'
import { tarjetas, veredictoRsi } from './tecnico'
import { hoyISO } from './fecha'

// Una lectura cuya última vela tiene más días corridos que esto no describe el
// precio de hoy (Yahoo dejó de mandar velas, cambió el ticker): va «sin
// lectura» con su fecha, en vez de contarse en el porcentaje. Un fin de semana
// largo con feriados son 5 días; las velas se guardan cada noche.
export const DIAS_LECTURA_VIEJA = 10

// ¿Acción ARGENTINA (no CEDEAR)? La regla vive en accionLocal.js, una para la
// ficha, la Cartera y las alertas técnicas; acá se re-exporta.
export { esLoteLocal, esAccionLocal }

export const clave = (asset, local) => `${asset}|${local ? 1 : 0}`

/** Lo que se le pide al servidor: cada activo (con su marca `local`) una vez. */
export function activosParaLeer(lotes = []) {
  const vistos = new Map()
  for (const p of lotes) {
    if (!p || p.is_cash || !p.asset) continue
    const local = esLoteLocal(p)
    const k = clave(p.asset, local)
    if (!vistos.has(k)) vistos.set(k, { asset: p.asset, local })
  }
  return [...vistos.values()].sort((a, b) => clave(a.asset, a.local).localeCompare(clave(b.asset, b.local)))
}

/** {clave → lectura del servidor}. */
export function indexarLecturas(lecturas = []) {
  const out = new Map()
  for (const x of lecturas) out.set(clave(x.asset, x.local), x)
  return out
}

/** La lectura de una fila de la tabla (un lote o una fila que junta lotes del
 *  mismo broker). null si es efectivo o no llegó. */
export function lecturaDeFila(indice, p) {
  if (!indice || !p || p.is_cash) return null
  const lots = p._lots || [p]
  return indice.get(clave(String(p.asset || '').toUpperCase(), esAccionLocal(p.asset, lots))) || null
}

// Por qué algo va «sin lectura», del más permanente al más pasajero. Cada uno
// con su explicación: un bono no se mide así y nunca va a tener; una acción
// recién agregada sí, a partir de la noche en que se guardan sus precios.
export const MOTIVOS_SIN_LECTURA = {
  no_se_mide: 'bonos, fondos, efectivo y plazos fijos no tienen historia de precios en Rendi: no se les mide la tendencia.',
  sin_historia: 'todavía no hay historia de precios guardada. Se guarda cada noche: aparece en un día.',
  pocos_dias: 'para leer la tendencia hacen falta 200 días de mercado de precios guardados, y todavía no los tienen.',
  vieja: `su último precio guardado tiene más de ${DIAS_LECTURA_VIEJA} días: no describe el de hoy.`,
}

/** ¿Este lote es de los que no se miden con velas? (efectivo, fondo, bono, plazo fijo) */
function noSeMide(p) {
  return !!p && (p.is_cash || p.es_plazo_fijo || isFciSym(p.asset) || isFixedIncome(p.asset_type)
    || ['FUND', 'FCI'].includes(String(p.asset_type || '').toUpperCase()))
}

/**
 * La tendencia de fondo con las palabras de la ficha: { id: 'alcista' |
 * 'bajista' | 'sin', palabra, motivo, porque }. «Sin lectura» trae `porque`
 * (una clave de MOTIVOS_SIN_LECTURA) y un `motivo` para el globo de la fila,
 * según qué le falta: `p` (un lote del activo) dice si es un bono o un fondo.
 */
export function tendencia(x, hoy = hoyISO(), p = null) {
  const sin = (porque, motivo) => ({ id: 'sin', palabra: 'Sin lectura', porque, motivo })
  if (!x || !x.disponible || !x.lectura) {
    if (noSeMide(p)) return sin('no_se_mide', 'Bonos, fondos y efectivo no tienen historia de precios en Rendi: no se les mide la tendencia.')
    return sin('sin_historia', 'Todavía no hay historia de precios guardada para este activo. Se guarda cada noche: aparece en un día.')
  }
  if (lecturaVieja(x, hoy)) {
    return sin('vieja', `El último precio guardado es del ${fechaCorta(x.lectura.fecha)}: no describe el de hoy.`)
  }
  const fondo = tarjetas(x.lectura).find(t => t.id === 'fondo')
  if (fondo?.veredicto === 'Alcista') return { id: 'alcista', palabra: 'Alcista', motivo: fondo.texto }
  if (fondo?.veredicto === 'Bajista') return { id: 'bajista', palabra: 'Bajista', motivo: fondo.texto }
  return sin('pocos_dias', fondo?.texto || 'Faltan datos.')
}

/** ¿La última vela es de hace más de DIAS_LECTURA_VIEJA días corridos? */
export function lecturaVieja(x, hoy = hoyISO()) {
  const f = x?.lectura?.fecha
  if (!f) return false
  return (Date.parse(hoy + 'T00:00:00Z') - Date.parse(f + 'T00:00:00Z')) / 86400000 > DIAS_LECTURA_VIEJA
}

function fechaCorta(iso) {
  const [y, m, d] = String(iso).split('-')
  return `${d}/${m}/${y}`
}

/** El RSI de la fila y su palabra (`veredictoRsi`, «Toma fuerza»). null si no hay o
 *  si la lectura es vieja. */
export function fuerza(x, hoy = hoyISO()) {
  const rsi = x?.disponible && !lecturaVieja(x, hoy) ? x.lectura?.rsi : null
  if (rsi == null) return null
  return { rsi, palabra: veredictoRsi(rsi) }
}

/**
 * Cuánto vale cada activo de la cartera: los lotes del mismo activo (y la misma
 * marca `local`) sumados con `valorDe(p)`, la valuación de la pantalla. El
 * efectivo va junto en 'efectivo' y cada `extra` ({ nombre, valor }: los plazos
 * fijos) en su propia clave. `total`: la suma de todo, el mismo total de la
 * Cartera. La usa «Tu lista» (el «cuánto pesa» de cada fila).
 * → { porActivo: Map(clave → { nombre, valor, p (un lote, para el motivo) }), total }
 */
export function valorPorActivo(lotes = [], valorDe, extra = []) {
  const porActivo = new Map()
  const sumar = (k, nombre, valor, p) => {
    if (!(valor > 0)) return
    const a = porActivo.get(k) || { nombre, valor: 0, p }
    a.valor += valor
    porActivo.set(k, a)
  }
  for (const p of lotes) {
    if (!p) continue
    const v = Number(valorDe(p))
    if (p.is_cash) { sumar('efectivo', 'efectivo', v, p); continue }
    sumar(clave(String(p.asset).toUpperCase(), esLoteLocal(p)), fciLabel(p.asset), v, p)
  }
  for (const e of extra) sumar(`extra:${e.nombre}`, e.nombre, Number(e.valor), { es_plazo_fijo: true })
  let total = 0
  for (const a of porActivo.values()) total += a.valor
  return { porActivo, total }
}
