// El botón «Fibonacci» de la lectura técnica, montado de verdad
// (testing/navegadorMinimo.js) con /api/tecnico simulado en la frontera:
//   · prendido de entrada: las rayas con su precio y la tarjeta en castellano;
//   · el botón lo apaga (ni rayas ni tarjeta) y lo vuelve a prender;
//   · sin tramo para medir: la tarjeta lo dice y no hay rayas de niveles.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscar, buscarBoton, clic } from '../../testing/navegadorMinimo'

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
  localStorage.clear()   // lo que apaga una prueba no pasa a la siguiente
})

const el = () => h(LecturaTecnica, { asset: 'ZZFB' })
async function dibujar() {
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}
async function tocarFibonacci() {
  await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Fibonacci'))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('Fibonacci en la ficha', () => {
  it('prendido de entrada: rayas con precio y la tarjeta; el botón lo apaga', async () => {
    respuesta = DATOS(FIB)
    const t = await dibujar()
    expect(t).toContain('Fibonacci de la última suba')
    expect(t).toContain('Devolvió el 45 % de la suba')
    expect(t).toContain('está entre el 38,2 % y el 50 % de la suba')
    expect(t).toContain('Pico · US$ 176,75')         // el final del tramo, siempre con rótulo
    expect(t).toContain('Arranque · US$ 108,90')
    expect(t).toContain('no es una recomendación')
    // Apagarlo lo saca, y prenderlo lo vuelve a poner.
    const apagado = await tocarFibonacci()
    expect(apagado).toContain('Fibonacci')            // el botón sigue
    expect(apagado).not.toContain('Fibonacci de la última suba')
    expect(apagado).not.toContain('61,8 % ·')
    expect(await tocarFibonacci()).toContain('Fibonacci de la última suba')
  })

  it('sin tramo claro: lo dice y no dibuja niveles', async () => {
    respuesta = DATOS({ disponible: false, motivo: 'tramos_chicos', n_pivote: 3, ruedas: 252, en_curso: null })
    const t = await dibujar()
    expect(t).toContain('Sin tramo claro')
    expect(t).not.toContain('61,8 % ·')
  })

  it('al prenderlo con un tramo corto, el gráfico se acerca al tramo', async () => {
    const { ventanaDelTramo } = await import('./CapaFibonacci')
    // Tramo de las últimas 30 ruedas en un gráfico de 252: se ven 63 (el mínimo).
    const corto = {
      ...FIB, desde: { fecha: puntos[222].d, precio: 100 }, hasta: { fecha: puntos[240].d, precio: 200 },
      ruptura: { fecha: puntos[245].d, cierre: 180, nivel: 185, nivel_fecha: puntos[236].d },
      niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 200 - n * 100 })),
    }
    expect(ventanaDelTramo(puntos, corto, 252)).toEqual({ n: 63, fin: 252 })
    // Tramo de 100 ruedas: 160, con aire antes del arranque.
    expect(ventanaDelTramo(puntos, { ...FIB, desde: { fecha: puntos[152].d, precio: 150 } }, 252)).toEqual({ n: 160, fin: 252 })
    // Ya se ve entero: no toca nada. Sin tramo, o arranca antes del gráfico: tampoco.
    expect(ventanaDelTramo(puntos, FIB, 252)).toBeNull()
    expect(ventanaDelTramo(puntos, corto, 63)).toBeNull()
    expect(ventanaDelTramo(puntos, { disponible: false }, 252)).toBeNull()
    expect(ventanaDelTramo(puntos, { ...FIB, desde: { fecha: '2020-01-01', precio: 1 } }, 252)).toBeNull()
    // Montado: con el tramo corto, al apagarlo y volver a prenderlo el gráfico
    // se acerca y aparecen las 7 rayas con rótulo.
    respuesta = DATOS(corto)
    await dibujar()
    await tocarFibonacci()
    const t = await tocarFibonacci()
    for (const n of ['Pico ·', '23,6 % ·', '38,2 % ·', '50 % ·', '61,8 % ·', '78,6 % ·', 'Arranque ·']) expect(t).toContain(n)
  })

  it('con zoom o arrastre, lo que queda fuera de la vista no se dibuja en otro lugar', async () => {
    const { default: Capa, posicion, preciosDeLaCapa } = await import('./CapaFibonacci')
    const capa = (vista) => h(Capa, {
      fib: FIB, puntos: vista, pctX: (i) => (i / (vista.length - 1)) * 100, pctY: (v) => 100 - (v - 100), precio: (x) => `US$ ${x}`,
    })
    // Ventana corrida al pasado (antes del arranque del tramo): nada, y la escala no se estira.
    const pasado = puntos.slice(0, 15)
    expect(posicion(pasado, FIB.desde.fecha).donde).toBe('despues')
    expect(preciosDeLaCapa(FIB, pasado)).toEqual([])
    montado = await montar(capa(pasado))
    expect(texto(montado.contenedor)).toBe('')
    await montado.desmontar()
    // Ventana que empieza a mitad del tramo: las rayas desde el borde, pero no
    // la raya del tramo ni su arranque (quedarían en una fecha que no es la suya).
    const medio = puntos.slice(60)
    expect(posicion(medio, FIB.desde.fecha).donde).toBe('antes')
    expect(preciosDeLaCapa(FIB, medio)).toEqual([108.9, 176.75])
    montado = await montar(capa(medio))
    expect(texto(montado.contenedor)).toContain('50 % ·')
    expect(buscar(montado.contenedor, 'svg')).toBeNull()
    await montado.desmontar()
    // Con todo a la vista, sí.
    montado = await montar(capa(puntos))
    expect(buscar(montado.contenedor, 'svg')).not.toBeNull()
    // Una vela semanal cubre su semana: el miércoles cae adentro, el lunes siguiente no.
    const semanal = [{ d: '2026-10-05', semana: true }, { d: '2026-10-12', semana: true }]
    expect(posicion(semanal, '2026-10-14').donde).toBe('adentro')
    expect(posicion(semanal, '2026-10-19').donde).toBe('despues')
  })

  it('una respuesta vieja sin el campo: el botón deshabilitado, con el porqué, y nada dibujado', async () => {
    respuesta = DATOS(undefined)
    const t = await dibujar()
    expect(t).not.toContain('Fibonacci de la')
    expect(t).not.toContain('61,8 % ·')
    expect(buscarBoton(montado.contenedor, 'Fibonacci').getAttribute('aria-disabled')).toBe('true')
    expect(await tocarFibonacci()).toContain('Fibonacci: Este activo todavía no tiene el cálculo del Fibonacci.')
  })
})
