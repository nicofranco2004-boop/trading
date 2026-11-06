import { it, expect, vi, beforeAll, afterAll } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo } from '../testing/navegadorMinimo'

// De dónde llegó el navegador (utils/origen.js) y el «Cerrar sesión», con la
// sesión de VERDAD (AuthProvider real; lo único simulado es el servidor).
//
// Encontrado en la auditoría del 06/11/2026: quien llegaba por un anuncio,
// probaba el demo y salía con «Cerrar sesión» (Sidebar y Más lo muestran en el
// demo) perdía el origen antes de registrarse, porque el cierre borra todo lo
// `rendi_*` guardado. En el demo no hay cuenta: el origen es del visitante y se
// queda. Al cerrar una cuenta de verdad sí se borra: el que entra después en esa
// máquina no llegó por ahí.

let api, auth, origen
beforeAll(async () => {
  instalarNavegadorMinimo()
  const href = 'https://rendi.finance/?demo=1&fbclid=IwAR0xYz'
  const u = new URL(href)
  window.location = { href, pathname: u.pathname, search: u.search, hash: u.hash, hostname: u.hostname, origin: u.origin, reload: vi.fn() }
  window.history = {
    state: null,
    replaceState(st, _t, url) {
      const n = new URL(url, window.location.href)
      Object.assign(window.location, { href: n.href, pathname: n.pathname, search: n.search, hash: n.hash })
    },
  }
  document.referrer = 'https://l.instagram.com/'
  origen = await import('../utils/origen')
  api = await import('../utils/api')
  auth = await import('./AuthContext')
})
afterAll(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('llega desde Instagram, prueba el demo, «Cerrar sesión»: el origen sigue para el registro', async () => {
  origen.anotarOrigen() // lo que hace main.jsx antes de montar
  expect(origen.origenParaElRegistro()?.origen).toBe('sitio/l.instagram.com/fbclid')

  let enElServidor = null
  vi.spyOn(api.api, 'get').mockImplementation(async (path) => {
    if (path === '/auth/me' && enElServidor) return enElServidor
    throw Object.assign(new Error('Unauthorized'), { status: 401 })
  })
  vi.spyOn(api.api, 'post').mockImplementation(async () => ({}))
  const v = {}
  const Mirar = () => { v.auth = auth.useAuth(); return null }
  await montar(h(auth.AuthProvider, null, h(Mirar)))
  expect(v.auth.user?.demo).toBe(true)

  await enActo(() => v.auth.logout()) // el «Cerrar sesión» de Sidebar o de Más
  expect(v.auth.user).toBe(null)
  expect(origen.origenParaElRegistro()?.origen).toBe('sitio/l.instagram.com/fbclid')

  // Una cuenta de verdad que cierra sesión, en cambio, se lo lleva.
  enElServidor = { id: 5, email: 'ana@prueba.test', name: 'Ana', tier: 'pro' }
  await enActo(() => v.auth.entrar())
  expect(v.auth.user?.email).toBe('ana@prueba.test')
  await enActo(() => v.auth.logout())
  expect(origen.origenParaElRegistro()).toBe(null)
})
