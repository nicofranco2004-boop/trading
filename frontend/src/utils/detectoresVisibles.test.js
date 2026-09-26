import { describe, it, expect } from 'vitest'
import { detectoresVisibles } from './detectoresVisibles'

// Los valores son los que manda /api/plan/features (`behavioral_tags_visible`),
// no los de ningún plan en particular: la regla es "lo que diga la tabla".
describe('detectoresVisibles — cuántas cartas de Comportamiento se ven', () => {
  it('sin tope (null) se ven todas, sea cual sea el nombre del plan', () => {
    // El caso del 15/10: Plus pasa a null. Antes se mostraba 1.
    expect(detectoresVisibles(null)).toBe(Infinity)
    expect([1, 2, 3].slice(0, detectoresVisibles(null))).toHaveLength(3)
  })

  it('con tope se ve ese número', () => {
    expect(detectoresVisibles(3)).toBe(3)
    expect(detectoresVisibles(6)).toBe(6)
  })

  it('sin features todavía (undefined) se ve una sola: fail-closed', () => {
    expect(detectoresVisibles(undefined)).toBe(1)
  })

  it('0 sigue contando como 1, como antes', () => {
    expect(detectoresVisibles(0)).toBe(1)
  })
})
