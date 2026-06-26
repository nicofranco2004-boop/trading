import { describe, it, expect } from 'vitest'
import {
  positionSection, isFixedIncome, sectionKey, sectionLabel,
  isLetraTicker, normCcy, sortSectionKeys, isKnownArBond,
} from './sections.js'

describe('positionSection', () => {
  it('clasifica bonos por moneda', () => {
    expect(positionSection('BOND', 'AL30', 'USD')).toEqual({ category: 'BONO', currency: 'USD' })
    expect(positionSection('BOND', 'AL30', 'ARS')).toEqual({ category: 'BONO', currency: 'ARS' })
    expect(positionSection('BOND', 'AL30', 'USDT')).toEqual({ category: 'BONO', currency: 'USD' })
  })

  it('clasifica bono por ticker aunque falte el tipo (IEB)', () => {
    expect(positionSection('', 'GD35', 'USD')).toEqual({ category: 'BONO', currency: 'USD' })
    expect(positionSection(null, 'AL30', 'ARS')).toEqual({ category: 'BONO', currency: 'ARS' })
  })

  it('clasifica letras por patrón de ticker', () => {
    expect(positionSection('', 'S28N5', 'ARS')).toEqual({ category: 'LETRA', currency: 'ARS' })
    expect(positionSection('OTHER', 'T13F6', 'ARS')).toEqual({ category: 'LETRA', currency: 'ARS' })
  })

  it('clasifica FCI', () => {
    expect(positionSection('FUND', 'COCORA', 'ARS')).toEqual({ category: 'FCI', currency: 'ARS' })
    expect(positionSection('FUND', 'BAHUSDA', 'USD')).toEqual({ category: 'FCI', currency: 'USD' })
  })

  it('renta variable → null', () => {
    expect(positionSection('CEDEAR', 'SPY', 'USD')).toBeNull()
    expect(positionSection('STOCK', 'YPFD', 'ARS')).toBeNull()
    expect(positionSection('CRYPTO', 'BTC', 'USD')).toBeNull()
    // ETF en BOND_META NO es renta fija
    expect(positionSection('', 'TIP', 'USD')).toBeNull()
  })
})

describe('helpers', () => {
  it('isLetraTicker', () => {
    expect(isLetraTicker('S28N5')).toBe(true)
    expect(isLetraTicker('AL30')).toBe(false)
    expect(isLetraTicker('SPY')).toBe(false)
  })
  it('isKnownArBond filtra ETFs', () => {
    expect(isKnownArBond('AL30')).toBe(true)
    expect(isKnownArBond('GD35')).toBe(true)
    expect(isKnownArBond('TIP')).toBe(false)   // etf
    expect(isKnownArBond('SPY')).toBe(false)
  })
  it('normCcy', () => {
    expect(normCcy('USDT')).toBe('USD')
    expect(normCcy('USD')).toBe('USD')
    expect(normCcy('ARS')).toBe('ARS')
    expect(normCcy(null)).toBe('ARS')
  })
  it('sectionKey / sectionLabel', () => {
    expect(sectionKey('BONO', 'USD')).toBe('BONO|USD')
    expect(sectionLabel('BONO', 'USD')).toBe('Bonos USD')
    expect(sectionLabel('FCI', 'ARS')).toBe('FCI ARS')
  })
  it('isFixedIncome', () => {
    expect(isFixedIncome({ asset_type: 'BOND', asset: 'AL30', currency: 'USD' })).toBe(true)
    expect(isFixedIncome({ asset_type: 'CEDEAR', asset: 'SPY', currency: 'USD' })).toBe(false)
  })
  it('sortSectionKeys', () => {
    expect(sortSectionKeys(['FCI|ARS', 'BONO|ARS', 'BONO|USD'])).toEqual(['BONO|USD', 'BONO|ARS', 'FCI|ARS'])
  })
})
