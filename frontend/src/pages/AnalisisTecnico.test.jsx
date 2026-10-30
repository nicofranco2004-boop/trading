// «Análisis técnico» en pestañas (recuadro 21, aprobado por Nico el 28/10),
// MONTADO con react-dom como lo ve el usuario: la página pide sus datos al
// servidor (simulado en el borde, `api`), corren sus efectos y se mira lo que
// queda dibujado. Lo que importa:
//   · la dirección decide la pestaña (?tab=lista / ?tab=senales; sin tab,
//     Panorama; Comparar y Mercado se ven y no se tocan);
//   · el Panorama dice el % que manda el servidor (senales_semana.reparto, la
//     cuenta única), los 3 cambios más nuevos de la semana y cuántas señales hay;
//   · la página pide UNA vez lo de la semana y UNA vez tu lista, aunque los
//     usen varias pestañas;
//   · /novedades?tab=senales (los mails viejos) lleva a la pestaña nueva.
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic, enActo } from '../testing/navegadorMinimo'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() }))
vi.mock('../utils/api', () => ({ api }))
vi.mock('../contexts/CurrencyContext', () => ({
  useCurrency: () => ({ valuationDollar: 'mep', costBasis: 'today', currency: 'USD' }),
  pickFinancialRate: (d) => d?.mep?.venta || null,
}))
vi.mock('../hooks/usePushNotifications', () => ({ usePushNotifications: () => null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { tier: 'pro' } }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))

const HOY = new Date().toISOString().slice(0, 10)
const LECTURA = (l = {}) => ({
  ruedas: 760, fecha: HOY, media200: 90, dist_media200: 11, tendencia: 'alcista', pendiente_media200: 2, media50: 95,
  dist_media50: 5, rsi: 60, adx: 30, dist_maximo_12m: -3, anio_completo: true, ...l,
})
const CAMBIO = (asset, tipo, fecha, extra = {}) => ({
  asset, local: false, ficha: asset, tipo, fecha, sentido: 'arriba', etiqueta: 'Tendencia de fondo', tono: 'pos',
  texto: 'pasó arriba de su promedio de 200 días: la tendencia de fondo se volvió alcista.', extra: null,
  tenes: true, watchlist: false, peso: 0.5, tesis: null, ...extra,
})

let pedidos
function servidor() {
  pedidos = []
  api.get.mockImplementation(async (url) => {
    pedidos.push(`GET ${url.split('?')[0]}`)
    if (url === '/positions') return [
      { id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
      { id: 2, broker: 'Schwab', asset: 'KO', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
    ]
    if (url === '/brokers') return [{ id: 1, name: 'Schwab', currency: 'USD' }]
    if (url === '/config') return {}
    if (url === '/dolar') return { mep: { venta: 1500 } }
    if (url === '/watchlist') return { items: [{ symbol: 'TSLA' }] }
    if (url.startsWith('/prices')) return { NVDA: 150, KO: 50 }
    if (url === '/plazos-fijos') return []
    if (url === '/tus-senales') return {
      desde: '2026-10-21', hasta: HOY, canal: 'mail', proximo_resumen: '2026-11-07',
      // LA cuenta del servidor (senales_semana.reparto). 74 y no 75 a propósito:
      // la cuenta vieja de la pantalla (NVDA 1.500 contra KO 500) daba 75; el
      // Panorama tiene que decir lo que manda el servidor.
      alcista: {
        pct: 74,
        grupos: { alcista: { pct: 74, fraccion: 0.74, nombres: ['NVDA'] }, bajista: { pct: 26, fraccion: 0.26, nombres: ['KO'] }, sin: { pct: 0, fraccion: 0, nombres: [] } },
        motivos: [], semana_pasada: { semana: new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10), pct: 70 },
      },
      tenes: { activos: 2, con_cambios: 2 }, watchlist: 1,
      senales: [
        CAMBIO('NVDA', 'media200', HOY),
        CAMBIO('KO', 'media50', HOY, { etiqueta: 'Corto plazo', texto: 'quedó abajo de su promedio de 50 días: el corto plazo se volvió bajista.', sentido: 'abajo', tono: 'neg' }),
        CAMBIO('TSLA', 'maximo_12m', HOY, { tenes: false, watchlist: true, peso: null, etiqueta: 'Máximo del año', texto: 'cerró en su precio más alto de los últimos 12 meses.' }),
        CAMBIO('KO', 'rsi_bajo_30', '2026-10-21', { etiqueta: 'Cayó muy rápido', tono: 'rsi', texto: 'tiene la fuerza (RSI) en 25.' }),
      ],
    }
    throw new Error(`GET inesperado ${url}`)
  })
  api.post.mockImplementation(async (url, body) => {
    pedidos.push(`POST ${url}`)
    if (url === '/tecnico/lista') {
      // Como el servidor: lo que tenés (y cuánto pesa) lo pone él, con su
      // lectura; la pantalla manda sólo lo que sigue.
      const tenencias = [{ asset: 'NVDA', local: false, peso: 0.75, tipo: 'STOCK' }, { asset: 'KO', local: false, peso: 0.25, tipo: 'STOCK' }]
      const todos = [...tenencias, ...body.activos]
      return { tenencias, lecturas: todos.map(a => ({
        asset: a.asset, local: a.local, disponible: true, linea: [{ d: HOY, c: 1 }, { d: HOY, c: 2 }], ultimo_cambio: null,
        lectura: a.asset === 'KO' ? LECTURA({ dist_media200: -5, tendencia: 'bajista', media200: 110 }) : LECTURA(),
      })) }
    }
    throw new Error(`POST inesperado ${url}`)
  })
}

async function abrir(ruta) {
  const { MemoryRouter, Routes, Route, useLocation } = await import('react-router-dom')
  const { default: AnalisisTecnico } = await import('./AnalisisTecnico')
  const { default: Novedades } = await import('./Novedades')
  const donde = { actual: null }
  function Mirar() { donde.actual = useLocation(); return null }
  const m = await montar(h(MemoryRouter, { initialEntries: [ruta] },
    h(Mirar),
    h(Routes, null,
      h(Route, { path: '/analisis-tecnico', element: h(AnalisisTecnico) }),
      h(Route, { path: '/novedades', element: h(Novedades) }),
      h(Route, { path: '*', element: h('div', null, 'otra') }))))
  // Los pedidos se resuelven en varias vueltas (precios después de la cartera).
  for (let i = 0; i < 6; i++) await enActo(async () => { await new Promise(r => setTimeout(r, 0)) })
  return { ...m, donde, t: () => texto(m.contenedor) }
}

const pestanaActiva = (c) => {
  const pila = [c]
  while (pila.length) {
    const n = pila.shift()
    if (n.atributos?.role === 'tab' && n.atributos['aria-selected'] === 'true') return texto(n)
    pila.push(...(n.childNodes || []))
  }
  return null
}

// La primera vez que se importa la página, vite la traduce con todo lo que
// arrastra (la ficha y Novedades): en la suite completa, en paralelo, eso solo
// pasaba los 5 s de la primera prueba. Se hace una vez acá, con tiempo; después
// `vi.resetModules` la vuelve a importar ya traducida.
beforeAll(async () => {
  instalarNavegadorMinimo()
  await import('./AnalisisTecnico')
  await import('./Novedades')
}, 60000)

let montado
beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
  instalarNavegadorMinimo()
  window.scrollTo = () => {}
  servidor()
})
afterEach(async () => { await montado?.desmontar?.(); montado = null; vi.unstubAllGlobals() })

describe('Análisis técnico: las pestañas', () => {
  it('sin ?tab abre Panorama; Comparar y Mercado se ven «Próximamente» y no se tocan', async () => {
    montado = await abrir('/analisis-tecnico')
    expect(pestanaActiva(montado.contenedor)).toBe('Panorama')
    const t = montado.t()
    expect(t).toContain('Comparar')
    expect(t).toContain('Próximamente')
    const comparar = buscarBoton(montado.contenedor, 'Comparar')
    expect(comparar.atributos.disabled).not.toBeUndefined()
    await enActo(async () => clic(montado.contenedor, comparar))
    expect(pestanaActiva(montado.contenedor)).toBe('Panorama')
  })

  it('?tab=lista abre la tabla y ?tab=senales las señales; tocar una pestaña cambia la dirección', async () => {
    montado = await abrir('/analisis-tecnico?tab=lista')
    expect(pestanaActiva(montado.contenedor)).toMatch(/^Tu lista/)
    expect(montado.t()).toContain('Ordenar por')
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Señales de la semana')))
    expect(montado.donde.actual.search).toBe('?tab=senales')
    expect(montado.t()).toContain('Qué cambió esta semana en lo tuyo y en tu watchlist')
    expect(montado.t()).toContain('Crear una alerta técnica en Alertas')
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Panorama')))
    expect(montado.donde.actual.search).toBe('')
  })

  it('una pestaña que no existe o que todavía no está cae en Panorama', async () => {
    montado = await abrir('/analisis-tecnico?tab=comparar')
    expect(pestanaActiva(montado.contenedor)).toBe('Panorama')
  })

  it('la página pide una vez lo de la semana y una vez tu lista, aunque los usen varias pestañas', async () => {
    montado = await abrir('/analisis-tecnico')
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Tu lista')))
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Señales de la semana')))
    expect(pedidos.filter(p => p === 'GET /tus-senales')).toHaveLength(1)
    expect(pedidos.filter(p => p === 'POST /tecnico/lista')).toHaveLength(1)
  })
})

describe('Análisis técnico: el Panorama', () => {
  it('el % del servidor (no el de la pantalla), los 3 cambios más nuevos y cuántas señales hay', async () => {
    montado = await abrir('/analisis-tecnico')
    const t = montado.t()
    expect(t).toContain('74% de tu plata está en activos con tendencia de fondo alcista')
    expect(t).toContain('(la semana pasada, 70%)')
    expect(t).toContain('26% bajista')
    expect(t).toContain('3 cambiosen lo que tenés')        // NVDA, KO del día y KO del RSI
    expect(t).toContain('1 cambioen tu watchlist')         // TSLA
    expect(t).toContain('los 3 más nuevos')
    expect(t).toContain('NVDA pasó arriba de su promedio de 200 días')
    expect(t).toContain('TSLA cerró en su precio más alto')
    // P5 (auditoría A 29/10): el título decía «en lo tuyo» y la lista trae
    // también lo que seguís (TSLA): el título dice las dos cosas.
    expect(t).toContain('Lo que cambió esta semana en lo tuyo y en tu watchlist')
    expect(t).toContain('En tu watchlist')
    expect(t).not.toContain('tiene la fuerza (RSI) en 25')  // el 4.º, más viejo, no va en el Panorama
    expect(t).toContain('Ver las 4 señales de la semana')
    expect(t).toContain('El resumen de la semana te llega el sábado 07/11 a las 10:00')
    expect(t).toContain('3 activos: 2 que tenés y 1 que seguís')
    expect(t).toContain('no es una recomendación para comprar ni vender')
  })
})

describe('las direcciones de antes', () => {
  it('/novedades?tab=senales (los mails viejos) lleva a Análisis técnico → Señales', async () => {
    montado = await abrir('/novedades?tab=senales')
    expect(montado.donde.actual.pathname).toBe('/analisis-tecnico')
    expect(montado.donde.actual.search).toBe('?tab=senales')
  })
})

describe('textoDelResumen', () => {
  it('el próximo sábado y por dónde, o que no llega', async () => {
    const { textoDelResumen } = await import('./AnalisisTecnico')
    // El sábado lo pone el servidor (`proximo_resumen`): acá sólo se escribe.
    expect(textoDelResumen('mail', '2026-10-31')).toBe('El resumen de la semana te llega el sábado 31/10 a las 10:00, por mail.')
    // A9: el sábado a la tarde, ya salido el de hoy, el servidor manda el que viene.
    expect(textoDelResumen('ambos', '2026-11-07')).toBe('El resumen de la semana te llega el sábado 07/11 a las 10:00, por mail y notificación.')
    // Un servidor de antes (sin el dato): no se inventa una fecha.
    expect(textoDelResumen('push', undefined)).toBe('El resumen de la semana te llega los sábados a las 10:00, por notificación.')
    expect(textoDelResumen('no', '2026-10-28')).toBe('No te llega el resumen de los sábados.')
  })
})
