import { createContext, useContext, useState } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem('rendi_user')) } catch { return null }
  })

  function login(token, name) {
    localStorage.setItem('rendi_token', token)
    localStorage.setItem('rendi_user', JSON.stringify({ name }))
    setUser({ name })
  }

  function logout() {
    localStorage.removeItem('rendi_token')
    localStorage.removeItem('rendi_user')
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
