// lecturaDeHoy.js — lo que la ficha dice alrededor del gráfico técnico: la
// frase de «La lectura de hoy», sus cuatro casilleros y las pestañas de las
// tarjetas (components/asset/LecturaDeHoy.jsx y TarjetasPorTema.jsx).
// ════════════════════════════════════════════════════════════════════════════
// Acá NO hay cuentas nuevas: todo sale de las tarjetas de utils/tecnico.js
// (`tarjetas()`, con su veredicto y su tono) y de la lectura que manda el
// servidor. Las palabras de los veredictos son las de esas tarjetas: si
// cambian ahí, cambian acá solas. Lo único que se lee de la serie del gráfico
// es el último día en que el precio cruzó su promedio (el que ya está
// dibujado), para decir desde cuándo está arriba o abajo.

import { veredictoRsi } from './tecnico'

/**
 * El último día en que el cierre cruzó su promedio (`clave`: 's200' o 's50')
 * en la serie del gráfico: { i, fecha, arriba } (arriba = lo cruzó hacia
 * arriba), o null si en toda la serie no lo cruzó o falta el promedio.
 * Los días sin promedio (el principio de la historia) no cuentan.
 */
export function ultimoCruce(puntos = [], clave) {
  let lado = null
  for (let i = puntos.length - 1; i >= 0; i--) {
    const p = puntos[i]
    if (!(p?.c > 0) || !(p[clave] > 0)) {
      if (lado === null) continue
      return null
    }
    const arriba = p.c >= p[clave]
    if (lado === null) { lado = arriba; continue }
    if (arriba !== lado) return { i: i + 1, fecha: puntos[i + 1].d, arriba: lado }
  }
  return null
}

/**
 * Para dónde va el impulso del RSI: 1 (gana), -1 (pierde), 0 (sin uno claro).
 * Con los MISMOS cortes de la tarjeta: el veredicto de 50 es el del medio
 * («sin fuerza clara»); cualquier otro veredicto, del lado en que esté el RSI.
 */
export function ladoDelRsi(rsi) {
  if (rsi == null) return 0
  if (veredictoRsi(rsi) === veredictoRsi(50)) return 0
  return rsi > 50 ? 1 : -1
}

const tonoDeLado = (lado) => (lado > 0 ? 'pos' : lado < 0 ? 'neg' : 'neutro')
const minuscula = (t) => t.charAt(0).toLowerCase() + t.slice(1)

/**
 * La frase de arriba: { texto, tono }. Con las tarjetas de largo y mediano
 * plazo (su veredicto) y la del RSI. null sin ninguna de las tres.
 *   «tendencia alcista en los dos plazos, con impulso al alza»
 *   «largo plazo alcista y mediano plazo bajista, sin impulso claro»
 */
export function fraseDeHoy(lista = []) {
  const de = (id) => lista.find(t => t.id === id)
  const fondo = de('fondo'), corto = de('corto'), rsi = de('rsi')
  const leido = (t) => t && (t.tono === 'pos' || t.tono === 'neg')
  const plazos = [fondo, corto].filter(leido)
  let tendencia = null
  if (plazos.length === 2 && fondo.tono === corto.tono) {
    tendencia = `tendencia ${minuscula(fondo.veredicto)} en los dos plazos`
  } else if (plazos.length) {
    // Con los nombres de los casilleros (el lienzo aprobado): largo y mediano plazo.
    tendencia = plazos.map(t => `${t.id === 'fondo' ? 'largo' : 'mediano'} plazo ${minuscula(t.veredicto)}`).join(' y ')
  }
  const lado = rsi ? ladoDelRsi(rsi.rsi) : null
  const impulso = lado === null ? null
    : lado > 0 ? 'con impulso al alza' : lado < 0 ? 'con impulso a la baja' : 'sin impulso claro'
  if (!tendencia && !impulso) return null
  const texto = tendencia && impulso ? `${tendencia}, ${impulso}.`
    : tendencia ? `${tendencia}.`
      : `${impulso.charAt(0).toUpperCase()}${impulso.slice(1)}; todavía no hay historia para leer la tendencia.`
  // Verde o rojo sólo si los dos plazos (o el único que hay) dicen lo mismo.
  const tono = plazos.length && plazos.every(t => t.tono === plazos[0].tono) ? plazos[0].tono : 'neutro'
  return { texto, tono }
}

// ─── Las pestañas de las tarjetas ───────────────────────────────────────────

// Qué tarjeta va en qué pestaña. Las de Niveles salen de su capa del gráfico;
// «tuyo» es «Contra lo que pagaste»; las de cuantoSeMueve van con la
// «Cuánto se mueve» de tecnico.js.
export const TEMAS = [
  { id: 'tendencia', nombre: 'Tendencia', ids: ['fondo', 'corto', 'maximo'] },
  { id: 'impulso', nombre: 'Impulso y fuerza', ids: ['rsi', 'fuerza'] },
  { id: 'niveles', nombre: 'Niveles', ids: ['bandas', 'fibonacci', 'elliott'] },
  { id: 'tuyo', nombre: 'Tu posición', ids: ['tuyo'] },
  { id: 'movimiento', nombre: 'Cuánto se mueve', ids: ['movimiento', 'caida', 'desde_maximo', 'dia', 'cartera'] },
]

/** La pestaña de una tarjeta. Una que todavía no tiene lugar va a «Tendencia»:
 *  mejor ahí que desaparecer (y la prueba exige que todas tengan el suyo). */
export function temaDe(id) {
  return (TEMAS.find(t => t.ids.includes(id)) || TEMAS[0]).id
}

/**
 * El puntito de color de una pestaña: 'pos' (verde, a favor de la suba), 'neg'
 * (rojo), 'neutro' (gris) o 'aviso' (amarillo, «Cuánto se mueve», que mide el
 * tamaño del movimiento y no su dirección). Verde o rojo sólo si todas las
 * tarjetas con color de la pestaña dicen lo mismo; el RSI, que no tiene color,
 * cuenta por el lado de su impulso.
 */
export function tonoDelTema(tema, lista = []) {
  if (tema === 'movimiento') return 'aviso'
  if (tema === 'niveles') return 'neutro'
  const tonos = lista
    .map(t => (t.id === 'rsi' ? tonoDeLado(ladoDelRsi(t.rsi)) : t.tono))
    .filter(t => t === 'pos' || t === 'neg')
  return tonos.length && tonos.every(t => t === tonos[0]) ? tonos[0] : 'neutro'
}

// La pestaña elegida, en este navegador (el almacenamiento puede estar
// bloqueado: modo privado; entonces, la primera).
const CLAVE_TEMA = 'rendi_ficha_tema_tecnico'
export function temaGuardado() {
  try { return localStorage.getItem(CLAVE_TEMA) } catch { return null }
}
export function guardarTema(id) {
  try { localStorage.setItem(CLAVE_TEMA, id) } catch { /* sin almacenamiento */ }
}

// ─── Los dibujitos ──────────────────────────────────────────────────────────

/**
 * El precio y su promedio en los últimos `n` días de la serie, listos para un
 * dibujo chico: { precio: [[x, y]…], promedio: [[x, y]…], cruce: [x, y] | null }
 * en un lienzo de `ancho` × `alto` (y crece hacia abajo, como en SVG). El
 * cruce es el de `ultimoCruce`, si cae adentro. null con menos de 2 días con
 * promedio.
 */
export function miniPromedio(puntos = [], clave, { n = 120, ancho = 300, alto = 54, aire = 5 } = {}) {
  const desde = Math.max(0, puntos.length - n)
  const tramo = puntos.slice(desde).map((p, k) => ({ ...p, k })).filter(p => p.c > 0 && p[clave] > 0)
  if (tramo.length < 2) return null
  const vals = tramo.flatMap(p => [p.c, p[clave]])
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const ultimo = puntos.length - desde - 1
  const x = (k) => (ultimo > 0 ? (k / ultimo) * ancho : 0)
  const y = (v) => (hi > lo ? aire + (1 - (v - lo) / (hi - lo)) * (alto - 2 * aire) : alto / 2)
  const c = ultimoCruce(puntos, clave)
  const enTramo = c && c.i >= desde ? tramo.find(p => p.k === c.i - desde) : null
  return {
    precio: tramo.map(p => [x(p.k), y(p.c)]),
    promedio: tramo.map(p => [x(p.k), y(p[clave])]),
    cruce: enTramo ? [x(enTramo.k), y(enTramo[clave])] : null,
  }
}

/** Una lista de puntos [[x, y]…] como el `d` de un <path>. */
export function trazo(pts) {
  return pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')
}

/** Dónde está hoy el precio entre el mínimo y el máximo del año (0 a 1), o
 *  null si falta alguno o no se separan. */
export function lugarEnElAnio(l) {
  const lo = l?.minimo_12m, hi = l?.maximo_12m, p = l?.precio
  if (!(lo > 0) || !(hi > lo) || !(p > 0)) return null
  return Math.min(1, Math.max(0, (p - lo) / (hi - lo)))
}
