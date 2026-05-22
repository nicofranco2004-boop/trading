import { createContext, useContext, useEffect, useState } from 'react'
import { api } from '../utils/api'
import { isDemoMode, enableDemoMode, disableDemoMode } from '../utils/demo'
import { track } from '../utils/track'
import { refreshPlanFeatures } from '../hooks/usePlanFeatures'

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
        const fresh = {
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
        localStorage.setItem('rendi_user', JSON.stringify(fresh))
        setUser(fresh)
        refreshPlanFeatures()
      })
      .catch(() => {
        // 401 / network → no hay sesión válida. Limpiar y ofrecer login.
        localStorage.removeItem('rendi_user')
        setUser(null)
        refreshPlanFeatures()
      })
      .finally(() => setBootstrapped(true))
  }, [])

  // El primer arg (`_legacyToken`) se ignora — la cookie ya fue seteada por
  // el backend en la respuesta de login/register/verify/reset. Lo dejamos
  // en la firma para no tener que tocar todos los call-sites.
  function login(_legacyToken, name, extra = {}) {
    const u = { name, ...extra }
    localStorage.setItem('rendi_user', JSON.stringify(u))
    setUser(u)
    // Identity change → forzar refetch del plan features.
    refreshPlanFeatures()
  }

  function updateUser(patch) {
    setUser(prev => {
      const next = { ...(prev || {}), ...patch }
      localStorage.setItem('rendi_user', JSON.stringify(next))
      return next
    })
  }

  function logout() {
    if (user?.demo) {
      track('demo_mode_exited')
      disableDemoMode()
    } else {
      // Server-side: borra la cookie HttpOnly. Si falla (network), igual
      // limpiamos el estado local; la cookie expira en 7d como fallback.
      api.post('/auth/logout').catch(() => {})
    }
    localStorage.removeItem('rendi_user')
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
    <AuthContext.Provider value={{ user, isDemo, login, logout, exitDemo, updateUser, bootstrapped }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
