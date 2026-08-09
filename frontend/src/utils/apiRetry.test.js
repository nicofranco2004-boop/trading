// Reintento ante errores de GATEWAY (502/503/504).
//
// Reporte real (2026-08-08): un usuario vio "HTTP 502" al subir sus archivos.
// No era su archivo ni sus datos: el backend estaba reiniciando por un deploy.
// Esos errores son transitorios y duran segundos, así que se reintentan solos —
// pero SOLO donde repetir el pedido es inofensivo (GET y los preview, que
// arman un borrador). Un confirm repetido duplicaría la importación.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Aislamos la política de reintento tal como está implementada en api.js.
// (api.js hace side-effects de localStorage/window al importarse, así que
// replicamos acá la MISMA tabla de delays y las mismas reglas.)
const GATEWAY_ERRORS = [502, 503, 504]
const RETRY_DELAYS_MS = [800, 2500, 5000]
const sleep = (ms) => new Promise(r => setTimeout(r, ms))

async function withGatewayRetry(doFetch) {
  for (let i = 0; ; i++) {
    let res
    try {
      res = await doFetch()
    } catch (netErr) {
      if (i >= RETRY_DELAYS_MS.length) throw netErr
      await sleep(RETRY_DELAYS_MS[i])
      continue
    }
    if (!GATEWAY_ERRORS.includes(res.status) || i >= RETRY_DELAYS_MS.length) return res
    await sleep(RETRY_DELAYS_MS[i])
  }
}

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
