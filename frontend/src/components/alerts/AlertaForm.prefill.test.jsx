// "Crear alerta BTC −10%" desde Mervall-E AI tiene que abrir el formulario con el
// % ya cargado — antes abría "precio objetivo ≥ ___", vacío y al revés. Se
// renderiza de verdad el formulario y se mira lo que ve el usuario.
// (Venía de AlertsManager.prefill.test; el formulario se mudó a AlertaForm.)
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../hooks/usePushNotifications', () => ({
  usePushNotifications: () => ({ supported: false, permission: 'default', subscribed: false, subscribe: vi.fn(), unsubscribe: vi.fn() }),
}))
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => Promise.resolve({})) } }))

import AlertaForm from './AlertaForm'

const plan = (pct) => ({ can: (f) => (f === 'alerts.pct_move' ? pct : true), limit: () => null })
const html = (p, props) => renderToStaticMarkup(
  <MemoryRouter><AlertaForm plan={p} onClose={() => {}} {...props} /></MemoryRouter>)
// Los campos con su valor, tal como quedan en el HTML.
const valores = (h) => [...h.matchAll(/<input[^>]*value="([^"]*)"/g)].map(m => m[1])

describe('prefill desde un botón de Mervall-E AI', () => {
  it('con &down=10 abre el aviso por % con el 10 cargado', () => {
    const h = html(plan(true), { prefill: { symbol: 'BTC', downPct: 10 } })
    expect(valores(h)).toContain('10')
    expect(h).toContain('Si cae más de')
  })

  it('sin permiso de %, queda el de precio, sin inventar el 10', () => {
    const h = html(plan(false), { prefill: { symbol: 'BTC', downPct: 10 } })
    expect(valores(h)).not.toContain('10')
    expect(h).toContain('Plus')
  })

  it('sin % en el link (el menú de una posición) abre el de precio con el ticker', () => {
    const h = html(plan(true), { prefill: { symbol: 'GGAL.BA' } })
    expect(valores(h)).not.toContain('10')
    expect(valores(h)).toContain('GGAL.BA')
  })
})

describe('editar', () => {
  const alerta = {
    id: 7, kind: 'price_target', scope: 'ticker', symbol: 'GGAL.BA', currency: 'ARS',
    direction: 'above', threshold: 8000, channel: 'both', repeat: 'once', active: true,
  }

  it('trae el precio guardado y la frase de confirmación', () => {
    const h = html(plan(true), { alerta })
    expect(valores(h)).toContain('8000')
    expect(h).toContain('Te avisamos cuando GGAL suba a $ 8.000.')
    expect(h).toContain('Guardar cambios')
    expect(h).toContain('Borrar aviso')
  })

  it('no ofrece cambiar de tipo: el servidor no lo permite', () => {
    const h = html(plan(true), { alerta })
    expect(h).not.toContain('Se mueve un %')
  })
})
