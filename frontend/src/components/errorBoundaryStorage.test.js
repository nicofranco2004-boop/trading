import { describe, it, expect } from 'vitest'
import { limpiarEstadoLocal } from './ErrorBoundary.jsx'

function fakeStorage(init = {}) {
  const m = new Map(Object.entries(init))
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, v),
    clear: () => m.clear(),
    get size() { return m.size },
  }
}

describe('limpiarEstadoLocal', () => {
  it('borra el contexto de cliente del asesor — la causa más probable de un crash que solo pasa fuera de incógnito', () => {
    const ls = fakeStorage({
      rendi_user: '{"id":1}',
      rendi_client_ctx: '{"id":99,"label":"Cliente"}',
      rendi_theme: 'dark',
      rendi_valuation_dollar: 'mep',
    })
    const ss = fakeStorage({ algo: 'x' })
    limpiarEstadoLocal(ls, ss)
    expect(ls.getItem('rendi_client_ctx')).toBeNull()
    expect(ls.getItem('rendi_theme')).toBeNull()
    expect(ss.size).toBe(0)
  })

  it('PRESERVA la sesión: limpiar no puede desloguear', () => {
    const ls = fakeStorage({ rendi_user: '{"id":1}', rendi_client_ctx: '{"id":9}' })
    limpiarEstadoLocal(ls, fakeStorage())
    expect(ls.getItem('rendi_user')).toBe('{"id":1}')
  })

  it('no explota si el storage está bloqueado o no existe', () => {
    expect(() => limpiarEstadoLocal(null, null)).not.toThrow()
    const roto = { getItem: () => { throw new Error('bloqueado') }, clear: () => {}, setItem: () => {} }
    expect(() => limpiarEstadoLocal(roto, roto)).not.toThrow()
  })

  it('sin sesión previa no inventa una', () => {
    const ls = fakeStorage({ rendi_theme: 'dark' })
    limpiarEstadoLocal(ls, fakeStorage())
    expect(ls.getItem('rendi_user')).toBeNull()
  })
})
