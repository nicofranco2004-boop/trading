import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { CRYPTO_SYMBOLS, isCrypto, cryptoBrokerFactor } from './crypto.js'
import { CRYPTO, tickerName } from './tickers.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const CRIPTO = 1554, MEP = 1499

// OJO al escribir un caso nuevo: TODO test que espere 1 por otro motivo (exchange,
// no-cripto, override, rate faltante) tiene que pasar 'ARS' igual. Sin la moneda el
// factor devuelve 1 SOLO por eso, y el test pasaría en verde sin ejercitar nunca su
// propio mecanismo — verde por la razón equivocada.
describe('cryptoBrokerFactor', () => {
  it('aplica el premium a cripto de una cuenta EN PESOS', () => {
    expect(cryptoBrokerFactor('BTC', false, false, CRIPTO, MEP, 'ARS')).toBeCloseTo(CRIPTO / MEP, 6)
  })
  it('SIN premium en una cuenta EN DÓLARES, aunque el broker sea argentino', () => {
    // La persona puso dólares y el broker le muestra dólares: no hubo ningún peso
    // en el medio que haya que convertir. Antes se aplicaba igual y el valor Y el
    // "Invertido" salían ~4% arriba.
    expect(cryptoBrokerFactor('BTC', false, false, CRIPTO, MEP, 'USD')).toBe(1)
    expect(cryptoBrokerFactor('BTC', false, false, CRIPTO, MEP, 'USDT')).toBe(1)
    expect(cryptoBrokerFactor('BTC', false, false, CRIPTO, MEP, 'usd')).toBe(1)
  })
  it('sin moneda de cuenta → 1 (el lado conservador: nunca infla)', () => {
    expect(cryptoBrokerFactor('BTC', false, false, CRIPTO, MEP)).toBe(1)
  })
  it('sin premium en un EXCHANGE', () => {
    expect(cryptoBrokerFactor('BTC', true, false, CRIPTO, MEP, 'ARS')).toBe(1)
  })
  it('sin premium para no-cripto', () => {
    expect(cryptoBrokerFactor('AAPL', false, false, CRIPTO, MEP, 'ARS')).toBe(1)
  })
  it('sin premium con override', () => {
    expect(cryptoBrokerFactor('BTC', false, true, CRIPTO, MEP, 'ARS')).toBe(1)
  })
  it('sin premium si falta algún rate (fallback)', () => {
    expect(cryptoBrokerFactor('BTC', false, false, null, MEP, 'ARS')).toBe(1)
    expect(cryptoBrokerFactor('BTC', false, false, CRIPTO, 0, 'ARS')).toBe(1)
  })
  it('reproduce el reporte del 2026-09-09 (broker argentino, saldo en dólares)', () => {
    // Números exactos del usuario y los dólares de ese día. Rendi mostraba
    // USD 2.956,39 y su broker USD 2.840,92 — la diferencia era este factor.
    const QTY = 0.03637049, SPOT = 78110.70
    const cripto = 1591.56, mep = (1528.8 + 1530) / 2
    const antes = cryptoBrokerFactor('BTC', false, false, cripto, mep, undefined)
    expect(QTY * SPOT * (cripto / mep)).toBeCloseTo(2956.39, 2)   // lo que se veía
    const ahora = cryptoBrokerFactor('BTC', false, false, cripto, mep, 'USDT')
    expect(QTY * SPOT * ahora).toBeCloseTo(2840.92, 2)            // lo que muestra el broker
    expect(antes).toBe(1)  // el default sin moneda tampoco infla
  })
  it('CVX/DASH (colisión Convex/Dash) NO son cripto', () => {
    expect(isCrypto('CVX')).toBe(false)
    expect(isCrypto('DASH')).toBe(false)
    expect(isCrypto('btc')).toBe(true)  // case-insensitive
  })
})

describe('el buscador sólo ofrece cripto que la app sabe valuar', () => {
  // Hasta 2026-10-08 el buscador ofrecía 22 criptos que no estaban en
  // CRYPTO_SYMBOLS: se valuaban como lo que el código fuera en otro lado (FET =
  // Forum Energy, 394 veces de más; JUP = otra moneda; KAS en pesos = sin precio).
  const ESTABLES = new Set(['USDT', 'USDC'])   // backend CRIPTO_ESTABLES: van como dólares

  it('cada cripto del buscador está en CRYPTO_SYMBOLS (o es una estable)', () => {
    const fuera = CRYPTO.map((x) => x.s).filter((s) => !CRYPTO_SYMBOLS.has(s) && !ESTABLES.has(s))
    expect(fuera).toEqual([])
  })
  it('las que entraron se valúan como cripto', () => {
    for (const s of ['FET', 'AR', 'ENS', 'QNT', 'KAS', 'JUP', 'ONE', 'RNDR', 'RENDER']) {
      expect(isCrypto(s), s).toBe(true)
    }
  })
  it('DASH, ROSE y AGIX no se ofrecen como cripto: el código es la acción', () => {
    const buscador = new Set(CRYPTO.map((x) => x.s))
    for (const s of ['DASH', 'ROSE', 'AGIX']) {
      expect(isCrypto(s), s).toBe(false)
      expect(buscador.has(s), s).toBe(false)
    }
    // El nombre sale de la primera lista que tiene el código, y la de cripto va
    // primero: el que tenía Rosenbusch veía «Oasis Network».
    expect(tickerName('ROSE')).toBe('Instituto Rosenbusch')
    expect(tickerName('DASH')).toBe('DoorDash')
  })
})

describe('CRYPTO_SYMBOLS — paridad FE/BE', () => {
  it('coincide EXACTO con backend/cripto.py CRYPTO_SYMBOLS (guard anti-drift)', () => {
    const py = readFileSync(resolve(__dirname, '../../../backend/cripto.py'), 'utf8')
    const m = py.match(/CRYPTO_SYMBOLS = \{([\s\S]*?)\}/)
    expect(m).toBeTruthy()
    const beSet = new Set([...m[1].matchAll(/'([A-Z0-9]+)'/g)].map((x) => x[1]))
    expect(beSet.size).toBeGreaterThan(50)
    expect(CRYPTO_SYMBOLS.size).toBe(beSet.size)
    for (const s of beSet) expect(CRYPTO_SYMBOLS.has(s)).toBe(true)
    for (const s of CRYPTO_SYMBOLS) expect(beSet.has(s)).toBe(true)
  })
})
