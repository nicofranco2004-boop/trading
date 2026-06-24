import { describe, it, expect } from 'vitest'
import { buildComparison, relativeFill, topMetricsFor } from './fundamentalsCompare'

function md(key, category, value, direction) {
  return {
    key, category, label: key.toUpperCase(),
    value, value_label: value == null ? '—' : String(value), direction,
  }
}

function entry(ticker, overall, detail) {
  return { ticker, data: { available: true, ticker, score: { overall, label: 'X' }, metrics_detail: detail } }
}

describe('buildComparison', () => {
  it('picks winner by direction (lower-is-better)', () => {
    const cmp = buildComparison([
      entry('AAA', 80, [md('pe', 'valuation', 30, 'lower')]),
      entry('BBB', 70, [md('pe', 'valuation', 20, 'lower')]),
    ])
    const row = cmp.rows.find(r => r.key === 'pe')
    expect(cmp.tickers[row.winnerIndex]).toBe('BBB') // menor P/E gana
    expect(cmp.winsByTicker.BBB).toBe(1)
    expect(cmp.winsByTicker.AAA).toBe(0)
  })

  it('picks winner by direction (higher-is-better)', () => {
    const cmp = buildComparison([
      entry('AAA', 80, [md('roe', 'profitability', 30, 'higher')]),
      entry('BBB', 70, [md('roe', 'profitability', 50, 'higher')]),
    ])
    const row = cmp.rows.find(r => r.key === 'roe')
    expect(cmp.tickers[row.winnerIndex]).toBe('BBB')
  })

  it('treats a metric with <2 values as non-comparable (no winner)', () => {
    const cmp = buildComparison([
      entry('AAA', 80, [md('roe', 'profitability', 30, 'higher')]),
      entry('BBB', 70, [md('roe', 'profitability', null, 'higher')]),
    ])
    const row = cmp.rows.find(r => r.key === 'roe')
    expect(row.winnerIndex).toBe(-1)
    expect(row.comparable).toBe(false)
    expect(cmp.comparableCount).toBe(0)
  })

  it('declares no winner on a tie', () => {
    const cmp = buildComparison([
      entry('AAA', 80, [md('pe', 'valuation', 25, 'lower')]),
      entry('BBB', 70, [md('pe', 'valuation', 25, 'lower')]),
    ])
    const row = cmp.rows.find(r => r.key === 'pe')
    expect(row.winnerIndex).toBe(-1)
  })

  it('counts category winner by most wins, ties broken by overall', () => {
    const cmp = buildComparison([
      entry('AAA', 90, [
        md('roe', 'profitability', 50, 'higher'),
        md('net_margin', 'profitability', 10, 'higher'),
      ]),
      entry('BBB', 60, [
        md('roe', 'profitability', 40, 'higher'),
        md('net_margin', 'profitability', 20, 'higher'),
      ]),
    ])
    // 1 win each → tie → higher overall (AAA) wins category
    expect(cmp.categoryWinner.profitability.ticker).toBe('AAA')
  })

  it('ranks by overall desc and exposes a leader', () => {
    const cmp = buildComparison([
      entry('LOW', 40, [md('pe', 'valuation', 30, 'lower')]),
      entry('HIGH', 88, [md('pe', 'valuation', 20, 'lower')]),
    ])
    expect(cmp.ranking[0].ticker).toBe('HIGH')
    expect(cmp.leader.ticker).toBe('HIGH')
  })
})

describe('relativeFill', () => {
  it('returns 1 for the best end (higher-is-better)', () => {
    expect(relativeFill(100, 0, 100, 'higher')).toBe(1)
    expect(relativeFill(0, 0, 100, 'higher')).toBe(0)
  })
  it('inverts for lower-is-better', () => {
    expect(relativeFill(0, 0, 100, 'lower')).toBe(1)
    expect(relativeFill(100, 0, 100, 'lower')).toBe(0)
  })
  it('handles a degenerate range', () => {
    expect(relativeFill(5, 5, 5, 'higher')).toBe(1)
  })
})

describe('topMetricsFor', () => {
  it('returns up to N metrics with non-null values in canonical order', () => {
    const top = topMetricsFor({
      metrics_detail: [
        md('roe', 'profitability', 50, 'higher'),
        md('pe', 'valuation', 30, 'lower'),
        md('peg', 'valuation', null, 'lower'),
        md('net_margin', 'profitability', 12, 'higher'),
      ],
    }, 2)
    expect(top.map(t => t.key)).toEqual(['pe', 'roe']) // pe before roe in METRIC_ORDER
  })
})
