import { describe, it, expect } from 'vitest'
import { computeMonthlyReturns, computeCAGR } from './insightsMetrics.js'

// ── computeMonthlyReturns (Modified Dietz) ──────────────────────────────────

describe('computeMonthlyReturns', () => {
  it('returns [] for null/empty input', () => {
    expect(computeMonthlyReturns(null)).toEqual([])
    expect(computeMonthlyReturns([])).toEqual([])
  })

  it('simple month sin flujos: ret = (end - start) / start', () => {
    const out = computeMonthlyReturns([
      { year: 2026, month: 2, capital_inicio: 1000, capital_final: 1100, deposits: 0, withdrawals: 0 },
    ])
    expect(out).toHaveLength(1)
    expect(out[0].key).toBe('2026-02')
    expect(out[0].return).toBeCloseTo(0.1, 6)
  })

  it('pondera el flujo al 50% (denominador Modified Dietz)', () => {
    // start 1000, depósito 200, end 1300 → gain real = 100
    // denom = 1000 + 200*0.5 = 1100 → ret = 100/1100
    const out = computeMonthlyReturns([
      { year: 2026, month: 3, capital_inicio: 1000, capital_final: 1300, deposits: 200, withdrawals: 0 },
    ])
    expect(out[0].return).toBeCloseTo(100 / 1100, 6)
  })

  it('saltea meses con capital insignificante (start ≤ 100 y flujo ≤ 100)', () => {
    const out = computeMonthlyReturns([
      { year: 2026, month: 1, capital_inicio: 50, capital_final: 60, deposits: 0, withdrawals: 0 },
    ])
    expect(out).toEqual([])
  })

  it('descarta outliers (|ret| > 300%, probable bug de data)', () => {
    const out = computeMonthlyReturns([
      { year: 2026, month: 1, capital_inicio: 1000, capital_final: 5000, deposits: 0, withdrawals: 0 },
    ])
    expect(out).toEqual([])
  })

  it('ordena por año/mes antes de calcular', () => {
    const out = computeMonthlyReturns([
      { year: 2026, month: 3, capital_inicio: 1050, capital_final: 1100, deposits: 0, withdrawals: 0 },
      { year: 2026, month: 2, capital_inicio: 1000, capital_final: 1050, deposits: 0, withdrawals: 0 },
    ])
    expect(out.map(r => r.key)).toEqual(['2026-02', '2026-03'])
  })
})

// ── computeCAGR ─────────────────────────────────────────────────────────────

describe('computeCAGR', () => {
  it('null con menos de 2 meses', () => {
    expect(computeCAGR(null)).toBe(null)
    expect(computeCAGR([])).toBe(null)
    expect(computeCAGR([{ return: 0.1 }])).toBe(null)
  })

  it('12 meses de +1% → CAGR ≈ crecimiento total (sin extrapolar)', () => {
    const mr = Array.from({ length: 12 }, () => ({ return: 0.01 }))
    const c = computeCAGR(mr)
    expect(c.months).toBe(12)
    expect(c.totalGrowth).toBeCloseTo(Math.pow(1.01, 12) - 1, 6) // ≈ 0.1268
    expect(c.cagr).toBeCloseTo(Math.pow(1.01, 12) - 1, 6)
  })

  it('períodos cortos anualizan (extrapolan) — 2 meses planos = 0', () => {
    const c = computeCAGR([{ return: 0 }, { return: 0 }])
    expect(c.totalGrowth).toBe(0)
    expect(c.cagr).toBe(0)
    expect(c.months).toBe(2)
  })

  it('pérdida total (≤ -99.9%) hace floor en -100% en vez de NaN', () => {
    const c = computeCAGR([{ return: -1 }, { return: 0 }])
    expect(c.cagr).toBe(-1)
    expect(c.totalGrowth).toBe(-1)
  })

  // Regresión 2026-05-27: si computeCAGR no extrae r.return y opera sobre los
  // objetos {key, return} que devuelve computeMonthlyReturns, da NaN.
  it('encadena el output real de computeMonthlyReturns sin dar NaN', () => {
    const mr = computeMonthlyReturns([
      { year: 2026, month: 2, capital_inicio: 1000, capital_final: 1050, deposits: 0, withdrawals: 0 },
      { year: 2026, month: 3, capital_inicio: 1050, capital_final: 1100, deposits: 0, withdrawals: 0 },
      { year: 2026, month: 4, capital_inicio: 1100, capital_final: 1200, deposits: 0, withdrawals: 0 },
    ])
    const c = computeCAGR(mr)
    expect(c.months).toBe(3)
    expect(Number.isFinite(c.cagr)).toBe(true)
    expect(Number.isFinite(c.totalGrowth)).toBe(true)
    expect(c.cagr).toBeGreaterThan(0)
  })
})
