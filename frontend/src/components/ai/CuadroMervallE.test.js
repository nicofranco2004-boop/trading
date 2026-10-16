import { describe, it, expect } from 'vitest'
import { ladoAlCostado, anchoDelCuerpo, LADO_COSTADO_MAX, LADO_COSTADO_MIN } from './CuadroMervallE'
import { proporcion } from './mervalle/motor'

describe('ladoAlCostado — ¿entra el cuadro al lado del chat?', () => {
  it('compu de 1440 con la barra abierta (228 px libres, medido): al costado, grande', () => {
    expect(ladoAlCostado(228)).toBe(196)
  })
  it('notebook de 1280 con la barra abierta (~170 px libres): al costado, no en la esquina tapando la pregunta', () => {
    expect(ladoAlCostado(170)).toBeGreaterThanOrEqual(LADO_COSTADO_MIN)
  })
  it('pantalla enorme: no pasa del máximo', () => {
    expect(ladoAlCostado(900)).toBe(LADO_COSTADO_MAX)
  })
  it('celular, tablet o costado sin medir: a la esquina', () => {
    expect(ladoAlCostado(16)).toBe(null)
    expect(ladoAlCostado(120)).toBe(null)
    expect(ladoAlCostado(NaN)).toBe(null)
  })
})

describe('anchoDelCuerpo — el cuerpo entero entra parado en el cuadro', () => {
  it.each([104, 128, 138, 196, 220])('cuadro de %i px', (lado) => {
    const ancho = anchoDelCuerpo(lado)
    expect(ancho * proporcion('full')).toBeLessThanOrEqual(lado)
    // y no queda perdido: ocupa al menos tres cuartos del alto
    expect(ancho * proporcion('full')).toBeGreaterThan(lado * 0.75)
  })
})
