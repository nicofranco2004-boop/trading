import { describe, it, expect, beforeEach } from 'vitest'
import { sellPriceSuggestion, setBrokersRegistry } from './valuation'

// Auditoría 20/10: un CEDEAR en dólares alojado en el broker EN PESOS (así lo deja
// el importador de Balanz) recibía como precio sugerido de venta el de la acción
// en Nueva York (US$ 230) en vez del CEDEAR (US$ 18). Tiene que leerse igual que
// lo valúa Cartera (usdLotValue): .BA ÷ MEP.
const B = (id, name, currency = 'ARS', parent_broker_id = null) => ({ id, name, currency, parent_broker_id })

beforeEach(() => setBrokersRegistry([B(1, 'Balanz'), B(2, 'Balanz · USD', 'USDT', 1)]))

const PRECIOS = { 'AAPL.BA': 27780, AAPL: 230 }

describe('precio sugerido al vender', () => {
  it('lote en dólares en el broker en pesos → .BA ÷ MEP, no Nueva York', () => {
    const p = { broker: 'Balanz', asset: 'AAPL', currency: 'USD', quantity: 5, buy_price: 17.2, asset_type: '' }
    const px = sellPriceSuggestion(p, PRECIOS, { enPesos: false, cedearRate: 1540 })
    expect(px).toBeCloseTo(27780 / 1540, 4)
  })
  it('lote en dólares en la pata en dólares → lo mismo', () => {
    const p = { broker: 'Balanz · USD', asset: 'AAPL', currency: 'USD', quantity: 5, buy_price: 17.2, asset_type: 'CEDEAR' }
    expect(sellPriceSuggestion(p, PRECIOS, { enPesos: false, cedearRate: 1540 })).toBeCloseTo(27780 / 1540, 4)
  })
  it('lote en pesos en el broker en pesos → el precio en pesos', () => {
    const p = { broker: 'Balanz', asset: 'AAPL', currency: 'ARS', quantity: 5, buy_price: 26000, asset_type: 'CEDEAR' }
    expect(sellPriceSuggestion(p, PRECIOS, { enPesos: true, cedearRate: 1540 })).toBe(27780)
  })
})
