// El CAGR anualizaba sobre los meses que SOBREVIVEN los filtros de
// computeMonthlyReturns (sin capital, outliers), no sobre el tiempo transcurrido.
// Medido antes del fix: un usuario 12 meses afuera del mercado en el medio de su
// historia veía +26,8% anual cuando su plata, sobre los 30 meses reales, rindió
// +10,0%. Con un import que trae meses vacíos adelante, 14,2pp de aire.
//
// La regla: el span va de la PRIMERA a la ÚLTIMA clave con dato.
//   · vacíos del arranque (import) → afuera: no invertía todavía
//   · huecos del medio             → adentro: la plata existía y no rindió
import { describe, it, expect } from 'vitest'
import { computeMonthlyReturns, computeCAGR } from './insightsMetrics'

const mes = (y, m, ci, cf, dep = 0, wd = 0) => ({
  year: y, month: m, broker: 'global',
  capital_inicio: ci, capital_final: cf, deposits: dep, withdrawals: wd, pnl_realized: 0,
})
// 12 meses seguidos al +2%: crecimiento compuesto = +26,82%
const doceMesesAl2 = (y, desde = 1) =>
  Array.from({ length: 12 }, (_, i) =>
    mes(y, desde + i, 1000 * 1.02 ** i, 1000 * 1.02 ** (i + 1)))

const cagrDe = (filas) => computeCAGR(computeMonthlyReturns(filas))

describe('computeCAGR — el exponente va sobre el tiempo transcurrido', () => {
  it('usuario continuo: no cambia nada (span == meses con dato)', () => {
    const c = cagrDe(doceMesesAl2(2025))
    expect(c.months).toBe(12)
    expect(c.monthsWithData).toBe(12)
    expect(c.cagr).toBeCloseTo(0.2682, 3)
  })

  it('EL CASO CARO: 12 meses afuera en el medio ⇒ 26,8% pasa a 10,0%', () => {
    const filas = [
      ...Array.from({ length: 6 }, (_, i) => mes(2024, i + 1, 1000 * 1.02 ** i, 1000 * 1.02 ** (i + 1))),
      ...Array.from({ length: 12 }, (_, i) => mes(2024, i + 7, 0, 0)),   // liquidado
      ...Array.from({ length: 6 }, (_, i) => mes(2026, i + 1, 1126 * 1.02 ** i, 1126 * 1.02 ** (i + 1))),
    ]
    const c = cagrDe(filas)
    expect(c.monthsWithData).toBe(12)   // solo 12 meses tuvieron retorno…
    expect(c.months).toBe(30)           // …pero pasaron 30
    expect(c.cagr).toBeCloseTo(0.100, 2)
  })

  it('import con meses vacíos ADELANTE: no penaliza, span arranca al invertir', () => {
    // Los meses vacíos del import no son "estuvo en cash": todavía no existía la
    // cartera. Contarlos bajaría el CAGR a ~12,6% y sería igual de falso.
    const filas = [
      ...Array.from({ length: 12 }, (_, i) => mes(2024, i + 1, 0, 0)),
      ...doceMesesAl2(2025),
    ]
    const c = cagrDe(filas)
    expect(c.months).toBe(12)
    expect(c.cagr).toBeCloseTo(0.2682, 3)
  })

  it('vacíos ADELANTE y hueco en el MEDIO a la vez', () => {
    const filas = [
      ...Array.from({ length: 6 }, (_, i) => mes(2023, i + 1, 0, 0)),         // trimmed
      ...Array.from({ length: 3 }, (_, i) => mes(2024, i + 1, 1000, 1020)),   // ene-mar 24
      ...Array.from({ length: 6 }, (_, i) => mes(2024, i + 4, 0, 0)),         // hueco: cuenta
      ...Array.from({ length: 3 }, (_, i) => mes(2024, i + 10, 1000, 1020)),  // oct-dic 24
    ]
    const c = cagrDe(filas)
    expect(c.monthsWithData).toBe(6)
    expect(c.months).toBe(12)           // ene-24 → dic-24
  })

  it('cruza años en el span', () => {
    const c = cagrDe([...doceMesesAl2(2025, 7).slice(0, 6), ...doceMesesAl2(2026).slice(0, 6)])
    expect(c.months).toBe(12)           // jul-25 → jun-26
  })

  it('el número que se MUESTRA es el transcurrido, no el de meses con dato', () => {
    // diagnostics.js dice "sobre N meses de historial" y Dashboard imprime
    // "N meses" — con el conteo viejo, un usuario con 30 meses de historia leía
    // "12 meses" y no tenía forma de notar el problema.
    const filas = [
      ...Array.from({ length: 3 }, (_, i) => mes(2024, i + 1, 1000, 1020)),
      ...Array.from({ length: 20 }, (_, i) => mes(2024, i + 4, 0, 0)),
      ...Array.from({ length: 3 }, (_, i) => mes(2026, i + 1, 1000, 1020)),
    ]
    const c = cagrDe(filas)
    expect(c.months).toBe(27)      // ene-24 → mar-26, inclusive
    expect(c.monthsWithData).toBe(6)
  })
})

describe('computeCAGR — bordes', () => {
  it('menos de 2 meses con dato ⇒ null', () => {
    expect(cagrDe([mes(2025, 1, 1000, 1100)])).toBeNull()
    expect(cagrDe([])).toBeNull()
  })

  it('dos meses consecutivos anualizan sobre 2, no sobre 1', () => {
    const c = cagrDe([mes(2025, 1, 1000, 1100), mes(2025, 2, 1100, 1210)])
    expect(c.months).toBe(2)
    expect(c.cagr).toBeCloseTo(Math.pow(1.21, 6) - 1, 6)
  })

  it('pérdida total sigue devolviendo −100% y no NaN', () => {
    const c = cagrDe([mes(2025, 1, 1000, 1), mes(2025, 2, 1000, 1)])
    expect(c.cagr).toBe(-1)
    expect(Number.isNaN(c.cagr)).toBe(false)
  })

  it('el crecimiento total NO depende del span (solo la anualización)', () => {
    const seguido = cagrDe(doceMesesAl2(2025))
    const conHueco = cagrDe([
      ...doceMesesAl2(2025).slice(0, 6),
      ...Array.from({ length: 12 }, (_, i) => mes(2025, i + 7, 0, 0)).slice(0, 6),
      ...Array.from({ length: 6 }, (_, i) => mes(2026, i + 1, 1126 * 1.02 ** i, 1126 * 1.02 ** (i + 1))),
    ])
    expect(conHueco.totalGrowth).toBeCloseTo(seguido.totalGrowth, 6)
    expect(conHueco.cagr).toBeLessThan(seguido.cagr)   // mismo crecimiento, más tiempo
  })
})
