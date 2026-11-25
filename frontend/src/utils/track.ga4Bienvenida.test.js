import { describe, it, expect, vi, beforeAll, afterAll, beforeEach } from 'vitest'

// El embudo de activación de Google Analytics: desde el 25/11 las cuentas
// nuevas pasan por la bienvenida obligatoria (pages/Onboarding.jsx) y ya no por
// onboarding_* ni por first_insight_viewed. Si sus hitos no se reenvían, el
// embudo de GA4 se corta en el registro sin que nadie lo note.

vi.mock('./uso', () => ({ registrarUso: () => {} }))

let track
const gtag = vi.fn()
beforeAll(async () => {
  vi.stubGlobal('window', { gtag })
  vi.spyOn(console, 'debug').mockImplementation(() => {})
  ;({ track } = await import('./track'))
})
afterAll(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })
beforeEach(() => { gtag.mockClear() })

describe('la bienvenida en GA4', () => {
  it('«confirmó su primer archivo» y «terminó la bienvenida» viajan a GA4', () => {
    for (const ev of ['bienvenida_historial_cargado', 'bienvenida_terminada']) {
      gtag.mockClear()
      track(ev)
      expect(gtag, ev).toHaveBeenCalledWith('event', ev, expect.anything())
    }
  })
  it('los pasos intermedios no (se cuentan en el panel propio, no hacen falta en GA4)', () => {
    track('bienvenida_hola')
    track('bienvenida_broker_elegido')
    expect(gtag).not.toHaveBeenCalled()
  })
})
