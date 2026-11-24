// Revisión final de «Mover a otro broker» (contrato #4): el 409 «sin precio» del
// servidor llega con `detail` OBJETO {codigo, mensaje, moneda_precio}. El cliente
// buscaba error/message/detail y no `mensaje`: el modal mostraba el JSON crudo.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api, errorMessage } from './api'

describe('un error del servidor con `mensaje` se lee como texto', () => {
  beforeEach(() => {
    globalThis.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} }
    const w = new EventTarget()
    w.location = { href: '' }
    globalThis.window = w
  })
  afterEach(() => {
    vi.restoreAllMocks()
    delete globalThis.localStorage
    delete globalThis.window
  })
  const responde = (status, cuerpo = {}) => vi.fn(async () => ({
    status, ok: status < 400, json: async () => cuerpo, text: async () => JSON.stringify(cuerpo),
    headers: { get: () => 'application/json' },
  }))

  it('el 409 «sin precio» del pase', async () => {
    const mensaje = 'No encontramos a cuánto cotizaba NVDA el 24/11/2026. Escribí el precio de ese ' +
      'día (en pesos) para calcular cuánto valía lo que pasaste.'
    globalThis.fetch = responde(409, { detail: { codigo: 'sin_precio', mensaje, moneda_precio: 'ARS' } })
    let error = null
    try { await api.post('/positions/traspaso', {}) } catch (e) { error = e }
    expect(error).toBeTruthy()
    expect(error.status).toBe(409)
    expect(error.message).toBe(mensaje)
    expect(errorMessage(error)).toBe(mensaje)
    expect(error.payload.detail.codigo).toBe('sin_precio')   // `faltaPrecio` lo sigue leyendo
  })
})
