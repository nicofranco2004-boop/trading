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
import { montar, enActo, buscarBoton, clic, texto, otraPestanaEscribe, escribir } from '../testing/navegadorMinimo'

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
  // La recarga de AuthContext acá es de mentira: no limpia la memoria del
  // «cambió la persona» que la de verdad sí tira.
  api.marcarPersonaCambiada?.(false)
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
    // Desde que la pestaña no adopta el cliente de la otra, el cierre ni sale:
    // espera, y la persona ve el cartel que le deja elegir.
    expect(texto(m.contenedor), 'la persona se entera de por qué no se guardó').toMatch(/Cambiaste de cuenta en otra pestaña/)
  }, 500000)
})

// 🔴 LA PESTAÑA VIEJA NO PUEDE MOSTRAR UNA CUENTA Y MANDAR OTRA (re-test 3,
// pedido de la sesión central, 30/10). El freno de enviarDe cubría lo que la
// pantalla manda sola; lo que toca la persona —agregar un mes, registrar una
// compra— salía con el cliente que la pestaña tenía AHORA, mostrando el
// anterior. Ahora, cuando otra pestaña cambia la cuenta, ésta deja de hablar
// con el servidor y lo dice con un cartel hasta que la persona elige.
describe('la pestaña vieja: lo que toca la persona después del cambio', () => {
  const escrituras = (cuenta) => servidor.pedidos.filter(x => x.method !== 'GET' && x.cuenta === cuenta)
  const enLaPagina = (parte) => texto(m.contenedor).includes(parte) || texto(document.body).includes(parte)
  // Los menús y los cuadros van a document.body (createPortal). Un botón se
  // busca por su texto o por su etiqueta (aria-label: el de los tres puntitos).
  function buscarEn(raiz, parte) {
    const pila = [raiz]
    while (pila.length) {
      const n = pila.shift()
      if (n.nodeName === 'BUTTON' && (texto(n).includes(parte) || (n.getAttribute?.('aria-label') || '').includes(parte))) return n
      pila.push(...(n.childNodes || []))
    }
    return null
  }
  const boton = (parte) => buscarEn(m.contenedor, parte) || buscarEn(document.body, parte)
  const tocar = async (parte, ruta) => {
    const b = boton(parte)
    expect(b, `botón «${parte}»`).toBeTruthy()
    const raiz = buscarEn(m.contenedor, parte) ? m.contenedor : document.body
    await enActo(() => clic(raiz, b))
    await quieta(() => el(ruta))
  }
  function campo(etiqueta) {
    const pila = [m.contenedor, document.body]
    while (pila.length) {
      const n = pila.shift()
      if (n.nodeName === 'LABEL' && texto(n).trim().startsWith(etiqueta)) {
        const pilaB = [n.parentNode]
        while (pilaB.length) { const x = pilaB.shift(); if (x.nodeName === 'INPUT') return x; pilaB.push(...(x.childNodes || [])) }
      }
      pila.push(...(n.childNodes || []))
    }
    return null
  }
  const pasarAlTres = async () => {
    await enActo(async () => otraPestanaEscribe('rendi_client_ctx', JSON.stringify({ id: 3, label: 'Tres' })))
    await esperar(400)
    servidor.pedidos = []
  }

  it('«Agregar mes» en el Mensual del cliente 2 después de que otra pestaña entró al 3: nada llega al 3', async () => {
    log('\n[Vieja: Agregar mes] ──────'); limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir('/mensual')
    await pasarAlTres()
    await tocar('Agregar mes', '/mensual')
    await tocar('Guardar', '/mensual')
    log('  escrituras:', servidor.pedidos.filter(x => x.method !== 'GET').map(x => `${x.method} ${x.path} ${x.cuenta}`))
    expect(escrituras('c3'), 'un mes tipeado sobre el 2, guardado en el 3').toEqual([])
    expect(enLaPagina('Cambiaste de cuenta en otra pestaña'), 'el cartel').toBe(true)
  }, 500000)

  it('una compra a mano en la Cartera del cliente 2 después de que otra pestaña entró al 3: nada llega al 3', async () => {
    log('\n[Vieja: compra] ──────'); limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir('/posiciones')
    await pasarAlTres()
    await tocar('Más acciones', '/posiciones')
    await tocar('Agregar compra', '/posiciones')
    const cantidad = campo('Cantidad'), precio = campo('Precio de compra')
    expect(cantidad && precio, 'los campos de la compra').toBeTruthy()
    await escribir(cantidad, '3')
    await escribir(precio, '100')
    await tocar('Guardar', '/posiciones')
    log('  escrituras:', servidor.pedidos.filter(x => x.method !== 'GET').map(x => `${x.method} ${x.path} ${x.cuenta} ${JSON.stringify(x.body).slice(0, 80)}`))
    expect(escrituras('c3'), 'una compra hecha mirando al 2, registrada en el 3').toEqual([])
    expect(enLaPagina('Cambiaste de cuenta en otra pestaña'), 'el cartel').toBe(true)
  }, 500000)

  it('«Seguir con Dos en esta pestaña»: lo tipeado se guarda en el 2, que es lo que se ve', async () => {
    log('\n[Vieja: seguir] ──────'); limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir('/mensual')
    await pasarAlTres()
    await tocar('Agregar mes', '/mensual')
    await tocar('Seguir con Dos', '/mensual')
    expect(enLaPagina('Cambiaste de cuenta en otra pestaña'), 'el cartel se fue').toBe(false)
    servidor.pedidos = []
    await tocar('Guardar', '/mensual')
    log('  escrituras:', servidor.pedidos.filter(x => x.method !== 'GET').map(x => `${x.method} ${x.path} ${x.cuenta}`))
    expect(escrituras('c3')).toEqual([])
    expect(escrituras('c2').filter(x => x.method === 'POST' && x.path === '/monthly'), 'el mes, en el 2').toHaveLength(1)
  }, 500000)

  it('«Ir a Tres» recarga la página (lo de memoria del 2 no pasa al 3)', async () => {
    limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir('/mensual')
    await pasarAlTres()
    window.location.reload.mockClear()
    await tocar('Ir a Tres', '/mensual')
    expect(window.location.reload).toHaveBeenCalled()
  }, 500000)

  it('otra persona entra en otra pestaña: en los 300 ms antes de recargar, nada sale con la sesión nueva', async () => {
    log('\n[Vieja: persona] ──────'); limpio(); persona('ana')
    await abrir('/mensual')
    await tocar('Agregar mes', '/mensual')
    const guardar = boton('Guardar')
    expect(guardar, 'el mes a medio cargar, con su Guardar').toBeTruthy()
    servidor.me = { quien: 'bruno', name: 'bruno', email: 'bruno@retest.test', tier: 'pro' }   // la cookie ya es de Bruno
    await enActo(async () => otraPestanaEscribe('rendi_user', JSON.stringify({ name: 'bruno', email: 'bruno@retest.test', tier: 'pro' })))
    servidor.pedidos = []
    window.location.reload.mockClear()
    await enActo(() => clic(buscarEn(m.contenedor, 'Guardar') ? m.contenedor : document.body, guardar))   // antes de los 300 ms
    await esperar(50)
    log('  escrituras:', servidor.pedidos.filter(x => x.method !== 'GET').map(x => `${x.method} ${x.path} ${x.cuenta}`))
    expect(escrituras('bruno'), 'el mes de Ana, guardado en la cuenta de Bruno').toEqual([])
    await esperar(400)
    expect(window.location.reload, 'y se recarga con la sesión nueva').toHaveBeenCalled()
  }, 500000)
})
