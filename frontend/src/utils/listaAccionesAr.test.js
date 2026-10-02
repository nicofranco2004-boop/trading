import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { ARG_LIDER, ARG_GENERAL, inferType } from './tickers'
import { classifyAsset } from './assetClass'
import { classifyAssetBucket } from './profileAllocations'
import { DIAGNOSTIC_GENERATORS } from './diagnostics'

// Una sola regla de "¿esto es argentino?", la misma en la pantalla y en el
// servidor (backend/tests/test_lista_acciones_ar.py prueba el otro lado).
//
// La lista de la pantalla se toma del PROGRAMA (los arrays que usa la app), no
// buscando un formato en el texto: una entrada escrita con comillas dobles o en
// varias líneas quedaba en la pantalla y no en el servidor sin que la prueba
// del servidor se enterara. La del servidor se lee de su archivo, con cualquier
// comilla, y si queda algo sin leer, rojo.
const AQUI = dirname(fileURLToPath(import.meta.url))
const listaDelServidor = () => {
  const py = readFileSync(resolve(AQUI, '../../../backend/ai/trade_tickers.py'), 'utf-8')
  const bloque = py.match(/^AR_STOCK_TICKERS = \{([\s\S]*?)\n\}/m)
  expect(bloque, 'no encontré AR_STOCK_TICKERS en trade_tickers.py').toBeTruthy()
  const cuerpo = bloque[1].replace(/#[^\n]*/g, '')
  const leidos = [...cuerpo.matchAll(/['"]([A-Z0-9.]+)['"]/g)].map(m => m[1])
  const entradas = cuerpo.split(',').map(x => x.trim()).filter(Boolean)
  expect(leidos.length, 'hay una entrada de AR_STOCK_TICKERS que no se pudo leer').toBe(entradas.length)
  return [...new Set(leidos)].sort()
}
const listaDeLaPantalla = () => [...new Set([...ARG_LIDER, ...ARG_GENERAL].map(x => x.s))].sort()

const COCOS = [{ name: 'Cocos', currency: 'ARS' }]
const SCHWAB = [{ name: 'Schwab', currency: 'USD' }]

describe('acciones argentinas: una lista, la misma en la pantalla y en el servidor', () => {
  it('son las mismas en los dos lados', () => {
    expect(listaDeLaPantalla().length).toBeGreaterThanOrEqual(64)
    expect(listaDeLaPantalla()).toEqual(listaDelServidor())
  })

  it('PCAR ya no está: en BYMA es el CEDEAR de PACCAR', () => {
    expect(listaDeLaPantalla()).not.toContain('PCAR')
    expect(classifyAsset({ asset: 'PCAR', broker: 'Cocos' }, COCOS)).not.toBe('accion_ar')
  })

  it('cada una, en un broker argentino, es "Acción AR" en la torta', () => {
    for (const s of listaDeLaPantalla()) {
      expect(classifyAsset({ asset: s, broker: 'Cocos' }, COCOS), s).toBe('accion_ar')
    }
  })

  it('la ficha y los buscadores (inferType) las reconocen, con o sin ".BA"', () => {
    for (const s of listaDeLaPantalla()) {
      expect(inferType(s), s).toBe('stock_ar')
      expect(inferType(s + '.BA'), s + '.BA').toBe('stock_ar')
    }
    expect(inferType('AAPL.BA')).toBe('cedear')
  })

  it('lo que el importador marcó cripto no es una acción argentina (ROSE)', () => {
    expect(classifyAsset({ asset: 'ROSE', broker: 'Cocos' }, COCOS)).toBe('accion_ar')
    expect(classifyAsset({ asset: 'ROSE', broker: 'Cocos', asset_type: 'CRYPTO' }, COCOS)).toBe('cripto')
  })
})

describe('renta fija del perfil = "Bonos y letras" de la torta (igual que Rendi AI)', () => {
  it('letras, ONs y soberanos son renta fija; acciones y fondos no', () => {
    const rf = (p, b = COCOS) => classifyAssetBucket(p, b)
    expect(rf({ asset: 'S31E5', broker: 'Cocos' })).toBe('fixed_income')
    expect(rf({ asset: 'YMCJO', broker: 'Cocos', asset_type: 'ON' })).toBe('fixed_income')
    expect(rf({ asset: 'AL30D', broker: 'Cocos' })).toBe('fixed_income')
    expect(rf({ asset: 'TX26', broker: 'Cocos' })).toBe('fixed_income')
    // "TG" volvía bonos a las transportadoras de gas.
    expect(rf({ asset: 'TGSU2', broker: 'Cocos' })).toBe('equity')
    expect(rf({ asset: 'TGNO4', broker: 'Cocos' })).toBe('equity')
    expect(rf({ asset: 'TXN', broker: 'Schwab' }, SCHWAB)).toBe('equity')
    expect(rf({ asset: 'FCI:BALANZ-AHORRO', broker: 'Cocos' })).toBe('equity')
  })
})

describe('Diagnóstico: concentración en Argentina (misma regla que Comportamiento)', () => {
  const gen = DIAGNOSTIC_GENERATORS.find(g => g.id === 'geographic_concentration_ar')
  const brokers = [...COCOS, ...SCHWAB, { name: 'Cocos · USD', currency: 'USD' }]
  const correr = (pos) => gen.generate({
    positionsWithValue: pos, brokers,
    totalPortfolio: pos.reduce((s, p) => s + p.value_usd, 0),
  })

  it('CEDEARs de Apple y Microsoft en Cocos no son Argentina', () => {
    expect(correr([
      { asset: 'AAPL', broker: 'Cocos', value_usd: 5000 },
      { asset: 'MSFT', broker: 'Cocos', value_usd: 5000 },
    ])).toBeNull()
  })

  it('ADRs en Schwab y acciones compradas con dólar MEP sí', () => {
    expect(correr([
      { asset: 'YPF', broker: 'Schwab', value_usd: 5000 },
      { asset: 'GGAL', broker: 'Schwab', value_usd: 5000 },
    ])).toMatch(/^\*\*100%\*\*/)
    expect(correr([
      { asset: 'GGAL', broker: 'Cocos · USD', value_usd: 5000 },
      { asset: 'YPFD', broker: 'Cocos · USD', value_usd: 5000 },
    ])).toMatch(/^\*\*100%\*\*/)
  })

  it('cuenta lo que VALE, no lo que costó, y los pesos cuentan', () => {
    // Costó poco, vale mucho: 80 % del valor es argentino.
    expect(correr([
      { asset: 'S31E5', broker: 'Cocos', invested: 1, value_usd: 6000 },
      { asset: 'ARS', broker: 'Cocos', is_cash: 1, value_usd: 2000 },
      { asset: 'SPY', broker: 'Schwab', invested: 100000, value_usd: 2000 },
    ])).toMatch(/^\*\*80%\*\*/)
  })
})
