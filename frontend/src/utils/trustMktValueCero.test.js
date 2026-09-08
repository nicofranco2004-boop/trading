// El guard anti-distorsión no puede confiar en un precio de cero.
//
// Espejo del test de backend (tests/test_trust_guard_cero.py). La regla vive en
// TRES lugares —este archivo, snapshots_job._trust_mkt_value y
// behavioral._trust_mkt_value_usd— y las tres tenían el mismo defecto: metían
// "no hay costo con qué comparar" y "el valor es implausible" en la misma
// condición, así que un valor NEGATIVO o NaN se aceptaba y la posición valía
// menos que nada.
//
// DÓNDE NO VA EL FIX: el CERO no se toca. Lo que entra acá es un VALOR
// (precio × CANTIDAD): una posición con cantidad 0 vale 0 de verdad, y hacerla
// caer a costo publicaría un valor fantasma. El precio 0 con cantidad > 0 se
// rechaza en la fuente (pricing/fci.py), no acá.

import { describe, it, expect } from 'vitest'
import { trustMktValue } from './valuation'

const COSTO = 1000

describe('trustMktValue — valor negativo o no finito', () => {
  it('no confía en negativo', () => expect(trustMktValue(-50, COSTO, null)).toBe(false))
  it('no confía en NaN', () => expect(trustMktValue(NaN, COSTO, null)).toBe(false))
  it('no confía en Infinity', () => expect(trustMktValue(Infinity, COSTO, null)).toBe(false))
  it('no confía en null/undefined', () => {
    expect(trustMktValue(null, COSTO, null)).toBe(false)
    expect(trustMktValue(undefined, COSTO, null)).toBe(false)
  })
  it('un valor ínfimo con cantidad > 0 sigue rechazándose', () => {
    expect(trustMktValue(0.0001, COSTO, null)).toBe(false)
  })
})

describe('trustMktValue — el cero es legítimo', () => {
  it('cantidad 0 → valor 0, y se acepta', () => {
    expect(trustMktValue(0, COSTO, null)).toBe(true)
    expect(trustMktValue(0, COSTO, null, true)).toBe(true)
    expect(trustMktValue(0, COSTO, 'BOND')).toBe(true)
  })
})

describe('trustMktValue — lo que ya andaba', () => {
  it('sin costo sigue devolviendo true', () => {
    expect(trustMktValue(500, 0, null)).toBe(true)
  })
  it('un precio normal se confía', () => {
    expect(trustMktValue(1200, COSTO, null)).toBe(true)
  })
  it('las bandas no cambiaron', () => {
    expect(trustMktValue(COSTO * 50, COSTO, null)).toBe(true)
    expect(trustMktValue(COSTO * 51, COSTO, null)).toBe(false)
    expect(trustMktValue(COSTO * 4, COSTO, 'BOND')).toBe(true)
    expect(trustMktValue(COSTO * 5, COSTO, 'BOND')).toBe(false)
  })
})
