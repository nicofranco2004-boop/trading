// navegadorMinimo — lo justo de un navegador para MONTAR proveedores de React
// en las pruebas.
// ═══════════════════════════════════════════════════════════════════════════
// Las pruebas del frontend corren en node, sin navegador (no hay jsdom
// instalado). Sin esto, de un proveedor como VozContext sólo se podía leer el
// código como texto: una prueba que busca `addEventListener(...)` en el fuente
// pasa aunque esa línea esté comentada, y no ve el orden de los efectos ni qué
// viaja de verdad al servidor. Con esto, react-dom monta el proveedor real,
// corren sus efectos, y la prueba hace lo mismo que el usuario: entra a un
// cliente, pregunta, cierra sesión, otra pestaña cambia algo.
//
// Tiene sólo lo que react-dom y los proveedores tocan hoy. Si un componente
// nuevo pide algo más del DOM, se agrega acá (el error dice qué falta).
//
// Sólo lo importan pruebas: no entra al build de la app.

import { vi } from 'vitest'

class Nodo {
  constructor(tag, doc) {
    this.nodeName = this.tagName = tag.toUpperCase()
    this.nodeType = 1
    this.namespaceURI = 'http://www.w3.org/1999/xhtml'
    this.ownerDocument = doc
    this.parentNode = null
    this.childNodes = []
    this.style = estilo()
    this.atributos = {}
    this.escuchas = {}
  }
  get firstChild() { return this.childNodes[0] || null }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null }
  appendChild(hijo) {
    if (hijo.parentNode) hijo.parentNode.removeChild(hijo)
    hijo.parentNode = this
    this.childNodes.push(hijo)
    return hijo
  }
  insertBefore(hijo, antesDe) {
    if (!antesDe) return this.appendChild(hijo)
    if (hijo.parentNode) hijo.parentNode.removeChild(hijo)
    hijo.parentNode = this
    this.childNodes.splice(this.childNodes.indexOf(antesDe), 0, hijo)
    return hijo
  }
  removeChild(hijo) {
    this.childNodes = this.childNodes.filter(n => n !== hijo)
    hijo.parentNode = null
    return hijo
  }
  setAttribute(k, v) { this.atributos[k] = String(v) }
  getAttribute(k) { return k in this.atributos ? this.atributos[k] : null }
  removeAttribute(k) { delete this.atributos[k] }
  hasAttribute(k) { return k in this.atributos }
  addEventListener(tipo, fn) { (this.escuchas[tipo] ||= []).push(fn) }
  removeEventListener(tipo, fn) { this.escuchas[tipo] = (this.escuchas[tipo] || []).filter(f => f !== fn) }
  // Medidas: acá nada ocupa lugar (las pantallas que se miden, como /ai, no
  // explotan; el número no importa en estas pruebas).
  getBoundingClientRect() { return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0 } }
  // Lo que usan los formularios (pages/dobleClick.test.js): el foco de un
  // `autoFocus`, el `value` de un <option> y la lista de opciones de un <select>.
  focus() {}
  blur() {}
  get value() { return this._valor !== undefined ? this._valor : (this.atributos.value ?? '') }
  set value(v) { this._valor = String(v) }
  get options() {
    const out = []
    const recorrer = (n) => {
      for (const h of n.childNodes || []) {
        if (h.nodeName === 'OPTION') out.push(h)
        else if (h.nodeName === 'OPTGROUP') recorrer(h)
      }
    }
    recorrer(this)
    return out
  }
  // Lo que usa el <audio> de VozContext. `src` es el atributo, como en el DOM.
  get src() { return this.atributos.src || '' }
  set src(v) { this.atributos.src = String(v) }
  load() {}
  pause() { this.paused = true }
  play() { this.paused = false; return Promise.resolve() }
}

// `style` con lo que React usa para las variables CSS (`--x`).
function estilo() {
  const s = {}
  Object.defineProperties(s, {
    setProperty: { value(k, v) { this[k] = v } },
    removeProperty: { value(k) { delete this[k] } },
    getPropertyValue: { value(k) { return this[k] ?? '' } },
  })
  return s
}

function almacen(mapa) {
  return {
    getItem: k => (mapa.has(k) ? mapa.get(k) : null),
    setItem: (k, v) => { mapa.set(k, String(v)) },
    removeItem: k => { mapa.delete(k) },
    clear: () => mapa.clear(),
    key: i => [...mapa.keys()][i] ?? null,
    get length() { return mapa.size },
  }
}

/**
 * Instala window, document, localStorage y sessionStorage. Hay que llamarla
 * ANTES de importar los módulos que miran `window` al cargarse (utils/api.js
 * registra ahí el escucha de "otra pestaña cambió el cliente").
 * Devuelve los dos almacenes como Map, para mirarlos o sembrarlos.
 */
export function instalarNavegadorMinimo() {
  const local = new Map()
  const sesion = new Map()
  const win = new EventTarget()
  const doc = {
    createElement: tag => new Nodo(tag, doc),
    createElementNS: (_, tag) => new Nodo(tag, doc),
    createTextNode: texto => ({ nodeType: 3, nodeValue: texto, textContent: texto, parentNode: null }),
    addEventListener() {},
    removeEventListener() {},
    activeElement: null,
    defaultView: win,
  }
  doc.body = new Nodo('body', doc)
  doc.documentElement = new Nodo('html', doc)
  Object.assign(win, {
    document: doc,
    HTMLIFrameElement: class {},
    location: { href: 'http://localhost/', pathname: '/', search: '', hash: '', reload: vi.fn() },
    navigator: globalThis.navigator,
    localStorage: almacen(local),
    sessionStorage: almacen(sesion),
    scrollY: 0,
  })
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  // El reloj de las animaciones (los números que cuentan, AnimatedNumber): un
  // cuadro cada 16 ms, como un navegador a 60 por segundo.
  const cuadro = (fn) => setTimeout(() => fn(performance.now()), 16)
  win.requestAnimationFrame = cuadro
  win.cancelAnimationFrame = clearTimeout
  vi.stubGlobal('requestAnimationFrame', cuadro)
  vi.stubGlobal('cancelAnimationFrame', clearTimeout)
  vi.stubGlobal('window', win)
  vi.stubGlobal('document', doc)
  vi.stubGlobal('localStorage', win.localStorage)
  vi.stubGlobal('sessionStorage', win.sessionStorage)
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  return { local, sesion }
}

/**
 * OTRA pestaña escribió en el localStorage compartido: cambia el dato y le
 * llega a ésta el evento `storage`, como en el navegador. `key` null = borró
 * todo; `valor` null = borró esa clave.
 */
export function otraPestanaEscribe(key, valor) {
  if (key === null) localStorage.clear()
  else if (valor === null) localStorage.removeItem(key)
  else localStorage.setItem(key, valor)
  window.dispatchEvent(Object.assign(new Event('storage'), { key, newValue: valor }))
}

/**
 * Monta un elemento con react-dom y devuelve cómo redibujarlo o desmontarlo.
 * `raiz.render` queda a mano para usarlo DENTRO de un enActo junto con otros
 * cambios, cuando tienen que caer en el mismo dibujo (como en un click real).
 */
export async function montar(elemento) {
  const { act } = await import('react')
  const { createRoot } = await import('react-dom/client')
  const contenedor = document.createElement('div')
  const raiz = createRoot(contenedor)
  await act(async () => { raiz.render(elemento) })
  return {
    raiz,
    contenedor,
    redibujar: (otro) => act(async () => { raiz.render(otro) }),
    desmontar: () => act(async () => { raiz.unmount() }),
  }
}

/** El primer elemento con esa etiqueta dentro de lo montado (p. ej. 'audio'). */
export function buscar(contenedor, etiqueta) {
  const T = etiqueta.toUpperCase()
  const pila = [contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === T) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

/** El texto visible de un nodo (lo que React escribió como texto o como hijos). */
export function texto(nodo) {
  if (!nodo) return ''
  if (nodo.nodeType === 3) return nodo.nodeValue
  if (!nodo.childNodes.length && typeof nodo.textContent === 'string') return nodo.textContent
  return nodo.childNodes.map(texto).join('')
}

/** El primer botón cuyo texto contiene `parte`. */
export function buscarBoton(contenedor, parte) {
  const pila = [contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && texto(n).includes(parte)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

/**
 * Un click como el del navegador: el evento entra por el escucha que React
 * puso en la raíz —no se llama a `onClick` a mano—, así que un botón con
 * `disabled` lo ignora igual que en la pantalla. Dos `clic` dentro del MISMO
 * `enActo` son dos clicks del mismo turno: React no redibujó entre uno y otro,
 * que es justo el doble click que el `disabled` solo no frena.
 */
export function clic(contenedor, nodo) {
  const ev = {
    type: 'click', target: nodo, bubbles: true, cancelable: true, button: 0,
    defaultPrevented: false, timeStamp: Date.now(),
    preventDefault() { this.defaultPrevented = true },
    stopPropagation() {},
  }
  for (const fn of contenedor.escuchas.click || []) fn(ev)
}

/** Corre algo que cambia estado de React y espera a que se dibuje. */
export async function enActo(fn) {
  const { act } = await import('react')
  let r
  await act(async () => { r = await fn() })
  return r
}
