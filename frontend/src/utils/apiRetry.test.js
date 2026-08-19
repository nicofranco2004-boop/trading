// Reintento ante errores de GATEWAY (502/503/504).
//
// Reporte real (2026-08-08): un usuario vio "HTTP 502" al subir sus archivos.
// No era su archivo ni sus datos: el backend estaba reiniciando por un deploy.
// Esos errores son transitorios y duran segundos, así que se reintentan solos —
// pero SOLO donde repetir el pedido es inofensivo (GET y los preview, que
// arman un borrador). Un confirm repetido duplicaría la importación.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Se importa la implementación REAL. Antes este archivo se copiaba la función y
// probaba a la copia: la política podía romperse en api.js y los tests seguían
// en verde (así sobrevivió el bug de AbortError de más abajo). Por eso la
// política vive en su propio módulo, sin los side-effects de localStorage/window
// que impedían importar api.js desde un test.
import { withGatewayRetry, conJitter, fueCancelado, RETRY_DELAYS_MS } from './gatewayRetry'

const isPreview = (path) => /\/preview(\?|$)/.test(path)

describe('reintento ante 502/503/504', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  const run = async (fn) => {
    const p = fn()
    await vi.runAllTimersAsync()
    return p
  }

  it('un 502 pasajero se resuelve solo en el siguiente intento', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ status: 502 })
      .mockResolvedValueOnce({ status: 200 })
    const res = await run(() => withGatewayRetry(fetchMock))
    expect(res.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('aguanta un reinicio entero y no reintenta para siempre', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ status: 502 })
    const res = await run(() => withGatewayRetry(fetchMock))
    expect(res.status).toBe(502)                       // devuelve el error al final
    expect(fetchMock).toHaveBeenCalledTimes(RETRY_DELAYS_MS.length + 1)
  })

  it('una caída de red también reintenta', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({ status: 200 })
    const res = await run(() => withGatewayRetry(fetchMock))
    expect(res.status).toBe(200)
  })

  it('un error del backend NO se reintenta (no es de infraestructura)', async () => {
    for (const status of [400, 401, 404, 422, 429, 500]) {
      const fetchMock = vi.fn().mockResolvedValue({ status })
      const res = await run(() => withGatewayRetry(fetchMock))
      expect(res.status).toBe(status)
      expect(fetchMock).toHaveBeenCalledTimes(1)
    }
  })

  it('solo los preview se reintentan; confirmar una importación no', () => {
    expect(isPreview('/imports/preview')).toBe(true)
    expect(isPreview('/imports/tenencia/preview')).toBe(true)
    // Lo que aplica cambios queda afuera: repetirlo duplicaría datos.
    expect(isPreview('/imports/confirm')).toBe(false)
    expect(isPreview('/imports/tenencia/confirm')).toBe(false)
    expect(isPreview('/imports/preview/confirm')).toBe(false)
  })
})

// Cancelar no es lo mismo que "no hay servidor". Cuando el que llama aborta
// —navegar a otra pantalla, un unmount, un AbortController— fetch rechaza con un
// DOMException 'AbortError', que caía en el mismo catch que una caída de red:
// dormía y reintentaba hasta 3 veces más. La cancelación tardaba ~8,3s en surtir
// efecto y mientras tanto seguían saliendo pedidos que ya no le importan a nadie.
describe('cancelar corta el reintento en el acto', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  const abortError = () => {
    // El DOMException real del navegador; en Node se replica el .name.
    const e = new Error('The user aborted a request.')
    e.name = 'AbortError'
    return e
  }

  it('no reintenta un pedido abortado', async () => {
    const fetchMock = vi.fn().mockRejectedValue(abortError())
    const p = withGatewayRetry(fetchMock)
    await expect(p).rejects.toThrow(/aborted/)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('devuelve el AbortError tal cual, para que el llamador lo distinga', async () => {
    const fetchMock = vi.fn().mockRejectedValue(abortError())
    await expect(withGatewayRetry(fetchMock)).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('si el signal ya está abortado tampoco insiste', async () => {
    const ac = new AbortController()
    ac.abort()
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(withGatewayRetry(fetchMock, { signal: ac.signal })).rejects.toThrow()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('un 502 con el signal abortado se devuelve sin dormir', async () => {
    const ac = new AbortController()
    ac.abort()
    const fetchMock = vi.fn().mockResolvedValue({ status: 502 })
    const res = await withGatewayRetry(fetchMock, { signal: ac.signal })
    expect(res.status).toBe(502)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('una caída de red de verdad SIGUE reintentando', async () => {
    // La contracara: el fix no puede apagar el reintento que sí queremos.
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce({ status: 200 })
    const p = withGatewayRetry(fetchMock)
    await vi.runAllTimersAsync()
    expect((await p).status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('fueCancelado distingue cancelación de caída de red', () => {
    expect(fueCancelado(abortError())).toBe(true)
    expect(fueCancelado(new TypeError('Failed to fetch'))).toBe(false)
    const ac = new AbortController(); ac.abort()
    expect(fueCancelado(new TypeError('Failed to fetch'), ac.signal)).toBe(true)
  })
})

// Sin ruido, un reinicio del backend deja a TODOS los clientes reintentando en
// el mismo instante (a los 800ms, a los 3,3s...): la avalancha le pega justo
// mientras está levantando.
describe('jitter en las esperas', () => {
  it('se mueve ±20% alrededor del delay base', () => {
    for (const base of RETRY_DELAYS_MS) {
      expect(conJitter(base, () => 0)).toBe(Math.round(base * 0.8))
      expect(conJitter(base, () => 1)).toBe(Math.round(base * 1.2))
      expect(conJitter(base, () => 0.5)).toBe(base)
    }
  })

  it('dos clientes no esperan lo mismo', () => {
    const valores = new Set(
      Array.from({ length: 50 }, () => conJitter(RETRY_DELAYS_MS[0])))
    expect(valores.size).toBeGreaterThan(1)
  })

  it('nunca es negativo', () => {
    expect(conJitter(0)).toBe(0)
    expect(conJitter(800, () => 0)).toBeGreaterThan(0)
  })
})
