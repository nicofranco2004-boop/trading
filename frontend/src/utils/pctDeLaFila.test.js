import { describe, it, expect } from 'vitest'
import { pctEnVista } from './pctDeLaFila'

// GGAL del demo (21/10/2026): 200 acciones en Cocos, pagadas ARS 850.000 cuando el
// dólar estaba más barato; hoy valen ARS 964.000 (USD 676,97 al MEP 1.424).
// En pesos ganó +13,4 %; en dólares perdió USD 132,56 (−16,4 %).
const ggal = {
  isAR: true,
  pnlPct: 114000 / 850000,          // nativo en pesos
  pnlUsd: -132.56,                  // base "dólar de compra"
  investedUsd: 676.97 + 132.56,     // USD 809,53 que valían esos pesos
}

describe('pctEnVista — el % va en la moneda del monto de al lado', () => {
  it('broker en pesos, vista en dólares: el % en USD, con el MISMO signo que el monto', () => {
    const pct = pctEnVista(ggal, 'USD')
    expect(pct).toBeCloseTo(-0.1637, 3)
    expect(Math.sign(pct)).toBe(Math.sign(ggal.pnlUsd))
  })

  it('broker en pesos, vista en pesos: el % nominal en pesos', () => {
    expect(pctEnVista(ggal, 'ARS')).toBeCloseTo(0.1341, 3)
  })

  it('broker en dólares: el mismo % en las dos vistas', () => {
    const nvda = { isAR: false, pnlPct: 0.253, pnlUsd: 1260, investedUsd: 4987.5 }
    expect(pctEnVista(nvda, 'USD')).toBe(0.253)
    expect(pctEnVista(nvda, 'ARS')).toBe(0.253)
  })

  it('fila que fusiona monedas: su % ya viene en USD y no se toca', () => {
    const fusion = { isAR: false, _multiCcy: true, pnlPct: -0.05, pnlUsd: 999, investedUsd: 1 }
    expect(pctEnVista(fusion, 'USD')).toBe(-0.05)
  })

  it('modo "dólar de hoy": los dos porcentajes coinciden, nada cambia', () => {
    const hoy = { isAR: true, pnlPct: 0.134, pnlUsd: 0.134 * 596.91, investedUsd: 596.91 }
    expect(pctEnVista(hoy, 'USD')).toBeCloseTo(pctEnVista(hoy, 'ARS'), 10)
  })

  it('sin costo no divide por cero', () => {
    expect(pctEnVista({ isAR: true, pnlPct: 0, pnlUsd: 0, investedUsd: 0 }, 'USD')).toBe(0)
    expect(pctEnVista(null, 'USD')).toBe(null)
  })
})
