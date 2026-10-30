// La tesis en la ficha de una acción argentina que se sigue desde la watchlist
// (auditoría B, re-test 29/10): vendiste GGAL, la seguís como «GGAL.BA»,
// Señales dice «Revisar tu tesis» y el botón abre /activo/GGAL.BA… que no la
// mostraba. La tesis se guarda con el nombre del papel de tus operaciones
// («GGAL»); la ficha la buscaba como «GGAL.BA» y decidía «acción argentina»
// sólo por tus lotes (vendida, no hay). La ficha ENTERA montada, con el
// servidor simulado en la frontera.
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

const TESIS = { items: [{ id: 3, asset: 'GGAL', texto: 'Bancos baratos con tasas bajando', escrita_el: '2026-03-02',
  tendencia: { tendencia: 'alcista' }, accion_local: 1, recordatorio: null }], hoy: {} }
let pedidosDeTendencia = []
vi.mock('../utils/api', async (orig) => ({
  ...(await orig()),
  api: {
    get: vi.fn((ruta) => Promise.resolve(
      ruta.startsWith('/tesis') ? TESIS
        : ruta.startsWith('/tecnico/') ? { disponible: false, motivo: 'sin_velas' }
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

describe('la tesis en la ficha de lo que seguís (GGAL vendida, seguida como GGAL.BA)', () => {
  it('/activo/GGAL.BA muestra tu tesis de GGAL', async () => {
    expect(await ficha('/activo/GGAL.BA')).toContain('Bancos baratos con tasas bajando')
  }, 120000)
  it('/activo/GGAL también', async () => {
    expect(await ficha('/activo/GGAL')).toContain('Bancos baratos con tasas bajando')
  }, 120000)
})
