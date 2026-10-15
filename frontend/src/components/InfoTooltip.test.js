// El corrimiento que mete el globo del (?) adentro de la pantalla tiene que ir
// por el margen del lado ANCLADO: con align 'right' el globo está anclado por
// `right` y un `marginLeft` no lo mueve (ver estiloDeCorrimiento).
import { describe, it, expect } from 'vitest'
import { estiloDeCorrimiento } from './InfoTooltip'

describe('estiloDeCorrimiento', () => {
  it('sin corrimiento no hay estilo', () => {
    expect(estiloDeCorrimiento('right', 0)).toBeUndefined()
  })
  it("con align 'right' corre con marginRight (marginLeft no lo movería)", () => {
    expect(estiloDeCorrimiento('right', 48)).toEqual({ marginRight: -48 })
    expect(estiloDeCorrimiento('right', -20)).toEqual({ marginRight: 20 })
  })
  it("con 'left' y 'center' corre con marginLeft, como antes", () => {
    expect(estiloDeCorrimiento('left', -108)).toEqual({ marginLeft: -108 })
    expect(estiloDeCorrimiento('center', 12)).toEqual({ marginLeft: 12 })
  })
})
