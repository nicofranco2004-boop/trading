// «Una cartera» de la pestaña Backtesting MONTADA con react-dom, como la ve el
// usuario: la página entera (/analisis-tecnico?tab=backtesting&modo=cartera) y
// los pedidos al servidor simulados en el borde (`api`). La simulación contesta
// con la respuesta REAL del servidor (backend/tests/fixtures/cartera_simulada.json,
// que backend/tests/test_cartera_simulada.py compara contra cartera_simulada.simular).
// Lo que importa:
//   · «Una regla | Una cartera» arriba; la cartera arranca con la tuya de hoy
//     (la arma el servidor) o de cero, y las dos se editan;
//   · cada activo con su porcentaje, la torta se arma mientras tanto y lo que
//     falta para 100 se dice; sólo con 100 se pide la simulación;
//   · el resultado: la cartera, el S&P 500 y el Nasdaq, lado a lado;
//   · con «Ocultar saldos» prendido, tu cartera de hoy no se trae ni se ve;
//   · la cartera queda en la dirección.
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic, enActo, escribir, tecla } from '../testing/navegadorMinimo'

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
const ojito = vi.hoisted(() => ({ hidden: false }))
vi.mock('../contexts/PrivacyContext', () => ({
  usePrivacy: () => ({ hidden: ojito.hidden, toggle: () => {} }),
  OCULTO: '•••',
}))
// La torta (components/CompositionDonut): se anota lo que recibe.
const torta = vi.hoisted(() => ({ ultima: null }))
vi.mock('../components/CompositionDonut', () => ({ default: (p) => { torta.ultima = p; return null } }))
const dibujado = vi.hoisted(() => ({ lineas: [] }))
vi.mock('recharts', () => {
  const nada = () => null
  return {
    ResponsiveContainer: ({ children }) => children,
    LineChart: ({ children }) => { dibujado.lineas.length = 0; return children ?? null },
    XAxis: nada, YAxis: nada, CartesianGrid: nada, Tooltip: nada, ReferenceLine: nada, ReferenceArea: nada,
    Line: (p) => { dibujado.lineas.push(p.dataKey); return null },
  }
})

const AQUI = dirname(fileURLToPath(import.meta.url))
const CASOS = JSON.parse(readFileSync(resolve(AQUI, '../../../backend/tests/fixtures/cartera_simulada.json'), 'utf8'))
const HOY = {
  activos: [{ asset: 'AAPL', local: false, peso: 50, tipo: 'STOCK' }, { asset: 'GGAL', local: true, peso: 30, tipo: 'ACCION' },
    { asset: 'BTC', local: false, peso: 20, tipo: 'CRYPTO' }],
  afuera: [{ asset: 'AL30', tipo: 'BOND', motivo: 'sin_serie' }],
}

let pedidos
let simulacion   // (url) → lo que contesta /backtest/cartera?…
function servidor() {
  pedidos = []
  api.get.mockImplementation(async (url) => {
    pedidos.push(`GET ${url}`)
    if (url === '/backtest/cartera/hoy') return HOY
    if (url.startsWith('/backtest/cartera?')) return simulacion(url)
    if (url.startsWith('/tickers/search')) return { results: [] }
    if (url === '/positions') return [
      { id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
    ]
    if (url === '/brokers') return [{ id: 1, name: 'Schwab', currency: 'USD' }]
    if (url === '/dolar') return { mep: { venta: 1500 } }
    if (url === '/operations') return []
    if (url === '/watchlist') return { items: [] }
    if (url.startsWith('/prices/prev-close')) return {}
    if (url.startsWith('/prices')) return { NVDA: 150 }
    if (/^\/tecnico\/[^/]+\/peso$/.test(url)) return { peso: null }
    if (/^\/tecnico\/[^/]+\/backtest/.test(url)) return { disponible: false, motivo: 'sin_datos' }
    if (url === '/tus-senales') return { senales: [], alcista: null }
    throw new Error(`GET inesperado ${url}`)
  })
  api.post.mockImplementation(async (url) => {
    if (url === '/tecnico/lista') return { tenencias: [], lecturas: [] }
    throw new Error(`POST inesperado ${url}`)
  })
}
const delServidor = () => ({ ...CASOS.tres, curva: [] })
const simulaciones = () => pedidos.filter(p => p.startsWith('GET /backtest/cartera?'))

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
// Lo que se escribe espera un momento quieto antes de pedir (PAUSA_MS).
const pasaLaPausa = async () => { await enActo(async () => { await new Promise(r => setTimeout(r, 450)) }); await esperar() }
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
const porcentajes = (c) => todos(c, n => /^Porcentaje de /.test(n.atributos?.['aria-label'] || ''))
  .map(n => [n.atributos['aria-label'].replace('Porcentaje de ', '').replace(' en la cartera', ''), n.value])

beforeAll(async () => {
  instalarNavegadorMinimo()
  await import('./AnalisisTecnico')
}, 60000)

let montado
beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
  dibujado.lineas.length = 0
  torta.ultima = null
  ojito.hidden = false
  simulacion = delServidor
  instalarNavegadorMinimo()
  localStorage.setItem('rendi_user', JSON.stringify({ email: 'Ana@X.com' }))
  window.scrollTo = () => {}
  servidor()
})
afterEach(async () => { await montado?.desmontar?.(); montado = null; vi.unstubAllGlobals() })

describe('Backtesting → Una cartera', () => {
  it('«Una regla | Una cartera» arriba; la cartera arranca con la tuya de hoy y se simula contra los índices', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&activo=NVDA')
    expect(montado.t()).toContain('Probá una regla con el pasado')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Una cartera'))
    await esperar()
    expect(deLaDireccion(montado.donde, 'modo')).toBe('cartera')
    const t = montado.t()
    expect(t).toContain('Simulá una cartera con el pasado')
    expect(t).not.toContain('Probá una regla con el pasado')
    // Tu cartera de hoy, la del servidor, y lo que quedó afuera.
    expect(porcentajes(montado.contenedor)).toEqual([['AAPL', '50'], ['GGAL', '30'], ['BTC', '20']])
    expect(t).toContain('Quedaron afuera AL30: no tiene precio de todos los días.')
    expect(t).toContain('Total 100% · Suma 100%')
    expect(torta.ultima.montos).toBe(false)
    expect(torta.ultima.items.map(i => [i.key, i.value])).toEqual([['AAPL', 50], ['GGAL', 30], ['BTC', 20]])
    // La simulación, con la marca de BYMA de GGAL, y lo que dicen los números.
    expect(simulaciones()).toEqual(['GET /backtest/cartera?activos=AAPL,GGAL,BTC&pesos=50,30,20&local=GGAL&anios=2'])
    const r = montado.t()
    for (const parte of ['Esta cartera', 'S&P 500', 'Nasdaq', '+21,4%', 'Le fue mejor que el S&P 500, pero no que el Nasdaq',
      'El que más sumó fue AAPL, +17,8 puntos', 'Sin tocarla, GGAL pasó de 30% a 19,7% de la cartera.',
      'Cada activo', 'Cómo habrían ido US$ 100', 'no es una recomendación']) {
      expect(r, parte).toContain(parte)
    }
    expect(new Set(dibujado.lineas)).toEqual(new Set(['cartera', 'sp500', 'nasdaq']))
    // Queda en la dirección: recargar abre la misma cartera.
    expect([deLaDireccion(montado.donde, 'activos'), deLaDireccion(montado.donde, 'pesos'), deLaDireccion(montado.donde, 'local')])
      .toEqual(['AAPL,GGAL,BTC', '50,30,20', 'GGAL'])
  })

  it('cambiar un porcentaje arma la torta y dice cuánto falta; repartir vuelve a 100 y pide de nuevo', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera')
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '40')
    await esperar()
    expect(montado.t()).toContain('Total 90% · Faltan 10%')
    expect(montado.t()).toContain('Para ver cómo le habría ido, los porcentajes tienen que sumar 100%: falta repartir 10%.')
    expect(torta.ultima.items.at(-1)).toMatchObject({ key: 'sin_dato', value: 10, label: 'Falta repartir' })
    await pasaLaPausa()
    expect(simulaciones()).toHaveLength(1)   // con 90 % no se pide
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Repartir en partes iguales'))
    await pasaLaPausa()
    expect(porcentajes(montado.contenedor)).toEqual([['AAPL', '34'], ['GGAL', '33'], ['BTC', '33']])
    expect(simulaciones().at(-1)).toBe('GET /backtest/cartera?activos=AAPL,GGAL,BTC&pesos=34,33,33&local=GGAL&anios=2')
  })

  it('sacar un activo y sumar otro con el buscador (toma lo que falta)', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera')
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Sacar BTC'))
    await esperar()
    expect(porcentajes(montado.contenedor)).toEqual([['AAPL', '50'], ['GGAL', '30']])
    expect(montado.t()).toContain('Faltan 20%')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Sumar activo'))
    await esperar()
    const buscador = porEtiqueta(montado.contenedor, 'Buscar un activo para sumar a la cartera')
    await escribir(buscador, 'KO')
    await tecla(buscador, 'Enter')
    await esperar()
    expect(porcentajes(montado.contenedor)).toEqual([['AAPL', '50'], ['GGAL', '30'], ['KO', '20']])
    await pasaLaPausa()
    expect(simulaciones().at(-1)).toBe('GET /backtest/cartera?activos=AAPL,GGAL,KO&pesos=50,30,20&local=GGAL&anios=2')
  })

  it('armar de cero: sin activos, y el primero que se suma toma el 100', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Armar de cero'))
    await esperar()
    expect(porcentajes(montado.contenedor)).toEqual([])
    expect(montado.t()).toContain('Todavía no hay activos.')
    expect(deLaDireccion(montado.donde, 'origen')).toBe('cero')
    const buscador = porEtiqueta(montado.contenedor, 'Buscar un activo para sumar a la cartera')
    await escribir(buscador, 'MSFT')
    await tecla(buscador, 'Enter')
    await pasaLaPausa()
    expect(porcentajes(montado.contenedor)).toEqual([['MSFT', '100']])
    expect(simulaciones().at(-1)).toBe('GET /backtest/cartera?activos=MSFT&pesos=100&anios=2')
  })

  it('con «Ocultar saldos» prendido no se trae tu cartera de hoy, y se puede armar de cero', async () => {
    ojito.hidden = true
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera')
    expect(pedidos).not.toContain('GET /backtest/cartera/hoy')
    expect(montado.t()).toContain('Con «Ocultar saldos» prendido no traemos tu cartera de hoy')
    expect(porcentajes(montado.contenedor)).toEqual([])
    // Aunque la dirección traiga una cartera «de hoy», con el ojito no se ve.
    await montado.desmontar()
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera&activos=AAPL&pesos=100')
    expect(porcentajes(montado.contenedor)).toEqual([])
    expect(simulaciones()).toEqual([])
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Armar de cero'))
    await esperar()
    expect(porEtiqueta(montado.contenedor, 'Buscar un activo para sumar a la cartera')).not.toBeNull()
  })

  it('la cartera de la dirección no se pisa con la de hoy', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera&origen=hoy&activos=KO,MELI&pesos=60,40&anios=3')
    expect(pedidos).not.toContain('GET /backtest/cartera/hoy')
    expect(porcentajes(montado.contenedor)).toEqual([['KO', '60'], ['MELI', '40']])
    expect(simulaciones()).toEqual(['GET /backtest/cartera?activos=KO,MELI&pesos=60,40&anios=3'])
  })

  it('lo que no se puede simular lo dice, y el Nasdaq que falta también', async () => {
    simulacion = () => CASOS.vieja
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera')
    expect(montado.t()).toContain('PARADA no tiene precios desde el 30/09/26: sacalo para simular el resto.')
    await montado.desmontar()
    simulacion = () => ({ ...CASOS.sin_nasdaq, curva: [] })
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera')
    expect(montado.t()).toContain('Todavía no tenemos la historia del Nasdaq para compararla.')
    expect(new Set(dibujado.lineas)).toEqual(new Set(['cartera', 'sp500']))
  })
})
