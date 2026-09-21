import { describe, it, expect } from 'vitest'
import { hayMultiLote, cuentaDe } from './lotes'

const pos = (asset, broker, extra = {}) => ({ asset, broker, quantity: 10, is_cash: false, ...extra })

describe('hayMultiLote — cuándo tiene sentido "Ver lotes"', () => {
  it('un lote por activo: no hay nada que desglosar', () => {
    expect(hayMultiLote([pos('AAPL', 'Cocos'), pos('GGAL', 'Cocos'), pos('AAPL', 'Balanz')])).toBe(false)
  })
  it('dos compras del mismo activo en el mismo broker: sí', () => {
    expect(hayMultiLote([pos('AAPL', 'Cocos'), pos('AAPL', 'Cocos')])).toBe(true)
  })
  it('el mismo ticker en pesos y en el sub-broker "· USD" cuenta como dos lotes de UNA cuenta', () => {
    expect(hayMultiLote([pos('AL30', 'Balanz'), pos('AL30', 'Balanz · USD')])).toBe(true)
    expect(cuentaDe('Balanz · USD')).toBe('Balanz')
  })
  it('el efectivo y las posiciones cerradas no cuentan', () => {
    expect(hayMultiLote([
      pos('ARS', 'Cocos', { is_cash: true }), pos('ARS', 'Cocos', { is_cash: true }),
      pos('AAPL', 'Cocos', { quantity: 0 }), pos('AAPL', 'Cocos'),
    ])).toBe(false)
  })
  it('lista vacía o undefined: false', () => {
    expect(hayMultiLote([])).toBe(false)
    expect(hayMultiLote(undefined)).toBe(false)
  })
})
