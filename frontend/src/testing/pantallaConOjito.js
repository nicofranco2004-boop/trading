// pantallaConOjito — monta la APP ENTERA (shell + rutas + proveedores de
// verdad) en una ruta, con la cuenta del demo, el ojito de «Ocultar saldos»
// prendido o apagado y la cartera del demo multiplicada por `factor`.
// ═══════════════════════════════════════════════════════════════════════════
// Lo usan las pruebas de __guards__/ocultar-saldos-pantallas-*.render.test.jsx.
//
// POR QUÉ ASÍ
// ───────────
// «¿Este número es tuyo?» no se puede contestar leyendo el código (los
// guardianes viejos buscaban `usePrivacy` en el archivo y daban por revisado
// el inicio, que mostraba la plata en tres tarjetas). Se contesta mirando lo
// dibujado: un monto TUYO es uno que cambia si tenés más plata. Así que cada
// pantalla se dibuja dos veces con el ojito prendido, con la cartera del demo
// tal cual y multiplicada por 3 (cantidades, efectivo, depósitos, lo
// invertido, la historia). Lo que cambia entre los dos dibujos depende de tu
// plata y el ojito lo tendría que tapar. Los precios del mercado, los % y las
// fechas no cambian (multiplicar todo por 3 no cambia un rendimiento ni un
// peso), así que la prueba no los confunde con montos.
//
// Los datos son los del demo (utils/demo.js) y pasan por utils/api.js como en
// producción: ninguna pantalla recibe una respuesta escrita para la prueba.
//
// Lo que se multiplica: TODO número de las respuestas (también los montos con
// moneda escritos dentro de un texto del servidor), salvo los campos cuyo
// nombre dice que es mercado o forma (precio, %, tipo de cambio, fecha, id…:
// NO_ES_PLATA) y las rutas de mercado (RUTAS_DE_MERCADO). Si un campo de
// mercado se multiplicara por error, la prueba da un falso rojo (un precio
// «cambia»): falla cerrada. Lo contrario —un monto tuyo que no se multiplica—
// no se ve: por eso la lista de excepciones es por NOMBRE de campo y corta.
import { vi } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, medidas } from './navegadorMinimo'

export const estado = { factor: 1, pendientes: 0 }

// Campos que no son plata: precios del mercado, %, tipos de cambio, fechas,
// identificadores, contadores. Multiplicarlos no cambia «cuánto tenés». Se
// compara por PEDAZO del nombre (buy_price → buy · price; pnlPct → pnl · pct),
// no por letras sueltas: «day» adentro de «pnl_today» es plata.
export const NO_ES_PLATA = new Set(('id ids price prices precio precios prev close cierre open high low ' +
  'pct percent porcentaje ratio tc fx rate rates tasa tna tea cotizacion year years anio month months mes ' +
  'meses day days dia dias date fecha ts time timestamp count n num score rsi beta vol volatility sigma ' +
  'desvio cagr twr tir ytm duration weight peso share order orden rank index idx semana week version ' +
  'nivel level edad age horizon horizonte cuota quota limit drawdown inflacion cer uva split spread ' +
  'cupon coupon plazo multiplicador factor threshold umbral x y').split(' '))
// Y si el nombre dice plata, es plata aunque tenga otro pedazo de la lista:
// `pnl_day` (el P&L del día) o `value_usd_fx` se multiplican. Sin esto, un campo
// nuevo así quedaba quieto y la prueba no lo vería (auditoría a ciegas, 30/10).
// (No entran «usd»/«ars» solos: `fx_to_usd` es un tipo de cambio.)
export const ES_PLATA = new Set(('pnl value valor amount monto invested invertido capital total ' +
  'cash efectivo saldo balance deposit deposits deposito depositos withdrawal retiro retiros ganancia ' +
  'perdida resultado aportado aporte cobro cobrado dividend dividendo fee comision').split(' '))
const pedazos = (k) => k.split(/[_\-\s]+|(?=[A-Z])/).map(x => x.toLowerCase()).filter(Boolean)
export const noEsPlata = (k) => {
  const p = pedazos(k)
  return !p.some(x => ES_PLATA.has(x)) && p.some(x => NO_ES_PLATA.has(x))
}

// Rutas cuyas respuestas son del mercado o de la cuenta, no de tu plata.
export const RUTAS_DE_MERCADO = [
  '/prices', '/dolar', '/market', '/indices', '/movers', '/news', '/noticias', '/events',
  '/fundamentals', '/price-history', '/heatmap', '/benchmarks', '/plan', '/auth', '/fx',
  '/resumen-mercado', '/watchlist', '/fuera-de-horario', '/search', '/ai/fundamentals',
  // «Lo que te afecta» del inicio: precio, % y fecha de lo que tenés, nunca un
  // monto tuyo (backend/home/briefing.py).
  '/home/',
]

// Un monto escrito ADENTRO de una frase del servidor («Aportaste US$ 2.000 este
// período»): el texto también se multiplica, con el mismo formato.
const MONTO_EN_TEXTO = /(US\$|U\$S|USD|ARS|\$)(\s?[+−-]?)(\d{1,3}(?:\.\d{3})+|\d+)(,\d+)?/g
function escalarTexto(t, f) {
  return t.replace(MONTO_EN_TEXTO, (_, mon, esp, ent, dec = '') => {
    const v = Number(ent.replace(/\./g, '') + (dec ? '.' + dec.slice(1) : '')) * f
    const d = dec ? dec.length - 1 : 0
    return mon + esp + v.toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d })
  })
}

function escalar(v, clave, f) {
  if (typeof v === 'string') return clave && noEsPlata(clave) ? v : escalarTexto(v, f)
  if (typeof v === 'number') return clave && noEsPlata(clave) ? v : v * f
  if (Array.isArray(v)) return v.map(x => escalar(x, clave, f))
  if (v && typeof v === 'object') {
    const out = {}
    for (const [k, x] of Object.entries(v)) out[k] = escalar(x, k, f)
    return out
  }
  return v
}

export function respuestaEscalada(orig, method, path, body) {
  const r = orig(method, path, body)
  if (r === null || estado.factor === 1 || method !== 'GET') return r
  const base = path.split('?')[0]
  if (RUTAS_DE_MERCADO.some(p => base.startsWith(p))) return r
  return escalar(r, null, estado.factor)
}

/**
 * La parte de `vi.mock` que va en cada archivo de prueba (vi.mock no se puede
 * llamar desde otro módulo). Ver ocultar-saldos-pantallas-*.render.test.jsx.
 */
export async function demoEscalado(importOriginal) {
  const orig = await importOriginal()
  return {
    ...orig,
    handleDemoRequest: (m, p, b) => {
      estado.pendientes++
      setTimeout(() => { estado.pendientes-- }, 120)
      return respuestaEscalada(orig.handleDemoRequest, m, p, b)
    },
  }
}

let App, HelmetProvider, ToastProvider, MemoryRouter

/** Instala el navegador mínimo con el ancho pedido e importa la app. */
export async function prepararApp({ ancho = 1280 } = {}) {
  instalarNavegadorMinimo()
  window.innerWidth = ancho
  window.matchMedia = (q) => {
    const max = /max-width:\s*(\d+)px/.exec(q)
    const min = /min-width:\s*(\d+)px/.exec(q)
    const matches = max ? ancho <= Number(max[1]) : min ? ancho >= Number(min[1]) : /reduce/.test(q)
    return { matches, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }
  }
  vi.stubGlobal('matchMedia', window.matchMedia)
  // Todo mide algo: sin tamaño, los gráficos (recharts) no se dibujan y sus
  // ejes —que pueden decir «US$ 42k», tu cartera— quedaban fuera de la prueba
  // (lo encontró el navegador de verdad, 30/10).
  medidas(() => ({ left: 0, top: 0, width: Math.min(ancho, 800), height: 300 }))
  vi.stubGlobal('scrollTo', () => {})
  window.scrollTo = () => {}
  // Las páginas de App.jsx se cargan a pedido (lazy): se traen antes, para que
  // el primer dibujo de cada una no termine en el esqueleto de carga.
  const fs = await import('fs')
  const app = fs.readFileSync(new URL('../App.jsx', import.meta.url), 'utf8')
  for (const m of app.matchAll(/import\('\.\/pages\/(\w+)'\)/g)) await import(`../pages/${m[1]}.jsx`)
  ;({ default: App } = await import('../App'))
  ;({ HelmetProvider } = await import('react-helmet-async'))
  ;({ ToastProvider } = await import('../components/Toast'))
  ;({ MemoryRouter } = await import('react-router-dom'))
}

/**
 * El texto dibujado con un corte entre elemento y elemento: «2024-08-12» y la
 * cantidad «105» de la celda de al lado no se leen como un solo número.
 * Lo de adentro de <style> no es texto de la pantalla.
 */
export function textoConCortes(nodo) {
  if (!nodo) return ''
  if (nodo.nodeType === 3) return nodo.nodeValue
  if (nodo.nodeName === 'STYLE' || nodo.nodeName === 'SCRIPT') return ' '
  // Lo que se lee sin estar en el texto: el globo del `title` y lo que dice un
  // lector de pantalla (`aria-label`). Reportes tenía montos ahí.
  const a = nodo.atributos || {}
  const extra = [a.title, a['aria-label']].filter(Boolean).join(' ')
  const propio = !nodo.childNodes?.length
    ? (typeof nodo.textContent === 'string' ? nodo.textContent : '')
    : nodo.childNodes.map(textoConCortes).join(' ')
  return extra ? `${extra} ${propio}` : propio
}

const esperar = (ms) => new Promise(r => setTimeout(r, ms))

/**
 * Dibuja `ruta` y devuelve el texto cuando la pantalla dejó de cambiar (sin
 * pedidos al demo en vuelo y el mismo texto tres vueltas seguidas).
 */
/** ¿Queda algo cargando? El esqueleto de página (PageSkeleton) y las partes
 * que esperan datos se marcan `aria-busy="true"`. */
export function cargando(nodo) {
  const pila = [nodo]
  while (pila.length) {
    const n = pila.pop()
    if (n?.atributos?.['aria-busy'] === 'true') return true
    if (n?.childNodes) pila.push(...n.childNodes)
  }
  return false
}

export async function dibujar(ruta, { ojito, factor = 1, local = {} }) {
  localStorage.clear()
  localStorage.setItem('rendi_demo_mode', String(Date.now()))
  localStorage.setItem('rendi_privacy', ojito ? '1' : '0')
  // El tutorial de la primera visita tapa la pantalla: ya visto.
  localStorage.setItem('rendi_tour_novedades_visto', '1')
  for (const [k, v] of Object.entries(local)) localStorage.setItem(k, v)
  estado.factor = factor
  const el = () => h(HelmetProvider, null, h(ToastProvider, null,
    h(MemoryRouter, { initialEntries: [ruta] }, h(App))))
  const m = await montar(el())
  let antes = null, quietas = 0
  for (let i = 0; i < 150 && (i < 8 || quietas < 6); i++) {
    await esperar(60)
    await m.redibujar(el())
    const t = textoConCortes(m.contenedor)
    quietas = (t === antes && estado.pendientes === 0 && !cargando(m.contenedor)) ? quietas + 1 : 0
    antes = t
  }
  const t = textoConCortes(m.contenedor)
  const sinTerminar = cargando(m.contenedor)
  await m.desmontar()
  // Una pantalla que quedó cargando no prueba nada: con el ojito prendido no
  // tendría montos y daría verde (auditoría a ciegas, 30/10).
  if (sinTerminar) throw new Error(`${ruta}: la pantalla no terminó de cargar`)
  return t.replace(/\s+/g, ' ')
}

// Un número como lo escribe la pantalla: 6.935,58 · 1.623 · 0,25 · 545. Un %
// o unos «pp» no son un monto (multiplicar la cartera no los cambia, y el
// criterio de la Cartera es dejarlos a la vista): no se cuentan. Tampoco los
// dígitos de un nombre (AL30, S&P 500).
const NUMERO = /(?<![\p{L}\d.,])(?<!S&P )\d(?:[\d.]*\d)?(?:,\d+)?(?![\d,])(?!\s?(?:%|pp\b|puntos\b))/gu

/** Los números de un texto, con un poco de lo que tienen alrededor. */
export function numeros(t) {
  const out = []
  for (const m of t.matchAll(NUMERO)) {
    out.push({ n: m[0], ctx: t.slice(Math.max(0, m.index - 40), m.index + m[0].length + 15) })
  }
  return out
}

/**
 * Las cantidades de la cartera del demo multiplicadas por `factor`, escritas
 * como las escribe la pantalla. La Cartera deja la cantidad a la vista con el
 * ojito (es «cuántas acciones», no «cuánta plata»): no cuentan como monto. El
 * efectivo NO entra: su «cantidad» es la plata misma.
 */
export function cantidadesDelDemo(handleDemoRequest, factor) {
  const antes = estado.factor
  estado.factor = 1
  const tenencias = handleDemoRequest('GET', '/positions', null).filter(p => !p.is_cash)
  const filas = [...tenencias, ...handleDemoRequest('GET', '/operations', null)]
  estado.factor = antes
  // Cada lote y también la suma por activo («tenés 62 nominales» de AAPL en
  // dos brokers).
  const porActivo = new Map()
  for (const f of tenencias) if (f.asset && f.quantity > 0) porActivo.set(f.asset, (porActivo.get(f.asset) || 0) + f.quantity)
  const out = new Set()
  for (const quantity of [...filas.map(f => f.quantity), ...porActivo.values()]) {
    if (!(quantity > 0)) continue
    const q = quantity * factor
    out.add(String(q))
    for (const d of [0, 1, 2, 4, 8]) {
      out.add(q.toLocaleString('es-AR', { maximumFractionDigits: d }))
      out.add(q.toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d }))
    }
  }
  return out
}

/**
 * Lo que cambió entre el dibujo con la cartera ×1 y con ×3: los números del
 * segundo que no estaban en el primero (como bolsa: dos «1.250» en uno y uno
 * solo en el otro = cambió uno).
 */
export function loQueCambio(t1, t3, permitidos = new Set()) {
  const bolsa = new Map()
  for (const { n } of numeros(t1)) bolsa.set(n, (bolsa.get(n) || 0) + 1)
  const cambiaron = []
  for (const x of numeros(t3)) {
    const c = bolsa.get(x.n) || 0
    if (c > 0) bolsa.set(x.n, c - 1)
    else if (!permitidos.has(x.n)) cambiaron.push(x)
  }
  return cambiaron
}

/**
 * Dibuja la pantalla con la cartera ×1 y ×3 y devuelve lo que cambió. Si algo
 * cambió, la dibuja OTRA VEZ y se queda con lo que cambió las dos veces: con la
 * máquina cargada, un dibujo puede cortarse antes de que llegue una tarjeta, y
 * lo que falta en uno «cambia» sin depender de tu plata. Un monto tuyo a la
 * vista sale las dos veces.
 */
export async function comparar(p, { ojito, handleDemoRequest, moneda = 'USD' }) {
  const permitidos = cantidadesDelDemo(handleDemoRequest, 3)
  const local = { ...(p.local || {}), rendi_display_currency: moneda }
  const vuelta = async () => {
    const x1 = await dibujar(p.url, { ojito, factor: 1, local })
    const x3 = await dibujar(p.url, { ojito, factor: 3, local })
    return { x1, visibles: loQueCambio(x1, x3, permitidos) }
  }
  const a = await vuelta()
  if (ojito) {
    // Buscando montos a la vista: cuenta lo que cambió en las DOS vueltas.
    if (!a.visibles.length) return a
    const b = await vuelta()
    const enLaOtra = new Set(b.visibles.map(v => v.n))
    return { x1: a.x1, visibles: a.visibles.filter(v => enLaOtra.has(v.n)) }
  }
  // El control (ojito apagado) quiere ver que la plata SÍ cambia: alcanza con
  // una vuelta que lo muestre.
  if (a.visibles.length > 3) return a
  const b = await vuelta()
  return b.visibles.length > a.visibles.length ? b : a
}

/**
 * Las pruebas de __guards__/ocultar-saldos-pantallas-*.render.test.jsx: cada
 * pantalla de la app (testing/pantallasDeLaApp.js), con el ojito prendido, no
 * puede mostrar ningún número que dependa de tu plata.
 *
 * Y para que el verde signifique algo (`conControl`): con el ojito APAGADO las
 * pantallas principales SÍ tienen que mostrar números que cambian con la
 * cartera. Si eso falla, se rompió la prueba (el demo no se multiplica, la
 * pantalla no carga), no la pantalla.
 */
export function revisarPantallas({ describe, it, expect, beforeAll, handleDemoRequest, pantallasDeLaApp, ancho, conControl,
                                   moneda = 'USD' }) {
  const { pantallas, sinDecidir } = pantallasDeLaApp()
  const nombre = (p) => p.url + (p.local ? ` (${Object.values(p.local).join(', ')})` : '')

  beforeAll(async () => { await prepararApp({ ancho }) }, 120000)

  describe(`«Ocultar saldos» en cada pantalla (${ancho} px, en ${moneda})`, () => {
    it('toda ruta de App.jsx con parámetro tiene con qué abrirse o un porqué para no mirarla', () => {
      expect(sinDecidir).toEqual([])
    })

    for (const p of pantallas) {
      it(`${nombre(p)}: con el ojito prendido no se ve ningún monto tuyo`, async () => {
        const { x1, visibles } = await comparar(p, { ojito: true, handleDemoRequest, moneda })
        expect(x1.length, 'la pantalla no dibujó nada').toBeGreaterThan(200)
        expect(visibles.map(v => `${v.n}  «${v.ctx}»`), 'montos a la vista con el ojito prendido').toEqual([])
      }, 120000)
    }

    if (conControl) {
      // Las pantallas donde la plata se ve sí o sí con el ojito apagado.
      const CONTROL = ['/dashboard', '/posiciones', '/operaciones', '/activo/NVDA', '/mensual', '/analisis?tab=diagnostico']
      for (const url of CONTROL) {
        it(`control: ${url} con el ojito APAGADO sí muestra tu plata (si no, la prueba no prueba nada)`, async () => {
          const p = pantallas.find(x => x.url === url)
          expect(p, `${url} ya no está entre las pantallas de App.jsx`).toBeTruthy()
          const { visibles } = await comparar(p, { ojito: false, handleDemoRequest, moneda })
          expect(visibles.length).toBeGreaterThan(3)
        }, 120000)
      }
    }
  })
}
