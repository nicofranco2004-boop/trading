import { createContext, useContext, useState } from 'react'

const PrivacyContext = createContext({ hidden: false, toggle: () => {} })

const STORAGE_KEY = 'rendi_privacy'

export function PrivacyProvider({ children }) {
  const [hidden, setHidden] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === '1' } catch { return false }
  })
  function toggle() {
    setHidden(h => {
      const next = !h
      try { localStorage.setItem(STORAGE_KEY, next ? '1' : '0') } catch {}
      return next
    })
  }
  return (
    <PrivacyContext.Provider value={{ hidden, toggle }}>
      {children}
    </PrivacyContext.Provider>
  )
}

export function usePrivacy() {
  return useContext(PrivacyContext)
}

// Wrapper para valores JSX (ej. <AnimatedNumber>) que deben ocultarse.
// Para strings simples usá: {hidden ? '••••••' : value}
export function PrivacyMask({ children }) {
  const { hidden } = useContext(PrivacyContext)
  if (hidden) return <span className="opacity-40 tracking-[0.2em] select-none" aria-label="valor oculto">••••••</span>
  return <>{children}</>
}
