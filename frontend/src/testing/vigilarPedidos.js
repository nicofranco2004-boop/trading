// vigilarPedidos — corre antes de CADA archivo de prueba (vite.config.js,
// test.setupFiles): todo pedido a /api que la app haga en cualquier prueba
// tiene que haber salido por la puerta única (utils/api, pedirAlServidor).
// ═══════════════════════════════════════════════════════════════════════════
// 🔴 POR QUÉ (re-test a ciegas 9, 31/10). La vista previa del pedido de acceso
// del asesor (/acceso) salía con un `fetch` suelto que no decía de quién era la
// pestaña; el servidor la tomó por alguien sin sesión y el cliente nunca podía
// aceptar. No lo vio ningún guardián: miraban POR ARCHIVO si aparecía el texto
// del encabezado, y el otro `fetch` del mismo archivo sí lo tenía. Esto no
// busca textos: mira los pedidos que de verdad salen mientras corre la prueba.
//
// La regla: un pedido a /api sin la marca `X-Rendi-Version` no pasó por la
// puerta —que la pone siempre, junto con la persona de la pestaña cuando la
// sabe—, y la prueba que lo hizo da rojo, sea cual sea. No hay excepciones:
// hasta las pantallas de entrada y lo público salen por la puerta.
//
// Funciona aunque la prueba reemplace `fetch` por el suyo (`vi.stubGlobal` o
// `globalThis.fetch = …`): lo que pone se envuelve sin cambiarle nada —sus
// `.mock.calls` y sus `expect(fetch)` siguen andando—.
// Lo que no ve: un `XMLHttpRequest`, un `<img src="/api…">` o un formulario
// HTML. Hoy no hay ninguno (lo vigila __guards__/envios-con-dueno.test.js).
import { afterAll, afterEach, vi } from 'vitest'

const MARCA = 'x-rendi-version'
const BASE = 'http://rendi.prueba'
let faltas = []

function rutaPropia(entrada) {
  const url = typeof entrada === 'string' ? entrada : (entrada?.url ?? String(entrada ?? ''))
  try {
    const u = new URL(url, BASE)
    return u.origin === BASE ? u.pathname : null       // otro sitio: no es nuestro servidor
  } catch { return null }
}

function tieneMarca(entrada, init) {
  const h = init?.headers ?? entrada?.headers
  if (!h) return false
  if (typeof h.get === 'function') return h.get(MARCA) != null
  if (Array.isArray(h)) return h.some(([k]) => String(k).toLowerCase() === MARCA)
  return Object.keys(h).some((k) => k.toLowerCase() === MARCA)
}

function revisar(entrada, init) {
  const ruta = rutaPropia(entrada)
  if (!ruta || !ruta.startsWith('/api/')) return
  if (!tieneMarca(entrada, init)) faltas.push(`${(init?.method || entrada?.method || 'GET').toUpperCase()} ${ruta}`)
}

const envueltas = new WeakMap()
const nuestras = new WeakSet()
function vigilada(fn) {
  if (typeof fn !== 'function' || nuestras.has(fn)) return fn
  if (envueltas.has(fn)) return envueltas.get(fn)
  const p = new Proxy(fn, {
    apply(destino, esto, args) { revisar(args[0], args[1]); return Reflect.apply(destino, esto, args) },
  })
  envueltas.set(fn, p)
  nuestras.add(p)
  return p
}

let actual = globalThis.fetch
Object.defineProperty(globalThis, 'fetch', {
  configurable: true,
  enumerable: true,
  get: () => vigilada(actual),
  set: (v) => { actual = v },
})
const stubOriginal = vi.stubGlobal.bind(vi)
vi.stubGlobal = (nombre, valor) => stubOriginal(nombre, nombre === 'fetch' ? vigilada(valor) : valor)

/** Los pedidos que salieron por fuera de la puerta desde la última vez (y los
 *  olvida). Para la prueba de este vigía. */
export function pedidosPorFueraDeLaPuerta() {
  const out = faltas
  faltas = []
  return out
}

function rojoSiHubo() {
  const lista = [...new Set(pedidosPorFueraDeLaPuerta())]
  if (!lista.length) return
  throw new Error('Pedidos a /api que no salieron por la puerta única (utils/api, pedirAlServidor): '
    + 'no dicen de quién es la pestaña ni de qué versión de la web son, y el servidor los atiende con '
    + 'la sesión del navegador, sea de quien sea.\n  ' + lista.join('\n  '))
}

afterEach(rojoSiHubo)
afterAll(rojoSiHubo)
