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

let medidor = () => null

/**
 * Dónde está y cuánto mide cada elemento SIN desplazar: `fn(nodo)` devuelve
 * { left, top, width, height } o null (= no ocupa lugar). Sin argumento,
 * vuelve a que nada ocupe lugar.
 */
export function medidas(fn) { medidor = fn || (() => null) }

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
  // `enCaptura`: React engancha cada evento DOS veces en la raíz, una para la
  // fase de bajada (onClickCapture) y otra para la de subida (onClick). Hay
  // que saber cuál es cuál para llamarlas en el orden del navegador.
  addEventListener(tipo, fn, opc) {
    (this.escuchas[tipo] ||= []).push(fn)
    if (opc === true || opc?.capture) (this.enCaptura ||= new Set()).add(fn)
  }
  removeEventListener(tipo, fn) { this.escuchas[tipo] = (this.escuchas[tipo] || []).filter(f => f !== fn) }
  // "Agarrar" el puntero: mientras alguien lo tenga agarrado, el navegador le
  // manda a ÉL los eventos de ese puntero, esté donde esté. Ver `puntero`.
  setPointerCapture(id) { this.ownerDocument.capturas.set(id, this) }
  releasePointerCapture(id) { if (this.ownerDocument.capturas.get(id) === this) this.ownerDocument.capturas.delete(id) }
  hasPointerCapture(id) { return this.ownerDocument.capturas.get(id) === this }
  // Medidas: por defecto nada ocupa lugar (las pantallas que se miden, como
  // /ai, no explotan; el número no importa en esas pruebas). Una prueba que SÍ
  // necesita tamaños los da con `medidas(fn)`; el desplazamiento de
  // `transform: translate3d(...)` se suma encima, como en el navegador.
  getBoundingClientRect() {
    const m = medidor(this) || { left: 0, top: 0, width: 0, height: 0 }
    const t = /translate3d\((-?[\d.]+)px, (-?[\d.]+)px/.exec(this.style.transform || '')
    const left = m.left + (t ? Number(t[1]) : 0)
    const top = m.top + (t ? Number(t[2]) : 0)
    return { left, top, x: left, y: top, width: m.width, height: m.height, right: left + m.width, bottom: top + m.height }
  }
  // Lo que usan los formularios (pages/dobleClick.test.js): el foco de un
  // `autoFocus`, el `value` de un <option> y la lista de opciones de un <select>.
  focus() {}
  blur() {}
  get value() { return this._valor !== undefined ? this._valor : (this.atributos.value ?? '') }
  set value(v) { this._valor = String(v) }
  // Un <input> sin `type` es de texto, como en el navegador. React mira esto
  // para decidir si a ese campo le corresponde el `onChange` de cada tecla.
  get type() { return this.atributos.type ?? (this.nodeName === 'INPUT' ? 'text' : undefined) }
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
    capturas: new Map(),     // puntero → elemento que lo tiene agarrado
    // React pregunta UNA vez, al cargarse, si este navegador tiene el evento
    // `input` (`'oninput' in document`). Si no lo encuentra, cree que es un
    // navegador viejo y escribir en un campo no dispara el `onChange`.
    oninput: null,
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
    // Una pantalla de compu: lo que se recorta contra los bordes (la isla
    // arrastrada) necesita saber cuánto mide.
    innerWidth: 1280,
    innerHeight: 800,
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

// ── EL PUNTERO (mouse, dedo, lápiz) COMO LO REPARTE CHROME ────────────────────
//
// Lo que importa —y lo que rompió el clic de la isla el 2026-10-07— es A QUIÉN
// le llega cada evento:
//   · pointerdown → al elemento que está debajo.
//   · con el DEDO, Chrome agarra el puntero solo, con ese mismo elemento
//     (captura implícita). Con el mouse, no.
//   · si alguien agarró el puntero (setPointerCapture), el mover, el soltar y
//     el CLIC van a ese elemento, no al que está debajo.
//   · al soltar, la captura se suelta sola.
//   · el clic del MOUSE sigue a la captura; el del DEDO no: Chrome lo arma
//     como "toque" sobre el elemento que estaba debajo del dedo. Por eso con
//     el dedo la burbuja abría y con el mouse no.
// Cada evento baja desde la raíz (fase de captura), sube hasta la raíz y
// después llega a la ventana, como en el navegador.
const gestos = new Map()      // puntero → { abajo, captorAlSoltar }

function camino(nodo) {
  const c = []
  for (let n = nodo; n; n = n.parentNode) c.push(n)
  return c
}

function repartir(tipo, destino, datos) {
  let cortado = false
  const ev = {
    type: tipo, target: destino, bubbles: true, cancelable: true,
    defaultPrevented: false, timeStamp: performance.now(),
    preventDefault() { this.defaultPrevented = true },
    stopPropagation() { cortado = true },
    ...datos,
  }
  const subida = camino(destino)
  const llamar = (n, captura) => {
    for (const fn of [...(n.escuchas?.[tipo] || [])]) {
      if (!!n.enCaptura?.has(fn) === captura) { ev.currentTarget = n; fn.call(n, ev) }
    }
  }
  for (const n of [...subida].reverse()) { if (cortado) break; llamar(n, true) }
  for (const n of subida) { if (cortado) break; llamar(n, false) }
  if (!cortado) window.dispatchEvent(Object.assign(new Event(tipo), datos))
  return ev
}

/**
 * Un evento de puntero sobre `debajo` (el elemento que está bajo el mouse o
 * el dedo), repartido con las reglas de Chrome de arriba. `pointerup` también
 * dispara el `click` que le sigue, al elemento que corresponde.
 * datos: { pointerId, pointerType: 'mouse' | 'touch', clientX, clientY, button }
 */
export async function puntero(tipo, debajo, datos = {}) {
  const d = { pointerId: 1, pointerType: 'mouse', clientX: 0, clientY: 0, button: 0, isPrimary: true, ...datos }
  if (tipo === 'pointermove' || tipo === 'pointerup') d.button = tipo === 'pointerup' ? d.button : -1
  const capturas = document.capturas
  await enActo(async () => {
    if (tipo === 'pointerdown') {
      gestos.set(d.pointerId, { abajo: debajo })
      if (d.pointerType !== 'mouse') debajo.setPointerCapture(d.pointerId)
      repartir('pointerdown', debajo, d)
      return
    }
    const destino = capturas.get(d.pointerId) || debajo
    repartir(tipo, destino, d)
    if (tipo === 'pointerup' || tipo === 'pointercancel') {
      capturas.delete(d.pointerId)
      const g = gestos.get(d.pointerId)
      gestos.delete(d.pointerId)
      if (tipo === 'pointerup' && g && d.button === 0) {
        // El clic. Mouse: al que agarró el puntero (`destino`). Dedo: a lo que
        // estaba debajo. En los dos, si no coincide con donde se apretó, al
        // ancestro común de los dos.
        const fin = d.pointerType === 'mouse' ? destino : debajo
        const arriba = new Set(camino(g.abajo))
        const comun = camino(fin).find(n => arriba.has(n))
        if (comun) repartir('click', comun, { ...d, detail: 1 })
      }
    }
  })
}

// ── EL TECLADO ───────────────────────────────────────────────────────────────

/**
 * Escribir en un campo como el navegador: cambia el valor y avisa con el
 * evento `input`, que es lo que React escucha para el `onChange`. El valor se
 * pone por el setter ORIGINAL: React vigila el del campo para saber si cambió,
 * y si lo pasáramos por ahí creería que no cambió nada.
 */
export async function escribir(campo, valor) {
  await enActo(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(campo), 'value').set.call(campo, valor)
    repartir('input', campo, {})
  })
}

/** Apretar una tecla (`'Enter'`, `'Escape'`…) con el foco en `nodo`. */
export async function tecla(nodo, key) {
  await enActo(async () => { repartir('keydown', nodo, { key }) })
}
