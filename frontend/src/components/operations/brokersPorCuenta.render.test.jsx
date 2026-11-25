// El rótulo «broker(s)» de cada grupo en Movimientos, agrupado por activo, con
// la pantalla ENTERA montada (testing/navegadorMinimo.js) y el servidor simulado
// en la frontera (utils/api). Se monta la página y no la tabla suelta a
// propósito: la lista de brokers la pide Operations y se la pasa a las dos
// tablas; una prueba de la tabla sola daría verde aunque ese pase faltara.
//
// El error (25/11): «Cocos» y su pata en dólares «Cocos · USD» (hija vía
// `parent_broker_id`) se contaban como dos brokers. Un grupo con una compra en
// pesos y otra en dólares en Cocos decía «Cocos · Cocos · USD», y uno con
// Cocos + Cocos · USD + IOL decía «3 brokers». El criterio es el de Cartera:
// cuentas, no filas (utils/brokerAccounts.js, `cuentasDeLosNombres`).
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto } from '../../testing/navegadorMinimo'
import { PrivacyProvider } from '../../contexts/PrivacyContext'

vi.mock('../../contexts/CurrencyContext', async (orig) => ({
  ...(await orig()),
  useCurrency: () => ({ currency: 'USD', valuationDollar: 'mep', costBasis: 'purchase', tcValuacion: 1555 }),
  pickFinancialRate: (d) => d?.mep?.venta ?? null,
}))
vi.mock('../../hooks/useFxHistory', () => ({ useFxHistory: () => ({ getRateOrFallback: () => 1555, fxKey: 'k' }) }))
vi.mock('../../components/ai/AskAIAbout', () => ({ default: ({ children }) => children }))
vi.mock('../../components/ai/AnalyzeButton', () => ({ default: () => null }))
vi.mock('../../components/plan/ExportCsvButton', () => ({ default: () => null }))
vi.mock('../../components/FueraDeHorario', () => ({ ChipDelActivo: () => null }))
vi.mock('../../components/AssetLogo', () => ({ default: () => null }))
vi.mock('../../components/Toast', () => ({
  useToast: () => ({ push: () => {}, success: () => {}, error: () => {}, info: () => {} }),
}))

// La forma real de GET /api/brokers: la pata en dólares apunta al padre.
const BROKERS = [
  { id: 1, name: 'Cocos', currency: 'ARS', parent_broker_id: null },
  { id: 2, name: 'Cocos · USD', currency: 'USDT', parent_broker_id: 1 },
  { id: 3, name: 'IOL', currency: 'ARS', parent_broker_id: null },
  { id: 4, name: 'Schwab', currency: 'USD', parent_broker_id: null },
]

// Tres activos, cada uno con su caso:
//   GGAL — Cocos + Cocos · USD          → una cuenta: «Cocos»
//   AL30 — Cocos + Cocos · USD + IOL    → dos cuentas: «Cocos · IOL»
//   NVDA — Cocos · USD + IOL + Schwab   → tres cuentas de verdad: «3 brokers»
const CASOS = [['GGAL', 'Cocos'], ['GGAL', 'Cocos · USD'],
  ['AL30', 'Cocos'], ['AL30', 'Cocos · USD'], ['AL30', 'IOL'],
  ['NVDA', 'Cocos · USD'], ['NVDA', 'IOL'], ['NVDA', 'Schwab']]

// Movimientos con la forma de GET /api/movements (compras importadas).
const MOVS = CASOS.map(([asset, broker], i) => ({
  id: `op-${i + 1}`, ref_id: i + 1, kind: 'movement', type: 'BUY', asset, broker, date: '2026-11-10',
  quantity: 10, unit_price: 10, amount_usd: 100, fees_usd: 0, currency: 'USD', fx_to_usd: 1,
  source: 'import', transfer_out: false, notes: '', cobro: null,
}))
// Operaciones cerradas con la forma de GET /api/operations.
const OPS = CASOS.map(([asset, broker], i) => ({
  id: i + 1, asset, broker, op_type: 'Venta', date: '2026-11-10', quantity: 10,
  entry_price: 10, exit_price: 11, pnl_usd: 10, pnl_pct: 10, currency: 'USD',
}))

const RESPUESTAS = {
  '/brokers': () => BROKERS,
  '/dolar': () => ({ mep: { venta: 1555, compra: 1550 } }),
  '/operations': () => OPS,
  '/movements': () => MOVS,
}
vi.mock('../../utils/api', async (orig) => ({
  ...(await orig()),
  api: {
    get: vi.fn((ruta) => {
      const k = Object.keys(RESPUESTAS).sort((a, b) => b.length - a.length).find(c => ruta.startsWith(c))
      return Promise.resolve(k ? RESPUESTAS[k]() : [])
    }),
    post: vi.fn(() => Promise.resolve({ items: [] })),
    delete: vi.fn(() => Promise.resolve({})),
  },
}))

let Operations
beforeAll(async () => {
  instalarNavegadorMinimo()
  window.matchMedia = (q) => ({ matches: /reduce/.test(q), addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
  ;({ default: Operations } = await import('../../pages/Operations'))
}, 60000)
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null; localStorage.clear() })

// `pestana`: 'all' (Todos los movimientos, MovementsTable) o 'trades' (Solo
// P/L, TradesTable). Las dos agrupadas por activo, que es donde va el rótulo.
async function pantalla(pestana) {
  localStorage.setItem('rendi_operations_tab', pestana)
  localStorage.setItem('rendi_movements_group', 'asset')
  localStorage.setItem('rendi_trades_group', 'asset')
  const el = () => h(PrivacyProvider, null, h(MemoryRouter, { initialEntries: ['/operaciones'] },
    h(Routes, null, h(Route, { path: '/operaciones', element: h(Operations) }))))
  montado = await montar(el())
  for (let i = 0; i < 8; i++) await montado.redibujar(el())
  return montado.contenedor
}

// La celda «broker(s)» de la fila-resumen del grupo `activo`: la fila cuyo
// primer casillero es el botón del grupo (el que abre y cierra) con ese nombre.
function rotuloDelGrupo(raiz, activo) {
  const pila = [raiz]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'TR') {
      const celdas = (n.childNodes || []).filter(c => c.nodeName === 'TD')
      const boton = celdas[0]?.childNodes?.find(c => c.nodeName === 'BUTTON')
      if (boton && 'aria-expanded' in (boton.atributos || {}) && texto(boton).trim() === activo) {
        return texto(celdas[1]).trim()
      }
    }
    pila.push(...(n.childNodes || []))
  }
  return null
}

describe.each([
  ['Todos los movimientos', 'all'],
  ['Solo P/L (operaciones cerradas)', 'trades'],
])('Movimientos · %s, agrupado por activo: el rótulo cuenta cuentas, no patas', (_, pestana) => {
  it('Cocos + Cocos · USD dice «Cocos» (antes «Cocos · Cocos · USD»)', async () => {
    const raiz = await pantalla(pestana)
    expect(rotuloDelGrupo(raiz, 'GGAL')).toBe('Cocos')
  })

  it('Cocos + Cocos · USD + IOL dice «Cocos · IOL» (antes «3 brokers»)', async () => {
    const raiz = await pantalla(pestana)
    expect(rotuloDelGrupo(raiz, 'AL30')).toBe('Cocos · IOL')
  })

  it('tres cuentas de verdad siguen diciendo «3 brokers»', async () => {
    // Sin este caso, un rótulo que dijera siempre una sola cuenta pasaría las dos de arriba.
    const raiz = await pantalla(pestana)
    expect(rotuloDelGrupo(raiz, 'NVDA')).toBe('3 brokers')
    expect(texto(raiz)).not.toContain('Cocos · Cocos · USD')
  })
})
