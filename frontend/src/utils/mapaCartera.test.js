// La cuenta del «Mapa de tu cartera» (Panorama de Análisis técnico, 30/10):
//   · cada cuadrito con el peso y la tendencia de su fila de Tu lista (la misma
//     cuenta del % alcista), sin inventar otra;
//   · el efectivo y los plazos fijos son lo que falta para llegar a 100 %;
//   · el área de cada cuadrito es proporcional a lo que pesa;
//   · con «Ocultar saldos» ni el tamaño, ni el orden, ni el % dicen cuánto pesa.
import { describe, it, expect } from 'vitest'
import { cuadritosDelMapa, ubicarCuadritos, MAX_CUADRITOS, PROPORCION } from './mapaCartera'

const fila = (nombre, peso, tendencia, extra = {}) => ({
  clave: `${nombre}|0`, nombre, ruta: nombre, tenes: true, peso, fondo: { id: tendencia }, ...extra,
})
const FILAS = [
  fila('AAPL', 15, 'alcista'),
  fila('GGAL', 18, 'alcista', { clave: 'GGAL|1' }),
  fila('MELI', 12, 'bajista'),
  fila('AL30', 8, 'sin'),
  // Lo que seguís y no tenés no va en el mapa de tu cartera.
  { clave: 'TSLA|0', nombre: 'TSLA', ruta: 'TSLA', tenes: false, peso: 0, fondo: { id: 'alcista' } },
]

describe('cuadritosDelMapa', () => {
  it('uno por activo que tenés, de más a menos peso, con su tendencia; el resto es efectivo', () => {
    const c = cuadritosDelMapa(FILAS, { sinLectura: ['AL30', 'efectivo'] })
    expect(c.map(x => x.nombre)).toEqual(['Efectivo', 'GGAL', 'AAPL', 'MELI', 'AL30'])
    expect(c.map(x => x.tendencia)).toEqual(['sin', 'alcista', 'alcista', 'bajista', 'sin'])
    // 100 − (18 + 15 + 12 + 8) = 47: el efectivo, sin ficha.
    expect(c[0].peso).toBeCloseTo(47)
    expect(c[0].ruta).toBeNull()
    expect(c.find(x => x.nombre === 'GGAL').ruta).toBe('GGAL')
  })

  it('el nombre del resto sigue lo que dice el servidor: efectivo, plazos fijos o los dos', () => {
    expect(cuadritosDelMapa(FILAS, { sinLectura: ['plazos fijos'] }).some(x => x.nombre === 'Plazos fijos')).toBe(true)
    expect(cuadritosDelMapa(FILAS, { sinLectura: ['efectivo', 'plazos fijos'] }).some(x => x.nombre === 'Efectivo y plazos fijos')).toBe(true)
    // Sin resto (todo invertido) no hay cuadrito de efectivo.
    const llenas = [fila('AAPL', 60, 'alcista'), fila('MELI', 40, 'bajista')]
    expect(cuadritosDelMapa(llenas).map(x => x.nombre)).toEqual(['AAPL', 'MELI'])
  })

  it('sin nada en la cartera (sólo watchlist), ningún cuadrito', () => {
    expect(cuadritosDelMapa([FILAS[4]])).toEqual([])
  })

  it(`más de ${MAX_CUADRITOS}: los que no entran van juntos en «y N más», con su peso sumado`, () => {
    const muchas = Array.from({ length: 14 }, (_, i) => fila(`A${String(i).padStart(2, '0')}`, 7 - i * 0.1, 'alcista'))
    const c = cuadritosDelMapa(muchas)
    expect(c).toHaveLength(MAX_CUADRITOS)
    const otros = c[c.length - 1]
    expect(otros.tendencia).toBe('otros')
    // 14 activos + el efectivo = 15; se ven 9 y van juntos 6.
    expect(otros.nombre).toBe('y 6 más')
    const suma = c.reduce((s, x) => s + x.peso, 0)
    expect(suma).toBeCloseTo(100)
  })

  it('con «Ocultar saldos»: sin peso y en orden alfabético (el orden por peso también lo delataría)', () => {
    const c = cuadritosDelMapa(FILAS, { hidden: true, sinLectura: ['efectivo'] })
    expect(c.map(x => x.nombre)).toEqual(['AAPL', 'AL30', 'Efectivo', 'GGAL', 'MELI'])
    expect(c.every(x => x.peso === null)).toBe(true)
    // Y el «y N más» tampoco lleva su suma.
    const muchas = Array.from({ length: 14 }, (_, i) => fila(`A${i}`, 5, 'alcista'))
    expect(cuadritosDelMapa(muchas, { hidden: true }).at(-1).peso).toBeNull()
  })
})

describe('ubicarCuadritos', () => {
  const area = (r) => (r.w / 100) * (r.h / 100)

  it('el área de cada uno es proporcional a lo que pesa, sin salirse de la caja ni pisarse', () => {
    const pesos = [47, 18, 15, 12, 8]
    const r = ubicarCuadritos(pesos)
    pesos.forEach((p, i) => expect(area(r[i])).toBeCloseTo(p / 100, 6))
    for (const x of r) {
      expect(x.x).toBeGreaterThanOrEqual(-1e-9)
      expect(x.y).toBeGreaterThanOrEqual(-1e-9)
      expect(x.x + x.w).toBeLessThanOrEqual(100 + 1e-9)
      expect(x.y + x.h).toBeLessThanOrEqual(100 + 1e-9)
    }
    for (let i = 0; i < r.length; i++) {
      for (let j = i + 1; j < r.length; j++) {
        const a = r[i], b = r[j]
        const pisa = a.x + 1e-9 < b.x + b.w && b.x + 1e-9 < a.x + a.w && a.y + 1e-9 < b.y + b.h && b.y + 1e-9 < a.y + a.h
        expect(pisa).toBe(false)
      }
    }
  })

  it('con «Ocultar saldos» (pesos null) todos ocupan lo mismo', () => {
    const r = ubicarCuadritos([null, null, null, null, null])
    for (const x of r) expect(area(x)).toBeCloseTo(1 / 5, 6)
  })

  it('cuadritos razonables: ninguno más de 4 veces más largo que ancho con 5 pesos parejos', () => {
    const r = ubicarCuadritos([22, 21, 20, 19, 18])
    for (const x of r) {
      const ancho = x.w * PROPORCION, alto = x.h
      expect(Math.max(ancho / alto, alto / ancho)).toBeLessThan(4)
    }
  })
})
