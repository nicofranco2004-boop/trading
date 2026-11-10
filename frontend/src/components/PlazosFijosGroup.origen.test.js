// Qué pasa con la plata al borrar un plazo fijo: el aviso de «Eliminar» lo dice
// ANTES de confirmar, con lo que decidió el servidor (2026-11-10).
import { describe, it, expect } from 'vitest'
import { plataAlBorrar } from './PlazosFijosGroup'

describe('la plata al borrar un plazo fijo', () => {
  it('lee el broker y si vuelve de lo que manda el servidor', () => {
    expect(plataAlBorrar({ plata_al_borrar: { broker: 'Bull Market', vuelve: true } }))
      .toEqual({ origen: 'Bull Market', vuelve: true })
    expect(plataAlBorrar({ plata_al_borrar: { broker: 'Bull Market', vuelve: false } }))
      .toEqual({ origen: 'Bull Market', vuelve: false })
  })
  it('plata de afuera, uno de antes o sin el dato: ningún broker', () => {
    expect(plataAlBorrar({ plata_al_borrar: { broker: null, vuelve: false } }).origen).toBe(null)
    expect(plataAlBorrar({}).origen).toBe(null)
  })
})
