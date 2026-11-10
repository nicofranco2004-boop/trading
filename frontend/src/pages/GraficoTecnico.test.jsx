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
//   · pedido con otro nombre (GGAL.BA) abre el tuyo (GGAL);
//   · «Tu cartera» del buscador, con la respuesta REAL del servidor (una cartera
//     grande de varios brokers: backend/tests/test_cartera_del_buscador.py la
//     arma por HTTP y la guarda), muestra todo lo tuyo; y si el pedido falla o
//     tarda lo dice, en vez de quedar vacío (02/11).
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
const recibido = vi.hoisted(() => [])
vi.mock('../components/asset/LecturaTecnica', () => ({
  default: (props) => { recibido.push(props); return null },
}))

const CLAVE = 'rendi_grafico:ana@x.com|propia'
let pedidos
// Lotes de más, por prueba (una cripto cargada como BTC-USD, un nombre raro).
let extra = []
// Lo que contesta el servidor a /positions y /brokers, si la prueba lo cambia.
let delServidor = null
function servidor() {
  pedidos = []
  api.get.mockImplementation(async (url) => {
    pedidos.push(`GET ${url}`)
    if (delServidor?.[url]) return delServidor[url]()
    if (url === '/positions') return [
      { id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
      { id: 2, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION', quantity: 100, invested: 500000, buy_price: 5000, currency: 'ARS', tc_compra: 1200 },
      ...extra,
    ]
    if (url === '/brokers') return [{ id: 1, name: 'Schwab', currency: 'USD' }, { id: 2, name: 'IOL', currency: 'ARS' }, { id: 3, name: 'Binance', currency: 'USD', is_exchange: 1 }]
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
  extra = []
  delServidor = null
  ;({ local: almacen } = instalarNavegadorMinimo())
  // La sesión que guarda la app: de ahí sale el dueño de lo recordado.
  localStorage.setItem('rendi_user', JSON.stringify({ email: 'Ana@X.com' }))
  window.scrollTo = () => {}
  servidor()
})
afterEach(async () => { await montado?.desmontar?.(); montado = null; vi.unstubAllGlobals() })

describe('Análisis técnico → Gráfico', () => {
  it('«Gráfico» es la primera pestaña de la fila y la que se abre al entrar (Nico, 30/10)', async () => {
    montado = await abrir('/analisis-tecnico')
    const pestanas = []
    const pila = [montado.contenedor]
    while (pila.length) {
      const n = pila.shift()
      if (n.atributos?.role === 'tab') pestanas.push(n)
      pila.push(...(n.childNodes || []))
    }
    expect(texto(pestanas[0])).toBe('Gráfico')
    expect(pestanas.find(t => t.atributos['aria-selected'] === 'true') && texto(pestanas.find(t => t.atributos['aria-selected'] === 'true'))).toBe('Gráfico')
  })

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

  it('línea o velas no lo decide la pestaña: es el gráfico de la ficha, con su único default (velas, Nico 02/11)', async () => {
    montado = await abrir('/analisis-tecnico?tab=grafico')
    expect(recibido.length).toBeGreaterThan(0)
    for (const g of recibido) expect(g).not.toHaveProperty('tipo')
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

  it('tu cripto cargada como BTC-USD: pedir BTC abre la tuya, no queda cargando', async () => {
    extra = [{ id: 7, broker: 'Binance', asset: 'BTC-USD', asset_type: 'CRYPTO', quantity: 0.1, invested: 6000, buy_price: 60000 }]
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=BTC')
    expect(recibido.at(-1)?.asset).toBe('BTC-USD')
    expect(recibido.at(-1).lotes.map(l => l.id)).toEqual([7])
    // La dirección dice el tuyo y no rebota a BTC.
    expect(activoDe(montado.donde)).toBe('BTC-USD')
    // Queda el que abrió (el tuyo), no el pedido.
    expect(JSON.parse(almacen.get(CLAVE)).recientes).toEqual(['BTC-USD'])
  })

  it('tu lote con un nombre que no se puede abrir («BRK B»): el gráfico de lo pedido, sin esperar', async () => {
    extra = [{ id: 8, broker: 'Schwab', asset: 'BRK B', asset_type: 'STOCK', quantity: 1, invested: 400, buy_price: 400 }]
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=BRK-B')
    expect(recibido.at(-1)?.asset).toBe('BRK-B')
  })

  it('tu AGRO de Schwab (Adecoagro) no se mete cuando pedís AGRO.BA (Agrometal, BYMA)', async () => {
    extra = [{ id: 9, broker: 'Schwab', asset: 'AGRO', asset_type: 'STOCK', quantity: 50, invested: 500, buy_price: 10 }]
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=AGRO.BA')
    expect(recibido.at(-1)?.asset).toBe('AGRO.BA')
    expect(recibido.at(-1).lotes).toEqual([])
    expect(recibido.at(-1).accionLocal).toBe(true)
    expect(activoDe(montado.donde)).toBe('AGRO.BA')
  })

  it('Esc cierra el buscador también desde un filtro', async () => {
    montado = await abrir('/analisis-tecnico?tab=grafico')
    await clic(montado.contenedor, botonDelActivo(montado.contenedor))
    await tecla(buscarBoton(montado.contenedor, 'Tu cartera'), 'Escape')
    expect(campo(montado.contenedor)).toBeNull()
  })

  it('pedido con otro nombre (GGAL.BA) abre el tuyo (GGAL), con tus lotes', async () => {
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=GGAL.BA')
    expect(recibido.at(-1).asset).toBe('GGAL')
    expect(recibido.at(-1).lotes.map(l => l.id)).toEqual([2])
    expect(recibido.at(-1).accionLocal).toBe(true)
    expect(activoDe(montado.donde)).toBe('GGAL')
    // Un solo atajo para el mismo papel (no «GGAL.BA» al lado de GGAL).
    expect(JSON.parse(almacen.get(CLAVE)).recientes).toEqual(['GGAL'])
  })
})

// La respuesta de GET /api/positions y /api/brokers de una cartera grande, tal
// cual la da el servidor (la escribe backend/tests/test_cartera_del_buscador.py).
const CONTRATO = JSON.parse(readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),
  '../../../backend/tests/fixtures/cartera_del_buscador.json'), 'utf8'))
const opcionesDe = (c, grupo) => {
  const pila = [c]
  while (pila.length) {
    const n = pila.shift()
    if (n.atributos?.role === 'group' && n.atributos?.['aria-label'] === grupo) {
      const out = []
      const p2 = [n]
      while (p2.length) {
        const m = p2.shift()
        if (m.atributos?.role === 'option') out.push(texto(m.childNodes[0]))
        else p2.push(...(m.childNodes || []))
      }
      return out
    }
    pila.push(...(n.childNodes || []))
  }
  return []
}
async function abrirElFiltroTuCartera() {
  montado = await abrir('/analisis-tecnico?tab=grafico&activo=TSLA')
  await clic(montado.contenedor, botonDelActivo(montado.contenedor))
  await esperar()
  await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Tu cartera'))
  await esperar()
}

describe('el buscador del gráfico → «Tu cartera»', () => {
  it('con la respuesta real de una cartera grande de varios brokers, están todos tus activos', async () => {
    delServidor = { '/positions': async () => CONTRATO.positions, '/brokers': async () => CONTRATO.brokers }
    await abrirElFiltroTuCartera()
    expect([...opcionesDe(montado.contenedor, 'Tu cartera')].sort()).toEqual(CONTRATO.esperado)
    expect(montado.t()).not.toContain('No pudimos traer')
  })

  it('si el pedido falla lo dice, con el motivo, y «Reintentar» la trae', async () => {
    let falla = true
    delServidor = {
      '/positions': async () => {
        if (falla) throw Object.assign(new Error('HTTP 500'), { status: 500 })
        return CONTRATO.positions
      },
      '/brokers': async () => CONTRATO.brokers,
    }
    await abrirElFiltroTuCartera()
    expect(montado.t()).toContain('No pudimos traer tu cartera.')
    expect(montado.t()).toContain('Detalle: error 500')
    expect(montado.t()).not.toContain('Escribí el ticker')
    falla = false
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Reintentar'))
    await esperar()
    expect(montado.t()).not.toContain('No pudimos traer')
    expect([...opcionesDe(montado.contenedor, 'Tu cartera')].sort()).toEqual(CONTRATO.esperado)
  })

  it('mientras tarda, dice que la está trayendo; si no llega, avisa y deja reintentar', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'], shouldAdvanceTime: true })
    try {
      delServidor = { '/positions': () => new Promise(() => {}) }
      await abrirElFiltroTuCartera()
      expect(montado.t()).toContain('Trayendo tu cartera…')
      // Con algo escrito, tampoco «No encontramos ese activo»: todavía no llegó.
      await escribir(campo(montado.contenedor), 'ggal')
      expect(montado.t()).toContain('Trayendo tu cartera…')
      expect(montado.t()).not.toContain('No encontramos')
      await enActo(async () => { vi.advanceTimersByTime(15000) })
      await esperar()
      expect(montado.t()).toContain('No pudimos traer tu cartera.')
      expect(montado.t()).toContain('Detalle: tardó más de 15 s')
      expect(buscarBoton(montado.contenedor, 'Reintentar')).not.toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('sin nada con gráfico dice por qué, no «Escribí el ticker»', async () => {
    const cajas = CONTRATO.positions.filter(p => p.is_cash)
    delServidor = { '/positions': async () => cajas }
    await abrirElFiltroTuCartera()
    expect(montado.t()).toContain('Tu cartera no tiene activos todavía.')
    expect(montado.t()).not.toContain('Escribí el ticker')
    await montado.desmontar()
    // Con un fondo (FCI): lo tenés, pero no tiene gráfico.
    delServidor = { '/positions': async () => [...cajas, { ...cajas[0], is_cash: 0, asset: 'FCI:Balanz Ahorro', quantity: 100 }] }
    await abrirElFiltroTuCartera()
    expect(montado.t()).toContain('En tu cartera no hay activos con gráfico: los fondos no tienen.')
  })
})

// ─── La lista al costado del gráfico (Nico, 10/11) ──────────────────────────
// Por la página entera, como en producción: la lista sale del MISMO pedido de
// la página (useListaTecnica: GET /watchlist + POST /tecnico/lista) y lo que se
// toca viaja al servidor (simulado acá, con memoria, en el borde `api`).
describe('la lista al costado del gráfico', () => {
  let lista
  let banderas
  let escrito
  const porEtiqueta = (c, parte) => {
    const pila = [c]
    while (pila.length) {
      const n = pila.shift()
      if ((n.atributos?.['aria-label'] || '').startsWith(parte)) return n
      pila.push(...(n.childNodes || []))
    }
    return null
  }
  const opcionDelMenu = (c, parte) => {
    const pila = [c]
    while (pila.length) {
      const n = pila.shift()
      if (n.atributos?.role === 'menuitemradio' && texto(n).includes(parte)) return n
      pila.push(...(n.childNodes || []))
    }
    return null
  }
  const secciones = (c) => {
    const out = []
    const pila = [c]
    while (pila.length) {
      const n = pila.shift()
      if (n.atributos?.role === 'group' && n.childNodes?.some?.(h => h.nodeName === 'BUTTON' && h.atributos?.['aria-expanded'] != null)) {
        const simbolos = n.childNodes.filter(h => h.atributos?.['data-simbolo']).map(h => h.atributos['data-simbolo'])
        out.push(`${n.atributos['aria-label']}: ${simbolos.join(' ')}`)
      }
      pila.push(...(n.childNodes || []))
    }
    return out
  }
  beforeEach(() => {
    lista = [
      { id: 1, symbol: 'TSLA', bandera: 'azul', orden: 0, price: 375.89, change: -2.16, change_pct: -0.57, mercado: 'us', en_horario: true, cierra: '18:00' },
      { id: 2, symbol: 'TSLA.BA', bandera: 'naranja', orden: 1, price: 39960, change: 1460, change_pct: 3.79, mercado: 'byma', en_horario: true, cierra: '17:00' },
      { id: 3, symbol: 'GGAL.BA', bandera: null, orden: 2, price: 4900, change: -105, change_pct: -2.1, mercado: 'byma', en_horario: false, as_of: '2026-11-07' },
    ]
    banderas = { azul: 'EE.UU.', naranja: 'CEDEARs' }
    escrito = []
    const conNombres = () => ['azul', 'naranja', 'verde', 'violeta', 'rosa', 'cian', 'rojo'].map(id => ({ id, nombre: banderas[id] || null }))
    delServidor = { '/watchlist': async () => ({ items: lista.map(x => ({ ...x })), banderas: conNombres() }) }
    api.post.mockImplementation(async (url, body) => {
      if (url === '/tecnico/lista') return { tenencias: [{ asset: 'TSLA', local: false, peso: 0.2, tipo: 'CEDEAR' }], lecturas: [] }
      if (url === '/watchlist') {
        escrito.push(['POST', url, body])
        lista.push({ id: lista.length + 1, symbol: body.symbol, bandera: body.bandera || null, orden: lista.length, price: 268.47, change: 1.12, change_pct: 0.42 })
        return { ok: true, symbol: body.symbol }
      }
      throw new Error(`POST inesperado ${url}`)
    })
    api.patch.mockImplementation(async (url, body) => {
      escrito.push(['PATCH', url, body])
      const s = decodeURIComponent(url.split('/').pop())
      lista = lista.map(x => (x.symbol === s ? { ...x, bandera: body.bandera } : x))
      return { ok: true }
    })
    api.put.mockImplementation(async (url, body) => { escrito.push(['PUT', url, body]); return { ok: true } })
    // Abierta, como la deja la compu.
    almacen.set('rendi_grafico_lista', JSON.stringify({ abierta: true }))
  })

  it('agrupa por bandera con el nombre de cada una, marca lo que tenés y tocar un renglón lo abre en el gráfico', async () => {
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=NVDA')
    expect(secciones(montado.contenedor)).toEqual(['EE.UU.: TSLA', 'CEDEARs: TSLA.BA', 'Sin bandera: GGAL.BA'])
    // Tenés TSLA en CEDEARs: el punto va en el CEDEAR, no en la de Nueva York.
    expect(porEtiqueta(montado.contenedor, 'TSLA, Tesla, CEDEAR').atributos['aria-label']).toContain('lo tenés')
    expect(porEtiqueta(montado.contenedor, 'TSLA, Tesla, Acción de EE.UU.').atributos['aria-label']).not.toContain('lo tenés')
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'TSLA, Tesla, CEDEAR'))
    await esperar()
    expect(activoDe(montado.donde)).toBe('TSLA.BA')
    expect(recibido.at(-1).asset).toBe('TSLA.BA')
    expect(porEtiqueta(montado.contenedor, 'TSLA, Tesla, CEDEAR').atributos['aria-current']).toBe('true')
  })

  it('la bandera se cambia en el menú, se guarda en la cuenta y el renglón cambia de grupo', async () => {
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=NVDA')
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Bandera de GGAL'))
    await clic(montado.contenedor, opcionDelMenu(montado.contenedor, 'EE.UU.'))
    await esperar()
    expect(escrito).toContainEqual(['PATCH', '/watchlist/GGAL.BA', { bandera: 'azul' }])
    expect(secciones(montado.contenedor)).toEqual(['EE.UU.: TSLA GGAL.BA', 'CEDEARs: TSLA.BA'])
    // El nombre de una bandera, con el lápiz.
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Bandera de TSLA (CEDEAR)'))
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Cambiarle el nombre a la bandera rosa'))
    await escribir(porEtiqueta(montado.contenedor, 'Nombre de la bandera rosa'), '  Dividendos ')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Listo'))
    await esperar()
    expect(escrito).toContainEqual(['PUT', '/watchlist/banderas/rosa', { nombre: 'Dividendos' }])
  })

  it('si el servidor no guarda la bandera, vuelve como estaba y lo dice', async () => {
    api.patch.mockImplementation(async () => { throw Object.assign(new Error('HTTP 500'), { status: 500 }) })
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=NVDA')
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Bandera de GGAL'))
    await clic(montado.contenedor, opcionDelMenu(montado.contenedor, 'EE.UU.'))
    await esperar()
    expect(secciones(montado.contenedor)).toEqual(['EE.UU.: TSLA', 'CEDEARs: TSLA.BA', 'Sin bandera: GGAL.BA'])
    expect(montado.t()).toContain('No pudimos guardar la bandera.')
  })

  it('«+» busca con el buscador del gráfico: «apple» ofrece las dos, y lo que agregás entra con la bandera que mirás', async () => {
    lista.push({ id: 9, symbol: 'AAPL.BA', bandera: 'naranja', orden: 3, price: 17850, change: 150, change_pct: 0.85 })
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=NVDA')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'CEDEARs'))
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Buscar y agregar un activo'))
    expect(montado.t()).toContain('Lo que agregues entra con la bandera «CEDEARs», la que estás mirando.')
    await escribir(montado.contenedor.ownerDocument.getElementById?.('lista-buscar') || porEtiqueta(montado.contenedor, 'Buscar un activo') || campo(montado.contenedor), 'apple')
    // El CEDEAR ya está; la acción de Nueva York, para agregar.
    expect(porEtiqueta(montado.contenedor, 'Agregar AAPL (CEDEAR)')).toBeNull()
    expect(porEtiqueta(montado.contenedor, 'Agregar AAPL (Acción de EE.UU.)')).not.toBeNull()
    expect(montado.t()).toContain('En tu lista')
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Agregar AAPL (Acción de EE.UU.)'))
    await esperar()
    expect(escrito).toContainEqual(['POST', '/watchlist', { symbol: 'AAPL', bandera: 'naranja' }])
    // La página volvió a pedir la lista (la avisó a toda la app) y AAPL ya está.
    expect(porEtiqueta(montado.contenedor, 'Agregar AAPL (Acción de EE.UU.)')).toBeNull()
  })

  it('«Cartera»: lo que tenés, por tipo y por lo que más pesa; la bandera es la de tu lista; tocar lo abre', async () => {
    const pedidosCartera = []
    const anterior = delServidor['/watchlist']
    delServidor = {
      '/watchlist': anterior,
      '/watchlist/cartera': async () => {
        pedidosCartera.push(1)
        return { items: [
          { symbol: 'NVDA', cotiza: 'NVDA', asset_type: 'STOCK', local: false, price: 167.51, change: -11.16, change_pct: -6.25, mercado: 'us', en_horario: true, cierra: '18:00' },
          { symbol: 'TSLA', cotiza: 'TSLA.BA', asset_type: 'CEDEAR', local: false, price: 39960, change: 1460, change_pct: 3.79, mercado: 'byma', en_horario: true, cierra: '17:00' },
          { symbol: 'GGAL', cotiza: 'GGAL.BA', asset_type: 'ACCION', local: true, price: 4900, change: -105, change_pct: -2.1, mercado: 'byma', en_horario: false },
        ] }
      },
    }
    api.post.mockImplementation(async (url) => {
      if (url === '/tecnico/lista') return { tenencias: [
        { asset: 'GGAL', local: true, peso: 0.1, tipo: 'ACCION' }, { asset: 'NVDA', local: false, peso: 0.5, tipo: 'STOCK' },
        { asset: 'TSLA', local: false, peso: 0.2, tipo: 'CEDEAR' },
      ], lecturas: [] }
      throw new Error(`POST inesperado ${url}`)
    })
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=NVDA')
    // No se pide hasta elegirla.
    expect(pedidosCartera).toEqual([])
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Cartera'))
    await esperar()
    expect(pedidosCartera).toHaveLength(1)
    expect(secciones(montado.contenedor)).toEqual(['Acciones de EE.UU.: NVDA', 'CEDEARs: TSLA', 'Acciones argentinas: GGAL'])
    // El CEDEAR de tu cartera es el TSLA.BA de tu lista: lleva su bandera.
    expect(porEtiqueta(montado.contenedor, 'Bandera de TSLA (CEDEAR)').atributos['aria-label']).toContain('CEDEARs')
    // GGAL de BYMA es el GGAL.BA de tu lista (sin bandera); NVDA no la seguís: sin banderita.
    expect(porEtiqueta(montado.contenedor, 'Bandera de NVDA')).toBeNull()
    expect(porEtiqueta(montado.contenedor, 'TSLA, Tesla, CEDEAR: $ 39.960')).not.toBeNull()
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'GGAL,'))
    await esperar()
    expect(activoDe(montado.donde)).toBe('GGAL')
    // Se acuerda de qué estabas viendo.
    expect(JSON.parse(almacen.get('rendi_grafico_lista')).fuente).toBe('cartera')
    // Sin «+» en tu cartera: se agrega desde la lista.
    expect(porEtiqueta(montado.contenedor, 'Buscar y agregar un activo')).toBeNull()
  })

  it('cerrada, el gráfico queda solo; se acuerda al volver a entrar', async () => {
    montado = await abrir('/analisis-tecnico?tab=grafico&activo=NVDA')
    await clic(montado.contenedor, porEtiqueta(montado.contenedor, 'Cerrar tu lista'))
    expect(JSON.parse(almacen.get('rendi_grafico_lista')).abierta).toBe(false)
    expect(porEtiqueta(montado.contenedor, 'Abrir tu lista')).not.toBeNull()
  })
})
