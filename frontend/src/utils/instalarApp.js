// instalarApp — lo que Rendi sabe sobre «ponerla en el celular».
// ═══════════════════════════════════════════════════════════════════════════
// Rendi no está en App Store ni en Play Store: se instala desde el navegador
// («Agregar a inicio»). El manifiesto y los meta tags que lo permiten ya viven
// en index.html + public/site.webmanifest; este archivo sólo contesta tres
// preguntas para el cartel de InstalarAppModal:
//
//   1. ¿En qué celular está? (para abrir en la pestaña correcta)
//   2. ¿Ya la tiene instalada? (para no ofrecerle instalar lo que ya instaló)
//   3. ¿El navegador deja instalar con un toque? (sólo Chrome en Android)

import { useSyncExternalStore } from 'react'
import { api } from './api'

/** 'iphone' | 'android' | 'otro' (computadora, o algo que no reconocemos). */
export function plataformaDe({ userAgent = '', maxTouchPoints = 0 } = {}) {
  const ua = String(userAgent || '')
  if (/android/i.test(ua)) return 'android'
  if (/iphone|ipad|ipod/i.test(ua)) return 'iphone'
  // El iPad se presenta como una Mac desde iPadOS 13. La única «Mac» con
  // pantalla táctil es un iPad: los pasos son los mismos que en iPhone.
  if (/macintosh/i.test(ua) && maxTouchPoints > 1) return 'iphone'
  return 'otro'
}

/** Teléfono o tablet: donde «Agregá Rendi a tu celular» tiene sentido. */
export function esCelular(plataforma) {
  return plataforma === 'iphone' || plataforma === 'android'
}

/** ¿Está corriendo como app instalada (sin las barras del navegador)? */
export function yaInstalada(win = typeof window !== 'undefined' ? window : undefined) {
  if (!win) return false
  try {
    // iPhone no implementa display-mode en todas las versiones: usa esta marca.
    if (win.navigator?.standalone === true) return true
    return Boolean(win.matchMedia?.('(display-mode: standalone)')?.matches)
  } catch {
    return false
  }
}

// ─── Instalación de un toque (Chrome en Android) ────────────────────────────
// Chrome avisa con `beforeinstallprompt` cuando la página se puede instalar, y
// ese aviso trae el botón: `prompt()` abre el cartel «Instalar app» del propio
// navegador. El aviso llega UNA vez, al cargar, mucho antes de que alguien abra
// nuestro cartel — por eso se escucha desde el arranque (main.jsx) y se guarda.
//
// A propósito NO se llama `preventDefault()`: eso apagaría la barrita «Agregar
// Rendi a la pantalla principal» que Chrome ya le muestra solo a quien entra
// desde Android, y este cambio no viene a sacarle a nadie un camino que hoy
// funciona.
let aviso = null
const oyentes = new Set()
const avisar = () => oyentes.forEach(f => f())

// SÓLO en Android: Chrome y Edge de la COMPU también mandan el aviso, y el
// botón terminaba instalando Rendi en la compu desde un paso que dice «Agregá
// Rendi a tu celular» (auditoría 2026-10-19). En la compu el navegador igual
// ofrece instalar con su propio ícono en la barra de direcciones.
export function escucharInstalador(win = typeof window !== 'undefined' ? window : undefined) {
  if (!win?.addEventListener) return
  win.addEventListener('beforeinstallprompt', (e) => {
    if (plataformaDe(win.navigator || {}) !== 'android') return
    aviso = e; avisar()
  })
  win.addEventListener('appinstalled', () => { aviso = null; avisar() })
}

export function hayInstalador() {
  return aviso != null
}

/** Abre el cartel del navegador. Devuelve 'accepted' | 'dismissed' | 'no-disponible' | 'error'. */
export async function instalarAhora() {
  const e = aviso
  if (!e) return 'no-disponible'
  // `prompt()` sirve una sola vez por aviso: se suelta antes de usarlo para
  // que el botón desaparezca y no quede uno que al tocarlo no hace nada.
  aviso = null
  avisar()
  try {
    await e.prompt()
    const { outcome } = await e.userChoice
    // Aceptó: el ícono ya está en su inicio. Se avisa ya (lo usan la lista y el
    // paso a paso de «Descargar app»): si no, el paso volvía a aparecer en Chrome
    // y en la compu hasta que la abriera desde el ícono.
    if (outcome === 'accepted') avisarAlServidor(null)
    return outcome
  } catch {
    return 'error'
  }
}

function suscribir(f) {
  oyentes.add(f)
  return () => oyentes.delete(f)
}

/** ¿Mostrar el botón «Instalar ahora»? Se actualiza solo cuando llega o se usa el aviso. */
export function useHayInstalador() {
  return useSyncExternalStore(suscribir, hayInstalador, () => false)
}

// ─── «Ya la tiene en el celular» ────────────────────────────────────────────
// Abierta desde el ícono del inicio de un celular → se le avisa al servidor
// (users.app_instalada_at), que tilda «Agregá Rendi a tu celular» en todos
// lados, también en la compu. Va apenas hay sesión, sin esperar a que toque
// nada (la medición de uso sí espera, y perdía a quien sólo entra a mirar).
//
// UNA vez por persona y dispositivo, recordado en el propio teléfono: el
// servidor guarda la primera fecha y no la pisa, así que repetirlo en cada
// apertura sólo ocupaba el turno de escritura de la base (auditoría 2026-10-19).
// Si el aviso falla, no se recuerda: se reintenta la próxima vez que la abra.
const CLAVE_AVISADA = 'rendi_instalada_avisada'
let enVuelo = false

function yaAvisado(quien) {
  try { return localStorage.getItem(CLAVE_AVISADA) === String(quien) } catch { return false }
}

function avisarAlServidor(quien) {
  if (enVuelo || (quien != null && yaAvisado(quien))) return false
  enVuelo = true
  api.post('/primeros-pasos/instalada', {})
    .then(() => { try { if (quien != null) localStorage.setItem(CLAVE_AVISADA, String(quien)) } catch { /* sin almacenamiento: se repite, no pasa nada */ } })
    .catch(() => {})
    .finally(() => { enVuelo = false })
  return true
}

/** Al arrancar la sesión (AuthContext). `quien` = la persona, para no mezclar cuentas en un mismo teléfono. */
export function avisarSiEstaInstalada(quien, win = typeof window !== 'undefined' ? window : undefined) {
  if (!win || !yaInstalada(win)) return false
  if (!esCelular(plataformaDe(win.navigator || {}))) return false
  return avisarAlServidor(quien)
}
