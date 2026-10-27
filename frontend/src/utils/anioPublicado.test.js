import { describe, it, expect } from 'vitest'
import { anioPublicado, detalleVsInflacion } from './anioPublicado'

// La elección "año entero o tramo parcial" vive UNA vez y la usan el inicio y
// Reportes. Antes cada pantalla elegía por su cuenta y las dos escondían la
// inflación en el tramo parcial.
describe('anioPublicado', () => {
  const entero = {
    pct: 12.0, vs_sp500_pct: -1.0, vs_inflation_pct: 2.5,
    retorno_ars_pct: 30.0, inflation_pct: 27.5,
    parcial_pct: null, parcial_vs_inflation_pct: null,
  }
  const parcial = {
    pct: null, vs_sp500_pct: null, vs_inflation_pct: null,
    parcial_pct: 13.0, parcial_desde: '2026-01-31', parcial_vs_sp500_pct: 1.5,
    parcial_vs_inflation_pct: -0.8, parcial_retorno_ars_pct: 19.24, parcial_inflation_pct: 20.2,
  }

  it('el año entero: su número y sus veredictos', () => {
    expect(anioPublicado(entero)).toEqual({
      parcial: false, pct: 12.0, desde: null, vsSp: -1.0, vsInfl: 2.5,
      retornoArs: 30.0, inflacion: 27.5,
    })
  })

  it('el tramo parcial: su número, su fecha y SUS DOS veredictos', () => {
    expect(anioPublicado(parcial)).toEqual({
      parcial: true, pct: 13.0, desde: '2026-01-31', vsSp: 1.5, vsInfl: -0.8,
      retornoArs: 19.24, inflacion: 20.2,
    })
  })

  it('un backend viejo sin los campos de inflación del tramo: null, no undefined', () => {
    const viejo = { pct: null, parcial_pct: 5, parcial_vs_sp500_pct: 1 }
    expect(anioPublicado(viejo).vsInfl).toBeNull()
  })

  it('sin fila no hay año', () => {
    expect(anioPublicado(null)).toBeNull()
  })
})

describe('detalleVsInflacion', () => {
  it('en dólares dice con qué número en pesos se restó', () => {
    expect(detalleVsInflacion(anioPublicado({ pct: null, parcial_pct: 13, parcial_retorno_ars_pct: 19.24, parcial_inflation_pct: 20.2 }), false))
      .toBe('Se compara en pesos: tu cartera hizo 19,24% en pesos y la inflación 20,2%')
  })
  it('en pesos, nada: el número de la tarjeta ya es el que se restó', () => {
    expect(detalleVsInflacion(anioPublicado({ pct: 10, retorno_ars_pct: 10, inflation_pct: 8 }), true)).toBeNull()
  })
})
