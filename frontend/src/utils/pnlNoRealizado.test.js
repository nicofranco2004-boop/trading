import { describe, it, expect } from 'vitest'
import { pnlNoRealizado } from './pnlNoRealizado'

describe('pnlNoRealizado (encabezado de Cartera)', () => {
  const totals = { value: 1200, invested: 1000 }       // modo de costo elegido
  const totalsToday = { value: 1200, invested: 1100 }  // costo al dólar de hoy
  const pf = { valueUsd: 105, investedUsd: 100 }

  it('en dólares: tenencias con el modo elegido + plazo fijo', () => {
    const r = pnlNoRealizado({ totals, totalsToday, pf, tcValuacion: 1000, moneda: 'USD' })
    expect(r.valor).toBe(1305)
    expect(r.invertido).toBe(1100)
    expect(r.pnl).toBe(205)
    expect(r.pct).toBeCloseTo(205 / 1100, 10)
  })

  it('en pesos: no depende del modo (costo de hoy) × dólar de hoy', () => {
    const r = pnlNoRealizado({ totals, totalsToday, pf, tcValuacion: 1000, moneda: 'ARS' })
    expect(r.valor).toBe(1305000)
    expect(r.invertido).toBe(1200000)
    expect(r.pnl).toBe(105000)
  })

  it('sin invertido no divide por cero', () => {
    const r = pnlNoRealizado({ totals: { value: 0, invested: 0 }, totalsToday: { value: 0, invested: 0 }, pf: null, tcValuacion: 1000 })
    expect(r.pct).toBe(0)
  })
})
