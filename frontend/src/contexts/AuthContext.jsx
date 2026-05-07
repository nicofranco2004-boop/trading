import { createContext, useContext, useEffect, useState } from 'react'
import { api } from '../utils/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('rendi_user')) } catch { return null }
  })
  const [bootstrapped, setBootstrapped] = useState(false)

  // Rehidratación: si hay token, validarlo y traer datos frescos del server.
  // Esto cubre: localStorage corrupto, name desactualizado, is_admin no presente, token expirado.
  useEffect(() => {
    const token = localStorage.getItem('rendi_token')
    if (!token) { setBootstrapped(true); return }
    api.get('/auth/me')
      .then(me => {
        const fresh = { name: me.name || me.email, email: me.email, is_admin: !!me.is_admin }
        localStorage.setItem('rendi_user', JSON.stringify(fresh))
        setUser(fresh)
      })
      .catch(() => {
        // Token inválido/expirado: limpiar (api.js ya redirige al login)
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
    localStorage.removeItem('rendi_token')
    localStorage.removeItem('rendi_user')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, login, logout, updateUser, bootstrapped }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
