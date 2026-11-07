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

import { isFciSym, isFixedIncome } from './valuation'
import { esLoteLocal, esAccionLocal } from './accionLocal'
import { tarjetas, veredictoRsi } from './tecnico'

// Una lectura sin precios de la última semana no describe el precio de hoy
// (Yahoo dejó de mandar velas, cambió el ticker): va «sin lectura» con su fecha,
// en vez de contarse en el porcentaje. Lo decide el SERVIDOR (`vieja` de cada
// lectura, `tecnico.es_vieja`, contado desde el día argentino): la misma regla
// de Comparar, el Backtesting y la ficha. Antes acá eran 10 días contados con la
// fecha de la compu, y el mismo papel salía «al día» en la Cartera y «viejo» en
// Comparar (auditoría de «1 año» 06/11, H2; Nico eligió 7 días).

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
  no_se_mide: 'Rendi no guarda la historia de precios de bonos, fondos, efectivo ni plazos fijos, así que no se les calcula la tendencia.',
  sin_historia: 'todavía no hay historia de precios guardada. Se guarda cada noche, así que va a aparecer mañana.',
  pocos_dias: 'para calcular la tendencia hacen falta 200 días de mercado de precios guardados, y todavía no los tienen.',
  vieja: 'su último precio guardado es de antes de la última semana, así que no refleja cómo está hoy.',
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
export function tendencia(x, p = null) {
  const sin = (porque, motivo) => ({ id: 'sin', palabra: 'Sin lectura', porque, motivo })
  if (!x || !x.disponible || !x.lectura) {
    if (noSeMide(p)) return sin('no_se_mide', 'Rendi no guarda la historia de precios de bonos, fondos ni efectivo, así que no se les calcula la tendencia.')
    return sin('sin_historia', 'Todavía no hay historia de precios guardada para este activo. Se guarda cada noche, así que va a aparecer mañana.')
  }
  if (lecturaVieja(x)) {
    return sin('vieja', `El último precio guardado es del ${fechaCorta(x.lectura.fecha)}, así que no refleja cómo está hoy.`)
  }
  const fondo = tarjetas(x.lectura).find(t => t.id === 'fondo')
  if (fondo?.veredicto === 'Alcista') return { id: 'alcista', palabra: 'Alcista', motivo: fondo.texto }
  if (fondo?.veredicto === 'Bajista') return { id: 'bajista', palabra: 'Bajista', motivo: fondo.texto }
  return sin('pocos_dias', fondo?.texto || 'Faltan datos.')
}

/** ¿Su último precio es de antes de la última semana? Lo dice el servidor
 *  (`vieja`); la pantalla no cuenta días. */
export function lecturaVieja(x) {
  return !!x?.vieja
}

function fechaCorta(iso) {
  const [y, m, d] = String(iso).split('-')
  return `${d}/${m}/${y}`
}

/** El RSI de la fila y su palabra (`veredictoRsi`, «Toma fuerza»). null si no hay o
 *  si la lectura es vieja. */
export function fuerza(x) {
  const rsi = x?.disponible && !lecturaVieja(x) ? x.lectura?.rsi : null
  if (rsi == null) return null
  return { rsi, palabra: veredictoRsi(rsi) }
}
