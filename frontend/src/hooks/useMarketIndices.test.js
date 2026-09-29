import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// La cinta de arriba y las tarjetas del inicio leen las cotizaciones de UN
// solo lugar. Se prueba el camino de producción: la respuesta entra por
// api.get('/home/indices'), igual que en la app.
vi.mock('../utils/api', () => ({ api: { get: vi.fn() } }))
vi.mock('../utils/demo', () => ({ isDemoMode: vi.fn(() => false) }))

import { api } from '../utils/api'
import { isDemoMode } from '../utils/demo'
import {
  REFRESH_MS, refreshMarketIndices, subscribeMarketIndices, conDato,
  _resetMarketIndices, _getMarketIndicesState,
} from './useMarketIndices'

const SPX = { symbol: '^GSPC', label: 'S&P 500', kind: 'index', price: 5840.5, change_pct: 0.42 }
const MERV = { symbol: '^MERV', label: 'Merval', kind: 'index', price: 2150420, change_pct: -0.85 }

let visibilidad
function stubDocument() {
  visibilidad = { handler: null }
  globalThis.document = {
    visibilityState: 'visible',
    addEventListener: vi.fn((ev, fn) => { if (ev === 'visibilitychange') visibilidad.handler = fn }),
    removeEventListener: vi.fn(),
  }
}

beforeEach(() => {
  _resetMarketIndices()
  api.get.mockReset()
  isDemoMode.mockReturnValue(false)
  stubDocument()
})
afterEach(() => {
  vi.useRealTimers()
  delete globalThis.document
})

describe('useMarketIndices — un solo dueño de las cotizaciones', () => {
  it('dos pedidos a la vez son UN pedido al servidor', async () => {
    api.get.mockResolvedValue({ items: [SPX] })
    await Promise.all([refreshMarketIndices(), refreshMarketIndices()])
    expect(api.get).toHaveBeenCalledTimes(1)
    expect(api.get).toHaveBeenCalledWith('/home/indices')
    expect(_getMarketIndicesState().items).toEqual([SPX])
    expect(_getMarketIndicesState().loading).toBe(false)
  })

  it('si un refresco falla, la cinta se queda con lo que tenía', async () => {
    api.get.mockResolvedValueOnce({ items: [SPX, MERV] })
    await refreshMarketIndices()
    api.get.mockRejectedValueOnce(new Error('red caída'))
    await refreshMarketIndices()
    const st = _getMarketIndicesState()
    expect(st.items).toEqual([SPX, MERV])
    expect(st.error).toBe('red caída')
  })

  it('el segundo componente que se suscribe NO vuelve a pedir si el dato está fresco', async () => {
    api.get.mockResolvedValue({ items: [SPX] })
    const off1 = subscribeMarketIndices(() => {})
    await refreshMarketIndices()
    const off2 = subscribeMarketIndices(() => {})
    expect(api.get).toHaveBeenCalledTimes(1)
    off1(); off2()
  })

  it('se refresca sola cada 5 minutos, y no con la pestaña oculta', async () => {
    vi.useFakeTimers()
    api.get.mockResolvedValue({ items: [SPX] })
    const off = subscribeMarketIndices(() => {})
    await vi.advanceTimersByTimeAsync(0)
    expect(api.get).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(REFRESH_MS)
    expect(api.get).toHaveBeenCalledTimes(2)
    document.visibilityState = 'hidden'
    await vi.advanceTimersByTimeAsync(REFRESH_MS)
    expect(api.get).toHaveBeenCalledTimes(2)
    off()
    // Sin nadie mirando, el reloj se apaga.
    document.visibilityState = 'visible'
    await vi.advanceTimersByTimeAsync(REFRESH_MS * 3)
    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('al volver a la pestaña con el dato viejo, lo pide en el momento', async () => {
    vi.useFakeTimers()
    api.get.mockResolvedValue({ items: [SPX] })
    const off = subscribeMarketIndices(() => {})
    await vi.advanceTimersByTimeAsync(0)
    document.visibilityState = 'hidden'
    await vi.advanceTimersByTimeAsync(REFRESH_MS + 1)
    expect(api.get).toHaveBeenCalledTimes(1)
    document.visibilityState = 'visible'
    visibilidad.handler()
    await vi.advanceTimersByTimeAsync(0)
    expect(api.get).toHaveBeenCalledTimes(2)
    off()
  })

  it('entrar al demo sin recargar descarta las cotizaciones reales', async () => {
    api.get.mockResolvedValueOnce({ items: [SPX] })
    const off = subscribeMarketIndices(() => {})
    await refreshMarketIndices()
    expect(_getMarketIndicesState().items).toEqual([SPX])

    isDemoMode.mockReturnValue(true)
    let resolver
    api.get.mockReturnValueOnce(new Promise(r => { resolver = r }))
    visibilidad.handler()
    // Mientras llega la del demo, no se muestra la real.
    expect(_getMarketIndicesState().items).toEqual([])
    expect(_getMarketIndicesState().loading).toBe(true)
    resolver({ items: [MERV] })
    await refreshMarketIndices()
    expect(_getMarketIndicesState().items).toEqual([MERV])
    off()
  })
})

describe('conDato — lo que la cinta puede mostrar', () => {
  it('saca las cotizaciones que no llegaron (precio y variación en null)', () => {
    const vacia = { symbol: 'GC=F', label: 'Oro', kind: 'commodity', price: null, change_pct: null }
    expect(conDato([SPX, vacia, MERV])).toEqual([SPX, MERV])
  })
  it('con sólo uno de los dos datos, se muestra', () => {
    const soloPrecio = { ...SPX, change_pct: null }
    expect(conDato([soloPrecio])).toEqual([soloPrecio])
  })
  it('sin lista, vacío', () => {
    expect(conDato(undefined)).toEqual([])
  })
})
