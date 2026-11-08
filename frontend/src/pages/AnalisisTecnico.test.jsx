// «Análisis técnico» en pestañas (recuadro 21, aprobado por Nico el 28/10),
// MONTADO con react-dom como lo ve el usuario: la página pide sus datos al
// servidor (simulado en el borde, `api`), corren sus efectos y se mira lo que
// queda dibujado. Lo que importa:
//   · la dirección decide la pestaña (?tab=lista / ?tab=senales; sin tab,
//     Gráfico); Comparar lleva a su pantalla y Mercado es un «Pronto»;
//   · el Panorama dice el % que manda el servidor (senales_semana.reparto, la
//     cuenta única) con el cambio contra la semana pasada, el mapa de tu
//     cartera, los 3 cambios más nuevos de la semana por día y cuántas señales hay;
//   · la página pide UNA vez lo de la semana y UNA vez tu lista, aunque los
//     usen varias pestañas;
//   · /novedades?tab=senales (los mails viejos) lleva a la pestaña nueva.
import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic, enActo } from '../testing/navegadorMinimo'
import { hoyISO } from '../utils/fecha'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), patch: vi.fn() }))
// Lo real de utils/api (getClientContext: de quién es la copia de los dibujos
// del gráfico, desde la barra) con `api` simulado.
vi.mock('../utils/api', async (original) => ({ ...(await original()), api }))
vi.mock('../contexts/CurrencyContext', () => ({
  useCurrency: () => ({ valuationDollar: 'mep', costBasis: 'today', currency: 'USD' }),
  pickFinancialRate: (d) => d?.mep?.venta || null,
}))
vi.mock('../hooks/usePushNotifications', () => ({ usePushNotifications: () => null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { tier: 'pro' } }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))

// El «hoy» del servidor es el día de acá (`hoy_art_date`, también el `hasta`
// de /tus-senales), no el de Londres (toISOString): de 21 a 24 h ése ya es
// mañana, y el Panorama, que cuenta los días entre `hasta` y la semana pasada,
// leía 8 y no 7.
const HOY = hoyISO()
const LECTURA = (l = {}) => ({
  ruedas: 760, fecha: HOY, media200: 90, dist_media200: 11, tendencia: 'alcista', pendiente_media200: 2, media50: 95,
  dist_media50: 5, rsi: 60, adx: 30, dist_maximo_12m: -3, anio_completo: true, ...l,
})
const CAMBIO = (asset, tipo, fecha, extra = {}) => ({
  asset, local: false, ficha: asset, tipo, fecha, sentido: 'arriba', etiqueta: 'Tendencia de largo plazo', tono: 'pos',
  texto: 'superó su promedio de 200 días: la tendencia de largo plazo pasó a ser alcista.', extra: null,
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
    if (url === '/alerts') return { items: [] }
    if (url === '/tus-senales') return {
      desde: '2026-10-21', hasta: HOY, canal: 'mail', proximo_resumen: '2026-11-07',
      // LA cuenta del servidor (senales_semana.reparto). 74 y no 75 a propósito:
      // la cuenta vieja de la pantalla (NVDA 1.500 contra KO 500) daba 75; el
      // Panorama tiene que decir lo que manda el servidor.
      alcista: {
        pct: 74,
        grupos: { alcista: { pct: 74, fraccion: 0.74, nombres: ['NVDA'] }, bajista: { pct: 26, fraccion: 0.26, nombres: ['KO'] }, sin: { pct: 0, fraccion: 0, nombres: [] } },
        // Hace 7 días contados desde `hasta`, con el mismo reloj: los dos los
        // pone el servidor con el día de acá.
        motivos: [], semana_pasada: { semana: new Date(Date.parse(HOY + 'T00:00:00Z') - 7 * 86400000).toISOString().slice(0, 10), pct: 70 },
      },
      tenes: { activos: 2, con_cambios: 2 }, watchlist: 1,
      senales: [
        CAMBIO('NVDA', 'media200', HOY),
        CAMBIO('KO', 'media50', HOY, { etiqueta: 'Mediano plazo', texto: 'cayó por debajo de su promedio de 50 días: la tendencia de mediano plazo pasó a ser bajista.', sentido: 'abajo', tono: 'neg' }),
        CAMBIO('TSLA', 'maximo_12m', HOY, { tenes: false, watchlist: true, peso: null, etiqueta: 'Máximo del año', corta: 'empezó a marcar máximos del año', texto: 'empezó a marcar máximos del año (cerró en su precio más alto de los últimos 12 meses), después de un mes sin hacerlo.' }),
        CAMBIO('KO', 'rsi_bajo_30', '2026-10-21', { etiqueta: 'Cayó muy rápido', tono: 'rsi', corta: 'cayó muy rápido', texto: 'cayó muy rápido: el impulso (RSI) bajó de 30 y quedó en 25.' }),
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

const conEtiqueta = (c, etiqueta) => {
  const pila = [c]
  while (pila.length) {
    const n = pila.shift()
    if (n.atributos?.['aria-label'] === etiqueta) return true
    pila.push(...(n.childNodes || []))
  }
  return false
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
  it('sin ?tab abre Gráfico (la de entrada desde el 30/10, Nico); Mercado es un «Pronto», no una pestaña', async () => {
    montado = await abrir('/analisis-tecnico')
    expect(pestanaActiva(montado.contenedor)).toBe('Gráfico')
    // Lienzo «1 · Panorama» (30/10): lo que todavía no está es un texto a la
    // derecha de la fila, no una pestaña gris. Comparar sí está (pieza 16).
    expect(montado.t()).toContain('Pronto: Mercado')
    expect(montado.t()).not.toContain('Próximamente')
    expect(buscarBoton(montado.contenedor, 'Mercado')).toBeFalsy()
  })

  it('Comparar lleva a LA pantalla de comparar precios, con lo tuyo que más pesa ya cargado', async () => {
    montado = await abrir('/analisis-tecnico')
    const comparar = buscarBoton(montado.contenedor, 'Comparar')
    expect(comparar.atributos.disabled).toBeUndefined()
    await enActo(async () => clic(montado.contenedor, comparar))
    // NVDA pesa 75 % y KO 25 %: en ese orden.
    expect(montado.donde.actual.pathname).toBe('/fundamentals')
    expect(montado.donde.actual.search).toBe('?vista=precio&cmp=NVDA,KO')
  })

  it('?tab=lista abre la tabla y ?tab=senales las señales; tocar una pestaña cambia la dirección', async () => {
    montado = await abrir('/analisis-tecnico?tab=lista')
    expect(pestanaActiva(montado.contenedor)).toMatch(/^Tu lista/)
    expect(montado.t()).toContain('Ordenar por')
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Señales de la semana')))
    expect(montado.donde.actual.search).toBe('?tab=senales')
    expect(montado.t()).toContain('Qué cambió esta semana en tu cartera y en tu watchlist')
    // Como el lienzo «4 · Señales de la semana»: la agenda y, al costado, el
    // resumen del sábado y la alerta técnica; cada cambio con su campanita.
    for (const x of ['Cambios esta semana', 'A favor · en contra', 'Cambios por día', '¿Querés enterarte en el momento?',
      'Crear una alerta técnica', 'El resumen del sábado']) expect(montado.t()).toContain(x)
    const nodos = (pred) => {
      const out = []
      const pila = [montado.contenedor]
      while (pila.length) { const n = pila.shift(); if (pred(n)) out.push(n); pila.push(...(n.childNodes || [])) }
      return out
    }
    // «hoy» en la pastilla de los cambios de hoy (no el «contados desde hoy» del subtítulo).
    expect(nodos(n => n.nodeName === 'SPAN' && texto(n) === 'hoy' && /bg-data-violet/.test(n.getAttribute?.('class') || '')).length).toBeGreaterThan(0)
    // Tocar una barra con el dedo abre su cartel; tocarla otra vez lo cierra.
    const barra = nodos(n => n.nodeName === 'BUTTON' && /: NVDA /.test(n.getAttribute?.('aria-label') || ''))[0]
    expect(barra).toBeTruthy()
    const toque = async () => enActo(async () => {
      for (const tipo of ['pointerdown', 'click']) {
        const ev = { type: tipo, target: barra, bubbles: true, cancelable: true, button: 0, pointerType: 'touch', defaultPrevented: false,
          timeStamp: Date.now(), preventDefault() { this.defaultPrevented = true }, stopPropagation() {} }
        for (const fn of montado.contenedor.escuchas[tipo] || []) fn(ev)
      }
    })
    const cartel = () => nodos(n => n.nodeName === 'DIV' && /bg-bg-3/.test(n.getAttribute?.('class') || '')).map(texto).join(' ')
    expect(cartel()).toBe('')
    await toque()
    expect(cartel()).toContain('NVDA')
    await toque()
    expect(cartel()).toBe('')
    const campanitas = []
    const pila = [montado.contenedor]
    while (pila.length) {
      const n = pila.shift()
      if (n.nodeName === 'BUTTON' && /^Avisame cuando/.test(n.getAttribute?.('aria-label') || '')) campanitas.push(n)
      pila.push(...(n.childNodes || []))
    }
    // NVDA, KO (dos) y TSLA: los cuatro tipos tienen alerta.
    expect(campanitas).toHaveLength(4)
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Panorama')))
    expect(montado.donde.actual.search).toBe('?tab=panorama')
  })

  it('una pestaña que no existe o que todavía no está cae en la de entrada (Gráfico)', async () => {
    montado = await abrir('/analisis-tecnico?tab=comparar')
    expect(pestanaActiva(montado.contenedor)).toBe('Gráfico')
  })

  it('la página pide una vez lo de la semana y una vez tu lista, aunque los usen varias pestañas', async () => {
    montado = await abrir('/analisis-tecnico')
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Tu lista')))
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, 'Señales de la semana')))
    expect(pedidos.filter(p => p === 'GET /tus-senales')).toHaveLength(1)
    expect(pedidos.filter(p => p === 'POST /tecnico/lista')).toHaveLength(1)
  })
})

describe('Análisis técnico: el Panorama con «Ocultar saldos»', () => {
  it('los 3 cambios más nuevos no se eligen por peso (el servidor ordena cada día por peso)', async () => {
    const { renderToStaticMarkup } = await import('react-dom/server')
    const { MemoryRouter } = await import('react-router-dom')
    const { Panorama } = await import('./AnalisisTecnico')
    const S = (asset, peso) => CAMBIO(asset, 'media200', HOY, { peso, corta: 'superó su promedio de 200 días' })
    // Como lo manda el servidor: de más a menos peso. ZZZ pesa más que todo.
    const semana = { datos: { hasta: HOY, senales: [S('ZZZ', 0.4), S('MMM', 0.3), S('BBB', 0.2), S('AAA', 0.1)] } }
    const dibujar = (hidden) => texto2(renderToStaticMarkup(h(MemoryRouter, null,
      h(Panorama, { lista: { cargando: false }, filas: [], semana, hidden, onVer: () => {}, onPestana: () => {} }))))
    const nombres = (t) => ['AAA', 'BBB', 'MMM', 'ZZZ'].filter(x => t.includes(`${x} superó`))
    expect(nombres(dibujar(false))).toEqual(['BBB', 'MMM', 'ZZZ'])
    expect(nombres(dibujar(true))).toEqual(['AAA', 'BBB', 'MMM'])
  })
})
const texto2 = (html) => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

describe('Análisis técnico: el Panorama', () => {
  it('el % del servidor (no el de la pantalla), los 3 cambios más nuevos y cuántas señales hay', async () => {
    montado = await abrir('/analisis-tecnico?tab=panorama')
    const t = montado.t()
    expect(t).toContain('74%de tu cartera está en activos con tendencia alcista de largo plazo')
    expect(t).toContain('▲ 4 puntos más que la semana pasada')
    expect(t).toContain('26% bajista')
    // Qué lo movió: el cruce del promedio de 200 de lo que tenés (NVDA), con su peso.
    expect(t).toContain('Qué lo movió: NVDA (50% de tu cartera) pasó a alcista el')
    expect(t).toContain('4 cambios · los 3 más nuevos')
    // El mapa: los pesos y la tendencia de Tu lista (NVDA 75 % alcista, KO 25 % bajista).
    expect(t).toContain('Mapa de tu cartera')
    expect(conEtiqueta(montado.contenedor, 'NVDA · 75% de tu cartera · tendencia alcista')).toBe(true)
    expect(conEtiqueta(montado.contenedor, 'KO · 25% de tu cartera · tendencia bajista')).toBe(true)
    // Una campanita por cambio que tiene alerta (la del máximo de TSLA también).
    expect(conEtiqueta(montado.contenedor, 'Avisame cuando cruce su promedio de 200 días')).toBe(true)
    expect(conEtiqueta(montado.contenedor, 'Avisame cuando cierre en su máximo del año')).toBe(true)
    expect(t).toContain('NVDA superó su promedio de 200 días')
    expect(t).toContain('TSLA empezó a marcar máximos del año')
    // P5 (auditoría A 29/10): el título decía «en lo tuyo» y la lista trae
    // también lo que seguís (TSLA): el título dice las dos cosas. Al juntar con
    // Arreglos D (D12) el título es UNO, `TITULO_CAMBIOS` de utils/tusSenales.js.
    expect(t).toContain('Qué cambió esta semana en tu cartera y en tu watchlist')
    expect(t).toContain('En tu watchlist')
    expect(t).not.toContain('el impulso (RSI) bajó de 30 y quedó en 25')  // el 4.º, más viejo, no va en el Panorama
    expect(t).toContain('Ver las 4 señales de la semana')
    expect(t).toContain('El resumen de la semana te llega el sábado 07/11 a las 10:00')
    expect(t).toContain('Tu lista de un vistazo')
    expect(t).toContain('3activos')
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
