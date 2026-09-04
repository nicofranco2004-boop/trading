import { describe, it, expect } from 'vitest'
import { sumRowUSDT, sumRowARS } from './valuation'

// La fila agregada de la Cartera se valúa SUMANDO sus lotes. Antes re-valuaba el
// agregado como una posición sola, y por eso la suma de las filas no daba el TOTAL
// del pie (que se calcula lote por lote con computeBrokerValue sobre bposRaw).

describe('sumRowUSDT', () => {
  it('suma valor, P&L y costo de los lotes', () => {
    const r = sumRowUSDT([
      { value: 100, pnl: 20, price: 10, investedUsd: 80 },
      { value: 300, pnl: -50, price: 10, investedUsd: 350 },
    ])
    expect(r.value).toBe(400)
    expect(r.pnl).toBe(-30)
    expect(r.investedUsd).toBe(430)
  })

  it('el % sale del costo REAL sumado, no del criterio del primer lote', () => {
    const r = sumRowUSDT([
      { value: 100, pnl: 20, price: 10, investedUsd: 80 },
      { value: 300, pnl: -50, price: 10, investedUsd: 350 },
    ])
    expect(r.pnlPct).toBeCloseTo(-30 / 430, 10)
  })

  it('un lote sin precio no rompe la fila, y no ensucia el %', () => {
    const r = sumRowUSDT([
      { value: 100, pnl: 20, price: 10, investedUsd: 80 },
      { value: null, pnl: null, price: null, investedUsd: 500 },
    ])
    expect(r.value).toBe(100)
    // El costo TOTAL incluye el lote sin precio (columna "Invertido")...
    expect(r.investedUsd).toBe(580)
    // ...pero el % va sobre el costo de lo que sí se pudo valuar.
    expect(r.pnlPct).toBeCloseTo(20 / 80, 10)
  })

  it('si NINGÚN lote tiene precio, el valor es null pero el costo se conserva', () => {
    const r = sumRowUSDT([
      { value: null, pnl: null, price: null, investedUsd: 80 },
      { value: null, pnl: null, price: null, investedUsd: 20 },
    ])
    expect(r.value).toBeNull()
    expect(r.pnl).toBeNull()
    expect(r.investedUsd).toBe(100)
  })

  it('el precio unitario solo se muestra si TODOS los lotes coinciden', () => {
    const same = [{ value: 1, pnl: 0, price: 10, investedUsd: 1 }, { value: 1, pnl: 0, price: 10, investedUsd: 1 }]
    expect(sumRowUSDT(same).price).toBe(10)
    // asset_type distinto entre lotes → dos precios → mostrar uno mentiría.
    const diff = [{ value: 1, pnl: 0, price: 10, investedUsd: 1 }, { value: 1, pnl: 0, price: 999, investedUsd: 1 }]
    expect(sumRowUSDT(diff).price).toBeNull()
  })

  it('pnlPct es 0 y no NaN si el costo da 0', () => {
    const r = sumRowUSDT([{ value: 0, pnl: 0, price: 1, investedUsd: 0 }, { value: 0, pnl: 0, price: 1, investedUsd: 0 }])
    expect(r.pnlPct).toBe(0)
    expect(Number.isNaN(r.pnlPct)).toBe(false)
  })

  it('INVARIANTE: la fila agregada == la suma de sus lotes', () => {
    const lots = [
      { value: 8204.59, pnl: 1200, price: 5, investedUsd: 7004.59 },
      { value: 1362.83, pnl: -300, price: 5, investedUsd: 1662.83 },
      { value: 943.40, pnl: 40, price: 5, investedUsd: 903.40 },
    ]
    const r = sumRowUSDT(lots)
    expect(r.value).toBeCloseTo(lots.reduce((s, c) => s + c.value, 0), 10)
    expect(r.pnl).toBeCloseTo(lots.reduce((s, c) => s + c.pnl, 0), 10)
    expect(r.investedUsd).toBeCloseTo(lots.reduce((s, c) => s + c.investedUsd, 0), 10)
  })
})

describe('sumRowARS', () => {
  const lot = (o) => ({ valueArs: 0, valueUsd: 0, pnlArs: 0, pnlUsd: 0, priceArs: 100, invUsd: 0, ...o })

  it('suma las dos monedas y el costo USD ruteado', () => {
    const r = sumRowARS([
      lot({ valueArs: 100_000, valueUsd: 80, pnlArs: 10_000, pnlUsd: 8, invUsd: 72 }),
      lot({ valueArs: 300_000, valueUsd: 240, pnlArs: -5_000, pnlUsd: -4, invUsd: 244 }),
    ])
    expect(r.valueArs).toBe(400_000)
    expect(r.valueUsd).toBe(320)
    expect(r.pnlArs).toBe(5_000)
    expect(r.pnlUsd).toBe(4)
    expect(r.invUsd).toBe(316)
  })

  it('el % sale del costo en pesos sumado', () => {
    const r = sumRowARS([
      lot({ valueArs: 100_000, pnlArs: 10_000 }),
      lot({ valueArs: 300_000, pnlArs: -5_000 }),
    ])
    expect(r.pnlPct).toBeCloseTo(5_000 / 395_000, 10)
  })

  it('sin ningún precio el valor queda null y el costo USD se conserva', () => {
    const r = sumRowARS([
      { valueArs: null, valueUsd: null, pnlArs: null, pnlUsd: null, priceArs: null, invUsd: 50 },
      { valueArs: null, valueUsd: null, pnlArs: null, pnlUsd: null, priceArs: null, invUsd: 30 },
    ])
    expect(r.valueArs).toBeNull()
    expect(r.invUsd).toBe(80)
  })

  it('precios distintos entre lotes → no se muestra ninguno', () => {
    expect(sumRowARS([lot({ priceArs: 100 }), lot({ priceArs: 100 })]).priceArs).toBe(100)
    expect(sumRowARS([lot({ priceArs: 100 }), lot({ priceArs: 250 })]).priceArs).toBeNull()
  })
})
