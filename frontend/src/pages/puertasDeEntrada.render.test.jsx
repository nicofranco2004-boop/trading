// 🔴 LAS PANTALLAS DE ENTRADA DE VERDAD, Y UNA PESTAÑA SIN DUEÑO QUE FRENA
// (re-test a ciegas 8, 31/10). Parte de la prueba del auditor
// (auditoria-final/dueno-retest-ciego-8.render.test.jsx), con aserciones.
//
// Por qué existe: el guardián de la puerta de la sesión busca TEXTOS y la prueba
// al azar llamaba a la puerta directo. El auditor plantó una pantalla de entrada
// que no la usaba (con un `entrar()` que nunca corría) y el síntoma volvió con
// todo en verde. Esto pasa por el camino de producción:
//   · Las PANTALLAS reales (iniciar sesión, registrarse y verificar el mail,
//     registro directo, reclamar una cuenta, restablecer la contraseña), con su
//     formulario completado y enviado como lo hace el navegador
//     (testing/pantallasDeEntrada).
//   · AuthContext, AdvisorContext, utils/api, el cartel, utils/uso y los envíos
//     automáticos, tal cual. Cada carga de la página vuelve a cargar todo el
//     código (vi.resetModules), con lo guardado en el navegador.
// Simulado: el servidor —con las reglas de main.py, que prueba
// backend/tests/test_persona_de_la_pestana.py contra el de verdad— y la otra
// pestaña (cambia la cookie y, un rato después, lo guardado en común). Al
// pedido con sesión que no dice de quién es lo rechaza (401 persona_falta):
// es el paso 2 de main.py, el más estricto. Hoy el servidor lo atiende y lo
// cuenta; así la prueba ve un olvido aunque hoy no se note.
//
// Lo que se mira, además de «nada de Ana en la cuenta de Bruno»: que NINGÚN
// pedido con sesión salga sin decir de quién es (salvo «¿quién soy?»). Así una
// pestaña «de nadie» da rojo acá aunque el servidor la rechace.
//
// PUERTAS_VECES=n repite cada caso de las puertas n veces (por defecto 1) con
// demoras distintas.
import { describe, it, expect, vi } from 'vitest'
import { createElement as h } from 'react'
import { contestarEntrada, entrarPorLaPantalla, PUERTAS, pantallasDeEntrada, RUTAS_DE_ENTRADA, rutasComoLaApp } from '../testing/pantallasDeEntrada'

const VECES = Number(process.env.PUERTAS_VECES || 1)

const ANA = { id: 11, name: 'Ana', email: 'ana@puertas.test', tier: 'pro' }
const BRUNO = { id: 12, name: 'Bruno', email: 'bruno@puertas.test', tier: 'pro' }
const PERSONAS = [ANA, BRUNO]
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

// ── El servidor simulado, con las reglas de main.py ─────────────────────────
const srv = {}
function reiniciarServidor() {
  Object.assign(srv, {
    me: null, demora: 3, demoraMe: 0, demoraUna: 0, registroDirecto: false, resetPara: ANA, claimPara: ANA,
    escrituras: [], usos: [], logouts: [], lecturas: [], sinPersona: [], previews: [], respuestas: [], accesoPara: ANA,
  })
}
reiniciarServidor()
const json = (o, status = 200) => new Response(o === null ? null : JSON.stringify(o), { status, headers: { 'content-type': 'application/json' } })
function cabeceras(hd) {
  if (!hd) return {}
  if (typeof Headers !== 'undefined' && hd instanceof Headers) { const o = {}; hd.forEach((v, k) => { o[k] = v }); return o }
  return hd
}
async function servidor(url, opts = {}) {
  const g = gen
  const method = (opts.method || 'GET').toUpperCase()
  const path = String(url).replace(/^\/api/, '').split('?')[0]
  const hd = cabeceras(opts.headers)
  const raw = hd['X-Rendi-Persona'] ?? hd['x-rendi-persona']
  const persona = raw ? decodeURIComponent(raw).trim().toLowerCase() || null : null
  let body
  try { body = opts.body && typeof opts.body === 'string' ? JSON.parse(opts.body) : undefined } catch { body = undefined }
  const sesion = srv.me                                   // la cookie AL LLEGAR el pedido
  // «Cerrar sesión» no cierra la sesión de otra persona (main.py, logout).
  if (path === '/auth/logout') {
    const cerro = persona && sesion && persona !== sesion.email ? null : (sesion?.email ?? null)
    srv.logouts.push({ persona, cerro })
    if (persona && sesion && persona !== sesion.email) return json({ detail: { code: 'persona_cambiada' } }, 409)
    srv.me = null
    return json({ ok: true })
  }
  const extra = srv.demoraUna; srv.demoraUna = 0
  await esperar((path === '/auth/me' ? srv.demoraMe : srv.demora) + extra)
  if (gen !== g) return new Promise(() => {})              // la página se fue: el navegador corta el pedido
  const entrada = contestarEntrada(srv, method, path, body, porEmail)
  if (entrada) return entrada
  // El pedido de acceso del asesor: pantalla pública que además quiere saber
  // quién mira (main.py, _optional_uid). Acá con la regla MÁS estricta —sin
  // decir de quién es, es «nadie»— para que un pedido que se olvide de decirlo
  // dé rojo aunque el servidor de hoy lo atienda (re-test a ciegas 9).
  if (path === '/auth/link-request/preview' || path === '/auth/link-request/respond') {
    if (persona && sesion && persona !== sesion.email) return json({ detail: { code: 'persona_cambiada' } }, 409)
    const quien = sesion && persona === sesion.email ? sesion : null
    if (path.endsWith('preview')) {
      srv.previews.push({ persona, cookie: sesion?.email ?? null })
      return json({ state: 'pending', advisor_name: 'La Asesora', permission: 'read_write', email_masked: 'a**@puertas.test',
        is_owner: quien?.email === srv.accesoPara.email, logged_in: !!quien })
    }
    if (body?.accept && quien?.email !== srv.accesoPara.email) return json({ detail: 'Iniciá sesión para aceptar el pedido.' }, 401)
    srv.respuestas.push({ accept: !!body?.accept, cuenta: quien?.email ?? null, persona })
    return json({ ok: true, accepted: !!body?.accept })
  }
  if (path === '/health' || path === '/stats/public') return json({ ok: true })
  // ── get_current_user
  if (!sesion) return json({ detail: 'Token inválido' }, 401)
  const quienSoy = method === 'GET' && path === '/auth/me'
  if (!persona && !quienSoy) {
    srv.sinPersona.push(`${method} ${path}`)
    return json({ detail: { code: 'persona_falta' } }, 401)
  }
  if (persona && persona !== sesion.email) return json({ detail: { code: 'persona_cambiada', message: 'otra persona' } }, 409)
  if (quienSoy) return json({ id: sesion.id, email: sesion.email, name: sesion.name, tier: sesion.tier })
  if (path === '/uso/eventos') { srv.usos.push({ cuenta: sesion.email, persona }); return new Response(null, { status: 204 }) }
  if (method === 'GET' && path === '/positions') { srv.lecturas.push({ cuenta: sesion.email, persona }); return json({ cuenta: sesion.email }) }
  if (method !== 'GET') { srv.escrituras.push({ method, path, cuenta: sesion.email, muestra: body?.muestra ?? null, persona }); return json({ ok: true }) }
  return json({})
}

// ── La pestaña: cada carga vuelve a cargar todo ─────────────────────────────
let mapas = { local: new Map(), sesion: new Map() }
let cur = null
async function cargar(ruta = '/dashboard', { antesDeMontar } = {}) {
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
  const pathname = ruta.split('?')[0]
  Object.assign(window.location, { href: 'http://localhost' + pathname, pathname, search: '', origin: 'http://localhost' })
  window.history = { replaceState() {}, pushState() {}, back() {} }
  vi.stubGlobal('fetch', servidor)
  const R = await import('react')
  const RR = await import('react-router-dom')
  const { HelmetProvider } = await import('react-helmet-async')
  const { AuthProvider, useAuth } = await import('../contexts/AuthContext')
  const { AdvisorProvider } = await import('../contexts/AdvisorContext')
  const { default: Cartel } = await import('../components/CuentaCambiadaEnOtraPestana')
  const api = await import('../utils/api')
  const uso = await import('../utils/uso')
  const { ENVIOS, enviarDe } = await import('../utils/enviosConDueno')
  const { useDuenoDeLosDatos } = await import('../utils/duenoDeLaPestana')
  const pantallas = await pantallasDeEntrada()
  const { default: Acceso } = await import('./AdvisorAccessRequest')
  const tab = { pantalla: null, ruta: pathname }
  function Pantalla() {
    const auth = useAuth()
    const dueno = useDuenoDeLosDatos()
    const [muestra, setMuestra] = R.useState(null)
    R.useEffect(() => {
      if (!auth.user || auth.user.demo) return undefined
      let vivo = true
      api.api.get('/positions').then(r => { if (vivo) setMuestra(r?.cuenta ?? null) }).catch(() => {})
      return () => { vivo = false }
    }, [])
    tab.pantalla = {
      user: auth.user, muestra, logout: auth.logout, exitDemo: auth.exitDemo,
      compra: () => api.api.post('/positions', { muestra }),
      mes: () => api.api.post('/monthly', { muestra }),
      automatico: () => enviarDe(ENVIOS.pnlNoRealizado, dueno, { muestra }),
      leer: () => api.api.get('/positions'),
    }
    return h('div', null, `Hola ${auth.user?.name ?? 'nadie'} · datos de ${muestra}`)
  }
  function PantallaDeLaCuenta() { const auth = useAuth(); return h(Pantalla, { key: auth.user?.email ?? 'nadie' }) }
  function Ojo() { tab.ruta = RR.useLocation().pathname; return null }
  const Rutas = rutasComoLaApp(h, RR, useAuth, pantallas, PantallaDeLaCuenta, { '/acceso': Acceso })
  const interior = h(R.Fragment, null, h(Cartel), h(Ojo), h(Rutas))
  const el = () => h(HelmetProvider, null, h(RR.MemoryRouter, { initialEntries: [ruta] },
    h(AuthProvider, null, h(AdvisorProvider, null, interior))))
  antesDeMontar?.()
  const m = await nav.montar(el())
  cur = { m, nav, el, api, uso, tab, href: window.location.href, win: window, ruta: () => tab.ruta }
  return cur
}

const quiereIrse = () => cur.win.location.reload.mock.calls.length > 0 || cur.win.location.href !== cur.href
async function quieta(ms = 400) {
  for (let i = 0; i < Math.ceil(ms / 25); i++) { await esperar(25); try { await cur.m.redibujar(cur.el()) } catch { /* */ } }
}
async function esperarQue(fn, ms = 6000) {
  const t = Date.now()
  while (Date.now() - t < ms) { await quieta(25); if (fn()) return true }
  return false
}
function nodos(raiz, pred) {
  const out = [], pila = [raiz]
  while (pila.length) { const n = pila.shift(); if (pred(n)) out.push(n); pila.push(...(n.childNodes || [])) }
  return out
}
const cartel = () => nodos(cur.m.contenedor, n => n.getAttribute?.('role') === 'alertdialog' || n.atributos?.role === 'alertdialog')[0] || null
const botonDelCartel = (parte) => { const c = cartel(); return c ? nodos(c, n => n.nodeName === 'BUTTON' && cur.nav.texto(n).includes(parte))[0] || null : null }
function otraPestanaEscribe(key, valor) {
  if (valor === null) localStorage.removeItem(key)
  else localStorage.setItem(key, valor)
  window.dispatchEvent(Object.assign(new Event('storage'), { key, newValue: valor }))
}
const enComun = () => { try { return JSON.parse(localStorage.getItem('rendi_user') || 'null')?.email ?? null } catch { return null } }
const enActo = (fn) => cur.nav.enActo(fn)
const enLaPantalla = () => !RUTAS_DE_ENTRADA.includes(cur.tab.ruta)
const entrarPor = (puerta, u) => entrarPorLaPantalla(puerta, u, { cargar, cur: () => cur, srv, quieta })

function navegadorLimpio() {
  mapas = { local: new Map(), sesion: new Map() }
  reiniciarServidor()
  mapas.local.set('rendi:tour:novedades:v2', '1')
}
async function abiertaComo(u) {
  navegadorLimpio()
  srv.me = u; mapas.local.set('rendi_user', guardado(u))
  await cargar('/dashboard')
  expect(await esperarQue(() => cur.tab.pantalla?.muestra === u.email), 'la pantalla muestra lo suyo').toBe(true)
}
// Ana sigue tocando en su pestaña (compra, mes, envío automático, lectura).
async function anaToca(veces, { sigueLaRecarga = false } = {}) {
  let pidio = null
  for (let i = 0; i < veces; i++) {
    const p = cur.tab.pantalla
    try { await enActo(() => [p.compra, p.mes, p.automatico, p.leer][i % 4]()) } catch { /* freno o servidor */ }
    await esperar(60)
    if (sigueLaRecarga && quiereIrse()) {
      pidio ??= Date.now()
      if (Date.now() - pidio >= 100) { await cargar('/dashboard'); pidio = null }
    }
  }
}
const enOtraCuenta = (desde) => srv.escrituras.slice(desde).filter(e => e.cuenta !== e.muestra)

describe('cada pantalla de entrada deja la pestaña con su dueño', () => {
  for (const puerta of Object.keys(PUERTAS)) {
    for (const recarga of ['frenada', 'sigue']) {
      it(`Ana entra por «${puerta}» y después entra Bruno en otra pestaña (la recarga ${recarga}): nada de Ana va a Bruno`, async () => {
        for (let vez = 0; vez < VECES; vez++) {
          navegadorLimpio()
          expect(await entrarPor(puerta, ANA), 'salió de la pantalla de entrada').toBe(true)
          expect(await esperarQue(() => enLaPantalla() && cur.tab.pantalla?.muestra === ANA.email), 'muestra lo de Ana').toBe(true)
          // La persona la dijo el servidor, no la pantalla: también con «restablecer», que no tiene el email.
          expect(cur.api.personaDeLaPestana(), 'la pestaña quedó de Ana').toBe(ANA.email)
          const n = srv.escrituras.length
          srv.me = BRUNO                                    // Bruno entra en otra pestaña: la cookie ya es suya
          const b = (async () => { await esperar([150, 0, 400][vez % 3]); otraPestanaEscribe('rendi_user', guardado(BRUNO)) })()
          await anaToca(8, { sigueLaRecarga: recarga === 'sigue' })
          await b
          await quieta(1800)
          expect(enOtraCuenta(n), 'algo de la pantalla de Ana guardado en la cuenta de Bruno').toEqual([])
          if (cur.tab.pantalla?.user?.name === 'Ana' && enLaPantalla()) expect(cartel(), 'muestra a Ana con la sesión de Bruno: con cartel').toBeTruthy()
          expect(srv.sinPersona, 'pedidos que salieron sin decir de quién son').toEqual([])
        }
      }, 120000)
    }
  }

  it('entrar por cada puerta y recargar tres veces: ni cartel, ni recargas, ni rechazos', async () => {
    for (const puerta of Object.keys(PUERTAS)) {
      navegadorLimpio()
      expect(await entrarPor(puerta, ANA), puerta).toBe(true)
      await esperarQue(() => enLaPantalla() && cur.tab.pantalla?.muestra === ANA.email)
      for (let i = 0; i < 3; i++) {
        await cargar('/dashboard')
        expect(await esperarQue(() => cur.tab.pantalla?.muestra === ANA.email, 3000), `${puerta}: F5 ${i + 1}`).toBe(true)
        expect(quiereIrse(), `${puerta}: se quiso recargar sola`).toBe(false)
      }
      const n = srv.escrituras.length
      await enActo(() => cur.tab.pantalla.compra())
      expect(srv.escrituras.slice(n).map(e => e.cuenta), puerta).toEqual([ANA.email])
      expect(cartel(), puerta).toBe(null)
      expect(srv.sinPersona, puerta).toEqual([])
    }
  }, 120000)
})

describe('el cartel no cierra una sesión ajena', () => {
  for (const variante of ['entra Bruno', 'entra Bruno y después otra pestaña entra al demo']) {
    it(`la recarga queda frenada y ${variante}: «Cerrar sesión» no aparece y la sesión de Bruno sigue`, async () => {
      await abiertaComo(ANA)
      srv.me = BRUNO
      otraPestanaEscribe('rendi_user', guardado(BRUNO))
      otraPestanaEscribe(`rendi_lastvisit_diagnostico:${BRUNO.email}|propia`, '{"t":2}')
      await quieta(400)
      if (variante.includes('demo')) { otraPestanaEscribe('rendi_demo_mode', String(Date.now())); await quieta(400) }
      await quieta(1700)                                   // la recarga no se hizo («¿Salir del sitio?»)
      expect(botonDelCartel('Recargar'), 'la salida es recargar').toBeTruthy()
      expect(botonDelCartel('Cerrar sesión'), 'no ofrece cerrar una sesión que es de Bruno').toBe(null)
      expect(srv.me?.email).toBe(BRUNO.email)
      expect(mapas.local.has(`rendi_lastvisit_diagnostico:${BRUNO.email}|propia`), 'lo de Bruno').toBe(true)
    }, 60000)
  }

  it('con el demo abierto en otra pestaña y la sesión todavía de Ana, «Cerrar sesión» sí aparece y cierra la de Ana', async () => {
    await abiertaComo(ANA)
    otraPestanaEscribe('rendi_demo_mode', String(Date.now()))
    await quieta(400)
    const cerrar = botonDelCartel('Cerrar sesión')
    expect(cerrar, 'la sesión del navegador es la de esta pestaña').toBeTruthy()
    await enActo(() => cur.nav.clic(cur.m.contenedor, cerrar))
    await quieta(100)
    expect(srv.logouts.at(-1), 'cerró la de Ana, diciendo que es Ana').toEqual({ persona: ANA.email, cerro: ANA.email })
  }, 60000)
})

describe('un 401 tardío no borra a quien entró después', () => {
  for (const salida of ['get', 'post', 'getBlob', 'upload']) {
    it(`por ${salida}`, async () => {
      await abiertaComo(ANA)
      srv.me = null                                         // la sesión de Ana vence sola
      srv.demoraUna = 250                                   // y el servidor tarda en contestar ese pedido
      const a = cur.api.api
      const pedido = (salida === 'get' ? a.get('/positions')
        : salida === 'post' ? a.post('/monthly', { muestra: ANA.email })
          : salida === 'getBlob' ? a.getBlob('/export/csv')
            : a.upload('/imports/preview', new FormData())).catch(() => {})
      await esperar(60)
      srv.me = BRUNO                                        // mientras tanto entra Bruno en otra pestaña
      otraPestanaEscribe('rendi_user', guardado(BRUNO))
      await enActo(() => pedido)
      expect(enComun(), 'Bruno sigue logueado').toBe(BRUNO.email)
    }, 60000)
  }

  it('por el «¿quién soy?» al abrir', async () => {
    for (let vez = 0; vez < 3; vez++) {
      navegadorLimpio()
      mapas.local.set('rendi_user', guardado(ANA))         // la sesión de Ana ya venció (sin cookie)
      srv.demoraMe = 250
      const carga = cargar('/dashboard')
      await esperar(40 + vez * 60)
      srv.me = BRUNO                                        // mientras tanto entra Bruno en otra pestaña
      otraPestanaEscribe('rendi_user', guardado(BRUNO))
      await carga
      await esperar(400)
      expect(enComun(), `vez ${vez}: Bruno sigue logueado`).toBe(BRUNO.email)
    }
  }, 60000)
})

describe('cerrar sesión decide por el dueño', () => {
  it('la métrica de uso y el «cerrar sesión» salen diciendo de quién son', async () => {
    await abiertaComo(ANA)
    await enActo(async () => { window.dispatchEvent(new Event('pointerdown')); cur.uso.registrarPantalla?.('/dashboard'); cur.uso.registrarPantalla?.('/cartera') })
    await quieta(100)
    await enActo(() => cur.tab.pantalla.logout())
    await quieta(150)
    expect(srv.usos.map(u => u.persona)).toEqual(srv.usos.map(() => ANA.email))
    expect(srv.logouts).toEqual([{ persona: ANA.email, cerro: ANA.email }])
    expect(srv.me).toBe(null)
  }, 60000)

  it('Ana cierra sesión justo cuando Bruno está entrando en otra pestaña: la sesión de Bruno sigue', async () => {
    await abiertaComo(ANA)
    srv.me = BRUNO                                          // su /login ya puso la cookie; lo guardado todavía no
    await enActo(() => cur.tab.pantalla.logout())
    await quieta(150)
    expect(srv.logouts[0]?.persona, 'el pedido dice que es de Ana').toBe(ANA.email)
    expect(srv.me?.email, 'la sesión de Bruno').toBe(BRUNO.email)
    expect(srv.usos.filter(u => u.cuenta === BRUNO.email), 'el uso de Ana no se le anota a Bruno').toEqual([])
  }, 60000)
})

describe('el demo no toca la sesión de la cuenta real', () => {
  for (const como of ['saliendo del demo', 'con «Cerrar sesión» adentro del demo']) {
    it(`una pestaña en el demo y Ana logueada en otra: ${como} no borra la sesión guardada de Ana`, async () => {
      navegadorLimpio()
      srv.me = ANA
      mapas.local.set('rendi_user', guardado(ANA))         // Ana, en otra pestaña
      mapas.local.set(`rendi_lastvisit_diagnostico:${ANA.email}|propia`, '{"t":1}')
      mapas.local.set('rendi_demo_mode', String(Date.now()))
      await cargar('/dashboard')
      await esperarQue(() => cur.tab.pantalla?.user?.demo)
      await enActo(() => (como.includes('Cerrar') ? cur.tab.pantalla.logout() : cur.tab.pantalla.exitDemo()))
      await quieta(100)
      expect(enComun(), 'la sesión guardada de Ana').toBe(ANA.email)
      expect(mapas.local.has(`rendi_lastvisit_diagnostico:${ANA.email}|propia`), 'lo de Ana').toBe(true)
      expect(srv.me?.email, 'su sesión').toBe(ANA.email)
      expect(srv.logouts, 'el demo no cierra la sesión real').toEqual([])
    }, 60000)
  }
})

describe('una pestaña que muestra una cuenta sin saber de quién es, frena', () => {
  it('al abrir, lo guardado cambia entre que se carga el código y se dibuja: la pestaña es de quien muestra', async () => {
    for (const demora of [0, 30]) {
      navegadorLimpio()
      // En otra pestaña alguien salió (no hay nadie guardado) y entra Bruno
      // justo mientras ésta abre: el código se carga sin nadie y la pantalla se
      // dibuja con Bruno.
      await cargar('/dashboard', { antesDeMontar: () => { srv.me = BRUNO; mapas.local.set('rendi_user', guardado(BRUNO)) } })
      await esperar(demora)
      await quieta(800)
      if (quiereIrse()) { await cargar('/dashboard'); await quieta(600) }
      if (cur.tab.pantalla?.user?.email === BRUNO.email) expect(cur.api.personaDeLaPestana(), 'muestra a Bruno: la pestaña es de Bruno').toBe(BRUNO.email)
      const n = srv.escrituras.length
      try { await enActo(() => cur.tab.pantalla.compra()) } catch { /* frenada */ }
      expect(srv.sinPersona, 'pedidos sin decir de quién son').toEqual([])
      expect(enOtraCuenta(n)).toEqual([])
    }
  }, 60000)

  it('si algo deja la pestaña «de nadie» mostrando a Ana (el olvido de una pantalla), no sale nada a nombre de nadie', async () => {
    await abiertaComo(ANA)
    // Lo que hacía «restablecer la contraseña» hasta el re-test 7: la pantalla
    // muestra a Ana y la pestaña no sabe de quién es.
    cur.api.fijarPersonaDeLaPestana(null)
    const n = srv.escrituras.length
    srv.me = BRUNO                                          // y después entra Bruno en otra pestaña
    const b = (async () => { await esperar(200); otraPestanaEscribe('rendi_user', guardado(BRUNO)) })()
    await anaToca(6)
    await b
    await quieta(300)
    expect(srv.sinPersona, 'pedidos que salieron sin decir de quién son').toEqual([])
    expect(enOtraCuenta(n), 'algo de Ana guardado en la cuenta de Bruno').toEqual([])
    expect(quiereIrse(), 'la pestaña se recarga para volver a preguntar quién es').toBe(true)
  }, 60000)
})

// 🔴 El pedido de acceso del asesor (/acceso, el link «Ver el pedido» del mail):
// la vista previa salía sin decir de quién era la pestaña y el servidor veía
// «nadie logueado»; el cliente adentro leía «entrá a tu cuenta» y nunca podía
// aceptar (re-test a ciegas 9). Por la pantalla de verdad, con y sin sesión.
describe('el pedido de acceso del asesor', () => {
  const texto = () => cur.nav.texto(cur.m.contenedor)
  const tocar = async (parte) => {
    const b = cur.nav.buscarBoton(cur.m.contenedor, parte)
    expect(b, `no hay botón «${parte}»: ${texto().slice(0, 200)}`).toBeTruthy()
    await enActo(() => cur.nav.clic(cur.m.contenedor, b))
  }
  async function abrirElLink(u) {
    navegadorLimpio()
    if (u) { srv.me = u; mapas.local.set('rendi_user', guardado(u)) }
    await cargar('/acceso?token=tok-acceso')
    expect(await esperarQue(() => /Darle acceso|Para aceptar|Estás con otra cuenta/.test(texto())), texto().slice(0, 200)).toBe(true)
  }

  it('Ana, ya adentro, ve «Darle acceso», acepta, y la respuesta sale con su persona', async () => {
    await abrirElLink(ANA)
    expect(srv.previews.at(-1)).toEqual({ persona: ANA.email, cookie: ANA.email })
    expect(texto()).toContain('Darle acceso')
    await tocar('Darle acceso')
    expect(await esperarQue(() => srv.respuestas.length > 0)).toBe(true)
    expect(srv.respuestas).toEqual([{ accept: true, cuenta: ANA.email, persona: ANA.email }])
    expect(await esperarQue(() => /Listo/.test(texto()))).toBe(true)
    expect(srv.sinPersona).toEqual([])
  })

  it('Bruno adentro (no es el dueño): «estás con otra cuenta», y no acepta por Ana', async () => {
    await abrirElLink(BRUNO)
    expect(srv.previews.at(-1)).toEqual({ persona: BRUNO.email, cookie: BRUNO.email })
    expect(texto()).toContain('Estás con otra cuenta')
    expect(texto()).not.toContain('Darle acceso')
    expect(srv.respuestas).toEqual([])
  })

  it('sin sesión: «entrá a tu cuenta»; rechazar sin entrar sale y queda rechazado', async () => {
    await abrirElLink(null)
    expect(srv.previews.at(-1)).toEqual({ persona: null, cookie: null })
    expect(texto()).toContain('Para aceptar, entrá a tu cuenta')
    await tocar('Rechazar sin entrar')
    expect(await esperarQue(() => srv.respuestas.length > 0)).toBe(true)
    expect(srv.respuestas).toEqual([{ accept: false, cuenta: null, persona: null }])
    expect(await esperarQue(() => /Pedido rechazado/.test(texto()))).toBe(true)
  })

  it('sin sesión: «Iniciar sesión» lleva a entrar, y al volver al link Ana acepta', async () => {
    await abrirElLink(null)
    await tocar('Iniciar sesión')
    expect(await esperarQue(() => cur.tab.ruta === '/login')).toBe(true)
    expect(await entrarPor('iniciar sesión', ANA)).toBe(true)
    // El token quedó guardado en la pestaña: el link vuelve a abrir el pedido.
    await cargar('/acceso')
    expect(await esperarQue(() => /Darle acceso/.test(texto())), texto().slice(0, 200)).toBe(true)
    await tocar('Darle acceso')
    expect(await esperarQue(() => srv.respuestas.length > 0)).toBe(true)
    expect(srv.respuestas).toEqual([{ accept: true, cuenta: ANA.email, persona: ANA.email }])
    expect(srv.sinPersona).toEqual([])
  })
})
