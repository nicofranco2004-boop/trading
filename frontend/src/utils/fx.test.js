import { describe, it, expect } from 'vitest'
import { lookupHistoricalDolar } from './fx.js'

const LIVE = 1500

const BENCH = {
  dolar_blue: {
    '2024-01': 1000,
    '2024-02': 1050,
    '2024-04': 1100,   // March missing intentionally — gap test
    '2025-12': 1300,
  },
}

const NOW = new Date(2026, 4, 15) // May 2026 (month is 0-indexed in Date)

describe('Current calendar month → liveTc', () => {
  it('exact (year, month) of today returns liveTc', () => {
    expect(lookupHistoricalDolar(BENCH, 2026, 5, LIVE, NOW)).toBe(LIVE)
  })
  it('current month wins even if bench has data for it', () => {
    const benchWithCurrent = { dolar_blue: { ...BENCH.dolar_blue, '2026-05': 9999 } }
    expect(lookupHistoricalDolar(benchWithCurrent, 2026, 5, LIVE, NOW)).toBe(LIVE)
  })
})

describe('Exact match in bench', () => {
  it('returns the rate for the exact month', () => {
    expect(lookupHistoricalDolar(BENCH, 2024, 1, LIVE, NOW)).toBe(1000)
    expect(lookupHistoricalDolar(BENCH, 2024, 2, LIVE, NOW)).toBe(1050)
    expect(lookupHistoricalDolar(BENCH, 2025, 12, LIVE, NOW)).toBe(1300)
  })
})

describe('Gap fallback — most recent month ≤ key', () => {
  it('March 2024 (missing) → falls back to Feb 2024', () => {
    expect(lookupHistoricalDolar(BENCH, 2024, 3, LIVE, NOW)).toBe(1050)
  })
  it('multi-month gap — May 2024 → falls back to April 2024', () => {
    expect(lookupHistoricalDolar(BENCH, 2024, 5, LIVE, NOW)).toBe(1100)
  })
  it('large gap — Aug 2025 → falls back to April 2024 (last known ≤)', () => {
    expect(lookupHistoricalDolar(BENCH, 2025, 8, LIVE, NOW)).toBe(1100)
  })
})

describe('Before earliest data → use earliest available', () => {
  it('Dec 2023 (before Jan 2024) → returns Jan 2024 rate', () => {
    expect(lookupHistoricalDolar(BENCH, 2023, 12, LIVE, NOW)).toBe(1000)
  })
})

describe('Defensive — missing/empty bench → liveTc', () => {
  it('null bench', () => {
    expect(lookupHistoricalDolar(null, 2024, 6, LIVE, NOW)).toBe(LIVE)
  })
  it('undefined bench', () => {
    expect(lookupHistoricalDolar(undefined, 2024, 6, LIVE, NOW)).toBe(LIVE)
  })
  it('bench without dolar_blue field', () => {
    expect(lookupHistoricalDolar({ sp500: {} }, 2024, 6, LIVE, NOW)).toBe(LIVE)
  })
  it('empty dolar_blue map', () => {
    expect(lookupHistoricalDolar({ dolar_blue: {} }, 2024, 6, LIVE, NOW)).toBe(LIVE)
  })
})

describe('Bench rate is null/undefined for the matched key → liveTc', () => {
  it('rate is null for found key', () => {
    const broken = { dolar_blue: { '2024-01': null } }
    expect(lookupHistoricalDolar(broken, 2024, 1, LIVE, NOW)).toBe(LIVE)
  })
})

describe('Future month (after today) — uses last historical ≤ key', () => {
  // No "future-FX leakage": for a row at June 2026 (after May "today"),
  // the lookup falls back to the most recent historical, NOT a forward-projected rate.
  it('June 2026 → falls back to last known (Dec 2025)', () => {
    expect(lookupHistoricalDolar(BENCH, 2026, 6, LIVE, NOW)).toBe(1300)
  })
})
