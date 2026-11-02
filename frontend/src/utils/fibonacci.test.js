// Las palabras del Fibonacci (utils/fibonacci.js). Las cuentas se prueban en
// backend/tests/test_estructura.py; acá, que cada caso que manda el servidor
// se diga en castellano y sin inventar.
import { describe, it, expect } from 'vitest'
import { nivelAlcanzado, rayas, rotuloNivel, rotulosQueEntran, tarjetaFibonacci } from './fibonacci'

const precio = (x) => `US$ ${x.toLocaleString('es-AR')}`
const fecha = (iso) => iso.split('-').reverse().join('/')

// Lo que devuelve /api/tecnico para la suba de MELI medida el 2026-10-22.
const SUBA = {
  disponible: true, n_pivote: 3, dir: 'suba',
  desde: { fecha: '2026-05-13', precio: 1495 }, hasta: { fecha: '2026-09-03', precio: 2066 },
  ruptura: { fecha: '2026-09-09', cierre: 1876.33, nivel: 1900, nivel_fecha: '2026-09-01' },
  niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 2066 - n * 571 })),
  precio_hoy: 1854.88, fecha_hoy: '2026-10-22', retroceso_hoy: 0.3697, retroceso_maximo: { valor: 0.6963, precio: 1668.44, fecha: '2026-10-01' }, entre: [0.236, 0.382],
}

describe('tarjetaFibonacci', () => {
  it('una suba rota: hasta dónde bajó, dónde está hoy y cuándo terminó', () => {
    const t = tarjetaFibonacci(SUBA, precio, fecha)
    expect(t.titulo).toBe('Fibonacci de la última suba')
    expect(t.veredicto).toBe('Devolvió el 37 % de la suba')
    expect(t.texto).toContain('La última suba fue de US$ 1.495 (13/05/2026) a US$ 2.066 (03/09/2026).')
    expect(t.texto).toContain('El 09/09/2026 cerró debajo de su último pozo más alto (US$ 1.900, del 01/09/2026): ahí terminó la suba.')
    expect(t.texto).toContain('Al cierre del 22/10/2026 estaba en US$ 1.854,88: está entre el 23,6 % y el 38,2 % de la suba.')
    expect(t.texto).toContain('Lo más bajo que llegó fue US$ 1.668,44, el 01/10/2026 (70 % de la suba).')
    // Cada nivel dicho por lo que significa; el porcentaje, como dato.
    expect(t.explicacion).toContain('hasta dónde podría volver a bajar antes de seguir subiendo')
    expect(`${t.veredicto} ${t.texto} ${t.explicacion}`).not.toMatch(/0,(236|382|5|618|786)\b|rueda/)
    expect(t.pie).toContain('3 días de mercado después')
    expect(t.pie).not.toContain('rueda')
    expect(t.pie).toContain('no es una recomendación')
  })

  it('una bajada: recuperó, y los niveles se cuentan desde el piso', () => {
    const t = tarjetaFibonacci({ ...SUBA, dir: 'bajada', retroceso_hoy: 0.8, retroceso_maximo: { valor: 0.85, precio: 2000, fecha: '2026-10-01' }, entre: [0.786, 1] }, precio, fecha)
    expect(t.veredicto).toBe('Recuperó el 80 % de la bajada')
    expect(t.texto).toContain('recuperó casi toda la bajada (más del 78,6 %)')
    expect(t.texto).toContain('Lo más alto que llegó fue US$ 2.000')
    expect(t.texto).toContain('cerró encima de su último techo más bajo')
    expect(t.explicacion).toContain('hasta dónde podría volver a subir antes de seguir bajando')
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

  it('si el pozo ya estaba perforado cuando se confirmó el pico, dice las dos fechas', () => {
    const t = tarjetaFibonacci({ ...SUBA, ruptura: { ...SUBA.ruptura, fecha: '2026-09-09', cerro_fuera_fecha: '2026-09-04' } }, precio, fecha)
    expect(t.texto).toContain('El 09/09/2026 se confirmó que el nivel a defender era su último pozo más alto (US$ 1.900, del 01/09/2026), y el precio ya había cerrado debajo el 04/09/2026: ahí terminó la suba.')
    const mismoDia = tarjetaFibonacci({ ...SUBA, ruptura: { ...SUBA.ruptura, cerro_fuera_fecha: SUBA.ruptura.fecha } }, precio, fecha)
    expect(mismoDia.texto).toContain('El 09/09/2026 cerró debajo de su último pozo más alto')
  })

  it('si se rompió contra su propio arranque, no lo llama "último pozo más alto"', () => {
    const t = tarjetaFibonacci({ ...SUBA, ruptura: { ...SUBA.ruptura, nivel: 1495, nivel_fecha: '2026-05-13' } }, precio, fecha)
    expect(t.texto).toContain('cerró debajo de donde había arrancado (US$ 1.495): ahí terminó la suba')
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
    expect(t.texto).toContain('Si un día cierra por debajo de US$ 486 (el último pozo más alto, del 10/09/2026), podría ser una señal de que esa suba está perdiendo fuerza.')
    // Lo que puede pasar se dice como posibilidad, nunca como certeza (Nico, 23/10).
    expect(t.texto).not.toMatch(/se da por terminada|se terminaría|se termina /)
  })

  it('pocos datos: lo dice', () => {
    expect(tarjetaFibonacci({ disponible: false, motivo: 'pocos_datos', ruedas: 12 }, precio, fecha).texto)
      .toContain('al menos 30 días de mercado y este activo tiene 12')
  })
})

describe('niveles', () => {
  it('nivelAlcanzado: el más lejano que tocó', () => {
    expect(nivelAlcanzado(0.1)).toBe(0)
    expect(nivelAlcanzado(0.5)).toBe(0.5)
    expect(nivelAlcanzado(0.7)).toBe(0.618)
    expect(nivelAlcanzado(1.3)).toBe(1)
  })

  it('rótulos: los extremos por su nombre, los niveles en porcentaje', () => {
    expect(rotuloNivel(0, 'suba')).toBe('Pico')
    expect(rotuloNivel(0, 'bajada')).toBe('Piso')
    expect(rotuloNivel(1, 'suba')).toBe('Arranque')
    expect(rotuloNivel(0.618, 'suba')).toBe('61,8 %')
    expect(rotuloNivel(0.5, 'suba')).toBe('50 %')
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

// Lo que devuelve /api/tecnico para INTC el 02/11/26 (backend/tests/test_elliott_grados.py):
// el Fibonacci del impulso de 5 ondas del conteo de Elliott, con la C en curso.
const IMPULSO = {
  disponible: true, de: 'impulso', n_pivote: 3, dir: 'suba', ruptura: null,
  desde: { fecha: '2025-11-21', precio: 32.89 }, hasta: { fecha: '2026-06-30', precio: 142.35 },
  niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 142.35 - n * 109.46 })),
  precio_hoy: 65.76, fecha_hoy: '2026-10-30', retroceso_hoy: 0.6997, entre: [0.618, 0.786],
  retroceso_maximo: { valor: 0.7231, precio: 63.2, fecha: '2026-10-30' },
  extension: { veces_a: 1.061, terminada: false, a: { desde: 142.35, hasta: 81.79 }, desde_b: 127.44, hasta: { fecha: '2026-10-30', precio: 63.2 } },
  tramo: { disponible: false, motivo: 'superado' },
}

describe('tarjetaFibonacci del impulso de Elliott', () => {
  it('mide del arranque de la onda 1 al final de la 5, como medida y no como objetivo', () => {
    const t = tarjetaFibonacci(IMPULSO, precio, fecha)
    expect(t.titulo).toBe('Fibonacci del impulso de suba')
    expect(t.veredicto).toBe('Devolvió el 70 % del impulso')
    expect(t.texto).toContain('subió de US$ 32,89 (21/11/2025, donde arranca la onda 1) a US$ 142,35 (30/06/2026, el final de la onda 5)')
    expect(t.texto).toContain('Al cierre del 30/10/2026 estaba en US$ 65,76: está entre el 61,8 % y el 78,6 % del impulso.')
    expect(t.texto).toContain('Lo más bajo que llegó desde ahí fue US$ 63,2, el 30/10/2026 (72 % del impulso).')
    expect(t.explicacion).toContain('no hasta dónde va a llegar')
    expect(t.explicacion).toContain('Extensión: la onda C lleva recorrido 1,06 veces lo que bajó la onda A (de US$ 127,44, el final de la B, a US$ 63,2 el 30/10/2026).')
    // Sin «ruptura» (lo terminó el conteo, no un cierre) y sin consejo.
    expect(t.texto).not.toContain('cerró debajo')
    expect(`${t.texto} ${t.explicacion}`).not.toMatch(/compr|vend|objetivo/i)
  })

  it('una corrección ya terminada: «recorrió»; sin A-B todavía, no hay extensión', () => {
    const fin = tarjetaFibonacci({ ...IMPULSO, extension: { ...IMPULSO.extension, terminada: true } }, precio, fecha)
    expect(fin.explicacion).toContain('la onda C recorrió 1,06 veces')
    const sinAB = tarjetaFibonacci({ ...IMPULSO, extension: null }, precio, fecha)
    expect(sinAB.explicacion).not.toContain('Extensión')
  })
})
