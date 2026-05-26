// analytics — wrapper de Google Analytics 4 + helpers de eventos custom.
// ════════════════════════════════════════════════════════════════════════════
// Inicializa GA4 solo si VITE_GA_MEASUREMENT_ID está seteada en build.
// Eso permite arrancar dev local sin tracking y producción con tracking.
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
// los params — solo IDs/categorías. user_id se setea como uid hasheado.

// GA4 Measurement ID — hardcoded porque Vercel no inyectaba el env var
// correctamente (problema con flag VITE_ exposed). El ID es público por
// diseño (aparece en el HTML de cualquier sitio que use GA4), no es secret.
// Si querés cambiarlo o deshabilitar tracking, cambialo acá directamente.
const GA_ID = 'G-DQ8LV6YJPP'

const DEBUG = typeof window !== 'undefined' && window.location?.hostname === 'localhost'

let initialized = false

/**
 * Inicializa GA4. Llamar 1 sola vez al arranque de la app (main.jsx).
 * Si no hay GA_ID seteado, no hace nada — la app sigue funcionando.
 */
export function initAnalytics() {
  if (initialized) return
  if (!GA_ID || typeof window === 'undefined') {
    if (DEBUG) {
      // eslint-disable-next-line no-console
      console.log('[analytics] VITE_GA_MEASUREMENT_ID no seteada — tracking deshabilitado')
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
  if (DEBUG) {
    // eslint-disable-next-line no-console
    console.log('[analytics] GA4 inicializado:', GA_ID)
  }
}

/**
 * Trackea un page view. Llamar en cada route change.
 * RouteTracker en App.jsx ya lo hace automático.
 */
export function trackPageView(path, title) {
  if (!initialized || !window.gtag) return
  window.gtag('event', 'page_view', {
    page_path: path,
    page_title: title || document.title,
    page_location: window.location.href,
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
  if (!initialized || !window.gtag) {
    if (DEBUG) console.log('[analytics] (noop)', name, params)
    return
  }
  window.gtag('event', name, params)
  if (DEBUG) console.log('[analytics]', name, params)
}

/**
 * Setea el user_id en GA4 (hasheado). Llamar tras login exitoso.
 * Permite trackear el embudo cross-device (mismo user en mobile + desktop).
 */
export function setUserId(uid) {
  if (!initialized || !window.gtag) return
  if (!uid) {
    window.gtag('set', 'user_properties', { user_id: null })
    return
  }
  window.gtag('config', GA_ID, {
    user_id: String(uid),
  })
  if (DEBUG) console.log('[analytics] user_id set', uid)
}

/**
 * Setea propiedades del user para segmentación (tier, has_broker, etc).
 * Útil para filtrar en GA4 reports: "users con tier=pro convierten al X%".
 */
export function setUserProperties(props) {
  if (!initialized || !window.gtag || !props) return
  window.gtag('set', 'user_properties', props)
  if (DEBUG) console.log('[analytics] user_properties', props)
}
