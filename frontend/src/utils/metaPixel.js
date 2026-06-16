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
// carga nada de Meta.

const META_PIXEL_ID = '1281911210681122' // ← Pixel "Rendi" del ad account (Events Manager).
// Antes apuntaba a 1313319913641013, que NO existía en esta cuenta publicitaria →
// la web mandaba eventos al vacío y el pixel real (1281...) figuraba "sin actividad".

const DEBUG = typeof window !== 'undefined' && window.location?.hostname === 'localhost'

let initialized = false

/**
 * Inicializa el Meta Pixel. Llamar 1 sola vez al arranque de la app (main.jsx).
 * No-op si META_PIXEL_ID está vacío → la app sigue funcionando sin tracking.
 */
export function initMetaPixel() {
  if (initialized) return
  if (!META_PIXEL_ID || typeof window === 'undefined') {
    if (DEBUG) {
      // eslint-disable-next-line no-console
      console.log('[meta-pixel] META_PIXEL_ID no seteado — pixel deshabilitado')
    }
    return
  }

  // Snippet oficial del Meta Pixel (carga fbevents.js async). Define window.fbq
  // y encola las llamadas hasta que el script termina de cargar.
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

  window.fbq('init', META_PIXEL_ID)
  window.fbq('track', 'PageView')

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
  if (typeof window === 'undefined' || !window.fbq) {
    if (DEBUG) {
      // eslint-disable-next-line no-console
      console.log('[meta-pixel] (noop)', name, params)
    }
    return
  }
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
  trackMetaEvent('PageView')
}
