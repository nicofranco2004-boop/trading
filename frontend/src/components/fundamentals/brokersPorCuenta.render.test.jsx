// Análisis fundamental («Analizar»): dónde tenés cada papel. Las dos pantallas
// montadas (testing/navegadorMinimo.js) con el servidor simulado en la frontera
// (utils/api):
//   · la lista «Tu cartera» (CarteraList): debajo de cada ticker, en qué brokers;
//   · el detalle de un ticker (DetailPortfolioBlocks): «Tenés 10 nominales en …».
//
// El error (25/11): «Cocos» y su pata en dólares «Cocos · USD» (hija vía
// `parent_broker_id`) se listaban como dos brokers: «Cocos · Cocos · USD».
// El criterio es el de Cartera: cuentas, no filas (utils/brokerAccounts.js).
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto } from '../../testing/navegadorMinimo'
import { PrivacyProvider } from '../../contexts/PrivacyContext'

vi.mock('../../contexts/CurrencyContext', async (orig) => ({
  ...(await orig()),
  useCurrency: () => ({ currency: 'USD', valuationDollar: 'mep', costBasis: 'purchase', tcValuacion: 1555 }),
  pickFinancialRate: (d) => d?.mep?.venta ?? null,
}))
vi.mock('../AssetLogo', () => ({ default: () => null }))

const COCOS = { id: 1, name: 'Cocos', currency: 'ARS', parent_broker_id: null }
const COCOS_USD = { id: 2, name: 'Cocos · USD', currency: 'USDT', parent_broker_id: 1 }
const SCHWAB = { id: 3, name: 'Schwab', currency: 'USD', parent_broker_id: null }
// NVDA en las dos patas de Cocos; AAPL en Cocos (dólares) y en Schwab.
const LOTE = { asset_type: 'CEDEAR', quantity: 5, buy_price: 10, invested: 50, entry_date: '2025-01-10', is_cash: 0 }
const POSICIONES = [
  { ...LOTE, id: 1, asset: 'NVDA', broker: 'Cocos', invested: 50000 },
  { ...LOTE, id: 2, asset: 'NVDA', broker: 'Cocos · USD' },
  { ...LOTE, id: 3, asset: 'AAPL', broker: 'Cocos · USD' },
  { ...LOTE, id: 4, asset: 'AAPL', broker: 'Schwab', asset_type: 'STOCK' },
]
const RESPUESTAS = {
  '/positions': () => POSICIONES,
  '/brokers': () => [COCOS, COCOS_USD, SCHWAB],
  '/dolar': () => ({ mep: { venta: 1555, compra: 1550 } }),
  '/prices': () => ({}),
  '/plazos-fijos': () => [],
  '/fundamentals/': () => ({ available: false }),
}
vi.mock('../../utils/api', async (orig) => ({
  ...(await orig()),
  api: {
    get: vi.fn((ruta) => {
      const k = Object.keys(RESPUESTAS).sort((a, b) => b.length - a.length).find(c => ruta.startsWith(c))
      return Promise.resolve(k ? RESPUESTAS[k]() : [])
    }),
  },
}))

let CarteraList, DetailPortfolioBlocks
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: CarteraList } = await import('./CarteraList'))
  ;({ default: DetailPortfolioBlocks } = await import('./DetailPortfolioBlocks'))
}, 60000)
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null })

async function dibujar(elemento) {
  const el = () => h(PrivacyProvider, null, elemento)
  montado = await montar(el())
  for (let i = 0; i < 8; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('Analizar: dónde tenés cada papel, por cuenta y no por pata', () => {
  it('la lista «Tu cartera»: NVDA en Cocos + Cocos · USD dice «Cocos»; AAPL dice «Cocos · Schwab»', async () => {
    const t = await dibujar(h(CarteraList, { onOpenTicker: () => {}, watchlist: { symbols: [] } }))
    expect(t).toContain('NVDACocos')            // ticker y debajo, su cuenta
    expect(t).toContain('AAPLCocos · Schwab')   // dos cuentas de verdad siguen siendo dos
    expect(t).not.toContain('Cocos · USD')
  })

  it('el detalle de NVDA: «Tenés 10 … en Cocos», no «en Cocos · Cocos · USD»', async () => {
    const data = { available: true, price: { current_usd: 180 }, metrics: {}, currency: 'USD' }
    const t = await dibujar(h(DetailPortfolioBlocks, { ticker: 'NVDA', data }))
    expect(t).toMatch(/Tenés 10 \S+ en Cocos/)
    expect(t).not.toContain('Cocos · USD')
  })
})
