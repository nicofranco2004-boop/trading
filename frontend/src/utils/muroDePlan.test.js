import { describe, it, expect } from 'vitest'
import { muroTapaLaPantalla } from './muroDePlan'

// El muro de cuenta en pausa y el buscador ⌘K usan esta MISMA regla.
describe('muroTapaLaPantalla', () => {
  const pausa = { cuenta_en_pausa: true }
  it('cuenta activa: nunca', () => {
    expect(muroTapaLaPantalla({ cuenta_en_pausa: false }, '/dashboard')).toBe(false)
    expect(muroTapaLaPantalla(null, '/dashboard')).toBe(false)
  })
  it('cuenta en pausa: tapa la app…', () => {
    expect(muroTapaLaPantalla(pausa, '/dashboard')).toBe(true)
    expect(muroTapaLaPantalla(pausa, '/')).toBe(true)
  })
  it('…salvo por donde se sale de la pausa (la llave no puede quedar adentro)', () => {
    expect(muroTapaLaPantalla(pausa, '/planes')).toBe(false)
    expect(muroTapaLaPantalla(pausa, '/billing/success')).toBe(false)
  })
})
