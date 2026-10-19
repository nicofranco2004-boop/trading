import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// Importar historial vive ADENTRO del menú de Registrar, separado de las cargas
// a mano (pedido de Nico, 2026-10-19). El menú abierto no se puede dibujar sin
// navegador (se abre al tocar, en un portal), así que acá se mira el cable: que
// el menú lateral le pase Importar a Registrar con la MISMA regla de quién lo ve
// (utils/navegacion.js). El menú abierto se miró en el navegador.
let usuario = { tier: 'pro' }
let cliente = null
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: usuario, logout: () => {} }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: cliente }) }))
vi.mock('../contexts/AlertsContext', () => ({ useAlertsContext: () => ({ unseenCount: 0 }) }))
vi.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ dark: true, toggle: () => {} }) }))
vi.mock('../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('./CurrencySwitcher', () => ({ default: () => null }))
vi.mock('./RecommendationsModal', () => ({ default: () => null }))
vi.mock('./RegistrarMenu', () => ({ default: ({ importar }) => <i data-importar={importar?.to ?? 'nada'} /> }))

import Sidebar from './Sidebar'

const dibujar = (u, c = null) => {
  usuario = u; cliente = c
  return renderToStaticMarkup(<MemoryRouter initialEntries={['/dashboard']}><Sidebar /></MemoryRouter>)
}

describe('Importar va adentro de Registrar', () => {
  beforeAll(() => { vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} }) })
  afterAll(() => { vi.unstubAllGlobals() })

  it('usuario común: Registrar recibe Importar, y no queda una fila suelta', () => {
    const html = dibujar({ tier: 'pro' })
    expect(html).toContain('data-importar="/imports"')
    expect(html).not.toContain('href="/imports"')
  })
  it('asesor adentro de un cliente: también', () => {
    expect(dibujar({ tier: 'advisor' }, { id: 7 })).toContain('data-importar="/imports"')
  })
  it('asesor en su nivel: ni Registrar ni Importar (tiene «Importar historiales» propio)', () => {
    const html = dibujar({ tier: 'advisor' })
    expect(html).not.toContain('data-importar')
    expect(html).toContain('href="/importar-historiales"')
  })
})
