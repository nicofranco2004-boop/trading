import { describe, it, expect, vi, afterEach } from 'vitest'
import { cargarDiagnostico, getCompartido, TOPE_PRECIOS_MS } from './cargaDiagnostico'
import { imprescindiblesDe, queFalta, pasosDiagnostico } from './cargaPorPasos'
import { perfEsDeLaVista } from './insightsModel'

// El MISMO camino que la pantalla (pages/Insights → loadAll): un `get` de
// mentira que contesta, demora o falla cada pedido, y los relojes de mentira
// para el tope de los precios.

const RESPUESTAS = {
  '/monthly': [
    { broker: 'Cocos', year: 2026, month: 8 }, { broker: 'global', year: 2026, month: 8 },
    { broker: 'Cocos', year: 2026, month: 9 }, { broker: 'global', year: 2026, month: 9 },
  ],
  '/positions': [{ asset: 'AAPL', broker: 'Schwab' }, { asset: 'USD', broker: 'Schwab', is_cash: 1 }],
  '/brokers': [{ name: 'Schwab', currency: 'USD' }],
  '/benchmarks': {}, '/snapshots?days=3650': [], '/dolar': {}, '/operations': [],
  '/insights/commissions': {}, '/auth/investor-profile': { goal: 'growth' },
}
const PRECIOS = { AAPL: 230 }

// `trato[url]`: 'nunca' (no vuelve), 'falla', o nada (contesta ya).
function armarGet(trato = {}) {
  const pedidos = []
  const get = vi.fn((url) => {
    pedidos.push(url)
    const clave = url.startsWith('/prices') ? '/prices' : url
    if (trato[clave] === 'nunca') return new Promise(() => {})
    if (trato[clave] === 'falla') return Promise.reject(new Error('503'))
    if (clave === '/prices') return Promise.resolve(PRECIOS)
    return Promise.resolve(RESPUESTAS[url])
  })
  return { get, pedidos }
}
const simbolos = (pos) => pos.filter(p => !p.is_cash).map(p => p.asset).join(',')

afterEach(() => { vi.useRealTimers() })

describe('cargarDiagnostico — los precios no frenan la página para siempre', () => {
  it('precios a tiempo: vienen con la carga', async () => {
    const { get } = armarGet()
    const r = await cargarDiagnostico({ get, simbolos })
    expect(r.falta).toBe(false)
    expect(r.precios).toEqual(PRECIOS)
    expect(r.preciosTarde).toBe(null)
  })
  it('precios que no vuelven: pasado el tope la página sale sin ellos, con la promesa para después', async () => {
    vi.useFakeTimers()
    const { get } = armarGet({ '/prices': 'nunca' })
    const marcas = {}
    let listo = null
    cargarDiagnostico({ get, simbolos, marcar: (p, v = true) => { marcas[p] = v } }).then(r => { listo = r })
    await vi.advanceTimersByTimeAsync(TOPE_PRECIOS_MS - 1)
    expect(listo).toBe(null)                      // todavía espera
    await vi.advanceTimersByTimeAsync(1)
    expect(listo.falta).toBe(false)
    expect(listo.precios).toBe(null)
    expect(listo.preciosTarde).toBeInstanceOf(Promise)
    expect(listo.datos.positions).toHaveLength(2)
    expect(marcas.prices).toBeUndefined()           // el cargador no tilda lo que no llegó
  })
  it('el cargador cuenta MESES, no renglones de /monthly', async () => {
    const { get } = armarGet()
    const marcas = {}
    await cargarDiagnostico({ get, simbolos, marcar: (p, v = true) => { marcas[p] = v } })
    expect(marcas.monthly).toBe(2)                  // 4 renglones, 2 meses
    expect(pasosDiagnostico(marcas).find(x => x.id === 'historial').detalle).toBe('2 meses')
    expect(marcas.positions).toBe(1)                // el efectivo no es un activo
  })
})

describe('cargarDiagnostico — sin lo imprescindible no se calcula', () => {
  it('/brokers caído: falta, sin esperar el tope de los precios y sin pedirlos', async () => {
    vi.useFakeTimers()
    const { get, pedidos } = armarGet({ '/brokers': 'falla' })
    const marcas = {}
    let listo = null
    cargarDiagnostico({ get, simbolos, marcar: (p, v = true) => { marcas[p] = v } }).then(r => { listo = r })
    await vi.advanceTimersByTimeAsync(0)
    expect(listo.falta).toBe(true)                  // sin avanzar los 8 s
    expect(pedidos.some(u => u.startsWith('/prices'))).toBe(false)
    expect(queFalta(marcas)).toEqual(['tus brokers'])
  })
  it('/monthly caído: también, y en el acto (antes esperaba hasta 8 s para mostrar el error)', async () => {
    vi.useFakeTimers()
    const { get } = armarGet({ '/monthly': 'falla', '/prices': 'nunca' })
    let listo = null
    cargarDiagnostico({ get, simbolos }).then(r => { listo = r })
    await vi.advanceTimersByTimeAsync(0)
    expect(listo?.falta).toBe(true)
  })
  it('el test de inversor: imprescindible en el Perfil, no en Diagnóstico', async () => {
    const { get } = armarGet({ '/auth/investor-profile': 'falla' })
    expect((await cargarDiagnostico({ get, simbolos, imprescindibles: imprescindiblesDe({ perfil: true }) })).falta).toBe(true)
    expect((await cargarDiagnostico({ get, simbolos, imprescindibles: imprescindiblesDe({ perfil: false }) })).falta).toBe(false)
  })
})

describe('cargarDiagnostico — la curva de Performance la pide un solo lugar', () => {
  it('la carga NO pide /insights/performance (lo pide el efecto con el benchmark elegido) y espera su primera respuesta', async () => {
    const { get, pedidos } = armarGet()
    let soltar
    const primeraPerf = new Promise(r => { soltar = r })
    let listo = null
    cargarDiagnostico({ get, simbolos, esperarTambien: [primeraPerf] }).then(r => { listo = r })
    await new Promise(r => setTimeout(r, 0))
    expect(listo).toBe(null)                        // espera a la curva
    soltar()
    await new Promise(r => setTimeout(r, 0))
    expect(listo.falta).toBe(false)
    expect(pedidos.some(u => u.includes('/insights/performance'))).toBe(false)
  })
  it('una respuesta de otro benchmark, modo o moneda no se dibuja', () => {
    const vista = { moneda: 'ars', bench: 'inflation_ar', modo: 'certero' }
    expect(perfEsDeLaVista({ moneda: 'ars', benchmark_key: 'inflation_ar', modo: 'certero' }, vista)).toBe(true)
    expect(perfEsDeLaVista({ moneda: 'ars', benchmark_key: 'sp500', modo: 'certero' }, vista)).toBe(false)
    expect(perfEsDeLaVista({ moneda: 'usd', benchmark_key: 'inflation_ar', modo: 'certero' }, vista)).toBe(false)
    expect(perfEsDeLaVista({ moneda: 'ars', benchmark_key: 'inflation_ar', modo: 'estimado' }, vista)).toBe(false)
    expect(perfEsDeLaVista({ moneda: 'ars' }, vista)).toBe(true)        // sin marca: no se rechaza
    expect(perfEsDeLaVista(null, vista)).toBe(false)
  })
})

describe('reintento — los precios en camino no se piden dos veces', () => {
  it('getCompartido: el mismo pedido en curso se comparte; terminado, se vuelve a pedir', async () => {
    let soltar
    const get = vi.fn(() => new Promise(r => { soltar = r }))
    const g = getCompartido(get)
    const a = g('/prices?symbols=AAPL')
    const b = g('/prices?symbols=AAPL')
    expect(get).toHaveBeenCalledTimes(1)
    expect(a).toBe(b)
    soltar({ AAPL: 1 })
    await a
    g('/prices?symbols=AAPL')
    expect(get).toHaveBeenCalledTimes(2)
  })
  it('una carga que se reintenta con los precios de la primera todavía bajando: UNA descarga', async () => {
    vi.useFakeTimers()
    const { get, pedidos } = armarGet({ '/prices': 'nunca' })
    const g = getCompartido(get)
    cargarDiagnostico({ get: g, simbolos })
    await vi.advanceTimersByTimeAsync(TOPE_PRECIOS_MS)
    cargarDiagnostico({ get: g, simbolos })
    await vi.advanceTimersByTimeAsync(TOPE_PRECIOS_MS)
    expect(pedidos.filter(u => u.startsWith('/prices'))).toHaveLength(1)
    expect(pedidos.filter(u => u === '/positions')).toHaveLength(2)   // lo demás sí se pide de nuevo
  })
})
