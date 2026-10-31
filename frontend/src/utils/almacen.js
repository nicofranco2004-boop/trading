// almacen — LA ÚNICA PUERTA al almacenamiento del navegador (localStorage y
// sessionStorage). Ningún otro archivo de la app los nombra: lo vigila
// src/__guards__/claves-del-navegador.test.js, que se pone rojo con CUALQUIER
// mención fuera de acá, sin intentar adivinar las formas de escribir.
//
// Sólo se lee y se escribe lo que está en utils/catalogoDelAlmacen.js, y cada
// entrada declara qué es (dato de una cuenta, preferencia, la sesión) y por qué.
//
// 🔴 LOS DATOS DE UNA CUENTA LLEVAN EL DUEÑO DE LOS DATOS, NO EL DE LA PESTAÑA.
// Re-test a ciegas 2 (30/10): la pantalla de Ana abierta, otra pestaña entra
// como Bruno, y lo que la pantalla de Ana guardaba después iba a nombre de
// Bruno: el número de Ana en el casillero de Bruno, y Bruno veía «+200 %». El
// dueño se decidía AL GUARDAR, mirando de quién era la pestaña en ese momento,
// y no de qué cuenta venía el número: era cambiarle la etiqueta al frasco sin
// cambiar lo que tiene adentro. Por eso `guardarDe` recibe el dueño que tenían
// los datos cuando se pidieron o se calcularon (useDuenoDeLosDatos) y NO
// guarda si ese dueño ya no es el de la pestaña.
//
// Los almacenes se piden en cada llamada (no se guardan al cargar): así las
// pruebas que los reemplazan, y el navegador que los bloquea, se respetan.
// Ninguna función atrapa errores: quien llama decide qué hacer sin almacenamiento,
// igual que con la API del navegador.

import { CATALOGO, CON_DUENO, LOCAL, SESION } from './catalogoDelAlmacen'

// La regla de dueño (¿este dueño sigue siendo el de la pestaña?) la registra
// utils/duenoDeLaPestana al cargarse. No se importa desde acá A PROPÓSITO: la
// regla usa la puerta (lee la sesión) y api.js y demo.js también, y una
// importación en los dos sentidos armaba un círculo (puerta → regla → api →
// demo → puerta). En las pruebas que reemplazan demo.js por otro, ese círculo
// hacía que api.js se quedara con el demo ORIGINAL. Si la regla no se registró,
// la puerta no guarda datos de una cuenta: falla del lado seguro.
let reglaDeDueno = null
export function registrarReglaDeDueno(sigueSiendoDe) { reglaDeDueno = sigueSiendoDe }
const sigueSiendoDe = (dueno, opciones) => !!reglaDeDueno && reglaDeDueno(dueno, opciones)

// Sin constantes de módulo armadas al cargar: api.js usa la puerta MIENTRAS se
// carga (borra la sesión vieja, lee el cliente abierto), y la puerta y la regla
// se importan entre sí. Según qué archivo se cargue primero, una constante de
// acá podría no estar lista todavía; el catálogo sí (se importa antes).
// Se compara por lo que la entrada declara (clave o prefijo, tipo, dónde vive) y
// no por ser el mismo objeto: una prueba que vuelve a cargar los módulos tiene
// otra copia del catálogo, con las mismas entradas.
const igual = (a, b) => a.clave === b.clave && a.prefijo === b.prefijo && a.tipo === b.tipo
  && a.donde === b.donde && !!a.deLaPersona === !!b.deLaPersona
const delCatalogo = (entrada) => (entrada && typeof entrada === 'object'
  ? Object.values(CATALOGO).find(e => igual(e, entrada)) : undefined)

/** El almacén del navegador ('local' o 'sesion'). Puede tirar (bloqueado). */
function tienda(donde) {
  if (donde !== LOCAL && donde !== SESION) throw new Error(`almacen: «${donde}» no es un almacén`)
  return donde === SESION ? globalThis.sessionStorage : globalThis.localStorage
}

function entradaValida(pedida, conDueno) {
  const entrada = delCatalogo(pedida)
  if (!entrada) throw new Error('almacen: esa clave no está en utils/catalogoDelAlmacen.js')
  if (conDueno && entrada.tipo !== CON_DUENO) throw new Error('almacen: esa entrada no es un dato de una cuenta')
  if (!conDueno && entrada.tipo === CON_DUENO) {
    throw new Error('almacen: un dato de una cuenta se lee y se guarda con su dueño (leerDe / guardarDe)')
  }
  return entrada
}

// Una familia que no es de una cuenta (la conversación con la IA) dice qué
// puede seguir al prefijo (`restos`): sin eso, cualquier sufijo era una clave
// nueva que nadie clasificó.
function claveDe(entrada, resto = '') {
  if (entrada.clave != null) return entrada.clave
  if (!entrada.restos || !entrada.restos.test(String(resto))) {
    throw new Error(`almacen: «${entrada.prefijo}${resto}» no es de las que declara utils/catalogoDelAlmacen.js`)
  }
  return entrada.prefijo + resto
}
const claveConDueno = (entrada, dueno, resto = '') => `${entrada.prefijo}${dueno}${resto}`

/** ¿Hay almacenamiento? (iOS privado, un navegador que lo bloquea) */
export function hay(donde = LOCAL) {
  try { return !!tienda(donde) } catch { return false }
}

// ── Preferencias, la sesión y lo de dueño propio ────────────────────────────

/** Lo guardado en `entrada` (con `resto` si es una familia), o null. */
export function leer(entrada, resto = '') {
  const e = entradaValida(entrada, false)
  return tienda(e.donde).getItem(claveDe(e, resto))
}

// 🔴 QUIÉN ESTÁ LOGUEADO EN ESTA PESTAÑA (re-test a ciegas 4, 30/10). La sesión
// guardada es una para todo el navegador; cuando la cambia ESTA pestaña (entrar,
// salir, refrescar el usuario, la sesión que vence) la puerta lo avisa con
// EVENTO_SESION_DE_LA_PESTANA. Lo que escribe OTRA pestaña no pasa por esta
// puerta, así que no avisa: utils/api sabe así la persona de ESTA pestaña y la
// manda en cada pedido, para que el servidor no la atienda con la sesión de otra.
export const EVENTO_SESION_DE_LA_PESTANA = 'rendi:sesion-de-la-pestana'
function avisarSiTocaLaSesion(clave) {
  if (clave !== null && clave !== CATALOGO.usuario.clave) return
  try { globalThis.window?.dispatchEvent?.(new Event(EVENTO_SESION_DE_LA_PESTANA)) } catch { /* sin ventana */ }
}

export function guardar(entrada, valor, resto = '') {
  const e = entradaValida(entrada, false)
  tienda(e.donde).setItem(claveDe(e, resto), String(valor))
  avisarSiTocaLaSesion(claveDe(e, resto))
}

export function borrar(entrada, resto = '') {
  const e = entradaValida(entrada, false)
  tienda(e.donde).removeItem(claveDe(e, resto))
  avisarSiTocaLaSesion(claveDe(e, resto))
}

/**
 * Para las funciones que reciben «un almacén» (y en las pruebas, uno de
 * mentira): uno que sólo sabe leer y escribir `entrada`.
 */
export function almacenDe(entrada) {
  entradaValida(entrada, false)
  const sola = (k) => {
    if (k !== entrada.clave) throw new Error(`almacen: este almacén es sólo de ${entrada.clave}`)
    return k
  }
  return {
    getItem: (k) => tienda(entrada.donde).getItem(sola(k)),
    setItem: (k, v) => tienda(entrada.donde).setItem(sola(k), String(v)),
    removeItem: (k) => tienda(entrada.donde).removeItem(sola(k)),
  }
}

// ── Datos de una cuenta ─────────────────────────────────────────────────────

/** Lo guardado de `dueno` (el de los datos de la pantalla). Sin dueño, null. */
export function leerDe(entrada, dueno, resto = '') {
  entradaValida(entrada, true)
  if (!dueno) return null
  return tienda(entrada.donde).getItem(claveConDueno(entrada, dueno, resto))
}

/**
 * Guarda un dato que salió de los datos de `dueno`. NO lo guarda —y devuelve
 * false— si no hay dueño o si ya no es el de la pestaña: los datos son de una
 * cuenta y la pestaña ya está en otra. Devuelve true si lo guardó.
 */
export function guardarDe(entrada, dueno, valor, resto = '') {
  entradaValida(entrada, true)
  if (!sigueSiendoDe(dueno, { propio: !!entrada.deLaPersona })) return false
  tienda(entrada.donde).setItem(claveConDueno(entrada, dueno, resto), String(valor))
  return true
}

/** Borra lo de `dueno`. Mismo freno que guardarDe: sólo el dueño de la pestaña. */
export function borrarDe(entrada, dueno, resto = '') {
  entradaValida(entrada, true)
  if (!sigueSiendoDe(dueno, { propio: !!entrada.deLaPersona })) return false
  tienda(entrada.donde).removeItem(claveConDueno(entrada, dueno, resto))
  return true
}

/**
 * Pasa una copia de la versión anterior (`claveVieja`, sin dueño en la clave) a
 * su dueño, cuando el dueño se SABE por la copia misma (iba a nombre del email
 * de la persona → `email|propia`). Si ya hay una con dueño, gana la nueva. La
 * vieja se borra siempre.
 */
export function mudarCopiaVieja(entrada, claveVieja, dueno) {
  entradaValida(entrada, true)
  if (!dueno || !String(claveVieja).startsWith(entrada.prefijo)) return false
  const t = tienda(entrada.donde)
  const valor = t.getItem(claveVieja)
  const nueva = claveConDueno(entrada, dueno)
  if (valor != null && t.getItem(nueva) == null) t.setItem(nueva, valor)
  t.removeItem(claveVieja)
  return valor != null
}

// ── Barridos: sólo BORRAN (cerrar sesión, «limpiar y recargar», copias viejas) ─

/**
 * Borra lo que guardó en este navegador cualquier persona que no sea `persona`
 * (los datos de una cuenta: `<prefijo><persona>|<cuenta>…`). Lo llama
 * utils/api cuando la pestaña fija su persona: si la sesión de la anterior
 * venció sola, lo suyo quedaba acá, con su email en el nombre (re-test a
 * ciegas 5). Se salvan las entradas con `seConservaParaSuDueno`: guardan algo
 * que todavía no llegó a la cuenta (los dibujos pendientes) y su dueño lo
 * recupera al volver.
 */
export function borrarLoDeOtrasPersonas(persona) {
  if (!persona) return
  for (const e of Object.values(CATALOGO)) {
    if (e.tipo !== CON_DUENO || e.seConservaParaSuDueno) continue
    const t = tienda(e.donde)
    const ajenas = claves(e.donde).filter(k => k.startsWith(e.prefijo)
      && k.slice(e.prefijo.length).split('|')[0] !== persona)
    for (const k of ajenas) t.removeItem(k)
  }
}

/** Todas las claves de un almacén. */
export function claves(donde = LOCAL) {
  const t = tienda(donde)
  return Array.from({ length: t.length }, (_, i) => t.key(i)).filter(k => k != null)
}

/** Borra estas claves (cualesquiera: borrar no deja datos de nadie). */
export function quitarClaves(donde, lista) {
  const t = tienda(donde)
  for (const k of lista) t.removeItem(k)
  if (lista.includes(CATALOGO.usuario.clave)) avisarSiTocaLaSesion(CATALOGO.usuario.clave)
}

/** Vacía un almacén entero. */
export function vaciar(donde = LOCAL) {
  tienda(donde).clear()
  avisarSiTocaLaSesion(null)
}
