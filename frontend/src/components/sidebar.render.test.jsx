import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// El menú lateral, DIBUJADO. Las listas de pantallas se mudaron a
// utils/navegacion.js (las comparte el buscador ⌘K) y en la mudanza quedó un
// `GROUPS` sin importar: la app entera mostraba "Se rompió esta pantalla" y
// ninguna prueba lo vio, porque ninguna dibujaba el menú. Ésta lo dibuja.
let usuario = { tier: 'pro' }
let cliente = null
let guardado = {}  // lo que el menú "recuerda" en localStorage
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
  beforeAll(() => { vi.stubGlobal('localStorage', { getItem: (k) => guardado[k] ?? null, setItem: () => {}, removeItem: () => {} }) })
  afterAll(() => { vi.unstubAllGlobals() })
  it('las secciones van con lo tuyo junto y primero: Tu Cartera, Análisis, Mercado', () => {
    // Mercado estaba al medio y cortaba las dos secciones que hablan de la
    // cartera (pedido de Nico, 2026-10-11).
    const html = dibujar({ tier: 'pro' })
    const lugar = ['>Tu Cartera<', '>Análisis<', '>Mercado<'].map(t => html.indexOf(t))
    for (const l of lugar) expect(l).toBeGreaterThan(0)
    expect(lugar).toEqual([...lugar].sort((a, b) => a - b))
    // Y adentro de cada una, sus pantallas en el orden de siempre.
    const r = rutas(html.slice(html.indexOf('<nav')))
    const orden = ['/dashboard', '/posiciones', '/operaciones', '/analisis', '/fundamentals', '/perfil-inversor', '/', '/novedades']
    expect(r.filter(to => orden.includes(to))).toEqual(orden)
  })
  it('usuario común: Tu Cartera, Análisis, Mercado y los sueltos', () => {
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
  it('el botón Registrar: lo ve quien tiene una cartera donde anotar', () => {
    const boton = /<button[^>]*aria-haspopup="menu"[^>]*>.*?Registrar<\/span><\/button>/s
    expect(dibujar({ tier: 'pro' })).toMatch(boton)
    // El asesor en su nivel no tiene cartera propia; adentro de un cliente, sí.
    expect(dibujar({ tier: 'advisor' })).not.toContain('Registrar')
    expect(dibujar({ tier: 'advisor' }, { id: 7 })).toMatch(boton)
  })
  it('el botón Registrar va arriba, antes del menú, y cerrado no ofrece nada', () => {
    const html = dibujar({ tier: 'pro' })
    expect(html.indexOf('Registrar')).toBeLessThan(html.indexOf('<nav'))
    expect(html).toContain('aria-expanded="false"')
    expect(html).not.toContain('role="menuitem"')
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

  // La flechita del pie (pedido de Nico, 2026-10-19): Alertas, Importar y las
  // utilidades le tapaban lugar a la cartera. Abierto por defecto; plegado deja
  // la cartera, el tema y salir, y esconde el resto también al teclado (inert).
  const pie = (html) => html.slice(html.indexOf('id="sidebar-pie"'))
  it('el pie arranca abierto, con la flechita para plegarlo', () => {
    guardado = {}
    const html = dibujar({ tier: 'pro' })
    expect(html).toMatch(/aria-controls="sidebar-pie"[^>]*aria-label="Ocultar las opciones de abajo"/)
    expect(html).toContain('aria-expanded="true" aria-controls="sidebar-pie"')
    expect(html).not.toMatch(/id="sidebar-pie"[^>]*inert/)
  })
  it('plegado: Alertas, Importar y utilidades quedan adentro e inertes; cartera, tema y salir a la vista', () => {
    guardado = { rendi_sidebar_pie_plegado: 'true' }
    const html = dibujar({ tier: 'pro' })
    expect(html).toMatch(/id="sidebar-pie"[^>]*inert=""/)
    expect(html).toContain('aria-expanded="false" aria-controls="sidebar-pie"')
    const adentro = rutas(pie(html).slice(0, pie(html).indexOf('Recomendaciones')))
    for (const to of ['/alertas', '/imports', '/guia', '/config']) expect(adentro).toContain(to)
    // Lo de la cartera sigue arriba, fuera del pie.
    const afuera = rutas(html.slice(0, html.indexOf('id="sidebar-pie"')))
    for (const to of ['/dashboard', '/posiciones', '/operaciones']) expect(afuera).toContain(to)
    expect(pie(html)).toContain('aria-label="Cerrar sesión"')
    guardado = {}
  })
})
