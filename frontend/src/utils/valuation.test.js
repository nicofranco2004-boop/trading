import { describe, it, expect } from 'vitest'
import { computeBrokerValue, computePf } from './valuation.js'

// ─── helpers ────────────────────────────────────────────────────────────────

const TCB = 1200   // tcBlue used throughout
const TC1 = 1000   // tc_compra at buy time (historical)
const TC2 = 800    // another historical tc_compra

function pos(overrides) {
  return {
    broker:         'TestBroker',
    asset:          'AAPL',
    quantity:       0,
    invested:       0,
    is_cash:        false,
    tc_compra:      null,
    price_override: null,
    ...overrides,
  }
}

function usdBroker(name = 'Binance') {
  return { name, currency: 'USDT' }
}

function arsBroker(name = 'Cocos') {
  return { name, currency: 'ARS' }
}

// ─── USD broker ─────────────────────────────────────────────────────────────

describe('USD broker — single equity with live price', () => {
  const positions = [pos({ broker: 'Binance', asset: 'BTC', quantity: 2, invested: 50_000 })]
  const prices    = { BTC: 30_000 }
  const r         = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('value  = price × qty',              () => expect(r.value).toBeCloseTo(60_000))
  it('invested  = cost basis',            () => expect(r.invested).toBeCloseTo(50_000))
  it('pnlUsd  = value − invested',        () => expect(r.pnlUsd).toBeCloseTo(10_000))
  it('valueArs = 0 (not meaningful)',     () => expect(r.valueArs).toBe(0))
  it('invArs   = 0 (not meaningful)',     () => expect(r.invArs).toBe(0))
  it('pnlArs   = 0 (not meaningful)',     () => expect(r.pnlArs).toBe(0))
})

describe('USD broker — single equity, no live price (fallback to cost)', () => {
  const positions = [pos({ broker: 'Binance', asset: 'BTC', quantity: 5, invested: 40_000 })]
  const prices    = {}
  const r         = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('value falls back to invested',  () => expect(r.value).toBeCloseTo(40_000))
  it('invested unchanged',            () => expect(r.invested).toBeCloseTo(40_000))
  it('pnlUsd = 0 (no price data)',    () => expect(r.pnlUsd).toBeCloseTo(0))
})

describe('USD broker — price_override takes precedence over prices map', () => {
  const positions = [pos({ broker: 'Binance', asset: 'ETH', quantity: 10, invested: 20_000, price_override: 2_500 })]
  const prices    = { ETH: 1_000 }   // should be ignored
  const r         = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('uses price_override, not prices map', () => expect(r.value).toBeCloseTo(25_000))
  it('pnlUsd uses override price',          () => expect(r.pnlUsd).toBeCloseTo(5_000))
})

describe('USD broker — cash position', () => {
  const positions = [pos({ broker: 'Binance', is_cash: true, invested: 5_000 })]
  const prices    = {}
  const r         = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('value  = invested (cash = value)',  () => expect(r.value).toBeCloseTo(5_000))
  it('invested = invested',               () => expect(r.invested).toBeCloseTo(5_000))
  it('pnlUsd = 0 (cash has no gain)',     () => expect(r.pnlUsd).toBeCloseTo(0))
})

describe('USD broker — mixed: equity (with price) + cash', () => {
  const positions = [
    pos({ broker: 'Binance', asset: 'SOL', quantity: 100, invested: 8_000 }),
    pos({ broker: 'Binance', is_cash: true, invested: 2_000 }),
  ]
  const prices = { SOL: 100 }
  const r      = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('value   = equity mkt + cash',  () => expect(r.value).toBeCloseTo(12_000))
  it('invested = cost + cash',       () => expect(r.invested).toBeCloseTo(10_000))
  it('pnlUsd  = only equity gain',   () => expect(r.pnlUsd).toBeCloseTo(2_000))
})

describe('USD broker — multiple equities, mixed prices', () => {
  const positions = [
    pos({ broker: 'Binance', asset: 'BTC',  quantity: 1,   invested: 30_000 }),   // has price
    pos({ broker: 'Binance', asset: 'DOGE', quantity: 100, invested: 500 }),      // no price
  ]
  const prices = { BTC: 35_000 }
  const r      = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('value  = BTC mkt + DOGE fallback',   () => expect(r.value).toBeCloseTo(35_500))
  it('invested = both cost bases',         () => expect(r.invested).toBeCloseTo(30_500))
  it('pnlUsd = only BTC gain',             () => expect(r.pnlUsd).toBeCloseTo(5_000))
})

// ─── ARS broker ─────────────────────────────────────────────────────────────

describe('ARS broker — single equity with live ARS price (no FX phantom)', () => {
  // Modelo post-fix: el cost basis USD se computa al blue actual, no al
  // tc_compra histórico. Eso elimina el "FX phantom" en el P&L.
  const positions = [pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 80_000, tc_compra: TC1 })]
  const prices    = { 'GGAL.BA': 12_000 }
  const r         = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('valueArs = price × qty',                          () => expect(r.valueArs).toBeCloseTo(120_000))
  it('value    = valueArs / tcBlue',                    () => expect(r.value).toBeCloseTo(120_000 / TCB))
  it('invArs   = invested (native ARS)',                () => expect(r.invArs).toBeCloseTo(80_000))
  it('invested = invArs / tcBlue (current rate, no FX phantom)', () => expect(r.invested).toBeCloseTo(80_000 / TCB))
  it('pnlArs   = valueArs − invArs',                    () => expect(r.pnlArs).toBeCloseTo(40_000))
  it('pnlUsd   = pnlArs / tcBlue (asset return only)',  () => expect(r.pnlUsd).toBeCloseTo(40_000 / TCB))
})

describe('ARS broker — FX phantom eliminated', () => {
  // Documenta la corrección: para brokers ARS, value e invested se mueven
  // juntos con el blue, así que el P&L USD refleja SOLO el rendimiento del
  // activo. Si los pesos quedan quietos sin operar, no hay drift FX en USD.
  const positions = [pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 80_000, tc_compra: TC1 })]
  const prices    = { 'GGAL.BA': 12_000 }
  const r         = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('pnlUsd === pnlArs / tcBlue (basis aligned)', () => {
    expect(r.pnlUsd).toBeCloseTo(r.pnlArs / TCB, 4)
  })

  it('tc_compra es ignorado (queda solo como dato informativo)', () => {
    const sameButDifferentTcCompra = computeBrokerValue(
      [pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 80_000, tc_compra: 500 })],
      prices, arsBroker(), TCB,
    )
    expect(sameButDifferentTcCompra.invested).toBeCloseTo(r.invested, 4)
    expect(sameButDifferentTcCompra.pnlUsd).toBeCloseTo(r.pnlUsd, 4)
  })
})

describe('ARS broker — no live price (fallback to cost basis)', () => {
  const positions = [pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 90_000, tc_compra: TC1 })]
  const prices    = {}
  const r         = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('valueArs falls back to invested (ARS)',    () => expect(r.valueArs).toBeCloseTo(90_000))
  it('value    falls back to invUsd at current blue', () => expect(r.value).toBeCloseTo(90_000 / TCB))
  it('pnlArs = 0',                               () => expect(r.pnlArs).toBeCloseTo(0))
  it('pnlUsd = 0',                               () => expect(r.pnlUsd).toBeCloseTo(0))
})

describe('ARS broker — no live price, no tc_compra (uses tcBlue)', () => {
  const positions = [pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 90_000, tc_compra: null })]
  const prices    = {}
  const r         = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('invested = invested / tcBlue',               () => expect(r.invested).toBeCloseTo(90_000 / TCB))
  it('value = invested (no price, falls back)',    () => expect(r.value).toBeCloseTo(90_000 / TCB))
  it('pnlUsd = 0',                                () => expect(r.pnlUsd).toBeCloseTo(0))
})

describe('ARS broker — price_override takes precedence', () => {
  const positions = [
    pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 80_000, tc_compra: TC1, price_override: 10_000 }),
  ]
  const prices = { 'GGAL.BA': 5_000 }   // should be ignored
  const r      = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('uses price_override, not prices map',  () => expect(r.valueArs).toBeCloseTo(100_000))
  it('pnlArs uses override',                 () => expect(r.pnlArs).toBeCloseTo(20_000))
})

describe('ARS broker — cash position', () => {
  const positions = [pos({ broker: 'Cocos', is_cash: true, invested: 120_000 })]
  const prices    = {}
  const r         = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('valueArs = invested',                   () => expect(r.valueArs).toBeCloseTo(120_000))
  it('value    = invested / tcBlue',          () => expect(r.value).toBeCloseTo(120_000 / TCB))
  it('invArs   = invested',                   () => expect(r.invArs).toBeCloseTo(120_000))
  it('invested = cashUsd  (cost = value)',    () => expect(r.invested).toBeCloseTo(120_000 / TCB))
  it('pnlArs = 0 (cash has no gain)',         () => expect(r.pnlArs).toBeCloseTo(0))
  it('pnlUsd = 0 (cash has no gain)',         () => expect(r.pnlUsd).toBeCloseTo(0))
})

describe('ARS broker — mixed: equity (with price) + cash', () => {
  const positions = [
    pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 80_000, tc_compra: TC1 }),
    pos({ broker: 'Cocos', is_cash: true, invested: 24_000 }),
  ]
  const prices = { 'GGAL.BA': 12_000 }
  const r      = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('valueArs = equity mkt + cash',        () => expect(r.valueArs).toBeCloseTo(144_000))
  it('value    = valueArs / tcBlue-ish',    () => expect(r.value).toBeCloseTo(120_000 / TCB + 24_000 / TCB))
  it('invArs   = equity + cash invested',   () => expect(r.invArs).toBeCloseTo(104_000))
  it('pnlArs   = only equity gain',         () => expect(r.pnlArs).toBeCloseTo(40_000))
})

describe('ARS broker — multiple equities (tc_compra ignored, current blue used)', () => {
  const positions = [
    pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 80_000, tc_compra: TC1 }),  // tc_compra es informativo
    pos({ broker: 'Cocos', asset: 'PAMP', quantity: 5,  invested: 30_000, tc_compra: TC2 }),  // tc_compra es informativo
  ]
  const prices = { 'GGAL.BA': 12_000, 'PAMP.BA': 7_000 }
  const r      = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('valueArs = sum of mkt values',        () => expect(r.valueArs).toBeCloseTo(155_000))
  it('invArs   = sum of ARS costs',         () => expect(r.invArs).toBeCloseTo(110_000))
  it('invested = sum of costs / tcBlue',    () => expect(r.invested).toBeCloseTo(110_000 / TCB))
  it('value    = sum / tcBlue',             () => expect(r.value).toBeCloseTo(155_000 / TCB))
  it('pnlArs   = total ARS gain',           () => expect(r.pnlArs).toBeCloseTo(45_000))
  it('pnlUsd   = pnlArs / tcBlue',          () => expect(r.pnlUsd).toBeCloseTo(45_000 / TCB))
})

// ─── isolation: only positions for this broker ───────────────────────────────

describe('Only positions belonging to the broker are included', () => {
  const positions = [
    pos({ broker: 'Binance', asset: 'BTC',  quantity: 1,  invested: 30_000 }),
    pos({ broker: 'Schwab',  asset: 'AAPL', quantity: 10, invested: 2_000 }),   // different broker
  ]
  const prices = { BTC: 35_000, AAPL: 300 }
  const r      = computeBrokerValue(positions, prices, usdBroker('Binance'), TCB)

  it('value excludes other brokers',    () => expect(r.value).toBeCloseTo(35_000))
  it('invested excludes other brokers', () => expect(r.invested).toBeCloseTo(30_000))
})

// ─── edge cases ──────────────────────────────────────────────────────────────

describe('Empty positions array', () => {
  const r = computeBrokerValue([], {}, usdBroker(), TCB)

  it('value    = 0', () => expect(r.value).toBe(0))
  it('invested = 0', () => expect(r.invested).toBe(0))
  it('pnlUsd   = 0', () => expect(r.pnlUsd).toBe(0))
  it('valueArs = 0', () => expect(r.valueArs).toBe(0))
  it('invArs   = 0', () => expect(r.invArs).toBe(0))
  it('pnlArs   = 0', () => expect(r.pnlArs).toBe(0))
})

describe('No positions for this broker (but other brokers have positions)', () => {
  const positions = [pos({ broker: 'OtherBroker', asset: 'BTC', quantity: 1, invested: 30_000 })]
  const r = computeBrokerValue(positions, { BTC: 35_000 }, usdBroker('Binance'), TCB)

  it('value    = 0', () => expect(r.value).toBe(0))
  it('invested = 0', () => expect(r.invested).toBe(0))
  it('pnlUsd   = 0', () => expect(r.pnlUsd).toBe(0))
})

describe('Position with null/undefined invested (defensive)', () => {
  const positions = [pos({ broker: 'Binance', asset: 'BTC', quantity: 1, invested: null })]
  const prices    = { BTC: 35_000 }
  const r         = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('treats null invested as 0', () => expect(r.invested).toBe(0))
  it('value still uses live price', () => expect(r.value).toBeCloseTo(35_000))
})

describe('Position with null/undefined quantity (defensive)', () => {
  const positions = [pos({ broker: 'Binance', asset: 'BTC', quantity: null, invested: 10_000 })]
  const prices    = { BTC: 35_000 }
  const r         = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('treats null quantity as 0 → value = 0', () => expect(r.value).toBe(0))
  it('invested is still counted',              () => expect(r.invested).toBeCloseTo(10_000))
  it('pnlUsd is negative (cost, no value)',    () => expect(r.pnlUsd).toBeCloseTo(-10_000))
})

describe('Equity with price = 0 (distinct from "no price")', () => {
  // price_override = 0 is a valid price (asset worth 0), not a missing price
  const positions = [pos({ broker: 'Binance', asset: 'LUNA', quantity: 1_000, invested: 5_000, price_override: 0 })]
  const prices    = {}
  const r         = computeBrokerValue(positions, prices, usdBroker(), TCB)

  // price_override is 0, which is != null → should be used (value = 0)
  it('price_override=0 is used (not treated as missing)', () => expect(r.value).toBe(0))
  it('pnlUsd = −invested',                                () => expect(r.pnlUsd).toBeCloseTo(-5_000))
})

// ─── MonthlySummary derived value contract ────────────────────────────────────

describe('MonthlySummary contract: pnlArs / tcBlue == pnlUsd (no FX phantom)', () => {
  // Post FX-phantom fix: ambos lados (value e invested) usan tcBlue actual,
  // así que pnlUsd y pnlArs/tcBlue son iguales. Esto simplifica la sincronía
  // entre el dashboard live y los snapshots mensuales.
  const positions = [pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 80_000, tc_compra: TC1 })]
  const prices    = { 'GGAL.BA': 12_000 }
  const r         = computeBrokerValue(positions, prices, arsBroker(), TCB)

  const storedValue = r.pnlArs / TCB

  it('stored value = pnlArs / tcBlue',           () => expect(storedValue).toBeCloseTo(40_000 / TCB, 4))
  it('stored value === pnlUsd (basis aligned)',  () => expect(storedValue).toBeCloseTo(r.pnlUsd, 4))
  it('pnlUsd refleja solo rendimiento del activo', () => expect(r.pnlUsd).toBeCloseTo(40_000 / TCB, 4))
})

// ─── Commissions integran cost basis ───────────────────────────────────────

describe('USD broker — commissions are part of cost basis', () => {
  const positions = [pos({ broker: 'Binance', asset: 'BTC', quantity: 1, invested: 1000, commissions: 5 })]
  const prices    = { BTC: 1100 }
  const r         = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('invested incluye comisiones (1000 + 5)', () => expect(r.invested).toBeCloseTo(1005))
  it('value = qty × price (sin tocar)',         () => expect(r.value).toBeCloseTo(1100))
  it('pnlUsd descuenta comisiones de compra',   () => expect(r.pnlUsd).toBeCloseTo(95))
})

describe('USD broker — commissions=0 mantiene comportamiento legacy', () => {
  const positions = [pos({ broker: 'Binance', asset: 'BTC', quantity: 1, invested: 1000 })]
  const prices    = { BTC: 1100 }
  const r         = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('sin commissions → cost basis = invested', () => expect(r.invested).toBeCloseTo(1000))
  it('pnlUsd = 100 (sin cambios)',               () => expect(r.pnlUsd).toBeCloseTo(100))
})

describe('ARS broker — commissions integran cost basis (en pesos)', () => {
  const positions = [pos({
    broker: 'Cocos', asset: 'GGAL', quantity: 100,
    invested: 100_000, commissions: 2_000, tc_compra: TC1,
  })]
  const prices = { 'GGAL.BA': 1200 }
  const r = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('invArs incluye comisiones',              () => expect(r.invArs).toBeCloseTo(102_000))
  it('invested USD = (invested+comm)/tcBlue',  () => expect(r.invested).toBeCloseTo(102_000 / TCB))
  it('valueArs no cambia',                     () => expect(r.valueArs).toBeCloseTo(120_000))
  it('pnlArs descuenta comisiones',            () => expect(r.pnlArs).toBeCloseTo(18_000))
})

describe('Cash positions ignoran commissions (no aplican)', () => {
  const positions = [pos({ broker: 'Binance', asset: 'USDT', quantity: 0, invested: 5_000, is_cash: true, commissions: 99 })]
  const prices    = {}
  const r         = computeBrokerValue(positions, prices, usdBroker(), TCB)

  it('cash value = invested',     () => expect(r.value).toBeCloseTo(5_000))
  it('cash invested = invested',  () => expect(r.invested).toBeCloseTo(5_000))
  it('cash pnl = 0',              () => expect(r.pnlUsd).toBeCloseTo(0))
})

// ─── Plazos fijos: computePf ──────────────────────────────────────────────────
describe('computePf — valuación de plazo fijo (al vencimiento)', () => {
  const base = { capital: 1_000_000, tasa: 0.30, fecha_inicio: '2026-06-02', plazo_dias: 125 }
  const pfTNA = { ...base, rate_type: 'TNA' }
  const pfTEA = { ...base, rate_type: 'TEA' }

  it('TNA 30% a 125 días → interés simple (10,27%)', () => {
    const r = computePf(pfTNA, '2026-06-02')   // día 0
    expect(r.tasaPeriodo).toBeCloseTo(0.30 * 125 / 365, 8)  // fórmula exacta
    expect(r.tasaPeriodo).toBeCloseTo(0.1027, 3)            // sanity
    expect(r.interes).toBeCloseTo(1_000_000 * r.tasaPeriodo, 2)
    expect(r.valorVencimiento).toBeCloseTo(1_000_000 + r.interes, 2)
    expect(r.teaEquiv).toBeCloseTo(0.3305, 2)               // 30% TNA = 33,05% TEA a 125d
    expect(r.tnaEquiv).toBeCloseTo(0.30, 6)
  })

  it('TEA 30% a 125 días → interés compuesto (9,40%)', () => {
    const r = computePf(pfTEA, '2026-06-02')
    expect(r.tasaPeriodo).toBeCloseTo(Math.pow(1.30, 125 / 365) - 1, 8)  // fórmula exacta
    expect(r.tasaPeriodo).toBeCloseTo(0.0940, 3)            // sanity
    expect(r.interes).toBeCloseTo(1_000_000 * r.tasaPeriodo, 2)
    expect(r.tnaEquiv).toBeCloseTo(0.2745, 2)               // 30% TEA = 27,45% TNA a 125d
    expect(r.teaEquiv).toBeCloseTo(0.30, 6)
  })

  it('TNA y TEA con el mismo número dan distinto (compuesta < simple en parcial)', () => {
    const tna = computePf(pfTNA, '2026-06-02')
    const tea = computePf(pfTEA, '2026-06-02')
    expect(tea.interes).toBeLessThan(tna.interes)
  })

  it('devenga lineal en TNA (mitad del plazo = mitad del interés)', () => {
    const pf = { capital: 1_000_000, tasa: 0.30, rate_type: 'TNA', fecha_inicio: '2026-06-02', plazo_dias: 30 }
    const full = computePf(pf, '2026-07-02')   // 30 días
    const half = computePf(pf, '2026-06-17')   // 15 días
    expect(half.diasTranscurridos).toBe(15)
    expect(half.diasRestantes).toBe(15)
    expect(half.devengadoHoy).toBeCloseTo(full.interes / 2, 4)
  })

  it('vencido → devengado = interés total + flag', () => {
    const r = computePf(pfTNA, '2026-12-31')
    expect(r.vencido).toBe(true)
    expect(r.diasTranscurridos).toBe(125)
    expect(r.devengadoHoy).toBeCloseTo(r.interes, 4)
    expect(r.valorHoy).toBeCloseTo(r.valorVencimiento, 4)
  })

  it('antes del inicio → sin devengado', () => {
    const r = computePf(pfTNA, '2026-05-01')
    expect(r.diasTranscurridos).toBe(0)
    expect(r.devengadoHoy).toBe(0)
    expect(r.valorHoy).toBe(1_000_000)
  })
})
