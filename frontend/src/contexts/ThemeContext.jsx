import { createContext, useContext, useState, useEffect } from 'react'

const ThemeContext = createContext()

// El modo claro está ABIERTO desde 2026-09-16.
//
// ── Por qué estuvo trabado, y qué lo destrabó ─────────────────────────────
// Los tokens V2 eran hex fijos: `bg-bg-1` valía #0E1218 y no había forma de
// que valiera otra cosa. El modo claro no era difícil, era IMPOSIBLE — y los
// dos intentos anteriores se vieron mal por eso, no por el diseño. Sobre fondo
// blanco, el borde de las tarjetas pasaba de contrastar 1,18:1 a 15,93:1 y el
// texto principal de 15,57 a 1,21.
//
// Cuatro tandas lo abrieron: los 33 colores pasaron a variables (F0), se
// enterraron las dos mitades del sistema anterior que convivían (F1), los
// gráficos dejaron de tener cada uno su copia de la escala (F2) y la
// superficie que flota dejó de compartir color con el hover (F3).
// El criterio de qué NO se toca: src/__design__/CRITERIO-modo-claro.md
//
// ── ESTA CONSTANTE Y EL SCRIPT DE index.html SE MUEVEN JUNTOS ─────────────
// Se deja puesta, en `false`, y no se borra: es el interruptor para volver
// atrás sin revertir cuatro tandas de trabajo. Si algún día hay que apagarlo,
// se pone en `true` EN LOS DOS LADOS. Con uno solo: o la app parpadea
// claro→oscuro en cada carga, o las cuentas con `rendi_theme` guardado
// arrancan del color equivocado.
const LIGHT_MODE_LOCKED = false

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
