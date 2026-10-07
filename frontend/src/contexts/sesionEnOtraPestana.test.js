import { describe, it, expect, vi, beforeAll, beforeEach, afterEach, afterAll } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, otraPestanaEscribe, montar } from '../testing/navegadorMinimo'

// 🔴 OTRA PESTAÑA CAMBIÓ QUIÉN ESTÁ LOGUEADO (2026-10-05).
//
// La sesión es una cookie, una sola para todas las pestañas. En una compu
// compartida: la persona A tiene dos pestañas; en una cierra sesión y entra B.
// La otra pestaña seguía creyendo que era A —su conversación con la IA, su
// foto de la cartera— y lo mandaba con la sesión de B. Ahora, si en otra
// pestaña cambia la persona, ésta se recarga y arranca con la de verdad.
//
// AuthProvider montado de verdad (ver testing/navegadorMinimo.js); lo único
// simulado es el servidor.

let api, auth, local
beforeAll(async () => {
  ;({ local } = instalarNavegadorMinimo())
  api = await import('../utils/api')
  auth = await import('./AuthContext')
})
afterAll(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

const A = { email: 'a@prueba.test', name: 'A', tier: 'pro' }
const B = { email: 'b@prueba.test', name: 'B', tier: 'pro' }

let montado
// Lo que la pantalla cree que es la sesión (el `user` de React).
const visto = { user: undefined }
const Mirar = () => { visto.user = auth.useAuth().user; return null }
async function montarSesionDe(persona, { meContesta } = {}) {
  local.set('rendi_user', JSON.stringify(persona))
  vi.spyOn(api.api, 'get').mockImplementation(async (path) => {
    if (path !== '/auth/me') return {}
    if (meContesta) return meContesta()
    return persona
  })
  montado = await montar(h(auth.AuthProvider, null, h(Mirar)))
}
// La pestaña mira un instante después del aviso (los cambios en dos pasos):
// se adelanta el reloj en vez de esperar de verdad.
const pasaUnInstante = () => vi.advanceTimersByTime(400)
beforeEach(() => {
  vi.restoreAllMocks()
  local.clear()
  window.location.reload.mockClear()
})
afterEach(async () => {
  vi.useRealTimers()
  if (montado) await montado.desmontar()
  montado = null
})
const conRelojFalso = () => vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })

describe('si en otra pestaña cambia la persona, ésta se recarga', () => {
  it('otra pestaña entró con otra cuenta', async () => {
    await montarSesionDe(A)
    conRelojFalso()
    otraPestanaEscribe('rendi_user', JSON.stringify(B))
    pasaUnInstante()
    expect(window.location.reload).toHaveBeenCalledTimes(1)
  })

  it('otra pestaña cerró la sesión', async () => {
    await montarSesionDe(A)
    conRelojFalso()
    otraPestanaEscribe('rendi_user', null)
    pasaUnInstante()
    expect(window.location.reload).toHaveBeenCalledTimes(1)
  })

  it('otra pestaña vació todo y volvió a poner la misma sesión (el "limpiar" del cartel de error): no', async () => {
    await montarSesionDe(A)
    conRelojFalso()
    // ErrorBoundary vacía el localStorage y vuelve a poner la sesión: en el
    // navegador llegan DOS avisos, y en el medio parece que no hay nadie.
    otraPestanaEscribe(null, null)
    otraPestanaEscribe('rendi_user', JSON.stringify(A))
    pasaUnInstante()
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('la MISMA persona actualizó sus datos en otra pestaña (por ejemplo, el plan): no', async () => {
    await montarSesionDe(A)
    conRelojFalso()
    otraPestanaEscribe('rendi_user', JSON.stringify({ ...A, email: 'A@Prueba.test', tier: 'advisor' }))
    pasaUnInstante()
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('otra clave cualquiera: no', async () => {
    await montarSesionDe(A)
    conRelojFalso()
    otraPestanaEscribe('rendi_theme', 'dark')
    pasaUnInstante()
    expect(window.location.reload).not.toHaveBeenCalled()
  })
})

describe('al abrir la app, sólo un 401 cierra la sesión', () => {
  // Antes cualquier falla de /auth/me (un corte de red, un deploy) borraba la
  // sesión guardada: la pestaña quedaba en el login con la cookie válida, y
  // con el aviso entre pestañas además recargaba todas las de la misma persona.
  it('un corte de red no la borra', async () => {
    await montarSesionDe(A, { meContesta: () => { throw new TypeError('Failed to fetch') } })
    expect(JSON.parse(localStorage.getItem('rendi_user'))?.email).toBe(A.email)
    expect(visto.user?.email).toBe(A.email)
  })

  it('un error del servidor tampoco', async () => {
    await montarSesionDe(A, { meContesta: () => { throw Object.assign(new Error('HTTP 503'), { status: 503 }) } })
    expect(JSON.parse(localStorage.getItem('rendi_user'))?.email).toBe(A.email)
    expect(visto.user?.email).toBe(A.email)
  })

  it('un 401 sí: la sesión venció', async () => {
    await montarSesionDe(A, { meContesta: () => { throw Object.assign(new Error('Unauthorized'), { status: 401 }) } })
    expect(localStorage.getItem('rendi_user')).toBe(null)
    expect(visto.user).toBe(null)
  })
})
