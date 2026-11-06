// ¿Qué le llega DE VERDAD a Google Analytics y al píxel de Meta?
//
// Corre los programas reales de Google (gtag.js, con la configuración de la
// propiedad de Rendi adentro) y de Meta (fbevents.js + la configuración del
// píxel de Rendi) junto con los archivos reales de la pantalla (index.html,
// utils/analytics.js, utils/metaPixel.js, utils/rutasSensibles.js), en un
// navegador de mentira (jsdom) que dice estar en rendi.finance.
//
// La salida a internet está cortada desde adentro del proceso: cada envío que
// Google o Meta intentan hacer se ANOTA y no sale. Si algo intenta abrir una
// conexión, se corta y se cuenta (la última línea dice cuántos intentos hubo).
//
// Cómo correrlo (05/11/2026; nada de esto toca el repo ni la red al medir):
//   1. Bajar los programas de Google y Meta a una carpeta nueva y vacía (son
//      los que carga rendi.finance; traen la configuración de la propiedad y
//      del píxel de Rendi adentro). Copia del 05/11 en
//      ~/Documents/rendi-archivo/fugas-a-terceros-2026-11-05/vendor/.
//        curl -o gtag.js 'https://www.googletagmanager.com/gtag/js?id=G-DQ8LV6YJPP'
//        curl -o fbevents.js 'https://connect.facebook.net/en_US/fbevents.js'
//        curl -o pixel-config.js 'https://connect.facebook.net/signals/config/1281911210681122?v=2.9.437&r=stable'
//      (el número de versión de la última sale de fbevents.js: "2.9.NNN").
//   2. jsdom en otra carpeta: npm install jsdom@24.1.3
//   3. Desde esta carpeta:
//        node medir.mjs --front <repo>/frontend --vendor <carpeta del 1>
//             --jsdom <carpeta del 2>/node_modules --esbuild <repo>/frontend/node_modules
//             [--sin-historial] [--csp] [--json salida.json]
//      --sin-historial simula la propiedad con «Cambios de página basados en
//      eventos del historial del navegador» apagado; --csp aplica la política de
//      seguridad de vercel.json como el navegador. Para el «antes», --front
//      a una copia de origin/main (git archive <sha> frontend/index.html
//      frontend/src/utils | tar -x -C <carpeta>).
//   sondas.mjs (mismos argumentos) prueba las perillas de Google y Meta.
import net from 'node:net'
import tls from 'node:tls'
import http from 'node:http'
import https from 'node:https'
import dns from 'node:dns'

// ── 1. Red cortada ANTES de cargar nada ─────────────────────────────────────
export const intentosDeSalir = []
const cortar = (nombre) => function () {
  intentosDeSalir.push(nombre)
  throw new Error('RED CORTADA (' + nombre + ')')
}
net.Socket.prototype.connect = cortar('net.Socket.connect')
net.connect = cortar('net.connect')
net.createConnection = cortar('net.createConnection')
tls.connect = cortar('tls.connect')
http.request = cortar('http.request'); http.get = cortar('http.get')
https.request = cortar('https.request'); https.get = cortar('https.get')
dns.lookup = cortar('dns.lookup')
globalThis.fetch = cortar('fetch')

import { readFileSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'

const arg = (k) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : undefined }
const FRONT = path.resolve(arg('front'))
const VENDOR = path.resolve(arg('vendor'))
const JSDOM_DIR = path.resolve(arg('jsdom'))
const ESBUILD_DIR = path.resolve(arg('esbuild'))
export const SALIDA_JSON = arg('json')

const { JSDOM } = createRequire(path.join(JSDOM_DIR, 'x.js'))('jsdom')
const esbuild = createRequire(path.join(ESBUILD_DIR, 'x.js'))('esbuild')

const GTAG_REAL = readFileSync(path.join(VENDOR, 'gtag.js'), 'utf8')
// --sin-historial: la propiedad con «Cambios de página basados en eventos del
// historial del navegador» APAGADO (es exactamente este dato del contenedor).
export const SIN_HISTORIAL = process.argv.includes('--sin-historial')
if (SIN_HISTORIAL && !GTAG_REAL.includes('"vtp_historyEvents":true')) throw new Error('no encontré vtp_historyEvents en gtag.js')
const GTAG = SIN_HISTORIAL ? GTAG_REAL.replace('"vtp_historyEvents":true', '"vtp_historyEvents":false') : GTAG_REAL
const FBEVENTS = readFileSync(path.join(VENDOR, 'fbevents.js'), 'utf8')
const PIXEL_CONFIG = readFileSync(path.join(VENDOR, 'pixel-config.js'), 'utf8')
const HTML = readFileSync(path.join(FRONT, 'index.html'), 'utf8')

// --csp: la política de seguridad de la página (vercel.json, la que rendi.finance
// sirve en cada respuesta), aplicada como la aplica el navegador: lo que va a un
// servidor que no está en su lista NO sale (se anota como bloqueado).
export const CON_CSP = process.argv.includes('--csp')
const CSP = (() => {
  const v = JSON.parse(readFileSync(path.join(FRONT, 'vercel.json'), 'utf8'))
  const h = v.headers.find((x) => x.source === '/(.*)').headers.find((x) => x.key === 'Content-Security-Policy').value
  const d = {}
  for (const parte of h.split(';')) { const [k, ...fuentes] = parte.trim().split(/\s+/); if (k) d[k] = fuentes }
  return d
})()
function permitidoPorCsp(directiva, destino) {
  if (!CON_CSP) return true
  let u
  try { u = new URL(destino) } catch { return false }
  const fuentes = CSP[directiva] || CSP['default-src'] || []
  return fuentes.some((f) => {
    if (f === "'self'") return u.origin === 'https://rendi.finance'
    if (/^[a-z]+:$/.test(f)) return u.protocol === f
    const m = /^(https?):\/\/(\*\.)?([^/]+)$/.exec(f)
    if (!m) return false
    if (u.protocol !== m[1] + ':') return false
    return m[2] ? u.hostname.endsWith('.' + m[3]) : u.hostname === m[3]
  })
}

// El bloque del píxel de index.html, tal cual (misma búsqueda que medicion.test.js).
export const BLOQUE_PIXEL = HTML.match(/<!-- Meta Pixel -->[\s\S]*?<script>([\s\S]*?)<\/script>/)[1]

// ── 2. Los archivos de la pantalla, empaquetados como los empaqueta Vite ────
// (sin el contador de uso, que habla con nuestro servidor y no con terceros).
const entrada = `
  import * as ga from './src/utils/analytics.js'
  import * as mp from './src/utils/metaPixel.js'
  window.__rendi = Object.assign({}, ga, mp)
`
export const paquete = (await esbuild.build({
  stdin: { contents: entrada, resolveDir: FRONT, sourcefile: 'entrada.js', loader: 'js' },
  bundle: true, format: 'iife', platform: 'browser', target: 'es2019', write: false,
  logLevel: 'silent',
  plugins: [{
    name: 'uso-vacio',
    setup(b) {
      b.onResolve({ filter: /^\.\/uso(\.js)?$/ }, () => ({ path: 'uso', namespace: 'vacio' }))
      b.onLoad({ filter: /.*/, namespace: 'vacio' }, () => ({ contents: 'export const registrarUsoGA=()=>{};export const registrarUso=()=>{};', loader: 'js' }))
    },
  }],
})).outputFiles[0].text
await esbuild.stop?.()

// ── 3. Una pestaña nueva de rendi.finance ───────────────────────────────────
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'
export const espera = (ms) => new Promise((r) => setTimeout(r, ms))

export async function abrirPestana({ url, referrer = '', titulo = 'Rendi', cuerpo = '' }) {
  const dom = new JSDOM(
    `<!doctype html><html><head><meta charset="utf-8"><title>${titulo}</title><script></script></head>` +
    `<body>${cuerpo}<div id="root"></div></body></html>`,
    { url, referrer: referrer || undefined, runScripts: 'outside-only', pretendToBeVisual: true },
  )
  const w = dom.window
  const anotados = []
  w.__anotar = (via, destino, cuerpo) => anotados.push({ via, url: String(destino), cuerpo: cuerpo == null ? '' : String(cuerpo) })
  // true si la política de la página deja salir este envío; si no, lo anota como bloqueado.
  w.__csp = (directiva, via, destino, cuerpo) => {
    if (permitidoPorCsp(directiva, String(destino))) return true
    anotados.push({ via: 'bloqueado por la CSP (' + via + ')', url: String(destino), cuerpo: cuerpo == null ? '' : String(cuerpo) })
    return false
  }
  Object.defineProperty(w.navigator, 'userAgent', { configurable: true, get: () => UA })
  // Todas las formas de mandar algo afuera, anotadas y sin salir.
  w.eval(`(function () {
    Object.defineProperty(navigator, 'sendBeacon', { configurable: true, value: function (u, b) { if (__csp('connect-src', 'beacon', u, b)) __anotar('beacon', u, b); return true } });
    window.fetch = function (u, o) {
      var dest = u && u.url ? u.url : u;
      if (!__csp('connect-src', 'fetch', dest, o && o.body)) return Promise.reject(new TypeError('Failed to fetch'));
      __anotar('fetch', dest, o && o.body);
      return Promise.resolve({ ok: true, status: 204, headers: { get: function () { return null } },
        text: function () { return Promise.resolve('') }, json: function () { return Promise.resolve({}) } });
    };
    function XHR() { this.readyState = 0 }
    XHR.prototype.open = function (m, u) { this._u = u; this.readyState = 1 };
    XHR.prototype.setRequestHeader = function () {};
    XHR.prototype.addEventListener = function (t, f) { (this['_' + t] = this['_' + t] || []).push(f) };
    XHR.prototype.send = function (b) {
      var s = this;
      if (!__csp('connect-src', 'xhr', this._u, b)) { setTimeout(function () { s.readyState = 4; s.status = 0; s.onerror && s.onerror(); (s._error || []).forEach(function (f) { f() }) }, 0); return }
      __anotar('xhr', this._u, b);
      setTimeout(function () { s.readyState = 4; s.status = 204; s.responseText = '';
        s.onreadystatechange && s.onreadystatechange(); s.onload && s.onload();
        (s._load || []).forEach(function (f) { f() }) }, 0);
    };
    window.XMLHttpRequest = XHR;
    Object.defineProperty(HTMLImageElement.prototype, 'src', { configurable: true,
      get: function () { return this.getAttribute('src') || '' },
      set: function (v) { if (__csp('img-src', 'imagen', v)) __anotar('imagen', v); this.setAttribute('src', v); var s = this;
        setTimeout(function () { s.onload && s.onload() }, 0) } });
    Object.defineProperty(HTMLIFrameElement.prototype, 'src', { configurable: true,
      get: function () { return this.getAttribute('src') || '' },
      set: function (v) { __anotar('iframe', v); this.setAttribute('src', v) } });
    HTMLFormElement.prototype.submit = function () {
      var f = {}; Array.prototype.forEach.call(this.elements, function (e) { f[e.name] = e.value });
      __anotar('formulario', this.action, JSON.stringify(f));
    };
    var ins = Node.prototype.insertBefore, app = Node.prototype.appendChild;
    function mirar(n) { if (n && n.tagName === 'SCRIPT' && n.getAttribute('src')) __cargarScript(n) }
    Node.prototype.insertBefore = function (n, r) { var x = ins.call(this, n, r); mirar(n); return x };
    Node.prototype.appendChild = function (n) { var x = app.call(this, n); mirar(n); return x };
  })()`)
  // Los <script src> que pide la página: los de Google y Meta, desde la copia local.
  w.__cargarScript = (nodo) => {
    const src = nodo.getAttribute('src')
    setTimeout(() => {
      let codigo = null
      if (src.startsWith('https://www.googletagmanager.com/gtag/js?id=G-DQ8LV6YJPP')) codigo = GTAG
      else if (src === 'https://connect.facebook.net/en_US/fbevents.js') codigo = FBEVENTS
      else if (src.startsWith('https://connect.facebook.net/signals/config/1281911210681122')) codigo = PIXEL_CONFIG
      if (codigo == null) { w.__anotar('script-no-cargado', src); nodo.dispatchEvent(new w.Event('error')); return }
      try { w.eval(codigo) } catch (e) { w.__anotar('script-error', src, String(e && e.message)) }
      nodo.dispatchEvent(new w.Event('load'))
    }, 0)
  }
  return { dom, w, anotados }
}

// Lo que hace la app al abrir una pestaña, en el orden de producción:
// index.html (el bloque del píxel corre antes que la app) → main.jsx
// (initAnalytics, initMetaPixel) → RouteTracker (page_view del primer render)
// → AuthContext (cuando /auth/me contesta: setUserId + setUserProperties).
export async function arrancar(p, { conSesion = true } = {}) {
  p.w.eval(BLOQUE_PIXEL)
  p.w.eval(paquete)
  p.w.__rendi.initAnalytics()
  p.w.__rendi.initMetaPixel()
  await espera(30)
  p.w.__rendi.trackPageView(p.w.location.pathname)
  await espera(30)
  if (conSesion) {
    p.w.__rendi.setUserId(98765)
    p.w.__rendi.setUserProperties({ tier: 'pro', access_mode: 'full' })
  }
  await espera(1500)
}

// Lo que hace React Router + RouteTracker al cambiar de pantalla.
export async function navegar(p, destino) {
  p.w.history.pushState({}, '', destino)
  await espera(30)
  p.w.__rendi.trackPageView(p.w.location.pathname)
  p.w.__rendi.trackMetaPageView()
  // El efecto de RouteTracker que mira [pathname, search] (sólo en el código nuevo).
  if (p.w.__rendi.actualizarDireccionParaGoogle) p.w.__rendi.actualizarDireccionParaGoogle()
  if (p.w.__rendi.sincronizarPixelConLaDireccion) p.w.__rendi.sincronizarPixelConLaDireccion()
  await espera(1500)
}

// setSearchParams(…, { replace: true }): cambia la dirección sin cambiar de pantalla.
export async function cambiarParametros(p, destino) {
  p.w.history.replaceState({}, '', destino)
  await espera(30)
  if (p.w.__rendi.actualizarDireccionParaGoogle) p.w.__rendi.actualizarDireccionParaGoogle()
  if (p.w.__rendi.sincronizarPixelConLaDireccion) p.w.__rendi.sincronizarPixelConLaDireccion()
  await espera(1500)
}

export async function volverConAtras(p) {
  const ev = new p.w.Event('pageshow')
  Object.defineProperty(ev, 'persisted', { value: true })
  p.w.dispatchEvent(ev)
  await espera(1500)
}

export async function cerrarPestana(p) {
  Object.defineProperty(p.w.document, 'visibilityState', { configurable: true, get: () => 'hidden' })
  Object.defineProperty(p.w.document, 'hidden', { configurable: true, get: () => true })
  p.w.document.dispatchEvent(new p.w.Event('visibilitychange'))
  p.w.dispatchEvent(new p.w.Event('pagehide'))
  await espera(1500)
}

// ── 4. Leer lo anotado como lo lee Google / Meta ────────────────────────────
export function leerEnvios(anotados) {
  const envios = []
  for (const a of anotados) {
    if (a.via.startsWith('bloqueado')) { envios.push({ destino: 'NO SALE: ' + a.via, via: a.via, bloqueado: true, todo: { url: a.url.slice(0, 120) } }); continue }
    let u
    try { u = new URL(a.url) } catch { envios.push({ destino: '?', via: a.via, crudo: a.url }); continue }
    const qs = Object.fromEntries(u.searchParams)
    if (/google-analytics\.com|analytics\.google\.com/.test(u.hostname) && /\/g\/collect/.test(u.pathname)) {
      const lineas = a.cuerpo ? a.cuerpo.split(/\r?\n/).filter(Boolean) : ['']
      for (const l of lineas) {
        const ev = { ...qs, ...Object.fromEntries(new URLSearchParams(l)) }
        envios.push({ destino: 'Google Analytics', via: a.via, evento: ev.en, dl: ev.dl, dr: ev.dr, dt: ev.dt, uid: ev.uid, todo: ev })
      }
    } else if (/facebook\.com$/.test(u.hostname) && /^\/tr/.test(u.pathname)) {
      let datos = qs
      if (a.cuerpo && a.via !== 'imagen') {
        try { datos = { ...qs, ...Object.fromEntries(new URLSearchParams(a.cuerpo)) } } catch { /* nada */ }
      }
      envios.push({ destino: 'Meta (facebook.com/tr)', via: a.via, evento: datos.ev, dl: datos.dl, dr: datos.rl, todo: datos })
    } else {
      let cuerpo = a.cuerpo
      envios.push({ destino: u.hostname, via: a.via, evento: '', dl: '', todo: { url: a.url.slice(0, 300), cuerpo: String(cuerpo).slice(0, 600) } })
    }
  }
  return envios
}

export const MARCAS = ['ZZPRIVADO', '73,27', '73%2C27', 'TOKENSECRETO', 'ana.secreta', 'Cliente Secreta', '98765']
export function marcasEn(envio) {
  if (envio.bloqueado) return []
  const texto = JSON.stringify(envio.todo || envio)
  let dec = texto
  try { dec = decodeURIComponent(texto) } catch { /* nada */ }
  return MARCAS.filter((m) => texto.includes(m) || dec.includes(m))
}

export function contar(titulo, envios) {
  console.log(`\n### ${titulo}`)
  if (!envios.length) { console.log('  (no salió nada)'); return }
  for (const e of envios) {
    const marcas = marcasEn(e)
    const extra = e.uid ? ` · user_id=${e.uid}` : ''
    console.log(`  ${marcas.length ? '❌' : '  '} ${e.destino} [${e.via}] ${e.evento || '—'}${extra}`)
    if (e.dl) console.log(`       dirección: ${e.dl}`)
    if (e.dr) console.log(`       de dónde venía: ${e.dr}`)
    if (e.dt) console.log(`       título: ${e.dt}`)
    if (!e.dl && e.todo && e.todo.url) console.log(`       ${e.todo.url}${e.todo.cuerpo ? '  cuerpo: ' + e.todo.cuerpo.slice(0, 200) : ''}`)
    if (marcas.length) console.log(`       lleva: ${marcas.join(', ')}`)
  }
}

