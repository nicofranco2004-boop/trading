// La «Var. día» de un lote (utils/variacionDelDia.js): la de la Cartera de la
// compu, mudada sin cambios para que el mapa de calor del Dashboard use la misma.
import { describe, it, expect, beforeEach } from 'vitest'
import { variacionDelDia, variacionDelDiaUsd } from './variacionDelDia'
import { setBrokersRegistry } from './valuation'

beforeEach(() => setBrokersRegistry([
  { id: 1, name: 'IOL', currency: 'ARS' }, { id: 2, name: 'Schwab', currency: 'USD' },
]))

const BROKERS = { IOL: { id: 1, name: 'IOL', currency: 'ARS' }, Schwab: { id: 2, name: 'Schwab', currency: 'USD' } }
// Con lo que pide la valuación para decidir si confía en el precio (`brokerDe`,
// `tcValuacion`, `costBasis`): al juntar con lo publicado (30/10) el control le
// pregunta a `valuePositionLot`, no a una copia de su cuenta.
const ctx = (prices, prevClose) => ({
  prices, prevClose, tcValuacion: 1000, tcCedear: 1000, tcCripto: 1050, costBasis: 'today',
  exchangeBrokers: new Set(), brokerDe: n => BROKERS[n],
})

describe('variacionDelDia', () => {
  it('una acción de afuera en un broker en dólares: su ticker, en dólares', () => {
    const p = { broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10 }
    expect(variacionDelDia(p, false, ctx({ NVDA: 150 }, { NVDA: 140 }))).toEqual({ amount: 100, pct: 10 / 140, base: 1400 })
  })

  it('un CEDEAR en un broker en dólares se mide en su .BA y pasa por el MEP', () => {
    const p = { broker: 'Schwab', asset: 'AAPL', asset_type: 'CEDEAR', quantity: 10 }
    const dv = variacionDelDia(p, false, ctx({ 'AAPL.BA': 20000, AAPL: 999 }, { 'AAPL.BA': 19000, AAPL: 1 }))
    expect(dv.pct).toBeCloseTo(1000 / 19000, 12)
    expect(dv.amount).toBeCloseTo(10, 12)        // 10 × $1.000 ÷ 1.000
    expect(dv.base).toBeCloseTo(190, 12)
  })

  it('en un broker en pesos el monto va en pesos; la versión en dólares lo pasa por el MEP', () => {
    const p = { broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION', quantity: 100 }
    const c = ctx({ 'GGAL.BA': 6000 }, { 'GGAL.BA': 5800 })
    expect(variacionDelDia(p, true, c).amount).toBe(20000)
    const usd = variacionDelDiaUsd(p, true, c)
    expect(usd.amount).toBe(20)
    expect(usd.base).toBe(580)
    expect(usd.pct).toBeCloseTo(200 / 5800, 12)
  })

  it('sin dato: efectivo, precio a mano, sin cierre anterior o sin precio de ahora', () => {
    const c = ctx({ NVDA: 150 }, { NVDA: 140 })
    expect(variacionDelDia({ broker: 'Schwab', asset: 'USD', is_cash: 1, quantity: 0 }, false, c)).toBeNull()
    expect(variacionDelDia({ broker: 'Schwab', asset: 'NVDA', quantity: 1, price_override: 155 }, false, c)).toBeNull()
    expect(variacionDelDia({ broker: 'Schwab', asset: 'KO', quantity: 1 }, false, c)).toBeNull()
    expect(variacionDelDia({ broker: 'Schwab', asset: 'NVDA', quantity: 1 }, false, ctx({}, { NVDA: 140 }))).toBeNull()
  })

  it('si la valuación no confía en el precio, no hay movimiento del día (lo mismo que el celular)', () => {
    // AL30 de la cuenta de prueba: costo $0,70 por lámina contra un precio de $847.
    // La fila lo valúa al costo; la Var. día decía −USD 217.
    const al30 = { broker: 'IOL', asset: 'AL30', asset_type: 'BONO', quantity: 200000, invested: 140000, currency: 'ARS' }
    expect(variacionDelDia(al30, true, ctx({ 'AL30.BA': 847.5 }, { 'AL30.BA': 849.2 }))).toBeNull()
    // El mismo bono con su costo de verdad: sí.
    const sano = { ...al30, invested: 170000000 }
    expect(variacionDelDia(sano, true, ctx({ 'AL30.BA': 847.5 }, { 'AL30.BA': 849.2 })).pct).toBeCloseTo(-1.7 / 849.2, 12)
    // Un CEDEAR en dólares con costo en USD se compara contra su .BA pasado a dólares.
    const aapl = { broker: 'Schwab', asset: 'AAPL', asset_type: 'CEDEAR', quantity: 10, invested: 200 }
    expect(variacionDelDia(aapl, false, ctx({ 'AAPL.BA': 20000 }, { 'AAPL.BA': 19000 }))).not.toBeNull()
  })
})
