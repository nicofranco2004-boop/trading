import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { crearLecturaDeCartera, VIGENCIA_MS, VUELTAS, claveDePersona, CAMBIO_DE_PERSONA, PAUSA_TRAS_CAMBIO_MS } from './lecturaDeCartera'
import { mapMeToUser } from '../contexts/AuthContext'
import { fetchAiSnapshot, resumenDeCartera } from './aiSnapshot'
import { pasosContextoIA } from './cargaPorPasos'
import { api, EVENTO_ESCRITURA, escrituraTocaLaCartera } from './api'

// La lectura de tu cartera que muestra la isla ("Viendo tu cartera · 12
// posiciones · 3 brokers") y que viaja con cada pregunta. Lo que se prueba acá
// es el MISMO objeto que usa VozContext (crearLecturaDeCartera), con el
// pedido de verdad reemplazado por uno que controla la prueba.

const snapDe = (n, brokers = 2) => ({
  summary: { open_positions_count: n },
  brokers: Array.from({ length: brokers }, (_, i) => ({ id: i })),
})

// Un pedido que la prueba resuelve cuando quiere; `avisos[k]` es el alLlegar
// que recibió la lectura k (el que tilda cada renglón del cargador de /ai).
function pedidoControlado() {
  const pendientes = []
  const avisos = []
  const leer = vi.fn((alLlegar) => { avisos.push(alLlegar); return new Promise((ok, mal) => pendientes.push({ ok, mal })) })
  return { leer, pendientes, avisos }
}
const sinSnap = (e) => e && { ...e, snap: e.snap ? e.snap.summary.open_positions_count : null }
// Sin la pausa tras una escritura (se prueba aparte): la relectura sale en el acto.
const RAPIDO = { pausaTrasCambio: 0 }

describe('lecturaDeCartera — una sola lectura para la isla, /ai y la pregunta', () => {
  it('la isla la pide al abrirse y la pregunta que llega antes espera ESA lectura', async () => {
    const { leer, pendientes } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|', alCambiar: (e) => estados.push(sinSnap(e)) })
    const deLaIsla = l.traer()
    const deLaPregunta = l.traer()
    expect(leer).toHaveBeenCalledTimes(1)           // no otros 4 pedidos
    pendientes[0].ok(snapDe(12, 3))
    expect(await deLaPregunta).toBe(await deLaIsla)
    expect(estados).toEqual([
      { estado: 'leyendo', llego: {}, snap: null },
      { estado: 'lista', snap: 12, resumen: { posiciones: 12, brokers: 3 } },
    ])
    // Ya leída: abrir de nuevo (o entrar a /ai) no pide nada.
    await l.traer()
    expect(leer).toHaveBeenCalledTimes(1)
  })

  it('cada pedido que vuelve se anota para el cargador de /ai', async () => {
    const { leer, pendientes, avisos } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|', alCambiar: (e) => estados.push(e) })
    l.traer()
    avisos[0]({ pieza: 'brokers', dato: [1, 2, 3] })
    avisos[0]({ pieza: 'operations', error: true })
    expect(estados.at(-1)).toEqual({ estado: 'leyendo', llego: { brokers: [1, 2, 3], operations: 'error' }, snap: null })
    pendientes[0].ok(snapDe(4))
  })

  it('guardaste algo (invalidar): se vuelve a leer, y lo que venía en camino no se guarda', async () => {
    const { leer, pendientes, avisos } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|', alCambiar: (e) => estados.push(sinSnap(e)) })
    l.traer()
    l.invalidar()                                    // se cargó la operación 13 mientras leía
    expect(estados.at(-1)).toBe(null)
    pendientes[0].ok(snapDe(12))                     // llega la lectura de antes
    avisos[0]({ pieza: 'positions', dato: [] })      // y sus avisos ya no tildan nada
    await Promise.resolve(); await Promise.resolve()
    expect(estados.at(-1)).toBe(null)                // no se dibuja "12"
    const nueva = l.traer()                          // la isla, por el aviso, vuelve a leer
    expect(leer).toHaveBeenCalledTimes(2)
    pendientes[1].ok(snapDe(13))
    expect((await nueva).summary.open_positions_count).toBe(13)
    expect(estados.at(-1)).toEqual({ estado: 'lista', snap: 13, resumen: { posiciones: 13, brokers: 2 } })
  })

  it('releyendo tras una escritura, /ai sigue con la anterior (no vuelve al cargador)', async () => {
    const { leer, pendientes } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|', alCambiar: (e) => estados.push(sinSnap(e)) })
    const a = l.traer(); pendientes[0].ok(snapDe(12)); await a
    l.invalidar()
    expect(estados.at(-1)).toEqual({ estado: 'vieja', snap: 12 })
    const b = l.traer()
    expect(estados.at(-1)).toEqual({ estado: 'leyendo', llego: {}, snap: 12 })
    pendientes[1].mal(new Error('sin red'))
    await expect(b).rejects.toThrow()
    expect(estados.at(-1)).toEqual({ estado: 'error', mensaje: 'sin red', snap: 12 })
  })

  it('el asesor pasa a otro cliente: no se reusa —ni se muestra— la cartera del anterior', async () => {
    let cliente = 'u9|101'
    const { leer, pendientes } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => cliente, alCambiar: (e) => estados.push(sinSnap(e)) })
    const a = l.traer()
    pendientes[0].ok(snapDe(5))
    await a
    cliente = 'u9|202'
    const b = l.traer()
    expect(leer).toHaveBeenCalledTimes(2)
    expect(estados.at(-1)).toEqual({ estado: 'leyendo', llego: {}, snap: null })   // nada del 101 a la vista
    pendientes[1].ok(snapDe(40))
    expect((await b).summary.open_positions_count).toBe(40)
  })

  it('cambia de cliente con una lectura en camino: la del anterior no queda guardada', async () => {
    let cliente = 'u9|101'
    const { leer, pendientes } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => cliente, alCambiar: (e) => estados.push(sinSnap(e)) })
    l.traer()
    cliente = 'u9|202'
    const b = l.traer()                              // otra lectura: es de otro
    pendientes[0].ok(snapDe(5))                      // llega la del 101
    pendientes[1].ok(snapDe(40))
    await b
    expect(estados.filter(e => e?.estado === 'lista').map(e => e.snap)).toEqual([40])
  })

  it('si falla sin nada antes, lo dice y la próxima vez lo vuelve a intentar', async () => {
    const { leer, pendientes } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|', alCambiar: (e) => estados.push(e) })
    const p = l.traer()
    pendientes[0].mal(new Error('sin red'))
    await expect(p).rejects.toThrow('sin red')
    expect(estados.at(-1)).toEqual({ estado: 'error', mensaje: 'sin red', snap: null })
    l.traer()
    expect(leer).toHaveBeenCalledTimes(2)
  })

  it('el asesor va de A a B y vuelve a A con la de B en camino: se ve A, y B no se publica al llegar', async () => {
    let cliente = 'u9|A'
    const { leer, pendientes } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => cliente, alCambiar: (e) => estados.push(sinSnap(e)) })
    const a = l.traer(); pendientes[0].ok(snapDe(12)); await a
    cliente = 'u9|B'
    const b = l.traer()                              // la de B sale…
    cliente = 'u9|A'
    expect((await l.traer()).summary.open_positions_count).toBe(12)
    expect(estados.at(-1)).toEqual({ estado: 'lista', snap: 12, resumen: { posiciones: 12, brokers: 2 } })
    pendientes[1].ok(snapDe(40))                     // …y llega con A a la vista
    await b
    expect(estados.at(-1)).toMatchObject({ estado: 'lista', snap: 12 })   // antes: 40, las de B
  })

  it('la pregunta que esperaba una lectura que quedó vieja recibe la nueva, no la de antes de guardar', async () => {
    const { leer, pendientes } = pedidoControlado()
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|' })
    const pregunta = l.paraPreguntar()
    l.invalidar()                                    // guardaste la operación 13 mientras leía
    pendientes[0].ok(snapDe(12))
    await Promise.resolve(); await Promise.resolve()
    expect(leer).toHaveBeenCalledTimes(2)
    pendientes[1].ok(snapDe(13))
    expect((await pregunta).summary.open_positions_count).toBe(13)
  })

  it('si la relectura falla, la pregunta sale con la anterior (antes fallaba entera)', async () => {
    const { leer, pendientes } = pedidoControlado()
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|' })
    const a = l.traer(); pendientes[0].ok(snapDe(12)); await a
    l.invalidar()
    const pregunta = l.paraPreguntar()
    pendientes[1].mal(new Error('502'))
    expect((await pregunta).summary.open_positions_count).toBe(12)
  })

  it('sin anterior, el error de la lectura sí llega a la pregunta', async () => {
    const { leer, pendientes } = pedidoControlado()
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|' })
    const pregunta = l.paraPreguntar()
    pendientes[0].mal(new Error('500'))
    await expect(pregunta).rejects.toThrow('500')
  })

  it('escrituras que no paran (una importación por tanda): la pregunta sale igual, con la última que llegó', async () => {
    const { leer, pendientes } = pedidoControlado()
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|' })
    const pregunta = l.paraPreguntar()
    for (let k = 0; k < 10; k++) {                   // cada lectura queda vieja antes de llegar
      await Promise.resolve(); await Promise.resolve()
      if (pendientes[k]) { l.invalidar(); pendientes[k].ok(snapDe(20 + k)) }
    }
    const s = await pregunta
    expect(leer.mock.calls.length).toBeLessThanOrEqual(VUELTAS)
    expect(s.summary.open_positions_count).toBe(20 + VUELTAS - 1)
  })

  it('si la lectura falla de verdad, la pregunta no la reintenta tres veces: sale con la anterior', async () => {
    const { leer, pendientes } = pedidoControlado()
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|' })
    const a = l.traer(); pendientes[0].ok(snapDe(12)); await a
    l.invalidar()
    const pregunta = l.paraPreguntar()
    await Promise.resolve()
    pendientes[1].mal(new Error('502'))
    expect((await pregunta).summary.open_positions_count).toBe(12)
    expect(leer).toHaveBeenCalledTimes(2)            // una relectura, no tres
  })

  it('el asesor vuelve al libro mientras la pregunta espera: se corta, sin leer para el libro', async () => {
    let quien = 'a@x|101'
    const { leer, pendientes } = pedidoControlado()
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => quien })
    const pregunta = l.paraPreguntar()
    quien = 'a@x|'                                   // volvió al libro
    l.invalidar()
    pendientes[0].ok(snapDe(7))
    await expect(pregunta).rejects.toMatchObject({ detail: CAMBIO_DE_PERSONA })
    expect(leer).toHaveBeenCalledTimes(1)            // nada leído para el libro
  })

  it('el asesor pasa del cliente A al B mientras la pregunta espera: se corta (no sale la foto de A con el encabezado de B)', async () => {
    let quien = 'a@x|101'
    const { leer, pendientes } = pedidoControlado()
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => quien })
    const pregunta = l.paraPreguntar()
    quien = 'a@x|202'
    pendientes[0].ok(snapDe(7))                      // la de A llega igual
    await expect(pregunta).rejects.toMatchObject({ detail: CAMBIO_DE_PERSONA })
  })

  it('lo que queda viejo se cancela (sus 4 pedidos), no sólo se ignora', () => {
    const señales = []
    const leer = vi.fn((alLlegar, signal) => { señales.push(signal); return new Promise(() => {}) })
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|' })
    l.traer()
    expect(señales[0].aborted).toBe(false)
    l.invalidar()
    expect(señales[0].aborted).toBe(true)
  })

  it('escrituras seguidas: espera la pausa y lee UNA vez (antes, una lectura completa por escritura)', async () => {
    let t = 0
    const pausas = []
    const { leer, pendientes } = pedidoControlado()
    const l = crearLecturaDeCartera({ leer, deQuien: () => 'u1|', ahora: () => t,
      esperar: (ms) => new Promise((r) => pausas.push({ ms, r })) })
    const a = l.traer(); pendientes[0].ok(snapDe(12)); await a      // la primera, sin pausa
    for (let k = 0; k < 10; k++) {                  // el cambio de mes: PUT + POST por broker
      t += 50
      l.invalidar()
      l.traer()                                      // la isla, por el aviso
    }
    for (const p of pausas) p.r()
    await Promise.resolve(); await Promise.resolve()
    expect(pausas[0].ms).toBe(PAUSA_TRAS_CAMBIO_MS)
    expect(leer).toHaveBeenCalledTimes(2)            // la primera + una sola relectura
  })

  it('una lectura que no vuelve se corta al tope y lo dice (antes colgaba todas las preguntas)', async () => {
    let cortar
    const { leer } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|', alCambiar: (e) => estados.push(e),
      programar: (fn) => { cortar = fn; return () => {} } })
    const leerDe = vi.fn((alLlegar, signal) => new Promise((ok, mal) => signal.addEventListener('abort', () => {
      const e = new Error('abortado'); e.name = 'AbortError'; mal(e) })))
    leer.mockImplementation(leerDe)
    const pregunta = l.paraPreguntar()
    cortar()                                         // pasaron TOPE_MS
    await expect(pregunta).rejects.toMatchObject({ detail: expect.stringMatching(/tardó demasiado/) })
    expect(estados.at(-1).estado).toBe('error')
  })

  it('vence a los 5 minutos: se relee (con la anterior a la vista), pero la pregunta no espera', async () => {
    let t = 0
    const { leer, pendientes } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => 'u1|', alCambiar: (e) => estados.push(sinSnap(e)), ahora: () => t })
    const a = l.traer(); pendientes[0].ok(snapDe(12)); await a
    t = VIGENCIA_MS - 1
    await l.traer()
    expect(leer).toHaveBeenCalledTimes(1)
    t = VIGENCIA_MS
    l.traer()
    expect(leer).toHaveBeenCalledTimes(2)
    expect(estados.at(-1)).toEqual({ estado: 'leyendo', llego: {}, snap: 12 })
    expect((await l.paraPreguntar()).summary.open_positions_count).toBe(12)   // la pregunta sale ya
    expect(leer).toHaveBeenCalledTimes(2)
    pendientes[1].ok(snapDe(14))
  })
})

// ─── Los cuatro pedidos, cada uno avisando al volver ─────────────────────────
describe('fetchAiSnapshot — avisa cada pedido en el orden en que vuelve', () => {
  const DATOS = {
    '/positions': [{ asset: 'AAPL' }, { asset: 'GGAL' }, { asset: 'USD', is_cash: true }],
    '/monthly': [
      { year: 2026, month: 8, broker: 'global' }, { year: 2026, month: 8, broker: 'IOL' },
      { year: 2026, month: 9, broker: 'global' }, { year: 2026, month: 9, broker: 'IOL' },
    ],
    '/brokers': [{ id: 1 }, { id: 2 }, { id: 3 }],
    '/operations': Array.from({ length: 140 }, (_, i) => ({ id: i })),
  }
  const DEMORA = { '/brokers': 1, '/positions': 3, '/monthly': 5, '/operations': 8 }
  afterEach(() => vi.restoreAllMocks())

  it('se tildan en el orden de llegada, no en el de la lista', async () => {
    vi.spyOn(api, 'get').mockImplementation((path) =>
      new Promise((ok) => setTimeout(() => ok(DATOS[path]), DEMORA[path])))
    const orden = []
    const llego = {}
    const snap = await fetchAiSnapshot({ alLlegar: ({ pieza, dato }) => { orden.push(pieza); llego[pieza] = dato } })
    expect(orden).toEqual(['brokers', 'positions', 'monthly', 'operations'])
    // El renglón del cargador dice lo que se va a leer…
    const pasos = Object.fromEntries(pasosContextoIA(llego).map(p => [p.id, p.detalle]))
    expect(pasos).toEqual({
      positions: '2 posiciones',                      // sin la línea de efectivo
      monthly: '2 meses',                             // no 4 filas: global + broker
      brokers: '3 brokers',
      operations: 'las 100 más recientes',            // a Mervall-E le llegan 100 de 140
    })
    // …y el número de posiciones es EL MISMO que la cabecera publica arriba.
    expect(resumenDeCartera(snap)).toEqual({ posiciones: 2, brokers: 3 })
  })

  it('sin operaciones el chat sigue, y el renglón lo dice', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path) => {
      if (path === '/operations') throw new Error('502')
      return DATOS[path]
    })
    const llego = {}
    const snap = await fetchAiSnapshot({ alLlegar: ({ pieza, dato, error }) => { llego[pieza] = error ? 'error' : dato } })
    expect(snap.operations).toEqual([])
    const ops = pasosContextoIA(llego).find(p => p.id === 'operations')
    expect(ops).toMatchObject({ estado: 'error', detalle: 'no llegaron: sigo sin ellas' })
  })

  it('si falla lo imprescindible, la lectura falla (y su renglón no queda girando)', async () => {
    vi.spyOn(api, 'get').mockImplementation(async (path) => {
      if (path === '/positions') throw new Error('500')
      return DATOS[path]
    })
    const llego = {}
    await expect(fetchAiSnapshot({ alLlegar: ({ pieza, dato, error }) => { llego[pieza] = error ? 'error' : dato } }))
      .rejects.toThrow('500')
    expect(pasosContextoIA(llego).find(p => p.id === 'positions').estado).toBe('error')
  })
})

// ─── Cualquier escritura deja vieja la lectura ───────────────────────────────
// `rendi:portfolio-changed` lo emiten el importador y el chat; las altas a mano
// (una operación, un broker, un movimiento de caja) no. El aviso sale de
// utils/api, por donde pasan todas.
describe('utils/api avisa cada escritura que sale bien', () => {
  let avisos
  beforeEach(() => {
    globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} }
    const w = new EventTarget()
    w.location = { href: '' }
    globalThis.window = w
    avisos = 0
    w.addEventListener(EVENTO_ESCRITURA, () => { avisos++ })
  })
  afterEach(() => {
    vi.restoreAllMocks()
    delete globalThis.localStorage
    delete globalThis.window
  })
  const responde = (status, cuerpo = {}) => vi.fn(async () => ({
    status, ok: status < 400, json: async () => cuerpo, text: async () => JSON.stringify(cuerpo),
    headers: { get: () => 'application/json' },
  }))

  it('POST, PUT y DELETE que salen bien: avisan', async () => {
    globalThis.fetch = responde(200, { ok: true })
    await api.post('/operations', { asset: 'AAPL' })
    await api.put('/operations/3', {})
    await api.delete('/operations/3')
    expect(avisos).toBe(3)
  })

  it('pedir el audio de una respuesta (/ai/voz) NO avisa: no toca la cartera', async () => {
    // Sin esto, cada respuesta hablada tiraba la lectura y salían otra vez
    // los 4 pedidos (auditoría 2026-10-05).
    globalThis.fetch = responde(200, { url: 'https://x/a.mp3' })
    await api.post('/ai/voz', { text: 'hola', sig: 'x' })
    await api.post('/watchlist', { symbol: 'AAPL' })
    await api.post('/alerts/events/seen', {})
    expect(avisos).toBe(0)
  })

  it('una lectura no avisa, y una escritura que falla tampoco', async () => {
    globalThis.fetch = responde(200, [])
    await api.get('/positions')
    globalThis.fetch = responde(422, { detail: 'mal' })
    await expect(api.post('/operations', {})).rejects.toBeTruthy()
    expect(avisos).toBe(0)
  })
})

describe('escrituraTocaLaCartera — qué escrituras dejan vieja la lectura', () => {
  it('lo que cambia posiciones, historial, brokers u operaciones: sí', () => {
    for (const p of ['/operations', '/operations/3', '/positions/sell', '/brokers/2?force=true', '/cash/flow',
      '/monthly/7', '/imports/confirm', '/plazos-fijos/4/cobrar', '/advisor/group-op/9/undo', '/wallbit/sync',
      // Las dos que una lista de prefijos anchos ('/me', '/sections') se comía:
      '/me/reset-data', '/sections/restore',
      // Editar un mes sí (la de arriba es una ruta exacta, no un prefijo):
      '/monthly', '/monthly/7']) {
      expect(escrituraTocaLaCartera(p), p).toBe(true)
    }
  })
  it('lo que no: no (la IA, avisos, la watchlist, la sesión, el plan)', () => {
    for (const p of ['/ai/voz', '/ai/analyze', '/fundamentals/ai-summary', '/alerts/events/seen', '/push/subscribe',
      '/watchlist', '/watchlist/AAPL', '/auth/logout', '/plan/track', '/billing/subscribe', '/me/advisor/3/revoke',
      '/me/advisor/requests/4/respond', '/auth/investor-profile', '/market-brief/prefs',
      // La valuación a precio de hoy que el Dashboard guarda cada 90 s:
      '/monthly/sync-unrealized', '/snapshots',
      '/goals/2', '/diagnostics/dismiss', '/feedback']) {
      expect(escrituraTocaLaCartera(p), p).toBe(false)
    }
  })
  it('un prefijo no se confunde con otra ruta que empieza igual', () => {
    expect(escrituraTocaLaCartera('/aiuda')).toBe(true)
    expect(escrituraTocaLaCartera('/merit')).toBe(true)
  })
})

// (El aviso de "cambió el cliente" lo prueba contexts/fotoDeOtraCuenta.test.js:
// es EVENTO_CUENTA_CAMBIADA de utils/api, el mismo que sigue esta lectura.)

// ─── De quién es la lectura: con lo que de verdad trae el usuario ────────────
// La auditoría lo encontró: la clave se armaba con `user.id`, que la app no
// tiene (mapMeToUser no lo copia) — la clave era la misma para todos, y quien
// entraba después en la misma pestaña veía la cartera del anterior. Esta prueba
// arma la clave con el usuario que arma AuthContext, no con un texto fijo.
describe('claveDePersona — con el usuario real de la app', () => {
  const ana = mapMeToUser({ id: 1, email: 'ana@x.com', name: 'Ana', tier: 'pro' })
  const beto = mapMeToUser({ id: 2, email: 'beto@x.com', name: 'Beto', tier: 'pro' })
  it('dos personas, dos claves; el mismo asesor en dos clientes, dos claves', () => {
    expect(claveDePersona(ana, null)).not.toBe(claveDePersona(beto, null))
    expect(claveDePersona(ana, 101)).not.toBe(claveDePersona(ana, 202))
  })
  it('el email tipeado al entrar ("Ana@X.com ") y el de /auth/me son la misma persona', () => {
    expect(claveDePersona({ email: ' Ana@X.com ' }, null)).toBe(claveDePersona(ana, null))
  })
  it('Ana cierra sesión y entra Beto en la misma pestaña: Beto no ve la de Ana', async () => {
    let usuario = ana
    const { leer, pendientes } = pedidoControlado()
    const estados = []
    const l = crearLecturaDeCartera({ ...RAPIDO, leer, deQuien: () => claveDePersona(usuario, null), alCambiar: (e) => estados.push(sinSnap(e)) })
    const a = l.traer(); pendientes[0].ok(snapDe(12)); await a
    usuario = beto
    l.olvidar()                                      // VozContext lo hace al cambiar el email
    expect(estados.at(-1)).toBe(null)
    const b = l.paraPreguntar()
    expect(leer).toHaveBeenCalledTimes(2)
    expect(estados.at(-1)).toEqual({ estado: 'leyendo', llego: {}, snap: null })   // nada de Ana a la vista
    pendientes[1].ok(snapDe(3))
    expect((await b).summary.open_positions_count).toBe(3)
  })
})
