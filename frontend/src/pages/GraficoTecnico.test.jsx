// La pestaña «Gráfico» de Análisis técnico MONTADA con react-dom, como la ve el
// usuario: la página entera (/analisis-tecnico?tab=grafico), los pedidos al
// servidor simulados en el borde (`api`) y el gráfico reemplazado por uno que
// anota lo que recibe (y no dibuja nada: como con un activo sin historia de
// precios, cuando el gráfico no muestra ni sus botones).
// Lo que importa:
//   · abre en el último activo que miraste (o el de la dirección, o lo tuyo) y
//     lo deja en la dirección (?activo=…);
//   · el botón abre el buscador; elegir otro activo lo cambia, lo guarda y el
//     anterior queda entre los últimos que miraste;
//   · al gráfico le llega la cuenta de la ficha (useFichaDelActivo): tus lotes
//     y qué parte de tu cartera es, lo mismo que en /activo/:ticker;
//   · pedido con otro nombre (GGAL.BA) abre el tuyo (GGAL).
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic, enActo, escribir, tecla } from '../testing/navegadorMinimo'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() }))
vi.mock('../utils/api', () => ({ api }))
vi.mock('../contexts/CurrencyContext', () => ({
  useCurrency: () => ({ valuationDollar: 'mep', costBasis: 'today', currency: 'USD' }),
  pickFinancialRate: (d) => d?.mep?.venta || null,
}))
vi.mock('../hooks/usePushNotifications', () => ({ usePushNotifications: () => null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { tier: 'pro', email: 'Ana@X.com' } }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))
const recibido = vi.hoisted(() => [])
vi.mock('../components/asset/LecturaTecnica', () => ({
  default: (props) => { recibido.push(props); return null },
}))

const CLAVE = 'rendi_grafico:ana@x.com:propia'
let pedidos
function servidor() {
  pedidos = []
  api.get.mockImplementation(async (url) => {
    pedidos.push(`GET ${url}`)
    if (url === '/positions') return [
      { id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
      { id: 2, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION', quantity: 100, invested: 500000, buy_price: 5000, currency: 'ARS', tc_compra: 1200 },
    ]
    if (url === '/brokers') return [{ id: 1, name: 'Schwab', currency: 'USD' }, { id: 2, name: 'IOL', currency: 'ARS' }]
    if (url === '/dolar') return { mep: { venta: 1500 } }
    if (url === '/operations') return []
    if (url === '/watchlist') return { items: [{ symbol: 'TSLA' }] }
    if (url.startsWith('/prices/prev-close')) return {}
    if (url.startsWith('/prices')) return { NVDA: 150, 'GGAL.BA': 6000, TSLA: 400 }
    if (/^\/tecnico\/[^/]+\/peso$/.test(url)) return { peso: url.includes('NVDA') ? 0.4 : null }
    if (url === '/tus-senales') return { senales: [], alcista: null }
    throw new Error(`GET inesperado ${url}`)
  })
  api.post.mockImplementation(async (url) => {
    if (url === '/tecnico/lista') return { tenencias: [], lecturas: [] }
    throw new Error(`POST inesperado ${url}`)
  })
}

let almacen
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
const activoDe = (donde) => new URLSearchParams(donde.actual.search).get('activo')
const botonDelActivo = (c) => {
  const pila = [c]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && n.atributos?.['data-capa'] === 'activo') return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
const campo = (c) => {
  const pila = [c]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'INPUT') return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

beforeAll(async () => {
  instalarNavegadorMinimo()
  await import('./AnalisisTecnico')
}, 60000)

let montado
beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
  recibido.length = 0
  ;({ local: almacen } = instalarNavegadorMinimo())
  window.scrollTo = () => {}
  servidor()
})
afterEach(async () => { await montado?.desmontar?.(); montado = null; vi.unstubAllGlobals() })

describe('Análisis técnico → Gráfico', () => {
  it('la primera vez abre lo tuyo, lo pone en la dirección y le pasa al gráfico la cuenta de la ficha', async () => {
    montado = await abrir('/analisis-tecnico?tab=grafico')
    expect(activoDe(montado.donde)).toBe('NVDA')
    const g = recibido.at(-1)
    expect(g.asset).toBe('NVDA')
    expect(g.lotes.map(l => l.id)).toEqual([1])
    expect(g.pesoEnCartera).toBe(0.4)
    expect(g.referencia).toEqual({ simbolo: 'NVDA', precio: 150 })
    expect(JSON.parse(almacen.get(CLAVE))).toEqual({ activo: 'NVDA', recientes: ['NVDA'] })
  })

  it('vuelve al último que miraste; la dirección gana', async () => {
    almacen.set(CLAVE, JSON.stringify({ activo: 'TSLA', recientes: ['TSLA', 'NVDA'] }))
    montado = await abrir('/analisis-tecnico?tab=grafico')
    expect(recibido.at(-1).asset).toBe('TSLA')
    // TSLA no la tenés: el gráfico sin tu precio ni tus compras.
    expect(recibido.at(-1).lotes).toEqual([])
    // Lo que la ficha muestra arriba de un activo que no tenés (el precio de
    // hoy, el cierre anterior), la pestaña no lo pide.
    expect(pedidos.filter(p => p.startsWith('GET /prices/prev-close'))).toEqual([])
    await montado.desmontar()
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=ggal')
    expect(recibido.at(-1).asset).toBe('GGAL')
    expect(activoDe(montado.donde)).toBe('GGAL')
  })

  it('el botón abre el buscador; elegir otro cambia el gráfico, lo guarda y el anterior queda entre los últimos', async () => {
    almacen.set(CLAVE, JSON.stringify({ activo: 'NVDA', recientes: ['NVDA'] }))
    montado = await abrir('/analisis-tecnico?tab=grafico')
    await clic(montado.contenedor, botonDelActivo(montado.contenedor))
    await esperar()
    const t = montado.t()
    expect(t).toContain('Últimos que miraste')
    expect(t).toContain('Tu cartera')
    expect(t).toContain('Tu lista')
    await escribir(campo(montado.contenedor), 'tes')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Tesla'))
    await esperar()
    expect(recibido.at(-1).asset).toBe('TSLA')
    expect(activoDe(montado.donde)).toBe('TSLA')
    expect(JSON.parse(almacen.get(CLAVE)).recientes).toEqual(['TSLA', 'NVDA'])
    // El buscador se cerró y NVDA quedó a un toque, al lado del botón.
    expect(campo(montado.contenedor)).toBeNull()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'NVDA'))
    await esperar()
    expect(recibido.at(-1).asset).toBe('NVDA')
  })

  it('con el teclado: Enter abre el primero; Esc cierra sin elegir', async () => {
    almacen.set(CLAVE, JSON.stringify({ activo: 'NVDA', recientes: ['NVDA'] }))
    montado = await abrir('/analisis-tecnico?tab=grafico')
    await clic(montado.contenedor, botonDelActivo(montado.contenedor))
    await tecla(campo(montado.contenedor), 'Escape')
    expect(campo(montado.contenedor)).toBeNull()
    await clic(montado.contenedor, botonDelActivo(montado.contenedor))
    await esperar()
    await escribir(campo(montado.contenedor), 'ggal')
    await tecla(campo(montado.contenedor), 'Enter')
    await esperar()
    expect(recibido.at(-1).asset).toBe('GGAL')
  })

  it('el botón del activo está aunque el gráfico no dibuje nada (un activo sin historia de precios)', async () => {
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=AL30')
    expect(recibido.at(-1).asset).toBe('AL30')
    expect(botonDelActivo(montado.contenedor)).not.toBeNull()
    expect(recibido.at(-1).titulo).toBeNull()
  })

  it('pedido con otro nombre (GGAL.BA) abre el tuyo (GGAL), con tus lotes', async () => {
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=GGAL.BA')
    expect(recibido.at(-1).asset).toBe('GGAL')
    expect(recibido.at(-1).lotes.map(l => l.id)).toEqual([2])
    expect(recibido.at(-1).accionLocal).toBe(true)
    expect(activoDe(montado.donde)).toBe('GGAL')
  })
})
