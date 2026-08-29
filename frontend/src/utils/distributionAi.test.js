import { describe, it, expect } from 'vitest'
import { toDistributionAiParams } from './distributionAi.js'
import { computeClassBreakdown } from './assetClass.js'

const BROKERS = [{ name: 'Balanz', currency: 'ARS' }, { name: 'Schwab', currency: 'USD' }]
const P = [
  { asset: 'AAPL', broker: 'Schwab', value_usd: 1200, pnl_usd: 200, is_cash: 0 },
  { asset: 'AL30', broker: 'Balanz', asset_type: 'BOND', value_usd: 1050, pnl_usd: 50, is_cash: 0 },
  { asset: 'ARS', broker: 'Balanz', is_cash: 1, value_usd: 750, pnl_usd: 0 },
]
const OPS = [{ asset: 'AL30', broker: 'Balanz', op_type: 'Interés', pnl_usd: 200, pnl_pct: null }]

describe('toDistributionAiParams', () => {
  it('traduce el breakdown al shape del builder', () => {
    const p = toDistributionAiParams(computeClassBreakdown(P, BROKERS, [], OPS))
    expect(p.total_usd).toBe(3000)
    const bono = p.slices.find(s => s.label === 'Bonos y letras')
    expect(bono).toMatchObject({ weight_pct: 35, pnl_usd: 250, pnl_pct: 25 })
  })

  it('omite la tasa cuando el frontend decidió no publicarla', () => {
    // Venta sin pnl_pct → no hay con qué despejar el costo → sin tasa.
    const ops = [{ asset: 'AAPL', broker: 'Schwab', op_type: 'Venta', pnl_usd: 300, pnl_pct: null }]
    const p = toDistributionAiParams(computeClassBreakdown(P, BROKERS, [], ops))
    const us = p.slices.find(s => s.label === 'Acciones US')
    expect(us.pnl_usd).toBe(500)
    expect(us.pnl_pct).toBeUndefined()
  })

  it('el efectivo va sin resultado', () => {
    const p = toDistributionAiParams(computeClassBreakdown(P, BROKERS, [], OPS))
    const cash = p.slices.find(s => s.label === 'Efectivo')
    expect(cash.pnl_usd).toBeUndefined()
  })

  it('sin operations manda solo peso', () => {
    const p = toDistributionAiParams(computeClassBreakdown(P, BROKERS))
    expect(p.slices.every(s => s.pnl_usd === undefined)).toBe(true)
  })

  it('acota el tamaño del payload', () => {
    const many = Array.from({ length: 40 }, (_, i) => ({
      asset: `T${i}`, broker: 'Schwab', value_usd: 100 + i, pnl_usd: i, is_cash: 0,
    }))
    const p = toDistributionAiParams(computeClassBreakdown(many, BROKERS))
    expect(p.slices.length).toBeLessThanOrEqual(12)
    expect(p.slices.every(s => (s.assets || []).length <= 6)).toBe(true)
  })

  it('no explota con un breakdown vacío', () => {
    expect(toDistributionAiParams({ items: [], total: 0, unclassified: { pct: 0 } }).slices).toEqual([])
    expect(toDistributionAiParams(undefined).total_usd).toBe(0)
  })
})
