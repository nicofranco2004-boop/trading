import { createContext, useContext, useState, useEffect } from 'react'

const ThemeContext = createContext()

// V2: light mode está postergado hasta Fase 4. El toggle queda funcional en
// el código pero forzamos `dark` siempre. Cuando volvamos a habilitar light,
// solo hay que sacar el override de abajo.
const LIGHT_MODE_LOCKED = true

export function ThemeProvider({ children }) {
  const [dark, setDark] = useState(() => {
    if (LIGHT_MODE_LOCKED) return true
    return localStorage.getItem('rendi_theme') !== 'light'
  })

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    if (!LIGHT_MODE_LOCKED) {
      localStorage.setItem('rendi_theme', dark ? 'dark' : 'light')
    }
  }, [dark])

  return (
    <ThemeContext.Provider value={{
      dark: true,  // V2: siempre dark hasta Fase 4
      toggle: () => {
        if (!LIGHT_MODE_LOCKED) setDark(d => !d)
      },
    }}>
      {children}
    </ThemeContext.Provider>
  )
}

export const useTheme = () => useContext(ThemeContext)
