import { describe, it, expect } from 'vitest'
import { cierreDeVela, textoCuenta } from './cierreDeVela'

// Lunes 02/11/2026: Nueva York ya está en su horario de invierno (UTC−5); Argentina, UTC−3.
const t = (iso) => Date.parse(iso)
const cierra = (mercado, cada, iso) => {
  const fin = cierreDeVela(mercado, cada, t(iso))
  return fin == null ? null : new Date(fin).toISOString().slice(0, 16)
}

describe('cuándo cierra la vela en curso', () => {
  it('Nueva York: velas de horas desde las 9:30; la diaria a las 16; la semanal el viernes', () => {
    expect(cierra('us', '1h', '2026-11-02T15:00:00Z')).toBe('2026-11-02T15:30')   // 10:00 → 10:30
    expect(cierra('us', '1h', '2026-11-02T20:45:00Z')).toBe('2026-11-02T21:00')   // la última: 15:30 → 16:00
    expect(cierra('us', '4h', '2026-11-02T15:00:00Z')).toBe('2026-11-02T18:30')   // 9:30 → 13:30
    expect(cierra('us', '4h', '2026-11-02T19:00:00Z')).toBe('2026-11-02T21:00')   // 13:30 → 16:00
    expect(cierra('us', 'dia', '2026-11-02T15:00:00Z')).toBe('2026-11-02T21:00')
    expect(cierra('us', 'semana', '2026-11-02T15:00:00Z')).toBe('2026-11-06T21:00')
  })
  it('Nueva York en horario de verano: la misma rueda, una hora antes en UTC', () => {
    expect(cierra('us', 'dia', '2026-07-15T15:00:00Z')).toBe('2026-07-15T20:00')
  })
  it('BYMA: velas de horas desde las 10:30; la diaria a las 17', () => {
    expect(cierra('byma', '1h', '2026-11-02T14:10:00Z')).toBe('2026-11-02T14:30')  // 11:10 → 11:30
    expect(cierra('byma', '4h', '2026-11-02T14:10:00Z')).toBe('2026-11-02T17:30')  // 10:30 → 14:30
    expect(cierra('byma', '4h', '2026-11-02T18:00:00Z')).toBe('2026-11-02T20:00')  // 14:30 → 17:00
    expect(cierra('byma', 'dia', '2026-11-02T14:10:00Z')).toBe('2026-11-02T20:00')
  })
  it('cripto: el día entero en UTC; la semanal cierra el lunes 00:00', () => {
    expect(cierra('cripto', '1h', '2026-11-02T14:10:00Z')).toBe('2026-11-02T15:00')
    expect(cierra('cripto', '4h', '2026-11-02T14:10:00Z')).toBe('2026-11-02T16:00')
    expect(cierra('cripto', 'dia', '2026-11-02T14:10:00Z')).toBe('2026-11-03T00:00')
    expect(cierra('cripto', 'semana', '2026-11-02T14:10:00Z')).toBe('2026-11-09T00:00')
    expect(cierra('cripto', 'semana', '2026-11-08T23:30:00Z')).toBe('2026-11-09T00:00')   // domingo
    expect(cierra('cripto', '1h', '2026-11-07T03:20:00Z')).toBe('2026-11-07T04:00')       // sábado también
  })
  it('fuera de la rueda no hay cuenta', () => {
    expect(cierra('us', '1h', '2026-11-02T14:00:00Z')).toBeNull()      // 9:00 en Nueva York
    expect(cierra('us', 'dia', '2026-11-02T21:00:00Z')).toBeNull()     // 16:00 justo: cerró
    expect(cierra('byma', 'dia', '2026-11-02T20:05:00Z')).toBeNull()   // 17:05
    expect(cierra('us', 'dia', '2026-11-07T15:00:00Z')).toBeNull()     // sábado
    expect(cierra('otro', 'dia', '2026-11-02T15:00:00Z')).toBeNull()
  })
  it('en palabras, como TradingView', () => {
    expect(textoCuenta(65 * 1000)).toBe('01:05')
    expect(textoCuenta((3 * 3600 + 12 * 60 + 5) * 1000)).toBe('3:12:05')
    expect(textoCuenta((2 * 86400 + 5 * 3600 + 60) * 1000)).toBe('2d 5h')
    expect(textoCuenta(-5)).toBe('00:00')
  })
})
