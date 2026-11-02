// «Desde tu última visita» y las tarjetas descartadas de Análisis, con DOS
// PESTAÑAS — la prueba del re-test a ciegas 2 (30/10), traída al repo.
//
// La pantalla Análisis DE VERDAD (App entera, rutas, AuthContext,
// AdvisorContext, api.js), con un servidor simulado (fetch) que sirve la
// cartera del demo multiplicada según la cuenta pedida:
//   cliente 2 ×1 · cliente 3 ×2 · Ana ×1 · Bruno ×3.
// Lo único simulado es el servidor. La sesión que vence es un 401 que pasa por
// api.js; el cambio de cliente es setClientContext de api.js (lo que llama
// AdvisorContext.enterClient) o el evento `storage` de otra pestaña.
//
// Lo que rompía (S1b, S3b): con la pantalla abierta, otra pestaña cambiaba de
// cliente o de persona, y lo que la pantalla guardaba a continuación iba a
// nombre del dueño NUEVO con los números del VIEJO (la plata de Ana a nombre de
// Bruno, que después veía «+200 %»). El dueño se decidía al guardar, mirando la
// pestaña; ahora viaja con los datos (utils/duenoDeLaPestana.useDuenoDeLosDatos)
// y la puerta (utils/almacen.guardarDe) no guarda para un dueño que ya no es el
// de la pestaña.
import { describe, it, expect, beforeAll, vi } from 'vitest'
import { createElement as h } from 'react'
import { CLAVES_DE_LOS_TOURS } from '../components/tour/recorrido'
import { prepararApp, estado, respuestaEscalada, textoConCortes, cargando } from '../testing/pantallaConOjito'
import { montar, enActo, buscarBoton, clic, texto, otraPestanaEscribe } from '../testing/navegadorMinimo'

vi.mock('../components/ai/mervalle/motor', async (io) => ({
  ...(await io()), crearMervallE: () => new Proxy({}, { get: () => () => {} }),
}))

let App, HelmetProvider, ToastProvider, MemoryRouter, api, handleDemoRequest
const servidor = { me: null, vencida: false, pedidos: [] }
const FACTOR = { cliente2: 1, cliente3: 2, ana: 1, bruno: 3, asesora: 5 }
function factorDe(cid) {
  if (cid === '2' || cid === 2) return FACTOR.cliente2
  if (cid === '3' || cid === 3) return FACTOR.cliente3
  return FACTOR[servidor.me?.quien] ?? 1
}

beforeAll(async () => {
  await prepararApp({ ancho: 1280 })
  ;({ default: App } = await import('../App'))
  ;({ HelmetProvider } = await import('react-helmet-async'))
  ;({ ToastProvider } = await import('../components/Toast'))
  ;({ MemoryRouter } = await import('react-router-dom'))
  api = await import('../utils/api')
  ;({ handleDemoRequest } = await import('../utils/demo'))
  vi.stubGlobal('fetch', async (url, opts = {}) => {
    const method = opts.method || 'GET'
    const path = String(url).replace(/^\/api/, '')
    const cid = opts.headers?.['X-Rendi-Client-Id']
    servidor.pedidos.push(`${method} ${path} cid=${cid ?? '-'}`)
    if (servidor.vencida) return new Response(JSON.stringify({ detail: 'Not authenticated' }), { status: 401, headers: { 'content-type': 'application/json' } })
    if (path.startsWith('/auth/me')) return new Response(JSON.stringify(servidor.me), { status: 200, headers: { 'content-type': 'application/json' } })
    estado.factor = factorDe(cid)
    let r = respuestaEscalada(handleDemoRequest, method, path, opts.body ? JSON.parse(opts.body) : undefined)
    if (r == null || r.__demoBlocked) r = method === 'GET' ? {} : { ok: true }
    return new Response(JSON.stringify(r), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}, 180000)

// Para mirar qué pasó: RETEST_LOG=/ruta npx vitest run … deja lo que se vio.
import { appendFileSync } from 'node:fs'
const log = (...a) => { if (process.env.RETEST_LOG) appendFileSync(process.env.RETEST_LOG, a.map(x => typeof x === 'string' ? x : JSON.stringify(x, null, 1)).join(' ') + '\n') }
const esperar = (ms) => new Promise(r => setTimeout(r, ms))
const el = (ruta) => h(HelmetProvider, null, h(ToastProvider, null, h(MemoryRouter, { initialEntries: [ruta] }, h(App))))
let montado = null
async function quieta(m, rehacer) {
  let antes = null, quietas = 0
  for (let i = 0; i < 200 && (i < 10 || quietas < 8); i++) {
    await esperar(60)
    if (rehacer) await m.redibujar(rehacer())
    const t = textoConCortes(m.contenedor)
    quietas = (t === antes && !cargando(m.contenedor)) ? quietas + 1 : 0
    antes = t
  }
  return textoConCortes(m.contenedor).replace(/\s+/g, ' ')
}
async function abrirAnalisis() {
  if (montado) await montado.desmontar()
  montado = await montar(el('/analisis?tab=diagnostico'))
  return quieta(montado, () => el('/analisis?tab=diagnostico'))
}
const persona = (quien, email, tier = 'pro') => {
  servidor.me = { quien, name: quien, email, tier }
  localStorage.setItem('rendi_user', JSON.stringify({ name: quien, email, tier }))   // lo que deja AuthContext.login
}
const desde = (t) => { const i = t.indexOf('Desde tu última visita'); return i < 0 ? '(no aparece el bloque)' : t.slice(i, i + 90) }
const tarjetas = (m) => {
  const out = []
  const pila = [m.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && texto(n).includes('No me interesa')) {
      let c = n; for (let k = 0; k < 4 && c.parentNode; k++) c = c.parentNode
      out.push(texto(c).replace('No me interesa', '').slice(0, 60))
    } else pila.push(...(n.childNodes || []))
  }
  return out
}
const claves = () => Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))
  .filter(k => /lastvisit|diag_dismissed/.test(k)).map(k => `${k} = ${localStorage.getItem(k).slice(0, 80)}`)
const limpio = () => { localStorage.clear(); sessionStorage.clear(); api.setClientContext(null); servidor.vencida = false
  for (const k of CLAVES_DE_LOS_TOURS) localStorage.setItem(k, '1'); localStorage.setItem('rendi_display_currency', 'USD') }

describe('Análisis: de quién es lo que la pestaña recuerda', () => {
  it('síntoma 1 — el asesor mira el cliente 2 y después el 3', async () => {
    limpio(); persona('asesora', 'asesora@prueba.test', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    const t2 = await abrirAnalisis()
    log('[S1] cliente 2, 1ra visita →', desde(t2))
    api.setClientContext({ id: 3, label: 'Tres' })          // lo que hace AdvisorContext.enterClient
    const t3 = await abrirAnalisis()
    log('[S1] cliente 3, 1ra visita →', desde(t3))
    log('[S1] guardado:', claves())
    expect(desde(t3), 'el cliente 3 en su primera visita no tiene que compararse con el 2').toBe('(no aparece el bloque)')
  }, 300000)

  it('síntoma 1b — pantalla ya abierta en el cliente 2 y OTRA pestaña entra al cliente 3', async () => {
    limpio(); persona('asesora', 'asesora@prueba.test', 'advisor')
    // Primera visita del cliente 3 (su valor de verdad, ×2) y del 2.
    api.setClientContext({ id: 3, label: 'Tres' }); await abrirAnalisis()
    api.setClientContext({ id: 2, label: 'Dos' }); await abrirAnalisis()
    const antes = claves()
    // Con Análisis del cliente 2 abierto, otra pestaña entra al cliente 3.
    await enActo(async () => otraPestanaEscribe('rendi_client_ctx', JSON.stringify({ id: 3, label: 'Tres' })))
    const t = await quieta(montado, () => el('/analisis?tab=diagnostico'))
    log('[S1b] antes  :', antes)
    log('[S1b] después:', claves())
    log('[S1b] pestaña vieja →', desde(t))
    // La pestaña vieja ya no adopta el 3: sigue con el 2 (cada pestaña con
    // su cliente, re-test a ciegas 3 y 4). El 3 se abre de nuevo —en la otra
    // pestaña, o en ésta entrando al 3—: otra visita, montaje limpio.
    expect(api.getClientContext()?.id).toBe(2)
    api.setClientContext({ id: 3, label: 'Tres' })
    const t3 = await abrirAnalisis()
    log('[S1b] cliente 3, visita siguiente →', desde(t3))
    expect(desde(t3), 'el cliente 3 contra sí mismo: 0 %').toMatch(/Tu cartera: (\+?0(,0)? ?%|0,0 %)/)
  }, 300000)

  it('síntoma 2 — descarta una tarjeta en el cliente 2; en el 3 sigue', async () => {
    limpio(); persona('asesora', 'asesora@prueba.test', 'advisor')
    api.setClientContext({ id: 3, label: 'Tres' })
    await abrirAnalisis()
    const control3 = tarjetas(montado)
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrirAnalisis()
    const antes2 = tarjetas(montado)
    const btn = buscarBoton(montado.contenedor, 'No me interesa')
    expect(btn, 'no hay botón «No me interesa»').toBeTruthy()
    await enActo(async () => clic(montado.contenedor, btn))
    await quieta(montado)
    const despues2 = tarjetas(montado)
    api.setClientContext({ id: 3, label: 'Tres' })
    await abrirAnalisis()
    const en3 = tarjetas(montado)
    log('[S2] cliente 3 sin tocar:', control3)
    log('[S2] cliente 2 antes   :', antes2)
    log('[S2] cliente 2 después :', despues2)
    log('[S2] cliente 3 luego   :', en3)
    log('[S2] guardado:', claves())
    expect(despues2).not.toEqual(antes2)
    expect(en3).toEqual(control3)
  }, 300000)

  it('síntoma 3 — a Ana se le vence la sesión (401) y entra Bruno', async () => {
    limpio(); persona('ana', 'ana@prueba.test')
    await abrirAnalisis()
    const b = buscarBoton(montado.contenedor, 'No me interesa')
    if (b) { await enActo(async () => clic(montado.contenedor, b)); await quieta(montado) }
    const tarjAna = tarjetas(montado)
    servidor.vencida = true
    await enActo(async () => { await api.api.get('/positions').catch(e => log('[S3] api.js →', e.status, e.message)) })
    log('[S3] rendi_user tras el 401:', localStorage.getItem('rendi_user'), '· location:', window.location.href)
    await montado.desmontar(); montado = null
    servidor.vencida = false
    persona('bruno', 'bruno@prueba.test')
    const tB = await abrirAnalisis()
    const tarjBruno = tarjetas(montado)
    // control: Bruno en un navegador limpio
    const guard = claves()
    limpio(); persona('bruno', 'bruno@prueba.test')
    await abrirAnalisis()
    const controlB = tarjetas(montado)
    log('[S3] Bruno →', desde(tB))
    log('[S3] Ana tarjetas  :', tarjAna)
    log('[S3] Bruno tarjetas:', tarjBruno)
    log('[S3] Bruno limpio  :', controlB)
    log('[S3] guardado:', guard)
    expect(desde(tB)).toBe('(no aparece el bloque)')
    expect(tarjBruno).toEqual(controlB)
  }, 300000)
  it('síntoma 3b — Análisis de Ana abierto; en OTRA pestaña la sesión pasa a Bruno', async () => {
    limpio(); persona('ana', 'ana@prueba.test')
    await abrirAnalisis()
    window.location.reload.mockClear()
    const antes = claves()
    // Otra pestaña: entra Bruno (rendi_user cambia de Ana a Bruno de una).
    await enActo(async () => otraPestanaEscribe('rendi_user', JSON.stringify({ name: 'bruno', email: 'bruno@prueba.test', tier: 'pro' })))
    await enActo(async () => { await esperar(100) })
    const a100ms = claves()
    await enActo(async () => { await esperar(400) })
    log('[S3b] antes        :', antes)
    log('[S3b] a los 100 ms :', a100ms)
    log('[S3b] recarga pedida por AuthContext:', window.location.reload.mock.calls.length, 'vez/veces')
    servidor.me = { quien: 'bruno', name: 'bruno', email: 'bruno@prueba.test', tier: 'pro' }
    const tB = await abrirAnalisis()          // la página recargada, ya de Bruno
    log('[S3b] Bruno, después de la recarga →', desde(tB))
    expect(desde(tB)).toBe('(no aparece el bloque)')
  }, 300000)
})

