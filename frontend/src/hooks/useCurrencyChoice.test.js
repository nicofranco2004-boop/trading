// El mapeo de los dos ejes del CurrencyContext (currency + valuationDollar) a
// la ÚNICA opción que ve el usuario. Ahora hay dos controles que lo usan (el
// riel de /config y el selector global del shell), así que el mapeo dejó de ser
// un detalle interno de un componente: si se rompe, los dos muestran distinto.
//
// El entorno de test es 'node' (sin DOM), así que se testea el modelo puro —
// el render se verifica a mano en el navegador.

import { describe, it, expect } from 'vitest'
import { CURRENCY_CHOICES, activeChoiceKey, fmtRate } from './useCurrencyChoice'

describe('activeChoiceKey', () => {
  it('ARS gana sobre el dólar de valuación (la opción visible es Pesos)', () => {
    expect(activeChoiceKey('ARS', 'mep')).toBe('ars')
    // Clave del round-trip: en Pesos el valuationDollar se CONSERVA, así que
    // acá sigue diciendo 'ccl' y la opción visible igual tiene que ser Pesos.
    expect(activeChoiceKey('ARS', 'ccl')).toBe('ars')
  })

  it('USD elige según el dólar de valuación', () => {
    expect(activeChoiceKey('USD', 'mep')).toBe('mep')
    expect(activeChoiceKey('USD', 'ccl')).toBe('ccl')
  })

  it('cualquier valor raro cae en mep (el default del contexto)', () => {
    expect(activeChoiceKey('USD', undefined)).toBe('mep')
    expect(activeChoiceKey(undefined, undefined)).toBe('mep')
    expect(activeChoiceKey('usd', 'blue')).toBe('mep')
  })
})

describe('fmtRate', () => {
  it('formatea con separador de miles es-AR y sin decimales', () => {
    expect(fmtRate(1424)).toBe('$1.424')
    expect(fmtRate(1424.37)).toBe('$1.424')
  })

  it('devuelve null cuando todavía no hay cotización', () => {
    // El caller pinta un espacio en blanco: mostrar "$0" afirmaría un dólar a
    // cero mientras /dolar está en vuelo.
    expect(fmtRate(null)).toBe(null)
    expect(fmtRate(undefined)).toBe(null)
    expect(fmtRate(0)).toBe(null)
    expect(fmtRate(-5)).toBe(null)
    expect(fmtRate('no es un número')).toBe(null)
  })
})

describe('CURRENCY_CHOICES', () => {
  it('son 3, en orden de riel, con las piezas que consumen los controles', () => {
    expect(CURRENCY_CHOICES.map(o => o.key)).toEqual(['mep', 'ccl', 'ars'])
    for (const o of CURRENCY_CHOICES) {
      expect(o.label).toBeTruthy()
      expect(o.hint).toBeTruthy()
      // symbol + tag arman la pastilla compacta ("US$ MEP") y la variante mini.
      expect(o.symbol).toBeTruthy()
      expect(o.tag).toBeTruthy()
    }
  })

  it('el símbolo distingue dólar de peso', () => {
    const bySym = Object.fromEntries(CURRENCY_CHOICES.map(o => [o.key, o.symbol]))
    expect(bySym.mep).toBe('US$')
    expect(bySym.ccl).toBe('US$')
    expect(bySym.ars).toBe('$')
  })
})
