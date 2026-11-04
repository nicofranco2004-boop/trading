// La pestaña «Backtesting» de Análisis técnico MONTADA con react-dom, como la ve
// el usuario: la página entera (/analisis-tecnico?tab=backtesting) y los pedidos
// al servidor simulados en el borde (`api`), que contesta con la respuesta REAL
// del servidor para GGAL (backend/tests/fixtures/backtest_ggal.json, que
// backend/tests/test_backtest.py compara contra backtest.probar).
// Lo que importa:
//   · es una pestaña de verdad, no un «Pronto», y abre en el mismo activo que
//     el Gráfico (lo último que miraste);
//   · pide la prueba sobre la serie de la ficha: tu GGAL de IOL va con local=1,
//     tu NVDA de Schwab sin;
//   · cambiar el período o la regla vuelve a pedir y queda en la dirección;
//   · muestra la regla y comprar y mantener lado a lado, qué quiere decir y
//     cada operación;
//   · comparar: se suman hasta 3 (una tarjeta y una fila de «cuándo estuvo
//     comprada» por regla), se sacan, y las operaciones se ven regla por regla;
//   · sin precios, o si el pedido falla, lo dice (y ofrece reintentar).
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscar, buscarBoton, clic, enActo } from '../testing/navegadorMinimo'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() }))
vi.mock('../utils/api', () => ({ api, getClientContext: () => null, EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada' }))
vi.mock('../contexts/CurrencyContext', () => ({
  useCurrency: () => ({ valuationDollar: 'mep', costBasis: 'today', currency: 'USD' }),
  pickFinancialRate: (d) => d?.mep?.venta || null,
}))
vi.mock('../hooks/usePushNotifications', () => ({ usePushNotifications: () => null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { tier: 'pro', email: 'Ana@X.com' } }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))
vi.mock('../components/asset/LecturaTecnica', () => ({ default: () => null }))
// El gráfico de líneas mide la pantalla para dibujarse: acá no hay pantalla.
// Se anota lo que recibe en el ÚLTIMO dibujo (las líneas y las franjas de los
// días comprada; cada dibujo del gráfico empieza la lista de nuevo) y no dibuja
// nada.
const dibujado = vi.hoisted(() => ({ franjas: [], lineas: [] }))
vi.mock('recharts', () => {
  const nada = () => null
  return {
    ResponsiveContainer: ({ children }) => children,
    LineChart: ({ children }) => { dibujado.franjas.length = 0; dibujado.lineas.length = 0; return children ?? null },
    XAxis: nada, YAxis: nada, CartesianGrid: nada, Tooltip: nada, ReferenceLine: nada,
    Line: (p) => { dibujado.lineas.push(p.dataKey); return null },
    ReferenceArea: (p) => { dibujado.franjas.push(p); return null },
  }
})

const AQUI = dirname(fileURLToPath(import.meta.url))
const GGAL = JSON.parse(readFileSync(resolve(AQUI, '../../../backend/tests/fixtures/backtest_ggal.json'), 'utf8'))
const CLAVE = 'rendi_grafico:ana@x.com|propia'

let pedidos
let respuesta   // (url) → lo que contesta /tecnico/:activo/backtest
function servidor() {
  pedidos = []
  api.get.mockImplementation(async (url) => {
    pedidos.push(`GET ${url}`)
    if (url.includes('/backtest?')) return respuesta(url)
    if (url === '/positions') return [
      { id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
      { id: 2, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION', quantity: 100, invested: 500000, buy_price: 5000, currency: 'ARS', tc_compra: 1200 },
    ]
    if (url === '/brokers') return [{ id: 1, name: 'Schwab', currency: 'USD' }, { id: 2, name: 'IOL', currency: 'ARS' }]
    if (url === '/dolar') return { mep: { venta: 1500 } }
    if (url === '/operations') return []
    if (url === '/watchlist') return { items: [] }
    if (url.startsWith('/prices/prev-close')) return {}
    if (url.startsWith('/prices')) return { NVDA: 150, 'GGAL.BA': 6000 }
    if (/^\/tecnico\/[^/]+\/peso$/.test(url)) return { peso: null }
    if (url === '/tus-senales') return { senales: [], alcista: null }
    throw new Error(`GET inesperado ${url}`)
  })
  api.post.mockImplementation(async (url) => {
    if (url === '/tecnico/lista') return { tenencias: [], lecturas: [] }
    throw new Error(`POST inesperado ${url}`)
  })
}
// La respuesta del servidor para esas reglas (GGAL). Una combinación que el
// archivo no tiene se arma con las de cada regla sola.
const delServidor = (url) => {
  const q = new URLSearchParams(url.split('?')[1])
  const reglas = q.get('reglas').split(',')
  const juntas = GGAL[reglas.join(',')]
  return {
    ...(juntas || GGAL[reglas[0]]), reglas, anios: Number(q.get('anios')), curva: [],
    resultados: juntas ? juntas.resultados : reglas.map(r => GGAL[r].resultados[0]),
  }
}
const pedidosDeLaPrueba = () => pedidos.filter(p => p.includes('/backtest?'))

async function abrir(ruta) {
  const { MemoryRouter, Routes, Route, useLocation } = await import('react-router-dom')
  const { default: AnalisisTecnico } = await import('./AnalisisTecnico')
  const donde = { actual: null }
  function Mirar() { donde.actual = useLocation(); return null }
  const m = await montar(h(MemoryRouter, { initialEntries: [ruta] },
    h(Mirar),
    h(Routes, null, h(Route, { path: '/analisis-tecnico', element: h(AnalisisTecnico) }))))
  await esperar()
  return { ...m, donde, t: () => texto(m.contenedor) }
}
const esperar = async () => { for (let i = 0; i < 8; i++) await enActo(async () => { await new Promise(r => setTimeout(r, 0)) }) }
const deLaDireccion = (donde, clave) => new URLSearchParams(donde.actual.search).get(clave)
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
const porEtiqueta = (c, etiqueta) => todos(c, n => n.atributos?.['aria-label'] === etiqueta)[0] || null
const titulosDeTarjetas = (c) => todos(c, n => n.nodeName === 'SECTION' && n.atributos?.['aria-label'])
  .map(n => n.atributos['aria-label'])
/** Elegir en un <select> como el navegador: cambia el valor y avisa con `change`. */
async function elegirEn(contenedor, select, valor) {
  await enActo(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(select), 'value').set.call(select, valor)
    const ev = { type: 'change', target: select, bubbles: true, cancelable: true, defaultPrevented: false,
      timeStamp: Date.now(), preventDefault() {}, stopPropagation() {} }
    for (const fn of contenedor.escuchas.change || []) fn(ev)
  })
}

beforeAll(async () => {
  instalarNavegadorMinimo()
  await import('./AnalisisTecnico')
}, 60000)

let montado
let almacen
beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
  dibujado.franjas.length = 0
  dibujado.lineas.length = 0
  respuesta = delServidor
  ;({ local: almacen } = instalarNavegadorMinimo())
  localStorage.setItem('rendi_user', JSON.stringify({ email: 'Ana@X.com' }))
  window.scrollTo = () => {}
  servidor()
})
afterEach(async () => { await montado?.desmontar?.(); montado = null; vi.unstubAllGlobals() })

describe('Análisis técnico → Backtesting', () => {
  it('es una pestaña de verdad (ya no un «Pronto») y abre en el último activo que miraste', async () => {
    almacen.set(CLAVE, JSON.stringify({ activo: 'GGAL', recientes: ['GGAL'] }))
    montado = await abrir('/analisis-tecnico?tab=backtesting')
    const tabs = todos(montado.contenedor, n => n.atributos?.role === 'tab')
    expect(tabs.map(texto)).toContain('Backtesting')
    expect(texto(tabs.find(t => t.atributos['aria-selected'] === 'true'))).toBe('Backtesting')
    expect(montado.t()).toContain('Pronto: Mercado')
    expect(montado.t()).not.toMatch(/Pronto: Mercado · Backtesting/)
    expect(deLaDireccion(montado.donde, 'activo')).toBe('GGAL')
  })

  it('pide la prueba con la serie de la ficha: tu GGAL de IOL es la acción de BYMA', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=GGAL')
    expect(pedidosDeLaPrueba()).toEqual(['GET /tecnico/GGAL/backtest?reglas=media200&anios=2&local=1'])
    await montado.desmontar()
    pedidos.length = 0
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=NVDA')
    expect(pedidosDeLaPrueba()).toEqual(['GET /tecnico/NVDA/backtest?reglas=media200&anios=2'])
  })

  it('la regla al lado de comprar y mantener, qué quiere decir y cada operación', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=GGAL&reglas=rsi')
    const t = montado.t()
    for (const parte of ['Probá una regla con el pasado', 'Siguiendo la regla', 'Comprar y mantener', '+22,5%',
      '−35,9%', '−59%', '−63%', '3 · 2 ganaron', '223 de 501', 'Le fue mejor que comprar y mantener',
      'La compra del 05/05/26 (+32,6%) explica casi todo', 'Cada operación',
      '10/04/25 → 10/11/25', '24/08/26 → seguía comprada', 'US$ 41,12 → US$ 35,14 (último cierre)',
      'Esta compra explica casi todo el resultado.', 'Cómo habrían ido US$ 100', 'US$ 123', 'US$ 64',
      'no es una recomendación']) {
      expect(t, parte).toContain(parte)
    }
    // Las franjas violetas: una por compra, de la compra a la venta.
    expect(dibujado.franjas.map(f => [f.x1, f.x2])).toEqual(GGAL.rsi.resultados[0].operaciones.map(o => [o.compra, o.venta]))
    expect(t).not.toContain('Cuándo estuvo comprada cada una')
  })

  it('cambiar el período vuelve a pedir y queda en la dirección', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=NVDA')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, '3 años'))
    await esperar()
    expect(pedidosDeLaPrueba().at(-1)).toBe('GET /tecnico/NVDA/backtest?reglas=media200&anios=3')
    expect(deLaDireccion(montado.donde, 'anios')).toBe('3')
  })

  it('elegir otra regla vuelve a pedir, queda en la dirección y explica la regla', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=NVDA')
    const select = buscar(montado.contenedor, 'select')
    expect(select.options.map(o => texto(o))).toEqual(
      ['Precio y media de 200 días', 'Precio y media de 50 días', 'RSI 30 / 70', 'ADX + Squeeze'])
    await elegirEn(montado.contenedor, select, 'adx_squeeze')
    await esperar()
    expect(pedidosDeLaPrueba().at(-1)).toBe('GET /tecnico/NVDA/backtest?reglas=adx_squeeze&anios=2')
    expect(deLaDireccion(montado.donde, 'reglas')).toBe('adx_squeeze')
    expect(montado.t()).toContain('Compra cuando el Squeeze empieza a subir desde abajo')
  })

  it('la media de 200 que recién existe: dice desde cuándo prueba', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=GGAL')
    expect(montado.t()).toContain('la media de 200 días necesita 200 días de precios antes: la prueba arranca el 17/04/25.')
  })

  it('sin precios lo dice, y si el pedido falla ofrece reintentar', async () => {
    respuesta = () => ({ asset: 'XYZ', disponible: false, motivo: 'sin_datos' })
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=NVDA')
    expect(montado.t()).toContain('NVDA no encontramos sus precios.')
    await montado.desmontar()

    respuesta = () => { throw new Error('Error 503') }
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=NVDA')
    expect(montado.t()).toContain('No se pudo armar la prueba.')
    respuesta = delServidor
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Reintentar'))
    await esperar()
    expect(montado.t()).toContain('Siguiendo la regla')
  })
})

describe('Análisis técnico → Backtesting → comparar reglas', () => {
  it('«Comparar con otra regla» suma la primera que no está, pide las dos y muestra una tarjeta por regla', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=NVDA&reglas=rsi')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Comparar con otra regla'))
    await esperar()
    expect(pedidosDeLaPrueba().at(-1)).toBe('GET /tecnico/NVDA/backtest?reglas=rsi,media200&anios=2')
    expect(deLaDireccion(montado.donde, 'reglas')).toBe('rsi,media200')
    const t = montado.t()
    expect(t).toContain('Compará reglas con el pasado')
    expect(titulosDeTarjetas(montado.contenedor)).toEqual(expect.arrayContaining(['RSI 30 / 70', 'Media de 200', 'Comprar y mantener']))
    expect(t).toContain('No las ordenamos de la que dio más a la que dio menos')
    expect(t).toContain('Cuándo estuvo comprada cada una')
    // Con varias, sin franjas detrás de las líneas: una línea por regla y la de mantener.
    expect(dibujado.franjas).toEqual([])
    expect(new Set(dibujado.lineas)).toEqual(new Set(['rsi', 'media200', 'mantener']))
  })

  it('cada lugar ofrece sólo las reglas que no están en otro', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=NVDA&reglas=rsi,adx_squeeze')
    const selects = todos(montado.contenedor, n => n.nodeName === 'SELECT')
    expect(selects.map(s => s.options.map(o => o.atributos.value))).toEqual([
      ['media200', 'media50', 'rsi'], ['media200', 'media50', 'adx_squeeze']])
  })

  it('con tres, el botón se apaga y lo dice; el título cuenta cuántas le ganaron', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=GGAL&reglas=media50,rsi,adx_squeeze')
    const boton = buscarBoton(montado.contenedor, 'Comparar con otra regla')
    expect('disabled' in boton.atributos).toBe(true)
    expect(montado.t()).toContain('Ya sumaste 3, el máximo.')
    expect(montado.t()).toContain('Las tres le ganaron a comprar y mantener')
    expect(montado.t()).toContain('Con 10, 3 y 7 compras en los últimos 2 años')
  })

  it('sacar una regla vuelve a pedir sin ella', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=NVDA&reglas=media50,rsi,adx_squeeze')
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Sacar RSI 30 / 70'))
    await esperar()
    expect(pedidosDeLaPrueba().at(-1)).toBe('GET /tecnico/NVDA/backtest?reglas=media50,adx_squeeze&anios=2')
    expect(deLaDireccion(montado.donde, 'reglas')).toBe('media50,adx_squeeze')
  })

  it('las operaciones se ven regla por regla', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=GGAL&reglas=rsi,adx_squeeze')
    expect(montado.t()).toContain('10/04/25 → 10/11/25')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'ADX + Squeeze· 7'))
    await esperar()
    const t = montado.t()
    expect(t).toContain('05/03/25 → 28/03/25')
    expect(t).not.toContain('10/04/25 → 10/11/25')
  })
})
