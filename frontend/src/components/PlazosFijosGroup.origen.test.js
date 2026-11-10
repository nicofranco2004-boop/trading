// De qué broker salió la plata de un plazo fijo: lo lee el aviso de «Eliminar»
// para decir ANTES de confirmar adónde vuelve (2026-11-10).
import { describe, it, expect } from 'vitest'
import { origenDelPlazoFijo } from './PlazosFijosGroup'

describe('origen de la plata del plazo fijo', () => {
  it('lee el broker de la receta del alta', () => {
    expect(origenDelPlazoFijo({ undo_meta_json: '{"src":"pf_alta","broker":"Bull Market"}' }))
      .toBe('Bull Market')
  })
  it('plata de afuera, uno de antes o una receta rota: ninguno', () => {
    expect(origenDelPlazoFijo({ undo_meta_json: '{"src":"pf_alta","broker":null}' })).toBe(null)
    expect(origenDelPlazoFijo({ undo_meta_json: null })).toBe(null)
    expect(origenDelPlazoFijo({ undo_meta_json: '{roto' })).toBe(null)
  })
})
