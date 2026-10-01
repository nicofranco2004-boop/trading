import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// El menú lateral, DIBUJADO. Las listas de pantallas se mudaron a
// utils/navegacion.js (las comparte el buscador ⌘K) y en la mudanza quedó un
// `GROUPS` sin importar: la app entera mostraba "Se rompió esta pantalla" y
// ninguna prueba lo vio, porque ninguna dibujaba el menú. Ésta lo dibuja.
let usuario = { tier: 'pro' }
let cliente = null
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: usuario, logout: () => {} }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: cliente }) }))
vi.mock('../contexts/AlertsContext', () => ({ useAlertsContext: () => ({ unseenCount: 0 }) }))
vi.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ dark: true, toggle: () => {} }) }))
vi.mock('../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('./CurrencySwitcher', () => ({ default: () => null }))
vi.mock('./RecommendationsModal', () => ({ default: () => null }))

import Sidebar from './Sidebar'

const rutas = (html) => [...html.matchAll(/href="([^"]+)"/g)].map(m => m[1])
const dibujar = (u, c = null, en = '/dashboard') => {
  usuario = u; cliente = c
  return renderToStaticMarkup(<MemoryRouter initialEntries={[en]}><Sidebar /></MemoryRouter>)
}

describe('<Sidebar> se dibuja con la lista compartida', () => {
  // El menú recuerda si estaba plegado en localStorage; en estas pruebas no hay
  // navegador. Se pone y se saca: no puede quedar para las pruebas que siguen.
  beforeAll(() => { vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} }) })
  afterAll(() => { vi.unstubAllGlobals() })
  it('usuario común: Tu Cartera, Mercado, Análisis y los sueltos', () => {
    const r = rutas(dibujar({ tier: 'pro' }))
    for (const to of ['/dashboard', '/posiciones', '/operaciones', '/', '/novedades', '/analisis', '/fundamentals', '/perfil-inversor', '/alertas', '/imports']) {
      expect(r).toContain(to)
    }
    expect(r).not.toContain('/clientes')
  })
  it('asesor en su nivel: su home (con Cobros), sin cartera propia ni Importar', () => {
    const r = rutas(dibujar({ tier: 'advisor' }))
    for (const to of ['/dashboard', '/clientes', '/novedades', '/cobros', '/importar-historiales', '/alertas']) expect(r).toContain(to)
    expect(r).not.toContain('/posiciones')
    expect(r).not.toContain('/imports')
  })
  it('asesor adentro de un cliente: la cartera del cliente y volver a Clientes', () => {
    const r = rutas(dibujar({ tier: 'advisor' }, { id: 7 }))
    expect(r).toContain('/posiciones')
    expect(r).toContain('/clientes')
    expect(r).not.toContain('/cobros')
  })
  it('el pie (Guía, Configuración) sale de la lista compartida; Admin sólo para is_admin', () => {
    const comun = rutas(dibujar({ tier: 'pro' }))
    expect(comun).toContain('/guia')
    expect(comun).toContain('/config')
    expect(comun).not.toContain('/admin')
    expect(rutas(dibujar({ tier: 'pro', is_admin: true }))).toContain('/admin')
  })
  it('la lupa del buscador: una sola, con el atajo en su cartel', () => {
    const html = dibujar({ tier: 'pro' })
    expect(html.match(/aria-label="Buscar en Rendi"/g)).toHaveLength(1)
  })
  it('tiene el botón "Buscar" con el atajo escrito', () => {
    const html = dibujar({ tier: 'pro' })
    expect(html).toContain('aria-label="Buscar en Rendi"')
    expect(html).toMatch(/⌘K|Ctrl K/)
  })
})
