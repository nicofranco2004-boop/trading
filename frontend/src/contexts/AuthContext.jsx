import { createContext, useContext, useEffect, useState } from 'react'
import { api } from '../utils/api'
import { isDemoMode, enableDemoMode, disableDemoMode } from '../utils/demo'
import { track } from '../utils/track'

const AuthContext = createContext(null)

// User fake para modo demo. No tiene token real — todas las llamadas API
// son interceptadas por handleDemoRequest en api.js.
const DEMO_USER = {
  name: 'Inversor Demo',
  email: 'demo@rendi.app',
  is_admin: false,
  tier: 'pro',  // Demo siempre simula Pro para mostrar todas las features
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
    try { return JSON.parse(localStorage.getItem('rendi_user')) } catch { return null }
  })
  const [bootstrapped, setBootstrapped] = useState(false)

  // Rehidratación: si hay token, validarlo y traer datos frescos del server.
  // En modo demo skipeamos la rehidratación (no hay token real).
  useEffect(() => {
    if (isDemoMode()) { setBootstrapped(true); return }
    const token = localStorage.getItem('rendi_token')
    if (!token) { setBootstrapped(true); return }
    api.get('/auth/me')
      .then(me => {
        const fresh = {
          name: me.name || me.email,
          email: me.email,
          is_admin: !!me.is_admin,
          tier: me.tier || 'free',
        }
        localStorage.setItem('rendi_user', JSON.stringify(fresh))
        setUser(fresh)
      })
      .catch(() => {
        localStorage.removeItem('rendi_token')
        localStorage.removeItem('rendi_user')
        setUser(null)
      })
      .finally(() => setBootstrapped(true))
  }, [])

  function login(token, name, extra = {}) {
    localStorage.setItem('rendi_token', token)
    const u = { name, ...extra }
    localStorage.setItem('rendi_user', JSON.stringify(u))
    setUser(u)
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
    }
    localStorage.removeItem('rendi_token')
    localStorage.removeItem('rendi_user')
    setUser(null)
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
