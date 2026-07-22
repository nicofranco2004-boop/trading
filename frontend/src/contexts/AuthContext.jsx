import { createContext, useContext, useEffect, useState } from 'react'
import { api, clearClientContext } from '../utils/api'
import { isDemoMode, enableDemoMode, disableDemoMode } from '../utils/demo'
import { track } from '../utils/track'
import { refreshPlanFeatures } from '../hooks/usePlanFeatures'
import { setUserId, setUserProperties, trackEvent } from '../utils/analytics'
import { trackMetaEvent } from '../utils/metaPixel'

const AuthContext = createContext(null)

// User fake para modo demo. No tiene token real — todas las llamadas API
// son interceptadas por handleDemoRequest en api.js.
const DEMO_USER = {
  name: 'Inversor Demo',
  email: 'demo@rendi.finance',
  is_admin: false,
  tier: 'pro',  // Demo siempre simula Pro para mostrar todas las features
  // En demo simulamos una sub authorized — Config muestra "Activo" + opción
  // de cancelar (que no haría nada real porque las llamadas a la API
  // están interceptadas en api.js).
  access_mode: 'authorized',
  subscription_status: 'authorized',
  subscription_period: 'monthly',
  demo: true,
  id: 0,
  created_at: '2024-04-01T00:00:00Z',
}

// Mapea la respuesta de /auth/me al shape de `user` que consume la app.
// Centralizado para que el bootstrap inicial Y refreshUser() produzcan
// EXACTAMENTE el mismo objeto — antes el mapeo vivía inline solo en el
// bootstrap, así que cualquier refresh mid-sesión tenía que duplicarlo (o
// no existía, que era el bug: el tier quedaba stale tras un pago).
function mapMeToUser(me) {
  return {
    name: me.name || me.email,
    email: me.email,
    is_admin: !!me.is_admin,
    tier: me.tier || 'free',
    // Estado de la suscripción Rebill — usado por Config/Planes para
    // distinguir authorized (mostrar "Cancelar") de cancelled
    // (mostrar "Reactivar" + permitir re-suscribirse).
    subscription_status: me.subscription_status || null,
    subscription_period_end: me.subscription_period_end || null,
    subscription_cancelled_at: me.subscription_cancelled_at || null,
    subscription_period: me.subscription_period || null,
    // Crédito (modelo Rendi-managed proration). Si credit_active_until
    // > NOW el user tiene acceso al tier sin necesidad de tener una
    // sub Rebill autorizada — viene de un upgrade/downgrade mid-período.
    credit_active_until:   me.credit_active_until || null,
    credit_days_remaining: me.credit_days_remaining ?? 0,
    credit_remaining_usd:  me.credit_remaining_usd ?? 0,
    credit_anchor_plan:    me.credit_anchor_plan || null,
    credit_anchor_period:  me.credit_anchor_period || null,
    // access_mode: single source of truth para el estado del acceso.
    // Valores: 'authorized' (sub Rebill renovable) | 'credit_only'
    // (cambió plan, vive del crédito) | 'cancelled' (canceló manual,
    // grace period) | 'free'.
    access_mode:           me.access_mode || 'free',
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    // Activación de demo via query param. Soporta `?demo=1` y `?demo=true`.
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search)
      const demoParam = params.get('demo')
      if (demoParam === '1' || demoParam === 'true') {
        enableDemoMode()
        track('demo_mode_started')
        // Limpiamos la URL para no dejar el param visible (UX más limpia)
        try {
          const cleanUrl = window.location.pathname + window.location.hash
          window.history.replaceState({}, '', cleanUrl)
        } catch {}
      }
      if (isDemoMode()) return DEMO_USER
    }
    // Hidratación optimista: usamos lo que dejamos en localStorage la última
    // vez (solo metadata: nombre, email, tier — sin token). En paralelo
    // /auth/me valida la cookie y refresca los valores.
    try { return JSON.parse(localStorage.getItem('rendi_user')) } catch { return null }
  })
  const [bootstrapped, setBootstrapped] = useState(false)

  // Rehidratación: si la cookie HttpOnly es válida, /auth/me devuelve el user.
  // No hay token visible para JS — confiamos en la cookie. En demo skipeamos.
  useEffect(() => {
    if (isDemoMode()) { setBootstrapped(true); return }
    api.get('/auth/me')
      .then(me => {
        const fresh = mapMeToUser(me)
        localStorage.setItem('rendi_user', JSON.stringify(fresh))
        setUser(fresh)
        refreshPlanFeatures()
        // Analytics: identificar al user y setear propiedades para segmentación
        // en GA4 (tier, access_mode). user_id permite trackear cross-device.
        if (me.id) setUserId(me.id)
        setUserProperties({
          tier: fresh.tier,
          access_mode: fresh.access_mode,
        })
      })
      .catch(() => {
        // 401 / network → no hay sesión válida. Limpiar y ofrecer login.
        localStorage.removeItem('rendi_user')
        setUser(null)
        refreshPlanFeatures()
        setUserId(null)
      })
      .finally(() => setBootstrapped(true))
  }, [])

  // Keep-alive: pinga /api/health cada 4 min para que Railway no duerma el servicio.
  // Se activa solo cuando hay un usuario logueado (no en demo ni sin sesión).
  useEffect(() => {
    if (!user || isDemoMode()) return
    const id = setInterval(() => { fetch('/api/health').catch(() => {}) }, 4 * 60 * 1000)
    return () => clearInterval(id)
  }, [user])

  // El primer arg (`_legacyToken`) se ignora — la cookie ya fue seteada por
  // el backend en la respuesta de login/register/verify/reset. Lo dejamos
  // en la firma para no tener que tocar todos los call-sites.
  function login(_legacyToken, name, extra = {}) {
    // Plan Asesor: si quedó un contexto de cliente colgado (logout sin
    // "Volver" en la misma pestaña SPA), el header stale rompería TODOS los
    // requests del user nuevo con 403. Identity change = contexto afuera.
    clearClientContext()
    const u = { name, ...extra }
    localStorage.setItem('rendi_user', JSON.stringify(u))
    setUser(u)
    // Identity change → forzar refetch del plan features.
    refreshPlanFeatures()
    // Analytics: trackear login. Si extra trae `event_type='sign_up'`, mandamos
    // sign_up también (callsite del flujo verify-email).
    if (extra?.event_type === 'sign_up') {
      trackEvent('sign_up', { method: 'email' })
      // Meta Pixel: evento de conversión de registro. Es el que optimizan las
      // campañas de Meta Ads y con el que medimos el costo por signup.
      trackMetaEvent('CompleteRegistration', { content_name: 'signup', status: true })
    } else {
      trackEvent('login', { method: 'email' })
    }
    if (extra?.id) setUserId(extra.id)
  }

  function updateUser(patch) {
    setUser(prev => {
      const next = { ...(prev || {}), ...patch }
      localStorage.setItem('rendi_user', JSON.stringify(next))
      return next
    })
  }

  // Re-fetcha /auth/me y actualiza el `user` canónico + el cache de plan
  // features. Llamar cuando el tier puede haber cambiado DENTRO de la misma
  // sesión sin un reload completo — el caso crítico es el retorno de un pago
  // Rebill: BillingReturn navega por SPA (no hard reload), así que el
  // AuthProvider no se re-monta y `/auth/me` no se vuelve a llamar solo. Sin
  // esto, el navbar y el banner de Config seguían mostrando el tier viejo
  // (free) aunque la cuenta ya estuviera activada en plus/pro.
  //
  // Propaga el error (ej. 401 si la sesión venció) para que el caller decida
  // qué hacer; no toca el estado local en ese caso.
  async function refreshUser() {
    const me = await api.get('/auth/me')
    const fresh = mapMeToUser(me)
    localStorage.setItem('rendi_user', JSON.stringify(fresh))
    setUser(fresh)
    refreshPlanFeatures()
    return fresh
  }

  function logout() {
    trackEvent('logout')
    setUserId(null)
    // Plan Asesor: el loop rendi_* de abajo borra la KEY rendi_client_ctx,
    // pero la variable módulo-level de api.js seguiría inyectando el header
    // el resto de la sesión SPA — limpiar el mirror en memoria también.
    clearClientContext()
    if (user?.demo) {
      track('demo_mode_exited')
      disableDemoMode()
    } else {
      // Server-side: borra la cookie HttpOnly. Si falla (network), igual
      // limpiamos el estado local; la cookie expira en 7d como fallback.
      api.post('/auth/logout').catch(() => {})
    }
    // SECURITY: limpiar TODOS los flags rendi_ del localStorage para evitar
    // cross-user state leak en máquinas compartidas. Antes solo borrábamos
    // rendi_user, quedaban: rendi_first_import_done, rendi_ai_discovered,
    // rendi_dashboard_currency, rendi_sidebar_collapsed, rendi_demo_overlay,
    // rendi_demo_mode, rendi_theme, etc. User B veía preferencias de user A.
    //
    // PRESERVE list — flags que NO se borran al logout:
    //   • rendi_theme: preferencia de máquina, no de cuenta.
    //   • rendi_ai_discovered: "el user de este browser ya descubrió la feature
    //     Coach IA". Si lo borramos, cada logout+login del MISMO user resetea
    //     el checklist y muestra "Coach IA pendiente" como si nunca lo hubiera
    //     usado. Trade-off aceptado: en máquina compartida user B ve ✓ Coach
    //     IA sin haberlo usado — minor leak (no es PII, solo discovery state)
    //     vs UX bug recurrente. Si en el futuro tracking server-side, mover
    //     este flag al endpoint /api/plan/features o similar.
    try {
      const preserve = new Set(['rendi_theme', 'rendi_ai_discovered'])
      const keysToRemove = []
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i)
        if (key && key.startsWith('rendi_') && !preserve.has(key)) {
          keysToRemove.push(key)
        }
      }
      keysToRemove.forEach((k) => localStorage.removeItem(k))
    } catch {
      // localStorage puede no estar disponible (private mode iOS antiguo) — best effort
      localStorage.removeItem('rendi_user')
    }
    setUser(null)
    refreshPlanFeatures()  // limpiamos cache para el próximo login
  }

  function exitDemo() {
    track('demo_mode_exited')
    disableDemoMode()
    setUser(null)
  }

  const isDemo = !!user?.demo

  return (
    <AuthContext.Provider value={{ user, isDemo, login, logout, exitDemo, updateUser, refreshUser, bootstrapped }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
