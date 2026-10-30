// «Ocultar saldos» (el ojito de la Cartera) tiene que esconder TU plata en todas
// las pantallas donde aparece. Criterio, el de la Cartera (Positions.jsx): se
// esconden los montos (lo que vale, lo invertido, lo ganado o perdido en plata)
// y qué parte de tu cartera es; quedan a la vista los precios del mercado, las
// cantidades y los % de rendimiento.
//
// POR QUÉ ESTE TEST
// ─────────────────
// Auditorías A3 y D4 (29/10): con el ojito prendido, la ficha mostraba «Valor
// actual $5.305 +$2.355», «En tu cartera −US$ 146 · Es el 61 % de tu cartera» y
// «Tu operatoria» entera; Movimientos, cada P&L y cada depósito. Causa de
// proceso: «se esconde con Ocultar saldos» no es una regla de la app sino algo
// que cada pantalla tiene que pedir a mano (usePrivacy), y ninguna prueba mira
// las pantallas que se olvidan. Las de Tu lista y Señales lo miraban; la ficha
// y Movimientos, no.
//
// Cómo: cada pantalla ENTERA, montada (testing/navegadorMinimo.js), con el
// ojito prendido como lo guarda la app (localStorage.rendi_privacy = '1' y el
// PrivacyProvider de verdad) y el servidor simulado en la frontera (utils/api).
// Los datos traen montos fáciles de reconocer; si alguno aparece, está a la
// vista. Y el precio del mercado tiene que seguir apareciendo: una pantalla que
// esconde TODO también pasaría «no muestra montos».
//
// El censo de las pantallas que traen tu plata y todavía no miran el ojito
// está en ocultar-saldos-censo.test.js.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto, clic, buscarBoton } from '../testing/navegadorMinimo'
import { PrivacyProvider } from '../contexts/PrivacyContext'

vi.mock('../contexts/CurrencyContext', async (orig) => ({
  ...(await orig()),
  useCurrency: () => ({ currency: 'USD', valuationDollar: 'mep', costBasis: 'purchase', tcValuacion: 1555 }),
  pickFinancialRate: (d) => d?.mep?.venta ?? null,
}))
vi.mock('../hooks/useFxHistory', () => ({ useFxHistory: () => ({ getRateOrFallback: () => 1555, fxKey: 'k' }) }))
vi.mock('../components/ai/AskAIAbout', () => ({ default: ({ children }) => children }))
vi.mock('../components/ai/AnalyzeButton', () => ({ default: () => null }))
vi.mock('../components/plan/ExportCsvButton', () => ({ default: () => null }))
vi.mock('../components/FueraDeHorario', () => ({ ChipDelActivo: () => null }))
vi.mock('../components/AssetLogo', () => ({ default: () => null }))
vi.mock('../components/Toast', () => ({ useToast: () => ({ success: () => {}, error: () => {}, info: () => {} }) }))

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
// Una venta vieja de NVDA (P&L 777,77) y un depósito de 4.321: montos raros a propósito.
const OPS = [{ id: 7, asset: 'NVDA', broker: 'Schwab', op_type: 'Venta', date: '2025-06-02', entry_date: '2024-12-10',
  quantity: 3, entry_price: 118, exit_price: 377.26, pnl_usd: 777.77, pnl_pct: 219.7, currency: 'USD', fx_to_usd: 1 }]
const MOVS = [{ id: 1, type: 'DEPOSIT', asset: null, broker: 'Schwab', date: '2025-01-05', amount_usd: 4321, amount: 4321,
  currency: 'USD', fx_to_usd: 1 }]
const RESPUESTAS = {
  '/positions': () => [{ id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 25, buy_price: 118,
    invested: 2950, entry_date: '2024-12-10', is_cash: 0 }],
  '/brokers': () => [{ id: 1, name: 'Schwab', currency: 'USD' }],
  '/dolar': () => ({ mep: { venta: 1555, compra: 1550 } }),
  '/operations': () => OPS,
  '/movements': () => MOVS,
  '/prices': () => ({ NVDA: 212.21 }),
  '/tesis': () => [],
  '/tecnico/NVDA/eventos': () => ({ empresa: 'NVDA', eventos: [] }),
  '/tecnico/NVDA/peso': () => ({ peso: 0.61 }),
  '/tecnico/NVDA': () => TECNICO,
}
vi.mock('../utils/api', async (orig) => ({
  ...(await orig()),
  api: {
    get: vi.fn((ruta) => {
      const k = Object.keys(RESPUESTAS).find(c => ruta.startsWith(c))
      return Promise.resolve(k ? RESPUESTAS[k]() : [])
    }),
    post: vi.fn(() => Promise.resolve({ items: [] })),
  },
}))

let AssetDetail, Operations
beforeAll(async () => {
  instalarNavegadorMinimo()
  // Movimientos pregunta el ancho (useIsMobile) y si se reducen las animaciones:
  // con «reducir», los números aparecen enteros (sin contar desde 0).
  window.matchMedia = (q) => ({ matches: /reduce/.test(q), addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
  ;({ default: AssetDetail } = await import('../pages/AssetDetail'))
  ;({ default: Operations } = await import('../pages/Operations'))
}, 60000)
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null; localStorage.clear() })

async function pantalla(Componente, ruta, patron, ojito) {
  localStorage.setItem('rendi_privacy', ojito ? '1' : '0')
  const el = () => h(PrivacyProvider, null, h(MemoryRouter, { initialEntries: [ruta] },
    h(Routes, null, h(Route, { path: patron, element: h(Componente) }))))
  montado = await montar(el())
  for (let i = 0; i < 8; i++) await montado.redibujar(el())
  return { el, leer: () => texto(montado.contenedor) }
}

// Lo que vale lo tuyo en la ficha: 25 × 212,21 = 5.305; ganancia 2.355; invertido
// 2.950; un día malo te mueve 146; es el 61 % y a la cartera la mueve 1,7 %.
const PLATA_FICHA = ['5.305', '2.355', '2.950', 'US$ 146', '61%', '1,7%', '778']

describe('A3/D4 · «Ocultar saldos» en la ficha', () => {
  it('apagado, la plata se ve (si no, la prueba no prueba nada)', async () => {
    const t = (await pantalla(AssetDetail, '/activo/NVDA', '/activo/:ticker', false)).leer()
    for (const m of ['5.305', '2.355', '2.950', 'US$ 146', '61%']) expect(t, m).toContain(m)
  })

  it('prendido, no se ve ningún monto tuyo ni tu peso; el precio, la cantidad y el % sí', async () => {
    const t = (await pantalla(AssetDetail, '/activo/NVDA', '/activo/:ticker', true)).leer()
    for (const m of PLATA_FICHA) expect(t, m).not.toContain(m)
    expect(t).toContain('$118,00')          // costo promedio por unidad (la Cartera también lo deja)
    expect(t).toContain('Cantidad25')
    expect(t).toContain('+79,8%')           // el % de rendimiento, como en la Cartera
    expect(t).toContain('••••••')
  })
})

describe('A3/D4 · «Ocultar saldos» en Movimientos', () => {
  it('apagado, el depósito y el P&L se ven', async () => {
    const p = await pantalla(Operations, '/operaciones', '/operaciones', false)
    expect(p.leer()).toContain('4.321')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Solo P/L'))
    for (let i = 0; i < 6; i++) await montado.redibujar(p.el())
    expect(p.leer()).toContain('777,77')
  })

  it('prendido, ni el depósito ni el P&L en plata; los % sí', async () => {
    const p = await pantalla(Operations, '/operaciones', '/operaciones', true)
    expect(p.leer()).not.toContain('4.321')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Solo P/L'))
    for (let i = 0; i < 6; i++) await montado.redibujar(p.el())
    const t = p.leer()
    expect(t).not.toContain('777,77')
    expect(t).not.toContain('777,8')
    expect(t).not.toContain('778')
    // Los % se ven, como en la Cartera (la tabla abre agrupada por activo: el
    // precio de cada venta queda adentro del grupo).
    expect(t).toContain('Win rate100%')
    expect(t).toContain('••••••')
  })
})
