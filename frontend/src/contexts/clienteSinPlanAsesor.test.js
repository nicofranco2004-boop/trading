import { describe, it, expect, vi, beforeAll, beforeEach, afterEach, afterAll } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar } from '../testing/navegadorMinimo'

// 🔴 SIN EL PLAN ASESOR, LA APP NO ABRE ADENTRO DE UN CLIENTE (10/11/2026).
//
// El servidor dejó de servir la cuenta de un cliente a quien no tiene el plan
// (backend/tests/test_asesor_sin_plan.py). Pero la pestaña recuerda el último
// cliente aunque se cierre el navegador: a quien se le venció o se le quitó el
// plan, la app le abría en ese cliente y cada pedido volvía con 403. Ahora, si
// /auth/me dice que quien mira ya no es asesor, se suelta el cliente y se
// recarga una vez.
//
// AuthProvider montado de verdad (testing/navegadorMinimo.js); lo único
// simulado es el servidor.

let api, auth, local
beforeAll(async () => {
  ;({ local } = instalarNavegadorMinimo())
  api = await import('../utils/api')
  auth = await import('./AuthContext')
})
afterAll(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

const ASESORA = { email: 'asesora@prueba.test', name: 'Asesora', tier: 'advisor' }
const CLIENTE = { id: 7, label: 'Juan' }

let montado
async function abrirLaApp({ guardado, meContesta, cliente }) {
  local.set('rendi_user', JSON.stringify(guardado))
  if (cliente) api.setClientContext(cliente)
  vi.spyOn(api.api, 'get').mockImplementation(async (path) => (path === '/auth/me' ? meContesta : {}))
  montado = await montar(h(auth.AuthProvider, null, null))
}
beforeEach(() => {
  vi.restoreAllMocks()
  api.clearClientContext()
  local.clear()
  window.location.reload.mockClear()
})
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
})

describe('al abrir, el cliente guardado se suelta si ya no hay plan Asesor', () => {
  it('se le quitó el plan: suelta al cliente, lo borra de lo guardado y recarga una vez', async () => {
    await abrirLaApp({ guardado: ASESORA, cliente: CLIENTE, meContesta: { ...ASESORA, tier: 'free' } })
    expect(api.getClientContext()).toBeNull()
    expect(local.get('rendi_client_ctx')).toBeUndefined()
    expect(window.location.reload).toHaveBeenCalledTimes(1)
  })

  it('el plan venció y pasó a Pro: tampoco es asesora, lo suelta igual', async () => {
    await abrirLaApp({ guardado: ASESORA, cliente: CLIENTE, meContesta: { ...ASESORA, tier: 'pro' } })
    expect(api.getClientContext()).toBeNull()
    expect(window.location.reload).toHaveBeenCalledTimes(1)
  })

  it('sigue con el plan: el cliente se queda y no recarga', async () => {
    await abrirLaApp({ guardado: ASESORA, cliente: CLIENTE, meContesta: ASESORA })
    expect(api.getClientContext()).toEqual(CLIENTE)
    expect(window.location.reload).not.toHaveBeenCalled()
  })

  it('una cuenta común sin cliente abierto no recarga', async () => {
    const ana = { email: 'ana@prueba.test', name: 'Ana', tier: 'free' }
    await abrirLaApp({ guardado: ana, meContesta: ana })
    expect(api.getClientContext()).toBeNull()
    expect(window.location.reload).not.toHaveBeenCalled()
  })
})
