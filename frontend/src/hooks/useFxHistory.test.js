// Tests del helper puro `lookupRate` (Phase C — FX histórico).
//
// El hook React `useFxHistory` no se testea acá (requiere @testing-library)
// — el smoke test es el build pasando + Dashboard chart funcionando.

import { describe, it, expect } from 'vitest'
import { lookupRate } from './useFxHistory'

const ROWS = [
  { date: '2025-01-01', blue: 1200 },
  { date: '2025-01-02', blue: 1205 },
  { date: '2025-01-03', blue: 1210 },
  { date: '2025-01-06', blue: 1220 }, // lunes después del weekend
  { date: '2025-01-07', blue: 1225 },
]

describe('lookupRate', () => {
  it('match exacto devuelve el blue de esa fecha', () => {
    expect(lookupRate(ROWS, '2025-01-02')).toBe(1205)
  })

  it('fecha sin match exacto devuelve el día anterior más cercano', () => {
    // Sábado 2025-01-04 no tiene blue (no se publica) → usa viernes 2025-01-03
    expect(lookupRate(ROWS, '2025-01-04')).toBe(1210)
    // Domingo 2025-01-05 → mismo viernes anterior
    expect(lookupRate(ROWS, '2025-01-05')).toBe(1210)
  })

  it('fecha posterior al último row devuelve el último blue', () => {
    expect(lookupRate(ROWS, '2025-02-15')).toBe(1225)
  })

  it('fecha anterior al primer row devuelve null', () => {
    expect(lookupRate(ROWS, '2024-12-31')).toBe(null)
  })

  it('rows vacío devuelve null', () => {
    expect(lookupRate([], '2025-01-01')).toBe(null)
  })

  it('null / undefined / dateIso vacío devuelve null', () => {
    expect(lookupRate(ROWS, null)).toBe(null)
    expect(lookupRate(ROWS, undefined)).toBe(null)
    expect(lookupRate(ROWS, '')).toBe(null)
    expect(lookupRate(null, '2025-01-01')).toBe(null)
  })

  it('rows con entries inválidos (sin date o blue=null) los skipea', () => {
    const dirty = [
      { date: '2025-01-01', blue: 1200 },
      { date: '2025-01-02', blue: null },  // inválido
      { /* no date */ blue: 1300 },        // inválido
      { date: '2025-01-03', blue: 1210 },
    ]
    expect(lookupRate(dirty, '2025-01-02')).toBe(1200) // skipea null, usa día previo
    expect(lookupRate(dirty, '2025-01-03')).toBe(1210)
  })
})
