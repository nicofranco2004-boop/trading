// Arrastrar los ejes del gráfico técnico, montado de verdad
// (testing/navegadorMinimo.js, que reparte el puntero como Chrome):
//   · la columna de precios: hacia abajo achica el gráfico (los precios de la
//     grilla se separan) y deja el precio a mano: aparece «Automático», y
//     arrastrar el gráfico lo mueve para arriba y para abajo; «Automático», el
//     doble click u otro rango vuelven a lo automático;
//   · la fila de fechas, con el dedo: hacia la derecha acerca (se ven menos
//     meses y ningún botón de rango queda elegido), doble click vuelve al 1A.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, puntero, enActo, medidas, clic, buscarBoton } from '../../testing/navegadorMinimo'

const puntos = Array.from({ length: 700 }, (_, i) => {
  const d = new Date(Date.UTC(2024, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = 100 + 20 * Math.sin(i / 40) + i * 0.05
  return { d, o: c, h: c * 1.01, l: c * 0.99, c, s50: null, s200: null, rsi: 50 }
})
const DATOS = {
  disponible: true, moneda: 'usd', ticker: 'ZZEJ', convertida: null, puntos, fibonacci: undefined,
  lectura: { ruedas: 700, fecha: puntos[699].d, precio: puntos[699].c, rsi: 50 },
}

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => Promise.resolve(DATOS)) } }))

let LecturaTecnica
beforeAll(async () => {
  instalarNavegadorMinimo()
  // Todo mide 1000 × 250: alcanza para convertir un arrastre en fracción del alto.
  medidas(() => ({ left: 0, top: 0, width: 1000, height: 250, right: 1000, bottom: 250 }))
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { medidas(null); vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
})

const el = () => h(LecturaTecnica, { asset: 'ZZEJ' })
async function dibujar() {
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
}

// El primer nodo cuyo `title` empieza así.
function porTitulo(nodo, empieza) {
  const pila = [nodo]
  while (pila.length) {
    const n = pila.shift()
    if (n.getAttribute?.('title')?.startsWith(empieza)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
function botonPresionado(nodo, rotulo) {
  const pila = [nodo]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && texto(n) === rotulo) return n.getAttribute('aria-pressed') === 'true'
    pila.push(...(n.childNodes || []))
  }
  return null
}
const numeros = (t) => (t.match(/[\d.]+(,\d+)?/g) || []).map(x => Number(x.replace(/\./g, '').replace(',', '.')))

async function arrastrar(nodo, { dx = 0, dy = 0, pointerType = 'mouse' }) {
  await puntero('pointerdown', nodo, { pointerType, clientX: 100, clientY: 100 })
  for (let k = 1; k <= 7; k++) {
    await puntero('pointermove', nodo, { pointerType, clientX: 100 + (dx * k) / 7, clientY: 100 + (dy * k) / 7 })
  }
  await puntero('pointerup', nodo, { pointerType, clientX: 100 + dx, clientY: 100 + dy })
}
// Un evento del mouse (no de puntero) como lo recibe React: por la raíz.
async function raton(tipo, nodo, datos = {}) {
  await enActo(async () => {
    const ev = { type: tipo, target: nodo, bubbles: true, cancelable: true, button: 0,
      preventDefault() {}, stopPropagation() {}, ...datos }
    for (const fn of montado.contenedor.escuchas[tipo] || []) fn(ev)
  })
}
async function dobleClick(nodo) {
  await raton('dblclick', nodo, { detail: 2 })
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
}
function porRol(nodo, rol) {
  const pila = [nodo]
  while (pila.length) {
    const n = pila.shift()
    if (n.getAttribute?.('role') === rol) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

describe('arrastrar los ejes del gráfico', () => {
  it('la columna de precios: achica, deja el precio a mano y se vuelve a automático', async () => {
    await dibujar()
    const columna = porTitulo(montado.contenedor, 'Arrastrá hacia arriba o hacia abajo')
    expect(columna).not.toBeNull()
    // Cada rótulo de la columna (la grilla y el último precio), por separado.
    const grilla = () => columna.childNodes.map(n => numeros(texto(n))[0]).filter(x => x != null)
    const ancho = (g) => Math.max(...g) - Math.min(...g)
    const antes = grilla()
    expect(buscarBoton(montado.contenedor, 'Automático')).toBeNull()

    await arrastrar(columna, { dy: 140 })
    const achicado = grilla()
    expect(ancho(achicado)).toBeGreaterThan(ancho(antes) * 1.5)    // entró el doble de rango de precio
    expect(buscarBoton(montado.contenedor, 'Automático')).not.toBeNull()

    // Con el precio a mano, arrastrar el gráfico hacia abajo muestra precios más altos.
    const grafico = porRol(montado.contenedor, 'img')
    await raton('mousedown', grafico, { clientX: 500, clientY: 100 })
    await raton('mousemove', grafico, { clientX: 500, clientY: 150 })   // 1/5 del alto
    await raton('mouseup', grafico, { clientX: 500, clientY: 150 })
    const corrido = grilla()
    expect(Math.max(...corrido)).toBeGreaterThan(Math.max(...achicado))

    // «Automático» lo devuelve.
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Automático'))
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(grilla()).toEqual(antes)
    expect(buscarBoton(montado.contenedor, 'Automático')).toBeNull()

    // El doble click también.
    await arrastrar(columna, { dy: -100 })
    expect(grilla()).not.toEqual(antes)
    await dobleClick(columna)
    expect(grilla()).toEqual(antes)

  })

  // Otro rango, moneda, tipo de gráfico o diarias/semanales: el precio vuelve a
  // automático (cada uno con su prueba, como pidió la sesión central).
  for (const [nombre, pasos] of [
    ['otro rango', ['2A']],
    ['otra moneda', ['Pesos']],
    ['otro tipo de gráfico', ['Velas']],
    ['de diarias a semanales', ['Velas', '@', 'Semanales']],
  ]) {
    it(`${nombre} vuelve el precio a automático`, async () => {
      await dibujar()
      const columna = () => porTitulo(montado.contenedor, 'Arrastrá hacia arriba o hacia abajo')
      const grilla = () => columna().childNodes.map(n => numeros(texto(n))[0]).filter(x => x != null)
      // Lo que se cambia ANTES de estirar (marcado con '@') no cuenta: es el punto de partida.
      const antes = pasos.includes('@') ? pasos.slice(0, pasos.indexOf('@')) : []
      const despues = pasos.includes('@') ? pasos.slice(pasos.indexOf('@') + 1) : pasos
      for (const b of antes) {
        await clic(montado.contenedor, buscarBoton(montado.contenedor, b))
        for (let i = 0; i < 3; i++) await montado.redibujar(el())
      }
      const auto = grilla()
      await arrastrar(columna(), { dy: 120 })
      expect(grilla()).not.toEqual(auto)
      expect(buscarBoton(montado.contenedor, 'Automático')).not.toBeNull()
      for (const b of despues) {
        await clic(montado.contenedor, buscarBoton(montado.contenedor, b))
        for (let i = 0; i < 3; i++) await montado.redibujar(el())
      }
      expect(buscarBoton(montado.contenedor, 'Automático')).toBeNull()
    })
  }

  it('las fechas a mano también muestran «Automático» (en el celular no hay doble click)', async () => {
    await dibujar()
    const fechas = porTitulo(montado.contenedor, 'Arrastrá hacia los costados')
    expect(buscarBoton(montado.contenedor, 'Automático')).toBeNull()
    await arrastrar(fechas, { dx: 200, pointerType: 'touch' })
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(botonPresionado(montado.contenedor, '1A')).toBe(false)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Automático'))
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(botonPresionado(montado.contenedor, '1A')).toBe(true)
    expect(buscarBoton(montado.contenedor, 'Automático')).toBeNull()
  })

  it('la fila de fechas, con el dedo: hacia la derecha acerca; doble click, vuelve al 1A', async () => {
    await dibujar()
    const fechas = porTitulo(montado.contenedor, 'Arrastrá hacia los costados')
    expect(fechas).not.toBeNull()
    expect(botonPresionado(montado.contenedor, '1A')).toBe(true)
    const meses = () => texto(fechas)
    const antes = meses()
    await arrastrar(fechas, { dx: 280, pointerType: 'touch' })
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(meses()).not.toBe(antes)
    expect(botonPresionado(montado.contenedor, '1A')).toBe(false)  // ya no es el rango del botón
    await dobleClick(fechas)
    expect(botonPresionado(montado.contenedor, '1A')).toBe(true)
    expect(meses()).toBe(antes)
  })
})
