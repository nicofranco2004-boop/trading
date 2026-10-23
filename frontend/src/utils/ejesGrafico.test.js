// Las cuentas de arrastrar los ejes (utils/ejesGrafico.js). El arrastre montado
// de verdad se prueba en components/asset/EjesGrafico.test.js.
import { describe, it, expect } from 'vitest'
import { PIXELES_POR_DOBLE, factorDeFechas, rangoCorrido, rangoEstirado } from './ejesGrafico'

describe('eje de precios', () => {
  it('hacia abajo entra el doble de rango; hacia arriba, la mitad; el centro queda quieto', () => {
    expect(rangoEstirado(100, 200, PIXELES_POR_DOBLE)).toEqual({ lo: 50, hi: 250 })
    expect(rangoEstirado(100, 200, -PIXELES_POR_DOBLE)).toEqual({ lo: 125, hi: 175 })
    expect(rangoEstirado(100, 200, 0)).toEqual({ lo: 100, hi: 200 })
  })

  it('tiene topes por arrastre', () => {
    const lejos = rangoEstirado(100, 200, 5000)
    expect(lejos.hi - lejos.lo).toBeCloseTo(600)
    const cerca = rangoEstirado(100, 200, -5000)
    expect(cerca.hi - cerca.lo).toBeCloseTo(20)
  })

  it('arrastrar el gráfico hacia abajo muestra precios más altos', () => {
    expect(rangoCorrido(100, 200, 0.1)).toEqual({ lo: 110, hi: 210 })
    expect(rangoCorrido(100, 200, -0.25)).toEqual({ lo: 75, hi: 175 })
  })
})

describe('eje de fechas', () => {
  it('a la izquierda acerca (menos días), a la derecha aleja', () => {
    // A la izquierda (dx < 0) acerca: la mitad de días; a la derecha aleja.
    expect(factorDeFechas(-PIXELES_POR_DOBLE)).toBeCloseTo(0.5)
    expect(factorDeFechas(PIXELES_POR_DOBLE)).toBeCloseTo(2)
  })
})
