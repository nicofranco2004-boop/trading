// metaPixel — wrapper del Meta (Facebook) Pixel para Rendi.
// ════════════════════════════════════════════════════════════════════════════
// El Meta Pixel le avisa a Meta (Facebook/Instagram Ads) qué pasa en el sitio:
//   • PageView            — automático al cargar. Alimenta la audiencia
//                           "visitantes del sitio" para retargeting.
//   • CompleteRegistration — cuando un user completa el signup. Es el evento de
//                           CONVERSIÓN que Meta usa para optimizar campañas y
//                           medir costo por registro.
//
// Igual que GA4 (ver analytics.js), el Pixel ID es PÚBLICO por diseño (aparece
// en el HTML de cualquier sitio que lo use), no es secret. Por eso lo dejamos
// hardcodeado acá — y porque Vercel no inyectaba bien los env var VITE_ (mismo
// problema documentado en analytics.js con el GA_ID).
//
// CÓMO ACTIVARLO (cuando tengas la cuenta de Meta Ads):
//   1. Creá el Pixel/Dataset en Meta Events Manager (business.facebook.com).
//   2. Copiá el Pixel ID (numérico, ~15 dígitos).
//   3. Pegalo abajo en META_PIXEL_ID y hacé deploy.
// Mientras esté vacío, todo este módulo es no-op: la app funciona igual y no
// carga nada de Meta. Lo mismo fuera de rendi.finance (ver utils/medicion.js):
// una prueba en el servidor local no es un visitante ni un registro.
//
// QUÉ DIRECCIÓN VE META. fbevents lee la dirección y la página anterior por su
// cuenta en cada envío. Al 2026-11-05 no salían enteras por dos cosas que no
// están en este archivo: el envío directo a Meta las recorta (el píxel está en
// «modo de datos protegidos», por ser finanzas) y la copia que va al servidor
// de Meta en Amazon (el «Conversions API Gateway», que las lleva completas) la
// frena la política de seguridad de vercel.json, que no incluye ese servidor.
// Si cambia cualquiera de las dos, salen enteras. No hay forma de darle otra
// dirección, así que el píxel sólo habla en una limpia (rutasSensibles.js):
//   · index.html lo inicia sólo si se entra por una dirección limpia, y le
//     apaga las vistas que manda solo cuando la app cambia la dirección
//     (disablePushState) y los eventos automáticos (autoConfig). Si no, queda
//     'esperando' y se inicia acá en la primera dirección limpia.
//   · Las vistas al navegar las manda trackMetaPageView. Sin
//     allowDuplicatePageViews, fbevents descarta toda vista después de la
//     primera de la carga: hasta el 2026-11-05 las de la navegación salían
//     sólo por el mecanismo automático, el que no miraba la dirección.
//   · Lo que se pide en una dirección que no es limpia (el CompleteRegistration
//     sale en /verify-email) espera y sale en la próxima limpia: así no se
//     pierde la conversión de los anuncios.

import { seMideAca } from './medicion'
import { referenteConDatos, urlTieneDatosSensibles } from './rutasSensibles'

const META_PIXEL_ID = '1281911210681122' // ← Pixel "Rendi" del ad account (Events Manager).
// Antes apuntaba a 1313319913641013, que NO existía en esta cuenta publicitaria →
// la web mandaba eventos al vacío y el pixel real (1281...) figuraba "sin actividad".

const DEBUG = typeof window !== 'undefined' && window.location?.hostname === 'localhost'

let initialized = false

// Lo pedido en una dirección que no es limpia, para la próxima que sí.
const pendientes = []
const MAX_PENDIENTES = 20

function direccionLimpia() {
  return !urlTieneDatosSensibles(window.location.pathname, window.location.search)
    && !referenteConDatos(document.referrer)
}

// index.html deja 'iniciado' o 'esperando' en window.__rendiPixel.
function iniciarSiFalta() {
  if (window.__rendiPixel === 'iniciado') return
  window.fbq('init', META_PIXEL_ID)
  window.__rendiPixel = 'iniciado'
}

// En una dirección que no es limpia el píxel queda «callado» con el
// interruptor de consentimiento de fbevents: mientras está cerrado, fbevents
// retiene lo que intenta mandar y lo manda al reabrirse, con la dirección de
// ese momento (verificado con el fbevents real). Es lo único que frena lo que
// fbevents manda solo y disablePushState no apaga: la vista al volver con
// «Atrás» desde otro sitio, cuando el navegador restaura la página guardada.
let callado = false

function callar() {
  if (callado || window.__rendiPixel !== 'iniciado') return
  window.fbq('consent', 'revoke')
  callado = true
}

function permitir() {
  if (!callado) return
  window.fbq('consent', 'grant')
  callado = false
}

/** En cada cambio de dirección, también de parámetros (RouteTracker). */
export function sincronizarPixelConLaDireccion() {
  if (!seMideAca() || !window.fbq) return
  if (direccionLimpia()) permitir()
  else callar()
}

/**
 * Inicializa el Meta Pixel. Llamar 1 sola vez al arranque de la app (main.jsx).
 * No-op si META_PIXEL_ID está vacío → la app sigue funcionando sin tracking.
 */
export function initMetaPixel() {
  if (initialized) return
  if (!META_PIXEL_ID || !seMideAca()) {
    if (DEBUG) {
      // eslint-disable-next-line no-console
      console.log('[meta-pixel] no es rendi.finance — el pixel no se carga')
    }
    return
  }

  // El snippet ESTÁTICO de index.html ya crea window.fbq y, si se entró por
  // una dirección limpia, dispara el init + PageView inicial al parsear el HTML
  // (antes que React, así sobrevive incluso si el bundle falla). Si ya existe,
  // NO re-inicializamos: un segundo fbq('init')+fbq('track','PageView')
  // duplicaría el PageView en Events Manager y ensuciaría la atribución. Solo
  // marcamos initialized; si quedó 'esperando', lo inicia trackMetaEvent.
  if (window.fbq) {
    initialized = true
    if (DEBUG) {
      // eslint-disable-next-line no-console
      console.log('[meta-pixel] ya inicializado por index.html — sin re-init')
    }
    return
  }

  // Fallback: si por algún motivo no está el snippet estático (index.html sin
  // el bloque), inicializamos acá para no perder el pixel.
  /* eslint-disable */
  !function (f, b, e, v, n, t, s) {
    if (f.fbq) return; n = f.fbq = function () {
      n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments)
    }
    if (!f._fbq) f._fbq = n; n.push = n; n.loaded = !0; n.version = '2.0'
    n.queue = []; t = b.createElement(e); t.async = !0
    t.src = v; s = b.getElementsByTagName(e)[0]
    s.parentNode.insertBefore(t, s)
  }(window, document, 'script', 'https://connect.facebook.net/en_US/fbevents.js')
  /* eslint-enable */

  // Lo mismo que hace index.html (ver arriba «QUÉ DIRECCIÓN VE META»).
  window.fbq.disablePushState = true
  window.fbq.allowDuplicatePageViews = true
  window.fbq('set', 'autoConfig', false, META_PIXEL_ID)
  window.__rendiPixel = 'esperando'
  if (direccionLimpia()) {
    iniciarSiFalta()
    window.fbq('track', 'PageView')
  }

  initialized = true
  if (DEBUG) {
    // eslint-disable-next-line no-console
    console.log('[meta-pixel] inicializado:', META_PIXEL_ID)
  }
}

/**
 * Dispara un evento estándar del Pixel (CompleteRegistration, Lead, etc.).
 * No-op si el pixel no está inicializado / no está seteado el ID.
 *
 * @param {string} name   evento estándar de Meta (e.g. 'CompleteRegistration')
 * @param {object} params opcional. NO mandar PII (email, nombre, montos).
 */
export function trackMetaEvent(name, params = {}) {
  if (!seMideAca() || !window.fbq) {
    if (DEBUG) {
      // eslint-disable-next-line no-console
      console.log('[meta-pixel] (noop)', name, params)
    }
    return
  }
  if (!direccionLimpia()) {
    if (pendientes.length < MAX_PENDIENTES) pendientes.push([name, params])
    return
  }
  permitir()
  iniciarSiFalta()
  window.fbq('track', name, params)
  if (DEBUG) {
    // eslint-disable-next-line no-console
    console.log('[meta-pixel]', name, params)
  }
}

/**
 * PageView manual — para route changes en la SPA. Opcional: con el PageView
 * del init ya alcanza para la audiencia "visitantes". Engancharlo en el
 * RouteTracker da granularidad (retargetear "vio /planes", etc.).
 */
export function trackMetaPageView() {
  // En una dirección que no es limpia, ni la vista ni lo que esperaba: todo
  // sale en la próxima limpia (ver arriba «QUÉ DIRECCIÓN VE META»).
  if (!seMideAca() || !window.fbq || !direccionLimpia()) return
  trackMetaEvent('PageView')
  while (pendientes.length) {
    const [name, params] = pendientes.shift()
    trackMetaEvent(name, params)
  }
}
