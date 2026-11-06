// rutasSensibles — una sola definición de qué parte de una dirección se le
// puede contar a terceros (Google Analytics y el píxel de Meta).
// ════════════════════════════════════════════════════════════════════════════
// Es una lista de PERMITIDOS. Hasta el 2026-11-05 era una de prohibidos
// (`token`, `email`, `code`) y todo lo demás pasaba: así la cartera que «Una
// cartera» escribía en la dirección (`activos`, `pesos`) le llegaba a Google
// (a Meta no, pero por dos cosas de afuera: ver metaPixel.js), y cada parámetro
// nuevo con datos de la persona iba a pasar hasta que alguien se acordara de
// anotarlo. Ahora pasa sólo lo que está acá: un
// parámetro nuevo queda afuera hasta que alguien decida que se puede contar.
// Olvidarse cuesta un dato de las métricas, no un dato de la persona.
//
// Qué hace cada medidor con una dirección:
//   · Google (analytics.js) recibe la ruta con SÓLO los parámetros de esta
//     lista; los demás se sacan. Así un utm o un gclid siguen llegando aunque
//     vengan junto con otro parámetro.
//   · El píxel de Meta lee la dirección entera por su cuenta (ver en
//     metaPixel.js por qué hoy no sale entera y por qué no alcanza): con un
//     solo parámetro que no esté acá no se dispara, y lo que hubiera que
//     mandarle espera a la próxima dirección limpia.
//   · En las rutas que llevan el secreto en la ruta misma (/i/<token>), Google
//     recibe sólo el comienzo (/i/), ninguna vista de página y el título
//     «Rendi» (el del informe nombra al cliente); el píxel no se dispara.
//   · La página ANTERIOR también viaja: Google y Meta leen document.referrer.
//     vercel.json manda `Referrer-Policy: strict-origin` para que, al saltar de
//     una página de Rendi a otra con recarga entera (el ErrorBoundary, la
//     sesión vencida, el login), el navegador diga sólo «https://rendi.finance/»
//     y no la dirección completa de donde venías (Google la guardaba como
//     «página anterior», con todos sus parámetros salvo los emails, que tacha
//     él). No volver a strict-origin-when-cross-origin.
//
// index.html tiene su PROPIA copia de las listas y de la regla (corre antes que
// el bundle y no puede importar): `medicion.test.js` corre ese bloque tal como
// está escrito y falla si sus listas o sus respuestas difieren de éstas.

import { SITIOS_MEDIDOS } from './medicion'

export const RUTAS_SENSIBLES = ['/i/', '/claim', '/acceso', '/reset-password', '/verify-email']

export const PARAMS_PERMITIDOS = [
  // De dónde viene la visita: campañas, anuncios (Google, Meta y otros) y el
  // código de cada post (`d`, ver origen.js). Sin éstos se rompe la atribución.
  'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'utm_id',
  'utm_source_platform', 'utm_creative_format', 'utm_marketing_tactic',
  'gclid', 'gbraid', 'wbraid', 'gad_source', 'gad_campaignid', 'dclid', 'srsltid', '_gl',
  'fbclid', 'brid', 'waaem', 'igshid', 'msclkid', 'ttclid', 'twclid', 'li_fat_id',
  'd',
  // Qué pantalla u opción se está mirando: pestañas, modos, el plan elegido,
  // cuántos años. Ninguno dice nada de la persona ni de su cartera (el ticker,
  // los activos y los porcentajes de Backtesting, en cambio, no entran).
  'tab', 'sub', 'vista', 'modo', 'origen', 'anios', 'reglas', 'moneda', 'periodo',
  'mode', 'demo', 'plan', 'period', 'step', 'from', 'action', 'nueva', 'provider',
  // Las recargas que fuerzan la versión nueva (main.jsx, autoUpdate.js).
  '_t', '_v',
]

const PERMITIDOS = new Set(PARAMS_PERMITIDOS)

/** El comienzo de ruta sensible que tiene `pathname` ('/i/', '/claim'…), o null. */
export function rutaSensible(pathname) {
  // En minúsculas: el router no distingue, y /I/<token> abre el mismo informe.
  const p = typeof pathname === 'string' ? pathname.toLowerCase() : ''
  return RUTAS_SENSIBLES.find((r) => p.startsWith(r)) || null
}

/**
 * true si la dirección NO se le puede mostrar entera a un tercero: es una ruta
 * sensible o lleva algún parámetro que no está en PARAMS_PERMITIDOS.
 */
export function urlTieneDatosSensibles(pathname, search) {
  if (rutaSensible(pathname)) return true
  try {
    for (const k of new URLSearchParams(search || '').keys()) {
      if (!PERMITIDOS.has(k)) return true
    }
    return false
  } catch {
    return true // query ilegible → no arriesgar
  }
}

/**
 * La dirección que se le puede dar a un tercero: la ruta con sólo los
 * parámetros permitidos (y sin el `#…`); de una ruta sensible, sólo su
 * comienzo. '' si no se puede leer.
 */
export function direccionParaTerceros(href) {
  let u
  try { u = new URL(href) } catch { return '' }
  const sensible = rutaSensible(u.pathname)
  if (sensible) return u.origin + sensible
  const permitidos = new URLSearchParams()
  for (const [k, v] of u.searchParams) if (PERMITIDOS.has(k)) permitidos.append(k, v)
  const qs = permitidos.toString()
  return u.origin + u.pathname + (qs ? `?${qs}` : '')
}

/**
 * De dónde venía la persona, como se le puede dar a un tercero. Una página web:
 * la misma limpieza que direccionParaTerceros. Una app (en Android el Gmail o
 * el buscador de Google llegan como android-app://com.google.android.gm/…):
 * entera menos la query y el `#…` — es como la lee la atribución, y new URL le
 * da origen «null», así que con la limpieza de las páginas quedaba «null/…».
 */
export function referenteParaTerceros(referrer) {
  if (!referrer) return ''
  let u
  try { u = new URL(referrer) } catch { return '' }
  if (u.protocol === 'http:' || u.protocol === 'https:') return direccionParaTerceros(referrer)
  return `${u.protocol}//${u.host}${u.pathname}`
}

/**
 * true si `referrer` (de dónde venía la persona) es una dirección de Rendi que
 * no se le puede mostrar entera a un tercero. Las de otros sitios no cuentan:
 * no son datos de la persona en Rendi y la atribución de los anuncios las usa.
 */
export function referenteConDatos(referrer) {
  if (!referrer) return false
  let u
  try { u = new URL(referrer) } catch { return true }
  if (!SITIOS_MEDIDOS.includes(u.hostname)) return false
  return urlTieneDatosSensibles(u.pathname, u.search)
}
