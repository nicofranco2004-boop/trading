// La ficha de un activo, lo tengas o no (pedido de Nico, 22/10): desde el mapa
// de calor, los movers, la watchlist y el buscador de Mercado, un toque abre
// LA ficha (/activo/X) con el análisis técnico completo. Antes abrían un modal
// con un gráfico chico de 30 días (AssetQuickView, borrado).
//
// Se monta de verdad (testing/navegadorMinimo.js) con el router real y los
// pedidos al servidor simulados en la frontera (utils/api):
//   · cada lugar de Mercado, al tocarlo, termina en /activo/X;
//   · la ficha de algo que NO tenés: último precio, análisis técnico, la
//     estrella de la watchlist y la empresa, sin nada "tuyo";
//   · la de algo que tenés con otro nombre (GGAL.BA → GGAL) va a TU ficha;
//   · una acción argentina que no tenés se mira en BYMA (local=1, GGAL.BA).
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic, enActo, escribir, buscar } from '../testing/navegadorMinimo'

function puntos(n, f) {
  return Array.from({ length: n }, (_, i) => ({
    d: new Date(Date.UTC(2025, 0, 1) + i * 86400000).toISOString().slice(0, 10),
    c: f(i), s50: f(i) * 1.02, s200: f(i) * 1.05, rsi: 40,
  }))
}
const TECNICO = {
  disponible: true, moneda: 'usd', ticker: 'NVDA', convertida: null,
  puntos: puntos(504, i => 150 + i * 0.05),
  lectura: { ruedas: 760, fecha: '2026-10-21', precio: 175, media50: 170, dist_media50: 3,
    media200: 160, dist_media200: 9, pendiente_media200: 2, rsi: 58, dist_maximo_12m: -4, anio_completo: true },
}

let respuestas
vi.mock('../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => {
      const clave = Object.keys(respuestas).filter(k => ruta.startsWith(k)).sort((a, b) => b.length - a.length)[0]
      const r = clave ? respuestas[clave] : []
      return r instanceof Error ? Promise.reject(r) : Promise.resolve(typeof r === 'function' ? r(ruta) : r)
    }),
    post: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
  },
}))
vi.mock('../contexts/CurrencyContext', () => ({
  useCurrency: () => ({ valuationDollar: 'mep', costBasis: 'today', currency: 'USD' }),
  pickFinancialRate: () => 1500,
}))
vi.mock('../components/ai/AskAIAbout', () => ({ default: ({ children }) => children }))
vi.mock('../components/FueraDeHorario', () => ({ ChipDelActivo: () => null }))

let R, AssetDetail, Heatmap, Watchlist, MoversRail, SearchBar
beforeAll(async () => {
  instalarNavegadorMinimo()
  vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} })
  R = await import('react-router-dom')
  ;({ default: AssetDetail } = await import('./AssetDetail'))
  ;({ default: Heatmap } = await import('../components/home/Heatmap'))
  ;({ default: Watchlist } = await import('../components/home/Watchlist'))
  ;({ default: MoversRail } = await import('../components/home/MoversRail'))
  ;({ default: SearchBar } = await import('../components/home/SearchBar'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
})

// Dónde quedó el router: lo escribe en la pantalla un elemento escondido.
let donde = null
function Donde() {
  donde = R.useLocation().pathname
  return null
}
function app(inicio, pantalla) {
  return h(R.MemoryRouter, { initialEntries: [inicio] },
    h(R.Routes, null,
      h(R.Route, { path: '/activo/:ticker', element: h('div', null, h(AssetDetail), h(Donde)) }),
      h(R.Route, { path: '*', element: h('div', null, pantalla, h(Donde)) }),
    ))
}
async function abrir(inicio, pantalla = null) {
  const el = () => app(inicio, pantalla)
  montado = await montar(el())
  for (let i = 0; i < 6; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

function porAtributo(contenedor, k, v) {
  const pila = [contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.atributos?.[k] === v) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

const SIN_CARTERA = {
  '/positions': [], '/brokers': [], '/dolar': null, '/operations': [],
  '/watchlist': { items: [] },
}

describe('la ficha de un activo que no tenés', () => {
  it('muestra el precio, el análisis técnico, la watchlist y la empresa; nada tuyo', async () => {
    respuestas = {
      ...SIN_CARTERA,
      '/prices?symbols=NVDA': { NVDA: 182.4 },
      '/prices/prev-close?symbols=NVDA': { NVDA: 180 },
      '/tecnico/NVDA?moneda=usd': TECNICO,
    }
    const t = await abrir('/activo/NVDA')
    expect(t).toContain('Último precio')
    expect(t).toContain('182,40')
    expect(t).toContain('+1,3%')
    expect(t).toContain('Análisis técnico')
    expect(t).toContain('Largo plazo')
    expect(t).toContain('Agregar a tu watchlist')
    expect(t).toContain('Ver fundamentals de NVDA')
    // Nada que dependa de tus compras.
    expect(t).not.toContain('Contra lo que pagaste')
    expect(t).not.toContain('Tu precio promedio')
    expect(t).not.toContain('Tu operatoria')
    expect(t).not.toContain('No tenés movimientos')
    expect(donde).toBe('/activo/NVDA')
  })

  it('la estrella la agrega a la watchlist ahí mismo', async () => {
    const { api } = await import('../utils/api')
    api.post.mockClear()
    respuestas = { ...SIN_CARTERA, '/prices?symbols=NVDA': { NVDA: 182.4 }, '/tecnico/': TECNICO }
    await abrir('/activo/NVDA')
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Agregar a tu watchlist')))
    expect(api.post).toHaveBeenCalledWith('/watchlist', { symbol: 'NVDA' })
    expect(texto(montado.contenedor)).toContain('En tu watchlist')
  })

  it('una acción argentina que no tenés: precio en pesos y gráfico de BYMA', async () => {
    const { api } = await import('../utils/api')
    api.get.mockClear()
    respuestas = {
      ...SIN_CARTERA,
      '/prices?symbols=GGAL.BA': { 'GGAL.BA': 6250 },
      '/tecnico/': { ...TECNICO, ticker: 'GGAL.BA', convertida: 'mep' },
    }
    const t = await abrir('/activo/GGAL.BA')
    expect(t).toContain('6.250')
    expect(t).toContain('pesos')
    const pedidos = api.get.mock.calls.map(c => c[0])
    expect(pedidos).toContain('/tecnico/GGAL.BA?moneda=usd&local=1')
    expect(t).toContain('Ver fundamentals de GGAL')
  })

  it('si el servidor no pudo traer la historia, lo dice y muestra los 30 días', async () => {
    respuestas = {
      ...SIN_CARTERA, '/prices?symbols=ZZZZ': { ZZZZ: 3 },
      '/tecnico/': { disponible: false, motivo: 'tope' }, '/prices/history': { points: [] },
    }
    const t = await abrir('/activo/ZZZZ')
    expect(t).toContain('Probá de nuevo en un rato')
    expect(t).toContain('últimos 30 días')
  })

  it('si lo tenés con otro nombre (GGAL.BA → GGAL), va a TU ficha', async () => {
    respuestas = {
      '/positions': [{ id: 1, asset: 'GGAL', broker: 'IOL', quantity: 10, invested: 50000, currency: 'ARS', asset_type: 'ACCION', entry_date: '2025-05-01' }],
      '/brokers': [{ name: 'IOL', currency: 'ARS' }], '/dolar': null, '/operations': [],
      '/prices': { 'GGAL.BA': 6000 }, '/tecnico/': TECNICO,
    }
    const t = await abrir('/activo/GGAL.BA')
    expect(donde).toBe('/activo/GGAL')
    expect(t).toContain('Tu operatoria en GGAL')
    expect(t).not.toContain('Último precio')
  })
})

describe('Mercado: un toque abre la ficha del activo', () => {
  it('el mapa de calor (una cripto llega como BTC-USD y abre BTC)', async () => {
    respuestas = {
      ...SIN_CARTERA, '/tecnico/': TECNICO,
      '/home/heatmap': { blocks: [{ symbol: 'BTC-USD', name: 'Bitcoin', market_cap: 1000, change_pct: 1.2, price: 100000 }] },
    }
    await abrir('/', h(Heatmap, { defaultMarket: 'crypto' }))
    const celda = porAtributo(montado.contenedor, 'aria-label', 'BTC: ver detalle')
    expect(celda).toBeTruthy()
    await enActo(async () => clic(montado.contenedor, celda))
    expect(donde).toBe('/activo/BTC')
  })

  it('la watchlist', async () => {
    respuestas = { ...SIN_CARTERA, '/tecnico/': TECNICO,
      '/watchlist': { items: [{ symbol: 'MELI', price: 2000, change_pct: 1 }] } }
    await abrir('/', h(Watchlist))
    const fila = buscar(montado.contenedor, 'span')
    const meli = (function hallar(n) {
      if (n.nodeType === 1 && texto(n) === 'MELI') return n
      for (const c of n.childNodes || []) { const r = hallar(c); if (r) return r }
      return null
    })(montado.contenedor)
    expect(fila && meli).toBeTruthy()
    await enActo(async () => clic(montado.contenedor, meli))
    expect(donde).toBe('/activo/MELI')
  })

  it('los movers del día', async () => {
    respuestas = { ...SIN_CARTERA, '/tecnico/': TECNICO,
      '/home/movers': { gainers: [{ symbol: 'AMD', name: 'AMD', price: 150, change_pct: 5 }], losers: [] } }
    await abrir('/', h(MoversRail))
    const amd = (function hallar(n) {
      if (n.nodeType === 1 && n.nodeName === 'BUTTON' && texto(n).includes('AMD')) return n
      for (const c of n.childNodes || []) { const r = hallar(c); if (r) return r }
      return null
    })(montado.contenedor)
    expect(amd).toBeTruthy()
    await enActo(async () => clic(montado.contenedor, amd))
    expect(donde).toBe('/activo/AMD')
  })

  it('el buscador de Mercado, aunque no lo agregues a la watchlist', async () => {
    respuestas = { ...SIN_CARTERA, '/tecnico/': TECNICO }
    await abrir('/', h(SearchBar))
    const campo = buscar(montado.contenedor, 'input')
    await escribir(campo, 'NVDA')
    for (let i = 0; i < 3; i++) await montado.redibujar(app('/', h(SearchBar)))
    const fila = (function hallar(n) {
      if (n.nodeName === 'SPAN' && texto(n) === 'NVDA') return n
      for (const c of n.childNodes || []) { const r = hallar(c); if (r) return r }
      return null
    })(montado.contenedor)
    expect(fila).toBeTruthy()
    await enActo(async () => clic(montado.contenedor, fila))
    expect(donde).toBe('/activo/NVDA')
  })
})
