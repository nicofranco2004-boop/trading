import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { empresaDeTenencias, tickerDeEmpresa } from './buscadorRapido'
import { ARG_LIDER, ARG_GENERAL, ADR_DE_ACCION_AR } from './tickers'

// "Ver fundamentals" de la ficha del activo y los botones "Tus posiciones" de
// Calidad de cartera: a qué empresa lleva un activo TUYO. Antes la ficha miraba
// sólo el ticker: Telecom (TECO2) no llevaba a TEO, el CEDEAR de Disney abría
// "DISN" (no es Disney en EE.UU.) y Agrometal (AGRO) abría Adecoagro.
const BROKERS = [
  { name: 'Cocos', currency: 'ARS' },
  { name: 'Cocos · USD', currency: 'USD' },
  { name: 'Schwab', currency: 'USD' },
  { name: 'Binance', currency: 'USDT' },
]
const en = (asset, broker = 'Cocos', extra = {}) => ({ asset, broker, ...extra })
const empresa = (...tenencias) => empresaDeTenencias(tenencias, BROKERS)?.ticker ?? null

describe('empresaDeTenencias: la empresa correcta de tu activo, o ninguna', () => {
  it('una acción argentina lleva a la misma empresa en Nueva York', () => {
    expect(empresa(en('TECO2'))).toBe('TEO')
    expect(empresa(en('YPFD'))).toBe('YPF')
    expect(empresa(en('PAMP.BA'))).toBe('PAM')
    expect(empresa(en('GGAL', 'Cocos · USD'))).toBe('GGAL')   // comprada con dólar MEP
    expect(empresa(en('GGAL', 'Schwab'))).toBe('GGAL')         // el ADR
    expect(empresaDeTenencias([en('TECO2')], BROKERS).ir).toBe('/fundamentals?ticker=TEO')
  })

  it('las 67 del panel argentino: su ADR si tiene, ninguna si no (nunca otra empresa)', () => {
    for (const { s } of [...ARG_LIDER, ...ARG_GENERAL]) {
      expect(empresa(en(s)), s).toBe(ADR_DE_ACCION_AR[s] || null)
    }
    expect(empresa(en('AGRO'))).toBe(null)                     // Agrometal, no Adecoagro
  })

  it('un CEDEAR lleva a la acción en EE.UU., con su ticker de allá', () => {
    expect(empresa(en('AAPL'))).toBe('AAPL')
    expect(empresa(en('AAPL.BA'))).toBe('AAPL')
    expect(empresa(en('DISN'))).toBe('DIS')
    expect(empresa(en('BRKB'))).toBe('BRK-B')
    expect(empresa(en('SI'))).toBe('SID')                      // especie en pesos de CSN
    expect(empresa(en('KO', 'Cocos · USD'))).toBe('KO')
  })

  it('en un broker del exterior el ticker es la empresa de allá', () => {
    expect(empresa(en('AAPL', 'Schwab'))).toBe('AAPL')
    expect(empresa(en('CELU', 'Schwab'))).toBe('CELU')         // Celularity
    expect(empresa(en('TEN', 'Schwab'))).toBe('TEN')           // Tsakos
  })

  it('lo que no tiene ficha de empresa no lleva a ningún lado', () => {
    expect(empresa(en('SPY'))).toBe(null)                      // CEDEAR de un ETF
    expect(empresa(en('SPY', 'Schwab'))).toBe(null)
    expect(empresa(en('AL30'))).toBe(null)
    expect(empresa(en('S31E5'))).toBe(null)
    expect(empresa(en('BTC', 'Binance'))).toBe(null)
    expect(empresa(en('FCI:BALANZ-AHORRO'))).toBe(null)
    expect(empresa(en('ARS', 'Cocos', { is_cash: 1 }))).toBe(null)
    expect(empresa(en('RIGO'))).toBe(null)                     // ticker local que no se reconoce
    expect(empresaDeTenencias([], BROKERS)).toBe(null)
  })

  it('si tus lotes de ese ticker son dos empresas distintas, no adivina', () => {
    // CELU en Cocos es Celulosa Argentina; en Schwab, Celularity.
    expect(empresa(en('CELU'), en('CELU', 'Schwab'))).toBe(null)
    expect(empresa(en('CELU', 'Schwab'), en('CELU'))).toBe(null)   // en cualquier orden
    // Mismo ticker y misma empresa en dos brokers: sí.
    expect(empresa(en('GGAL'), en('GGAL', 'Schwab'))).toBe('GGAL')
  })

  it('funciona con operaciones (sin lotes abiertos): sólo hace falta el broker', () => {
    expect(empresa({ asset: 'TECO2', broker: 'Cocos', type: 'Venta' })).toBe('TEO')
  })

  it('tickerDeEmpresa de un CEDEAR (la lista con puntaje de Calidad de cartera)', () => {
    expect(tickerDeEmpresa('DISN', 'cedear')).toBe('DIS')
    expect(tickerDeEmpresa('SI', 'cedear')).toBe('SID')
    expect(tickerDeEmpresa('SPY', 'cedear')).toBe(null)
  })
})

// Las tres pantallas que abren "la empresa de tu activo" usan esta regla y no
// arman el link por su cuenta: si una vuelve a decidir con el ticker solo,
// vuelve el Adecoagro.
const AQUI = dirname(fileURLToPath(import.meta.url))
const fuente = (rel) => readFileSync(resolve(AQUI, rel), 'utf-8')
describe('las pantallas usan la regla única', () => {
  it('la ficha del activo', () => {
    const src = fuente('../pages/AssetDetail.jsx')
    expect(src).toMatch(/empresaDeTenencias\(/)
    expect(src).not.toMatch(/fundamentals\?ticker=/)
    expect(src).not.toMatch(/inferType/)
  })
  it('los botones "Tus posiciones" de Calidad de cartera', () => {
    const src = fuente('../components/fundamentals/AnalyzeView.jsx')
    expect(src).toMatch(/empresaDeTenencias\(/)
    expect(src).not.toMatch(/inferType/)
  })
  it('la lista con puntaje de Calidad de cartera (CEDEARs)', () => {
    const src = fuente('../components/fundamentals/CarteraList.jsx')
    expect(src).toMatch(/tickerDeEmpresa\(p\.asset, 'cedear'\)/)
    expect(src).not.toMatch(/cedearEspecieBase/)
  })
})
