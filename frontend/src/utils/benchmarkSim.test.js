import { describe, it, expect } from 'vitest'
import {
  lookupMonthly,
  simulateBenchmark,
  simulateSp500,
  simulateDolarCash,
  simulateArsCash,
  computeInflationCumulative,
} from './benchmarkSim.js'

const month = (y, m, capInicio, capFinal, deposits = 0, withdrawals = 0) => ({
  year: y, month: m, capital_inicio: capInicio, capital_final: capFinal,
  deposits, withdrawals, pnl_realized: 0, pnl_unrealized: 0,
})

// ── lookupMonthly ─────────────────────────────────────────────────────────────

describe('lookupMonthly', () => {
  it('exact match', () => {
    expect(lookupMonthly({ '2025-01': 100 }, '2025-01')).toBe(100)
  })

  it('falls back to most recent earlier month', () => {
    const m = { '2025-01': 100, '2025-03': 130 }
    expect(lookupMonthly(m, '2025-02')).toBe(100)
    expect(lookupMonthly(m, '2025-04')).toBe(130)
  })

  it('falls back to oldest if requested key is before all', () => {
    const m = { '2025-03': 130, '2025-04': 140 }
    expect(lookupMonthly(m, '2025-01')).toBe(130)
  })

  it('null para mapa vacío', () => {
    expect(lookupMonthly({}, '2025-01')).toBe(null)
    expect(lookupMonthly(null, '2025-01')).toBe(null)
  })
})

// ── simulateBenchmark ─────────────────────────────────────────────────────────

describe('simulateBenchmark', () => {
  it('null sin entradas', () => {
    expect(simulateBenchmark([], () => 100)).toBe(null)
  })

  it('null si el primer mes no tiene precio', () => {
    const m = [month(2025, 1, 1000, 1000)]
    expect(simulateBenchmark(m, () => null)).toBe(null)
  })

  it('crece linealmente con el precio si no hay flujos', () => {
    // Capital inicial 1000 al precio 100 → 10 unidades.
    // Si el precio sube a 200, valor final = 10 * 200 = 2000.
    const m = [
      month(2025, 1, 1000, 0),
      month(2025, 2, 0, 0),
    ]
    const prices = { '2025-01': 100, '2025-02': 200 }
    const r = simulateBenchmark(m, k => prices[k])
    expect(r.finalUnits).toBeCloseTo(10, 5)
    expect(r.finalValue).toBeCloseTo(2000, 5)
  })

  it('aporte mensual se invierte al precio del mes', () => {
    // Mes 1: 1000 al precio 100 → 10 unidades.
    // Mes 2: depósito 200 al precio 200 → +1 unidad. Total 11.
    // Valor final = 11 * 200 = 2200.
    const m = [
      month(2025, 1, 1000, 0),
      month(2025, 2, 0, 0, 200, 0),
    ]
    const prices = { '2025-01': 100, '2025-02': 200 }
    const r = simulateBenchmark(m, k => prices[k])
    expect(r.finalUnits).toBeCloseTo(11, 5)
    expect(r.finalValue).toBeCloseTo(2200, 5)
  })

  it('retiro reduce unidades al precio del mes', () => {
    const m = [
      month(2025, 1, 1000, 0),                       // 10 units
      month(2025, 2, 0, 0, 0, 200),                  // -1 unit (retiro 200 al precio 200)
    ]
    const prices = { '2025-01': 100, '2025-02': 200 }
    const r = simulateBenchmark(m, k => prices[k])
    expect(r.finalUnits).toBeCloseTo(9, 5)
    expect(r.finalValue).toBeCloseTo(1800, 5)
  })
})

// ── simulateSp500 ─────────────────────────────────────────────────────────────

describe('simulateSp500', () => {
  it('null si no hay datos de S&P', () => {
    const m = [month(2025, 1, 1000, 1000)]
    expect(simulateSp500(m, null)).toBe(null)
    expect(simulateSp500(m, {})).toBe(null)
  })

  it('simula el comportamiento del S&P', () => {
    const m = [
      month(2025, 1, 1000, 0),
      month(2025, 2, 0, 0, 500, 0),
    ]
    const sp500 = { '2025-01': 5000, '2025-02': 5500 }
    const r = simulateSp500(m, sp500)
    // Mes 1: 1000 / 5000 = 0.2 units
    // Mes 2: + 500 / 5500 = ~0.0909 units. Total ~0.2909
    // Valor final = 0.2909 * 5500 = ~1600
    expect(r.finalUnits).toBeCloseTo(0.2 + 500 / 5500, 5)
    expect(r.finalValue).toBeCloseTo(0.2 * 5500 + 500, 1)
  })
})

// ── simulateDolarCash ─────────────────────────────────────────────────────────

describe('simulateDolarCash', () => {
  it('valor final = capital aportado total', () => {
    const m = [
      month(2025, 1, 1000, 0),                       // baseline 1000
      month(2025, 2, 0, 0, 500, 0),                  // +500
      month(2025, 3, 0, 0, 0, 200),                  // -200
    ]
    const r = simulateDolarCash(m)
    expect(r.finalValue).toBe(1300)  // 1000 + 500 - 200
  })

  it('null sin entradas', () => {
    expect(simulateDolarCash([])).toBe(null)
  })
})

// ── simulateArsCash ───────────────────────────────────────────────────────────

describe('simulateArsCash', () => {
  it('null si no hay datos de blue', () => {
    const m = [month(2025, 1, 1000, 0)]
    expect(simulateArsCash(m, null)).toBe(null)
  })

  it('USD-equivalente flat si el blue no se mueve', () => {
    const m = [
      month(2025, 1, 1000, 0),
      month(2025, 2, 0, 0, 500, 0),
    ]
    const blue = { '2025-01': 1000, '2025-02': 1000 }
    const r = simulateArsCash(m, blue)
    expect(r.finalPesos).toBe(1500 * 1000)         // 1500 USD * 1000 = 1.5M pesos
    expect(r.finalValue).toBe(1500)                // / 1000 = 1500 USD
  })

  it('USD-equivalente cae si el blue sube (peso devalúa)', () => {
    // 1000 USD aportados al blue 1000 = 1M pesos.
    // Al final, blue subió a 1500 → mismos 1M pesos = 666.67 USD.
    const m = [month(2025, 1, 1000, 0), month(2025, 2, 0, 0)]
    const blue = { '2025-01': 1000, '2025-02': 1500 }
    const r = simulateArsCash(m, blue)
    expect(r.finalPesos).toBe(1_000_000)
    expect(r.finalValue).toBeCloseTo(1_000_000 / 1500, 2)
  })

  it('aporte tardío entra al blue del mes', () => {
    // Mes 1: 1000 USD * 1000 = 1M pesos
    // Mes 2: deposito 500 USD * 1500 = 750k pesos. Total = 1.75M pesos.
    // Valor final en USD = 1.75M / 1500 = 1166.67
    const m = [
      month(2025, 1, 1000, 0),
      month(2025, 2, 0, 0, 500, 0),
    ]
    const blue = { '2025-01': 1000, '2025-02': 1500 }
    const r = simulateArsCash(m, blue)
    expect(r.finalPesos).toBe(1_750_000)
    expect(r.finalValue).toBeCloseTo(1_750_000 / 1500, 2)
  })
})

// ── computeInflationCumulative ───────────────────────────────────────────────

describe('computeInflationCumulative', () => {
  it('null si no hay datos de inflación', () => {
    const m = [month(2025, 1, 1000, 0)]
    expect(computeInflationCumulative(m, null)).toBe(null)
  })

  it('compone IPCs mensuales del período', () => {
    const m = [
      month(2025, 1, 1000, 0),
      month(2025, 3, 0, 0),
    ]
    // IPC del mes 2 = 5%, mes 3 = 4%. Cumulativo = 1.05 * 1.04 - 1 = 9.2%
    const inf = { '2025-01': 6, '2025-02': 5, '2025-03': 4, '2025-04': 3 }
    const r = computeInflationCumulative(m, inf)
    expect(r.cumPct).toBeCloseTo((1.05 * 1.04 - 1) * 100, 1)
    expect(r.monthsCounted).toBe(2)
  })

  it('null si no hay IPCs en el rango', () => {
    const m = [month(2025, 1, 1000, 0)]
    const inf = { '2024-12': 5 }
    expect(computeInflationCumulative(m, inf)).toBe(null)
  })
})
