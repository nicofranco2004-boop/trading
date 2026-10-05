// "Crear alerta BTC −10%" desde Mervall-E AI tiene que abrir el formulario con la
// variación ya cargada — antes abría "precio objetivo ≥ ___", vacío y al revés.
// Se renderiza de verdad (misma técnica que UpgradePromoCard.render.test) y se
// mira el formulario que ve el usuario.
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../hooks/useAlerts', () => ({
  useAlerts: () => ({ items: [], events: [], loading: false, create: vi.fn(), update: vi.fn(), remove: vi.fn() }),
}))
vi.mock('../../hooks/usePushNotifications', () => ({
  usePushNotifications: () => ({ supported: false, permission: 'default', subscribed: false, subscribe: vi.fn(), unsubscribe: vi.fn() }),
}))
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => Promise.resolve({})) } }))

import AlertsManager from './AlertsManager'

const plan = (pct) => ({ can: (f) => (f === 'alerts.pct_move' ? pct : true), limit: () => null })
const html = (p, prefill) => renderToStaticMarkup(
  <MemoryRouter><AlertsManager plan={p} prefill={prefill} /></MemoryRouter>)
// Los campos numéricos con su valor, tal como quedan en el HTML.
const valores = (h) => [...h.matchAll(/<input[^>]*value="([^"]*)"/g)].map(m => m[1])

describe('prefill desde un botón de Mervall-E AI', () => {
  it('con &down=10 abre la alerta de variación con el 10 cargado', () => {
    const h = html(plan(true), { symbol: 'BTC', downPct: 10 })
    expect(valores(h)).toContain('10')
  })

  it('sin permiso de variación queda el formulario de siempre, sin inventar el 10', () => {
    const h = html(plan(false), { symbol: 'BTC', downPct: 10 })
    expect(valores(h)).not.toContain('10')
  })

  it('sin % en el link (el menú de una posición) sigue igual que antes', () => {
    const h = html(plan(true), { symbol: 'GGAL.BA' })
    expect(valores(h)).not.toContain('10')
    expect(h).toContain('GGAL')
  })
})
