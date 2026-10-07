import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo } from '../testing/navegadorMinimo'

// 🔴 CERRAR SESIÓN CON EL CHAT ABIERTO, CON LA SESIÓN DE VERDAD (2026-10-05).
//
// Las pruebas de fotoDeOtraCuenta.test.js simulan quién está logueado. Ésta
// monta AuthProvider y VozProvider REALES, juntos, y usa login() y logout()
// de la app: si alguien cambia el orden de lo que hace el logout (salir del
// cliente, borrar lo guardado, vaciar la sesión), esto lo ve. El caso es el
// peor: el asesor cierra sesión adentro de un cliente con Rendi a mitad de una
// respuesta, y en la misma pestaña entra otra persona.
//
// Lo único simulado es el servidor.

let api, auth, voz, sesion
beforeAll(async () => {
  ;({ sesion } = instalarNavegadorMinimo())
  api = await import('../utils/api')
  auth = await import('./AuthContext')
  voz = await import('./VozContext')
})
afterAll(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

const ASESOR = { id: 1, email: 'asesor@prueba.test', name: 'Asesor', tier: 'advisor' }
const OTRA = { id: 9, email: 'otra@prueba.test', name: 'Otra', tier: 'pro' }
const ANA = { id: 2, label: 'Ana' }
const BROKERS = { null: [{ name: 'IOL' }], 2: [{ name: 'Balanz' }] }

describe('cerrar sesión con el chat abierto (sesión y chat reales)', () => {
  it('el que entra después en la misma pestaña no ve ni manda nada del anterior', async () => {
    // Arranca de una pestaña limpia, corra antes o después de la otra prueba.
    for (const k of [...sesion.keys()]) sesion.delete(k)
    localStorage.removeItem('rendi_user')
    api.clearClientContext()
    let enElServidor = null
    vi.spyOn(api.api, 'get').mockImplementation(async (path) => {
      if (path === '/auth/me') {
        if (!enElServidor) throw Object.assign(new Error('Unauthorized'), { status: 401 })
        return enElServidor
      }
      if (path === '/brokers') return BROKERS[api.getClientContext()?.id ?? null]
      return []
    })
    vi.spyOn(api.api, 'post').mockImplementation(async () => ({}))
    let soltar
    const pedidos = []
    vi.spyOn(api.api, 'chatStream').mockImplementation(async (body, avisos) => {
      pedidos.push({
        cliente: api.getClientContext()?.id ?? null,
        brokers: (body.snapshot.brokers || []).map(b => b.name),
        mensajes: body.messages.map(m => `${m.role[0]}: ${m.content}`),
      })
      avisos.onDelta?.(`Respuesta a: ${body.messages.at(-1).content}`)
      if (body.messages.at(-1).content === 'otra sobre Ana') await new Promise(r => { soltar = r })
      return {}
    })

    const v = { auth: null, voz: null }
    const Mirar = () => { v.auth = auth.useAuth(); v.voz = voz.useVoz(); return null }
    const m = await montar(h(auth.AuthProvider, null, h(voz.VozProvider, null, h(Mirar))))
    const charla = () => v.voz.thread.map(x => `${x.role[0]}: ${x.content}`)
    const guardadoDelChat = () => [...sesion.keys()].filter(k => k.startsWith('rendi_chat'))

    // Entra el asesor, abre a Ana y le pregunta a Rendi.
    enElServidor = ASESOR
    await enActo(() => v.auth.login(null, ASESOR.name, { email: ASESOR.email }))
    await enActo(() => api.setClientContext(ANA))
    await enActo(() => v.voz.ask('sobre Ana'))
    expect(charla()).toEqual(['u: sobre Ana', 'a: Respuesta a: sobre Ana'])

    // Repregunta y, con Rendi a mitad de la respuesta, cierra sesión.
    let enCurso
    await enActo(async () => { enCurso = v.voz.ask('otra sobre Ana') })
    enElServidor = null
    await enActo(() => v.auth.logout())
    expect(v.auth.user).toBe(null)
    expect(charla()).toEqual([])
    expect(guardadoDelChat()).toEqual([])
    // La respuesta que venía llegando termina: no cae en ningún lado.
    await enActo(async () => { soltar(); await enCurso })
    expect(charla()).toEqual([])
    expect(guardadoDelChat()).toEqual([])

    // Entra otra persona en la misma pestaña.
    enElServidor = OTRA
    await enActo(() => v.auth.login(null, OTRA.name, { email: OTRA.email }))
    expect(charla()).toEqual([])
    await enActo(() => v.voz.ask('soy otra persona'))
    expect(pedidos.at(-1)).toEqual({ cliente: null, brokers: ['IOL'], mensajes: ['u: soy otra persona'] })

    await m.desmontar()
  })

  it('la sesión del asesor VENCIÓ con un cliente abierto y otra persona entra por "olvidé mi contraseña": no le llega nada del asesor', async () => {
    // Lo que deja un 401: sin sesión guardada, pero con el cliente abierto
    // anotado y las charlas del asesor en la pestaña, firmadas por él.
    for (const k of [...sesion.keys()]) sesion.delete(k)
    localStorage.removeItem('rendi_user')
    api.setClientContext(ANA)
    sesion.set('rendi_chat_dueno', ASESOR.email)
    sesion.set('rendi_chat_v1', JSON.stringify([{ role: 'user', content: 'charla privada del asesor' }]))
    sesion.set('rendi_chat_v1_c2', JSON.stringify([{ role: 'user', content: 'charla privada sobre Ana' }]))
    // El servidor no contesta /auth/me (y el login de "olvidé mi contraseña"
    // no trae el email): por un rato no se sabe quién es.
    vi.spyOn(api.api, 'get').mockImplementation(async (path) => {
      if (path === '/auth/me') throw Object.assign(new Error('HTTP 503'), { status: 503 })
      if (path === '/brokers') return BROKERS[api.getClientContext()?.id ?? null]
      return []
    })
    const pedidos = []
    vi.spyOn(api.api, 'chatStream').mockImplementation(async (body) => {
      pedidos.push(body.messages.map(x => `${x.role[0]}: ${x.content}`))
      return {}
    })
    const v = { auth: null, voz: null }
    const Mirar = () => { v.auth = auth.useAuth(); v.voz = voz.useVoz(); return null }
    const m = await montar(h(auth.AuthProvider, null, h(voz.VozProvider, null, h(Mirar))))
    await enActo(() => v.auth.login(null, 'Q', {}))
    expect(v.voz.thread).toEqual([])
    await enActo(() => v.voz.ask('hola, soy otra persona'))
    expect(pedidos).toEqual([['u: hola, soy otra persona']])
    await m.desmontar()
  })
})
