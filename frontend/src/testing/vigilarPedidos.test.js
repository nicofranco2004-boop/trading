// El vigía de pedidos (testing/vigilarPedidos.js) tiene que ver lo que salió
// por fuera de la puerta, ponga la prueba el `fetch` que ponga.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { pedidosPorFueraDeLaPuerta } from './vigilarPedidos'

const responde = () => vi.fn(async () => new Response('{}', { status: 200 }))
afterEach(() => { vi.unstubAllGlobals() })

describe('el vigía de pedidos a /api', () => {
  it('ve el fetch suelto de /acceso (re-test a ciegas 9) aunque la prueba ponga su fetch con vi.stubGlobal', async () => {
    const suyo = responde()
    vi.stubGlobal('fetch', suyo)
    await fetch('/api/auth/link-request/preview?token=x', { credentials: 'include' })
    expect(pedidosPorFueraDeLaPuerta()).toEqual(['GET /api/auth/link-request/preview'])
    expect(suyo).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledTimes(1)       // el `expect(fetch)` de la prueba sigue andando
  })

  it('y con globalThis.fetch = …', async () => {
    const antes = globalThis.fetch
    globalThis.fetch = responde()
    await fetch('/api/uso/eventos', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
    expect(pedidosPorFueraDeLaPuerta()).toEqual(['POST /api/uso/eventos'])
    expect(globalThis.fetch.mock.calls).toHaveLength(1)
    globalThis.fetch = antes
  })

  it('lo que sale por la puerta pasa; lo que no es nuestro servidor no cuenta', async () => {
    vi.stubGlobal('fetch', responde())
    const { pedirAlServidor } = await import('../utils/api')
    await pedirAlServidor('/plan/features', {}, { freno: false })
    await pedirAlServidor('/auth/login', { method: 'POST' }, { freno: false })
    await fetch('/version.json')
    await fetch('https://otro.sitio/api/x')
    expect(pedidosPorFueraDeLaPuerta()).toEqual([])
  })

  it('la puerta dice la persona de la pestaña cuando la sabe, y la marca siempre', async () => {
    const suyo = responde()
    vi.stubGlobal('fetch', suyo)
    const api = await import('../utils/api')
    api.fijarPersonaDeLaPestana('Ana@R9.test')
    await api.pedirAlServidor('/positions', {}, { freno: false })
    api.fijarPersonaDeLaPestana(null)
    await api.pedirAlServidor('/stats/public', {}, { freno: false })
    const [conPersona, sinPersona] = suyo.mock.calls.map(([, init]) => init)
    expect(conPersona.headers[api.PERSONA_HEADER]).toBe('ana%40r9.test')
    expect(conPersona.headers[api.VERSION_HEADER]).toBeTruthy()
    expect(conPersona.credentials).toBe('include')
    expect(sinPersona.headers[api.PERSONA_HEADER]).toBeUndefined()
    expect(sinPersona.headers[api.VERSION_HEADER]).toBeTruthy()
  })
})
