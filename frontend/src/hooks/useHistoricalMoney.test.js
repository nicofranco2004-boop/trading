// Tests del chain de prioridad de FX histórico (audit fix H1).
//
// `resolveHistoricalFx` es una función pura — el wrapper hook `useHistoricalMoney`
// (que combina useCurrency + useFxHistory) se valida implícitamente vía el
// build + smoke en Operations/OperationsMobile. Acá testeamos la lógica pura
// porque es donde puede romperse el chain.

import { describe, it, expect } from 'vitest'
import { resolveHistoricalFx } from './useHistoricalMoney'

const TC_BLUE_ACTUAL = 1466

// Helper: lookup determinístico para los tests
const getRate = (d) => {
  const m = {
    '2024-08-15': 1100,
    '2024-12-31': 1180,
    '2025-06-01': 1310,
    '2025-12-01': 1420,
  }
  return m[d] || null
}

describe('resolveHistoricalFx — chain de prioridad', () => {
  it('USD currency: SIEMPRE devuelve 1 (no convierte)', () => {
    // Aun con stampedFx + dateIso presentes, currency='USD' fuerza 1
    expect(resolveHistoricalFx('USD', TC_BLUE_ACTUAL, { stampedFx: 9999, dateIso: '2024-08-15' }, getRate)).toBe(1)
    expect(resolveHistoricalFx('USD', TC_BLUE_ACTUAL, {}, getRate)).toBe(1)
  })

  it('ARS + stampedFx válido: gana sobre todo lo demás (prioridad 1)', () => {
    // Aun con dateIso que mapea a otro valor, stamped tiene preferencia
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { stampedFx: 1234, dateIso: '2024-08-15' }, getRate)
    expect(r).toBe(1234)
  })

  it('ARS + stampedFx=null: fallback al lookup por fecha (prioridad 2)', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { stampedFx: null, dateIso: '2024-08-15' }, getRate)
    expect(r).toBe(1100) // del map del helper
  })

  it('ARS + stampedFx=0: fallback al lookup (0 no cuenta como válido)', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { stampedFx: 0, dateIso: '2024-08-15' }, getRate)
    expect(r).toBe(1100)
  })

  it('ARS + stampedFx negativo: fallback al lookup', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { stampedFx: -100, dateIso: '2024-08-15' }, getRate)
    expect(r).toBe(1100)
  })

  it('ARS + dateIso sin match: fallback a tcBlue actual (prioridad 3)', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { dateIso: '2030-01-01' }, getRate)
    expect(r).toBe(TC_BLUE_ACTUAL)
  })

  it('ARS + sin dateIso ni stamped: tcBlue actual', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, {}, getRate)
    expect(r).toBe(TC_BLUE_ACTUAL)
  })

  it('ARS + tcBlue inválido (0): último fallback es 1 (no rompe matemática)', () => {
    // Edge: si por alguna razón tcBlue es 0 / negativo, no devolvemos 0
    // (rompería multiplicación). Devolvemos 1 → valor queda en USD nominal.
    expect(resolveHistoricalFx('ARS', 0, {}, getRate)).toBe(1)
    expect(resolveHistoricalFx('ARS', -100, {}, getRate)).toBe(1)
  })

  it('ARS + getRateForDate no es función: cae a tcBlue', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { dateIso: '2024-08-15' }, null)
    expect(r).toBe(TC_BLUE_ACTUAL)
  })

  it('ARS + getRateForDate devuelve 0: cae a tcBlue', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { dateIso: '2024-08-15' }, () => 0)
    expect(r).toBe(TC_BLUE_ACTUAL)
  })

  it('opts undefined no rompe', () => {
    expect(() => resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, undefined, getRate)).not.toThrow()
    expect(resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, undefined, getRate)).toBe(TC_BLUE_ACTUAL)
  })
})

// ─── Casos reales: la razón de existir de este fix ───────────────────────────

describe('resolveHistoricalFx — casos reales (audit fix H1)', () => {
  it('trade cerrado en agosto 2024 (blue=1100) NO se infla al blue de hoy', () => {
    // Antes del fix: $200 pnl_usd × 1466 (blue actual) = $293,200 ARS — INFLADO
    // Después del fix: usa el blue stampeado al cierre = $200 × 1100 = $220,000 ARS
    const fx = resolveHistoricalFx('ARS', 1466, { stampedFx: 1100, dateIso: '2024-08-15' }, getRate)
    expect(fx).toBe(1100)
    const pnlArs = 200 * fx
    expect(pnlArs).toBe(220_000)  // realista
  })

  it('trade sin fx stampeado pero con date: usa lookup', () => {
    // Operaciones legacy (importadas antes del Phase D backend) sin fx_to_usd
    const fx = resolveHistoricalFx('ARS', 1466, { dateIso: '2025-06-01' }, getRate)
    expect(fx).toBe(1310)
  })

  it('toggle en USD: el chain entero queda neutralizado (no convierte)', () => {
    // El user mira en USD → siempre devolvemos 1, el value canónico se preserva
    const fx = resolveHistoricalFx('USD', 1466, { stampedFx: 1100, dateIso: '2024-08-15' }, getRate)
    expect(fx).toBe(1)
  })
})
