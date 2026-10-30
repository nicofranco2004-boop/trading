// La ficha del activo ANTES y DESPUÉS de sacar sus cuentas a un lugar
// compartido (hooks/useFichaDelActivo.js), para que la pestaña «Gráfico» de
// Análisis técnico arme el gráfico con la MISMA cuenta que la ficha.
// ════════════════════════════════════════════════════════════════════════════
// Las fotos de `__snapshots__/` se sacaron con la ficha de antes (punta
// 9958c9b0, sin tocar): lo que la ficha le pasa al gráfico técnico y todo el
// texto que se ve, en nueve casos (un papel de EE.UU., una acción argentina en
// un broker en pesos, un CEDEAR en un broker en pesos, uno pagado en pesos en
// una cuenta en dólares y uno comprado en dólares, una cripto en un exchange,
// un activo que no tenés, uno que vendiste entero y uno pedido con otro
// nombre). Si una foto
// cambia, la ficha cambió: no se regenera, se busca qué se rompió.
//
// La ficha entera montada (testing/navegadorMinimo.js) con los pedidos al
// servidor simulados en la frontera (utils/api), como en
// AssetDetail.render.test.jsx. El gráfico se reemplaza por uno que anota lo
// que recibe: lo que importa acá es qué le llega, no cómo se dibuja.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto } from '../testing/navegadorMinimo'

vi.mock('../contexts/CurrencyContext', () => ({
  useCurrency: () => ({ currency: 'USD', valuationDollar: 'mep', costBasis: 'purchase', tcValuacion: 1555 }),
  pickFinancialRate: (d) => d?.mep?.venta ?? null,
}))
vi.mock('../components/ai/AskAIAbout', () => ({ default: ({ children }) => children }))
vi.mock('../components/FueraDeHorario', () => ({ ChipDelActivo: () => null }))
vi.mock('../components/AssetLogo', () => ({ default: () => null }))
vi.mock('../components/fundamentals/AnalyzeView', () => ({ default: () => null }))
vi.mock('../components/asset/LiquidezByma', () => ({ default: ({ papel }) => `[liquidez ${papel}]` }))

const recibido = []
vi.mock('../components/asset/LecturaTecnica', () => ({
  default: (props) => { recibido.push(props); return `[gráfico ${props.asset}]` },
}))

const DOLAR = { mep: { venta: 1555, compra: 1550 }, cripto: { venta: 1580 } }
const CASOS = {
  'papel de EE.UU. en un broker en dólares': {
    ruta: '/activo/NVDA',
    positions: [{ id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 25, buy_price: 118,
      invested: 2950, commissions: 4, entry_date: '2024-12-10', is_cash: 0 }],
    brokers: [{ id: 1, name: 'Schwab', currency: 'USD' }],
    operations: [{ id: 9, broker: 'Schwab', asset: 'NVDA', type: 'SELL', date: '2025-03-01', quantity: 5, pnl_usd: 120 }],
    prices: { NVDA: 212.21 },
    peso: { peso: 0.31 },
  },
  'acción argentina en un broker en pesos': {
    ruta: '/activo/GGAL',
    positions: [
      { id: 2, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION_AR', quantity: 100, buy_price: 5200,
        invested: 520000, currency: 'ARS', tc_compra: 1200, entry_date: '2025-01-15', is_cash: 0 },
      { id: 3, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION_AR', quantity: 50, buy_price: 6100,
        invested: 305000, currency: 'ARS', entry_date: '2025-06-02', is_cash: 0 },
    ],
    brokers: [{ id: 2, name: 'IOL', currency: 'ARS' }],
    operations: [],
    prices: { 'GGAL.BA': 6420 },
    peso: { peso: 0.12 },
  },
  'CEDEAR en un broker en pesos': {
    ruta: '/activo/AAPL',
    positions: [{ id: 4, broker: 'Balanz', asset: 'AAPL', asset_type: 'CEDEAR', quantity: 40, buy_price: 14000,
      invested: 560000, currency: 'ARS', tc_compra: 1180, entry_date: '2025-02-20', is_cash: 0 }],
    brokers: [{ id: 3, name: 'Balanz', currency: 'ARS' }],
    operations: [],
    prices: { 'AAPL.BA': 18200 },
    peso: { peso: 0.2 },
  },
  'CEDEAR pagado en pesos en una cuenta en dólares': {
    ruta: '/activo/MSFT',
    positions: [{ id: 6, broker: 'IOL · USD', asset: 'MSFT', asset_type: 'CEDEAR', quantity: 30, buy_price: 21000,
      invested: 630000, currency: 'ARS', tc_compra: 1210, entry_date: '2025-03-11', is_cash: 0 }],
    brokers: [{ id: 5, name: 'IOL · USD', currency: 'USD' }],
    operations: [],
    prices: { 'MSFT.BA': 24500 },
    peso: { peso: 0.15 },
  },
  'CEDEAR comprado en dólares': {
    ruta: '/activo/KO',
    positions: [{ id: 7, broker: 'IOL · USD', asset: 'KO', asset_type: 'CEDEAR', quantity: 60, buy_price: 11,
      invested: 660, currency: 'USD', entry_date: '2025-04-01', is_cash: 0 }],
    brokers: [{ id: 5, name: 'IOL · USD', currency: 'USD' }],
    operations: [],
    prices: { 'KO.BA': 17800 },
    peso: { peso: 0.05 },
  },
  'cripto en un exchange': {
    ruta: '/activo/BTC',
    positions: [{ id: 5, broker: 'Binance', asset: 'BTC', asset_type: 'CRYPTO', quantity: 0.05, buy_price: 60000,
      invested: 3000, entry_date: '2024-11-01', is_cash: 0 }],
    brokers: [{ id: 4, name: 'Binance', currency: 'USD', is_exchange: 1 }],
    operations: [],
    prices: { BTC: 71000 },
    peso: { peso: 0.08 },
  },
  'activo que no tenés': {
    ruta: '/activo/MELI',
    positions: [],
    brokers: [{ id: 1, name: 'Schwab', currency: 'USD' }],
    operations: [],
    prices: { MELI: 1990 },
    prevClose: { MELI: 1960 },
    watchlist: { items: [{ symbol: 'MELI' }] },
    peso: null,
  },
  'activo que vendiste entero': {
    ruta: '/activo/YPFD',
    positions: [],
    brokers: [{ id: 2, name: 'IOL', currency: 'ARS' }],
    operations: [
      { id: 10, broker: 'IOL', asset: 'YPFD', type: 'BUY', date: '2025-01-03', quantity: 10, price: 30000 },
      { id: 11, broker: 'IOL', asset: 'YPFD', type: 'SELL', date: '2025-05-03', quantity: 10, price: 36000, pnl_usd: 41 },
    ],
    prices: {},
    peso: { peso: null },
  },
  'pedido con otro nombre (GGAL.BA, lo tenés como GGAL)': {
    ruta: '/activo/GGAL.BA',
    positions: [{ id: 2, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION_AR', quantity: 100, buy_price: 5200,
      invested: 520000, currency: 'ARS', tc_compra: 1200, entry_date: '2025-01-15', is_cash: 0 }],
    brokers: [{ id: 2, name: 'IOL', currency: 'ARS' }],
    operations: [],
    prices: { 'GGAL.BA': 6420 },
    peso: { peso: 0.12 },
  },
}

let caso
vi.mock('../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => {
      const c = caso
      const r = ruta.startsWith('/positions') ? c.positions
        : ruta.startsWith('/brokers') ? c.brokers
          : ruta.startsWith('/dolar') ? DOLAR
            : ruta.startsWith('/operations') ? c.operations
              : ruta.startsWith('/prices/prev-close') ? (c.prevClose || {})
                : ruta.startsWith('/prices') ? c.prices
                  : ruta.startsWith('/watchlist') ? (c.watchlist || { items: [] })
                    : /^\/tecnico\/[^/]+\/peso/.test(ruta) ? c.peso
                      : []
      return Promise.resolve(r)
    }),
  },
}))

let AssetDetail
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: AssetDetail } = await import('./AssetDetail'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null })

async function ficha(nombre) {
  caso = CASOS[nombre]
  recibido.length = 0
  const el = () => h(MemoryRouter, { initialEntries: [caso.ruta] },
    h(Routes, null, h(Route, { path: '/activo/:ticker', element: h(AssetDetail) })))
  montado = await montar(el())
  for (let i = 0; i < 10; i++) await montado.redibujar(el())
  // Lo último que recibió el gráfico (las cargas intermedias no importan: la
  // ficha muestra un esqueleto hasta tener todo).
  return { alGrafico: recibido.at(-1) ?? null, texto: texto(montado.contenedor) }
}

describe('la ficha del activo, antes y después de compartir sus cuentas', () => {
  for (const nombre of Object.keys(CASOS)) {
    it(nombre, async () => {
      const { alGrafico, texto: t } = await ficha(nombre)
      expect(alGrafico).not.toBeNull()
      expect(alGrafico).toMatchSnapshot('lo que recibe el gráfico técnico')
      expect(t).toMatchSnapshot('todo el texto de la ficha')
    })
  }
})
