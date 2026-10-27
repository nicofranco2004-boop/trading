import { createContext, useCallback, useContext, useEffect, useState } from 'react'

/**
 * ModoRendimientoContext — la elección Certero / Estimado, UNA para toda la app.
 *
 * ⚠️ POR QUÉ VIVE ACÁ Y NO EN CADA PANTALLA. Métricas, Dashboard, Metas y
 * Reportes tenían cada una su `useState('certero')`. El usuario elegía Estimado
 * en Métricas, pasaba al Dashboard y veía Certero; volvía a Métricas y otra vez
 * Certero. Cuatro pantallas mostrando el rendimiento con dos reglas distintas al
 * mismo tiempo, y la decisión del usuario olvidada en cada navegación.
 *
 * Ahora la elección se guarda (como la moneda y el tema: preferencia del
 * dispositivo, en localStorage) y la leen todas. Dura hasta que el usuario la
 * cambie, desde cualquiera de los toggles.
 */
export const MODOS_RENDIMIENTO = ['certero', 'estimado']
const STORAGE_KEY = 'rendi_modo_rendimiento'

export function leerModoGuardado(storage = globalThis.localStorage) {
  try {
    const v = storage.getItem(STORAGE_KEY)
    return MODOS_RENDIMIENTO.includes(v) ? v : 'certero'
  } catch { return 'certero' }
}

export function guardarModo(v, storage = globalThis.localStorage) {
  try { storage.setItem(STORAGE_KEY, v) } catch {}
}

const ModoRendimientoContext = createContext(null)

function useModoGuardado() {
  const [modo, setModoState] = useState(() => leerModoGuardado())
  const setModo = useCallback((v) => {
    if (!MODOS_RENDIMIENTO.includes(v)) return
    guardarModo(v)
    setModoState(v)
  }, [])
  // Otra pestaña cambió el modo: ésta lo sigue, para no tener dos reglas abiertas.
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === STORAGE_KEY && MODOS_RENDIMIENTO.includes(e.newValue)) setModoState(e.newValue)
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])
  return [modo, setModo]
}

export function ModoRendimientoProvider({ children }) {
  const valor = useModoGuardado()
  return (
    <ModoRendimientoContext.Provider value={valor}>
      {children}
    </ModoRendimientoContext.Provider>
  )
}

/**
 * `const [modo, setModo] = useModoRendimiento()` — mismo contrato que useState.
 * Fuera del provider (tests que montan una página suelta) funciona igual, con
 * su propio estado guardado.
 */
export function useModoRendimiento() {
  const ctx = useContext(ModoRendimientoContext)
  const propio = useModoGuardado()
  return ctx || propio
}
