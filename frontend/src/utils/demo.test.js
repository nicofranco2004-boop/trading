import { describe, it, expect, vi, afterEach } from 'vitest'
import { isDemoMode } from './demo'

afterEach(() => { vi.unstubAllGlobals() })

// `isDemoMode` la llaman 11 lugares, incluido el micrófono y la clave con la
// que se guarda el chat. Si revienta, se lleva puesto al que la llamó.
describe('preguntar si es la demo nunca puede reventar', () => {
  it('con el almacenamiento bloqueado contesta que no es demo', () => {
    // Leer localStorage TIRA EXCEPCIÓN —no viene vacío— en navegación privada
    // vieja, en un iframe con el almacenamiento bloqueado y con "no guardar
    // datos de sitios". Chequear `window` no cubre ninguno de esos: ahí
    // `window` existe igual.
    vi.stubGlobal('window', globalThis)
    vi.stubGlobal('localStorage', {
      getItem() { throw new DOMException('acceso denegado', 'SecurityError') },
    })
    expect(() => isDemoMode()).not.toThrow()
    expect(isDemoMode()).toBe(false)
  })

  it('y sigue contestando que sí cuando de verdad es la demo', () => {
    vi.stubGlobal('window', globalThis)
    vi.stubGlobal('localStorage', { getItem: (k) => (k === 'rendi_demo_mode' ? '1' : null) })
    expect(isDemoMode()).toBe(true)
  })
})
