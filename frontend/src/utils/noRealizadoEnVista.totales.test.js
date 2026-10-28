import { describe, it, expect } from 'vitest'
import { noRealizadoEnVista } from './valuation'

// El encabezado de Cartera le pasa sus sumas ya hechas (`totales`): la cuenta
// tiene que ser la misma que antes vivía inline en Positions.jsx.
describe('noRealizadoEnVista con `totales` (encabezado de Cartera)', () => {
  const pf = { extraValorUsd: 105, extraCostoUsd: 100 }

  it('en dólares: tenencias con el modo elegido + plazo fijo', () => {
    const r = noRealizadoEnVista({ ...pf, tcValuacion: 1000, moneda: 'USD', totales: { value: 1200, invested: 1000 } })
    expect(r.valor).toBe(1305)
    expect(r.costo).toBe(1100)
    expect(r.monto).toBe(205)
    expect(r.pct).toBeCloseTo(205 / 1100, 10)
  })

  it('en pesos: (costo de hoy + plazo fijo) × dólar de hoy', () => {
    const r = noRealizadoEnVista({ ...pf, tcValuacion: 1000, moneda: 'ARS', totales: { value: 1200, invested: 1100 } })
    expect(r.valor).toBe(1305000)
    expect(r.costo).toBe(1200000)
    expect(r.monto).toBe(105000)
  })

  it('sin costo no divide por cero', () => {
    expect(noRealizadoEnVista({ tcValuacion: 1000, totales: { value: 0, invested: 0 } }).pct).toBe(0)
  })
})
