import { describe, it, expect, vi } from 'vitest'

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})) } }))

import { monedaDe } from './Watchlist'

// La watchlist decía "US$" a todo. Desde que la variación del día sale de BYMA
// para los `.BA` (y los bonos en pesos tienen precio), la etiqueta tiene que
// salir del símbolo: GGAL.BA a 5.850 son pesos.
describe('Watchlist — la moneda del precio sale del símbolo', () => {
  it('.BA es BYMA, en pesos', () => {
    expect(monedaDe('GGAL.BA')).toBe('$')
    expect(monedaDe('al30.ba')).toBe('$')
  })
  it('sin sufijo, en dólares (acciones de EEUU, bonos en su especie D, cripto)', () => {
    expect(monedaDe('AAPL')).toBe('US$')
    expect(monedaDe('AL30')).toBe('US$')
    expect(monedaDe('BTC-USD')).toBe('US$')
  })
})
