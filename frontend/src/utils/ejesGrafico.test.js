// Las cuentas de arrastrar los ejes (utils/ejesGrafico.js). El arrastre montado
// de verdad se prueba en components/asset/EjesGrafico.test.js.
import { describe, it, expect } from 'vitest'
import {
  ESCALA_Y_MAX, ESCALA_Y_MIN, PIXELES_POR_DOBLE, escalaYDespuesDe, factorDeFechas, rangoConEscala,
} from './ejesGrafico'

describe('eje de precios', () => {
  it('hacia abajo achica (entra más rango); hacia arriba estira', () => {
    expect(escalaYDespuesDe(1, PIXELES_POR_DOBLE)).toBeCloseTo(2)
    expect(escalaYDespuesDe(1, -PIXELES_POR_DOBLE)).toBeCloseTo(0.5)
    expect(escalaYDespuesDe(1, 0)).toBe(1)
  })

  it('tiene topes', () => {
    expect(escalaYDespuesDe(1, 5000)).toBe(ESCALA_Y_MAX)
    expect(escalaYDespuesDe(1, -5000)).toBe(ESCALA_Y_MIN)
  })

  it('estira alrededor del centro de lo que se ve', () => {
    expect(rangoConEscala(100, 200, 1)).toEqual([100, 200])
    expect(rangoConEscala(100, 200, 2)).toEqual([50, 250])
    expect(rangoConEscala(100, 200, 0.5)).toEqual([125, 175])
  })
})

describe('eje de fechas', () => {
  it('a la derecha acerca (menos días), a la izquierda aleja', () => {
    expect(factorDeFechas(PIXELES_POR_DOBLE)).toBeCloseTo(0.5)
    expect(factorDeFechas(-PIXELES_POR_DOBLE)).toBeCloseTo(2)
  })
})
