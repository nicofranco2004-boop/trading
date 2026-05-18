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

// Eventos que se reenvían al backend para analytics de conversión Pro.
// Whitelist coincide con _ALLOWED_PLAN_EVENTS del backend — cambios acá
// requieren cambios allá.
const SERVER_TRACKED_EVENTS = new Set([
  'feature_blocked_clicked',
  'upgrade_modal_cta_clicked',
  'plan_hero_upgrade_clicked',
  'upgrade_promo_clicked',
])

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

  // Forward al backend SOLO los eventos del paywall (analytics de conversión).
  // Fire-and-forget — no esperamos respuesta para no bloquear UX. Falla
  // silenciosamente si no hay auth o el server no responde (es telemetría,
  // no acción crítica).
  if (SERVER_TRACKED_EVENTS.has(event)) {
    _forwardToBackend(event, props)
  }

  // ── Stub de provider real ──────────────────────────────────────────────────
  // Cuando integremos PostHog:
  //   if (window.posthog) window.posthog.capture(event, props)
  if (typeof window !== 'undefined' && window.__rendi_track__) {
    try { window.__rendi_track__(event, props) } catch {}
  }
}

async function _forwardToBackend(event, props) {
  // Lazy import para evitar dependencias circulares con utils/api.js
  try {
    const { api } = await import('./api.js')
    const { isDemoMode } = await import('./demo.js')
    if (isDemoMode()) return  // En demo no contamina la tabla real
    // Extraer keys reconocidas + dejar el resto como `props`
    const { feature, source, ...rest } = props || {}
    api.post('/plan/track', {
      event,
      feature_id: feature || null,
      source: source || null,
      props: rest,
    }).catch(() => {
      // No hacer nada — telemetría es best-effort
    })
  } catch {
    // dynamic import failed → silent
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
