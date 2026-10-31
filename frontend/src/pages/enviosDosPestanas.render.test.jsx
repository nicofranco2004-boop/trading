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

let App, HelmetProvider, ToastProvider, MemoryRouter, api, handleDemoRequest, AdvisorImportsMod, demo, dictado
// Cuánta plata tiene cada cuenta (multiplica la cartera del demo).
const FACTOR = { c2: 1, c3: 4, ana: 1, bruno: 7, asesora: 1, asesorb: 1 }
const servidor = { me: null, vencida: false, demora: 0, pedidos: [], rechazados: [] }
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
  demo = await import('../utils/demo')
  ;({ handleDemoRequest } = demo)
  dictado = await import('../hooks/useDictado')
  AdvisorImportsMod = await import('../pages/AdvisorImports')
  vi.stubGlobal('fetch', async (url, opts = {}) => {
    const method = opts.method || 'GET'
    const path = String(url).replace(/^\/api/, '')
    const cid = opts.headers?.['X-Rendi-Client-Id']
    const cuenta = cuentaDe(cid)          // la cookie es la de quien esté logueado AHORA
    const body = opts.body && typeof opts.body === 'string' ? JSON.parse(opts.body) : undefined
    // Como el servidor de verdad (get_current_user, backend/tests/
    // test_persona_de_la_pestana.py): si el pedido dice que es de otra persona
    // que la de la sesión, 409 y no se toca nada (queda en `rechazados`).
    const persona = opts.headers?.['X-Rendi-Persona']
    if (persona && servidor.me?.email && decodeURIComponent(persona) !== servidor.me.email.toLowerCase()) {
      servidor.rechazados.push({ method, path, persona: decodeURIComponent(persona), sesion: servidor.me.email })
      return new Response(JSON.stringify({ detail: { code: 'persona_cambiada', message: 'otra persona' } }),
        { status: 409, headers: { 'content-type': 'application/json' } })
    }
    servidor.pedidos.push({ method, path, cid: cid ?? null, cuenta, body })
    // `servidor.fallar503`: esa lectura contesta «probá de nuevo» (503) las
    // primeras `veces`, y en cada una corre `alFallar` (otra pestaña que cambia).
    const f = servidor.fallar503
    if (f && method === 'GET' && path.startsWith(f.ruta) && f.veces > 0) {
      f.veces -= 1
      f.alFallar?.()
      return new Response('{"detail":"ocupado"}', { status: 503, headers: { 'content-type': 'application/json' } })
    }
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
  // Entró en ESTA pestaña (como AuthContext.login, que escribe por la puerta y
  // la puerta avisa): utils/api toma a esta persona como la de la pestaña.
  window.dispatchEvent(new Event('rendi:sesion-de-la-pestana'))
}
const vencer = async () => {
  servidor.vencida = true
  await enActo(async () => { await api.api.get('/positions').catch(() => {}) })
  servidor.vencida = false
  log('    tras el 401 → rendi_user =', localStorage.getItem('rendi_user'), '| location =', window.location.href)
}
const limpio = () => {
  if (m) { /* se desmonta en abrir */ }
  // El demo se apaga por su puerta ANTES de vaciar: vaciar borra la marca sin
  // avisar, y la pestaña seguiría creyéndose en el demo (utils/api).
  if (demo?.isDemoMode()) demo.disableDemoMode()
  localStorage.clear(); sessionStorage.clear(); api.setClientContext(null)
  // La recarga de AuthContext acá es de mentira: no limpia la memoria del
  // «cambió la persona» que la de verdad sí tira.
  api.marcarPersonaCambiada?.(false)
  // Y lo que haría la recarga con el modo demo: la pestaña vuelve a tomar el
  // de ahora como propio.
  if (demo?.EVENTO_MODO_DEMO) window.dispatchEvent(new Event(demo.EVENTO_MODO_DEMO))
  window.dispatchEvent(new Event('rendi:sesion-de-la-pestana'))        // vacía: nadie, como al recargar
  servidor.fallar503 = null
  servidor.vencida = false; servidor.demora = 0; servidor.pedidos = []; servidor.rechazados = []
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
    // Desde que cada pestaña tiene su cliente, el cierre va al 2 —el que se ve—
    // y no aparece ningún cartel.
    expect(escrituras.filter(x => x.cuenta === 'c2').length, 'el cierre, en el 2').toBeGreaterThan(0)
    expect(texto(m.contenedor)).not.toMatch(/Cambiaste de cuenta en otra pestaña/)
  }, 500000)
})

// 🔴 CADA PESTAÑA TIENE SU CUENTA (re-test a ciegas 3 y 4, 30/10).
// Antes, la pestaña ADOPTABA el cliente que elegía otra: lo que la persona
// tocaba mirando al 2 —agregar un mes, registrar una compra— se guardaba en el
// 3. Primero se la frenó con un cartel; el re-test 4 mostró que el asesor que
// trabaja con dos clientes en dos pestañas lo veía a cada rato (y también si en
// la otra sólo abría la lista de clientes). Ahora cada pestaña tiene SU
// cliente (utils/api, en el almacén de la pestaña) y manda a ése, sin cartel.
// El cartel queda para lo que sí es uno para todas: la PERSONA (la cookie) y
// el modo demo.
describe('la pestaña vieja: lo que toca la persona después de que otra cambia', () => {
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
  // Un botón DEL CARTEL (la barra lateral también tiene «Cerrar sesión»).
  function delCartel(parte) {
    const pila = [m.contenedor, document.body]
    while (pila.length) {
      const n = pila.shift()
      if (n.getAttribute?.('role') === 'alertdialog') return buscarEn(n, parte)
      pila.push(...(n.childNodes || []))
    }
    return null
  }
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
  const otraPestanaEntraAl = async (ctx) => {
    await enActo(async () => otraPestanaEscribe('rendi_client_ctx', ctx ? JSON.stringify(ctx) : null))
    await esperar(400)
    servidor.pedidos = []
  }
  const CARTEL = 'Cambiaste de cuenta en otra pestaña'

  it('«Agregar mes» en el Mensual del cliente 2 después de que otra pestaña entró al 3: va al 2, sin cartel', async () => {
    log('\n[Vieja: Agregar mes] ──────'); limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir('/mensual')
    await otraPestanaEntraAl({ id: 3, label: 'Tres' })
    await tocar('Agregar mes', '/mensual')
    await tocar('Guardar', '/mensual')
    log('  escrituras:', servidor.pedidos.filter(x => x.method !== 'GET').map(x => `${x.method} ${x.path} ${x.cuenta}`))
    expect(escrituras('c3'), 'un mes tipeado sobre el 2, guardado en el 3').toEqual([])
    expect(escrituras('c2').filter(x => x.method === 'POST' && x.path === '/monthly'), 'el mes, en el 2').toHaveLength(1)
    expect(enLaPagina(CARTEL), 'sin cartel: cada pestaña con su cliente').toBe(false)
  }, 500000)

  it('una compra a mano en la Cartera del cliente 2 después de que otra pestaña entró al 3: va al 2, sin cartel', async () => {
    log('\n[Vieja: compra] ──────'); limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir('/posiciones')
    await otraPestanaEntraAl({ id: 3, label: 'Tres' })
    await tocar('Más acciones', '/posiciones')
    await tocar('Agregar compra', '/posiciones')
    const cantidad = campo('Cantidad'), precio = campo('Precio de compra')
    expect(cantidad && precio, 'los campos de la compra').toBeTruthy()
    await escribir(cantidad, '3')
    await escribir(precio, '100')
    await tocar('Guardar', '/posiciones')
    log('  escrituras:', servidor.pedidos.filter(x => x.method !== 'GET').map(x => `${x.method} ${x.path} ${x.cuenta} ${JSON.stringify(x.body).slice(0, 80)}`))
    expect(escrituras('c3'), 'una compra hecha mirando al 2, registrada en el 3').toEqual([])
    expect(escrituras('c2').filter(x => x.path === '/positions'), 'la compra, en el 2').toHaveLength(1)
    expect(enLaPagina(CARTEL)).toBe(false)
  }, 500000)

  it('otra pestaña abre la lista de clientes (sale del cliente): ésta sigue en el 2, sin cartel', async () => {
    limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir('/mensual')
    await otraPestanaEntraAl(null)
    expect(api.getClientContext()?.id).toBe(2)
    expect(enLaPagina(CARTEL)).toBe(false)
    expect(enLaPagina('Estás viendo la cuenta de Dos'), 'la banda').toBe(true)
  }, 500000)

  it('una pestaña nueva arranca con el último cliente elegido; una recargada, con el suyo', async () => {
    limpio(); persona('asesora', 'advisor')
    api.setClientContext({ id: 2, label: 'Dos' })
    expect(JSON.parse(localStorage.getItem('rendi_client_ctx')).id, 'lo comparte para las pestañas nuevas').toBe(2)
    otraPestanaEscribe('rendi_client_ctx', JSON.stringify({ id: 3, label: 'Tres' }))
    expect(api.clienteAlCargarLaPestana()?.id, 'al recargar esta pestaña: el suyo').toBe(2)
    sessionStorage.clear()                       // una pestaña nueva no trae el almacén de ésta
    expect(api.clienteAlCargarLaPestana()?.id, 'una pestaña nueva: el último elegido').toBe(3)
    // Si en el medio entró otra persona, lo de la pestaña no vale: es de la anterior.
    api.setClientContext({ id: 2, label: 'Dos' })
    localStorage.setItem('rendi_user', JSON.stringify({ name: 'otra', email: 'otra@retest.test' }))
    localStorage.removeItem('rendi_client_ctx')
    expect(api.clienteAlCargarLaPestana(), 'otra persona: sin el cliente de la anterior').toBe(null)
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

  const ANA = { name: 'ana', email: 'ana@retest.test', tier: 'pro' }
  const BRUNO = { name: 'bruno', email: 'bruno@retest.test', tier: 'pro' }
  const entraEnOtraPestana = async (u, quien) => {
    servidor.me = u ? { quien, ...u } : null                        // la cookie ya es de la otra
    await enActo(async () => otraPestanaEscribe('rendi_user', u ? JSON.stringify(u) : null))
  }
  const intento = (fn) => Promise.race([
    Promise.resolve().then(fn).then(() => 'volvió ok', (e) => `error: ${String(e?.message || e).slice(0, 60)}`),
    esperar(1500).then(() => 'sigue esperando'),
  ])

  // P2 del re-test a ciegas 4: la cookie YA es de Bruno, pero a esta pestaña
  // todavía no le llegó el aviso de la otra (milisegundos). Nada de acá lo sabe:
  // lo frena el servidor, porque el pedido dice que es de Ana.
  it('P2: la cookie ya es de Bruno y el aviso todavía no llegó: el servidor lo rechaza, cartel y recarga', async () => {
    log('\n[Vieja: P2] ──────'); limpio(); persona('ana')
    await abrir('/dashboard')
    servidor.me = { quien: 'bruno', ...BRUNO }                        // sólo la cookie: sin aviso
    servidor.pedidos = []
    window.location.reload.mockClear()
    const compra = await intento(() => api.api.post('/positions', { asset: 'AAPL', quantity: 1, buy_price: 1 }))
    log('  compra:', compra, '| guardados:', servidor.pedidos.map(x => `${x.method} ${x.path} ${x.cuenta}`), '| rechazados:', servidor.rechazados)
    expect(servidor.pedidos.filter(x => x.cuenta === 'bruno' && x.method !== 'GET'), 'la compra de Ana, en la cuenta de Bruno').toEqual([])
    expect(servidor.rechazados.some(x => x.path === '/positions' && x.persona === 'ana@retest.test')).toBe(true)
    await m.redibujar(el('/dashboard'))
    expect(enLaPagina('entró otra persona'), 'el cartel').toBe(true)
    await esperar(400)
    expect(window.location.reload, 'y se recarga').toHaveBeenCalled()
  }, 500000)

  it('el dictado por voz no sale con la sesión de otra persona', async () => {
    log('\n[Vieja: dictado] ──────'); limpio(); persona('ana')
    await abrir('/dashboard')
    await entraEnOtraPestana(BRUNO, 'bruno')
    servidor.pedidos = []
    const r = await intento(() => dictado.mandarAlServidor(new Blob(['x']), 'audio/webm'))
    log('  dictado:', r, '| llegaron:', servidor.pedidos.map(x => `${x.method} ${x.path} ${x.cuenta}`))
    expect(servidor.pedidos.filter(x => x.path.startsWith('/ai/dictado')), 'el audio de Ana, con los activos y los minutos de Bruno').toEqual([])
  }, 500000)

  it('el reintento automático de una lectura vuelve a pasar por el freno', async () => {
    log('\n[Vieja: reintento] ──────'); limpio(); persona('ana')
    await abrir('/dashboard')
    servidor.pedidos = []
    // La lectura falla una vez (503) y, mientras espera para reintentar, en otra pestaña entra Bruno.
    servidor.fallar503 = { ruta: '/positions', veces: 1, alFallar: () => { entraEnOtraPestana(BRUNO, 'bruno') } }
    const r = await Promise.race([
      api.api.get('/positions').then(() => 'volvió ok', (e) => `error: ${e.message.slice(0, 50)}`),
      esperar(4000).then(() => 'sigue esperando'),
    ])
    log('  lectura:', r, '| llegaron:', servidor.pedidos.map(x => `${x.method} ${x.path} ${x.cuenta}`))
    expect(servidor.pedidos.filter(x => x.cuenta === 'bruno' && x.path.startsWith('/positions')), 'el reintento, con la sesión de Bruno').toEqual([])
  }, 500000)

  it('demo en esta pestaña; en otra la persona sale del demo y entra a su cuenta: nada de acá llega a la cuenta real', async () => {
    log('\n[Vieja: demo → real] ──────'); limpio()
    demo.enableDemoMode()
    servidor.me = null
    await abrir('/dashboard')
    window.location.reload.mockClear()
    await enActo(async () => otraPestanaEscribe('rendi_demo_mode', null))
    await entraEnOtraPestana(ANA, 'ana')
    servidor.pedidos = []
    const compra = await intento(() => api.api.post('/positions', { asset: 'DEMO', quantity: 1, buy_price: 1 }))
    const lectura = await intento(() => api.api.get('/positions'))
    log('  compra:', compra, '| lectura:', lectura, '| llegaron:', servidor.pedidos.map(x => `${x.method} ${x.path} ${x.cuenta}`))
    expect(servidor.pedidos, 'lo tocado en el demo, en la cuenta real de Ana').toEqual([])
    expect(enLaPagina(CARTEL), 'el cartel').toBe(true)
    await esperar(400)
    expect(window.location.reload, 'y se recarga').toHaveBeenCalled()
  }, 500000)

  it('cuenta real en esta pestaña; en otra entran al demo: ésta no muestra el demo como si fuera suyo', async () => {
    log('\n[Vieja: real → demo] ──────'); limpio(); persona('ana')
    await abrir('/dashboard')
    window.location.reload.mockClear()
    await enActo(async () => otraPestanaEscribe('rendi_demo_mode', String(Date.now())))
    const lectura = await intento(() => api.api.get('/positions'))
    log('  lectura:', lectura)
    expect(lectura, 'la cartera de ejemplo dibujada en la pantalla de Ana').not.toBe('volvió ok')
    expect(enLaPagina(CARTEL)).toBe(true)
    await esperar(400)
    expect(window.location.reload).toHaveBeenCalled()
  }, 500000)

  it('el cartel dice lo que pasa AHORA: si la otra pestaña vuelve a la misma persona, se va', async () => {
    limpio(); persona('ana')
    await abrir('/dashboard')
    await entraEnOtraPestana(BRUNO, 'bruno')
    await m.redibujar(el('/dashboard'))
    expect(enLaPagina('entró otra persona')).toBe(true)
    await entraEnOtraPestana(ANA, 'ana')                 // «Limpiar» en la otra: vacía y repone la misma sesión
    await m.redibujar(el('/dashboard'))
    expect(enLaPagina(CARTEL)).toBe(false)
  }, 500000)

  // 🔴 RE-TEST A CIEGAS 5: LA RECARGA SIN FIN. El navegador quedó con la persona
  // guardada de Ana y la sesión de Bruno (un inicio de sesión de Bruno cortado
  // justo entre la respuesta del servidor y el guardado). Cada apertura pedía
  // «¿quién soy?» diciendo «soy Ana» → 409 → recarga → y otra vez: 37 recargas
  // en 20 s, y el cartel sin botones no dejaba ni cerrar sesión. Cada recarga
  // de la app se simula acá volviendo a montarla.
  it('persona guardada Ana y sesión de Bruno: abre la app de Bruno, con una sola recarga', async () => {
    log('\n[Sin fin] ──────'); limpio(); persona('ana')
    servidor.me = { quien: 'bruno', ...BRUNO }                       // la sesión es de Bruno
    window.location.reload.mockClear()
    for (let i = 0; i < 3; i++) { await abrir('/dashboard'); await esperar(400) }
    log('  recargas:', window.location.reload.mock.calls.length, '| persona guardada:', localStorage.getItem('rendi_user'),
      '| rechazados:', servidor.rechazados.length)
    expect(window.location.reload.mock.calls.length, 'recargas en bucle').toBeLessThanOrEqual(1)
    expect(JSON.parse(localStorage.getItem('rendi_user') || 'null')?.email, 'se le creyó al servidor').toBe('bruno@retest.test')
    servidor.rechazados = []
    await abrir('/dashboard')
    expect(servidor.rechazados, 'ya abierta como Bruno, nada se rechaza').toEqual([])
    expect(enLaPagina(CARTEL)).toBe(false)
  }, 500000)

  it('si los rechazos siguen, a la tercera no recarga más y el cartel ofrece «Cerrar sesión», que sí sale', async () => {
    limpio(); persona('ana')
    await abrir('/dashboard')
    window.location.reload.mockClear()
    for (let i = 0; i < 3; i++) {
      api.rechazoPorPersona(409, { detail: { code: 'persona_cambiada' } })
      await esperar(350)
    }
    expect(window.location.reload.mock.calls.length, 'tope de recargas').toBe(2)
    await m.redibujar(el('/dashboard'))
    const salir = delCartel('Cerrar sesión')
    expect(salir, 'el botón del cartel').toBeTruthy()
    servidor.pedidos = []
    await enActo(() => clic(buscarEn(m.contenedor, 'Cerrar sesión') ? m.contenedor : document.body, salir))
    await esperar(200)
    expect(servidor.pedidos.map(x => `${x.method} ${x.path}`), 'cerrar sesión sale aunque la pestaña esté frenada').toContain('POST /auth/logout')
  }, 500000)

  it('el cartel de otra persona siempre trae «Cerrar sesión»', async () => {
    limpio(); persona('ana')
    await abrir('/dashboard')
    await entraEnOtraPestana(BRUNO, 'bruno')
    await m.redibujar(el('/dashboard'))
    expect(enLaPagina('entró otra persona')).toBe(true)
    expect(delCartel('Cerrar sesión')).toBeTruthy()
  }, 500000)

  it('la misma persona vuelve a entrar en otra pestaña: sin cartel ni recarga', async () => {
    limpio(); persona('ana')
    await abrir('/dashboard')
    window.location.reload.mockClear()
    await enActo(async () => otraPestanaEscribe('rendi_user', null))          // sale…
    await m.redibujar(el('/dashboard'))
    const enElMedio = enLaPagina(CARTEL)
    await entraEnOtraPestana(ANA, 'ana')                                     // …y vuelve a entrar ella
    await m.redibujar(el('/dashboard'))
    await esperar(400)
    expect(enElMedio, 'el cartel de «otra persona» en el medio').toBe(false)
    expect(enLaPagina(CARTEL)).toBe(false)
    expect(window.location.reload).not.toHaveBeenCalled()
  }, 500000)

  it('cuando entra otra persona, lo guardado de la anterior se borra (también si su sesión venció sola)', async () => {
    limpio(); persona('ana')
    const deAna = 'rendi_snapshot_date:ana@retest.test|propia'
    localStorage.setItem(deAna, '2026-10-30')
    await vencer()                                    // la sesión de Ana vence: 401
    persona('bruno')                                  // y entra Bruno en esta pestaña
    expect(localStorage.getItem(deAna), 'lo de Ana, con su email, quedaba en el navegador').toBeNull()
  }, 500000)
})

