import { describe, it, expect } from 'vitest'
import { computeBrokerValue, computePf, priceSymbol, costInPesos, pesoLotUsd, trustMktValue, costInUsd, usdLotValue, isFciSym, holdingHasReliableFundamentals, costBasisRate, valueEquityLot, lotMissingPurchaseRate, avgCostUsdPerUnit, valuationPriceKey, setBrokersRegistry, isArUsdBroker, valuePositionLot, cashAssetLabel } from './valuation.js'
import { cedearEspecieBase } from './tickers.js'

describe('priceSymbol — clases de acción US (BRK B)', () => {
  it('normaliza espacio a guión (forma yfinance) para acción US', () => {
    expect(priceSymbol('BRK B', false)).toBe('BRK-B')      // Schwab/IBKR import
  })
  it('normaliza punto a guión para acción US', () => {
    expect(priceSymbol('BRK.B', false)).toBe('BRK-B')      // catálogo viejo
  })
  it('deja la forma canónica con guión intacta', () => {
    expect(priceSymbol('BRK-B', false)).toBe('BRK-B')
  })
  it('no toca un ticker US normal', () => {
    expect(priceSymbol('AAPL', false)).toBe('AAPL')
  })
  it('broker ARS sigue agregando .BA (sin normalizar el punto del sufijo)', () => {
    expect(priceSymbol('GGAL', true)).toBe('GGAL.BA')
  })
  it('CEDEAR va por .BA y no se normaliza como US', () => {
    expect(priceSymbol('MELI', false, 'CEDEAR')).toBe('MELI.BA')
  })
  it('acción argentina: .BA en contexto ARS (padre), ticker pelado en broker USD extranjero', () => {
    // Lo decide el PADRE (isARS), no el ticker (espejo de _byma en el backend).
    expect(priceSymbol('GGAL', true)).toBe('GGAL.BA')    // padre ARS / sub-broker AR·USD → BYMA
    expect(priceSymbol('YPFD', true)).toBe('YPFD.BA')    // idem
    expect(priceSymbol('GGAL', false)).toBe('GGAL')      // broker USD extranjero (Schwab) → ADR NYSE
    expect(priceSymbol('YPFD', false)).toBe('YPFD')      // sin .BA forzado (antes forzaba 'YPFD.BA')
  })
  it('FCI se pide tal cual', () => {
    expect(priceSymbol('FCI:COCOS-AHORRO-A', false)).toBe('FCI:COCOS-AHORRO-A')
  })
})

describe('holdingHasReliableFundamentals + alias de especie CEDEAR (SI/SID = CSN)', () => {
  const ARS = new Set(['Balanz', 'Cocos', 'IOL'])   // brokers ARS del usuario
  const h = (asset, broker, extra) => ({ asset, broker, currency: null, ...extra })

  it("CEDEAR 'SID' (Companhia Siderúrgica) en broker AR → analizable (ticker NYSE real)", () => {
    expect(holdingHasReliableFundamentals(h('SID', 'Balanz'), ARS)).toBe(true)
  })
  it("especie pesos 'SI' del mismo CEDEAR en broker AR → analizable vía alias a SID", () => {
    expect(holdingHasReliableFundamentals(h('SI', 'Balanz'), ARS)).toBe(true)
  })
  it("'SI' y 'SID' colapsan al MISMO canónico 'SID' (una empresa, no dos)", () => {
    expect(cedearEspecieBase('SI')).toBe('SID')
    expect(cedearEspecieBase('SID')).toBe('SID')
    expect(cedearEspecieBase('si')).toBe('SID')       // case-insensitive
  })
  it('el alias NO toca tickers reconocidos ni los que terminan en D', () => {
    expect(cedearEspecieBase('AAPL')).toBe('AAPL')
    expect(cedearEspecieBase('YPFD')).toBe('YPFD')    // no rompe la acción local de YPF
    expect(cedearEspecieBase('MELI.BA')).toBe('MELI') // strip .BA
  })
  it('acción argentina local no reconocida (TXAR) en broker AR → NO analizable', () => {
    expect(holdingHasReliableFundamentals(h('TXAR', 'Cocos'), ARS)).toBe(false)
  })
  it('CEDEAR reconocido (AAPL) en broker AR → SÍ analizable (símbolo = ticker US real)', () => {
    expect(holdingHasReliableFundamentals(h('AAPL', 'Cocos'), ARS)).toBe(true)
  })
  it("sub-broker dólar-MEP 'Cocos · USD': SID analizable", () => {
    expect(holdingHasReliableFundamentals(h('SID', 'Cocos · USD'), ARS)).toBe(true)
  })
  it('lote de costo en pesos (currency=ARS) aunque el broker no sea ARS → gatea como AR: SI→SID analizable', () => {
    expect(holdingHasReliableFundamentals(h('SI', 'OtroUSD', { currency: 'ARS' }), ARS)).toBe(true)
  })
  it('acción local no reconocida en sub-broker USD sigue sin analizarse', () => {
    expect(holdingHasReliableFundamentals(h('CEPU', 'Cocos · USD'), ARS)).toBe(false)
  })
  it('broker US real (Schwab): cualquier ticker US es analizable como está (SMCI no está en el allowlist)', () => {
    expect(holdingHasReliableFundamentals(h('SMCI', 'Schwab'), ARS)).toBe(true)
  })
  it("broker US real: 'SI' ahí ES Shoulder Innovations (el usuario la tiene de verdad); no se aliasea", () => {
    expect(holdingHasReliableFundamentals(h('SI', 'Schwab'), ARS)).toBe(true)
  })
})

// ─── helpers ────────────────────────────────────────────────────────────────

const TCB = 1200   // tcValuacion used throughout
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

describe('sub-broker AR·USD — acción argentina (YPFD) se valúa por .BA ÷ MEP', () => {
  // Sub-broker "· USD" (padre ARS): YPFD comprado por dólar-MEP sigue siendo BYMA →
  // .BA ÷ MEP, no el ticker US (que no existe para YPFD). isArUsdBroker lo reconoce
  // por el sufijo "· USD" (o por parent_broker_id si el registro está poblado).
  const positions = [pos({ broker: 'Cocos Capital · USD', asset: 'YPFD', quantity: 10, invested: 500 })]
  const prices    = { 'YPFD.BA': 72_000 }   // ARS · con TCB=1200 → 60 USD/acción → 600
  const r         = computeBrokerValue(positions, prices, usdBroker('Cocos Capital · USD'), TCB)

  it('value = YPFD.BA ÷ MEP × qty (no cae al costo)', () => expect(r.value).toBeCloseTo(600))
  it('NO se valúa como el ticker US "YPFD" (sin .BA)', () => {
    const rUsPrice = computeBrokerValue(positions, { YPFD: 45 }, usdBroker('Cocos Capital · USD'), TCB)
    expect(rUsPrice.value).toBeCloseTo(500)   // pide .BA → 'YPFD' pelado no matchea → costo
  })
})

describe('broker USD extranjero (Schwab) — ADR argentino (GGAL) usa el ADR NYSE, no .BA', () => {
  // Bug reportado: GGAL/BMA en Charles Schwab (broker USD extranjero, sin padre AR) son
  // el ADR NYSE en USD, NO la acción local .BA. Antes isArStock forzaba .BA → se preciaba
  // por el .BA local ÷ MEP (o "—" por key mismatch). El padre (no-AR) decide → ticker pelado.
  const positions = [pos({ broker: 'Charles Schwab', asset: 'GGAL', quantity: 100, invested: 4_000 })]

  it('value = precio ADR US × qty (usa el ticker pelado)', () => {
    const r = computeBrokerValue(positions, { GGAL: 50 }, usdBroker('Charles Schwab'), TCB)
    expect(r.value).toBeCloseTo(5_000)
  })
  it('NO usa el precio .BA local', () => {
    const r = computeBrokerValue(positions, { 'GGAL.BA': 7_000 }, usdBroker('Charles Schwab'), TCB)
    expect(r.value).toBeCloseTo(4_000)   // pide 'GGAL' pelado → 'GGAL.BA' no matchea → costo
  })
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
  it('value    = valueArs / tcValuacion',                    () => expect(r.value).toBeCloseTo(120_000 / TCB))
  it('invArs   = invested (native ARS)',                () => expect(r.invArs).toBeCloseTo(80_000))
  it('invested = invArs / tcValuacion (current rate, no FX phantom)', () => expect(r.invested).toBeCloseTo(80_000 / TCB))
  it('pnlArs   = valueArs − invArs',                    () => expect(r.pnlArs).toBeCloseTo(40_000))
  it('pnlUsd   = pnlArs / tcValuacion (asset return only)',  () => expect(r.pnlUsd).toBeCloseTo(40_000 / TCB))
})

describe('ARS broker — FX phantom eliminated', () => {
  // Documenta la corrección: para brokers ARS, value e invested se mueven
  // juntos con el blue, así que el P&L USD refleja SOLO el rendimiento del
  // activo. Si los pesos quedan quietos sin operar, no hay drift FX en USD.
  const positions = [pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 80_000, tc_compra: TC1 })]
  const prices    = { 'GGAL.BA': 12_000 }
  const r         = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('pnlUsd === pnlArs / tcValuacion (basis aligned)', () => {
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

describe('ARS broker — holdings Y cash al MEP (cedearRate)', () => {
  // Unificación FX: tanto las tenencias (CEDEARs/acciones AR) como el CASH en
  // pesos se valúan al dólar-MEP (cedearRate) — es el dólar al que dolarizás la
  // plata EN el broker. Antes el cash iba al blue (inconsistente con los holdings
  // y con el backend behavioral._position_value_usd, que ya usa MEP).
  const BLUE = 1530, MEP = 1499
  it('holding usa MEP, no blue', () => {
    const positions = [pos({ broker: 'Balanz', asset: 'GGAL', quantity: 100, invested: 140_000 })]
    const r = computeBrokerValue(positions, { 'GGAL.BA': 1500 }, arsBroker('Balanz'), BLUE, MEP)
    expect(r.value).toBeCloseTo(150_000 / MEP)       // 150.000 ARS / MEP
    expect(r.value).not.toBeCloseTo(150_000 / BLUE)  // NO al blue
    expect(r.invested).toBeCloseTo(140_000 / MEP)
  })
  it('cash también al MEP, no al blue', () => {
    const positions = [pos({ broker: 'Balanz', asset: 'ARS', is_cash: true, invested: 153_000 })]
    const r = computeBrokerValue(positions, {}, arsBroker('Balanz'), BLUE, MEP)
    expect(r.value).toBeCloseTo(153_000 / MEP)        // cash al MEP, igual que holdings
    expect(r.value).not.toBeCloseTo(153_000 / BLUE)   // NO al blue
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

describe('ARS broker — no live price, no tc_compra (uses tcValuacion)', () => {
  const positions = [pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 90_000, tc_compra: null })]
  const prices    = {}
  const r         = computeBrokerValue(positions, prices, arsBroker(), TCB)

  it('invested = invested / tcValuacion',               () => expect(r.invested).toBeCloseTo(90_000 / TCB))
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
  it('value    = invested / tcValuacion',          () => expect(r.value).toBeCloseTo(120_000 / TCB))
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
  it('value    = valueArs / tcValuacion-ish',    () => expect(r.value).toBeCloseTo(120_000 / TCB + 24_000 / TCB))
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
  it('invested = sum of costs / tcValuacion',    () => expect(r.invested).toBeCloseTo(110_000 / TCB))
  it('value    = sum / tcValuacion',             () => expect(r.value).toBeCloseTo(155_000 / TCB))
  it('pnlArs   = total ARS gain',           () => expect(r.pnlArs).toBeCloseTo(45_000))
  it('pnlUsd   = pnlArs / tcValuacion',          () => expect(r.pnlUsd).toBeCloseTo(45_000 / TCB))
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

describe('MonthlySummary contract: pnlArs / tcValuacion == pnlUsd (no FX phantom)', () => {
  // Post FX-phantom fix: ambos lados (value e invested) usan tcValuacion actual,
  // así que pnlUsd y pnlArs/tcValuacion son iguales. Esto simplifica la sincronía
  // entre el dashboard live y los snapshots mensuales.
  const positions = [pos({ broker: 'Cocos', asset: 'GGAL', quantity: 10, invested: 80_000, tc_compra: TC1 })]
  const prices    = { 'GGAL.BA': 12_000 }
  const r         = computeBrokerValue(positions, prices, arsBroker(), TCB)

  const storedValue = r.pnlArs / TCB

  it('stored value = pnlArs / tcValuacion',           () => expect(storedValue).toBeCloseTo(40_000 / TCB, 4))
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
  it('invested USD = (invested+comm)/tcValuacion',  () => expect(r.invested).toBeCloseTo(102_000 / TCB))
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

  it('capitalización periódica mensual: TNA 30% a 365d → TEA ≈ 34,49%', () => {
    const pf = { capital: 1_000_000, tasa: 0.30, rate_type: 'TNA', fecha_inicio: '2026-06-02', plazo_dias: 365, modalidad: 'periodico', pago_frecuencia_meses: 1 }
    const r = computePf(pf, '2027-06-02')   // a 365 días
    expect(r.tnaEquiv).toBeCloseTo(0.30, 3)            // nominal sigue 30%
    expect(r.teaEquiv).toBeCloseTo(0.3449, 3)          // efectiva compuesta mensual
    expect(r.valorVencimiento).toBeCloseTo(1_000_000 * Math.pow(1.025, 12), 0)
    // compuesto rinde más que simple "al vencimiento"
    const simple = computePf({ ...pf, modalidad: 'vencimiento' }, '2027-06-02')
    expect(r.interes).toBeGreaterThan(simple.interes)
  })
})

// ─── Premium dólar-cripto (broker vs exchange) ───────────────────────────────
// Mismos números que el backend test_crypto_premium.py → garantiza paridad FE/BE.
describe('crypto premium — broker (MEP) vs exchange (spot)', () => {
  const CRIPTO = 1554, MEP = 1499, BLUE = 1530, SPOT = 59281, QTY = 0.0114, COST = 700
  const PREMIUM = CRIPTO / MEP
  const cocos = { name: 'Cocos', currency: 'USDT', is_exchange: 0 }     // broker AR
  const binance = { name: 'Binance', currency: 'USDT', is_exchange: 1 } // exchange
  const btc = (broker, extra) => pos({ broker, asset: 'BTC', quantity: QTY, invested: COST, ...extra })

  it('cripto en un BROKER → spot × premium, valor Y costo (P&L% invariante)', () => {
    const r = computeBrokerValue([btc('Cocos')], { BTC: SPOT }, cocos, BLUE, MEP, CRIPTO)
    expect(r.value).toBeCloseTo(QTY * SPOT * PREMIUM, 2)
    expect(r.invested).toBeCloseTo(COST * PREMIUM, 2)
    expect((r.value - r.invested) / r.invested).toBeCloseTo((QTY * SPOT - COST) / COST, 5)
  })
  it('cripto en un EXCHANGE → spot (sin premium)', () => {
    const r = computeBrokerValue([btc('Binance')], { BTC: SPOT }, binance, BLUE, MEP, CRIPTO)
    expect(r.value).toBeCloseTo(QTY * SPOT, 2)
    expect(r.invested).toBeCloseTo(COST, 2)
  })
  it('sin tcCripto → spot (back-compat, comportamiento previo intacto)', () => {
    const r = computeBrokerValue([btc('Cocos')], { BTC: SPOT }, cocos, BLUE, MEP)
    expect(r.value).toBeCloseTo(QTY * SPOT, 2)
  })
  it('no-cripto en un broker → sin premium', () => {
    const aapl = pos({ broker: 'Cocos', asset: 'AAPL', quantity: 10, invested: 1500 })
    const r = computeBrokerValue([aapl], { AAPL: 150 }, cocos, BLUE, MEP, CRIPTO)
    expect(r.value).toBeCloseTo(1500, 2)
  })
  it('override en cripto → directo, sin premium', () => {
    const r = computeBrokerValue([btc('Cocos', { price_override: 60000 })], { BTC: SPOT }, cocos, BLUE, MEP, CRIPTO)
    expect(r.value).toBeCloseTo(QTY * 60000, 2)
  })
})

// ── Costo por moneda del LOTE, no de la cuenta (bug Christian: invertido inflado) ──
// Un CEDEAR/acción AR comprado en PESOS pero alojado en una cuenta USD (cargado en
// dólares o mal ruteado) tiene currency='ARS'. Su costo debe ir a USD por el MEP, no
// contarse como dólares. El valor ya usaba .BA ÷ MEP; el costo quedaba inflado ~MEP×.
describe('cuenta USD — lote en PESOS (currency=ARS) no se cuenta como dólares', () => {
  const BLUE = 1200, MEP = 1486
  const positions = [pos({ broker: 'MiUSD', asset: 'SPY', quantity: 1, invested: 48540, currency: 'ARS', asset_type: 'CEDEAR' })]
  const r = computeBrokerValue(positions, { 'SPY.BA': 48540 }, usdBroker('MiUSD'), BLUE, MEP)
  it('invested = costo ARS / MEP (NO el número de pesos como USD)', () => expect(r.invested).toBeCloseTo(48540 / MEP))
  it('value    = .BA / MEP',                                       () => expect(r.value).toBeCloseTo(48540 / MEP))
  it('pnlUsd   ≈ 0 (costo y valor al mismo MEP)',                  () => expect(r.pnlUsd).toBeCloseTo(0))
})

describe('cuenta USD — regresiones de moneda del lote', () => {
  const BLUE = 1200, MEP = 1486
  it('CEDEAR comprado en USD (currency=USD) NO se divide', () => {
    const r = computeBrokerValue([pos({ broker: 'MiUSD', asset: 'AAPL', quantity: 1, invested: 32, currency: 'USD', asset_type: 'CEDEAR' })],
      { 'AAPL.BA': 32 * MEP }, usdBroker('MiUSD'), BLUE, MEP)
    expect(r.invested).toBeCloseTo(32)
  })
  it('acción US genuina (currency=USD) queda en USD', () => {
    const r = computeBrokerValue([pos({ broker: 'IBKR', asset: 'NVDA', quantity: 2, invested: 1000, currency: 'USD' })],
      { NVDA: 600 }, usdBroker('IBKR'), BLUE, MEP)
    expect(r.invested).toBeCloseTo(1000)
    expect(r.value).toBeCloseTo(1200)
  })
  it('currency NULL en cuenta USD → comportamiento USD conservador (sin dividir)', () => {
    const r = computeBrokerValue([pos({ broker: 'MiUSD', asset: 'TSLA', quantity: 1, invested: 500, currency: null })],
      { TSLA: 500 }, usdBroker('MiUSD'), BLUE, MEP)
    expect(r.invested).toBeCloseTo(500)
  })
  it('lote en PESOS sin precio → valor cae al costo-USD (no a pesos crudos)', () => {
    const r = computeBrokerValue([pos({ broker: 'MiUSD', asset: 'SPY', quantity: 1, invested: 48540, currency: 'ARS', asset_type: 'CEDEAR' })],
      {}, usdBroker('MiUSD'), BLUE, MEP)
    expect(r.invested).toBeCloseTo(48540 / MEP)
    expect(r.value).toBeCloseTo(48540 / MEP)
  })
  it('lote en PESOS en cuenta ARS (rama ARS) sigue igual', () => {
    const r = computeBrokerValue([pos({ broker: 'Cocos', asset: 'SPY', quantity: 1, invested: 48540, currency: 'ARS', asset_type: 'CEDEAR' })],
      { 'SPY.BA': 48540 }, arsBroker('Cocos'), BLUE, MEP)
    expect(r.invested).toBeCloseTo(48540 / MEP)
  })
})

describe('costInPesos — moneda del costo por lote', () => {
  it("currency='ARS' → true",        () => expect(costInPesos({ currency: 'ARS' })).toBe(true))
  it("currency='USD' → false",       () => expect(costInPesos({ currency: 'USD' })).toBe(false))
  it('currency NULL → false (cons.)', () => expect(costInPesos({ currency: null })).toBe(false))
  it("cripto con currency='ARS' → false (cripto va a USD/spot, no por MEP)", () => expect(costInPesos({ currency: 'ARS', asset: 'BTC' })).toBe(false))
  it("CEDEAR con currency='ARS' → true", () => expect(costInPesos({ currency: 'ARS', asset: 'SPY' })).toBe(true))
})

describe('pesoLotUsd — lote en pesos → USD por MEP (helper compartido)', () => {
  const MEP = 1486
  const p = { asset: 'SPY', quantity: 1, invested: 48540, commissions: 0, currency: 'ARS', asset_type: 'CEDEAR' }
  it('con precio .BA: costo y valor ÷ MEP', () => {
    const u = pesoLotUsd(p, { 'SPY.BA': 50000 }, MEP)
    expect(u.investedUsd).toBeCloseTo(48540 / MEP)
    expect(u.valueUsd).toBeCloseTo(50000 / MEP)
    expect(u.priceUsd).toBeCloseTo(50000 / MEP)
  })
  it('sin precio: valor cae al costo-USD (P&L 0), no a pesos crudos', () => {
    const u = pesoLotUsd(p, {}, MEP)
    expect(u.investedUsd).toBeCloseTo(48540 / MEP)
    expect(u.valueUsd).toBeCloseTo(48540 / MEP)
    expect(u.priceUsd).toBe(null)
  })
  it('incluye comisiones en el costo', () => {
    const u = pesoLotUsd({ ...p, commissions: 1486 }, {}, MEP)
    expect(u.investedUsd).toBeCloseTo((48540 + 1486) / MEP)
  })
})

// ─── ESPEJO: lote de COSTO EN DÓLARES (currency='USD') en un broker ARS ───────
// Bug real (usuario Balanz): bonos/ONs/FCI-USD y CEDEARs comprados en dólar-MEP
// viven en el broker ARS con currency='USD'. El path ARS dividía TODO el costo por
// el MEP → el costo USD colapsaba (~1/MEP) y el guard descartaba el precio real →
// la tenencia dólar caía a ~u$s0. Fix = costInUsd/usdLotValue (espejo de costInPesos).
describe('costInUsd — moneda del costo por lote (espejo de costInPesos)', () => {
  it("currency='USD' → true",         () => expect(costInUsd({ currency: 'USD' })).toBe(true))
  it("currency='USDT' → true",        () => expect(costInUsd({ currency: 'USDT' })).toBe(true))
  it("currency='ARS' → false",        () => expect(costInUsd({ currency: 'ARS' })).toBe(false))
  it('currency NULL → false',         () => expect(costInUsd({ currency: null })).toBe(false))
  it("cripto con currency='USD' → false (va a spot, no por este camino)",
     () => expect(costInUsd({ currency: 'USD', asset: 'BTC' })).toBe(false))
})

describe('isFciSym', () => {
  it("'FCI:...' → true", () => expect(isFciSym('FCI:BALANZ-AHORRO-EN-DOLARES-A')).toBe(true))
  it("CEDEAR → false",   () => expect(isFciSym('MELI')).toBe(false))
})

describe('usdLotValue — bono/ON USD (priceado .BA en ARS) → costo USD, valor .BA÷MEP', () => {
  const MEP = 1500
  const p = { asset: 'RUCEO', asset_type: 'BOND', currency: 'USD', quantity: 100, invested: 100, commissions: 0 }
  it('costo USD SIN ÷MEP; valor = .BA×qty÷MEP', () => {
    const u = usdLotValue(p, { 'RUCEO.BA': 1650 }, MEP)   // .BA en ARS per-1
    expect(u.investedUsd).toBeCloseTo(100)                // costo YA en USD
    expect(u.valueUsd).toBeCloseTo(100 * 1650 / MEP)      // 110
  })
  it('sin precio → valor al costo-USD (P&L 0)', () => {
    const u = usdLotValue(p, {}, MEP)
    expect(u.valueUsd).toBeCloseTo(100)
  })
})

describe('usdLotValue — FCI-USD se valúa por su NAV USD (sin ÷MEP)', () => {
  const MEP = 1500
  const p = { asset: 'FCI:BALANZ-AHORRO-EN-DOLARES-A', asset_type: 'FUND', currency: 'USD', quantity: 1000, invested: 1400, commissions: 0 }
  it('valor = NAV × qty (USD directo)', () => {
    const u = usdLotValue(p, { 'FCI:BALANZ-AHORRO-EN-DOLARES-A': 1.42 }, MEP)
    expect(u.valueUsd).toBeCloseTo(1420)
    expect(u.investedUsd).toBeCloseTo(1400)
  })
})

describe('computeBrokerValue — broker ARS con tenencias de COSTO USD (bono/ON/FCI/CEDEAR-MEP)', () => {
  const MEP = 1500, BLUE = 1200
  const positions = [
    pos({ broker: 'Balanz', asset: 'RUCEO', asset_type: 'BOND', currency: 'USD', quantity: 100, invested: 100 }),
    pos({ broker: 'Balanz', asset: 'FCI:BALANZ-AHORRO-EN-DOLARES-A', asset_type: 'FUND', currency: 'USD', quantity: 1000, invested: 1400 }),
    pos({ broker: 'Balanz', asset: 'JPM', asset_type: 'CEDEAR', currency: 'USD', quantity: 73, invested: 1573 }),
    pos({ broker: 'Balanz', asset: 'MELI', asset_type: 'CEDEAR', currency: 'ARS', quantity: 10, invested: 30000 }),  // costo ARS: NO cambia
  ]
  const prices = { 'RUCEO.BA': 1650, 'FCI:BALANZ-AHORRO-EN-DOLARES-A': 1.42, 'JPM.BA': 33000, 'MELI.BA': 4500 }
  const r = computeBrokerValue(positions, prices, arsBroker('Balanz'), BLUE, MEP)

  const wantValue = (100 * 1650 / MEP) + 1420 + (73 * 33000 / MEP) + (10 * 4500 / MEP)
  const wantInv   = 100 + 1400 + 1573 + (30000 / MEP)   // USD-cost sin ÷MEP; ARS-cost ÷MEP
  it('value NO colapsa: suma cada clase bien',  () => expect(r.value).toBeCloseTo(wantValue))
  it('invested: costo USD sin ÷MEP, ARS ÷MEP',  () => expect(r.invested).toBeCloseTo(wantInv))
  it('invariante ARS: valueArs / MEP === value', () => expect(r.valueArs / MEP).toBeCloseTo(r.value))
})

// ─── Guard anti-distorsión sobre override de renta fija (caso SXC2O) ──────────
// Una ON sin precio live con un precio manual cargado en convención per-100 (97
// en vez de 0,97) inflaba el valor ×100 (+9775%). El guard ahora clampea el
// override de renta fija (un bono no puede valer ~100× su costo) y cae a costo.
describe('trustMktValue — guard sobre override de renta fija', () => {
  it('override per-100 en una ON (×100) NO se confía → cae a costo', () => {
    expect(trustMktValue(388000, 3900, 'ON', /*hasOverride*/ true)).toBe(false)
  })
  it('override razonable en una ON (~1×) SÍ se confía', () => {
    expect(trustMktValue(3920, 3900, 'ON', true)).toBe(true)
  })
  it('override en una ACCIÓN (no renta fija) siempre se respeta, aun ×100', () => {
    expect(trustMktValue(388000, 3900, 'STOCK', true)).toBe(true)
  })
  it('sin override, renta fija ×100 → no se confía (banda [0.02,4])', () => {
    expect(trustMktValue(388000, 3900, 'BOND', false)).toBe(false)
  })
  it('sin costo no hay con qué comparar → se confía', () => {
    expect(trustMktValue(388000, 0, 'ON', true)).toBe(true)
  })
})

describe('computeBrokerValue — ON con override per-100 cae a costo (no infla la cartera)', () => {
  const balanz = { name: 'Balanz', currency: 'USDT' }
  const sxc2o = {
    broker: 'Balanz', asset: 'SXC2O', asset_type: 'ON', quantity: 4000,
    invested: 3900, commissions: 0, is_cash: false, tc_compra: null,
    price_override: 97,   // ← per-100 (debería ser 0,97)
  }
  const r = computeBrokerValue([sxc2o], {}, balanz, 1200)
  it('el valor no se va a ~$388k: cae a costo', () => {
    expect(r.value).toBeCloseTo(3900, 2)
  })
})

// ─── Modo costBasis: 'purchase' (dólar de compra, DEFAULT) vs 'today' (FX-neutral) ──
describe('costBasisRate — chokepoint del divisor del costo', () => {
  it("today → siempre el rate actual (aunque haya tc_compra)", () => {
    expect(costBasisRate(pos({ tc_compra: TC1 }), TCB, 'today')).toBe(TCB)
  })
  it("purchase con tc_compra>0 → el tc de la compra", () => {
    expect(costBasisRate(pos({ tc_compra: TC1 }), TCB, 'purchase')).toBe(TC1)
  })
  it("purchase sin tc_compra (NULL) → fallback al rate de hoy (no-breaking)", () => {
    expect(costBasisRate(pos({ tc_compra: null }), TCB, 'purchase')).toBe(TCB)
    expect(costBasisRate(pos({ tc_compra: 0 }), TCB, 'purchase')).toBe(TCB)
  })
  it("default (sin 3er arg) = purchase, igual que el contexto", () => {
    // Cuando este default era 'today' y el del contexto era otro, cualquier
    // caller que se olvidara del 3er argumento volvía al dólar de hoy en
    // silencio — el mismo bug, pero sin nada en pantalla que lo delatara.
    expect(costBasisRate(pos({ tc_compra: TC1 }), TCB)).toBe(TC1)
  })

  it("el caso REAL que reportó el usuario: ALUA 880 pesos, tc_compra 1048", () => {
    // Compra del 7/5/24 a 880 ARS. Con el default viejo la app mostraba
    // 880/1517 = 0,58 (el MEP de HOY) mientras la columna de al lado imprimía
    // 1048. Con el default nuevo da 0,84, que es lo que el usuario calcula.
    const MEP_HOY = 1517
    const alua = pos({ tc_compra: 1048 })
    expect(880 / costBasisRate(alua, MEP_HOY)).toBeCloseTo(0.84, 2)
    expect(880 / costBasisRate(alua, MEP_HOY, 'today')).toBeCloseTo(0.58, 2)
  })
})

describe('pesoLotUsd — modo purchase cambia el COSTO, no el valor', () => {
  const p = { ...pos({ asset: 'AMZN', asset_type: 'CEDEAR', currency: 'ARS',
                        invested: 100_000, quantity: 40, tc_compra: TC1 }) }
  const prices = { 'AMZN.BA': 3000 }
  const today  = pesoLotUsd(p, prices, TCB, 'today')
  const purch  = pesoLotUsd(p, prices, TCB, 'purchase')
  it('today: invested = 100.000/TCB', () => expect(today.investedUsd).toBeCloseTo(100_000 / TCB))
  it('purchase: invested = 100.000/TC1 (dólares reales)', () => expect(purch.investedUsd).toBeCloseTo(100_000 / TC1))
  it('el VALOR es idéntico en ambos modos (siempre a hoy)', () => expect(purch.valueUsd).toBeCloseTo(today.valueUsd))
  it('→ el P&L USD cambia entre modos', () => {
    const pnlToday = today.valueUsd - today.investedUsd
    const pnlPurch = purch.valueUsd - purch.investedUsd
    expect(pnlPurch).not.toBeCloseTo(pnlToday)
  })
})

describe('computeBrokerValue — modo purchase sobre lote ARS con tc_compra', () => {
  const p = pos({ broker: 'Cocos', asset: 'GGAL', currency: 'ARS',
                  invested: 90_000, quantity: 10, tc_compra: TC1 })
  const prices = { 'GGAL.BA': 12_000 }
  const today  = computeBrokerValue([p], prices, arsBroker(), TCB, TCB, null, 'today')
  const purch  = computeBrokerValue([p], prices, arsBroker(), TCB, TCB, null, 'purchase')
  it('today: invested USD = 90.000/TCB', () => expect(today.invested).toBeCloseTo(90_000 / TCB))
  it('purchase: invested USD = 90.000/TC1', () => expect(purch.invested).toBeCloseTo(90_000 / TC1))
  it('el valor USD NO cambia', () => expect(purch.value).toBeCloseTo(today.value))
  it('el invertido en ARS NO cambia (moneda base)', () => expect(purch.invArs).toBeCloseTo(today.invArs))
})

describe('fallback NULL — purchase sin tc_compra == today (no-breaking)', () => {
  const p = pos({ broker: 'Cocos', asset: 'GGAL', currency: 'ARS',
                  invested: 90_000, quantity: 10, tc_compra: null })
  const prices = { 'GGAL.BA': 12_000 }
  const today  = computeBrokerValue([p], prices, arsBroker(), TCB, TCB, null, 'today')
  const purch  = computeBrokerValue([p], prices, arsBroker(), TCB, TCB, null, 'purchase')
  it('invested USD idéntico (cae a hoy)', () => expect(purch.invested).toBeCloseTo(today.invested))
})

describe('valueEquityLot — modo purchase (rama costInPesos y rama isAR)', () => {
  const cedearUsdAcct = pos({ broker: 'Bal · USD', asset: 'AMZN', asset_type: 'CEDEAR',
                              currency: 'ARS', invested: 100_000, quantity: 40, tc_compra: TC1 })
  it('rama costInPesos !isAR: purchase usa tc_compra', () => {
    const t = valueEquityLot(cedearUsdAcct, usdBroker('Bal · USD'), { 'AMZN.BA': 3000 }, TCB, TCB, 'today')
    const p = valueEquityLot(cedearUsdAcct, usdBroker('Bal · USD'), { 'AMZN.BA': 3000 }, TCB, TCB, 'purchase')
    expect(p.investedUsd).toBeCloseTo(100_000 / TC1)
    expect(t.investedUsd).toBeCloseTo(100_000 / TCB)
    expect(p.valueUsd).toBeCloseTo(t.valueUsd)
  })
  const arsLot = pos({ broker: 'Cocos', asset: 'GGAL', currency: 'ARS',
                       invested: 90_000, quantity: 10, tc_compra: TC1 })
  it('rama isAR: purchase usa tc_compra', () => {
    const p = valueEquityLot(arsLot, arsBroker(), { 'GGAL.BA': 12_000 }, TCB, TCB, 'purchase')
    expect(p.investedUsd).toBeCloseTo(90_000 / TC1)
  })
})

describe('valueEquityLot — el guard NO se afloja en purchase (bono per-100, tc_compra viejo)', () => {
  // Bono en broker ARS con tc_compra MUY viejo (30) vs hoy (TCB=1000). Un precio en
  // convención per-100 infla el valor ~×120. El guard debe RECHAZARLO en AMBOS modos:
  // usa el costo de HOY como denominador, no el ruteado (que en purchase lo aflojaría
  // de mult 120 → 3,6 y dejaría pasar el precio basura → +8.667 USD fantasma).
  const bond = pos({ broker: 'Cocos', asset: 'ON123', asset_type: 'ON', currency: 'ARS',
                     invested: 100_000, quantity: 100, tc_compra: 30 })
  const prices = { 'ON123.BA': 120_000 }
  const t = valueEquityLot(bond, arsBroker(), prices, TCB, TCB, 'today')
  const p = valueEquityLot(bond, arsBroker(), prices, TCB, TCB, 'purchase')
  it('today: guard rechaza → valor = costo, P&L 0', () => {
    expect(t.valueUsd).toBeCloseTo(t.investedUsd)
    expect(t.pnlUsd).toBeCloseTo(0)
  })
  it('purchase: guard TAMBIÉN rechaza (no afloja por tc_compra) → P&L 0', () => {
    expect(p.valueUsd).toBeCloseTo(p.investedUsd)
    expect(p.pnlUsd).toBeCloseTo(0)
  })
  // CAMBIO DE CONTRATO (parte II): cuando el guard RECHAZA el precio, el costo
  // display ya NO se queda en el tc_compra. Antes esta aserción pedía 100.000/30
  // = 3.333 USD como valor de una posición cuyo costo a hoy son 100 USD: un ×33
  // fantasma en el hero, publicado como valor de MERCADO de algo que no cotiza.
  // El modo 'purchase' no aplica sobre algo que no cotiza. Lo que este describe
  // protege — que el guard NO se afloje por tc_compra — sigue intacto: es lo que
  // asertan los dos `it` de arriba, y el denominador del guard sigue siendo el
  // costo de HOY.
  it('sin precio confiable el costo display cae al dólar de HOY, en los dos modos', () => {
    expect(p.investedUsd).toBeCloseTo(100_000 / TCB)
    expect(t.investedUsd).toBeCloseTo(100_000 / TCB)
    expect(p.investedUsd).toBeCloseTo(t.investedUsd)   // el modo deja de importar
  })
})

describe('valueEquityLot / computeBrokerValue — sin precio: P&L 0 en ambos modos', () => {
  const lot = pos({ broker: 'Cocos', asset: 'ZZZ', currency: 'ARS',
                    invested: 90_000, quantity: 10, tc_compra: TC1 })
  const noPrices = {}
  it('valueEquityLot: pnl 0 en today y en purchase (fila sin cotización)', () => {
    const t = valueEquityLot(lot, arsBroker(), noPrices, TCB, TCB, 'today')
    const p = valueEquityLot(lot, arsBroker(), noPrices, TCB, TCB, 'purchase')
    expect(t.pnlUsd).toBeCloseTo(0)
    expect(p.pnlUsd).toBeCloseTo(0)
  })
  it('computeBrokerValue: sin precio, pnlUsd y pnlArs 0 en purchase', () => {
    const r = computeBrokerValue([lot], noPrices, arsBroker(), TCB, TCB, null, 'purchase')
    expect(r.pnlUsd).toBeCloseTo(0)
    expect(r.pnlArs).toBeCloseTo(0)
  })
})

describe('lotMissingPurchaseRate — badge TC? (purchase + lote de costo peso sin tc_compra)', () => {
  const pesoNoTc   = pos({ asset: 'GGAL', currency: 'ARS', invested: 1000, tc_compra: null })
  const pesoWithTc = pos({ asset: 'GGAL', currency: 'ARS', invested: 1000, tc_compra: TC1 })
  const usdLot     = pos({ asset: 'AAPL', currency: 'USD', invested: 1000, tc_compra: null })
  const cash       = pos({ asset: 'ARS',  currency: 'ARS', is_cash: true, tc_compra: null })
  const nullCcy    = pos({ asset: 'AAPL', currency: null,  invested: 1000, tc_compra: null })
  it('today → nunca marca', () => expect(lotMissingPurchaseRate(pesoNoTc, 'today')).toBe(false))
  it('purchase + peso sin tc → marca', () => expect(lotMissingPurchaseRate(pesoNoTc, 'purchase')).toBe(true))
  it('purchase + peso CON tc → no marca', () => expect(lotMissingPurchaseRate(pesoWithTc, 'purchase')).toBe(false))
  it('purchase + lote USD → no marca (el modo no aplica al costo en USD)', () => expect(lotMissingPurchaseRate(usdLot, 'purchase')).toBe(false))
  it('purchase + cash → no marca', () => expect(lotMissingPurchaseRate(cash, 'purchase')).toBe(false))
  // Broker-aware: un lote de moneda sin marcar NO se rutea en un broker USD (cae a
  // USD-nativo) → no marca; pero en un broker ARS SÍ se rutea (path nativo) → marca.
  it('purchase + moneda-null en broker USD → no marca (no se rutea)', () => expect(lotMissingPurchaseRate(nullCcy, 'purchase', false)).toBe(false))
  it('purchase + moneda-null en broker ARS → marca (path nativo ruteado)', () => expect(lotMissingPurchaseRate(nullCcy, 'purchase', true)).toBe(true))
  it('purchase + lote USD en broker ARS → no marca (costo ya en USD)', () => expect(lotMissingPurchaseRate(usdLot, 'purchase', true)).toBe(false))
})

describe('computeBrokerValue — valueArs/invArs son 0 para brokers USD (trampa del hero ARS)', () => {
  // Documenta por qué el hero en display ARS se calcula con Σvalue×tcValuacion (totalsToday),
  // NO con Σ r.valueArs: un broker USD acumula value/invested pero deja valueArs/invArs
  // en 0 → sumar invArs dropearía toda la tenencia en dólares (fue un BLOCKER real).
  const usdPos = pos({ broker: 'Schwab', asset: 'AAPL', currency: 'USD', quantity: 10, invested: 2000 })
  const r = computeBrokerValue([usdPos], { AAPL: 250 }, usdBroker('Schwab'), TCB, TCB, null, 'today')
  it('value/invested en USD pero valueArs/invArs quedan en 0', () => {
    expect(r.value).toBeCloseTo(2500)
    expect(r.invested).toBeCloseTo(2000)
    expect(r.valueArs).toBe(0)
    expect(r.invArs).toBe(0)
  })
})

describe('computeBrokerValue — agregado DCA multi-lote: invertido USD purchase suma POR LOTE', () => {
  // Dos compras de GGAL a distinto tc_compra. El invertido USD en purchase debe ser
  // Σ(invested_i / tc_i), independiente del orden — NO Σinvested / tc del primer lote.
  // computeBrokerValue itera por-lote (es la referencia de reconciliación del subtotal).
  const lotA = pos({ broker: 'Cocos', asset: 'GGAL', currency: 'ARS', quantity: 10, invested: 100_000, tc_compra: 200 })
  const lotB = pos({ broker: 'Cocos', asset: 'GGAL', currency: 'ARS', quantity: 10, invested: 100_000, tc_compra: 1000 })
  const prices = { 'GGAL.BA': 12_000 }
  const expected = 100_000 / 200 + 100_000 / 1000   // 500 + 100 = 600 USD
  it('invertido USD purchase = Σ(inv_i/tc_i), no depende del orden', () => {
    const r1 = computeBrokerValue([lotA, lotB], prices, arsBroker(), TCB, TCB, null, 'purchase')
    const r2 = computeBrokerValue([lotB, lotA], prices, arsBroker(), TCB, TCB, null, 'purchase')
    expect(r1.invested).toBeCloseTo(expected)
    expect(r2.invested).toBeCloseTo(expected)
  })
})

// ─── avgCostUsdPerUnit — el "Precio prom." en dólares ────────────────────────
// Bug real (2026-07-30): la celda dividía el costo en pesos por el dólar de HOY,
// ignorando el tc_compra del lote y el toggle "Costo en dólares". El usuario
// cargó TC 1448,6 y veía 14,23 (dólar de hoy 1523,07) en vez de 14,96.
describe('avgCostUsdPerUnit', () => {
  const HOY = 1523.07
  const meli = { asset: 'MELI', quantity: 10, invested: 216732.82, commissions: 1432.83, tc_compra: 1448.6, currency: 'ARS' }

  it('caso del usuario: purchase usa SU tc_compra, today usa el dólar de hoy', () => {
    expect(avgCostUsdPerUnit(meli, HOY, 'purchase', true)).toBeCloseTo(14.96, 2)
    expect(avgCostUsdPerUnit(meli, HOY, 'today', true)).toBeCloseTo(14.23, 2)
  })

  it("modo 'today' es byte-idéntico al cálculo viejo (invested/qty/rate)", () => {
    const viejo = meli.invested / meli.quantity / HOY
    expect(avgCostUsdPerUnit(meli, HOY, 'today', true)).toBe(viejo)
    // …y sin tc_compra, 'purchase' cae al dólar de hoy igual que antes.
    const sinTc = { ...meli, tc_compra: null }
    expect(avgCostUsdPerUnit(sinTc, HOY, 'purchase', true)).toBe(viejo)
  })

  it('multi-lote: promedio ponderado e independiente del orden', () => {
    const a = { asset: 'MELI', quantity: 10, invested: 120000, tc_compra: 1200, currency: 'ARS' }
    const b = { asset: 'MELI', quantity: 5, invested: 75000, tc_compra: 1500, currency: 'ARS' }
    const agg = (lots) => ({ asset: 'MELI', quantity: 15, invested: 195000, tc_compra: lots[0].tc_compra, currency: 'ARS', _lots: lots })
    // (120000/1200 + 75000/1500) / 15 = (100 + 50) / 15 = 10
    const esperado = 10
    expect(avgCostUsdPerUnit(agg([a, b]), HOY, 'purchase', true)).toBeCloseTo(esperado, 6)
    expect(avgCostUsdPerUnit(agg([b, a]), HOY, 'purchase', true)).toBeCloseTo(esperado, 6)
    // El tc_compra del agregado (el del PRIMER lote) daría 195000/1200/15 = 10.83
    // o 195000/1500/15 = 8.67 según el orden — justamente lo que NO debe pasar.
    expect(avgCostUsdPerUnit(agg([a, b]), HOY, 'purchase', true))
      .toBeCloseTo(avgCostUsdPerUnit(agg([b, a]), HOY, 'purchase', true), 10)
  })

  it('lote de costo EN DÓLARES dentro de un broker ARS no se divide', () => {
    // CEDEAR comprado a dólar-MEP: invested ya está en USD (currency USD).
    const usdLot = { asset: 'AAPL', quantity: 10, invested: 140, currency: 'USD', asset_type: 'CEDEAR' }
    expect(avgCostUsdPerUnit(usdLot, HOY, 'today', true)).toBeCloseTo(14, 6)
    // Antes daba 140/10/1523 = 0,0092 (colapsado ~1500×).
    expect(avgCostUsdPerUnit(usdLot, HOY, 'today', true)).toBeGreaterThan(1)
  })

  it('cash, sin cantidad o sin costo → null', () => {
    expect(avgCostUsdPerUnit({ is_cash: true, quantity: 0, invested: 100 }, HOY, 'today', true)).toBe(null)
    expect(avgCostUsdPerUnit({ quantity: 0, invested: 100 }, HOY, 'today', true)).toBe(null)
    expect(avgCostUsdPerUnit({ quantity: 10, invested: 0 }, HOY, 'today', true)).toBe(null)
  })

  it('INVARIANTE: promedio × cantidad === costo ruteado (sin comisiones)', () => {
    for (const modo of ['today', 'purchase']) {
      const prom = avgCostUsdPerUnit(meli, HOY, modo, true)
      const rate = modo === 'purchase' ? meli.tc_compra : HOY
      expect(prom * meli.quantity).toBeCloseTo(meli.invested / rate, 6)
    }
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Los bugs de SÍMBOLO: pedir una key y leer otra.
// Toda esta familia falla igual — la posición cae a costo EN SILENCIO y el P&L
// queda en 0 para siempre, sin nada en pantalla que lo delate. Estos tests fijan
// el mecanismo; los call-sites que lo sufrían (PositionDetailMobile, AssetDetail,
// Insights, FirstInsight) viven en pages/ y no se pueden importar acá (el
// entorno de tests es node, sin jsdom), así que se pinea lo que SÍ es puro:
// la key canónica y el ruteo que depende del registry.
// ════════════════════════════════════════════════════════════════════════════

describe('key de precio: la que se pide tiene que ser la que se lee', () => {
  it('un class-share con punto se lee por la key normalizada, no por la cruda', () => {
    // El fetch pide 'BRK-B' (priceSymbol normaliza). Leer prices['BRK.B'] deja el
    // lote al costo. computeBrokerValue lee normalizada primero.
    expect(priceSymbol('BRK.B', false)).toBe('BRK-B')
    const p = { asset: 'BRK.B', quantity: 10, invested: 1000, is_cash: false, broker: 'Schwab', currency: 'USD' }
    const broker = { name: 'Schwab', currency: 'USD' }
    setBrokersRegistry([broker])
    const r = computeBrokerValue([p], { 'BRK-B': 500 }, broker, 1466, 1412, null, 'today')
    expect(r.value).toBeCloseTo(5000, 6)   // no 1000 (el costo)
  })

  it('valuationPriceKey saca la MISMA key que la valuación lee, rama por rama', () => {
    const reg = [
      { id: 1, name: 'Balanz', currency: 'ARS' },
      { id: 2, name: 'Mi cuenta dólar', currency: 'USD', parent_broker_id: 1 },  // sub-broker AR renombrado
      { id: 3, name: 'Schwab', currency: 'USD' },
    ]
    setBrokersRegistry(reg)
    // broker ARS → .BA
    expect(valuationPriceKey({ asset: 'GGAL', broker: 'Balanz' }, true)).toBe('GGAL.BA')
    // sub-broker AR (por REGISTRY, no por nombre) → .BA
    expect(valuationPriceKey({ asset: 'YPFD', broker: 'Mi cuenta dólar' }, false)).toBe('YPFD.BA')
    // cripto en ese mismo sub-broker → spot, NUNCA .BA
    expect(valuationPriceKey({ asset: 'BTC', broker: 'Mi cuenta dólar' }, false)).toBe('BTC')
    // broker USD real → ticker US normalizado
    expect(valuationPriceKey({ asset: 'BRK.B', broker: 'Schwab' }, false)).toBe('BRK-B')
    // lote en pesos alojado en cuenta USD → .BA
    expect(valuationPriceKey({ asset: 'AL30', broker: 'Schwab', currency: 'ARS' }, false)).toBe('AL30.BA')
    // cash no tiene precio
    expect(valuationPriceKey({ asset: 'ARS', broker: 'Balanz', is_cash: true }, true)).toBeNull()
  })
})

describe('setBrokersRegistry: sin él, un sub-broker renombrado se rutea mal', () => {
  const sub = { id: 2, name: 'Mi cuenta dólar', currency: 'USD', parent_broker_id: 1 }
  const reg = [{ id: 1, name: 'Balanz', currency: 'ARS' }, sub]
  // Acción argentina SIN ADR: con el ruteo correcto va por su .BA ÷ MEP.
  const ypfd = { asset: 'YPFD', quantity: 100, invested: 1000, is_cash: false, broker: sub.name, currency: 'USD' }

  it('con el registry VACÍO cae al fallback por nombre y no reconoce el sub-broker', () => {
    setBrokersRegistry([])
    expect(isArUsdBroker('Mi cuenta dólar')).toBe(false)          // no matchea /· USD$/
    // Se rutea al ticker US pelado: YPFD no cotiza en US → sin precio → al costo.
    expect(valuationPriceKey(ypfd, false)).toBe('YPFD')
    const r = computeBrokerValue([ypfd], { 'YPFD.BA': 5000 }, sub, 1466, 1412, null, 'today')
    expect(r.value).toBeCloseTo(1000, 6)                          // congelado al costo
    expect(r.pnlUsd).toBeCloseTo(0, 6)                            // P&L 0 para siempre
  })

  it('con el registry POBLADO lo reconoce por parent_broker_id y lee el .BA', () => {
    setBrokersRegistry(reg)
    expect(isArUsdBroker('Mi cuenta dólar')).toBe(true)
    expect(valuationPriceKey(ypfd, false)).toBe('YPFD.BA')
    const r = computeBrokerValue([ypfd], { 'YPFD.BA': 5000 }, sub, 1466, 1412, null, 'today')
    expect(r.value).toBeCloseTo(100 * 5000 / 1412, 6)             // .BA ÷ MEP
  })

  it('el nombre "X · USD" funciona sin registry — por eso el bug pasa desapercibido', () => {
    // Es el caso de la cartera real: mientras nadie renombre, el fallback acierta.
    setBrokersRegistry([])
    expect(isArUsdBroker('Balanz · USD')).toBe(true)
    expect(isArUsdBroker('Balanz - USD')).toBe(false)   // guión: NO
    expect(isArUsdBroker('Balanz USD')).toBe(false)     // sin punto medio: NO
  })
})

describe('valueEquityLot: las comisiones integran el costo, como en el resto de la casa', () => {
  const brokerUsd = { name: 'Schwab', currency: 'USD' }
  const brokerArs = { name: 'Balanz', currency: 'ARS' }

  it('broker USD: el costo suma la comisión y el P&L la descuenta', () => {
    const p = { asset: 'AAPL', quantity: 10, invested: 1000, commissions: 5, currency: 'USD' }
    const r = valueEquityLot(p, brokerUsd, { AAPL: 110 }, 1466, 1412, 'today')
    expect(r.investedUsd).toBeCloseTo(1005, 6)
    expect(r.valueUsd).toBeCloseTo(1100, 6)     // el valor NO se toca
    expect(r.pnlUsd).toBeCloseTo(95, 6)         // no 100
  })

  it('broker ARS: idem, dividido por el dólar', () => {
    const p = { asset: 'GGAL', quantity: 100, invested: 100_000, commissions: 2_000, currency: 'ARS' }
    const r = valueEquityLot(p, brokerArs, { 'GGAL.BA': 1200 }, 1200, 1200, 'today')
    expect(r.investedUsd).toBeCloseTo(102_000 / 1200, 6)
    expect(r.pnlUsd).toBeCloseTo(120_000 / 1200 - 102_000 / 1200, 6)
  })

  it('sin commissions se comporta igual que antes (no-breaking)', () => {
    const p = { asset: 'AAPL', quantity: 10, invested: 1000, currency: 'USD' }
    const r = valueEquityLot(p, brokerUsd, { AAPL: 110 }, 1466, 1412, 'today')
    expect(r.investedUsd).toBeCloseTo(1000, 6)
    expect(r.pnlUsd).toBeCloseTo(100, 6)
  })

  it('ya no se contradice a sí misma: la rama costInUsd y las demás cuentan igual', () => {
    // La rama costInUsd delega en usdLotValue, que SIEMPRE sumó comisiones. Antes
    // las otras cuatro no → el mismo lote valía distinto según por dónde entraba.
    const enUsd = { asset: 'AL30', quantity: 100, invested: 1000, commissions: 7, currency: 'USD', asset_type: 'BOND' }
    const rUsd = valueEquityLot(enUsd, brokerArs, {}, 1466, 1412, 'today')
    const enUsdBrokerUsd = { ...enUsd, currency: 'USD' }
    const rOtra = valueEquityLot(enUsdBrokerUsd, brokerUsd, {}, 1466, 1412, 'today')
    expect(rUsd.investedUsd).toBeCloseTo(1007, 6)
    expect(rOtra.investedUsd).toBeCloseTo(1007, 6)   // antes daba 1000
  })
})

// ════════════════════════════════════════════════════════════════════════════
// Modo 'purchase' SIN precio confiable: el valor va al dólar de HOY.
// El bug: `pesoLotUsd` tenía un comentario que decía "el VALOR siempre va a HOY
// en ambos modos" y la línea de abajo hacía lo contrario — publicaba
// costo/tc_compra como valor de MERCADO. Misma fuga en valueEquityLot y en
// valuePositionLot. 'purchase' es el DEFAULT del contexto, así que pegaba solo.
// ════════════════════════════════════════════════════════════════════════════
describe("purchase sin precio: el valor y el costo-display van al dólar de HOY", () => {
  const HOY = 1500, COMPRA = 1000
  const brokerArs = { name: 'Cocos', currency: 'ARS' }
  // El ejemplo del brief: 1.500.000 con tc_compra 1000 y dólar de hoy 1500.
  const lote = { broker: 'Cocos', asset: 'ZZZ', currency: 'ARS', is_cash: false,
                 invested: 1_500_000, quantity: 10, tc_compra: COMPRA }
  const ctx = (costBasis, prices = {}) => ({
    broker: brokerArs, prices, tcValuacion: HOY, tcCedear: HOY, tcCripto: null, costBasis,
  })

  it('CONTROL: con tc_compra el escenario mueve algo — si no, el resto no prueba nada', () => {
    // Obligatorio. Sin este control, "probé los dos modos" es falso: si el lote no
    // tuviera tc_compra, costBasisRate cae al rate de hoy y los dos modos coinciden.
    const conPrecio = { 'ZZZ.BA': 200_000 }
    const hoy = valuePositionLot(lote, ctx('today', conPrecio))
    const compra = valuePositionLot(lote, ctx('purchase', conPrecio))
    expect(compra.investedUsd).not.toBeCloseTo(hoy.investedUsd)
    expect(compra.investedUsd).toBeCloseTo(1_500_000 / COMPRA)   // 1500
    expect(hoy.investedUsd).toBeCloseTo(1_500_000 / HOY)         // 1000
  })

  it('sin precio: valor y costo al dólar de HOY, y P&L exactamente 0', () => {
    const r = valuePositionLot(lote, ctx('purchase'))
    expect(r.valueUsd).toBeCloseTo(1_000, 6)              // no 1.500 (costo/tc_compra)
    expect(r.investedUsdDisplay).toBeCloseTo(1_000, 6)
    expect(r.guardCost).toBeCloseTo(1_500_000, 6)         // el guard compara en PESOS
    expect(r.pnlUsd).toBeCloseTo(0, 9)
  })

  it('con un precio que el GUARD rechaza, lo mismo (bono per-100)', () => {
    const bono = { ...lote, asset: 'AL30', asset_type: 'BOND', quantity: 100 }
    // per-100 leído per-1: infla ×100 → trustMktValue lo rechaza (renta fija, [0.02×, 4×])
    const r = valuePositionLot(bono, ctx('purchase', { 'AL30.BA': 150_000 }))
    expect(r.priceTrusted).toBe(false)
    expect(r.valueUsd).toBeCloseTo(1_000, 6)
    expect(r.pnlUsd).toBeCloseTo(0, 9)
  })

  it("en modo 'today' no cambia nada: los dos caminos ya eran idénticos", () => {
    const r = valuePositionLot(lote, ctx('today'))
    expect(r.valueUsd).toBeCloseTo(1_000, 6)
    expect(r.pnlUsd).toBeCloseTo(0, 9)
  })

  it('el hero lo hereda: computeBrokerValue suma el valor a HOY', () => {
    const antes = 1_500_000 / COMPRA   // lo que publicaba el bug
    const r = computeBrokerValue([lote], {}, brokerArs, HOY, HOY, null, 'purchase')
    expect(r.value).toBeCloseTo(1_000, 6)
    expect(r.value / antes).toBeCloseTo(2 / 3, 6)   // −33,3% en la fila
    expect(r.pnlUsd).toBeCloseTo(0, 9)
  })

  it('pesoLotUsd: el fallback sin precio ya no arrastra el tc_compra', () => {
    const enCuentaUsd = { ...lote, broker: 'Schwab' }
    const u = pesoLotUsd(enCuentaUsd, {}, HOY, 'purchase')
    expect(u.valueUsd).toBeCloseTo(1_000, 6)          // antes: 1.500
    expect(u.investedUsd).toBeCloseTo(1_500, 6)       // el costo del MODO no cambia
    expect(u.investedUsdToday).toBeCloseTo(1_000, 6)
  })

  it('valueEquityLot: idem, y el P&L queda 0', () => {
    const r = valueEquityLot(lote, brokerArs, {}, HOY, HOY, 'purchase')
    expect(r.valueUsd).toBeCloseTo(1_000, 6)
    expect(r.investedUsd).toBeCloseTo(1_000, 6)
    expect(r.pnlUsd).toBeCloseTo(0, 9)
  })
})

describe('setBrokersRegistry([]) — el registro se puede limpiar', () => {
  // Es estado de MÓDULO y no se limpiaba nunca. Como el login es navegación SPA
  // (sin reload), en una máquina compartida el usuario B valuaba con los brokers
  // del usuario A. AuthContext ahora lo limpia en login y en logout.
  const subDelUsuarioA = { id: 2, name: 'Mi cuenta dólar', currency: 'USD', parent_broker_id: 1 }
  const regA = [{ id: 1, name: 'Balanz', currency: 'ARS' }, subDelUsuarioA]

  it('limpiarlo devuelve isArUsdBroker al fallback por nombre', () => {
    setBrokersRegistry(regA)
    expect(isArUsdBroker('Mi cuenta dólar')).toBe(true)      // reconocido por parent_broker_id

    setBrokersRegistry([])
    // Ya no queda nada del usuario A: cae al fallback por NOMBRE, que no matchea.
    expect(isArUsdBroker('Mi cuenta dólar')).toBe(false)
    // Y el fallback sigue funcionando para la convención del backend.
    expect(isArUsdBroker('Balanz · USD')).toBe(true)
  })

  it('un lote del usuario B deja de heredar el ruteo del usuario A', () => {
    const lote = { asset: 'YPFD', quantity: 100, invested: 1000, is_cash: false,
                   broker: 'Mi cuenta dólar', currency: 'USD' }
    setBrokersRegistry(regA)
    expect(valuationPriceKey(lote, false)).toBe('YPFD.BA')   // ruteo heredado de A
    setBrokersRegistry([])
    expect(valuationPriceKey(lote, false)).toBe('YPFD')      // sin herencia
  })
})

// El logo del efectivo usa la MISMA etiqueta que el texto: sin esto, el cash del
// sub-broker dolar de un broker AR mostraba el logo de Tether en lugar del dolar.
describe('cashAssetLabel — el dolar del sub-broker AR no es Tether', () => {
  it('USDT en un sub-broker "· USD" se muestra como USD', () => {
    expect(cashAssetLabel({ is_cash: 1, asset: 'USDT', broker: 'Balanz · USD' })).toBe('USD')
  })
  it('USDT en un exchange cripto sigue siendo USDT', () => {
    expect(cashAssetLabel({ is_cash: 1, asset: 'USDT', broker: 'Binance' })).toBe('USDT')
  })
  it('el cash en pesos no se toca', () => {
    expect(cashAssetLabel({ is_cash: 1, asset: 'ARS', broker: 'IOL' })).toBe('ARS')
  })
  it('un activo normal pasa sin cambios (manda el logo real)', () => {
    expect(cashAssetLabel({ is_cash: 0, asset: 'AAPL', broker: 'Schwab' })).toBe('AAPL')
  })
})
