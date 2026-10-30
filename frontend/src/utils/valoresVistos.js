// valoresVistos — para que una métrica muestre CÓMO CAMBIÓ después de que el
// usuario hizo algo (cobró un cupón o un dividendo, vendió con ganancia o
// pérdida, depositó, borró un movimiento…). Pedido de Nico, 2026-10-10.
//
// Dos piezas:
//
//   1. La VERSIÓN de la cartera: un contador que sube cada vez que una escritura
//      toca la cartera. No se engancha acción por acción: escucha el aviso
//      central que ya emite utils/api.js en CADA escritura que sale bien
//      (`EVENTO_ESCRITURA`) y el del importador y el chat
//      (`rendi:portfolio-changed`). Una acción nueva queda cubierta sin que
//      nadie se acuerde de esto — enganchar caso por caso es como se genera la
//      deuda de "se arregló en 1 de N lugares".
//
//   2. El último valor VISTO de cada métrica, con la versión en la que se vio.
//      Al mostrarse de nuevo: si la versión subió y el valor es otro, la
//      métrica cuenta del viejo al nuevo y muestra la diferencia
//      (<NumeroQueCambia>). Si la versión es la misma, no hace nada: lo que se
//      movió fueron los precios, y eso no es "tu cambio".
//
// Límite que hay que saber: en un número que depende de precios (el total, la
// ganancia no realizada) la diferencia que se muestra es la del número entero
// —el cambio del usuario MÁS lo que se movió el mercado desde que se vio—. Por
// eso la etiqueta dice "respecto de antes" y no "por tu cambio", y por eso lo
// visto caduca (CADUCA_MS).
//
// Todo es de UNA cuenta (la propia o la del cliente del asesor) y sus claves
// empiezan con `rendi_`, que es lo que borra el cierre de sesión — mismas dos
// reglas que utils/cambioDeMovimiento.js, y por la misma auditoría.
// sessionStorage: de esta pestaña y de esta visita; sin almacenamiento no hay
// animación y nada se rompe.

import { EVENTO_ESCRITURA } from './api'
import { duenoDeLaPestana } from './duenoDeLaPestana'
import { leerDe, guardarDe } from './almacen'
import { CATALOGO } from './catalogoDelAlmacen'

// De la persona Y de la cuenta DE LOS DATOS (utils/duenoDeLaPestana). Antes
// sólo de la cuenta: «Cerrar sesión» lo borra, pero una sesión que vence no, y
// el siguiente en la pestaña veía su número «cambiar» desde el de la anterior.
// La pantalla pasa SIEMPRE el dueño de lo que muestra (useDuenoDeLosDatos): sin
// dueño no se lee ni se guarda nada (antes caía al de la pestaña, la forma del
// error del re-test 2; re-test 3). La puerta
// (utils/almacen.guardarDe) no guarda para un dueño que ya no es el de la
// pestaña, ni sin nadie logueado.
function leer(entrada, dueno, resto) {
  try { return JSON.parse(leerDe(entrada, dueno, resto) || 'null') } catch { return null }
}
function escribir(entrada, dueno, valor, resto) {
  try { guardarDe(entrada, dueno, JSON.stringify(valor), resto) } catch { /* sin almacenamiento */ }
}

/** Cuántas veces cambió la cartera de esta cuenta en esta visita. */
export function versionDeCartera(dueno) {
  const v = leer(CATALOGO.versionCartera, dueno)
  return Number.isFinite(v) ? v : 0
}

/** Algo cambió la cartera (lo llama el aviso central; no hace falta a mano). */
export function subirVersionDeCartera(dueno) {
  escribir(CATALOGO.versionCartera, dueno, versionDeCartera(dueno) + 1)
}

/** La métrica `clave` se está mostrando con este valor (de los datos de `dueno`). */
export function recordarValor(clave, valor, moneda, dueno) {
  if (Number.isFinite(valor)) {
    escribir(CATALOGO.valorVisto, dueno, { valor, moneda, version: versionDeCartera(dueno), t: Date.now() }, `:${clave}`)
  }
}

// Pasado este rato, lo que se vio ya no sirve de "antes": nadie se acuerda del
// número, y en los que dependen de precios la diferencia sería casi toda del
// mercado, no del cambio del usuario.
export const CADUCA_MS = 30 * 60 * 1000

/**
 * El valor que tenía `clave` la última vez que se vio, SÓLO si desde entonces
 * la cartera cambió (y se estaba mirando en la misma moneda). Si no, null: no
 * hay cambio del usuario que mostrar.
 */
export function valorAntesDelCambio(clave, moneda, dueno) {
  const g = leer(CATALOGO.valorVisto, dueno, `:${clave}`)
  if (!g || !Number.isFinite(g.valor) || g.moneda !== moneda) return null
  if (!Number.isFinite(g.t) || Date.now() - g.t > CADUCA_MS) return null
  return g.version < versionDeCartera(dueno) ? g.valor : null
}

// El aviso central. Se engancha una vez, al cargar la app (App.jsx importa este
// archivo): tiene que estar escuchando ANTES de la primera escritura.
let enganchado = false
export function engancharVersionDeCartera() {
  if (enganchado || typeof window === 'undefined' || typeof window.addEventListener !== 'function') return
  enganchado = true
  // El dueño de la PESTAÑA a propósito, y es el único lugar: el aviso llega
  // apenas termina una escritura, y la escritura fue de la cuenta de la pestaña
  // (api.js le puso ese cliente al pedido). No es un número de una pantalla.
  const subir = () => subirVersionDeCartera(duenoDeLaPestana())
  window.addEventListener(EVENTO_ESCRITURA, subir)
  window.addEventListener('rendi:portfolio-changed', subir)
}
engancharVersionDeCartera()
