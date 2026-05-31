// Tests para los helpers de conversión de CurrencyContext (Fase A —
// toggle global ARS/USD).
//
// Los helpers `fromUsd` y `fromArs` son funciones puras — no requieren
// montar componentes React. La lógica del Provider/hook se valida vía
// los pages que ya consumen `useCurrency()` (Dashboard, HomeMobile,
// PositionsMobile, Positions) — si rompen, falla el build y/o smoke tests.

import { describe, it, expect } from 'vitest'
import { fromUsd, fromArs } from './CurrencyContext'

describe('fromUsd / fromArs helpers', () => {
  it('fromUsd con USD currency no cambia el valor', () => {
    expect(fromUsd(100, 'USD', 1415)).toBe(100)
  })

  it('fromUsd con ARS currency multiplica por tcBlue', () => {
    expect(fromUsd(100, 'ARS', 1415)).toBe(141500)
  })

  it('fromArs con ARS currency no cambia el valor', () => {
    expect(fromArs(141500, 'ARS', 1415)).toBe(141500)
  })

  it('fromArs con USD currency divide por tcBlue', () => {
    expect(fromArs(141500, 'USD', 1415)).toBe(100)
  })

  it('null / undefined / NaN pasan through sin romper', () => {
    expect(fromUsd(null, 'ARS', 1415)).toBe(null)
    expect(fromUsd(undefined, 'ARS', 1415)).toBe(undefined)
    expect(Number.isNaN(fromUsd(NaN, 'ARS', 1415))).toBe(true)
    expect(fromArs(null, 'USD', 1415)).toBe(null)
  })

  it('tcBlue=0 no rompe (devuelve valor original)', () => {
    // Edge case: si tcBlue no está disponible (loading), no convertimos
    // — devolvemos el valor USD as-is para que el render no muestre 0
    // ni Infinity.
    expect(fromUsd(100, 'ARS', 0)).toBe(100)
    expect(fromArs(100, 'USD', 0)).toBe(100)
  })

  it('tcBlue negativo no convierte (defensa)', () => {
    expect(fromUsd(100, 'ARS', -1)).toBe(100)
    expect(fromArs(100, 'USD', -1)).toBe(100)
  })

  it('round-trip: fromUsd → fromArs vuelve al original', () => {
    const original = 1234.56
    const ars = fromUsd(original, 'ARS', 1415)
    const back = fromArs(ars, 'USD', 1415)
    expect(back).toBeCloseTo(original, 6)
  })
})
