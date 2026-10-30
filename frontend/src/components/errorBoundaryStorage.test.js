import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'
import { limpiarEstadoLocal } from './ErrorBoundary.jsx'

// «Limpiar y recargar» del cartel de error: vacía el almacenamiento del
// navegador por la única puerta (utils/almacen), salvo la sesión.
let local, sesion
beforeAll(() => { ;({ local, sesion } = instalarNavegadorMinimo()) })
afterEach(() => { localStorage.clear(); sessionStorage.clear() })

describe('limpiarEstadoLocal', () => {
  it('borra el contexto de cliente del asesor — la causa más probable de un crash que solo pasa fuera de incógnito', () => {
    localStorage.setItem('rendi_user', '{"id":1}')
    localStorage.setItem('rendi_client_ctx', '{"id":99,"label":"Cliente"}')
    localStorage.setItem('rendi_theme', 'dark')
    localStorage.setItem('rendi_valuation_dollar', 'mep')
    sessionStorage.setItem('algo', 'x')
    limpiarEstadoLocal()
    expect(localStorage.getItem('rendi_client_ctx')).toBeNull()
    expect(localStorage.getItem('rendi_theme')).toBeNull()
    expect(sesion.size).toBe(0)
  })

  it('PRESERVA la sesión: limpiar no puede desloguear', () => {
    localStorage.setItem('rendi_user', '{"id":1}')
    localStorage.setItem('rendi_client_ctx', '{"id":9}')
    limpiarEstadoLocal()
    expect(localStorage.getItem('rendi_user')).toBe('{"id":1}')
  })

  it('no explota si el storage está bloqueado o no existe', () => {
    const real = { l: globalThis.localStorage, s: globalThis.sessionStorage }
    try {
      vi.stubGlobal('localStorage', undefined); vi.stubGlobal('sessionStorage', undefined)
      expect(() => limpiarEstadoLocal()).not.toThrow()
      const roto = { getItem: () => { throw new Error('bloqueado') }, clear: () => {}, setItem: () => {} }
      vi.stubGlobal('localStorage', roto); vi.stubGlobal('sessionStorage', roto)
      expect(() => limpiarEstadoLocal()).not.toThrow()
    } finally {
      vi.stubGlobal('localStorage', real.l); vi.stubGlobal('sessionStorage', real.s)
    }
  })

  it('sin sesión previa no inventa una', () => {
    localStorage.setItem('rendi_theme', 'dark')
    limpiarEstadoLocal()
    expect(localStorage.getItem('rendi_user')).toBeNull()
    expect(local.size).toBe(0)
  })
})
