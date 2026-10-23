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
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic, enActo, escribir, buscar, tecla } from '../testing/navegadorMinimo'

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

// Dónde quedó el router, y cómo moverlo (como el ⌘K, que está en toda la app).
let donde = null
let navegar = null
function Donde() {
  donde = R.useLocation().pathname
  navegar = R.useNavigate()
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
  // Sin empresa en el pedido: la ficha no muestra el análisis fundamental.
  '/fundamentals/': { available: false },
}

// Lo que contesta /api/fundamentals/{ticker} (el contrato de "Calidad de cartera").
const FUNDAMENTALES = (ticker, nombre) => ({
  available: true, ticker, company_name: nombre, sector: 'Technology', currency: 'USD',
  score: { categories: [
    { key: 'valuation', score: 40 }, { key: 'growth', score: 85 },
    { key: 'profitability', score: 90 }, { key: 'health', score: 80 },
  ] },
  categories_detail: [{ key: 'growth', label: 'Crecimiento', question: '¿Crece?', score: 85, metrics: [] }],
  price: { current_usd: 182.4 }, metrics: { market_cap_usd: 4.4e12, trailing_pe: 45 },
})

describe('la ficha de un activo que no tenés', () => {
  it('muestra el precio, el análisis técnico, la watchlist y la empresa; nada tuyo', async () => {
    respuestas = {
      ...SIN_CARTERA,
      '/prices?symbols=NVDA': { NVDA: 182.4 },
      '/prices/prev-close?symbols=NVDA': { NVDA: 180 },
      '/tecnico/NVDA?moneda=usd': TECNICO,
      '/fundamentals/NVDA': FUNDAMENTALES('NVDA', 'NVIDIA Corporation'),
    }
    const t = await abrir('/activo/NVDA')
    expect(t).toContain('Último precio')
    expect(t).toContain('182,40')
    expect(t).toContain('+1,3%')
    expect(t).toContain('Análisis técnico')
    expect(t).toContain('Largo plazo')
    expect(t).toContain('Agregar a la watchlist')
    // El análisis fundamental, adentro de la ficha y DEBAJO del técnico.
    expect(t).toContain('Análisis fundamental')
    expect(t.indexOf('Análisis fundamental')).toBeGreaterThan(t.indexOf('Largo plazo'))
    expect(t).toContain('NVIDIA Corporation')
    expect(t).toContain('El negocio')
    expect(t).toContain('Sólido')
    expect(t).toContain('El precio hoy')
    expect(t).toContain('Caro')
    expect(t).toContain('Compararla en Calidad de cartera')
    expect(t).not.toContain('Ver fundamentals de')
    const link = porAtributo(montado.contenedor, 'href', '/fundamentals?ticker=NVDA')
    expect(link).toBeTruthy()
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
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Agregar a la watchlist')))
    expect(api.post).toHaveBeenCalledWith('/watchlist', { symbol: 'NVDA' })
    expect(texto(montado.contenedor)).toContain('En la watchlist')
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
    // La empresa de GGAL.BA es GGAL (su ADR): ésa se pide para el fundamental.
    expect(pedidos).toContain('/fundamentals/GGAL')
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

  it('el buscador de Mercado: Enter abre la ficha (no agrega a la watchlist)', async () => {
    const { api } = await import('../utils/api')
    api.post.mockClear()
    respuestas = { ...SIN_CARTERA, '/tecnico/': TECNICO }
    await abrir('/', h(SearchBar))
    const campo = buscar(montado.contenedor, 'input')
    await escribir(campo, 'NVDA')
    for (let i = 0; i < 3; i++) await montado.redibujar(app('/', h(SearchBar)))
    await tecla(campo, 'Enter')
    expect(donde).toBe('/activo/NVDA')
    expect(api.post).not.toHaveBeenCalled()
  })

  it('el buscador de Mercado: un bono que no tenés no abre una ficha vacía', async () => {
    respuestas = { ...SIN_CARTERA }
    await abrir('/', h(SearchBar))
    const campo = buscar(montado.contenedor, 'input')
    await escribir(campo, 'AL30')
    for (let i = 0; i < 3; i++) await montado.redibujar(app('/', h(SearchBar)))
    const fila = (function hallar(n) {
      if (n.nodeName === 'SPAN' && texto(n) === 'AL30') return n
      for (const c of n.childNodes || []) { const r = hallar(c); if (r) return r }
      return null
    })(montado.contenedor)
    expect(fila).toBeTruthy()
    await enActo(async () => clic(montado.contenedor, fila))
    expect(donde).toBe('/')
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

describe('lo que encontró la auditoría (22/10)', () => {
  it('si cambiás de activo mientras carga, la respuesta vieja no pisa la ficha nueva', async () => {
    let soltar
    const lenta = new Promise(r => { soltar = r })
    let primera = true
    respuestas = {
      ...SIN_CARTERA,
      '/positions': () => { if (primera) { primera = false; return lenta } return [] },
      '/prices?symbols=AAPL': { AAPL: 255.55 }, '/prices?symbols=NVDA': { NVDA: 182.4 },
      '/watchlist': { items: [{ symbol: 'AAPL' }] }, '/tecnico/': TECNICO,
    }
    const el = () => app('/activo/AAPL', null)
    montado = await montar(el())
    await enActo(async () => navegar('/activo/NVDA'))
    for (let i = 0; i < 4; i++) await montado.redibujar(el())
    await enActo(async () => soltar([]))
    for (let i = 0; i < 4; i++) await montado.redibujar(el())
    const t = texto(montado.contenedor)
    expect(donde).toBe('/activo/NVDA')
    expect(t).toContain('182,40')
    expect(t).not.toContain('255,55')
    expect(t).toContain('Agregar a la watchlist')       // AAPL está en la lista; NVDA no
  })

  it('la estrella guarda el instrumento que muestra la ficha (Agrometal, no Adecoagro)', async () => {
    const { api } = await import('../utils/api')
    api.post.mockClear()
    respuestas = { ...SIN_CARTERA, '/prices?symbols=AGRO.BA': { 'AGRO.BA': 900 }, '/tecnico/': TECNICO,
      '/watchlist': { items: [{ symbol: 'AGRO' }] } }      // AGRO a secas = Adecoagro: otra cosa
    const t = await abrir('/activo/AGRO')
    expect(t).toContain('pesos')
    expect(t).toContain('Agregar a la watchlist')
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Agregar a la watchlist')))
    expect(api.post).toHaveBeenCalledWith('/watchlist', { symbol: 'AGRO.BA' })
  })

  it('si la watchlist no acepta el símbolo, lo dice en la pantalla', async () => {
    const { api } = await import('../utils/api')
    api.post.mockImplementationOnce(() => Promise.reject(Object.assign(new Error('Tu lista llegó a 100 activos'), { status: 400 })))
    respuestas = { ...SIN_CARTERA, '/prices?symbols=NVDA': { NVDA: 182.4 }, '/tecnico/': TECNICO }
    await abrir('/activo/NVDA')
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Agregar a la watchlist')))
    expect(texto(montado.contenedor)).toContain('Tu lista llegó a 100 activos')
  })

  it('BRK-B del mapa del S&P lleva a tu Berkshire aunque lo tengas como BRK.B', async () => {
    respuestas = {
      '/positions': [{ id: 3, asset: 'BRK.B', broker: 'Schwab', quantity: 2, invested: 900, currency: 'USD', asset_type: 'STOCK', entry_date: '2025-05-01' }],
      '/brokers': [{ name: 'Schwab', currency: 'USD' }], '/dolar': null, '/operations': [],
      '/prices': { 'BRK-B': 480 }, '/tecnico/': TECNICO,
    }
    await abrir('/activo/BRK-B')
    expect(donde).toBe('/activo/BRK.B')
  })

  it('GGAL.BA no te lleva a tu ADR de Schwab: es otro instrumento', async () => {
    respuestas = {
      '/positions': [{ id: 4, asset: 'GGAL', broker: 'Schwab', quantity: 5, invested: 250, currency: 'USD', asset_type: 'STOCK', entry_date: '2025-05-01' }],
      '/brokers': [{ name: 'Schwab', currency: 'USD' }], '/dolar': null, '/operations': [],
      '/watchlist': { items: [] }, '/prices?symbols=GGAL.BA': { 'GGAL.BA': 6250 }, '/tecnico/': TECNICO,
    }
    const t = await abrir('/activo/GGAL.BA')
    expect(donde).toBe('/activo/GGAL.BA')
    expect(t).toContain('Último precio')
  })

  it('una acción argentina que vendiste toda se grafica en BYMA, no con el ADR', async () => {
    const { api } = await import('../utils/api')
    api.get.mockClear()
    respuestas = {
      '/positions': [], '/brokers': [{ name: 'IOL', currency: 'ARS' }], '/dolar': null,
      '/operations': [{ id: 9, asset: 'GGAL', broker: 'IOL', op_type: 'Venta', date: '2026-05-01', quantity: 10, pnl_usd: 12 }],
      '/tecnico/': TECNICO,
    }
    await abrir('/activo/GGAL')
    expect(api.get.mock.calls.map(c => c[0])).toContain('/tecnico/GGAL?moneda=usd&local=1')
  })

  it('si otra persona está bajando la historia, avisa y vuelve a pedir solo', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    try {
      let veces = 0
      respuestas = { ...SIN_CARTERA, '/prices?symbols=NVDA': { NVDA: 182.4 }, '/prices/history': { points: [] },
        '/tecnico/': () => (++veces === 1 ? { disponible: false, motivo: 'bajando' } : TECNICO) }
      const t = await abrir('/activo/NVDA')
      expect(t).toContain('Estamos trayendo la historia')
      await enActo(async () => { vi.advanceTimersByTime(3100) })
      for (let i = 0; i < 4; i++) await montado.redibujar(app('/activo/NVDA', null))
      expect(texto(montado.contenedor)).toContain('Largo plazo')
      expect(veces).toBe(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('en el demo, el gráfico cae a los 30 días (no a "No se pudo cargar")', async () => {
    const { handleDemoRequest } = await vi.importActual('../utils/demo')
    expect(handleDemoRequest('GET', '/tecnico/CSCO?moneda=usd')).toMatchObject({ disponible: false, motivo: 'sin_serie' })
  })
})

describe('el análisis fundamental en la ficha', () => {
  it('no pide el resumen con IA (gasta el cupo semanal mirando fichas)', async () => {
    const { api } = await import('../utils/api')
    api.post.mockClear()
    respuestas = { ...SIN_CARTERA, '/prices?symbols=NVDA': { NVDA: 182.4 }, '/tecnico/': TECNICO,
      '/fundamentals/NVDA': FUNDAMENTALES('NVDA', 'NVIDIA Corporation') }
    const t = await abrir('/activo/NVDA')
    expect(t).toContain('El negocio')
    expect(api.post.mock.calls.map(c => c[0])).not.toContain('/fundamentals/ai-summary')
  })

  it('una cripto no tiene empresa: ni se pide ni queda un título suelto', async () => {
    const { api } = await import('../utils/api')
    api.get.mockClear()
    respuestas = { ...SIN_CARTERA, '/prices?symbols=BTC': { BTC: 80000 }, '/tecnico/': TECNICO }
    const t = await abrir('/activo/BTC')
    expect(t).not.toContain('Análisis fundamental')
    expect(api.get.mock.calls.map(c => c[0]).some(r => r.startsWith('/fundamentals/'))).toBe(false)
  })

  it('si la empresa no tiene fundamentales, la ficha sigue sin un cartel vacío', async () => {
    respuestas = { ...SIN_CARTERA, '/prices?symbols=NVDA': { NVDA: 182.4 }, '/tecnico/': TECNICO,
      '/fundamentals/NVDA': { available: false, reason: 'sin datos' } }
    const t = await abrir('/activo/NVDA')
    expect(t).toContain('Largo plazo')
    expect(t).not.toContain('Análisis fundamental')
    expect(t).not.toContain('no tenemos fundamentales')
  })

  it('en lo que tenés, también va debajo del técnico y antes de tu operatoria', async () => {
    respuestas = {
      '/positions': [{ id: 5, asset: 'NVDA', broker: 'Schwab', quantity: 3, invested: 450, currency: 'USD', asset_type: 'STOCK', entry_date: '2025-05-01' }],
      '/brokers': [{ name: 'Schwab', currency: 'USD' }], '/dolar': null, '/operations': [],
      '/prices': { NVDA: 182.4 }, '/tecnico/': TECNICO, '/plazos-fijos': [],
      '/fundamentals/NVDA': FUNDAMENTALES('NVDA', 'NVIDIA Corporation'),
    }
    const t = await abrir('/activo/NVDA')
    const tecnico = t.indexOf('Largo plazo'), fundamental = t.indexOf('Análisis fundamental'), tuya = t.indexOf('Tu operatoria')
    expect(tecnico).toBeGreaterThan(-1)
    expect(fundamental).toBeGreaterThan(tecnico)
    expect(tuya).toBeGreaterThan(fundamental)
  })
})
