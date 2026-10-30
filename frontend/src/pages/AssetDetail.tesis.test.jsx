// La tesis en la ficha, por el nombre del papel (auditorías B y D, 29/10).
// · Vendiste GGAL en IOL y la seguís como «GGAL.BA»: Señales abre
//   /activo/GGAL.BA, la ficha te lleva a /activo/GGAL (la regla «es el mismo
//   papel», esElMismo) y ahí está tu tesis.
// · Pero AGRO (Adecoagro, Nueva York) y AGRO.BA (Agrometal, BYMA) son empresas
//   distintas: la tesis de una no puede aparecer en la ficha de la otra. Una
//   primera versión de este arreglo le sacaba el «.BA» al nombre y las mezclaba.
// La ficha ENTERA montada, con el servidor simulado en la frontera.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto } from '../testing/navegadorMinimo'

vi.mock('../contexts/CurrencyContext', async (orig) => ({
  ...(await orig()),
  useCurrency: () => ({ currency: 'USD', valuationDollar: 'mep', costBasis: 'purchase', tcValuacion: 1555 }),
  pickFinancialRate: (d) => d?.mep?.venta ?? null,
}))
vi.mock('../components/ai/AskAIAbout', () => ({ default: ({ children }) => children }))
vi.mock('../components/FueraDeHorario', () => ({ ChipDelActivo: () => null }))
vi.mock('../components/AssetLogo', () => ({ default: () => null }))

const TESIS = { items: [
  { id: 3, asset: 'GGAL', texto: 'Bancos baratos con tasas bajando', escrita_el: '2026-03-02',
    tendencia: { tendencia: 'alcista' }, accion_local: 1, recordatorio: null },
  { id: 4, asset: 'AGRO', texto: 'Tesis de Adecoagro, la de Nueva York', escrita_el: '2026-03-02',
    tendencia: { tendencia: 'alcista' }, accion_local: 0, recordatorio: null }], hoy: {} }
// Vendiste GGAL en IOL (pesos): sin lotes, con su operación.
const OPS = [{ id: 1, asset: 'GGAL', broker: 'IOL', currency: 'ARS', op_type: 'Venta', date: '2026-06-01',
  entry_date: '2026-01-10', quantity: 10, entry_price: 5000, exit_price: 6000, pnl_usd: 7, pnl_pct: 20, fx_to_usd: 1400 }]
let pedidosDeTendencia = []
vi.mock('../utils/api', async (orig) => ({
  ...(await orig()),
  api: {
    get: vi.fn((ruta) => Promise.resolve(
      ruta.startsWith('/tesis') ? TESIS
        : ruta.startsWith('/tecnico/') ? { disponible: false, motivo: 'sin_velas' }
          : ruta.startsWith('/operations') ? OPS
          : ruta.startsWith('/brokers') ? [{ id: 1, name: 'IOL', currency: 'ARS' }]
          : ruta.startsWith('/dolar') ? { mep: { venta: 1555, compra: 1550 } } : [])),
    post: vi.fn((ruta, body) => { pedidosDeTendencia.push(body); return Promise.resolve({}) }),
  },
}))

let AssetDetail
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: AssetDetail } = await import('./AssetDetail'))
}, 120000)
afterAll(() => { vi.unstubAllGlobals() })
let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null })

async function ficha(ruta) {
  const el = () => h(MemoryRouter, { initialEntries: [ruta] },
    h(Routes, null, h(Route, { path: '/activo/:ticker', element: h(AssetDetail) })))
  montado = await montar(el())
  for (let i = 0; i < 8; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('la tesis en la ficha, por el nombre del papel', () => {
  it('GGAL vendida en IOL: /activo/GGAL.BA te lleva a tu ficha de GGAL, con tu tesis', async () => {
    expect(await ficha('/activo/GGAL.BA')).toContain('Bancos baratos con tasas bajando')
  }, 120000)
  it('la tesis de Adecoagro (AGRO) NO aparece en la ficha de Agrometal (AGRO.BA)', async () => {
    expect(await ficha('/activo/AGRO.BA')).not.toContain('Tesis de Adecoagro')
  }, 120000)
  it('y sí en la de Adecoagro (AGRO)', async () => {
    expect(await ficha('/activo/AGRO')).toContain('Tesis de Adecoagro')
  }, 120000)
})
