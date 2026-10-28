import { describe, it, expect, vi, beforeAll, beforeEach, afterAll } from 'vitest'
import { createElement as h, act } from 'react'
import { instalarNavegadorMinimo, montar } from '../../testing/navegadorMinimo'

// LA ISLA FLOTANTE SE PUEDE APAGAR (pedido de un usuario, 2026-10-25).
//
// El interruptor vive en la cabecera de /ai (RendiAI.jsx) y mueve
// `islaVisible` de VozContext. Acá se monta la isla REAL (RendiMate, con la
// sesión y el chat reales, igual que en islaConMouse.test.js) y se mira lo que
// importa:
//   · apagada, no se dibuja en ninguna pantalla, y la elección se recuerda;
//   · el ✦ Analizar de cualquier pantalla (VozContext → analizar) abre la isla
//     para mostrar la respuesta. Con la isla apagada esa respuesta caía en una
//     tarjeta que nadie ve: tiene que llevarte a /ai, donde está la misma
//     conversación.

vi.mock('../ai/MervallE', () => ({ default: () => null }))

let auth, voz, RendiMate, router, local
beforeAll(async () => {
  ;({ local } = instalarNavegadorMinimo())
  const api = await import('../../utils/api')
  vi.spyOn(api.api, 'get').mockImplementation(async () => [])
  vi.spyOn(api.api, 'post').mockImplementation(async () => ({}))
  auth = await import('../../contexts/AuthContext')
  voz = await import('../../contexts/VozContext')
  RendiMate = (await import('./RendiMate')).default
  router = await import('react-router-dom')
})
afterAll(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })
beforeEach(() => { local.delete('rendi:isla:on') })

function buscarPor(raiz, cumple) {
  const pila = [raiz]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeType === 1 && cumple(n)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

async function montarIsla() {
  const v = {}
  const Mirar = () => { v.voz = voz.useVoz(); v.ruta = router.useLocation().pathname; return null }
  const m = await montar(
    h(router.MemoryRouter, { initialEntries: ['/dashboard'] },
      h(auth.AuthProvider, null,
        h(voz.VozProvider, null, h(Mirar), h(RendiMate)))))
  const isla = () => buscarPor(m.contenedor, n => n.getAttribute?.('data-tour') === 'isla'
    || n.getAttribute?.('aria-label') === 'Mervall-E AI, tu acompañante')
  return { m, v, isla }
}

describe('la isla flotante prendida o apagada', () => {
  it('arranca prendida para quien nunca tocó el interruptor', async () => {
    const { m, v, isla } = await montarIsla()
    expect(v.voz.islaVisible).toBe(true)
    expect(isla()).not.toBeNull()
    await m.desmontar()
  })

  it('apagada no se dibuja, y la elección se recuerda', async () => {
    const { m, v, isla } = await montarIsla()
    await act(async () => v.voz.setIslaVisible(false))
    expect(isla()).toBeNull()
    expect(local.get('rendi:isla:on')).toBe('0')
    await m.desmontar()

    // Otra vez la app: sigue apagada.
    const otra = await montarIsla()
    expect(otra.v.voz.islaVisible).toBe(false)
    expect(otra.isla()).toBeNull()
    await otra.m.desmontar()
  })

  it('apagada, el ✦ Analizar te lleva al chat en vez de abrir una isla que no se ve', async () => {
    const { m, v, isla } = await montarIsla()
    await act(async () => v.voz.setIslaVisible(false))
    await act(async () => v.voz.analizar({ screen: 'position', params: { asset: 'AAPL' } }))
    expect(v.ruta).toBe('/ai')
    expect(v.voz.open).toBe(false)
    expect(isla()).toBeNull()
    await m.desmontar()
  })

  it('prendida, el ✦ Analizar sigue abriendo la isla donde estás', async () => {
    const { m, v, isla } = await montarIsla()
    await act(async () => v.voz.analizar({ screen: 'position', params: { asset: 'AAPL' } }))
    expect(v.ruta).toBe('/dashboard')
    expect(v.voz.open).toBe(true)
    expect(isla()).not.toBeNull()
    await m.desmontar()
  })
})
