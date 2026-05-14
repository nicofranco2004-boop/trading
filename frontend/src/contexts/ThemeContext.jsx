import { createContext, useContext, useState, useEffect } from 'react'

const ThemeContext = createContext()

// V2: light mode sigue bloqueado al cierre de Fase 4.
//
// El barrido masivo de tokens legacy (slate-*, bg-white) → V2 tokens cold
// (bg-bg-X, text-ink-X, border-line) durante Fases 1-4 eliminó la mayoría
// de las clases `dark:` que mantenían el contraste para light mode. Hoy
// los tokens V2 son intrínsecamente dark — no hay equivalente "light".
//
// Para des-bloquear light mode hace falta:
//   1. Definir paleta light en tailwind.config.js (CSS vars o variantes
//      explícitas tipo `bg-bg-1` → `dark:bg-bg-1 bg-white`).
//   2. Re-introducir `dark:` prefixes en componentes críticos donde
//      el cold neutral no leería bien sobre fondo claro.
//   3. Validar contraste WCAG AA para cada par bg/text.
//
// Mientras tanto: dark-only es la experiencia oficial.
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
