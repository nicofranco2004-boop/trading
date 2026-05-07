import { describe, it, expect } from 'vitest'
import { buildEvolutionFromSnapshots } from './evolution.js'

const TCB = 1500

const BENCH = {
  dolar_blue: {
    '2025-01': 1000,
    '2025-02': 1100,
    '2025-03': 1200,
    '2026-04': 1400,
  },
}

// ── Guards ────────────────────────────────────────────────────────────────────

describe('Returns null when there are <2 snapshots', () => {
  it('null snapshots', () => {
    expect(buildEvolutionFromSnapshots(null, [], BENCH, TCB)).toBe(null)
  })
  it('undefined snapshots', () => {
    expect(buildEvolutionFromSnapshots(undefined, [], BENCH, TCB)).toBe(null)
  })
  it('empty array', () => {
    expect(buildEvolutionFromSnapshots([], [], BENCH, TCB)).toBe(null)
  })
  it('single snapshot', () => {
    const snaps = [{ date: '2025-02-01', total_value: 100, total_invested: 100, net_deposited: 100 }]
    expect(buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)).toBe(null)
  })
})

// ── USD core math ─────────────────────────────────────────────────────────────

describe('USD: 2 snapshots, simple growth', () => {
  const snaps = [
    { date: '2025-02-01', total_value: 1000, total_invested: 800, net_deposited: 1000 },
    { date: '2025-02-15', total_value: 1100, total_invested: 800, net_deposited: 1000 },
  ]
  const result = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)

  it('produces 2 USD points', () => expect(result.seriesUsd.length).toBe(2))
  it('first point: 0% (value == baseline)', () => expect(result.seriesUsd[0].total).toBe(0))
  it('second point: 10% gain', () => expect(result.seriesUsd[1].total).toBe(10))
  it('label is MM-DD', () => {
    expect(result.seriesUsd[0].label).toBe('02-01')
    expect(result.seriesUsd[1].label).toBe('02-15')
  })
  it('key is full ISO date', () => {
    expect(result.seriesUsd[0].key).toBe('2025-02-01')
    expect(result.seriesUsd[1].key).toBe('2025-02-15')
  })
  it('realized = 0 with no monthly entries', () => {
    expect(result.seriesUsd[0].realized).toBe(0)
    expect(result.seriesUsd[1].realized).toBe(0)
  })
})

describe('USD: snapshots are sorted ascending regardless of input order', () => {
  const snaps = [
    { date: '2025-03-15', total_value: 1200, total_invested: 800, net_deposited: 1000 },  // later
    { date: '2025-02-01', total_value: 1000, total_invested: 800, net_deposited: 1000 },  // earlier
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
  it('first point is the earlier date', () => expect(r.seriesUsd[0].key).toBe('2025-02-01'))
  it('second point is the later date', () => expect(r.seriesUsd[1].key).toBe('2025-03-15'))
  it('% growth applied to correct point', () => {
    expect(r.seriesUsd[0].total).toBe(0)
    expect(r.seriesUsd[1].total).toBe(20)
  })
})

describe('USD: legacy snapshot (net_deposited=0) falls back to total_invested', () => {
  const snaps = [
    { date: '2025-01-01', total_value: 1000, total_invested: 800, net_deposited: 0 },
    { date: '2025-01-15', total_value: 880,  total_invested: 800, net_deposited: 0 },
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
  it('first point: (1000-800)/800 = 25%', () => expect(r.seriesUsd[0].total).toBe(25))
  it('second point: (880-800)/800 = 10%', () => expect(r.seriesUsd[1].total).toBe(10))
})

describe('USD: zero baseline → 0% (no division by zero)', () => {
  const snaps = [
    { date: '2025-02-01', total_value: 0, total_invested: 0, net_deposited: 0 },
    { date: '2025-02-02', total_value: 100, total_invested: 0, net_deposited: 0 },
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
  it('first total = 0', () => expect(r.seriesUsd[0].total).toBe(0))
  it('second total = 0 (baseline still 0)', () => expect(r.seriesUsd[1].total).toBe(0))
})

// ── Realized line from monthly_entries ────────────────────────────────────────

describe('Realized line: cumulative from monthly_entries, step-matched by month', () => {
  const monthly = [
    { broker: 'global', year: 2025, month: 1, pnl_realized: 50 },   // Jan: cum=50
    { broker: 'global', year: 2025, month: 2, pnl_realized: 30 },   // Feb: cum=80
    { broker: 'global', year: 2025, month: 3, pnl_realized: -10 },  // Mar: cum=70
  ]
  const snaps = [
    { date: '2025-01-15', total_value: 1000, net_deposited: 1000 },  // baseline=1000, cumR=50 → 5%
    { date: '2025-02-15', total_value: 1100, net_deposited: 1000 },  // baseline=1000, cumR=80 → 8%
    { date: '2025-03-15', total_value: 1200, net_deposited: 1000 },  // baseline=1000, cumR=70 → 7%
  ]
  const r = buildEvolutionFromSnapshots(snaps, monthly, BENCH, TCB)
  it('Jan snap: realized = 5%', () => expect(r.seriesUsd[0].realized).toBe(5))
  it('Feb snap: realized = 8%', () => expect(r.seriesUsd[1].realized).toBe(8))
  it('Mar snap: realized = 7% (negative March cancels)', () => expect(r.seriesUsd[2].realized).toBe(7))
})

describe('Realized line: snapshot before any monthly entry → 0%', () => {
  const monthly = [{ broker: 'global', year: 2025, month: 5, pnl_realized: 100 }]
  const snaps = [
    { date: '2025-01-01', total_value: 1000, net_deposited: 1000 },  // before May entry
    { date: '2025-02-01', total_value: 1100, net_deposited: 1000 },
  ]
  const r = buildEvolutionFromSnapshots(snaps, monthly, BENCH, TCB)
  it('all pre-monthly snaps have realized=0', () => {
    expect(r.seriesUsd[0].realized).toBe(0)
    expect(r.seriesUsd[1].realized).toBe(0)
  })
})

describe('Realized line: snapshot after gap month uses last known cumulative', () => {
  const monthly = [
    { broker: 'global', year: 2025, month: 1, pnl_realized: 100 },   // Jan: cum=100
    // Feb missing
    { broker: 'global', year: 2025, month: 3, pnl_realized: 50 },    // Mar: cum=150
  ]
  const snaps = [
    { date: '2025-02-15', total_value: 1100, net_deposited: 1000 },  // Feb gap → falls back to Jan cum=100 → 10%
    { date: '2025-03-15', total_value: 1150, net_deposited: 1000 },  // Mar exists → 15%
  ]
  const r = buildEvolutionFromSnapshots(snaps, monthly, BENCH, TCB)
  it('Feb snap (gap month) → uses Jan cum', () => expect(r.seriesUsd[0].realized).toBe(10))
  it('Mar snap → uses Mar cum', () => expect(r.seriesUsd[1].realized).toBe(15))
})

// ── ARS series uses historical FX of snapshot's month ─────────────────────────

describe('ARS: each snapshot converted at its own historical FX', () => {
  const snaps = [
    { date: '2025-01-15', total_value: 1000, net_deposited: 1000 },  // FX=1000 (Jan)
    { date: '2025-02-15', total_value: 1100, net_deposited: 1000 },  // FX=1100 (Feb)
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
  // Jan: valueArs=1000*1000=1M, baselineArs=1000*1000=1M → 0%
  // Feb: valueArs=1100*1100=1.21M, baselineArs=1000*1100=1.1M → (1.21M-1.1M)/1.1M = 10%
  // (note: the % per-point matches USD because value & baseline use SAME fx → fx cancels)
  it('Jan ARS: 0%', () => expect(r.seriesArs[0].total).toBe(0))
  it('Feb ARS: 10% (fx cancels in pct calc)', () => expect(r.seriesArs[1].total).toBe(10))
})

describe('ARS realized: cumRealized × fx_at_snap / baselineArs', () => {
  const monthly = [
    { broker: 'global', year: 2025, month: 1, pnl_realized: 100 },  // cum=100
  ]
  const snaps = [
    { date: '2025-01-15', total_value: 1000, net_deposited: 1000 },
  ]
  const snaps2 = [
    snaps[0],
    { date: '2025-02-15', total_value: 1000, net_deposited: 1000 },
  ]
  const r = buildEvolutionFromSnapshots(snaps2, monthly, BENCH, TCB)
  // Jan: cumR=100, fx=1000 → realArs = 100*1000 / (1000*1000) * 100 = 10%
  // Feb: cumR=100 (Feb missing → falls back to Jan), fx=1100 → realArs = 100*1100 / (1000*1100) * 100 = 10%
  it('Jan ARS realized = 10%', () => expect(r.seriesArs[0].realized).toBe(10))
  it('Feb ARS realized = 10% (still 10% since fx cancels)', () => expect(r.seriesArs[1].realized).toBe(10))
})

// ── Robustness ────────────────────────────────────────────────────────────────

describe('Robustness — bench null', () => {
  const snaps = [
    { date: '2025-02-01', total_value: 1000, net_deposited: 1000 },
    { date: '2025-02-15', total_value: 1100, net_deposited: 1000 },
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], null, TCB)
  it('still produces both series', () => {
    expect(r.seriesUsd.length).toBe(2)
    expect(r.seriesArs.length).toBe(2)
  })
  it('USD math unaffected by missing bench', () => {
    expect(r.seriesUsd[1].total).toBe(10)
  })
  it('ARS uses tcBlue fallback (FX cancels in % anyway)', () => {
    expect(r.seriesArs[1].total).toBe(10)
  })
})

describe('Robustness — globalMonthly empty', () => {
  const snaps = [
    { date: '2025-02-01', total_value: 1000, net_deposited: 1000 },
    { date: '2025-02-15', total_value: 1100, net_deposited: 1000 },
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
  it('realized line = 0 throughout', () => {
    expect(r.seriesUsd[0].realized).toBe(0)
    expect(r.seriesUsd[1].realized).toBe(0)
  })
})
