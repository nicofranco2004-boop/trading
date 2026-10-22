// Las palabras del Fibonacci (utils/fibonacci.js). Las cuentas se prueban en
// backend/tests/test_estructura.py; acá, que cada caso que manda el servidor
// se diga en castellano y sin inventar.
import { describe, it, expect } from 'vitest'
import { nivelAlcanzado, rayas, rotulosQueEntran, tarjetaFibonacci } from './fibonacci'

const precio = (x) => `US$ ${x.toLocaleString('es-AR')}`
const fecha = (iso) => iso.split('-').reverse().join('/')

// Lo que devuelve /api/tecnico para la suba de MELI medida el 2026-10-22.
const SUBA = {
  disponible: true, n_pivote: 3, dir: 'suba',
  desde: { fecha: '2026-05-13', precio: 1495 }, hasta: { fecha: '2026-09-03', precio: 2066 },
  ruptura: { fecha: '2026-09-09', cierre: 1876.33, nivel: 1900, nivel_fecha: '2026-09-01' },
  niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 2066 - n * 571 })),
  retroceso_hoy: 0.3697, retroceso_maximo: { valor: 0.6963, precio: 1668.44, fecha: '2026-10-01' }, entre: [0.236, 0.382],
}

describe('tarjetaFibonacci', () => {
  it('una suba rota: hasta dónde bajó, dónde está hoy y cuándo terminó', () => {
    const t = tarjetaFibonacci(SUBA, precio, fecha)
    expect(t.titulo).toBe('Fibonacci de la última suba')
    expect(t.veredicto).toBe('Bajó hasta el 0,618')
    expect(t.texto).toContain('De la última suba (de US$ 1.495 el 13/05/2026 a US$ 2.066 el 03/09/2026)')
    expect(t.texto).toContain('Lo más bajo que llegó fue US$ 1.668,44, el 01/10/2026.')
    expect(t.texto).toContain('Hoy está entre el 0,236 y el 0,382: devolvió el 37 % de la suba')
    expect(t.texto).toContain('se dio por terminada el 09/09/2026, cuando cerró debajo de su último pozo más alto (US$ 1.900, del 01/09/2026)')
    expect(t.pie).toContain('3 ruedas después: hasta entonces no se sabe si alguno de los 3 días siguientes lo supera')
    expect(t.pie).toContain('no es una recomendación')
  })

  it('una bajada: recuperó, y los niveles se cuentan desde el piso', () => {
    const t = tarjetaFibonacci({ ...SUBA, dir: 'bajada', retroceso_maximo: { valor: 0.52, fecha: '2026-10-01' }, entre: [0.786, 1] }, precio, fecha)
    expect(t.veredicto).toBe('Recuperó hasta el 0,5')
    expect(t.texto).toContain('Hoy está entre el 0,786 y el arranque de la bajada')
    expect(t.texto).toContain('cerró encima de su último techo más bajo')
  })

  it('lateral (tramos chicos): sin tramo claro, sin inventar niveles', () => {
    const t = tarjetaFibonacci({ disponible: false, motivo: 'tramos_chicos', n_pivote: 3, en_curso: null }, precio, fecha)
    expect(t.veredicto).toBe('Sin tramo claro')
    expect(t.texto).not.toMatch(/0,\d/)
  })

  it('una suba larga que nunca se rompió no se llama "sin tramo claro"', () => {
    const t = tarjetaFibonacci({
      disponible: false, motivo: 'sin_tramo_terminado', n_pivote: 3,
      en_curso: { dir: 'suba', desde: { fecha: '2025-01-02', precio: 99.38 }, hasta: { fecha: '2026-10-20', precio: 300 },
        se_rompe_si_cierra: { debajo_de: 280, fecha: '2026-10-01' } },
    }, precio, fecha)
    expect(t.veredicto).toBe('Suba en curso')
    expect(t.texto).toContain('todavía no terminó ninguna suba ni bajada')
    expect(t.texto).toContain('Ahora sube desde US$ 99,38 (02/01/2025)')
    expect(t.texto).not.toContain('clara')
  })

  it('el último tramo es de hace más de un año: lo dice', () => {
    const t = tarjetaFibonacci({ disponible: false, motivo: 'tramo_viejo', n_pivote: 3, en_curso: null,
      viejo: { dir: 'suba', desde: { fecha: '2024-03-01', precio: 10 }, hasta: { fecha: '2024-06-01', precio: 20 } } }, precio, fecha)
    expect(t.veredicto).toBe('Sin tramo reciente')
    expect(t.texto).toContain('La última suba (de US$ 10 el 01/03/2024 a US$ 20 el 01/06/2024) terminó hace más de un año')
  })

  it('si se rompió contra su propio arranque, no lo llama "último pozo más alto"', () => {
    const t = tarjetaFibonacci({ ...SUBA, ruptura: { ...SUBA.ruptura, nivel: 1495, nivel_fecha: '2026-05-13' } }, precio, fecha)
    expect(t.texto).toContain('cuando cerró debajo de donde había arrancado (US$ 1.495)')
    expect(t.texto).not.toContain('último pozo más alto')
  })

  it('superado: cuenta el tramo vivo y qué cierre lo daría por terminado', () => {
    const t = tarjetaFibonacci({
      disponible: false, motivo: 'superado', n_pivote: 3,
      superado: { dir: 'bajada', desde: { fecha: '2026-06-01', precio: 466.32 }, hasta: { fecha: '2026-06-25', precio: 349.2 } },
      en_curso: { dir: 'suba', desde: { fecha: '2026-06-25', precio: 349.2 }, hasta: { fecha: '2026-10-13', precio: 551.15 },
        se_rompe_si_cierra: { debajo_de: 486, fecha: '2026-09-10' } },
    }, precio, fecha)
    expect(t.veredicto).toBe('Suba en curso')
    expect(t.texto).toContain('La última bajada (de US$ 466,32 el 01/06/2026 a US$ 349,2 el 25/06/2026) ya quedó atrás')
    expect(t.texto).toContain('si un día cierra debajo de US$ 486 (el último pozo más alto, del 10/09/2026)')
  })

  it('pocos datos: lo dice', () => {
    expect(tarjetaFibonacci({ disponible: false, motivo: 'pocos_datos', ruedas: 12 }, precio, fecha).texto)
      .toContain('al menos 30 ruedas y hay 12')
  })
})

describe('niveles', () => {
  it('nivelAlcanzado: el más lejano que tocó', () => {
    expect(nivelAlcanzado(0.1)).toBe(0)
    expect(nivelAlcanzado(0.5)).toBe(0.5)
    expect(nivelAlcanzado(0.7)).toBe(0.618)
    expect(nivelAlcanzado(1.3)).toBe(1)
  })

  it('rayas: el final del tramo es 0 y el arranque es 1', () => {
    const r = rayas(SUBA)
    expect(r.map(x => x.nivel)).toEqual([0, 0.236, 0.382, 0.5, 0.618, 0.786, 1])
    expect(r[0].precio).toBe(2066)
    expect(r[6].precio).toBe(1495)
  })

  it('los rótulos que se pisan se saltean, nunca los extremos', () => {
    const r = rayas(SUBA)
    const tops = [10, 20, 22, 30, 33, 45, 60]   // 0,236 y 0,382 pegados; 0,5 y 0,618 también
    const entran = rotulosQueEntran(r, tops, [0.236, 0.382])
    expect(entran.has(0)).toBe(true)
    expect(entran.has(6)).toBe(true)
    expect(entran.has(1) && entran.has(2)).toBe(false)
    expect(entran.has(3) && entran.has(4)).toBe(false)
  })
})
