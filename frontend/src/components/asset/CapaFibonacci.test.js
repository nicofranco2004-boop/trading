// El botón «Fibonacci» de la lectura técnica, montado de verdad
// (testing/navegadorMinimo.js) con /api/tecnico simulado en la frontera:
//   · apagado de entrada: ni rayas ni tarjeta;
//   · al prenderlo: las rayas con su precio y la tarjeta en castellano;
//   · sin tramo para medir: la tarjeta lo dice y no hay rayas de niveles.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic } from '../../testing/navegadorMinimo'

const puntos = Array.from({ length: 252 }, (_, i) => {
  const d = new Date(Date.UTC(2025, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = i < 150 ? 100 + i * 0.5 : 175 - (i - 150) * 0.3
  return { d, o: c, h: c * 1.01, l: c * 0.99, c, s50: null, s200: null, rsi: 50 }
})
const FIB = {
  disponible: true, n_pivote: 3, dir: 'suba',
  desde: { fecha: puntos[20].d, precio: 108.9 }, hasta: { fecha: puntos[150].d, precio: 176.75 },
  ruptura: { fecha: puntos[170].d, cierre: 169, nivel: 170, nivel_fecha: puntos[140].d },
  niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 176.75 - n * 67.85 })),
  retroceso_hoy: 0.45, retroceso_maximo: { valor: 0.46, fecha: puntos[251].d }, entre: [0.382, 0.5],
}
const DATOS = (fibonacci) => ({
  disponible: true, moneda: 'usd', ticker: 'ZZFB', convertida: null, puntos, fibonacci,
  lectura: { ruedas: 252, fecha: puntos[251].d, precio: puntos[251].c, rsi: 50 },
})

let respuesta
vi.mock('../../utils/api', () => ({
  api: { get: vi.fn(() => Promise.resolve(respuesta)) },
}))

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

const el = () => h(LecturaTecnica, { asset: 'ZZFB' })
async function dibujar() {
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}
async function prender() {
  await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Fibonacci'))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('Fibonacci en la ficha', () => {
  it('apagado de entrada; al prenderlo, rayas con precio y la tarjeta', async () => {
    respuesta = DATOS(FIB)
    const antes = await dibujar()
    expect(antes).toContain('Fibonacci')            // el botón
    expect(antes).not.toContain('Fibonacci de la última suba')
    expect(antes).not.toContain('0,618 ·')
    const t = await prender()
    expect(t).toContain('Fibonacci de la última suba')
    expect(t).toContain('Bajó hasta el 0,382')
    expect(t).toContain('Hoy está entre el 0,382 y el 0,5')
    expect(t).toContain('0 · US$ 176,75')            // el final del tramo, siempre con rótulo
    expect(t).toContain('1 · US$ 108,90')            // el arranque
    expect(t).toContain('no es una recomendación')
    // Apagarlo lo saca.
    const despues = await prender()
    expect(despues).not.toContain('Fibonacci de la última suba')
  })

  it('sin tramo claro: lo dice y no dibuja niveles', async () => {
    respuesta = DATOS({ disponible: false, motivo: 'sin_tramo_claro', n_pivote: 3, ruedas: 252, en_curso: null })
    await dibujar()
    const t = await prender()
    expect(t).toContain('Sin tramo claro')
    expect(t).not.toContain('0,618 ·')
  })

  it('una respuesta vieja sin el campo no muestra el botón', async () => {
    respuesta = DATOS(undefined)
    const t = await dibujar()
    expect(t).not.toContain('Fibonacci')
  })
})
