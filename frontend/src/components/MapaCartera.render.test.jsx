// El mapa de calor de tu cartera (pieza 8), MONTADO adentro del Dashboard con
// react-dom como lo ve el usuario: el Dashboard pide su cartera, sus precios y
// sus cierres de ayer al servidor (simulado en el borde, `api`), el mapa pide
// sus pesos (POST /tecnico/lista) y se mira lo que queda dibujado. Lo que importa:
//   · el peso de cada cuadro es el «Sí · N%» de Tu lista (la MISMA respuesta,
//     montando las dos pantallas);
//   · «Hoy» es la Var. día de la Cartera lote por lote, en dólares (un papel de
//     un broker en pesos pasa por el MEP), y abajo dice lo que más sumó y restó;
//   · «Contra tu promedio» y «Tendencia» cambian el color y el número;
//   · arriba dice el MISMO «Hoy» que la tarjeta de rendimiento del Dashboard;
//   · cada cuadro abre la ficha; efectivo no;
//   · «Ocultar saldos»: sin montos ni pesos.
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, clic, enActo, medidas } from '../testing/navegadorMinimo'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() }))
vi.mock('../utils/api', async (original) => ({ ...(await original()), api }))
const privacidad = vi.hoisted(() => ({ hidden: false }))
vi.mock('../contexts/PrivacyContext', async (importOriginal) => ({
  // Lo real (OCULTO y compañía, que el Dashboard usa desde lo publicado el 30/10)
  // con el ojito que maneja la prueba.
  ...(await importOriginal()),
  usePrivacy: () => ({ hidden: privacidad.hidden, toggle: () => {} }),
  PrivacyMask: ({ children }) => (privacidad.hidden ? '••••••' : children),
}))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { tier: 'pro' } }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))
vi.mock('../hooks/usePushNotifications', () => ({ usePushNotifications: () => null }))
// La pastilla «Preguntale a Mervall-E» mide botones con `dataset`, que el
// navegador de prueba no tiene; no es parte de lo que se prueba acá.
vi.mock('../components/ai/AskAIAbout', () => ({ default: ({ children }) => children }))

const HOY = new Date().toISOString().slice(0, 10)
const AYER = new Date(Date.now() - 86400000).toISOString().slice(0, 10)
const LECTURA = (l = {}) => ({
  ruedas: 760, fecha: HOY, media200: 90, dist_media200: 11, pendiente_media200: 2, media50: 95,
  dist_media50: 5, rsi: 60, adx: 30, dist_maximo_12m: -3, anio_completo: true, ...l,
})
// Lo que manda el servidor para lo que TENÉS (senales_semana.cartera / peso).
// Los pesos no son los de la valuación de la pantalla a propósito: el mapa
// tiene que dibujar los del servidor, no recalcularlos.
const LISTA = {
  tenencias: [
    { asset: 'NVDA', local: false, peso: 0.55, tipo: 'STOCK' },
    { asset: 'GGAL', local: true, peso: 0.2, tipo: 'ACCION' },
    { asset: 'KO', local: false, peso: 0.15, tipo: 'STOCK' },
  ],
  sin_medir: { efectivo: 0.1, plazos_fijos: null },
  lecturas: [
    { asset: 'NVDA', local: false, disponible: true, lectura: LECTURA(), linea: [], ultimo_cambio: null },
    { asset: 'KO', local: false, disponible: true, lectura: LECTURA({ dist_media200: -5, media200: 110 }), linea: [], ultimo_cambio: null },
    { asset: 'GGAL', local: true, disponible: false },
  ],
}

let pedidos
function servidor() {
  pedidos = []
  api.get.mockImplementation(async (url) => {
    pedidos.push(`GET ${url.split('?')[0]}`)
    if (url === '/positions') return [
      { id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
      { id: 2, broker: 'Schwab', asset: 'KO', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
      { id: 3, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION', quantity: 100, invested: 500000, buy_price: 5000, currency: 'ARS' },
      { id: 4, broker: 'Schwab', asset: 'USD', is_cash: 1, quantity: 0, invested: 300 },
    ]
    if (url === '/brokers') return [{ id: 1, name: 'Schwab', currency: 'USD' }, { id: 2, name: 'IOL', currency: 'ARS' }]
    if (url === '/config') return { tc_mep: 1000, tc_blue: 1000 }
    if (url === '/dolar') return { mep: { venta: 1000, compra: 1000, medio: 1000 }, blue: { venta: 1000 } }
    if (url.startsWith('/prices/prev-close')) return { NVDA: 140, KO: 52, 'GGAL.BA': 5800 }
    if (url.startsWith('/prices')) return { NVDA: 150, KO: 50, 'GGAL.BA': 6000 }
    if (url.startsWith('/snapshots')) return [
      { date: AYER, total_value: 2160, total_invested: 2500, net_deposited: 2500 },
    ]
    if (url === '/watchlist') return { items: [] }
    if (url === '/monthly' || url === '/operations' || url === '/plazos-fijos') return []
    return {}
  })
  api.post.mockImplementation(async (url, body) => {
    pedidos.push(`POST ${url}`)
    if (url === '/tecnico/lista') return { ...LISTA, pedido: body }
    return {}
  })
}

// El mapa mide su ancho con getBoundingClientRect: 900 px es una compu, 360 un celular.
const anchoDe = (px) => medidas(n => (n.atributos && 'data-mapa' in n.atributos ? { left: 0, top: 0, width: px, height: 0 } : null))

async function abrir(Pagina, ruta = '/dashboard', camino = ruta) {
  const { MemoryRouter, Routes, Route, useLocation } = await import('react-router-dom')
  const { default: P } = await import(Pagina)
  const donde = { actual: null }
  function Mirar() { donde.actual = useLocation(); return null }
  const m = await montar(h(MemoryRouter, { initialEntries: [ruta] },
    h(Mirar),
    h(Routes, null,
      h(Route, { path: camino, element: h(P) }),
      h(Route, { path: '*', element: h('div', null, 'otra') }))))
  for (let i = 0; i < 8; i++) await enActo(async () => { await new Promise(r => setTimeout(r, 0)) })
  return { ...m, donde, t: () => texto(m.contenedor) }
}

function todos(c, pred) {
  const out = []
  const pila = [c]
  while (pila.length) {
    const n = pila.shift()
    if (pred(n)) out.push(n)
    pila.push(...(n.childNodes || []))
  }
  return out
}
const cuadro = (c, clave) => todos(c, n => n.atributos?.['data-cuadro'] === clave)[0]
const etiqueta = (c, clave) => cuadro(c, clave)?.atributos?.['aria-label']

beforeAll(async () => {
  instalarNavegadorMinimo()
  await import('../pages/Dashboard')
  await import('../pages/AnalisisTecnico')
}, 60000)

let montado
beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
  instalarNavegadorMinimo()
  window.scrollTo = () => {}
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
  privacidad.hidden = false
  anchoDe(900)
  servidor()
})
afterEach(async () => { await montado?.desmontar?.(); montado = null; medidas(); vi.unstubAllGlobals() })

describe('Mapa de calor de tu cartera (Dashboard)', () => {
  it('pide sus pesos al servidor, UNA vez y sin watchlist', async () => {
    montado = await abrir('../pages/Dashboard')
    expect(pedidos.filter(p => p === 'POST /tecnico/lista')).toHaveLength(1)
    expect(api.post.mock.calls.find(c => c[0] === '/tecnico/lista')[1]).toEqual({ activos: [] })
    expect(pedidos).toContain('GET /prices/prev-close')
  })

  it('el peso de cada cuadro es el «Sí · N%» de Tu lista', async () => {
    montado = await abrir('../pages/Dashboard')
    const mapa = {}
    for (const k of ['NVDA|0', 'GGAL|1', 'KO|0']) mapa[k] = etiqueta(montado.contenedor, k).match(/pesa (\d+%|menos de 1%)/)[1]
    expect(mapa).toEqual({ 'NVDA|0': '55%', 'GGAL|1': '20%', 'KO|0': '15%' })
    await montado.desmontar()
    // Tu lista, como la ve el usuario: Análisis técnico → pestaña «Tu lista».
    montado = await abrir('../pages/AnalisisTecnico', '/analisis-tecnico?tab=lista', '/analisis-tecnico')
    const t = montado.t()
    for (const p of Object.values(mapa)) expect(t).toContain(`Sí · ${p}`)
  })

  it('«Hoy»: la Var. día de la Cartera en dólares; lo que más sumó y lo que más restó', async () => {
    montado = await abrir('../pages/Dashboard')
    // NVDA (150 − 140) / 140; KO (50 − 52) / 52; GGAL en pesos (6000 − 5800) / 5800.
    expect(etiqueta(montado.contenedor, 'NVDA|0')).toMatch(/^NVDA: \+7,1%/)
    expect(etiqueta(montado.contenedor, 'KO|0')).toMatch(/^KO: −3,8%/)
    expect(etiqueta(montado.contenedor, 'GGAL|1')).toMatch(/^GGAL: \+3,4%/)
    const t = montado.t()
    // NVDA suma 10 × 10 = US$ 100; GGAL 100 × $200 = $20.000 ÷ 1.000 = US$ 20; KO resta 10 × 2.
    expect(t).toContain('Lo que más sumó hoy: NVDA (+USD 100,00)')
    expect(t).toContain('Lo que más restó: KO (−USD 20,00)')
    expect(etiqueta(montado.contenedor, 'efectivo')).toMatch(/^Efectivo: no cotiza, pesa 10%/)
  })

  it('arriba dice el MISMO «Hoy» que la tarjeta de rendimiento', async () => {
    montado = await abrir('../pages/Dashboard')
    const t = montado.t()
    const m = t.match(/Hoy tu cartera: ([+−][\d,]+%) \(([+−]USD [\d.,]+)\)/)
    expect(m).not.toBeNull()
    // La tarjeta «Hoy» de la fila de rendimiento: rótulo, %, monto.
    expect(t).toContain(`Hoy${m[1]}${m[2]}Este mes`)
  })

  it('«Contra tu promedio» y «Tendencia» cambian el color y el número', async () => {
    montado = await abrir('../pages/Dashboard')
    const radio = (txt) => todos(montado.contenedor, n => n.atributos?.role === 'radio' && texto(n) === txt)[0]
    // En el mapa, el fondo del cuadro; en la lista de abajo, su muestra de color.
    const fondo = (k) => { const n = cuadro(montado.contenedor, k); return n.style.background || n.childNodes[0].style.background }
    const antes = fondo('GGAL|1')   // +3,4 % en el día: el paso más fuerte
    await clic(montado.contenedor, radio('Contra tu promedio'))
    expect(etiqueta(montado.contenedor, 'NVDA|0')).toMatch(/^NVDA: \+50,0%/)   // 1.500 contra 1.000
    expect(etiqueta(montado.contenedor, 'KO|0')).toMatch(/^KO: −50,0%/)
    expect(etiqueta(montado.contenedor, 'GGAL|1')).toMatch(/^GGAL: \+20,0%/)   // $600.000 contra $500.000
    expect(montado.t()).toContain('arriba o abajo de tu precio promedio de compra')
    expect(fondo('GGAL|1')).not.toBe(antes)   // +20 % contra su promedio: el del medio
    await clic(montado.contenedor, radio('Tendencia'))
    expect(etiqueta(montado.contenedor, 'NVDA|0')).toMatch(/^NVDA: Alcista/)
    expect(etiqueta(montado.contenedor, 'KO|0')).toMatch(/^KO: Bajista/)
    expect(etiqueta(montado.contenedor, 'GGAL|1')).toMatch(/^GGAL: Sin lectura/)
    expect(etiqueta(montado.contenedor, 'efectivo')).toMatch(/^Efectivo: Sin lectura/)
    expect(fondo('GGAL|1')).toBe(fondo('efectivo'))   // el mismo gris
    expect(montado.t()).toContain('promedio de los últimos 200 días')
    expect(montado.t()).toContain('No es una recomendación de compra o venta.')
  })

  it('cada cuadro abre la ficha; el efectivo no', async () => {
    montado = await abrir('../pages/Dashboard')
    expect(cuadro(montado.contenedor, 'efectivo').nodeName).toBe('DIV')
    await clic(montado.contenedor, cuadro(montado.contenedor, 'KO|0'))
    expect(montado.donde.actual.pathname).toBe('/activo/KO')
  })

  it('en el celular lo que no se puede tocar baja a la lista de abajo', async () => {
    anchoDe(360)
    montado = await abrir('../pages/Dashboard')
    const enElMapa = todos(montado.contenedor, n => n.atributos?.['data-cuadro'] && n.style.width)
    for (const n of enElMapa) {
      expect(parseFloat(n.style.width)).toBeGreaterThanOrEqual(52 - 3)
      expect(parseFloat(n.style.height)).toBeGreaterThanOrEqual(52 - 3)
    }
    // Los cuatro siguen estando: en el mapa o en la lista.
    for (const k of ['NVDA|0', 'GGAL|1', 'KO|0', 'efectivo']) expect(cuadro(montado.contenedor, k)).toBeTruthy()
  })

  it('con «Ocultar saldos» no se ven montos ni cuánto pesa', async () => {
    privacidad.hidden = true
    montado = await abrir('../pages/Dashboard')
    const seccion = todos(montado.contenedor, n => n.atributos?.['aria-label'] === 'Mapa de calor de tu cartera')[0]
    const t = texto(seccion)
    expect(t).not.toMatch(/USD|ARS/)
    expect(t).not.toMatch(/\d+%\s*$/m)
    expect(t).toContain('Lo que más sumó hoy: NVDA (+7,1%)')
    expect(etiqueta(montado.contenedor, 'NVDA|0')).not.toContain('pesa')
  })
})
