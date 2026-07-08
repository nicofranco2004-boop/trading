// Tests del helper canónico de símbolos (Fase 2 del audit de variaciones).
// La invariante: buildPriceSymbols pide EXACTAMENTE las keys que
// computeBrokerValue va a leer — si difieren, la posición cae a costo en
// silencio y "el mismo lote vale distinto en mobile que en desktop".
import { describe, it, expect, beforeEach } from 'vitest'
import { buildPriceSymbols, valuationPriceKey, setBrokersRegistry } from './valuation'

const BROKERS = [
  { id: 1, name: 'Balanz', currency: 'ARS' },
  { id: 2, name: 'Cocos', currency: 'ARS' },
  { id: 3, name: 'Cocos · USD', currency: 'USD', parent_broker_id: 2 },
  { id: 4, name: 'Schwab', currency: 'USD' },
  { id: 5, name: 'Binance', currency: 'USDT', is_exchange: 1 },
]

beforeEach(() => setBrokersRegistry(BROKERS))

describe('buildPriceSymbols — espejo de computeBrokerValue', () => {
  it('broker ARS: holdings → .BA; FCI → as-is', () => {
    const syms = buildPriceSymbols([
      { broker: 'Balanz', asset: 'GGAL', is_cash: 0 },
      { broker: 'Balanz', asset: 'FCI:FIMA-A', is_cash: 0 },
    ], BROKERS)
    expect(syms).toContain('GGAL.BA')
    expect(syms).toContain('FCI:FIMA-A')
  })

  it('broker USD real (Schwab): acción AR → ticker pelado (ADR), CEDEAR → .BA', () => {
    const syms = buildPriceSymbols([
      { broker: 'Schwab', asset: 'GGAL', is_cash: 0, currency: 'USD' },
      { broker: 'Schwab', asset: 'MELI', is_cash: 0, currency: 'USD', asset_type: 'CEDEAR' },
    ], BROKERS)
    expect(syms).toContain('GGAL')      // el ADR NYSE, no el .BA local
    expect(syms).toContain('MELI.BA')   // CEDEAR siempre por su .BA
  })

  it('sub-broker AR "· USD": BYMA → .BA, pero la CRIPTO va SPOT (M-3)', () => {
    const syms = buildPriceSymbols([
      { broker: 'Cocos · USD', asset: 'PAMP', is_cash: 0, currency: 'USD' },
      { broker: 'Cocos · USD', asset: 'BTC', is_cash: 0, currency: 'USD' },
    ], BROKERS)
    expect(syms).toContain('PAMP.BA')
    // la valuación lee prices['BTC'] (spot) — pedir BTC.BA dejaba la cripto a costo
    expect(syms).toContain('BTC')
    expect(syms).not.toContain('BTC.BA')
  })

  it('lote costInPesos en broker USD (IOL sin sibling) → .BA (H-4)', () => {
    const syms = buildPriceSymbols([
      { broker: 'Schwab', asset: 'GGAL', is_cash: 0, currency: 'ARS' },
    ], BROKERS)
    expect(syms).toEqual(['GGAL.BA'])   // pesoLotUsd lo busca con .BA
  })

  it('class-share con punto/espacio (BRK.B) → key normalizada, la MISMA que lee la valuación (B1)', () => {
    // El fetch pide 'BRK-B' (yfinance cotiza con guión) y la valuación (post-B1)
    // lee primero prices[priceSymbol(asset,false,type)] = 'BRK-B' → misma key.
    for (const raw of ['BRK.B', 'BRK B']) {
      const p = { broker: 'Schwab', asset: raw, is_cash: 0, currency: 'USD' }
      const syms = buildPriceSymbols([p], BROKERS)
      expect(syms).toEqual(['BRK-B'])
      expect(valuationPriceKey(p, false)).toBe('BRK-B')
    }
  })

  it('cripto en exchange → spot', () => {
    const syms = buildPriceSymbols([
      { broker: 'Binance', asset: 'BTC', is_cash: 0 },
    ], BROKERS)
    expect(syms).toEqual(['BTC'])
  })

  it('skipea cash, USDT y brokers desconocidos; dedup', () => {
    const syms = buildPriceSymbols([
      { broker: 'Balanz', asset: 'ARS', is_cash: 1 },
      { broker: 'Binance', asset: 'USDT', is_cash: 0 },
      { broker: 'BorradoHaceRato', asset: 'AAPL', is_cash: 0 },
      { broker: 'Balanz', asset: 'GGAL', is_cash: 0 },
      { broker: 'Cocos', asset: 'GGAL', is_cash: 0 },
    ], BROKERS)
    expect(syms).toEqual(['GGAL.BA'])
  })
})

describe('valuationPriceKey', () => {
  it('cash → null', () => {
    expect(valuationPriceKey({ broker: 'Balanz', asset: 'ARS', is_cash: 1 }, true)).toBeNull()
  })
  it('la key del guard coincide con la del fetch (misma posición, misma key)', () => {
    const p = { broker: 'Cocos · USD', asset: 'VIST', is_cash: 0, currency: 'USD' }
    const fetched = buildPriceSymbols([p], BROKERS)
    expect(fetched).toContain(valuationPriceKey(p, false))
  })
})
