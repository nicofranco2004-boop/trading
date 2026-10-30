// Lo que la pantalla MANDA al servidor con números de una cuenta, con DOS
// PESTAÑAS — re-test a ciegas 3 (30/10), traído al repo y ampliado al resumen
// mensual (Mensual), que el auditor no montó.
//
// La APP ENTERA (App, rutas, AuthContext, AdvisorContext, api.js) con un
// servidor simulado (fetch) que sirve la cartera del demo multiplicada por
// cuenta y ANOTA a nombre de quién llega cada pedido: la cookie de quien esté
// logueado en ese momento, o el cliente del encabezado X-Rendi-Client-Id. El
// cambio de otra pestaña es el evento `storage` del navegador.
//
// Lo que rompía (pasa hoy en producción): el inicio del cliente 2 abierto, otra
// pestaña entra al 3, y la pestaña vieja mandaba cada 90 s la ganancia no
// realizada del 2 a nombre del 3 (/monthly/sync-unrealized): el servidor pisaba
// el mes en curso y el capital final del 3 (5.010 donde el real era 20.043). Lo
// mismo entre Ana y Bruno, y el resumen mensual con su carga. Ahora todo envío
// automático con números de una cuenta sale por utils/enviosConDueno.enviarDe,
// que no lo manda si el dueño de los datos ya no es el de la pestaña.
import { describe, it, expect, beforeAll, vi } from 'vitest'
import { createElement as h } from 'react'
import { appendFileSync } from 'node:fs'
import { prepararApp, estado, respuestaEscalada, textoConCortes, cargando } from '../testing/pantallaConOjito'
import { montar, enActo, buscarBoton, clic, texto, otraPestanaEscribe } from '../testing/navegadorMinimo'

vi.mock('../components/ai/mervalle/motor', async (io) => ({
  ...(await io()), crearMervallE: () => new Proxy({}, { get: () => () => {} }),
}))

// Para mirar qué pasó: RETEST_LOG=/ruta npx vitest run … deja lo que se vio.
const log = (...a) => { if (process.env.RETEST_LOG) appendFileSync(process.env.RETEST_LOG, a.map(x => typeof x === 'string' ? x : JSON.stringify(x)).join(' ') + '\n') }

let App, HelmetProvider, ToastProvider, MemoryRouter, api, handleDemoRequest, AdvisorImportsMod
// Cuánta plata tiene cada cuenta (multiplica la cartera del demo).
const FACTOR = { c2: 1, c3: 4, ana: 1, bruno: 7, asesora: 1, asesorb: 1 }
const servidor = { me: null, vencida: false, demora: 0, pedidos: [] }
const cuentaDe = (cid) => (cid != null ? `c${cid}` : servidor.me?.quien)
const intervalos = []

beforeAll(async () => {
  await prepararApp({ ancho: 1280 })
  // Para disparar a mano el refresco de 90 s del inicio.
  const orig = globalThis.setInterval
  const envuelto = (fn, ms, ...r) => { const id = orig(fn, ms, ...r); if (ms === 90_000) intervalos.push(fn); return id }
  vi.stubGlobal('setInterval', envuelto); window.setInterval = envuelto
  ;({ default: App } = await import('../App'))
  ;({ HelmetProvider } = await import('react-helmet-async'))
  ;({ ToastProvider } = await import('../components/Toast'))
  ;({ MemoryRouter } = await import('react-router-dom'))
  api = await import('../utils/api')
  ;({ handleDemoRequest } = await import('../utils/demo'))
  AdvisorImportsMod = await import('../pages/AdvisorImports')
  vi.stubGlobal('fetch', async (url, opts = {}) => {
    const method = opts.method || 'GET'
    const path = String(url).replace(/^\/api/, '')
    const cid = opts.headers?.['X-Rendi-Client-Id']
    const cuenta = cuentaDe(cid)          // la cookie es la de quien esté logueado AHORA
    const body = opts.body && typeof opts.body === 'string' ? JSON.parse(opts.body) : undefined
    servidor.pedidos.push({ method, path, cid: cid ?? null, cuenta, body })
    if (servidor.vencida) return new Response('{"detail":"Not authenticated"}', { status: 401, headers: { 'content-type': 'application/json' } })
    if (path.startsWith('/auth/me')) return new Response(JSON.stringify(servidor.me), { status: 200, headers: { 'content-type': 'application/json' } })
    estado.factor = FACTOR[cuenta] ?? 1
    let r = respuestaEscalada(handleDemoRequest, method, path, body)
    if (r == null || r.__demoBlocked) r = method === 'GET' ? {} : { ok: true }
    const txt = JSON.stringify(r)
    if (servidor.demora && method === 'GET') await new Promise(res => setTimeout(res, servidor.demora))
    return new Response(txt, { status: 200, headers: { 'content-type': 'application/json' } })
  })
}, 240000)

const esperar = (ms) => new Promise(r => setTimeout(r, ms))
const el = (ruta) => h(HelmetProvider, null, h(ToastProvider, null, h(MemoryRouter, { initialEntries: [ruta] }, h(App))))
let m = null
async function quieta(rehacer, { vistas } = {}) {
  let antes = null, q = 0
  for (let i = 0; i < 250 && (i < 10 || q < 8); i++) {
    await esperar(60)
    if (rehacer) await m.redibujar(rehacer())
    const t = textoConCortes(m.contenedor)
    if (vistas) vistas.push(t)
    q = (t === antes && !cargando(m.contenedor)) ? q + 1 : 0
    antes = t
  }
  return textoConCortes(m.contenedor).replace(/\s+/g, ' ')
}
async function abrir(ruta, opc) {
  if (m) await m.desmontar()
  m = await montar(el(ruta))
  return quieta(() => el(ruta), opc)
}
const persona = (quien, tier = 'pro') => {
  const email = `${quien}@retest.test`
  servidor.me = { quien, name: quien, email, tier }
  localStorage.setItem('rendi_user', JSON.stringify({ name: quien, email, tier }))
}
const vencer = async () => {
  servidor.vencida = true
  await enActo(async () => { await api.api.get('/positions').catch(() => {}) })
  servidor.vencida = false
  log('    tras el 401 → rendi_user =', localStorage.getItem('rendi_user'), '| location =', window.location.href)
}
const limpio = () => {
  if (m) { /* se desmonta en abrir */ }
  localStorage.clear(); sessionStorage.clear(); api.setClientContext(null)
  servidor.vencida = false; servidor.demora = 0; servidor.pedidos = []
  localStorage.setItem('rendi:tour:novedades:v2', '1'); localStorage.setItem('rendi_display_currency', 'USD')
}
const desde = (t) => { const i = t.indexOf('Desde tu última visita'); return i < 0 ? '(no aparece)' : t.slice(i, i + 80) }
const tarjetas = () => {
  const out = []; const pila = [m.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && texto(n).includes('No me interesa')) {
      let c = n; for (let k = 0; k < 4 && c.parentNode; k++) c = c.parentNode
      out.push(texto(c).replace('No me interesa', '').slice(0, 50))
    } else pila.push(...(n.childNodes || []))
  }
  return out
}
const posts = (p) => servidor.pedidos.filter(x => x.method === 'POST' && x.path.startsWith(p))
const resumenPosts = (p) => posts(p).map(x => `${x.path} cuenta=${x.cuenta} ${JSON.stringify(x.body)}`.slice(0, 160))
const guardado = () => [
  ...Object.keys(Object.fromEntries(Array.from({ length: localStorage.length }, (_, i) => [localStorage.key(i), 1]))).map(k => `L ${k}`),
  ...Array.from({ length: sessionStorage.length }, (_, i) => `S ${sessionStorage.key(i)}`),
].filter(k => /lastvisit|diag_dismissed|snapshot|valor_visto|version_cartera|ultimo_total|tanda/.test(k))

describe('lo que se manda al servidor con dos pestañas', () => {
  const tick90 = async () => { for (const fn of intervalos.splice(0)) await enActo(async () => { fn() }) }
  const largo = async (ms) => { for (let t = 0; t < ms; t += 200) { await esperar(200); await m.redibujar(el('/dashboard')) } }
  const glob = (lista) => lista.filter(x => x.body?.broker === 'global').map(x => `${x.cuenta} ${x.body.pnl_unrealized_usd}`)

  it('S6a-1 dos pestañas: inicio del cliente 2 CARGANDO; otra pestaña entra al cliente 3', async () => {
    log('\n[S6a-1] ────────'); limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    servidor.demora = 1500; intervalos.length = 0
    if (m) await m.desmontar()
    m = await montar(el('/dashboard'))
    await esperar(300)
    await enActo(async () => otraPestanaEscribe('rendi_client_ctx', JSON.stringify({ id: 3, label: 'Tres' })))
    await largo(8000)
    servidor.demora = 0
    log('  pedidos GET de datos:', servidor.pedidos.filter(x => x.method === 'GET' && /^\/(positions|prices)/.test(x.path)).map(x => `${x.path.slice(0, 18)} ${x.cuenta}`))
    log('  POST /snapshots:', resumenPosts('/snapshots'))
    log('  POST sync-unrealized global:', glob(posts('/monthly/sync-unrealized')))
    expect(posts('/snapshots').filter(x => x.cuenta === 'c3').length, 'foto del cliente 2 a nombre del 3').toBe(0)
    expect(posts('/monthly/sync-unrealized').filter(x => x.cuenta === 'c3').length, 'P&L del 2 a nombre del 3').toBe(0)
  }, 500000)

  it('S6a-2 dos pestañas: inicio del cliente 2 QUIETO; otra pestaña entra al 3; pasa el refresco de 90 s', async () => {
    log('\n[S6a-2] ────────'); limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' }); intervalos.length = 0
    if (m) await m.desmontar()
    m = await montar(el('/dashboard')); await largo(5000)
    const n0 = servidor.pedidos.length
    log('  al cargar (cliente 2): snapshots', resumenPosts('/snapshots').length, '| sync global', glob(posts('/monthly/sync-unrealized')))
    await enActo(async () => otraPestanaEscribe('rendi_client_ctx', JSON.stringify({ id: 3, label: 'Tres' })))
    await tick90(); await largo(4000)
    const nuevos = servidor.pedidos.slice(n0)
    const sn = nuevos.filter(x => x.method === 'POST' && x.path.startsWith('/snapshots'))
    const sy = nuevos.filter(x => x.method === 'POST' && x.path.startsWith('/monthly/sync-unrealized'))
    log('  tras el refresco: snapshots', sn.map(x => x.cuenta), '| sync global', glob(sy), '| brokers', sy.map(x => `${x.cuenta}:${x.body?.broker}`))
    // Control: el P&L global de verdad del cliente 3.
    const pc = servidor.pedidos.length
    api.setClientContext({ id: 3, label: 'Tres' }); await abrir('/dashboard')
    log('  control: P&L global real del cliente 3 =', glob(servidor.pedidos.slice(pc).filter(x => x.method === 'POST' && x.path.startsWith('/monthly/sync-unrealized'))))
    expect(sn.filter(x => x.cuenta === 'c3').length, 'foto del 2 a nombre del 3').toBe(0)
    expect(sy.filter(x => x.cuenta === 'c3').length, 'P&L del 2 a nombre del 3').toBe(0)
  }, 500000)

  it('S6b dos pestañas: inicio de Ana QUIETO; en otra pestaña entra Bruno; el refresco cae antes de la recarga', async () => {
    log('\n[S6b] ──────────'); limpio(); persona('ana'); intervalos.length = 0
    if (m) await m.desmontar()
    m = await montar(el('/dashboard')); await largo(5000)
    // Ana todavía no tenía la foto de hoy (p. ej. el primer intento dio 5xx y la pestaña sigue): se la saca para ver qué se manda.
    for (const k of Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))) if (k.startsWith('rendi_snapshot_date')) localStorage.removeItem(k)
    const n0 = servidor.pedidos.length
    servidor.me = { quien: 'bruno', name: 'bruno', email: 'bruno@retest.test', tier: 'pro' }   // la cookie ya es de Bruno
    window.location.reload.mockClear?.()
    await enActo(async () => otraPestanaEscribe('rendi_user', JSON.stringify({ name: 'bruno', email: 'bruno@retest.test', tier: 'pro' })))
    await tick90()                                  // dentro de los 300 ms antes de que AuthContext recargue
    await largo(1500)
    const nuevos = servidor.pedidos.slice(n0)
    log('  recarga pedida por AuthContext:', window.location.reload.mock?.calls?.length)
    log('  POST tras el cambio:', nuevos.filter(x => x.method === 'POST').map(x => `${x.path} ${x.cuenta} ${x.body?.broker ?? ''} ${x.body?.pnl_unrealized_usd ?? x.body?.total_value ?? ''}`))
    expect(nuevos.filter(x => x.method === 'POST' && x.path.startsWith('/snapshots') && x.cuenta === 'bruno').length, 'foto de Ana a nombre de Bruno').toBe(0)
    expect(nuevos.filter(x => x.method === 'POST' && x.path.startsWith('/monthly/sync') && x.cuenta === 'bruno').length, 'P&L de Ana a nombre de Bruno').toBe(0)
  }, 500000)

  it('Mensual del cliente 2 CARGANDO; otra pestaña entra al cliente 3: nada del 2 llega al 3', async () => {
    log('\n[Mensual] ──────'); limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    servidor.demora = 1500
    if (m) await m.desmontar()
    m = await montar(el('/mensual'))
    await esperar(300)
    await enActo(async () => otraPestanaEscribe('rendi_client_ctx', JSON.stringify({ id: 3, label: 'Tres' })))
    for (let t = 0; t < 8000; t += 200) { await esperar(200); await m.redibujar(el('/mensual')) }
    servidor.demora = 0
    const escrituras = servidor.pedidos.filter(x => x.method !== 'GET' && x.path.startsWith('/monthly'))
    log('  escrituras a /monthly:', escrituras.map(x => `${x.method} ${x.path} ${x.cuenta} ${x.body?.broker ?? ''}`))
    expect(escrituras.filter(x => x.cuenta === 'c3'), 'números del 2 a nombre del 3').toEqual([])
  }, 500000)

  it('Mensual del cliente 2 QUIETO; otra pestaña entra al 3; la persona toca «Cerrar mes» y «Abrir»: nada del 2 llega al 3', async () => {
    log('\n[Mensual clic] ──────'); limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir('/mensual')
    await enActo(async () => otraPestanaEscribe('rendi_client_ctx', JSON.stringify({ id: 3, label: 'Tres' })))
    servidor.pedidos = []
    const cerrar = buscarBoton(m.contenedor, 'Cerrar mes')
    expect(cerrar, 'botón «Cerrar mes»').toBeTruthy()
    await enActo(() => clic(m.contenedor, cerrar))
    await quieta(() => el('/mensual'))
    const abrirMes = buscarBoton(m.contenedor, 'Abrir ')
    expect(abrirMes, 'botón «Abrir <mes>» del cierre').toBeTruthy()
    await enActo(() => clic(m.contenedor, abrirMes))
    await quieta(() => el('/mensual'))
    const escrituras = servidor.pedidos.filter(x => x.method !== 'GET' && x.path.startsWith('/monthly'))
    log('  escrituras a /monthly tras el clic:', escrituras.map(x => `${x.method} ${x.path} ${x.cuenta} ${x.body?.broker ?? ''} ${x.body?.capital_final ?? ''}`))
    expect(escrituras.filter(x => x.cuenta === 'c3'), 'el cierre del 2 a nombre del 3').toEqual([])
    expect(texto(m.contenedor), 'la persona se entera de por qué no se guardó').toMatch(/se cambió de cuenta/)
  }, 500000)
})
