import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { useAuth } from './AuthContext'
import { api } from '../utils/api'
import { isDemoMode } from '../utils/demo'

/**
 * ModoRendimientoContext — la elección Certero / Estimado, UNA para toda la app.
 *
 * ⚠️ POR QUÉ VIVE ACÁ Y NO EN CADA PANTALLA. Métricas, Dashboard, Metas y
 * Reportes tenían cada una su `useState('certero')`. El usuario elegía Estimado
 * en Métricas, pasaba al Dashboard y veía Certero; volvía a Métricas y otra vez
 * Certero. Y el inicio del celular ni siquiera tenía toggle: medía siempre en
 * certero.
 *
 * ⚠️ Y POR QUÉ SE GUARDA EN LA CUENTA, NO SÓLO EN EL NAVEGADOR. La IA, los
 * informes y todo cálculo que el servidor hace sin que la pantalla le diga el
 * modo leen `users.modo_rendimiento` (`twr.modo_de` en el backend). Si la
 * elección quedara sólo en localStorage, la pantalla diría un número en
 * estimado y el chat otro en certero.
 *
 * El circuito:
 *   · al elegir → estado + localStorage (inmediato) + PUT a la cuenta.
 *   · al entrar (cada vez que cambia QUIÉN está logueado) → lo de localStorage
 *     para no parpadear, y enseguida GET a la cuenta, que manda: es la misma
 *     decisión tomada en otro dispositivo. No se lee del usuario cacheado en
 *     `rendi_user`: ese objeto puede ser de hace días, y el login lo arma sin
 *     pasar por /auth/me.
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

/**
 * Qué modo aplicar cuando llega lo guardado en la cuenta. Pura, para testear.
 *   · la cuenta tiene un modo → ése.
 *   · la cuenta no tiene (nunca eligió) → certero, y NO el local: en una compu
 *     compartida lo local puede ser la elección de OTRA persona, y subirlo se la
 *     guardaría a ésta.
 */
export function reconciliarModo(deLaCuenta) {
  return MODOS_RENDIMIENTO.includes(deLaCuenta) ? deLaCuenta : 'certero'
}

function subirALaCuenta(modo) {
  if (isDemoMode()) return
  api.put('/preferencias/modo-rendimiento', { modo }).catch(() => {})
}

const ModoRendimientoContext = createContext(null)

function useModoGuardado() {
  const [modo, setModoState] = useState(() => leerModoGuardado())
  const setModo = useCallback((v, { subir = true } = {}) => {
    if (!MODOS_RENDIMIENTO.includes(v)) return
    guardarModo(v)
    setModoState(v)
    if (subir) subirALaCuenta(v)
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
  const [modo, setModo] = useModoGuardado()
  const { user } = useAuth() || {}
  const quien = user && !isDemoMode() ? (user.email || user.name || null) : null
  // Cuántas veces eligió la persona: si toca el toggle mientras la cuenta
  // todavía no contestó, la respuesta (vieja) no pisa lo que acaba de elegir.
  const elecciones = useRef(0)
  const elegir = useCallback((v) => { elecciones.current++; setModo(v) }, [setModo])
  // Una vez por persona logueada: lo de la cuenta manda sobre lo local.
  useEffect(() => {
    if (!quien) return
    let vivo = true
    const antes = elecciones.current
    api.get('/preferencias/modo-rendimiento')
      .then(r => {
        if (vivo && elecciones.current === antes) setModo(reconciliarModo(r && r.modo), { subir: false })
      })
      .catch(() => {})                 // sin red: se sigue con lo local
    return () => { vivo = false }
  }, [quien, setModo])
  const valor = [modo, elegir]
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
