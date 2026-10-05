import { describe, it, expect, vi, beforeAll, beforeEach, afterEach, afterAll } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, otraPestanaEscribe, montar, enActo, buscar } from '../testing/navegadorMinimo'

// 🔴 LA IA CONTESTABA SOBRE UN CLIENTE CON LOS DATOS DE OTRO (2026-10-05).
//
// Cada pregunta a la IA viaja con una "foto" de la cartera armada en el
// navegador y con la conversación previa, y el servidor las toma como de la
// cuenta a la que va la pregunta: vuelve a valuar las posiciones, pero las
// operaciones cerradas, los meses, los brokers y la charla los usa como
// llegan. El chat guardaba la primera foto y la conversación sin anotar de
// quién eran, y nada le avisaba cuando el asesor cambiaba de cliente. Medido
// en el navegador con dos clientes de prueba: con Bruno abierto, la pregunta
// salía con el broker, la operación y la charla de Ana; y al cerrar sesión, el
// siguiente usuario de la pestaña veía la charla del anterior.
//
// Acá se prueba la cadena con las piezas DE VERDAD —el contexto de cliente de
// api.js, la foto de aiSnapshot, el proveedor VozContext MONTADO con react-dom
// (ver testing/navegadorMinimo.js), AdvisorContext—. Lo único simulado es el
// servidor y quién está logueado.

// Quién está logueado: un contexto que la prueba controla, en lugar de
// AuthContext (que pediría /auth/me). Se puede cambiar redibujando.
const sesionDePrueba = vi.hoisted(() => ({ Ctx: null }))
vi.mock('./AuthContext', async () => {
  const { createContext, useContext } = await import('react')
  sesionDePrueba.Ctx = createContext({ user: null })
  return { useAuth: () => useContext(sesionDePrueba.Ctx) }
})

let api, aiSnapshot, voz, advisor
let local, sesion
// Los controles de audio del sistema (pantalla bloqueada, auriculares).
const controles = { metadata: null, botones: {}, setActionHandler(n, f) { this.botones[n] = f } }
beforeAll(async () => {
  ;({ local, sesion } = instalarNavegadorMinimo())
  Object.defineProperty(globalThis.navigator, 'mediaSession', { value: controles, configurable: true })
  window.MediaMetadata = class { constructor(o) { Object.assign(this, o) } }
  api = await import('../utils/api')
  aiSnapshot = await import('../utils/aiSnapshot')
  voz = await import('./VozContext')
  advisor = await import('./AdvisorContext')
})
afterAll(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

const ANA = { id: 2, label: 'Ana' }
const BRUNO = { id: 3, label: 'Bruno' }
const ASESOR = { email: 'asesor@prueba.test', tier: 'advisor' }
const OTRA = { email: 'otra@prueba.test', tier: 'pro' }

// El "servidor": contesta con los datos de la cuenta que diga el contexto en
// el momento del pedido — igual que el de verdad con el encabezado del cliente.
const DATOS = {
  null: { brokers: [{ name: 'IOL' }], operations: [] },
  2: { brokers: [{ name: 'Balanz' }], operations: [{ asset: 'YPF' }] },
  3: { brokers: [{ name: 'IBKR' }], operations: [{ asset: 'NVDA' }] },
}
const datosDeAhora = (path) => {
  const d = DATOS[api.getClientContext()?.id ?? null]
  if (path === '/brokers') return d.brokers
  if (path === '/operations') return d.operations
  return []
}

// Lo que el navegador le manda a la IA en cada pregunta, resumido.
function servidor({ responder } = {}) {
  vi.spyOn(api.api, 'get').mockImplementation(async (path) => datosDeAhora(path))
  const pedidos = []
  vi.spyOn(api.api, 'chatStream').mockImplementation(async (body, avisos) => {
    pedidos.push({
      cliente: api.getClientContext()?.id ?? null,
      libro: Object.keys(body.snapshot).length === 0,
      brokers: (body.snapshot.brokers || []).map(b => b.name),
      mensajes: body.messages.map(m => `${m.role[0]}: ${m.content}`),
    })
    if (responder) return responder(body, avisos)
    avisos.onDelta?.(`Respuesta a: ${body.messages.at(-1).content}`)
    return {}
  })
  return pedidos
}

const guardada = (clave) => JSON.parse(sesion.get(clave) || '[]').map(m => `${m.role[0]}: ${m.content}`)
const charla = (v) => v.actual.thread.map(m => `${m.role[0]}: ${m.content}`)

// Monta el chat como en la app (VozProvider arriba de todo) con `user` logueado.
const montados = []
async function montarChat(user) {
  const v = { actual: null }
  const Mirar = () => { v.actual = voz.useVoz(); return null }
  const arbol = (u) => h(sesionDePrueba.Ctx.Provider, { value: { user: u } }, h(voz.VozProvider, null, h(Mirar)))
  const m = await montar(arbol(user))
  montados.push(m)
  return { v, arbol, m, cambiarPersona: (u) => m.redibujar(arbol(u)) }
}
const preguntar = (v, texto) => enActo(() => v.actual.ask(texto))
const entrarA = (cliente) => enActo(() => api.setClientContext(cliente))
const salirDelCliente = () => enActo(() => api.clearClientContext())

let avisos = 0
const contar = () => { avisos += 1 }
beforeEach(() => {
  vi.restoreAllMocks()
  api.clearClientContext()
  local.clear()
  sesion.clear()
  avisos = 0
  window.removeEventListener(api.EVENTO_CUENTA_CAMBIADA, contar)
  window.addEventListener(api.EVENTO_CUENTA_CAMBIADA, contar)
})
afterEach(async () => {
  while (montados.length) await montados.pop().desmontar()
})

describe('api.js avisa cuando cambia la cuenta', () => {
  it('entrar a un cliente avisa; volver a entrar al mismo, no; salir, sí', () => {
    api.setClientContext(ANA)
    expect(avisos).toBe(1)
    api.setClientContext({ ...ANA })
    expect(avisos).toBe(1)
    api.setClientContext(BRUNO)
    expect(avisos).toBe(2)
    api.clearClientContext()
    expect(avisos).toBe(3)
    api.clearClientContext()
    expect(avisos).toBe(3)
  })

  it('cuando avisa, el cliente nuevo ya está puesto (lo leen los que escuchan)', () => {
    let visto = 'nada'
    const mirar = () => { visto = api.getClientContext()?.id ?? null }
    window.addEventListener(api.EVENTO_CUENTA_CAMBIADA, mirar)
    api.setClientContext(BRUNO)
    window.removeEventListener(api.EVENTO_CUENTA_CAMBIADA, mirar)
    expect(visto).toBe(3)
  })

  it('también cuando el cambio lo hizo otra pestaña', () => {
    otraPestanaEscribe('rendi_client_ctx', JSON.stringify(BRUNO))
    expect(api.getClientContext()?.id).toBe(3)
    expect(avisos).toBe(1)
    // Otra pestaña vació todo (`key` null): sin cliente.
    otraPestanaEscribe(null, null)
    expect(api.getClientContext()).toBe(null)
    expect(avisos).toBe(2)
    // Una clave que no tiene nada que ver no avisa.
    otraPestanaEscribe('rendi_theme', 'dark')
    expect(avisos).toBe(2)
  })
})

describe('cada foto sabe de qué cuenta es', () => {
  it('los cuatro pedidos de la foto salen con el cliente con el que queda anotada', async () => {
    // Acá NO se simula api.get: van los pedidos reales de api.js, y lo que se
    // mira es el encabezado que llevan.
    const encabezados = []
    vi.stubGlobal('fetch', vi.fn(async (_url, opts) => {
      encabezados.push(opts.headers['X-Rendi-Client-Id'] ?? null)
      return { status: 200, ok: true, json: async () => [] }
    }))
    try {
      api.setClientContext(ANA)
      const foto = await aiSnapshot.fetchAiSnapshot()
      expect(encabezados).toEqual(['2', '2', '2', '2'])
      expect(aiSnapshot.esFotoDeLaCuentaActual(foto)).toBe(true)
      api.setClientContext(BRUNO)
      expect(aiSnapshot.esFotoDeLaCuentaActual(foto)).toBe(false)
      api.clearClientContext()
      expect(aiSnapshot.esFotoDeLaCuentaActual(foto)).toBe(false)
      api.setClientContext(ANA)
      expect(aiSnapshot.esFotoDeLaCuentaActual(foto)).toBe(true)
    } finally {
      vi.stubGlobal('fetch', undefined)
    }
  })

  it('si cambian de cliente mientras llega, queda anotada con la cuenta a la que fueron los pedidos', async () => {
    let soltar
    const enVuelo = new Promise(r => { soltar = r })
    const get = vi.spyOn(api.api, 'get').mockImplementation(() => enVuelo)
    api.setClientContext(ANA)
    const pedida = aiSnapshot.fetchAiSnapshot()
    expect(get).toHaveBeenCalledTimes(4)   // los cuatro salieron YA, con Ana
    api.setClientContext(BRUNO)
    soltar([])
    const foto = await pedida
    expect(aiSnapshot.esFotoDeLaCuentaActual(foto)).toBe(false)
    api.setClientContext(ANA)
    expect(aiSnapshot.esFotoDeLaCuentaActual(foto)).toBe(true)
  })

  it('la del modo libro (`{}`) no es de ninguna cuenta', () => {
    expect(aiSnapshot.esFotoDeLaCuentaActual({})).toBe(false)
    expect(aiSnapshot.esFotoDeLaCuentaActual(null)).toBe(false)
  })
})

describe('fotoParaLaPregunta: la que viaja con la pregunta', () => {
  it('con la misma cuenta reusa la que hay: no pide los datos en cada pregunta', async () => {
    const get = vi.spyOn(api.api, 'get').mockImplementation(async (p) => datosDeAhora(p))
    api.setClientContext(BRUNO)
    const primera = await voz.fotoParaLaPregunta({ libro: false, guardada: null })
    const pedidos = get.mock.calls.length
    expect(await voz.fotoParaLaPregunta({ libro: false, guardada: primera })).toBe(primera)
    expect(await voz.fotoParaLaPregunta({ libro: false, deAfuera: primera, guardada: null })).toBe(primera)
    expect(get.mock.calls.length).toBe(pedidos)
  })

  it('si la pantalla trae una foto de otra cuenta, no viaja: se pide la de ahora', async () => {
    vi.spyOn(api.api, 'get').mockImplementation(async (p) => datosDeAhora(p))
    api.setClientContext(ANA)
    const deAna = await aiSnapshot.fetchAiSnapshot()
    api.setClientContext(BRUNO)
    const foto = await voz.fotoParaLaPregunta({ libro: false, deAfuera: deAna, guardada: null })
    expect(foto.brokers.map(b => b.name)).toEqual(['IBKR'])
  })

  it('en el modo libro no se piden datos (la cartera personal del asesor está vacía)', async () => {
    const traer = vi.fn()
    expect(await voz.fotoParaLaPregunta({ libro: true, guardada: null, traer })).toEqual({})
    expect(traer).not.toHaveBeenCalled()
  })
})

describe('el chat de verdad (VozContext montado): cambiar de cliente', () => {
  it('escenario B — Ana → Bruno: la pregunta en Bruno viaja con los datos y la charla de Bruno', async () => {
    const pedidos = servidor()
    const { v } = await montarChat(ASESOR)
    await entrarA(ANA)
    await preguntar(v, 'sobre Ana')
    await entrarA(BRUNO)
    expect(charla(v)).toEqual([])
    await preguntar(v, 'sobre Bruno')
    expect(pedidos).toEqual([
      { cliente: 2, libro: false, brokers: ['Balanz'], mensajes: ['u: sobre Ana'] },
      { cliente: 3, libro: false, brokers: ['IBKR'], mensajes: ['u: sobre Bruno'] },
    ])
    // Cada charla quedó guardada a nombre de su cliente, y al volver a Ana vuelve la suya.
    expect(guardada('rendi_chat_v1_c2')).toEqual(['u: sobre Ana', 'a: Respuesta a: sobre Ana'])
    expect(guardada('rendi_chat_v1_c3')).toEqual(['u: sobre Bruno', 'a: Respuesta a: sobre Bruno'])
    await entrarA(ANA)
    expect(charla(v)).toEqual(['u: sobre Ana', 'a: Respuesta a: sobre Ana'])
  })

  it('escenario A — libro → Ana: en el libro viaja `{}`, en Ana su foto y sin la charla del libro', async () => {
    const pedidos = servidor()
    const { v } = await montarChat(ASESOR)
    await preguntar(v, 'sobre el libro')
    await entrarA(ANA)
    await preguntar(v, 'sobre Ana')
    expect(pedidos).toEqual([
      { cliente: null, libro: true, brokers: [], mensajes: ['u: sobre el libro'] },
      { cliente: 2, libro: false, brokers: ['Balanz'], mensajes: ['u: sobre Ana'] },
    ])
    // Y al salir del cliente vuelve la charla del libro.
    await salirDelCliente()
    expect(charla(v)).toEqual(['u: sobre el libro', 'a: Respuesta a: sobre el libro'])
  })

  it('cambia de cliente mientras Rendi responde: se descarta, y la charla de Ana queda como antes de preguntar', async () => {
    sesion.set('rendi_chat_v1_c2', JSON.stringify([
      { role: 'user', content: 'vieja' }, { role: 'assistant', content: 'respuesta vieja' }]))
    let soltar
    const pedidos = servidor({
      responder: async (body, avisos) => {
        if (!body.messages.at(-1).content.includes('Ana')) return {}
        avisos.onDelta?.('a medias')
        await new Promise(r => { soltar = r })
        avisos.onDelta?.(' y el resto')
        return {}
      },
    })
    const { v } = await montarChat(ASESOR)
    await entrarA(ANA)
    let enCurso
    await enActo(async () => { enCurso = v.actual.ask('nueva sobre Ana') })
    // A mitad de la respuesta, lo guardado de Ana ya tiene la pregunta y el pedazo.
    expect(guardada('rendi_chat_v1_c2')).toEqual(['u: vieja', 'a: respuesta vieja', 'u: nueva sobre Ana', 'a: a medias'])
    await entrarA(BRUNO)
    expect(guardada('rendi_chat_v1_c2')).toEqual(['u: vieja', 'a: respuesta vieja'])
    expect(charla(v)).toEqual([])
    expect(v.actual.sending).toBe(false)
    // Llega el resto de la respuesta de Ana: no cae en Bruno ni en lo guardado.
    await enActo(async () => { soltar(); await enCurso })
    expect(charla(v)).toEqual([])
    expect(sesion.has('rendi_chat_v1_c3')).toBe(false)
    expect(guardada('rendi_chat_v1_c2')).toEqual(['u: vieja', 'a: respuesta vieja'])
    // Y en Bruno se puede preguntar enseguida, con lo de Bruno.
    await preguntar(v, 'sobre Bruno')
    expect(pedidos.at(-1)).toEqual({ cliente: 3, libro: false, brokers: ['IBKR'], mensajes: ['u: sobre Bruno'] })
  })

  it('cambia de cliente con la respuesta YA entera (mientras decide si leerla): la charla de Ana la conserva', async () => {
    let soltarCupo
    servidor({ responder: async (_body, avisos) => {
      avisos.onDelta?.('Respuesta completa')
      return { voz: { text: 'Resumen hablado', sig: 'firma' } }   // la voz llega recién al final
    } })
    // Mientras se pregunta el cupo de escuchas, el asesor cambia de cliente.
    api.api.get.mockImplementation(async (path) =>
      (path === '/ai/usage' ? new Promise(r => { soltarCupo = r }) : datosDeAhora(path)))
    const { v } = await montarChat(ASESOR)
    await entrarA(ANA)
    let enCurso
    await enActo(async () => { enCurso = v.actual.ask('sobre Ana') })
    await enActo(() => new Promise(r => setTimeout(r, 0)))
    expect(guardada('rendi_chat_v1_c2')).toEqual(['u: sobre Ana', 'a: Respuesta completa'])
    await entrarA(BRUNO)
    expect(guardada('rendi_chat_v1_c2')).toEqual(['u: sobre Ana', 'a: Respuesta completa'])
    await enActo(async () => { soltarCupo(null); await enCurso })
    await entrarA(ANA)
    expect(charla(v)).toEqual(['u: sobre Ana', 'a: Respuesta completa'])
  })

  it('cambia de cliente con una respuesta hablada: el audio se descarga y los controles del sistema quedan sin título', async () => {
    servidor({ responder: async (_body, avisos) => {
      avisos.onDelta?.('Respuesta')
      avisos.onVoz?.({ text: 'Ana tiene AAPL en Balanz', sig: 'firma' })
      return {}
    } })
    vi.spyOn(api.api, 'post').mockImplementation(async () => ({ url: '/api/ai/voz/AAAA.mp3' }))
    const { v, m } = await montarChat(ASESOR)
    await entrarA(ANA)
    await preguntar(v, 'sobre Ana')
    await enActo(() => new Promise(r => setTimeout(r, 0)))
    const audio = buscar(m.contenedor, 'audio')
    expect(audio.src).toBe('/api/ai/voz/AAAA.mp3')
    expect(controles.metadata?.title).toBe('Ana tiene AAPL en Balanz')
    await entrarA(BRUNO)
    expect(audio.src).toBe('')
    expect(controles.metadata).toBe(null)
    expect(v.actual.current).toBe(null)
    // Y el play de los auriculares no hace nada (ni sonar lo de Ana, ni
    // dejar la pantalla diciendo "Hablando…").
    const play = vi.spyOn(audio, 'play')
    await enActo(() => controles.botones.play())
    expect(play).not.toHaveBeenCalled()
    expect(v.actual.status).not.toBe('playing')
  })

  it('cambia de cliente justo cuando el audio arranca: no queda un error falso en el chat nuevo', async () => {
    servidor({ responder: async (_body, avisos) => {
      avisos.onDelta?.('Respuesta')
      avisos.onVoz?.({ text: 'Ana tiene AAPL en Balanz', sig: 'firma' })
      return {}
    } })
    vi.spyOn(api.api, 'post').mockImplementation(async () => ({ url: '/api/ai/voz/AAAA.mp3' }))
    const { v, m } = await montarChat(ASESOR)
    // Un <audio> como el de verdad: la reproducción queda pendiente hasta que
    // llega audio, y pausar la corta con un AbortError.
    const audio = buscar(m.contenedor, 'audio')
    let cortar = null
    vi.spyOn(audio, 'play').mockImplementation(() => (audio.src.startsWith('data:')
      ? Promise.resolve()
      : new Promise((_, rechazar) => { cortar = () => rechazar(Object.assign(new Error('aborted'), { name: 'AbortError' })) })))
    vi.spyOn(audio, 'pause').mockImplementation(() => { cortar?.(); cortar = null })
    await entrarA(ANA)
    await preguntar(v, 'sobre Ana')
    await enActo(() => new Promise(r => setTimeout(r, 0)))
    expect(cortar).not.toBe(null)            // el audio está arrancando
    await entrarA(BRUNO)
    await enActo(() => new Promise(r => setTimeout(r, 0)))
    expect(v.actual.askError).toBe(null)
    expect(v.actual.status).not.toBe('error')
  })

  it('cambia de cliente mientras se arma la foto: esa pregunta no sale', async () => {
    let soltar
    const enVuelo = new Promise(r => { soltar = r })
    const pedidos = servidor()
    vi.spyOn(api.api, 'get').mockImplementation(() => enVuelo)
    const { v } = await montarChat(ASESOR)
    await entrarA(ANA)
    let enCurso
    await enActo(async () => { enCurso = v.actual.ask('sobre Ana') })
    await entrarA(BRUNO)
    await enActo(async () => { soltar([]); await enCurso })
    expect(pedidos).toEqual([])
    expect(charla(v)).toEqual([])
  })
})

describe('el chat de verdad (VozContext montado): cambiar de PERSONA', () => {
  // Lo que hace AuthContext.logout(), todo en el mismo click: sale del
  // cliente, borra lo guardado y deja la sesión vacía.
  const cerrarSesion = (m, arbol) => enActo(async () => {
    api.clearClientContext()
    for (const k of [...sesion.keys()]) if (k.startsWith('rendi_')) sesion.delete(k)
    m.raiz.render(arbol(null))
  })

  it('cierra sesión adentro de un cliente y entra otra persona: no ve ni manda nada del anterior', async () => {
    const pedidos = servidor()
    const { v, m, arbol, cambiarPersona } = await montarChat(ASESOR)
    await preguntar(v, 'sobre el libro')
    await entrarA(ANA)
    await preguntar(v, 'sobre Ana')
    await cerrarSesion(m, arbol)
    expect(charla(v)).toEqual([])
    expect([...sesion.keys()].filter(k => k.startsWith('rendi_chat'))).toEqual([])
    await cambiarPersona(OTRA)
    expect(charla(v)).toEqual([])
    await preguntar(v, 'soy otra persona')
    expect(pedidos.at(-1)).toEqual({ cliente: null, libro: false, brokers: ['IOL'], mensajes: ['u: soy otra persona'] })
  })

  it('aunque el cierre de sesión llegue en dos pasos, lo que se escriba en el medio no le toca al siguiente', async () => {
    servidor()
    const { v, cambiarPersona } = await montarChat(ASESOR)
    await preguntar(v, 'sobre el libro')
    await entrarA(ANA)
    // Primero sale del cliente (y el chat vuelve a la charla del libro)…
    await salirDelCliente()
    for (const k of [...sesion.keys()]) if (k.startsWith('rendi_')) sesion.delete(k)
    // …y recién después se borra la sesión.
    await cambiarPersona(null)
    await cambiarPersona(OTRA)
    expect(charla(v)).toEqual([])
    await entrarA(BRUNO)
    await salirDelCliente()
    expect(charla(v)).toEqual([])
  })

  it('la sesión VENCIÓ (sin cerrar sesión) y entra otra persona: lo guardado del anterior se borra', async () => {
    // El 401 recarga la página sin borrar nada: queda lo guardado del asesor,
    // firmado por él, y el cliente que tenía abierto.
    sesion.set('rendi_chat_dueno', 'asesor@prueba.test')
    sesion.set('rendi_chat_v1', JSON.stringify([{ role: 'user', content: 'del libro' }]))
    sesion.set('rendi_chat_v1_c2', JSON.stringify([{ role: 'user', content: 'de Ana' }]))
    api.setClientContext(ANA)
    servidor()
    const { v, m, arbol } = await montarChat(null)
    // Entra otra persona: login() saca el cliente y pone la sesión nueva, en el mismo click.
    await enActo(async () => { api.clearClientContext(); m.raiz.render(arbol(OTRA)) })
    expect(charla(v)).toEqual([])
    expect(sesion.has('rendi_chat_v1')).toBe(false)
    expect(sesion.has('rendi_chat_v1_c2')).toBe(false)
    await entrarA(ANA)
    await salirDelCliente()
    expect(charla(v)).toEqual([])
  })

  it('y si vuelve a entrar la MISMA persona, recupera su charla', async () => {
    sesion.set('rendi_chat_dueno', 'asesor@prueba.test')
    sesion.set('rendi_chat_v1', JSON.stringify([{ role: 'user', content: 'del libro' }]))
    const { v, cambiarPersona } = await montarChat(null)
    await cambiarPersona(ASESOR)
    expect(charla(v)).toEqual(['u: del libro'])
  })

  it('lo guardado por la versión ANTERIOR de la app (sin dueño) no se lo hereda el que entra', async () => {
    sesion.set('rendi_chat_v1', JSON.stringify([{ role: 'user', content: 'charla vieja sin dueño' }]))
    const { v, cambiarPersona } = await montarChat(null)
    await cambiarPersona(OTRA)
    expect(charla(v)).toEqual([])
    expect(sesion.has('rendi_chat_v1')).toBe(false)
  })

  it('pero con un F5 de la misma persona, lo sin dueño de la versión anterior sigue siendo suyo', async () => {
    sesion.set('rendi_chat_v1', JSON.stringify([{ role: 'user', content: 'mi charla de antes del deploy' }]))
    const { v } = await montarChat(ASESOR)
    expect(charla(v)).toEqual(['u: mi charla de antes del deploy'])
  })

  it('F5: la conversación de quien está sigue ahí', async () => {
    sesion.set('rendi_chat_dueno', 'asesor@prueba.test')
    sesion.set('rendi_chat_v1', JSON.stringify([{ role: 'user', content: 'antes del F5' }]))
    const { v } = await montarChat(ASESOR)
    expect(charla(v)).toEqual(['u: antes del F5'])
  })

  it('si todavía no se sabe quién es (entró por "olvidé mi contraseña"), no muestra lo guardado', async () => {
    // El reseteo de contraseña inicia sesión sin email hasta que /auth/me lo trae.
    sesion.set('rendi_chat_dueno', 'otra@prueba.test')
    sesion.set('rendi_chat_v1', JSON.stringify([{ role: 'user', content: 'de otra persona' }]))
    const { v, cambiarPersona } = await montarChat({ name: 'Sin email todavía' })
    expect(charla(v)).toEqual([])
    await cambiarPersona(ASESOR)
    expect(charla(v)).toEqual([])
    expect(sesion.has('rendi_chat_v1')).toBe(false)
  })

  it('abrir el demo en la misma pestaña no borra lo guardado de la persona real', async () => {
    sesion.set('rendi_chat_dueno', 'asesor@prueba.test')
    sesion.set('rendi_chat_v1', JSON.stringify([{ role: 'user', content: 'del asesor' }]))
    sesion.set('rendi_chat_v1_c7', JSON.stringify([{ role: 'user', content: 'de un cliente' }]))
    sesion.set('rendi_chat_demo_v1', JSON.stringify([{ role: 'user', content: 'del demo' }]))
    local.set('rendi_demo_mode', String(Date.now()))
    const { v } = await montarChat({ email: 'demo@rendi.finance', tier: 'pro' })
    expect(charla(v)).toEqual(['u: del demo'])
    expect(guardada('rendi_chat_v1')).toEqual(['u: del asesor'])
    expect(guardada('rendi_chat_v1_c7')).toEqual(['u: de un cliente'])
  })

  it('la pestaña se recarga con OTRA persona (cambió en otra pestaña): lo guardado del anterior no aparece', async () => {
    sesion.set('rendi_chat_dueno', 'otra@prueba.test')
    sesion.set('rendi_chat_v1', JSON.stringify([{ role: 'user', content: 'de otra persona' }]))
    const { v } = await montarChat(ASESOR)
    expect(charla(v)).toEqual([])
    expect(sesion.has('rendi_chat_v1')).toBe(false)
  })
})

describe('AdvisorContext sigue el mismo aviso que el chat', () => {
  it('otra pestaña vació todo: la banda deja de mostrar el cliente, igual que los pedidos', async () => {
    vi.spyOn(api.api, 'get').mockImplementation(async () => ({}))
    const visto = { actual: null }
    const Mirar = () => { visto.actual = advisor.useAdvisorContext(); return null }
    montados.push(await montar(h(advisor.AdvisorProvider, null, h(Mirar))))
    await enActo(() => visto.actual.enterClient(ANA))
    expect(visto.actual.clientCtx?.id).toBe(2)
    await enActo(() => otraPestanaEscribe(null, null))
    expect(api.getClientContext()).toBe(null)
    expect(visto.actual.clientCtx).toBe(null)
  })
})

// La pantalla /ai se prueba montada en pages/RendiAI.fotoPorCliente.test.js.
