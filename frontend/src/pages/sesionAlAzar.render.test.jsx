// 🔴 LA SESIÓN DE LA PESTAÑA, POR ESCENARIOS AL AZAR (re-test a ciegas 6, 30/10).
//
// Seis vueltas de arreglos sobre «una pestaña no muestra una cuenta y manda
// otra», y en cada una el arreglo abrió un hueco en una secuencia de eventos
// que nadie había escrito a mano: la recarga sin fin, la pestaña trabada tras
// tres cambios en 30 s, el «Guardar» de Ana en la cuenta de Bruno cuando la
// cookie llegaba antes que el aviso. Los casos armados siempre dejan afuera
// alguna combinación. Esta prueba no los arma: tira secuencias al azar (con
// semilla fija: un rojo se repite) y en cada paso verifica TRES REGLAS:
//
//   (i)   Ningún pedido con datos que muestra una pantalla se guarda en otra
//         cuenta (el servidor anota en qué cuenta escribió y qué mostraba la
//         pantalla que lo mandó).
//   (ii)  La pestaña queda usable —con la sesión que hay, sin cartel— o con un
//         cartel cuyo botón «Recargar» la deja usable, en pocas recargas.
//   (iii) Nunca se borra algo guardado de la persona que tiene la sesión.
//   (iv)  Ningún pedido con sesión sale sin decir de quién es (salvo «¿quién
//         soy?»): una pestaña «de nadie» es la puerta abierta del re-test a
//         ciegas 8, aunque el servidor la rechace.
//
// Qué es de verdad y qué no:
//   · La pestaña A es de verdad: cada recarga vuelve a cargar TODO el código con
//     una ventana nueva (como el navegador), y conserva lo guardado en el
//     navegador. Monta las piezas que deciden de quién es cada pedido —
//     AuthContext, AdvisorContext, el cartel, utils/api, la puerta del almacén,
//     los envíos con dueño— y una pantalla mínima que muestra datos de una
//     cuenta y desde ahí compra, agrega un mes y manda un envío automático.
//     A entra por las PANTALLAS de entrada de verdad, llenando y mandando su
//     formulario (testing/pantallasDeEntrada): hasta el re-test 8 llamaba a la
//     puerta directo y no veía una pantalla que no la usara.
//   · La otra pestaña (B) hace lo que hace en el navegador compartido: cambia la
//     cookie (el servidor) y, a veces un rato después, lo guardado en común,
//     y le llega a A el aviso `storage`.
//   · El servidor simulado aplica la regla del de verdad (get_current_user,
//     backend/tests/test_persona_de_la_pestana.py): sin sesión 401; si el
//     pedido dice otra persona que la de la cookie, 409 persona_cambiada; si
//     no dice ninguna, 401 persona_falta (salvo «¿quién soy?»); «cerrar
//     sesión» no cierra la sesión de otra persona. Las rutas de entrada
//     contestan lo que contesta main.py.
//
// Por defecto corren 24 escenarios de 7 pasos. Para cientos:
//   RENDI_AZAR=300 npx vitest run src/pages/sesionAlAzar.render.test.jsx
// Para repetir uno: RENDI_AZAR_SEMILLA=<la del rojo> RENDI_AZAR=1
// Para juntar más rojos antes de cortar: RENDI_AZAR_ROJOS=30
import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { createElement as h } from 'react'
import { appendFileSync } from 'node:fs'
import { contestarEntrada, entrarPorLaPantalla, PUERTAS, pantallasDeEntrada, RUTAS_DE_ENTRADA, rutasComoLaApp } from '../testing/pantallasDeEntrada'

const SEMILLA = Number(process.env.RENDI_AZAR_SEMILLA || 20261031)
const ESCENARIOS = Number(process.env.RENDI_AZAR || 24)
const PASOS = Number(process.env.RENDI_AZAR_PASOS || 7)
const MAX_ROJOS = Number(process.env.RENDI_AZAR_ROJOS || 3)     // corta al juntar tantos
// RENDI_AZAR_SOLO=i: vigila sólo la regla (i) (sin cortar por las otras), para
// buscar ventanas que una pestaña trabada taparía.
const SOLO = process.env.RENDI_AZAR_SOLO || ''
const LOG = process.env.RETEST_LOG
const log = (...a) => { if (LOG) appendFileSync(LOG, a.map(x => (typeof x === 'string' ? x : JSON.stringify(x))).join(' ') + '\n') }

// Un generador de números al azar con semilla (mulberry32): el mismo número da
// la misma secuencia.
function azar(semilla) {
  let a = semilla >>> 0
  const sig = () => {
    a = (a + 0x6D2B79F5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
  return { sig, entre: (n) => Math.floor(sig() * n), uno: (lista) => lista[Math.floor(sig() * lista.length)] }
}

const ANA = { name: 'Ana', email: 'ana@azar.test', tier: 'pro' }
const BRUNO = { name: 'Bruno', email: 'bruno@azar.test', tier: 'pro' }
const ASESORA = { name: 'Asesora', email: 'asesora@azar.test', tier: 'advisor', clientes: [2, 3] }
const PERSONAS = [ANA, BRUNO, ASESORA]
const porEmail = (e) => PERSONAS.find(p => p.email === String(e || '').trim().toLowerCase()) || null
const guardado = (u) => JSON.stringify({ name: u.name, email: u.email, tier: u.tier })

// ── Relojes por carga: los de una página que ya se fue no corren más ────────
const T0 = globalThis.setTimeout, I0 = globalThis.setInterval, CI0 = globalThis.clearInterval
const esperar = (ms) => new Promise(r => T0(r, ms))
let gen = 0
function relojesDeLaCarga() {
  const g = gen
  const st = (fn, ms, ...r) => T0(() => { if (gen === g && typeof fn === 'function') fn(...r) }, ms)
  const si = (fn, ms, ...r) => { const id = I0(() => { if (gen === g) fn(...r); else CI0(id) }, ms); return id }
  vi.stubGlobal('setTimeout', st); window.setTimeout = st
  vi.stubGlobal('setInterval', si); window.setInterval = si
  window.clearTimeout = globalThis.clearTimeout; window.clearInterval = CI0
}

// ── El servidor ───────────────────────────────────────────────────────────
const srv = { me: null, demoraMe: 0, meFalla: 0, escrituras: [], sinPersona: [] }
const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'content-type': 'application/json' } })
async function servidor(url, opts = {}) {
  const g = gen
  const method = opts.method || 'GET'
  const path = String(url).replace(/^\/api/, '').split('?')[0]
  const hd = opts.headers || {}
  const persona = hd['X-Rendi-Persona'] ? decodeURIComponent(hd['X-Rendi-Persona']).trim().toLowerCase() || null : null
  const cid = hd['X-Rendi-Client-Id'] != null ? Number(hd['X-Rendi-Client-Id']) : null
  const sesion = srv.me                                   // la cookie: la de quien está logueado AL MANDAR
  let body
  try { body = opts.body && typeof opts.body === 'string' ? JSON.parse(opts.body) : undefined } catch { body = undefined }
  // «Cerrar sesión» no cierra la de otra persona (main.py, logout).
  const deOtra = path === '/auth/logout' && persona && sesion && persona !== sesion.email
  if (path === '/auth/logout' && !deOtra) srv.me = null
  await esperar(path === '/auth/me' ? srv.demoraMe : (srv.demoraResto || 3))
  if (gen !== g) return new Promise(() => {})              // la página se fue: el navegador corta el pedido
  if (path === '/auth/logout') return deOtra ? json({ detail: { code: 'persona_cambiada' } }, 409) : json({ ok: true })
  const entrada = contestarEntrada(srv, method, path, body, porEmail)
  if (entrada) return entrada
  if (path === '/health' || path === '/stats/public') return json({ ok: true })
  if (!sesion) return json({ detail: 'Token inválido' }, 401)
  if (!persona && !(method === 'GET' && path === '/auth/me')) {
    srv.sinPersona.push({ pedido: `${method} ${path}`, paso: pasoActual })
    return json({ detail: { code: 'persona_falta' } }, 401)
  }
  if (persona && persona !== sesion.email) return json({ detail: { code: 'persona_cambiada' } }, 409)
  if (path === '/auth/me') {
    if (srv.meFalla > 0) { srv.meFalla -= 1; return json({ detail: 'ocupado' }, 503) }   // se reintenta solo
    return json({ email: sesion.email, name: sesion.name, tier: sesion.tier })
  }
  let cuenta = sesion.email
  if (cid != null) {
    if (!(sesion.clientes || []).includes(cid)) return json({ detail: 'sin vínculo' }, 403)
    cuenta = `c${cid}`
  }
  if (method === 'GET' && path === '/positions') return json({ cuenta })
  if (method !== 'GET') {
    srv.escrituras.push({ path, cuenta, muestra: body?.muestra ?? null, paso: pasoActual })
    return json({ ok: true })
  }
  return json({})
}

// ── La pestaña A: cada carga vuelve a cargar todo ───────────────────────────
let mapas = { local: new Map(), sesion: new Map() }
let cur = null
let pasoActual = ''

async function cargar(ruta = '/app') {
  if (cur?.m) { try { await cur.m.desmontar() } catch { /* */ } }
  gen++
  const prevL = new Map(mapas.local), prevS = new Map(mapas.sesion)
  vi.resetModules()
  const nav = await import('../testing/navegadorMinimo')
  const maps = nav.instalarNavegadorMinimo()
  for (const [k, v] of prevL) maps.local.set(k, v)
  for (const [k, v] of prevS) maps.sesion.set(k, v)
  mapas = maps
  relojesDeLaCarga()
  // La página arranca en /app: así se ve cuando algo la manda a otra dirección
  // (el 401 y el demo la mandan al inicio, «/»).
  const pathname = ruta.split('?')[0]
  Object.assign(window.location, { href: 'http://localhost' + pathname, pathname, search: '' })
  window.history = { replaceState() {}, pushState() {}, back() {} }
  const R = await import('react')
  const RR = await import('react-router-dom')
  const { HelmetProvider } = await import('react-helmet-async')
  const pantallas = await pantallasDeEntrada()
  const { AuthProvider, useAuth } = await import('../contexts/AuthContext')
  const { AdvisorProvider, useAdvisorContext } = await import('../contexts/AdvisorContext')
  const { default: Cartel } = await import('../components/CuentaCambiadaEnOtraPestana')
  const api = await import('../utils/api')
  const { ENVIOS, enviarDe } = await import('../utils/enviosConDueno')
  const { useDuenoDeLosDatos } = await import('../utils/duenoDeLaPestana')
  const almacen = await import('../utils/almacen')
  const demo = await import('../utils/demo')
  const tab = { pantalla: null, ruta: pathname }
  // Una pantalla que muestra datos de UNA cuenta (la que contestó al montarse)
  // y manda con ellos: lo que hace cualquier pantalla de la app.
  function Pantalla() {
    const auth = useAuth()
    const adv = useAdvisorContext()
    const dueno = useDuenoDeLosDatos()
    const [muestra, setMuestra] = R.useState(null)
    R.useEffect(() => {
      if (!auth.user || auth.user.demo) return undefined
      let vivo = true
      api.api.get('/positions').then(r => { if (vivo) setMuestra(r?.cuenta ?? null) }).catch(() => {})
      return () => { vivo = false }
    }, [])
    tab.pantalla = {
      user: auth.user, muestra, cliente: adv.clientCtx?.id ?? null, logout: auth.logout,
      exitDemo: auth.exitDemo, enterClient: adv.enterClient, exitClient: adv.exitClient,
      compra: () => api.api.post('/positions', { muestra }),
      mes: () => api.api.post('/monthly', { muestra }),
      automatico: () => enviarDe(ENVIOS.pnlNoRealizado, dueno, { muestra }),
    }
    return R.createElement('div', null, `pantalla de ${muestra}`)
  }
  function PantallaDeLaCuenta() {
    const auth = useAuth()
    const adv = useAdvisorContext()
    return R.createElement(Pantalla, { key: `${auth.user?.email ?? 'nadie'}|${adv.clientCtx?.id ?? 'propia'}` })
  }
  function Ojo() { tab.ruta = RR.useLocation().pathname; return null }
  const Rutas = rutasComoLaApp(h, RR, useAuth, pantallas, PantallaDeLaCuenta)
  const el = () => h(HelmetProvider, null, h(RR.MemoryRouter, { initialEntries: [ruta] },
    h(AuthProvider, null, h(AdvisorProvider, null, h(Cartel), h(Ojo), h(Rutas)))))
  const m = await nav.montar(el())
  cur = { m, nav, el, api, almacen, demo, tab, href: window.location.href, win: window }
  return cur
}

const quiereIrse = () => cur.win.location.reload.mock.calls.length > 0 || cur.win.location.href !== cur.href
// Sigue a la pestaña como el navegador —cada recarga es una carga nueva— hasta
// que se queda quieta. Devuelve cuántas recargas hubo.
async function seguir({ quieto = 450, max = 8 } = {}) {
  let recargas = 0, ultimo = Date.now()
  for (let i = 0; i < 400; i++) {
    await esperar(25)
    try { await cur.m.redibujar(cur.el()) } catch { /* */ }
    if (quiereIrse()) {
      if (recargas >= max) break
      await cargar(); recargas++; ultimo = Date.now()
      continue
    }
    // «Recargando» es esperar a que conteste «¿quién soy?» (puede tardar) para
    // recargar: no es estar quieta. Si no sale de ahí en 10 s, es una traba
    // y (ii) la marca.
    if (cur.api.pestanaDesfasada?.()?.motivo === 'recargando') { ultimo = Date.now(); continue }
    if (Date.now() - ultimo > quieto) break
  }
  return recargas
}

// ── Lo que pasa en el navegador compartido ──────────────────────────────────
function otraPestanaEscribe(key, valor) {
  if (valor === null) localStorage.removeItem(key)
  else localStorage.setItem(key, valor)
  window.dispatchEvent(Object.assign(new Event('storage'), { key, newValue: valor }))
}
function enComun() { try { return JSON.parse(localStorage.getItem('rendi_user') || 'null')?.email ?? null } catch { return null } }
const textoCartel = () => {
  const pila = [cur.m.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.getAttribute?.('role') === 'alertdialog') return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
function botonDelCartel(parte) {
  const c = textoCartel()
  if (!c) return null
  const pila = [c]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && cur.nav.texto(n).includes(parte)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
const clavesDe = (email) => [...mapas.local.keys()].filter(k => k.includes(`:${email}|`))

// Las acciones. Cada una devuelve una promesa; las de B pueden dejar lo
// guardado en común para un rato después (la cookie llega antes que el aviso).
// Cinco compras cada 300 ms con la pantalla que esté montada. Si la página
// pide irse (recargar, ir al inicio), la vieja sigue viva un rato antes de que
// arranque la nueva —en el navegador, la navegación no es instantánea, y un
// «¿Salir del sitio?» la frena del todo—: `demoraDeNavegacion`. Las ventanas
// del re-test a ciegas 6 (un 401 antes de la cookie nueva, el reintento de
// «¿quién soy?») vivían justo ahí.
const ráfaga = (demoraDeNavegacion, { veces = 5, cada = 300 } = {}) => async () => {
  let pidioIrse = null
  for (let i = 0; i < veces; i++) {
    try { await cur.tab.pantalla?.compra() } catch { /* el freno o el servidor */ }
    await esperar(cada)
    if (quiereIrse()) {
      pidioIrse ??= Date.now()
      if (Date.now() - pidioIrse >= demoraDeNavegacion) { await cargar(); pidioIrse = null }
    }
  }
}

function accionesDeA(r) {
  const p = cur.tab.pantalla
  const lista = []
  const intentar = (fn) => async () => { try { await fn() } catch { /* el freno o el servidor la cortaron */ } }
  if (p?.user && !p.user.demo) {
    lista.push(['A compra', intentar(() => cur.tab.pantalla.compra())])
    lista.push(['A agrega un mes', intentar(() => cur.tab.pantalla.mes())])
    lista.push(['A manda un envío automático', intentar(() => cur.tab.pantalla.automatico())])
    // La persona sigue tocando mientras pasa algo: las ventanas de milisegundos
    // (el 401 antes de la cookie nueva, el reintento de «¿quién soy?») sólo se
    // ven con pedidos repartidos en el tiempo, no con uno suelto.
    const nav = r.uno([0, 100, 500])
    lista.push([`A compra varias veces seguidas (la página tarda ${nav} ms en irse)`, ráfaga(nav)])
    lista.push(['A cierra sesión', intentar(() => cur.tab.pantalla.logout())])
    if (p.user.tier === 'advisor') {
      const c = r.uno([2, 3, null])
      lista.push([`A pasa al cliente ${c ?? 'propia'}`, intentar(() => (c ? cur.tab.pantalla.enterClient({ id: c, label: `C${c}` }) : cur.tab.pantalla.exitClient()))])
    }
  }
  if (!p?.user) {
    const u = r.uno(PERSONAS)
    // Una acción por cada puerta de entrada, por su PANTALLA: abre la pantalla,
    // llena el formulario y lo manda (re-test a ciegas 7: «restablecer la
    // contraseña» tenía su propio camino y se quedó afuera; re-test 8: llamar a
    // la puerta directo no veía una pantalla que no la usara).
    for (const puerta of Object.keys(PUERTAS)) {
      lista.push([`A entra como ${u.name} por «${puerta}»`, intentar(() => entrarPorLaPantalla(puerta, u, ctxDeEntrada))])
    }
    lista.push(['A entra al demo', intentar(async () => { cur.demo.enableDemoMode(); cur.win.location.href = 'http://localhost/' })])
  }
  if (p?.user?.demo) lista.push(['A sale del demo', intentar(() => cur.tab.pantalla.exitDemo())])
  lista.push(['A recarga (F5)', async () => { cur.win.location.reload() }])
  const nav2 = r.uno([0, 100, 500])
  lista.push([`A recarga y sigue tocando mientras abre (la página tarda ${nav2} ms en irse)`, async () => {
    await cargar()                                           // la página nueva, recién abierta
    await ráfaga(nav2)()
  }])
  lista.push(['A: la sesión vence sola', async () => { srv.me = null; try { await cur.api.api.get('/positions') } catch { /* 401 */ } }])
  return lista
}
function accionesDeB(r) {
  const demora = r.uno([0, 0, 40, 150, 400])
  const u = r.uno(PERSONAS)
  return [
    [`B entra como ${u.name} (lo guardado ${demora} ms después)`, async () => {
      srv.me = u
      await esperar(demora)
      // Lo que hace AuthContext.login en esa pestaña: borra lo de otras
      // personas (la sesión es de ésta) y guarda quién es.
      cur.almacen.borrarLoDeOtrasPersonas(u.email)
      otraPestanaEscribe('rendi_client_ctx', null)
      otraPestanaEscribe('rendi_user', guardado(u))
    }, { sale: false, entra: u.email }],
    ['B cierra sesión', async () => {
      srv.me = null
      for (const k of [...mapas.local.keys()].filter(k => k.startsWith('rendi_') && k !== 'rendi_theme')) otraPestanaEscribe(k, null)
    }, { sale: true }],
    ['B entra al demo', async () => { otraPestanaEscribe('rendi_demo_mode', String(Date.now())) }],
    // Salir del demo no toca la sesión de la cuenta real (re-test a ciegas 8).
    ['B sale del demo', async () => { otraPestanaEscribe('rendi_demo_mode', null) }],
    [`B abre el cliente ${r.uno([2, 3])}`, async () => { otraPestanaEscribe('rendi_client_ctx', JSON.stringify({ id: r.uno([2, 3]), label: 'X' })) }],
    ['«¿quién soy?» se pone lento', async () => { srv.demoraMe = r.uno([0, 350, 900]) }],
    ['«¿quién soy?» falla una vez (y se reintenta)', async () => { srv.meFalla = 1 }],
    [`B sale y entra como ${u.name} (lo guardado ${demora} ms después)`, async () => {
      srv.me = null
      for (const k of [...mapas.local.keys()].filter(k => k.startsWith('rendi_') && k !== 'rendi_theme')) otraPestanaEscribe(k, null)
      await esperar(r.uno([0, 20, 200]))
      srv.me = u
      await esperar(demora)
      cur.almacen.borrarLoDeOtrasPersonas(u.email)
      otraPestanaEscribe('rendi_user', guardado(u))
    }],
  ]
}

beforeAll(() => { vi.stubGlobal('fetch', servidor) }, 60000)
afterAll(() => { vi.unstubAllGlobals() })

describe('la sesión de la pestaña, por escenarios al azar', () => {
  it(`${ESCENARIOS} escenarios de ${PASOS} pasos (semilla ${SEMILLA}): las tres reglas se cumplen siempre`, async () => {
    const rojos = []
    for (let e = 0; e < ESCENARIOS && rojos.length < MAX_ROJOS; e++) {
      const semilla = SEMILLA + e
      const r = azar(semilla)
      // Arranca: navegador limpio, alguien logueado (o nadie), con ayudas
      // guardadas de cada persona (para ver si alguna se borra de más).
      mapas = { local: new Map(), sesion: new Map() }
      srv.me = null; srv.demoraMe = 0; srv.demoraResto = 0; srv.meFalla = 0; srv.escrituras = []; srv.sinPersona = []
      const inicial = r.uno([ANA, BRUNO, ASESORA, null])
      if (inicial) { srv.me = inicial; mapas.local.set('rendi_user', guardado(inicial)) }
      mapas.local.set('rendi:tour:novedades:v2', '1')
      for (const u of PERSONAS) mapas.local.set(`rendi_snapshot_date:${u.email}|propia`, '2026-10-30')
      await cargar(); await seguir()
      const historia = [`inicio: ${inicial?.name ?? 'nadie'}`]
      for (let paso = 0; paso < PASOS; paso++) {
        // (iii) lo de quien tiene la sesión ANTES del paso
        const titular = srv.me?.email ?? null
        const deTitular = titular ? clavesDe(titular) : []
        const nEscrituras = srv.escrituras.length
        const nSinPersona = srv.sinPersona.length
        // El paso: una acción de A, de B, o las dos a la vez (B cambia la
        // cookie y A toca algo antes de que llegue el aviso).
        const tipo = r.uno(['A', 'B', 'AB', 'AB'])
        const a = r.uno(accionesDeA(r))
        const b = r.uno(accionesDeB(r))
        pasoActual = tipo === 'A' ? a[0] : tipo === 'B' ? b[0] : `${b[0]} + ${a[0]}`
        historia.push(pasoActual)
        if (tipo === 'A') await enActo(a[1])
        else if (tipo === 'B') await enActo(b[1])
        else await enActo(() => Promise.all([b[1](), esperar(r.uno([0, 5, 30])).then(a[1])]))
        const recargas = await seguir()
        // ── las reglas ──
        const malas = srv.escrituras.slice(nEscrituras).filter(x => x.muestra != null && x.cuenta !== x.muestra)
        if (malas.length) rojos.push({ regla: '(i) datos de una pantalla guardados en otra cuenta', semilla, historia: [...historia], malas })
        const sinDecir = srv.sinPersona.slice(nSinPersona)
        if (sinDecir.length) rojos.push({ regla: '(iv) pedidos con sesión que no dicen de quién son', semilla, historia: [...historia], sinDecir })
        // Un cierre de sesión borra todo lo guardado (AuthContext.logout): en
        // ese instante nadie tiene la sesión, y no cuenta para (iii).
        const sale = /cierra sesión|vence|sale del demo|sale y entra/.test(pasoActual)
        if (!SOLO && titular && !sale && srv.me?.email === titular) {
          const borradas = deTitular.filter(k => !mapas.local.has(k))
          if (borradas.length) rojos.push({ regla: '(iii) se borró algo de quien tiene la sesión', semilla, historia: [...historia], borradas })
        }
        let estado = await usable()
        if (!estado.ok && estado.cartel) {
          // El cartel tiene que tener una salida que funcione: «Recargar».
          const b2 = botonDelCartel('Recargar')
          if (b2) { await enActo(() => cur.nav.clic(cur.m.contenedor, b2)); await seguir(); estado = await usable() }
        }
        if (!SOLO && (!estado.ok || recargas > 4)) rojos.push({ regla: '(ii) la pestaña no quedó usable', semilla, historia: [...historia], recargas, estado })
        if (rojos.some(x => x.semilla === semilla)) break
      }
      log(`[${semilla}]`, historia.join(' → '))
      if (cur?.m) { try { await cur.m.desmontar() } catch { /* */ } }
      gen++
    }
    for (const x of rojos) log('ROJO', x)
    expect(rojos, rojos.length ? `Repetilo con RENDI_AZAR_SEMILLA=${rojos[0].semilla} RENDI_AZAR=1` : '').toEqual([])
  }, 3_600_000)
})

// ── Los escenarios del informe del re-test a ciegas 6, escritos tal cual ─────
// Corren por las mismas piezas y con las mismas reglas: si el azar no los
// alcanza en una corrida, éstos igual los prueban siempre.
async function arrancar(u) {
  mapas = { local: new Map(), sesion: new Map() }
  srv.me = u; srv.demoraMe = 0; srv.demoraResto = 0; srv.meFalla = 0; srv.escrituras = []; srv.sinPersona = []
  if (u) mapas.local.set('rendi_user', guardado(u))
  mapas.local.set('rendi:tour:novedades:v2', '1')
  for (const p of PERSONAS) mapas.local.set(`rendi_snapshot_date:${p.email}|propia`, '2026-10-30')
  await cargar(); await seguir()
}
const enOtraSaleYEntra = async (u, { cookieMs = 20, guardadoMs = 400 } = {}) => {
  srv.me = null
  for (const k of [...mapas.local.keys()].filter(k => k.startsWith('rendi_') && k !== 'rendi_theme')) otraPestanaEscribe(k, null)
  await esperar(cookieMs)
  srv.me = u
  await esperar(guardadoMs)
  cur.almacen.borrarLoDeOtrasPersonas(u.email)
  otraPestanaEscribe('rendi_user', guardado(u))
}
const malasDesde = (n) => srv.escrituras.slice(n).filter(x => x.muestra != null && x.cuenta !== x.muestra)

describe('los escenarios del re-test a ciegas 6, fijos', () => {
  it('B3: Ana sale en otra pestaña, ésta recibe un 401 y entra la cookie de Bruno antes de recargar: nada de Ana va a Bruno', async () => {
    await arrancar(ANA)
    expect(cur.tab.pantalla.muestra).toBe(ANA.email)
    const n = srv.escrituras.length
    pasoActual = 'B3'
    await enActo(() => Promise.all([enOtraSaleYEntra(BRUNO), esperar(5).then(ráfaga(500))]))
    await seguir()
    log('[B3] escrituras:', srv.escrituras.slice(n))
    expect(malasDesde(n), 'compras de la pantalla de Ana guardadas en la cuenta de Bruno').toEqual([])
  }, 120000)

  it('B2b: el reintento de «¿quién soy?» sale con la cookie de Bruno antes del aviso: nada de Ana va a Bruno', async () => {
    await arrancar(ANA)
    srv.meFalla = 1                                    // la próxima apertura: 503 y se reintenta (~0,8 s)
    pasoActual = 'B2b'
    await cargar()
    const n = srv.escrituras.length
    // La pantalla de Ana ya cargó sus datos; Ana no toca nada todavía. En otra
    // pestaña entra Bruno: la cookie ya es suya, y su pestaña guarda quién es
    // recién en 2 s. El reintento de «¿quién soy?» contesta Bruno; en cuanto
    // ESTA pestaña lo guarda (lo hace ella al adoptar), Ana toca «Guardar».
    const deAnaAntes = await (async () => { for (let i = 0; i < 40 && cur.tab.pantalla?.muestra !== ANA.email; i++) await esperar(25); return cur.tab.pantalla?.muestra })()
    expect(deAnaAntes, 'la pantalla muestra los datos de Ana').toBe(ANA.email)
    await enActo(() => Promise.all([
      (async () => { srv.me = BRUNO; await esperar(2000); otraPestanaEscribe('rendi_user', guardado(BRUNO)) })(),
      (async () => {
        for (let i = 0; i < 120 && enComun() !== BRUNO.email; i++) await esperar(20)
        for (let i = 0; i < 4; i++) { try { await cur.tab.pantalla?.compra() } catch { /* */ } await esperar(40) }
      })(),
    ]))
    await seguir()
    log('[B2b] escrituras:', srv.escrituras.slice(n), '| muestra:', cur.tab.pantalla?.muestra)
    expect(malasDesde(n), 'compras de la pantalla de Ana guardadas en la cuenta de Bruno').toEqual([])
  }, 120000)

  it('D3: Ana abre y su «¿quién soy?» tarda; entra Bruno en otra pestaña: no se borra nada de Bruno', async () => {
    await arrancar(ANA)
    mapas.local.set(`rendi_lastvisit_diagnostico:${BRUNO.email}|propia`, '{"t":1}')
    srv.demoraMe = 600
    const pagina = cargar()                                   // Ana abre: «¿quién soy?» sale con su cookie
    await esperar(60)
    srv.me = BRUNO                                            // en otra pestaña entra Bruno
    otraPestanaEscribe('rendi_user', guardado(BRUNO))
    await pagina
    await seguir()
    const deBruno = [`rendi_snapshot_date:${BRUNO.email}|propia`, `rendi_lastvisit_diagnostico:${BRUNO.email}|propia`]
    log('[D3] queda de Bruno:', deBruno.map(k => [k, mapas.local.has(k)]), '| guardada:', enComun())
    expect(deBruno.filter(k => !mapas.local.has(k)), 'lo de Bruno, que tiene la sesión').toEqual([])
    expect(enComun()).toBe(BRUNO.email)
  }, 120000)

  it('demo: con el demo prendido en otra pestaña, «Cerrar sesión» de la pestaña de Ana cierra la sesión de verdad', async () => {
    await arrancar(ANA)
    await enActo(async () => otraPestanaEscribe('rendi_demo_mode', String(Date.now())))
    await enActo(async () => { try { await cur.tab.pantalla.logout() } catch { /* */ } })
    log('[demo] sesión después de cerrar:', srv.me)
    expect(srv.me, 'la sesión real de Ana').toBe(null)
  }, 120000)

  // ── re-test a ciegas 7 ──
  it('R7-1: Ana entra por «restablecer la contraseña» y enseguida entra Bruno en otra pestaña: nada de Ana va a Bruno', async () => {
    await arrancar(null)
    pasoActual = 'R7-1'
    // Por la pantalla de verdad: el link del mail, la contraseña nueva dos veces, «Guardar».
    expect(await entrarPorLaPantalla('restablecer la contraseña', ANA, ctxDeEntrada), 'entró').toBe(true)
    await seguir()
    expect(cur.tab.pantalla.muestra, 'la pantalla de Ana muestra lo de Ana').toBe(ANA.email)
    const n = srv.escrituras.length
    await enActo(() => Promise.all([
      (async () => { srv.me = BRUNO; await esperar(150); otraPestanaEscribe('rendi_user', guardado(BRUNO)) })(),
      (async () => { for (let i = 0; i < 6; i++) { try { await cur.tab.pantalla?.compra() } catch { /* */ } await esperar(40) } })(),
    ]))
    log('[R7-1] escrituras:', srv.escrituras.slice(n))
    expect(malasDesde(n), 'compras de la pantalla de Ana guardadas en la cuenta de Bruno').toEqual([])
    expect(srv.sinPersona, 'pedidos que no dicen de quién son').toEqual([])
  }, 120000)

  it('R7-2: la recarga queda frenada («¿Salir del sitio?») y entra Bruno: el cartel no cierra la sesión de Bruno', async () => {
    await arrancar(ANA)
    mapas.local.set(`rendi_lastvisit_diagnostico:${BRUNO.email}|propia`, '{"t":1}')
    srv.me = BRUNO                                            // en otra pestaña entra Bruno
    cur.almacen.borrarLoDeOtrasPersonas(BRUNO.email)
    mapas.local.set(`rendi_lastvisit_diagnostico:${BRUNO.email}|propia`, '{"t":1}')
    await enActo(async () => otraPestanaEscribe('rendi_user', guardado(BRUNO)))
    // No se sigue la recarga: el navegador preguntó «¿Salir del sitio?» y Ana dijo que no.
    for (let i = 0; i < 20; i++) { await esperar(25); try { await cur.m.redibujar(cur.el()) } catch { /* */ } }
    const cerrar = botonDelCartel('Cerrar sesión')
    if (cerrar) await enActo(() => cur.nav.clic(cur.m.contenedor, cerrar))
    await esperar(100)
    log('[R7-2] botón Cerrar sesión:', !!cerrar, '| sesión:', srv.me?.email ?? null)
    expect(srv.me?.email, 'la sesión de Bruno sigue abierta').toBe(BRUNO.email)
    expect(mapas.local.has(`rendi_lastvisit_diagnostico:${BRUNO.email}|propia`), 'lo de Bruno no se borró').toBe(true)
    expect(botonDelCartel('Recargar'), 'la salida es recargar').toBeTruthy()
  }, 120000)

  it('R7-3: un 401 de la sesión vencida de Ana llega después de que entró Bruno: no se borra que Bruno está logueado', async () => {
    await arrancar(ANA)
    srv.me = null                                             // la sesión de Ana vence sola
    srv.demoraResto = 200                                     // y el servidor tarda en contestar
    const pedido = cur.api.api.get('/positions').catch(() => {})
    await esperar(50)
    srv.me = BRUNO                                            // mientras tanto entra Bruno en otra pestaña
    await enActo(async () => otraPestanaEscribe('rendi_user', guardado(BRUNO)))
    await enActo(() => pedido)                                // llega el 401 (del pedido de Ana)
    log('[R7-3] guardada después del 401:', enComun())
    expect(enComun(), 'la sesión guardada de Bruno').toBe(BRUNO.email)
  }, 120000)

  it('A9: en otra pestaña Ana sale, entra Bruno, Bruno sale y entra Ana (en 30 s): ésta no queda trabada', async () => {
    await arrancar(ANA)
    const pasos = []
    for (const [que, fn] of [
      ['Ana sale', async () => { srv.me = null; otraPestanaEscribe('rendi_user', null) }],
      ['entra Bruno', async () => { srv.me = BRUNO; otraPestanaEscribe('rendi_user', guardado(BRUNO)) }],
      ['Bruno sale', async () => { srv.me = null; otraPestanaEscribe('rendi_user', null) }],
      ['entra Ana', async () => { srv.me = ANA; otraPestanaEscribe('rendi_user', guardado(ANA)) }],
    ]) {
      await enActo(fn)
      const recargas = await seguir()
      pasos.push({ que, recargas, ...(await usable()) })
    }
    log('[A9]', pasos)
    expect(pasos.filter(x => !x.ok || x.recargas > 2), 'pasos en que la pestaña quedó trabada').toEqual([])
  }, 120000)
})

const enActo = async (fn) => { const { act } = await import('react'); let r; await act(async () => { r = await fn() }); return r }
// Para entrar por las pantallas (testing/pantallasDeEntrada).
const quietaUn = async (ms) => { for (let i = 0; i < Math.ceil(ms / 25); i++) { await esperar(25); try { await cur.m.redibujar(cur.el()) } catch { /* */ } } }
const ctxDeEntrada = { cargar, cur: () => ({ ...cur, ruta: () => cur.tab.ruta }), srv, quieta: quietaUn }

// (ii) ¿La pestaña quedó usable? Con la sesión que hay (o el demo, o nadie) y
// sin cartel; o, si quedó lo guardado en común distinto de la cookie (B no
// terminó de escribir), al menos frenada.
async function usable() {
  const p = cur.tab.pantalla
  const enDemo = !!mapas.local.get('rendi_demo_mode')
  const cartel = !!textoCartel()
  const desfase = cur.api.pestanaDesfasada()
  const yo = p?.user?.demo ? 'demo' : (p?.user?.email ?? null)
  const sesion = srv.me?.email ?? null
  const estado = { yo, sesion, enComun: enComun(), enDemo, cartel, desfase, persona: cur.api.personaDeLaPestana?.() }
  let ok
  if (enDemo) ok = yo === 'demo' && !cartel
  else if (!yo) ok = !cartel && !desfase  // en el inicio: puede entrar
  else if (sesion) ok = yo === sesion && !desfase && !cartel
  else ok = !cartel                       // sin sesión: el próximo pedido la lleva al inicio
  return { ok, cartel, ...estado }
}
