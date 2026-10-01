import { describe, it, expect } from 'vitest'
import { esRecienLlegada, RECIEN_LLEGADA_MS } from './VozContext'

// La respuesta de Rendi AI se arma en escalera SÓLO si acaba de llegar.
describe('esRecienLlegada', () => {
  const ahora = 1_000_000
  it('la que llegó hace un instante, sí', () => {
    expect(esRecienLlegada({ llego: ahora - 200 }, ahora)).toBe(true)
  })
  it('la misma un rato después (volviste a la pantalla), no', () => {
    expect(esRecienLlegada({ llego: ahora - RECIEN_LLEGADA_MS - 1 }, ahora)).toBe(false)
  })
  it('una conversación reabierta (sin hora de llegada: no se guarda en la sesión), no', () => {
    expect(esRecienLlegada({ role: 'assistant', content: 'x', meta: {} }, ahora)).toBe(false)
    expect(esRecienLlegada(null, ahora)).toBe(false)
  })
})

import { sumarPaso } from './VozContext'

// Los pasos que manda el servidor mientras Rendi AI piensa.
describe('sumarPaso', () => {
  it('agrega el paso nuevo al final', () => {
    expect(sumarPaso(['Leyendo tu cartera'], 'Buscando los precios de hoy')).toEqual(['Leyendo tu cartera', 'Buscando los precios de hoy'])
  })
  it('el mismo paso repetido seguido no se duplica', () => {
    const l = ['Leyendo tu cartera']
    expect(sumarPaso(l, 'Leyendo tu cartera')).toBe(l)
  })
  it('un paso vacío no agrega un renglón en blanco', () => {
    const l = ['A']
    expect(sumarPaso(l, null)).toBe(l)
    expect(sumarPaso(l, '')).toBe(l)
  })
  it('un paso que vuelve después de otro sí se agrega (es otro momento)', () => {
    expect(sumarPaso(['A', 'B'], 'A')).toEqual(['A', 'B', 'A'])
  })
})
