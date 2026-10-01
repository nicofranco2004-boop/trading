import { describe, it, expect } from 'vitest'
import { seccionDe } from './TransicionDePantalla'

// El fundido va al cambiar de SECCIÓN, no al moverse adentro de una pantalla.
describe('seccionDe', () => {
  it('el primer tramo de la dirección', () => {
    expect(seccionDe('/posiciones')).toBe('posiciones')
    expect(seccionDe('/activo/NVDA')).toBe('activo')
  })
  it('el inicio es su propia sección', () => {
    expect(seccionDe('/')).toBe('')
    expect(seccionDe('')).toBe('')
  })
  it('una sub-ruta de la misma pantalla no es otra sección', () => {
    expect(seccionDe('/posiciones/3')).toBe(seccionDe('/posiciones'))
  })
  it('Dashboard → Cartera sí', () => {
    expect(seccionDe('/dashboard')).not.toBe(seccionDe('/posiciones'))
  })
})
