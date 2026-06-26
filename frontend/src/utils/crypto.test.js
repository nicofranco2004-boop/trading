import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { CRYPTO_SYMBOLS, isCrypto, cryptoBrokerFactor } from './crypto.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const CRIPTO = 1554, MEP = 1499

describe('cryptoBrokerFactor', () => {
  it('aplica el premium a cripto en un BROKER (no exchange)', () => {
    expect(cryptoBrokerFactor('BTC', false, false, CRIPTO, MEP)).toBeCloseTo(CRIPTO / MEP, 6)
  })
  it('sin premium en un EXCHANGE', () => {
    expect(cryptoBrokerFactor('BTC', true, false, CRIPTO, MEP)).toBe(1)
  })
  it('sin premium para no-cripto', () => {
    expect(cryptoBrokerFactor('AAPL', false, false, CRIPTO, MEP)).toBe(1)
  })
  it('sin premium con override', () => {
    expect(cryptoBrokerFactor('BTC', false, true, CRIPTO, MEP)).toBe(1)
  })
  it('sin premium si falta algún rate (fallback)', () => {
    expect(cryptoBrokerFactor('BTC', false, false, null, MEP)).toBe(1)
    expect(cryptoBrokerFactor('BTC', false, false, CRIPTO, 0)).toBe(1)
  })
  it('CVX/DASH (colisión Convex/Dash) NO son cripto', () => {
    expect(isCrypto('CVX')).toBe(false)
    expect(isCrypto('DASH')).toBe(false)
    expect(isCrypto('btc')).toBe(true)  // case-insensitive
  })
})

describe('CRYPTO_SYMBOLS — paridad FE/BE', () => {
  it('coincide EXACTO con backend/main.py CRYPTO_SYMBOLS (guard anti-drift)', () => {
    const py = readFileSync(resolve(__dirname, '../../../backend/main.py'), 'utf8')
    const m = py.match(/CRYPTO_SYMBOLS = \{([\s\S]*?)\}/)
    expect(m).toBeTruthy()
    const beSet = new Set([...m[1].matchAll(/'([A-Z0-9]+)'/g)].map((x) => x[1]))
    expect(beSet.size).toBeGreaterThan(50)
    expect(CRYPTO_SYMBOLS.size).toBe(beSet.size)
    for (const s of beSet) expect(CRYPTO_SYMBOLS.has(s)).toBe(true)
    for (const s of CRYPTO_SYMBOLS) expect(beSet.has(s)).toBe(true)
  })
})
