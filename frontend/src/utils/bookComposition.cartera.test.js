import { describe, it, expect } from 'vitest'
import { assetSlicesFromPositions, DEFAULT_TOP_ASSETS } from './bookComposition.js'
import { ASSET_CLASS_META } from './assetClass.js'

// "Distribución de activos" de Análisis: la torta por activo de UNA cartera.
const pos = (asset, value, extra = {}) => ({ asset, value_usd: value, is_cash: false, ...extra })

describe('assetSlicesFromPositions', () => {
  it('el efectivo de varias monedas y brokers es UNA porción, con el gris de la torta por tipo', () => {
    const { items } = assetSlicesFromPositions([
      pos('AAPL', 600),
      pos('USD', 200, { is_cash: true }),
      pos('ARS', 150, { is_cash: true }),
      pos('USDT', 50, { is_cash: true }),
    ])
    const ef = items.filter(i => i.key === 'efectivo')
    expect(ef).toHaveLength(1)
    expect(ef[0]).toMatchObject({ label: 'Efectivo', value: 400, color: ASSET_CLASS_META.cash.color })
    expect(ef[0].pct).toBeCloseTo(40)
    expect(items.map(i => i.key)).not.toContain('USD')
  })

  it('el mismo activo en dos brokers es una sola porción', () => {
    const { items } = assetSlicesFromPositions([pos('AAPL', 300), pos('AAPL.BA', 200), pos('MSFT', 500)])
    expect(items.map(i => i.key).sort()).toEqual(['AAPL', 'MSFT'])
    expect(items.find(i => i.key === 'AAPL').value).toBe(500)
  })

  it(`más de ${DEFAULT_TOP_ASSETS} activos: los ${DEFAULT_TOP_ASSETS} más grandes y un "Resto" que se abre; todo suma 100 %`, () => {
    const muchos = Array.from({ length: 15 }, (_, i) => pos(`T${i}`, 100 - i))
    const { items } = assetSlicesFromPositions([...muchos, pos('USD', 50, { is_cash: true })])
    const resto = items.find(i => i.key === '__resto__')
    expect(items.filter(i => !['__resto__', 'efectivo'].includes(i.key))).toHaveLength(DEFAULT_TOP_ASSETS)
    expect(resto.assets).toHaveLength(15 - DEFAULT_TOP_ASSETS)
    expect(items.reduce((s, i) => s + i.pct, 0)).toBeCloseTo(100)
  })

  it('sin posiciones con valor, nada', () => {
    expect(assetSlicesFromPositions([pos('AAPL', 0), pos('USD', 0, { is_cash: true })]).items).toEqual([])
  })
})
