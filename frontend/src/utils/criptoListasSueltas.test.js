// «¿Esto es cripto?» en la pantalla: una sola respuesta, la de la torta.
//
// Hasta 2026-10-08 la tarjeta de perfil (classifyAssetBucket) y la ficha del
// buscador (inferType) tenían su propia lista de cripto (36 y 13 códigos):
// KAS, FET o WBTC eran «equity» en la tarjeta mientras la torta de al lado
// decía Cripto, y PEPE, KAS o FET en «tus activos» del buscador salían
// «acción de EE.UU.».
// Mervall-E AI usa la misma regla del lado del servidor
// (backend/tests/test_cripto_listas_sueltas.py).
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { classifyAsset } from './assetClass'
import { computeAllocationBuckets } from './profileAllocations'
import { inferType } from './tickers'
import { esCripto, CRIPTO_ESTABLES } from './crypto'

const BROKERS = [
  { name: 'Wallet', currency: 'USD' },
  { name: 'Santander', currency: 'ARS' },
]
const pos = (asset, broker = 'Wallet', extra = {}) =>
  ({ asset, broker, is_cash: 0, value_usd: 100, asset_type: null, ...extra })

describe('la tarjeta de perfil dice lo mismo que la torta', () => {
  it('KAS, FET, WBTC y RENDER son alternativo (antes: equity)', () => {
    for (const s of ['PEPE', 'KAS', 'FET', 'WBTC', 'RENDER']) {
      expect(classifyAsset(pos(s), BROKERS), s).toBe('cripto')
      expect(computeAllocationBuckets([pos(s)], BROKERS).alternative, s).toBe(100)
    }
  })

  it('lo que el importador marcó CRYPTO es cripto aunque el código sea una acción', () => {
    const rose = pos('ROSE', 'Santander', { asset_type: 'CRYPTO' })
    expect(classifyAsset(rose, BROKERS)).toBe('cripto')
    expect(computeAllocationBuckets([rose], BROKERS).alternative).toBe(100)
  })

  it('DoorDash es una acción, no la cripto Dash', () => {
    expect(computeAllocationBuckets([pos('DASH')], BROKERS).equity).toBe(100)
  })

  it('las stables son efectivo (también BUSD y FDUSD, como en la torta)', () => {
    for (const s of ['USDT', 'USDC', 'DAI', 'BUSD', 'FDUSD']) {
      expect(computeAllocationBuckets([pos(s)], BROKERS).cash, s).toBe(100)
    }
  })

  it('para cada activo, la porción de la tarjeta sale de la clase de la torta', () => {
    const casos = ['PEPE', 'BTC', 'USDT', 'AL30', 'TGSU2', 'AAPL', 'HYPE', 'DASH']
    const esperado = { cripto: 'alternative', cash: 'cash', bono: 'fixed_income' }
    for (const s of casos) {
      const p = pos(s, s === 'AL30' || s === 'TGSU2' ? 'Santander' : 'Wallet')
      const porcion = esperado[classifyAsset(p, BROKERS)] || 'equity'
      expect(computeAllocationBuckets([p], BROKERS)[porcion], s).toBe(100)
    }
  })
})

describe('el buscador (inferType) usa la lista de la app', () => {
  it('PEPE, KAS y FET son cripto, con o sin -USD', () => {
    for (const s of ['PEPE', 'KAS', 'FET', 'PEPE-USD', 'USDT', 'btc']) {
      expect(inferType(s), s).toBe('crypto')
    }
  })

  it('las acciones del catálogo siguen siendo acciones', () => {
    expect(inferType('DASH')).toBe('stock_us')
    expect(inferType('AAPL')).toBe('stock_us')
    expect(inferType('ROSE')).toBe('stock_ar')
  })

  it('esCripto: el espejo de cripto.es_cripto del servidor', () => {
    expect(esCripto('pepe')).toBe(true)
    expect(esCripto('TON-USD')).toBe(true)
    for (const s of CRIPTO_ESTABLES) expect(esCripto(s)).toBe(true)
    for (const s of ['AAPL', 'DASH', 'ROSE', 'CVX', 'AGIX', '', null, 'BTC.BA']) {
      expect(esCripto(s), String(s)).toBe(false)
    }
  })
})

// Guard: ninguna lista de cripto suelta en el código de la app — un array de
// códigos pelados ('BTC', 'ETH', …). El catálogo del buscador (tickers.js) y la
// tabla de ejemplo de la Landing son objetos ({ s: 'BTC', … }) y no cuentan.
// Pueden tener una: la lista misma (crypto.js) y los datos del modo demo.
const PERMITIDOS = new Set(['utils/crypto.js', 'utils/demo.js'])
const LISTA_DE_CODIGOS = /\[\s*(?:(?:\/\/[^\n]*\n\s*)*['"][A-Za-z0-9.-]+['"]\s*,?\s*)+\]/g

function archivos(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f)
    if (statSync(p).isDirectory()) return archivos(p)
    return /\.(js|jsx)$/.test(f) && !/\.test\.jsx?$/.test(f) ? [p] : []
  })
}

describe('no hay otra lista de cripto en la pantalla', () => {
  it('ningún array/Set con BTC y ETH fuera de los permitidos', () => {
    const src = resolve(__dirname, '..')
    const sueltas = []
    for (const p of archivos(src)) {
      const rel = relative(src, p)
      if (PERMITIDOS.has(rel)) continue
      const texto = readFileSync(p, 'utf8')
      for (const m of texto.matchAll(LISTA_DE_CODIGOS)) {
        if (/['"]BTC['"]/.test(m[0]) && /['"]ETH['"]/.test(m[0])) sueltas.push(rel)
      }
    }
    expect(sueltas).toEqual([])
  })
})
