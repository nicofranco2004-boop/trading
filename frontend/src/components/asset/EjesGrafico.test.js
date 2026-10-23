// Arrastrar los ejes del gráfico técnico, montado de verdad
// (testing/navegadorMinimo.js, que reparte el puntero como Chrome):
//   · la columna de precios: hacia abajo achica el gráfico (los precios de la
//     grilla se separan), doble click vuelve a lo automático;
//   · la fila de fechas, con el dedo: hacia la derecha acerca (se ven menos
//     meses y ningún botón de rango queda elegido), doble click vuelve al 1A.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, puntero, enActo } from '../../testing/navegadorMinimo'

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
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { vi.unstubAllGlobals() })

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
async function dobleClick(nodo) {
  await enActo(async () => {
    const ev = { type: 'dblclick', target: nodo, bubbles: true, cancelable: true, button: 0, detail: 2,
      preventDefault() {}, stopPropagation() {} }
    for (const fn of montado.contenedor.escuchas.dblclick || []) fn(ev)
  })
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
}

describe('arrastrar los ejes del gráfico', () => {
  it('la columna de precios: hacia abajo achica el gráfico; doble click, automático', async () => {
    await dibujar()
    const columna = porTitulo(montado.contenedor, 'Arrastrá hacia arriba o hacia abajo')
    expect(columna).not.toBeNull()
    // Cada rótulo de la columna (la grilla y el último precio), por separado.
    const grilla = () => columna.childNodes.map(n => numeros(texto(n))[0]).filter(x => x != null)
    const antes = grilla()
    const ancho = (g) => Math.max(...g) - Math.min(...g)
    await arrastrar(columna, { dy: 140 })
    const despues = grilla()
    expect(ancho(despues)).toBeGreaterThan(ancho(antes) * 1.5)    // entró el doble de rango de precio
    await dobleClick(columna)
    expect(grilla()).toEqual(antes)
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
