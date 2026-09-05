// Tests de los formatters de moneda (fmtMoneyRaw / fmtConvertedRaw).
//
// Motivo: en es-AR el PUNTO es separador de MILES, así que "$135.444" son ciento
// treinta y cinco mil pesos — pero se lee como "135,444". Un usuario reportó
// justamente esa ambigüedad. El fix agrega `minimumFractionDigits` (antes solo
// se seteaba `maximumFractionDigits`, así que `decimals: 2` sobre un valor
// redondo seguía imprimiendo "$135.444" y no desambiguaba nada).
//
// Invariante que NO se puede romper: con `decimals` en su default (0) el output
// tiene que ser byte-idéntico al de antes — Cartera y Dashboard dependen de eso.
import { describe, it, expect } from 'vitest'
import { fmtMoneyRaw, fmtConvertedRaw } from './CurrencyContext'

describe('decimales — desambiguar el punto de miles de es-AR', () => {
  it('decimals:2 imprime los centavos aunque el valor sea redondo', () => {
    expect(fmtConvertedRaw(135444, 'ARS', { decimals: 2 })).toBe('$135.444,00')
  })

  it('decimals:2 con signo (celda de P&L)', () => {
    expect(fmtConvertedRaw(135443.8, 'ARS', { signed: true, decimals: 2 })).toBe('+$135.443,80')
    expect(fmtConvertedRaw(-135443.8, 'ARS', { signed: true, decimals: 2 })).toBe('−$135.443,80')
  })

  it('en USD también respeta los 2 decimales', () => {
    expect(fmtConvertedRaw(90.1189, 'USD', { signed: true, decimals: 2 })).toBe('+US$90,12')
  })

  it('fmtMoneyRaw convierte y respeta decimales', () => {
    // Caso real: el P&L de la venta de YPFD (90,1189 USD) al blue del 22/4/2026.
    // Da los "$135.444" que mostraba la fila — ahora sin ambigüedad de lectura.
    expect(fmtMoneyRaw(90.1189, 'ARS', 1502.95, { decimals: 2 })).toBe('$135.444,20')
  })
})

describe('decimales — el default (0) queda idéntico a antes', () => {
  it('fmtConvertedRaw sin opts', () => {
    expect(fmtConvertedRaw(135444, 'ARS')).toBe('$135.444')
    expect(fmtConvertedRaw(1234.56, 'USD')).toBe('US$1.235')
  })

  it('fmtMoneyRaw sin opts (Cartera/Dashboard)', () => {
    expect(fmtMoneyRaw(100, 'ARS', 1500)).toBe('$150.000')
    expect(fmtMoneyRaw(1234.56, 'USD', 1500)).toBe('US$1.235')
  })

  it('null / NaN siguen dando —', () => {
    expect(fmtConvertedRaw(null, 'ARS', { decimals: 2 })).toBe('—')
    expect(fmtMoneyRaw(NaN, 'ARS', 1500, { decimals: 2 })).toBe('—')
  })

  it('ARS sin tcValuacion válido no convierte (queda en USD)', () => {
    expect(fmtMoneyRaw(100, 'ARS', 0)).toBe('US$100')
  })
})
