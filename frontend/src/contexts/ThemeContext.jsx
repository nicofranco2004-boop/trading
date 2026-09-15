import { createContext, useContext, useState, useEffect } from 'react'

const ThemeContext = createContext()

// El modo claro sigue trabado, pero ya no por falta de paleta.
//
// ── Lo que había antes (y ya no) ──────────────────────────────────────────
// Los tokens V2 eran hex fijos: `bg-bg-1` valía #0E1218 y no había forma de
// que valiera otra cosa. Eso hacía el modo claro literalmente imposible, no
// difícil. F0 (2026-09-15) los pasó a variables CSS con un set claro y uno
// oscuro — la paleta existe, está medida contra WCAG AA y vive en
// src/index.css. Los ~8.900 usos del código ya responden al tema solos.
//
// ── Lo que falta para destrabar ───────────────────────────────────────────
//   F1 · Enterrar el modo claro viejo: 92 `bg-white` y 482 `dark:` sueltos
//        del sistema anterior, que hoy producen blanco sobre blanco.
//   F2 · Los gráficos: ~360 colores escritos a mano adentro de cada gráfico,
//        que no miran el tema. Las rampas de heatmap hay que recorrerlas al
//        revés, no cambiarles los valores.
//   F3 · Elevación: bg-2 hace dos trabajos (elevar y hover) que en claro
//        tiran para lados opuestos, y las sombras están apagadas.
//
// ── Cuando se destrabe ────────────────────────────────────────────────────
// ESTA CONSTANTE Y EL SCRIPT DE index.html SE CAMBIAN JUNTOS. Si se saca
// acá y no allá, la app parpadea claro→oscuro en cada carga; si se saca
// allá y no acá, las cuentas con `rendi_theme=light` guardado de la época
// vieja arrancan claras y saltan a oscuras.
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
      // Con el lock puesto esto vale siempre true (el useState de arriba lo
      // fuerza). Se expone el estado y no un `true` literal para que, el día
      // que se destrabe, no quede un componente leyendo una constante muerta.
      dark,
      toggle: () => {
        if (!LIGHT_MODE_LOCKED) setDark(d => !d)
      },
    }}>
      {children}
    </ThemeContext.Provider>
  )
}

export const useTheme = () => useContext(ThemeContext)
