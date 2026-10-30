// La ficha del activo ENTERA, montada (testing/navegadorMinimo.js), con los
// pedidos al servidor simulados en la frontera (utils/api): que lo que vale tu
// tenencia (la cuenta de la ficha) y qué parte de tu cartera es (la cuenta del
// servidor, GET /api/tecnico/{activo}/peso: la misma de Tu lista y de Señales)
// lleguen hasta «En tu cartera» de «Cuánto se mueve este activo». Las cuentas
// del servidor se prueban en backend/tests/test_movimiento.py y, el peso, en
// backend/tests/test_tus_senales.py.
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

const puntos = Array.from({ length: 700 }, (_, i) => {
  const d = new Date(Date.UTC(2024, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  return { d, c: 150 + i * 0.1, s50: null, s200: null, rsi: 50 }
})
const TECNICO = {
  disponible: true, moneda: 'usd', ticker: 'NVDA', convertida: null, puntos,
  lectura: { ruedas: 700, fecha: puntos[699].d, precio: puntos[699].c, rsi: 50 },
  movimiento: {
    disponible: true, desde: '2024-09-01', hasta: puntos[699].d, peor_caida: null,
    dia_normal: { desvio_pct: 2.76, dias: 699, dias_malos: 66, sp500_desvio_pct: 1.02, veces_el_sp500: 2.7 },
    desde_el_maximo: null,
  },
}
let peso
const RESPUESTAS = {
  '/positions': () => [{ id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 25, buy_price: 118,
    invested: 2950, entry_date: '2024-12-10', is_cash: 0 }],
  '/brokers': () => [{ id: 1, name: 'Schwab', currency: 'USD' }],
  '/dolar': () => ({ mep: { venta: 1555, compra: 1550 } }),
  '/operations': () => [],
  '/prices': () => ({ NVDA: 212.21 }),
  '/tecnico/NVDA/eventos': () => ({ empresa: 'NVDA', eventos: [] }),
  '/tecnico/NVDA/peso': () => peso,
  '/tecnico/NVDA': () => TECNICO,
}
vi.mock('../utils/api', () => ({
  // La copia de los dibujos es de la persona y la cuenta (utils/duenoDeLaPestana).
  getClientContext: () => null,
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
  api: {
    get: vi.fn((ruta) => {
      const k = Object.keys(RESPUESTAS).find(c => ruta.startsWith(c))
      return Promise.resolve(k ? RESPUESTAS[k]() : [])
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

async function ficha() {
  const el = () => h(MemoryRouter, { initialEntries: ['/activo/NVDA'] },
    h(Routes, null, h(Route, { path: '/activo/:ticker', element: h(AssetDetail) })))
  montado = await montar(el())
  for (let i = 0; i < 8; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('ficha del activo: «En tu cartera»', () => {
  it('lo tuyo por el día malo normal, y qué parte de tu cartera es', async () => {
    // El % lo manda el servidor: la ficha no lo calcula (antes dividía lo tuyo
    // de hoy por la última foto y decía otro % que Tu lista).
    peso = { peso: 0.61 }
    const t = await ficha()
    // 25 × US$ 212,21 = US$ 5.305; × 2,76 % = US$ 146.
    expect(t).toContain('Cuánto se mueve este activo')
    expect(t).toContain('−US$ 146')
    expect(t).toContain('Es el 61% de tu cartera')
  })

  it('si el servidor no sabe el %, la plata sí y el % de tu cartera no', async () => {
    peso = { peso: null }
    const t = await ficha()
    expect(t).toContain('−US$ 146')
    expect(t).not.toContain('de tu cartera')
  })
})
