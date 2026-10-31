// La cuenta del «Mapa de tu cartera» (Panorama de Análisis técnico, 30/10):
//   · cada cuadrito con el peso y la tendencia de su fila de Tu lista (la misma
//     cuenta del % alcista), sin inventar otra;
//   · el efectivo y los plazos fijos son lo que falta para llegar a 100 %;
//   · el área de cada cuadrito es proporcional a lo que pesa;
//   · con «Ocultar saldos» ni el tamaño, ni el orden, ni el % dicen cuánto pesa.
import { describe, it, expect } from 'vitest'
import { cuadritosDelMapa, ubicarCuadritos, sinLecturaDe, conElDia, colorDelModo, losExtremosDeHoy, MAX_CUADRITOS, PROPORCION } from './mapaCartera'

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

describe('sinLecturaDe: qué hay en lo que falta para 100 %, del mismo pedido que las filas', () => {
  it('efectivo, plazos fijos, los dos o nada (sin_medir de POST /api/tecnico/lista)', () => {
    expect(sinLecturaDe({ efectivo: 0.15, plazos_fijos: null })).toEqual(['efectivo'])
    expect(sinLecturaDe({ efectivo: null, plazos_fijos: 0.1 })).toEqual(['plazos fijos'])
    expect(sinLecturaDe({ efectivo: 0.1, plazos_fijos: 0.1 })).toEqual(['efectivo', 'plazos fijos'])
    expect(sinLecturaDe(null)).toEqual([])
    // Y el nombre del cuadrito sale de ahí.
    const filas = [fila('GGAL', 80, 'alcista')]
    expect(cuadritosDelMapa(filas, { sinLectura: sinLecturaDe({ efectivo: 0.2 }) }).map(c => c.nombre)).toEqual(['GGAL', 'Efectivo'])
  })
})

// Lo del día (GET /api/cartera/mapa-del-dia): el servidor manda % en puntos y
// por (asset, local), la misma clave de los cuadritos.
const DEL_DIA = {
  cartera: { pct: 0.8, usd: 120 },
  activos: [
    { asset: 'AAPL', local: false, hoy: { pct: 2, usd: 150 }, dia_txt: 'hoy', promedio_pct: 30 },
    { asset: 'GGAL', local: true, hoy: null, dia_txt: 'ayer', promedio_pct: -10 },
    { asset: 'GGAL', local: false, hoy: { pct: 5, usd: 999 }, dia_txt: 'hoy', promedio_pct: 0 },   // el ADR: no es tu GGAL de BYMA
    { asset: 'MELI', local: false, hoy: { pct: -1, usd: -40 }, dia_txt: 'hoy', promedio_pct: null },
  ],
}

describe('conElDia, colorDelModo y losExtremosDeHoy', () => {
  it('cada cuadrito con lo suyo, por la clave de Tu lista (GGAL de BYMA no toma lo del ADR)', () => {
    const c = Object.fromEntries(conElDia(cuadritosDelMapa(FILAS), DEL_DIA).map(x => [x.clave, x]))
    expect(c['AAPL|0'].hoy).toEqual({ pct: 0.02, usd: 150 })
    expect(c['AAPL|0'].promedio).toBe(0.3)
    expect(c['GGAL|1'].hoy).toBeNull()
    expect(c['GGAL|1'].diaTxt).toBe('ayer')
    expect(c['GGAL|1'].promedio).toBe(-0.1)
    expect(c['MELI|0'].promedio).toBeNull()
    expect(c.efectivo.hoy).toBeNull()
    // Sin lo del día (no llegó): el mapa sigue, sin colores de hoy.
    expect(conElDia(cuadritosDelMapa(FILAS), null).every(x => x.hoy === null && x.promedio === null)).toBe(true)
  })
  it('el color: la rampa verde/roja en Hoy y Contra tu promedio, gris sin dato, los tonos del lienzo en Tendencia', () => {
    const c = Object.fromEntries(conElDia(cuadritosDelMapa(FILAS), DEL_DIA).map(x => [x.clave, x]))
    expect(colorDelModo(c['AAPL|0'], 'hoy').bg).toMatch(/--pol-up-/)
    expect(colorDelModo(c['MELI|0'], 'hoy').bg).toMatch(/--pol-down-/)
    expect(colorDelModo(c['GGAL|1'], 'hoy').bg).toBe('rgb(var(--bg-3))')
    expect(colorDelModo(c['GGAL|1'], 'promedio').bg).toMatch(/--pol-down-/)
    expect(colorDelModo(c['AAPL|0'], 'tendencia')).toBeNull()
  })
  it('lo que más sumó y restó hoy, en plata, con el nombre del cuadrito', () => {
    const nombres = new Map([['AAPL|0', 'Apple'], ['MELI|0', 'MELI']])
    const { sumo, resto } = losExtremosDeHoy(DEL_DIA, nombres)
    // El ADR de GGAL sumó más, pero también es tuyo sólo si lo tenés: acá lo es
    // (viene en activos), así que cuenta con su propio nombre.
    expect(sumo).toEqual({ nombre: 'GGAL', usd: 999, pct: 0.05 })
    expect(resto).toEqual({ nombre: 'MELI', usd: -40, pct: -0.01 })
    expect(losExtremosDeHoy(null)).toEqual({ sumo: null, resto: null })
  })
})
