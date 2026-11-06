// analytics — wrapper de Google Analytics 4 + helpers de eventos custom.
// ════════════════════════════════════════════════════════════════════════════
// Inicializa GA4 sólo en rendi.finance (ver utils/medicion.js): el servidor
// local y los previews no cargan gtag ni mandan nada.
//
// Eventos custom que trackeamos (alineados con embudo Rendi):
//
//   SEO / acquisition:
//     page_view (automático en SPA via RouteTracker)
//
//   Activation:
//     sign_up           — user confirma email
//     login             — user inicia sesión (no demo)
//     first_position_added — primera vez que carga una posición/operación
//
//   Conversion:
//     paywall_blocked   — click en CTA bloqueado por tier (de track.js)
//     subscribe_clicked — click en CTA "Suscribirme" de /planes
//     subscribe_started — POST /api/billing/subscribe OK (Rebill payment link)
//     subscribe_completed — user vuelve de Rebill exitoso (BillingSuccess)
//     plan_changed      — change_plan exitoso
//     plan_cancelled    — user canceló suscripción
//
//   Engagement:
//     ai_analyze_clicked  — click en "Analizar" de alguna page
//     ai_chat_sent        — user mandó mensaje al Coach IA
//     report_exported     — descargó CSV
//     wrapped_viewed      — abrió Wrapped anual
//
// Privacy: anonymize_ip=true. No mandamos email, name ni amount_usd en
// los params — solo IDs/categorías. Tampoco el número de cuenta (setUserId).
// La dirección que lleva CADA envío la decide rutasSensibles.js (ver
// actualizarDireccionParaGoogle).

import { seMideAca } from './medicion'
import { registrarUsoGA } from './uso'
import { direccionParaTerceros, referenteParaTerceros, rutaSensible } from './rutasSensibles'

// GA4 Measurement ID — hardcoded porque Vercel no inyectaba el env var
// correctamente (problema con flag VITE_ exposed). El ID es público por
// diseño (aparece en el HTML de cualquier sitio que use GA4), no es secret.
// Si querés cambiarlo o deshabilitar tracking, cambialo acá directamente.
const GA_ID = 'G-DQ8LV6YJPP'

const DEBUG = typeof window !== 'undefined' && window.location?.hostname === 'localhost'

let initialized = false

/**
 * Inicializa GA4. Llamar 1 sola vez al arranque de la app (main.jsx).
 * Fuera de rendi.finance no hace nada — la app sigue funcionando, y como
 * `initialized` queda en false, trackEvent/setUserId/etc. (y el reenvío de
 * track.js, que mira `window.gtag`) tampoco mandan nada.
 */
export function initAnalytics() {
  if (initialized) return
  if (!GA_ID || !seMideAca()) {
    if (DEBUG) {
      // eslint-disable-next-line no-console
      console.log('[analytics] no es rendi.finance — GA4 no se carga')
    }
    return
  }

  // Cargar gtag.js async
  const script = document.createElement('script')
  script.async = true
  script.src = `https://www.googletagmanager.com/gtag/js?id=${GA_ID}`
  document.head.appendChild(script)

  window.dataLayer = window.dataLayer || []
  window.gtag = function () { window.dataLayer.push(arguments) }

  window.gtag('js', new Date())
  window.gtag('config', GA_ID, {
    // SPA: vamos a llamar gtag('event', 'page_view', ...) manualmente
    // en cada route change vía RouteTracker. Para que GA4 no duplique
    // el page_view inicial, lo desactivamos acá.
    send_page_view: false,
    anonymize_ip: true,
    // No queremos signal data (mejora privacy)
    allow_google_signals: false,
    allow_ad_personalization_signals: false,
  })

  initialized = true
  // Antes del primer envío: gtag.js todavía no cargó y esto queda en la cola.
  actualizarDireccionParaGoogle()
  if (DEBUG) {
    // eslint-disable-next-line no-console
    console.log('[analytics] GA4 inicializado:', GA_ID)
  }
}

// La dirección que lleva CADA envío a Google. gtag.js no la toma de nuestro
// page_view: la lee él mismo de la barra de direcciones en todo lo que manda
// solo —el scroll, los clics a otros sitios, el tiempo en la página— y en cada
// evento. Por eso filtrar sólo el page_view no alcanzaba: la cartera de «Una
// cartera» y el token del informe público (/i/<token>, con el nombre del
// cliente en el título) le llegaban igual. Con `set`, todo lo que sale después
// lleva ESTA dirección, la limpia (rutasSensibles.js). Verificado con el
// gtag.js real de la propiedad: audit/_scripts/fugas_a_terceros/.
//
// ⚠️ Lo único que no respeta el `set`: las vistas automáticas «por cambios en
// el historial del navegador» de la medición mejorada, que toman la dirección
// real y la anterior. Esa opción tiene que estar APAGADA en la propiedad
// (Admin → Flujos de datos → Web → Medición mejorada → Vistas de página →
// Mostrar configuración avanzada); las vistas de página las manda trackPageView.
let ultimaDireccion = null

/**
 * Le dice a Google la dirección limpia de AHORA. Llamar en cada cambio de
 * dirección, también cuando sólo cambian los parámetros (RouteTracker).
 */
export function actualizarDireccionParaGoogle() {
  if (!initialized || !window.gtag) return
  const direccion = direccionParaTerceros(window.location.href)
  if (direccion === ultimaDireccion) return
  window.gtag('set', {
    page_location: direccion,
    // De dónde venía: la dirección limpia anterior o, al entrar, la de afuera
    // (sin sus parámetros: la atribución usa el sitio o la app, no la query).
    page_referrer: ultimaDireccion ?? referenteParaTerceros(document.referrer),
    // El título también viaja en cada envío, y el del informe público nombra
    // al cliente. `undefined` vuelve al título real de la página (verificado).
    page_title: rutaSensible(window.location.pathname) ? 'Rendi' : undefined,
  })
  ultimaDireccion = direccion
}

/**
 * Trackea un page view. Llamar en cada route change.
 * RouteTracker en App.jsx ya lo hace automático.
 */
// Las rutas con el SECRETO en la ruta misma (el token del informe = la cartera
// del cliente, el del claim = tomar la cuenta) no mandan vista de página: los
// demás envíos llevan sólo su comienzo (/i/), sin el token (audit RENDI-09).
// Las demás se mandan con sólo los parámetros permitidos.

export function trackPageView(path, title) {
  if (!initialized || !window.gtag) return
  actualizarDireccionParaGoogle()
  if (rutaSensible(path || window.location.pathname)) return
  window.gtag('event', 'page_view', {
    page_path: path,
    page_title: title || document.title,
    page_location: direccionParaTerceros(window.location.href),
  })
  if (DEBUG) console.log('[analytics] page_view', path)
}

/**
 * Trackea un evento custom.
 *
 * @param name string  e.g. 'sign_up', 'subscribe_started', 'ai_chat_sent'
 * @param params object  opcional, params custom del evento.
 *
 * IMPORTANTE: no incluyas PII en params (email, name, amounts).
 * GA4 los puede mostrar en reportes Y los logueamos a console en dev.
 */
export function trackEvent(name, params = {}) {
  // Antes de mirar si GA está: el panel de uso cuenta aunque GA no cargue.
  registrarUsoGA(name)
  if (!initialized || !window.gtag) {
    if (DEBUG) console.log('[analytics] (noop)', name, params)
    return
  }
  window.gtag('event', name, params)
  if (DEBUG) console.log('[analytics]', name, params)
}

/**
 * El número de cuenta NO se le manda a Google. AuthContext la llama al entrar
 * y al salir; queda acá como el único lugar donde se decide.
 *
 * Hasta el 2026-11-05 hacía gtag('config', GA_ID, { user_id: String(uid) }) y
 * el comentario decía «hasheado»: no lo estaba, pero tampoco llegaba. La
 * propiedad tiene prendido «ignorar las configuraciones repetidas», así que
 * Google descartaba esa segunda llamada entera (verificado con su gtag.js
 * real: ningún envío llevaba `uid`). Y si alguien apagaba esa opción, la misma
 * llamada mandaba además una vista de página con la dirección completa, sin
 * pasar por rutasSensibles.js. Si algún día se quiere unir a la misma persona
 * entre el celular y la compu: un seudónimo que arme el servidor, mandado con
 * gtag('set', { user_id }) — nunca otro 'config'.
 */
export function setUserId() {}

/**
 * Setea propiedades del user para segmentación (tier, has_broker, etc).
 * Útil para filtrar en GA4 reports: "users con tier=pro convierten al X%".
 */
export function setUserProperties(props) {
  if (!initialized || !window.gtag || !props) return
  window.gtag('set', 'user_properties', props)
  if (DEBUG) console.log('[analytics] user_properties', props)
}
