import { describe, it, expect } from 'vitest'
import { entrada } from './useAlVerse'

// La única definición de "entra en escalera" (8 listas y grillas la usan): las
// clases tienen que ser las que index.css anima y esconde.
describe('entrada', () => {
  it('antes de verse espera escondida; después entra, con su turno en --i', () => {
    expect(entrada(false, 3, 'h-full')).toEqual({ className: 'h-full por-entrar', style: { '--i': 3 } })
    expect(entrada(true, 3, 'h-full')).toEqual({ className: 'h-full entra', style: { '--i': 3 } })
  })
  it('sin clases propias no deja espacios sueltos', () => {
    expect(entrada(true, 0).className).toBe('entra')
  })
})
