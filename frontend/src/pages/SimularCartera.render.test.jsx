// «Una cartera» de la pestaña Backtesting MONTADA con react-dom, como la ve el
// usuario: la página entera (/analisis-tecnico?tab=backtesting&modo=cartera) y
// los pedidos al servidor simulados en el borde (`api`). La simulación contesta
// con la respuesta REAL del servidor (backend/tests/fixtures/cartera_simulada.json,
// que backend/tests/test_cartera_simulada.py compara contra cartera_simulada.simular).
// Lo que importa:
//   · «Una regla | Una cartera» arriba; la cartera arranca con la tuya de hoy
//     (la arma el servidor) o de cero, y las dos se editan;
//   · cada activo con su porcentaje, la barra del 100 % se llena mientras tanto y
//     lo que falta para 100 se dice; sólo con 100 se pide la simulación;
//   · la respuesta, al lado de la tabla: la cartera, el S&P 500 y el Nasdaq, lado
//     a lado; abajo, el gráfico y «Cada activo»; de 1 a 5 años;
//   · con «Ocultar saldos» prendido, tu cartera de hoy no se trae ni se ve;
//   · la armada de cero queda en la dirección; la de hoy NUNCA (ni cambiada):
//     dice qué tenés, y la dirección se ve con el ojito y viaja en los links;
//   · lo que se suma con el buscador lleva la marca de la ficha (GGAL y AGRO de
//     BYMA; lo que tenés, como tus lotes).
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic, enActo, escribir, tecla } from '../testing/navegadorMinimo'
import { porcentaje } from '../utils/backtesting'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() }))
vi.mock('../utils/api', () => ({ api, getClientContext: () => null, EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada' }))
vi.mock('../contexts/CurrencyContext', () => ({
  useCurrency: () => ({ valuationDollar: 'mep', costBasis: 'today', currency: 'USD' }),
  pickFinancialRate: (d) => d?.mep?.venta || null,
}))
vi.mock('../hooks/usePushNotifications', () => ({ usePushNotifications: () => null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { tier: 'pro', email: 'Ana@X.com' } }) }))
const asesor = vi.hoisted(() => ({ clientCtx: null }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: asesor.clientCtx }) }))
vi.mock('../components/asset/LecturaTecnica', () => ({ default: () => null }))
const ojito = vi.hoisted(() => ({ hidden: false }))
vi.mock('../contexts/PrivacyContext', () => ({
  usePrivacy: () => ({ hidden: ojito.hidden, toggle: () => {} }),
  OCULTO: '•••',
}))
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
let hoyDelServidor   // () → lo que contesta /backtest/cartera/hoy
let lotes        // lo que contesta /positions
let sugerencias  // (q) → lo que contesta /tickers/search
function servidor() {
  pedidos = []
  api.get.mockImplementation(async (url) => {
    pedidos.push(`GET ${url}`)
    if (url === '/backtest/cartera/hoy') return hoyDelServidor()
    if (url.startsWith('/backtest/cartera?')) return simulacion(url)
    if (url.startsWith('/tickers/search')) return { results: sugerencias(decodeURIComponent(url.split('q=')[1] || '')) }
    if (url === '/positions') return lotes
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
  // «Una cartera» se baja recién al elegirla (React.lazy): ya bajada, aparece en el
  // momento, como en la página después de la primera vez.
  await import('./SimularCartera')
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
// Entrar a un campo como el navegador: React escucha `focusin` en la raíz (como `clic`).
async function entrar(contenedor, nodo) {
  await enActo(async () => {
    const ev = { type: 'focusin', target: nodo, bubbles: true, cancelable: true, defaultPrevented: false,
      timeStamp: Date.now(), preventDefault() {}, stopPropagation() {} }
    for (const fn of contenedor.escuchas.focusin || []) fn(ev)
  })
}
const porcentajes = (c) => todos(c, n => /^Porcentaje de /.test(n.atributos?.['aria-label'] || ''))
  .map(n => [n.atributos['aria-label'].replace('Porcentaje de ', '').replace(' en la cartera', ''), n.value])
// La barra del 100 %: cada tramo con lo que dice al pasar el mouse, cuánto ocupa y su color.
function barra(c) {
  const b = todos(c, n => n.atributos?.['data-barra'] != null)[0]
  return b ? b.childNodes.map(n => [n.atributos.title, Number(n.style.flexGrow), n.atributos.class]) : null
}
// La tarjeta de arriba (la de la tabla), donde ahora va también la respuesta.
const laTarjeta = (c) => todos(c, n => n.atributos?.['aria-labelledby'] === 'sc-titulo')[0]

beforeAll(async () => {
  instalarNavegadorMinimo()
  await import('./AnalisisTecnico')
}, 60000)

let montado
beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
  dibujado.lineas.length = 0
  ojito.hidden = false
  asesor.clientCtx = null
  simulacion = delServidor
  hoyDelServidor = () => HOY
  sugerencias = () => []
  lotes = [{ id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 }]
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
    expect(t).toContain('¿Qué querés probar?')   // el rótulo, a la vista (producto 05/11, A6)
    expect(t).toContain('Simulá una cartera con el pasado')
    expect(t).not.toContain('Probá una regla con el pasado')
    // Tu cartera de hoy, la del servidor, y lo que quedó afuera.
    expect(porcentajes(montado.contenedor)).toEqual([['AAPL', '50'], ['GGAL', '30'], ['BTC', '20']])
    expect(t).toContain('Quedó afuera AL30: no tenemos sus precios de cada día.')
    expect(t).toContain('Suma 100%')
    expect(barra(montado.contenedor)).toEqual([['AAPL 50%', 50, 'bg-data-violet'], ['GGAL 30%', 30, 'bg-data-violet'],
      ['BTC 20%', 20, 'bg-data-violet']])
    // La simulación, con la marca de BYMA de GGAL, y lo que dicen los números.
    expect(simulaciones()).toEqual(['GET /backtest/cartera?activos=AAPL,GGAL,BTC&pesos=50,30,20&local=GGAL&anios=2'])
    const r = montado.t()
    // En condicional, primero la respuesta, y con «Mi cartera de hoy» que no es lo que ganaste.
    for (const parte of ['Esta cartera', 'S&P 500', 'Nasdaq', '+21,4%',
      'Habría dado casi lo mismo que el S&P 500, y el Nasdaq le habría ganado',
      'Es tu cartera de hoy puesta en el pasado', 'No es lo que ganaste: eso está en Métricas.', 'Ver Métricas',
      'De cada US$ 100, AAPL habría sumado US$ 17,8', 'Sin tocarla, GGAL habría pasado de 30% a 19,7% de la cartera.',
      'Los índices, sin dividendos, como la cartera.', 'Peor caída: lo más que habría bajado desde su mejor momento.',
      'Cada activo', 'Cómo habrían ido US$ 100', 'no es una recomendación']) {
      expect(r, parte).toContain(parte)
    }
    expect(new Set(dibujado.lineas)).toEqual(new Set(['cartera', 'sp500', 'nasdaq']))
    // La respuesta va al lado de la tabla, en la misma tarjeta, y se ve mientras escribís;
    // el gráfico y «Cada activo», abajo (Nico 06/11; diseño 05/11, M1).
    const arriba = texto(laTarjeta(montado.contenedor))
    for (const parte of ['Habría dado casi lo mismo que el S&P 500, y el Nasdaq le habría ganado', 'Habría dado',
      'Peor caída', 'Esta cartera+21,4%']) expect(arriba, parte).toContain(parte)
    for (const parte of ['Cómo habrían ido US$ 100', 'Cada activo', 'De cada US$ 100']) expect(arriba, parte).not.toContain(parte)
    // Tu cartera de hoy NO queda en la dirección: dice qué tenés y cuánto pesa cada
    // cosa, y la dirección se ve con el ojito, queda en el historial y viaja en cada
    // link (auditorías 05/11, A2 y A3). Tampoco cambiada, ni al volver a «Una regla».
    const deLaCartera = () => ['activos', 'pesos', 'local'].map(k => deLaDireccion(montado.donde, k))
    expect(deLaCartera()).toEqual([null, null, null])
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '40')
    await pasaLaPausa()
    expect(deLaCartera()).toEqual([null, null, null])
    expect(montado.t()).toContain('Partiste de tu cartera de hoy y la cambiaste.')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Una regla'))
    await esperar()
    expect(deLaCartera()).toEqual([null, null, null])
  })

  it('cambiar un porcentaje llena la barra y dice cuánto falta; repartir vuelve a 100 y pide de nuevo', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera')
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '40')
    await esperar()
    expect(montado.t()).toContain('Total 90% · Faltan 10%')
    // El resultado de antes queda en su lugar, diciendo que es el anterior (pantalla 06/11, M2 y B4).
    expect(montado.t()).toContain('Es el resultado anterior: no suman 100%')
    expect(barra(montado.contenedor)).toEqual([['AAPL 40%', 40, 'bg-data-violet'], ['GGAL 30%', 30, 'bg-data-violet'],
      ['BTC 20%', 20, 'bg-data-violet'], ['Falta repartir 10%', 10, 'bg-data-amber/60']])
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
    // Un link viejo con origen=hoy y una cartera: con el ojito no se ve, no se pide
    // nada, y la cartera sale de la dirección.
    await montado.desmontar()
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera&origen=hoy&activos=AAPL&pesos=100')
    expect(porcentajes(montado.contenedor)).toEqual([])
    expect(simulaciones()).toEqual([])
    expect(deLaDireccion(montado.donde, 'pesos')).toBeNull()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Armar de cero'))
    await esperar()
    expect(porEtiqueta(montado.contenedor, 'Buscar un activo para sumar a la cartera')).not.toBeNull()
    // Una cartera ARMADA que llega por un link no es la tuya: se ve con el ojito.
    await montado.desmontar()
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera&activos=KO&pesos=100')
    expect(porcentajes(montado.contenedor)).toEqual([['KO', '100']])
    expect(simulaciones()).toEqual(['GET /backtest/cartera?activos=KO&pesos=100&anios=2'])
  })

  it('la cartera armada de la dirección se abre tal cual; con origen=hoy, la de hoy de quien abre', async () => {
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera&origen=cero&activos=KO,MELI&pesos=60,40&anios=3')
    expect(pedidos).not.toContain('GET /backtest/cartera/hoy')
    expect(porcentajes(montado.contenedor)).toEqual([['KO', '60'], ['MELI', '40']])
    expect(simulaciones()).toEqual(['GET /backtest/cartera?activos=KO,MELI&pesos=60,40&anios=3'])
    await montado.desmontar()
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera&origen=hoy&activos=KO,MELI&pesos=60,40')
    expect(pedidos).toContain('GET /backtest/cartera/hoy')
    expect(porcentajes(montado.contenedor)).toEqual([['AAPL', '50'], ['GGAL', '30'], ['BTC', '20']])
    expect(['activos', 'pesos'].map(k => deLaDireccion(montado.donde, k))).toEqual([null, null])
  })

  it('un link con más de 10 activos dice cuáles no entraron', async () => {
    const doce = Array.from({ length: 12 }, (_, i) => `T${i}`)
    montado = await abrir(`/analisis-tecnico?tab=backtesting&modo=cartera&activos=${doce.join(',')}&pesos=${doce.map(() => 8).join(',')}`)
    expect(porcentajes(montado.contenedor)).toHaveLength(10)
    expect(montado.t()).toContain('El link traía 12 activos y entran hasta 10: quedaron afuera T10 y T11.')
  })

  it('lo que no se puede simular lo dice, y el Nasdaq que falta también', async () => {
    simulacion = () => CASOS.vieja
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera')
    expect(montado.t()).toContain('No tenemos precios de PARADA desde el 30/09/26: sacalo para simular el resto.')
    await montado.desmontar()
    simulacion = () => ({ ...CASOS.sin_nasdaq, curva: [] })
    montado = await abrir('/analisis-tecnico?tab=backtesting&modo=cartera')
    expect(montado.t()).toContain('Todavía no tenemos la historia del Nasdaq para compararla.')
    expect(new Set(dibujado.lineas)).toEqual(new Set(['cartera', 'sp500']))
  })
})

describe('Una cartera — lo que encontraron las auditorías del 05/11', () => {
  const CARTERA = '/analisis-tecnico?tab=backtesting&modo=cartera'
  const DE_CERO = `${CARTERA}&origen=cero`
  async function sumarConElBuscador(m, que) {
    if (!porEtiqueta(m.contenedor, 'Buscar un activo para sumar a la cartera')) {
      await clic(m.contenedor, buscarBoton(m.contenedor, 'Sumar activo'))
      await esperar()
    }
    const buscador = porEtiqueta(m.contenedor, 'Buscar un activo para sumar a la cartera')
    await escribir(buscador, que)
    await tecla(buscador, 'Enter')
    await esperar()
  }
  // Lo que dibuja «Una cartera» (sin el resto de Análisis técnico).
  const laCartera = (c) => todos(c, n => n.atributos?.['aria-labelledby'] === 'sc-titulo')[0].parentNode
  // A quién se le pide el foco (el navegador de las pruebas no lo lleva).
  function mirarElFoco(nodo) {
    const proto = Object.getPrototypeOf(nodo)
    const original = proto.focus
    const visto = { nodo: null, soltar: () => { proto.focus = original } }
    proto.focus = function () { visto.nodo = this }
    return visto
  }

  // H1 · A1: con `local: false` fijo, GGAL se simulaba con el ADR de Nueva York y
  // AGRO con Adecoagro (otra empresa); ALUA decía «no tenemos los precios».
  it('una acción argentina sumada con el buscador es la de BYMA, como en su ficha', async () => {
    montado = await abrir(DE_CERO)
    await sumarConElBuscador(montado, 'GGAL')
    await sumarConElBuscador(montado, 'AGRO')
    expect(porcentajes(montado.contenedor).map(([a]) => a)).toEqual(['GGAL', 'AGRO'])
    expect(montado.t()).toMatch(/GGALBYMA/)
    expect(montado.t()).toMatch(/AGROBYMA/)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Repartir en partes iguales'))
    await pasaLaPausa()
    expect(simulaciones().at(-1)).toBe('GET /backtest/cartera?activos=GGAL,AGRO&pesos=50,50&local=GGAL,AGRO&anios=2')
    expect(deLaDireccion(montado.donde, 'local')).toBe('GGAL,AGRO')
  })

  it('lo que tenés lleva la marca de tus lotes: tu GGAL de Schwab es el ADR', async () => {
    lotes = [{ id: 1, broker: 'Schwab', asset: 'GGAL', asset_type: 'STOCK', quantity: 10, invested: 300, buy_price: 30 }]
    montado = await abrir(DE_CERO)
    await sumarConElBuscador(montado, 'GGAL')
    await pasaLaPausa()
    expect(montado.t()).not.toMatch(/GGALBYMA/)
    expect(simulaciones().at(-1)).toBe('GET /backtest/cartera?activos=GGAL&pesos=100&anios=2')
  })

  it('«GGAL.BA» es GGAL: no entra dos veces, y se dice', async () => {
    montado = await abrir(DE_CERO)
    await sumarConElBuscador(montado, 'GGAL')
    const foco = mirarElFoco(porEtiqueta(montado.contenedor, 'Porcentaje de GGAL en la cartera'))
    try {
      await sumarConElBuscador(montado, 'GGAL.BA')
      expect(porcentajes(montado.contenedor).map(([a]) => a)).toEqual(['GGAL'])
      expect(montado.t()).toContain('GGAL ya está en la cartera: cambiá su porcentaje acá arriba.')
      expect(foco.nodo?.atributos?.['aria-label']).toBe('Porcentaje de GGAL en la cartera')
    } finally { foco.soltar() }
  })

  // M4: «Armar de cero» abre el buscador con los populares; un Enter sin escribir
  // nada sumaba AAPL al 100 % y lo simulaba.
  it('un Enter con el buscador vacío no suma nada, con la lista abierta como en el navegador', async () => {
    montado = await abrir(CARTERA)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Armar de cero'))
    await esperar()
    const antes = simulaciones().length   // la de hoy, antes de armar de cero
    // La lista se abre al entrar al cuadro (`focusin`): sin abrirla, la prueba quedaba
    // verde aunque se borrara el arreglo (verificación 05/11, V12).
    const buscador = porEtiqueta(montado.contenedor, 'Buscar un activo para sumar a la cartera')
    await entrar(montado.contenedor, buscador)
    expect(todos(montado.contenedor, n => n.atributos?.role === 'option').length).toBeGreaterThan(0)
    // Ninguna resaltada sin escribir ni navegar (V9), y Enter no elige.
    expect(todos(montado.contenedor, n => n.atributos?.role === 'option' && String(n.atributos['aria-selected']) === 'true')).toEqual([])
    await tecla(buscador, 'Enter')
    await pasaLaPausa()
    expect(porcentajes(montado.contenedor)).toEqual([])
    expect(simulaciones()).toHaveLength(antes)
    // Con la flecha, la primera de la lista; y ahí Enter sí la elige.
    await entrar(montado.contenedor, porEtiqueta(montado.contenedor, 'Buscar un activo para sumar a la cartera'))
    await tecla(porEtiqueta(montado.contenedor, 'Buscar un activo para sumar a la cartera'), 'ArrowDown')
    await tecla(porEtiqueta(montado.contenedor, 'Buscar un activo para sumar a la cartera'), 'Enter')
    await esperar()
    expect(porcentajes(montado.contenedor)).toEqual([['AAPL', '100']])
  })

  // V2: con el catálogo de Análisis fundamental, AGRO sólo ofrecía Adecoagro (Nueva York).
  it('AGRO del buscador es Agrometal aunque el servidor sugiera Adecoagro', async () => {
    sugerencias = (q) => (q === 'AGRO' ? [{ symbol: 'AGRO', name: 'Adecoagro S.A.' }] : [])
    montado = await abrir(DE_CERO)
    await sumarConElBuscador(montado, 'AGRO')
    await pasaLaPausa()
    expect(montado.t()).toMatch(/AGROBYMA/)
    expect(simulaciones().at(-1)).toBe('GET /backtest/cartera?activos=AGRO&pesos=100&local=AGRO&anios=2')
  })

  // V8: el buscador espera tus lotes, que deciden la marca de lo que tenés.
  it('mientras tus lotes no llegaron, el buscador no se abre', async () => {
    let soltar
    const tarde = new Promise(r => { soltar = r })
    const antes = api.get.getMockImplementation()
    api.get.mockImplementation(async (url) => (url === '/positions' ? tarde : antes(url)))
    montado = await abrir(CARTERA)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Armar de cero'))
    await esperar()
    expect(porEtiqueta(montado.contenedor, 'Buscar un activo para sumar a la cartera')).toBeNull()
    expect(montado.t()).toContain('Un momento…')
    await enActo(async () => { soltar([]) })
    await esperar()
    expect(porEtiqueta(montado.contenedor, 'Buscar un activo para sumar a la cartera')).not.toBeNull()
  })

  // M2: mientras la suma no da 100, el último resultado queda tenue, no desaparece. Y
  // desde el 06/11 queda EN SU LUGAR: el aviso de arriba lo bajaba 68 px en cada tecla;
  // un renglón fijo dice que es el anterior (pantalla 06/11, M2, B4 y B5).
  it('mientras la suma no da 100, el último resultado queda en su lugar, diciendo que es el anterior', async () => {
    montado = await abrir(CARTERA)
    expect(montado.t()).toContain('+21,4%')
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '5')
    await pasaLaPausa()
    const arriba = texto(laTarjeta(montado.contenedor))
    expect(arriba).toContain('Es el resultado anterior: no suman 100%')
    expect(arriba).toContain('+21,4%')                  // el de antes, tenue
    expect(arriba).not.toContain('Para ver cómo le habría ido')
    expect(simulaciones()).toHaveLength(1)              // y no se pidió nada con 55 %
    // Un solo «Repartir»: el aviso tenía otro (B5).
    expect(todos(montado.contenedor, n => n.nodeName === 'BUTTON' && texto(n) === 'Repartir en partes iguales')).toHaveLength(1)
  })

  it('sin un resultado anterior, el aviso entero; y no se lee solo: el total ya se lee en cada tecla', async () => {
    montado = await abrir(`${DE_CERO}&activos=AAPL,KO&pesos=60,30`)
    expect(simulaciones()).toEqual([])
    const aviso = todos(montado.contenedor, n => texto(n) === 'Para ver cómo le habría ido, los porcentajes tienen que sumar 100%: falta repartir 10%.'
      && n.nodeName === 'DIV')[0]
    expect(aviso).toBeDefined()
    expect(aviso.atributos.role).toBeUndefined()        // B11: no se lee dos veces
    expect(todos(montado.contenedor, n => n.atributos?.role === 'status' && texto(n) === 'Total 90% · Faltan 10%')).toHaveLength(1)
  })

  it('con un activo sin porcentaje la barra queda en ámbar: llena pero no lista', async () => {
    // Con 50 / 50 / 0 se veía violeta y completa (pantalla 06/11, B3).
    montado = await abrir(`${DE_CERO}&activos=AAPL,KO,MSFT&pesos=50,50,0`)
    expect(montado.t()).toContain('Total 100% · Falta un porcentaje')
    expect(barra(montado.contenedor)).toEqual([['AAPL 50%', 50, 'bg-data-amber'], ['KO 50%', 50, 'bg-data-amber']])
  })

  it('más de 100 en un porcentaje no se acepta: queda lo que estaba', async () => {
    // Con «10» y el cursor al final, un «5» dejaba 100 sin avisar (pantalla 06/11).
    montado = await abrir(CARTERA)
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '505')
    await esperar()
    expect(porcentajes(montado.contenedor)[0]).toEqual(['AAPL', '50'])
  })

  it('la respuesta: el título, enseguida si arrancó más tarde, la tabla, y después la aclaración', async () => {
    // M1 y M3 (pantalla 06/11): la tabla pegada al título para que entre en la pantalla, y
    // «Tenemos precios de NUEVA desde…» enseguida del título (iba último, afuera).
    simulacion = () => ({ ...CASOS.recortada, curva: [] })
    montado = await abrir(CARTERA)
    const arriba = texto(laTarjeta(montado.contenedor))
    const donde = (x) => { const i = arriba.indexOf(x); expect(i, x).toBeGreaterThan(-1); return i }
    const orden = ['Le habría ido mejor que el S&P 500 y que el Nasdaq', 'Tenemos precios de NUEVA desde el 26/01/26',
      'Habría dadoPeor caída', 'Es tu cartera de hoy puesta en el pasado', 'Del 26/01/26 al 30/10/26'].map(donde)
    expect(orden).toEqual([...orden].sort((a, b) => a - b))
    // La nota de «Mi cartera de hoy», debajo de la tabla de activos de la que habla.
    expect(donde('BTC%')).toBeLessThan(donde('Con tus activos y lo que pesa cada uno hoy'))
  })

  // B5: con el ojito prendido, la salida se puede tocar.
  it('con el ojito prendido, «Armar de cero» está en el mismo aviso', async () => {
    ojito.hidden = true
    montado = await abrir(CARTERA)
    const botones = todos(montado.contenedor, n => n.nodeName === 'BUTTON' && texto(n) === 'Armar de cero')
    expect(botones.length).toBe(2)   // el del selector y el del aviso
    await clic(montado.contenedor, botones[1])
    await esperar()
    expect(deLaDireccion(montado.donde, 'origen')).toBe('cero')
  })

  // M7: tocar la opción ya elegida borraba lo armado, sin aviso ni vuelta atrás.
  it('volver a tocar la opción elegida no borra la cartera', async () => {
    montado = await abrir(`${DE_CERO}&activos=KO,MELI&pesos=60,40`)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Armar de cero'))
    await esperar()
    expect(porcentajes(montado.contenedor)).toEqual([['KO', '60'], ['MELI', '40']])
    await montado.desmontar()
    montado = await abrir(CARTERA)
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '40')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Mi cartera de hoy'))
    await esperar()
    expect(porcentajes(montado.contenedor)[0]).toEqual(['AAPL', '40'])
    expect(pedidos.filter(x => x === 'GET /backtest/cartera/hoy')).toHaveLength(1)
  })

  // M6: lo sumado mientras se traía la de hoy quedaba debajo de «Trayendo…» para siempre.
  it('mientras se trae tu cartera de hoy no se puede sumar', async () => {
    let soltar
    hoyDelServidor = () => new Promise(r => { soltar = r })
    montado = await abrir(CARTERA)
    expect(montado.t()).toContain('Trayendo tu cartera de hoy…')
    expect(buscarBoton(montado.contenedor, 'Sumar activo').atributos.disabled).toBeDefined()
    expect(montado.t()).not.toContain('Total 0%')
    await enActo(async () => { soltar(HOY) })
    await esperar()
    expect(buscarBoton(montado.contenedor, 'Sumar activo').atributos.disabled).toBeUndefined()
    expect(montado.t()).toContain('Suma 100%')
  })

  // M9: con más de 100, la torta decía porcentajes que nadie escribió.
  it('pasada de 100, la barra dice lo que escribiste, toda en ámbar', async () => {
    montado = await abrir(`${DE_CERO}&activos=GGAL,AAPL&pesos=100,33.5`)
    expect(montado.t()).toContain('Total 133,5% · Sobran 33,5%')
    expect(barra(montado.contenedor)).toEqual([['GGAL 100%', 100, 'bg-data-amber'], ['AAPL 33,5%', 33.5, 'bg-data-amber']])
  })

  // A5: de 1 a 5 años, y el período lo comparten los dos modos.
  it('«Una cartera» llega a 5 años; en «Una regla» el mismo link abre 4', async () => {
    montado = await abrir(`${DE_CERO}&activos=KO&pesos=100`)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, '5 años'))
    await pasaLaPausa()
    expect(simulaciones().at(-1)).toBe('GET /backtest/cartera?activos=KO&pesos=100&anios=5')
    expect(deLaDireccion(montado.donde, 'anios')).toBe('5')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Una regla'))
    await esperar()
    const periodo = porEtiqueta(montado.contenedor, 'Período')
    const elegido = todos(periodo, n => n.nodeName === 'BUTTON' && n.atributos['aria-pressed'] === 'true')
    expect(elegido.map(b => texto(b))).toEqual(['4 años'])
    expect(texto(periodo)).not.toContain('5 años')
    expect(pedidos.filter(x => /\/backtest\?reglas=/.test(x)).at(-1)).toMatch(/&anios=4/)
  })

  // M11: el asesor adentro de un cliente leía «Mi cartera de hoy» y «Con tus activos».
  it('con el asesor adentro de un cliente, la cartera de hoy es la de él', async () => {
    asesor.clientCtx = { id: 7, label: 'Ana' }
    montado = await abrir(CARTERA)
    const t = texto(laCartera(montado.contenedor))
    expect(t).toContain('Su cartera de hoy')
    expect(t).toContain('Con los activos de Ana y lo que pesa cada uno hoy')
    expect(t).not.toContain('Mi cartera de hoy')
    expect(t).not.toContain('tus activos')
  })

  it('si se prende el ojito con la cartera de hoy cargada, se saca de la pantalla', async () => {
    montado = await abrir(CARTERA)
    expect(porcentajes(montado.contenedor)).toHaveLength(3)
    ojito.hidden = true
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '45')   // un dibujo nuevo
    await esperar()
    expect(porcentajes(montado.contenedor)).toEqual([])
    expect(montado.t()).toContain('Con «Ocultar saldos» prendido no traemos tu cartera de hoy')
  })

  // Las que siguen las propuso la auditoría de las pruebas: cada una atrapa un
  // error que ninguna otra veía.

  // F2: «Suma 100%» y el pedido, con la MISMA tolerancia que acepta el servidor.
  it('con 99,9 % no dice «Suma 100%» ni pide; con 99,96 % sí', async () => {
    montado = await abrir(CARTERA)
    expect(simulaciones()).toHaveLength(1)
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '49,9')
    await pasaLaPausa()
    expect(montado.t()).toContain('Total 99,9% · Faltan 0,1%')
    expect(simulaciones()).toHaveLength(1)
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '49,96')
    await pasaLaPausa()
    expect(simulaciones().at(-1)).toBe('GET /backtest/cartera?activos=AAPL,GGAL,BTC&pesos=49.96,30,20&local=GGAL&anios=2')
  })

  // F8 y M1: la tabla de la respuesta dice lo de cada línea como se ve; la plata, el gráfico.
  it('la tabla de al lado dice el resultado y la peor caída de cada uno, y la plata va en el gráfico', async () => {
    const r = CASOS.recortada
    simulacion = () => ({ ...r, curva: [] })
    montado = await abrir(`${DE_CERO}&activos=AAPL,GGAL,NUEVA&pesos=50,30,20&local=GGAL&anios=2`)
    const renglon = (nombre) => texto(todos(laTarjeta(montado.contenedor), x => x.nodeName === 'TH' && texto(x) === nombre)[0].parentNode)
    for (const [nombre, x] of [['Esta cartera', r.cartera], ['S&P 500', r.indices[0]], ['Nasdaq', r.indices[1]]]) {
      expect(renglon(nombre), nombre).toBe(`${nombre}${porcentaje(x.resultado)}${porcentaje(x.peor_caida, 0)}`)
    }
    // Una caída que redondea a 0 se ve con su decimal: «−0,3%», no «0%» (auditoría de las pruebas, F8).
    expect(renglon('Esta cartera')).toContain('−0,3%')
    // Desde cuándo arranca, al lado de los números que cambia.
    expect(texto(laTarjeta(montado.contenedor))).toContain('Tenemos precios de NUEVA desde el 26/01/26: la simulación arranca ese día.')
    // La plata de la leyenda del gráfico, con un decimal.
    expect(montado.t()).toMatch(/Esta carteraUS\$ [\d.]+,\dS&P 500US\$ [\d.]+,\dNasdaqUS\$ [\d.]+,\d/)
  })

  // F9: si todos restaron, la frase nombra al que más restó (del servidor).
  it('si todos los activos restaron, dice cuál restó más', async () => {
    const res = CASOS.todos_restan
    simulacion = () => ({ ...res, curva: [] })
    montado = await abrir(`${DE_CERO}&activos=BAJA1,BAJA2&pesos=60,40&anios=1`)
    const peor = [...res.activos].sort((a, b) => a.aporte - b.aporte)[0]
    expect(montado.t()).toContain(`De cada US$ 100, el que más habría restado es ${peor.asset}: US$ ${porcentaje(peor.aporte).replace(/^[−+]/, '').replace('%', '')} de los`)
  })

  // S4: el teclado no se pierde al sacar un activo.
  it('al sacar un activo, el teclado queda en el porcentaje del que tomó su lugar', async () => {
    montado = await abrir(CARTERA)
    const foco = mirarElFoco(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'))
    try {
      await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Sacar GGAL'))
      await esperar()
      expect(foco.nodo?.atributos?.['aria-label']).toBe('Porcentaje de BTC en la cartera')
      await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Sacar BTC'))
      await esperar()
      expect(foco.nodo?.atributos?.['aria-label']).toBe('Porcentaje de AAPL en la cartera')
      await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Sacar AAPL'))
      await esperar()
      expect(texto(foco.nodo)).toContain('Sumar activo')
    } finally { foco.soltar() }
  })

  // M5: «Reintentar» desaparece al tocarlo; el teclado no vuelve al principio.
  it('al reintentar, el teclado queda en el resultado', async () => {
    let falla = true
    simulacion = () => { if (falla) { falla = false; throw new Error('Internal Server Error') } return delServidor() }
    montado = await abrir(CARTERA)
    expect(montado.t()).toContain('No pudimos simular la cartera.')
    expect(montado.t()).toContain('Detalle: el servidor tuvo un error')
    const boton = buscarBoton(montado.contenedor, 'Reintentar')
    const foco = mirarElFoco(boton)
    try {
      await clic(montado.contenedor, boton)
      await esperar()
      expect(String(foco.nodo?.atributos?.tabIndex ?? foco.nodo?.atributos?.tabindex)).toBe('-1')
      expect(montado.t()).toContain('+21,4%')
    } finally { foco.soltar() }
  })

  // S5: la respuesta de una cartera vieja no pisa la de la nueva.
  it('una respuesta vieja que llega tarde no pisa a la nueva', async () => {
    let soltarVieja
    const vieja = new Promise(r => { soltarVieja = r })
    let n = 0
    simulacion = () => (n++ === 0 ? vieja : delServidor())
    montado = await abrir(CARTERA)
    expect(simulaciones()).toHaveLength(1)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Repartir en partes iguales'))
    await pasaLaPausa()
    expect(simulaciones()).toHaveLength(2)
    expect(montado.t()).toContain('+21,4%')
    await enActo(async () => { soltarVieja({ ...CASOS.recortada, curva: [] }) })
    await esperar()
    expect(montado.t()).toContain('+21,4%')
    expect(montado.t()).not.toContain(porcentaje(CASOS.recortada.cartera.resultado))
  })

  // M8: mientras otra persona baja los precios se dice, y un aviso de otra cartera no queda.
  it('si otra persona está bajando los precios, lo dice y reintenta sola', async () => {
    let n = 0
    simulacion = () => (n++ < 1 ? { disponible: false, motivo: 'bajando', faltan: [] } : delServidor())
    montado = await abrir(CARTERA)
    expect(montado.t()).toContain('Estamos trayendo los precios de los activos nuevos: un momento…')
    await enActo(async () => { await new Promise(r => setTimeout(r, 4100)) })
    await esperar()
    expect(montado.t()).toContain('+21,4%')
    expect(simulaciones()).toHaveLength(2)
  }, 10000)

  // S7: el arreglo de e13a8ea1: al entrar al porcentaje, el número queda elegido.
  it('al entrar a un porcentaje, el número queda elegido', async () => {
    montado = await abrir(CARTERA)
    const campo = porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera')
    let elegido = false
    campo.select = () => { elegido = true }
    await entrar(montado.contenedor, campo)
    expect(elegido).toBe(true)
  })

  // F7: toda palabra que muestra «Una cartera» es la revisada: un cambio de texto
  // (una promesa, un consejo) no pasa sin que alguien lo lea y lo acepte
  // (`vitest -u`). Una lista de palabras prohibidas deja pasar lo que no está en
  // la lista («vas a ganar»).
  it('lo que dice la pantalla, caso por caso, es lo revisado', async () => {
    // Cada caso con SU cartera: con la de hoy para todos, la foto mostraba la tabla con
    // BTC y «Cada activo» con NUEVA, justo el error que esta pantalla no puede tener
    // (auditoría de código 06/11, 8). «tres» y «sin_nasdaq» son la de hoy (HOY).
    const DE = {
      tres: CARTERA, sin_nasdaq: CARTERA,
      recortada: `${DE_CERO}&activos=AAPL,GGAL,NUEVA&pesos=50,30,20&local=GGAL&anios=2`,
      vieja: `${DE_CERO}&activos=AAPL,GGAL,PARADA&pesos=50,30,20&local=GGAL&anios=2`,
      todos_restan: `${DE_CERO}&activos=BAJA1,BAJA2&pesos=60,40&anios=1`,
    }
    expect(Object.keys(DE).sort()).toEqual(Object.keys(CASOS).sort())
    const textos = {}
    for (const [caso, res] of Object.entries(CASOS)) {
      simulacion = () => ({ ...res, curva: [] })
      montado = await abrir(DE[caso])
      if (res.disponible) {
        expect(porcentajes(montado.contenedor).map(([a]) => a), caso).toEqual(res.activos.map(a => a.asset))
      }
      textos[caso] = texto(laCartera(montado.contenedor))
      await montado.desmontar()
      montado = null
    }
    expect(textos).toMatchSnapshot()
  })

  // Las que siguen las propuso la auditoría de código del 06/11 (4 y 5): cada una da
  // rojo con su copia rota de la pantalla, y la de antes de ellas quedaba en verde.
  const elTitulo = (c) => todos(c, n => n.atributos?.id === 'sc-respuesta')[0] || null
  const elGrafico = (c) => todos(c, n => n.atributos?.['aria-label'] === 'Cómo habrían ido US$ 100')[0] || null
  function tenue(nodo) {
    for (let n = nodo; n; n = n.parentNode) if ((n.atributos?.class || '').split(/\s+/).includes('opacity-60')) return true
    return false
  }

  it('mientras la suma no da 100, el anterior queda tenue al lado y abajo, y es el mismo', async () => {
    montado = await abrir(CARTERA)
    expect([tenue(elTitulo(montado.contenedor)), tenue(elGrafico(montado.contenedor))]).toEqual([false, false])
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '5')
    await pasaLaPausa()
    const c = montado.contenedor
    expect([tenue(elTitulo(c)), tenue(elGrafico(c))]).toEqual([true, true])
    // Al lado y abajo, el MISMO resultado: +21,4 % en la tabla y US$ 121,4 en el gráfico.
    expect(texto(elTitulo(c).parentNode)).toContain('Esta cartera+21,4%')
    expect(texto(elGrafico(c))).toContain('Esta carteraUS$ 121,4')
  })

  it('mientras llega la respuesta nueva, «Actualizando…» y lo de antes tenue desde el primer momento', async () => {
    montado = await abrir(CARTERA)
    let soltar
    simulacion = () => new Promise(r => { soltar = r })
    // «Repartir» de una cartera que ya sumaba 100: el resultado viejo se veía como el
    // nuevo durante la pausa de 0,4 s (código 06/11, 5).
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Repartir en partes iguales'))
    await esperar()
    const c = montado.contenedor
    expect(texto(laTarjeta(c))).toContain('Actualizando…')
    expect([tenue(elTitulo(c)), tenue(elGrafico(c))]).toEqual([true, true])
    await pasaLaPausa()
    expect(texto(laTarjeta(c))).toContain('Actualizando…')
    await enActo(async () => { soltar({ ...CASOS.todos_restan, curva: [] }) })
    await esperar()
    expect(texto(laTarjeta(c))).not.toContain('Actualizando…')
    expect([tenue(elTitulo(c)), tenue(elGrafico(c))]).toEqual([false, false])
  })

  it('al volver a sumar 100 después de no sumarlo, «Actualizando…» y el anterior tenue mientras llega', async () => {
    montado = await abrir(CARTERA)
    let soltar
    simulacion = () => new Promise(r => { soltar = r })
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de AAPL en la cartera'), '40')   // suma 90
    await pasaLaPausa()
    await escribir(porEtiqueta(montado.contenedor, 'Porcentaje de GGAL en la cartera'), '40')   // otra vez 100
    await pasaLaPausa()
    const c = montado.contenedor
    expect(simulaciones().at(-1)).toBe('GET /backtest/cartera?activos=AAPL,GGAL,BTC&pesos=40,40,20&local=GGAL&anios=2')
    expect(texto(laTarjeta(c))).toContain('Actualizando…')
    expect(texto(laTarjeta(c))).not.toContain('Es el resultado anterior')
    expect([tenue(elTitulo(c)), tenue(elGrafico(c))]).toEqual([true, true])
    await enActo(async () => { soltar(delServidor()) })
    await esperar()
    expect([tenue(elTitulo(c)), tenue(elGrafico(c))]).toEqual([false, false])
  })

  it('al cambiar el período, «Actualizando…» desde el primer momento', async () => {
    montado = await abrir(CARTERA)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, '5 años'))
    await esperar()
    expect(texto(laTarjeta(montado.contenedor))).toContain('Actualizando…')
    expect(tenue(elTitulo(montado.contenedor))).toBe(true)
  })

  it('al sacar todos los activos no queda ningún resultado, ni al lado ni abajo', async () => {
    montado = await abrir(`${DE_CERO}&activos=KO&pesos=100`)
    expect(elTitulo(montado.contenedor)).not.toBeNull()
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Sacar KO'))
    await esperar()
    const c = montado.contenedor
    expect([elTitulo(c), elGrafico(c)]).toEqual([null, null])
    expect(montado.t()).toContain('Cuando los porcentajes sumen 100%')
    // Y el que se suma después no hereda el de antes mientras llega el suyo.
    simulacion = () => new Promise(() => {})
    await sumarConElBuscador(montado, 'MSFT')
    await pasaLaPausa()
    expect([elTitulo(c), elGrafico(c)]).toEqual([null, null])
    expect(todos(c, n => n.atributos?.['aria-busy'] === 'true').length).toBeGreaterThan(0)
  })

  it('si el servidor frena al traer tu cartera de hoy, no ofrece «Reintentar»; con otro error, sí', async () => {
    hoyDelServidor = () => { const e = new Error('Pediste muchas lecturas seguidas. Esperá un minuto.'); e.status = 429; throw e }
    montado = await abrir(CARTERA)
    expect(montado.t()).toContain('No pudimos traer tu cartera de hoy.')
    expect(montado.t()).toContain('Esperá un minuto')
    expect(buscarBoton(montado.contenedor, 'Reintentar')).toBeNull()
    await montado.desmontar()
    hoyDelServidor = () => { const e = new Error('Internal Server Error'); e.status = 500; throw e }
    montado = await abrir(CARTERA)
    expect(buscarBoton(montado.contenedor, 'Reintentar')).not.toBeNull()
  })
})
