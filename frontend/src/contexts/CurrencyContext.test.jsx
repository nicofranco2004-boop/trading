// Tests para los helpers de conversión de CurrencyContext (Fase A —
// toggle global ARS/USD).
//
// Los helpers `fromUsd` y `fromArs` son funciones puras — no requieren
// montar componentes React. La lógica del Provider/hook se valida vía
// los pages que ya consumen `useCurrency()` (Dashboard, HomeMobile,
// PositionsMobile, Positions) — si rompen, falla el build y/o smoke tests.

import { describe, it, expect } from 'vitest'
import { fromUsd, fromArs, fmtMoneyRaw, fmtMoneyCompactRaw } from './CurrencyContext'

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

// ─── Phase B: fmtMoneyRaw / fmtMoneyCompactRaw ─────────────────────────────

describe('fmtMoneyRaw (Phase B formatter)', () => {
  it('USD: símbolo US$ y formato es-AR', () => {
    expect(fmtMoneyRaw(1234.56, 'USD', 1415)).toBe('US$1.235')
  })

  it('ARS: convierte por tcBlue y usa símbolo $', () => {
    // 100 * 1415 = 141500
    expect(fmtMoneyRaw(100, 'ARS', 1415)).toBe('$141.500')
  })

  it('valores negativos llevan signo − (no -)', () => {
    expect(fmtMoneyRaw(-100, 'USD', 1415)).toBe('−US$100')
  })

  it('signed: true agrega + a positivos', () => {
    expect(fmtMoneyRaw(50, 'USD', 1415, { signed: true })).toBe('+US$50')
    expect(fmtMoneyRaw(-50, 'USD', 1415, { signed: true })).toBe('−US$50')
  })

  it('null / undefined / NaN devuelven —', () => {
    expect(fmtMoneyRaw(null, 'USD', 1415)).toBe('—')
    expect(fmtMoneyRaw(undefined, 'ARS', 1415)).toBe('—')
    expect(fmtMoneyRaw(NaN, 'ARS', 1415)).toBe('—')
    expect(fmtMoneyRaw(Infinity, 'USD', 1415)).toBe('—')
  })

  it('ARS con tcBlue=0 cae a USD (defensa, no muestra $0)', () => {
    expect(fmtMoneyRaw(100, 'ARS', 0)).toBe('US$100')
  })

  it('decimals: 2 muestra centavos', () => {
    expect(fmtMoneyRaw(1234.56, 'USD', 1415, { decimals: 2 })).toBe('US$1.234,56')
  })
})

describe('fmtMoneyCompactRaw (Phase B abbreviated)', () => {
  it('< 1k: muestra entero con separador', () => {
    expect(fmtMoneyCompactRaw(500, 'USD', 1415)).toBe('US$500')
  })

  it('1k-10k: abrevia con 1 decimal', () => {
    expect(fmtMoneyCompactRaw(5000, 'USD', 1415)).toBe('US$5.0k')
  })

  it('10k-1M: abrevia con k', () => {
    expect(fmtMoneyCompactRaw(50000, 'USD', 1415)).toBe('US$50k')
  })

  it('boundary 9.95k-10k: no muestra "10.0k" (smooth jump)', () => {
    // Antes del fix: 9999 → "10.0k", 10000 → "10k" (flicker visual)
    // Después: ambos → "10k" (consistente)
    expect(fmtMoneyCompactRaw(9499, 'USD', 1415)).toBe('US$9.5k')
    expect(fmtMoneyCompactRaw(9949, 'USD', 1415)).toBe('US$9.9k')
    expect(fmtMoneyCompactRaw(9950, 'USD', 1415)).toBe('US$10k')   // ← clave
    expect(fmtMoneyCompactRaw(9999, 'USD', 1415)).toBe('US$10k')
    expect(fmtMoneyCompactRaw(10000, 'USD', 1415)).toBe('US$10k')
  })

  it('boundary 9.95M-10M: misma lógica', () => {
    expect(fmtMoneyCompactRaw(9_499_999, 'USD', 1415)).toBe('US$9.5M')
    expect(fmtMoneyCompactRaw(9_949_999, 'USD', 1415)).toBe('US$9.9M')
    expect(fmtMoneyCompactRaw(9_950_000, 'USD', 1415)).toBe('US$10M')
    expect(fmtMoneyCompactRaw(10_000_000, 'USD', 1415)).toBe('US$10M')
  })

  it('1M+: abrevia con M', () => {
    expect(fmtMoneyCompactRaw(5_000_000, 'USD', 1415)).toBe('US$5.0M')
    expect(fmtMoneyCompactRaw(50_000_000, 'USD', 1415)).toBe('US$50M')
  })

  it('1B+: abrevia con B', () => {
    expect(fmtMoneyCompactRaw(5_000_000_000, 'USD', 1415)).toBe('US$5.0B')
  })

  it('ARS convierte y abrevia: 50k USD → ~71M ARS al blue 1415', () => {
    // 50000 * 1415 = 70_750_000 → toFixed(0) "71" (rounds up)
    expect(fmtMoneyCompactRaw(50000, 'ARS', 1415)).toBe('$71M')
  })

  it('signed funciona con compact', () => {
    expect(fmtMoneyCompactRaw(-50000, 'USD', 1415, { signed: true })).toBe('−US$50k')
    expect(fmtMoneyCompactRaw(50000, 'USD', 1415, { signed: true })).toBe('+US$50k')
  })

  it('null / NaN devuelven —', () => {
    expect(fmtMoneyCompactRaw(null, 'USD', 1415)).toBe('—')
    expect(fmtMoneyCompactRaw(NaN, 'ARS', 1415)).toBe('—')
  })
})
