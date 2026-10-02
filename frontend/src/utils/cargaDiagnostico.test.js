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

import { benchPedido, BENCH_EN_CERO } from './insightsModel'
import { coberturaDePrecios, COBERTURA_MINIMA } from './valuation'

describe('benchPedido — la curva se pide SIEMPRE, con un benchmark que el servidor tiene', () => {
  it('cada opción del selector con su clave; Pesos cash (sin serie allá) con el S&P', () => {
    expect(benchPedido('inflation')).toBe('inflation_ar')
    expect(benchPedido('tbill')).toBe('shv')
    expect(benchPedido('pesos_cash')).toBe('sp500')   // antes: undefined → no se pedía nada
    expect(BENCH_EN_CERO.has('pesos_cash')).toBe(true)  // y su línea va en 0 %, no la del S&P
  })
  it('pasar de Inflación a Pesos cash: la respuesta de inflación ya no se acepta', () => {
    const vista = { moneda: 'ars', bench: benchPedido('pesos_cash'), modo: 'certero' }
    expect(perfEsDeLaVista({ moneda: 'ars', benchmark_key: 'inflation_ar', modo: 'certero' }, vista)).toBe(false)
    expect(perfEsDeLaVista({ moneda: 'ars', benchmark_key: 'sp500', modo: 'certero' }, vista)).toBe(true)
  })
})

describe('coberturaDePrecios — ¿alcanza para guardar o mandar un valor? (la regla del cron)', () => {
  const brokers = [{ name: 'Schwab', currency: 'USD' }, { name: 'Cocos', currency: 'ARS' }, { name: 'Binance', currency: 'USDT' }]
  const tc = { tcValuacion: 1400 }
  const pos = [
    { asset: 'AAPL', broker: 'Schwab', invested: 9700 },
    { asset: 'FCI:RARO', broker: 'Schwab', invested: 300 },        // nunca cotiza
    { asset: 'USD', broker: 'Schwab', is_cash: 1, invested: 5000 },
  ]
  it('un activo chico que nunca cotiza no apaga nada (97 %)', () => {
    const c = coberturaDePrecios(pos, { AAPL: 230 }, brokers, tc)
    expect(c).toBeCloseTo(0.97, 5)
    expect(c >= COBERTURA_MINIMA).toBe(true)
  })
  it('Yahoo caído para lo grande: no alcanza', () => {
    expect(coberturaDePrecios(pos, {}, brokers, tc) >= COBERTURA_MINIMA).toBe(false)
  })
  // El peso es el costo en USD del LOTE (el motor), no según el broker: los
  // dos casos cruzados que el cron ya había corregido (snapshots_job.py).
  it('lote en PESOS en cuenta USD: pesa sus dólares, no sus pesos (decía 99,9 %; es 33 %)', () => {
    const cruzado = [
      { asset: 'GGAL', broker: 'Schwab', currency: 'ARS', invested: 14_000_000 },  // ~US$10.000, con precio
      { asset: 'AAPL', broker: 'Schwab', invested: 20_000 },                        // sin precio
    ]
    const c = coberturaDePrecios(cruzado, { 'GGAL.BA': 7000 }, brokers, tc)
    expect(c).toBeCloseTo(1 / 3, 2)
    expect(c >= COBERTURA_MINIMA).toBe(false)
  })
  it('lote en DÓLARES en broker en pesos: pesa sus dólares, no ÷MEP (decía 97,9 %; es 3 %)', () => {
    const cruzado = [
      { asset: 'AL30', broker: 'Cocos', currency: 'USD', invested: 30_000 },        // sin precio
      { asset: 'GGAL', broker: 'Cocos', invested: 1_400_000 },                      // ~US$1.000, con precio
    ]
    const c = coberturaDePrecios(cruzado, { 'GGAL.BA': 7000 }, brokers, tc)
    expect(c).toBeCloseTo(1 / 31, 2)
  })
  it('lo que nunca se cotiza (USDT, broker desconocido) no cuenta en contra', () => {
    const conUsdt = [
      { asset: 'USDT', broker: 'Binance', invested: 2000 },
      { asset: 'AAPL', broker: 'Schwab', invested: 8000 },
      { asset: 'MSFT', broker: 'BrokerBorrado', invested: 5000 },
    ]
    expect(coberturaDePrecios(conUsdt, { AAPL: 230 }, brokers, tc)).toBe(1)   // decía 0,80
  })
  it('sin dólar y con algo en pesos: 0 (no se puede pesar)', () => {
    expect(coberturaDePrecios([{ asset: 'GGAL', broker: 'Cocos', invested: 1000 }], { 'GGAL.BA': 5000 }, brokers, { tcValuacion: 0 })).toBe(0)
  })
  it('sin nada que cotizar: 1', () => {
    expect(coberturaDePrecios([{ asset: 'USD', broker: 'Schwab', is_cash: 1 }], {}, brokers, tc)).toBe(1)
  })
})
