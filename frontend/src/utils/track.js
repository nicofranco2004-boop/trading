// track — wrapper unificado de event tracking.
// ═══════════════════════════════════════════════════════════════════════════
// Hoy: noop + console.debug. Mañana: pega a PostHog / Plausible / Mixpanel
// cambiando solo este archivo. Las páginas/componentes llaman `track(event,
// props)` sin saber del provider de abajo.
//
// Eventos canónicos del producto (lista cerrada — agregar acá si sumás más):
//   AUTH:
//     auth_signup
//     auth_login
//     auth_logout
//   ONBOARDING:
//     demo_mode_started
//     demo_mode_exited
//     import_started
//     import_format_detected   (props: { broker })
//     import_completed         (props: { broker, rows })
//     import_failed            (props: { stage, error })
//     first_insight_viewed
//   NAV:
//     route_change             (props: { from, to })
//   ACTIONS:
//     position_added
//     position_edited
//     position_deleted
//     watchlist_added          (props: { symbol })
//     watchlist_removed        (props: { symbol })
//     report_generated         (props: { period_key })
//     report_shared            (props: { period_key, channel })
//   PRO (a futuro):
//     paywall_viewed
//     trial_started
//     trial_to_paid
//     pro_subscribed
//     pro_canceled

const IS_DEV = typeof import.meta !== 'undefined' && import.meta?.env?.DEV

// Buffer de últimos eventos en memoria — útil para debug y para mandar
// en batch cuando lleguemos a integrar un provider real con queue.
const RECENT_EVENTS = []
const MAX_BUFFER = 100

export function track(event, props = {}) {
  const enriched = {
    event,
    props: { ...props, ts: new Date().toISOString() },
  }

  RECENT_EVENTS.push(enriched)
  if (RECENT_EVENTS.length > MAX_BUFFER) RECENT_EVENTS.shift()

  if (IS_DEV) {
    // En dev mostramos el event para debug.
    console.debug('[track]', event, props)
  }

  // ── Stub de provider real ──────────────────────────────────────────────────
  // Cuando integremos PostHog:
  //   if (window.posthog) window.posthog.capture(event, props)
  // Plausible:
  //   if (window.plausible) window.plausible(event, { props })
  // Mixpanel:
  //   if (window.mixpanel) window.mixpanel.track(event, props)
  if (typeof window !== 'undefined' && window.__rendi_track__) {
    try { window.__rendi_track__(event, props) } catch {}
  }
}

// Útil para hooks que necesitan trackear route changes
export function trackRoute(from, to) {
  track('route_change', { from, to })
}

// Para que QA / dev en consola pueda inspeccionar
if (typeof window !== 'undefined') {
  window.__rendi_recent_events__ = () => RECENT_EVENTS
}
