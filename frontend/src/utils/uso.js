// uso — junta lo que se toca en Rendi y lo manda en tandas a /api/uso/eventos.
// ═══════════════════════════════════════════════════════════════════════════
// El backend guarda UN contador por usuario, evento y día (`uso_diario`). Acá
// se suma en memoria y se manda:
//   · cada 30 s si hay algo pendiente,
//   · al esconder o cerrar la pestaña (fetch con keepalive: el navegador lo
//     termina de mandar aunque la página ya se haya ido).
//
// Sólo se manda con una sesión real (AuthContext llama `activarUso`). En el
// demo o sin sesión no sale nada. Y sólo viaja el NOMBRE del evento y cuántas
// veces: ningún dato de la pantalla.
//
// ⚠️ NADA SE MANDA HASTA QUE LA PERSONA INTERACTÚA con esta carga de la página
// (toca, hace clic, tipea o scrollea). Auditoría 2026-10-08: una pestaña
// olvidada abierta se recarga sola cada vez que se publica una versión nueva
// (utils/autoUpdate.js) y el navegador reabre pestañas al arrancar. Sin esta
// condición, cada recarga contaba como "usó la app ese día" a alguien que no
// estaba ni mirando. Lo juntado sin interacción se descarta al esconderse.
//
// "Abrió la app" (`app_abierta`) se marca al activar y cada vez que la pestaña
// vuelve a verse en un día nuevo: cuenta a quien entra con la sesión ya
// abierta, que no pasa por el login.

import { NO_SE_CUENTAN, EVENTOS, claveDeUso, pantallaDe } from './usoCatalogo'

const CADA_MS = 30_000
const SENALES = ['pointerdown', 'keydown', 'wheel', 'touchstart']
let activo = false
let interactuo = false
let pendientes = {}
let timer = null
let ultimoDiaAbierta = null

function hoyLocal() {
  const d = new Date()
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`
}

function programar() {
  if (activo && interactuo && !timer && Object.keys(pendientes).length) timer = setTimeout(mandar, CADA_MS)
}

function sumar(clave, n = 1) {
  if (!activo || !clave) return
  pendientes[clave] = (pendientes[clave] || 0) + n
  programar()
}

/** Para track(): cuenta el evento si está en el catálogo (y no es de GA). */
export function registrarUso(evento) {
  if (NO_SE_CUENTAN.has(evento)) return
  if (EVENTOS[evento]?.soloGA) return
  sumar(claveDeUso(evento))
}

/** Para analytics.trackEvent(): sólo lo que hasta ahora iba nada más que a GA. */
export function registrarUsoGA(evento) {
  if (EVENTOS[evento]?.soloGA) sumar(claveDeUso(evento))
}

/** Para el cambio de ruta: la pantalla con su nombre fijo. */
export function registrarPantalla(pathname) {
  const p = pantallaDe(pathname)
  if (p) sumar(p)
}

function marcarAbierta() {
  const hoy = hoyLocal()
  if (ultimoDiaAbierta === hoy) return
  ultimoDiaAbierta = hoy
  sumar('app_abierta')
}

export function mandar({ alCerrar = false } = {}) {
  clearTimeout(timer)
  timer = null
  if (!activo || !interactuo) return Promise.resolve()
  const lote = pendientes
  pendientes = {}
  if (!Object.keys(lote).length) return Promise.resolve()
  return fetch('/api/uso/eventos', {
    method: 'POST',
    credentials: 'include',
    keepalive: alCerrar,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ eventos: lote }),
  }).catch(() => {
    // Telemetría: si no salió, se pierde. No se reintenta para no duplicar
    // un envío que el servidor sí haya recibido.
  })
}

function alInteractuar() {
  if (interactuo) return
  interactuo = true
  for (const s of SENALES) window.removeEventListener(s, alInteractuar, true)
  programar()
}

function alCambiarVisibilidad() {
  if (document.visibilityState === 'hidden') {
    if (interactuo) mandar({ alCerrar: true })
    else pendientes = {}   // nadie la tocó: lo de esta carga no fue uso
  } else {
    marcarAbierta()
  }
}
function alIrse() { if (interactuo) mandar({ alCerrar: true }) }

/**
 * Lo llama AuthContext: `true` con una sesión real (no demo), `false` al
 * salir. Al desactivar se descarta lo pendiente: la sesión ya no es de esa
 * persona y no se le puede atribuir.
 */
export function activarUso(si) {
  if (typeof window === 'undefined') return
  if (!!si === activo) return
  activo = !!si
  if (activo) {
    document.addEventListener('visibilitychange', alCambiarVisibilidad)
    window.addEventListener('pagehide', alIrse)
    if (!interactuo) for (const s of SENALES) window.addEventListener(s, alInteractuar, { capture: true, passive: true })
    ultimoDiaAbierta = null
    marcarAbierta()
    registrarPantalla(window.location.pathname)
  } else {
    document.removeEventListener('visibilitychange', alCambiarVisibilidad)
    window.removeEventListener('pagehide', alIrse)
    for (const s of SENALES) window.removeEventListener(s, alInteractuar, true)
    clearTimeout(timer)
    timer = null
    pendientes = {}
  }
}

// Para los tests.
export function _estadoUso() { return { activo, interactuo, pendientes: { ...pendientes } } }
