import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { Star } from 'lucide-react'

// El menú "Más" del celular y el menú lateral de la compu, DIBUJADOS, tienen
// que llevar a los mismos lugares. "Más" tenía su propia copia de la lista y
// de la regla del asesor, y se desvió: el asesor tenía "Cobros" en la compu y
// en el celular no, y ningún otro enlace del celular llevaba ahí. Ahora los
// dos leen utils/navegacion.js; esto se pone en rojo si alguno vuelve a armar
// su propia lista.
//
// El menú lateral recuerda si estaba plegado en localStorage; en estas pruebas
// no hay navegador. Se pone y se saca: no puede quedar para las que siguen.
beforeAll(() => { vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} }) })
afterAll(() => { vi.unstubAllGlobals() })
let usuario = { tier: 'pro' }
let cliente = null
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: usuario, logout: () => {} }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: cliente }) }))
vi.mock('../contexts/AlertsContext', () => ({ useAlertsContext: () => ({ unseenCount: 0 }) }))
vi.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ dark: true, toggle: () => {} }) }))
vi.mock('../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('../components/CurrencySwitcher', () => ({ default: () => null }))
vi.mock('../components/RecommendationsModal', () => ({ default: () => null }))
vi.mock('../components/Toast', () => ({ useToast: () => null }))
vi.mock('../hooks/usePushNotifications', () => ({
  usePushNotifications: () => ({ supported: false }),
}))

import More, { seccionesDelMenuMas } from './More'
import Sidebar from '../components/Sidebar'
import MobileTabBar from '../components/mobile/MobileTabBar'

const rutas = (html) => [...html.matchAll(/href="([^"]+)"/g)].map(m => m[1])
const dibujar = (Componente, u, c) => {
  usuario = u; cliente = c
  return renderToStaticMarkup(<MemoryRouter initialEntries={['/mas']}><Componente /></MemoryRouter>)
}
// El logo de arriba del menú lateral lleva a "/" para todos (también al asesor,
// que no tiene esa pantalla en su menú): es el logo, no una entrada del menú.
// El menú empieza en <nav>.
const menuCompu = (u, c) => {
  const html = dibujar(Sidebar, u, c)
  return rutas(html.slice(html.indexOf('<nav')))
}
const menuMas = (u, c) => rutas(dibujar(More, u, c))
const ordenadas = (r) => [...new Set(r)].sort()

const CASOS = [
  ['usuario común', { tier: 'pro' }, null],
  ['asesor en su nivel', { tier: 'advisor' }, null],
  ['asesor adentro de un cliente', { tier: 'advisor' }, { id: 7 }],
  ['admin sin plan asesor', { tier: 'pro', is_admin: true }, null],
]

describe('"Más" (celular) y el menú lateral (compu) llevan a los mismos lugares', () => {
  for (const [quien, u, c] of CASOS) {
    it(quien, () => {
      const compu = menuCompu(u, c)
      const mas = menuMas(u, c)
      // Contra el falso verde: si un dibujo sale vacío, "iguales" no prueba nada.
      expect(compu.length).toBeGreaterThan(3)
      expect(ordenadas(mas)).toEqual(ordenadas(compu))
      // Y en "Más" cada lugar aparece una sola vez (Dashboard está en dos listas).
      expect(mas).toHaveLength(new Set(mas).size)
    })
  }

  it('el asesor en su nivel tiene "Cobros" en el celular, y no una cartera propia', () => {
    const mas = menuMas({ tier: 'advisor' }, null)
    expect(mas).toContain('/cobros')
    expect(mas).toContain('/importar-historiales')
    expect(mas).not.toContain('/posiciones')
    expect(mas).not.toContain('/imports')
  })

  it('adentro de un cliente: la cartera del cliente y "Clientes" para volver, sin "Cobros"', () => {
    const mas = menuMas({ tier: 'advisor' }, { id: 7 })
    expect(mas).toContain('/posiciones')
    expect(mas).toContain('/clientes')
    expect(mas).not.toContain('/cobros')
  })

  it('ser admin no da "Clientes" (es del plan Asesor), sí el panel de Admin', () => {
    const mas = menuMas({ tier: 'pro', is_admin: true }, null)
    expect(mas).not.toContain('/clientes')
    expect(mas).toContain('/admin')
    expect(menuMas({ tier: 'pro' }, null)).not.toContain('/admin')
  })

  it('la Guía y Configuración están en el celular para todos', () => {
    for (const [, u, c] of CASOS) {
      expect(menuMas(u, c)).toContain('/guia')
      expect(menuMas(u, c)).toContain('/config')
    }
  })
})

describe('la barra de abajo del celular usa la misma regla del asesor', () => {
  const barra = (u, c) => rutas(dibujar(MobileTabBar, u, c))
  it('asesor en su nivel: las pestañas de su mundo', () => {
    expect(barra({ tier: 'advisor' }, null)).toEqual(['/dashboard', '/clientes', '/novedades', '/mas'])
  })
  it('asesor adentro de un cliente y usuario común: las de una cartera', () => {
    expect(barra({ tier: 'advisor' }, { id: 7 })).toEqual(['/', '/posiciones', '/insights', '/mas'])
    expect(barra({ tier: 'pro' }, null)).toEqual(['/', '/posiciones', '/insights', '/mas'])
  })
})

describe('seccionesDelMenuMas', () => {
  it('una pantalla nueva sin renglón propio en el celular aparece igual', () => {
    const nueva = { to: '/nueva', label: 'Pantalla nueva', icon: Star, grupo: 'Mercado' }
    const secciones = seccionesDelMenuMas([{ to: '/posiciones', label: 'Cartera', icon: Star }, nueva])
    const enMercado = secciones.find(s => s.label === 'Mercado')
    expect(enMercado.items.map(i => [i.to, i.label, i.sub])).toEqual([['/nueva', 'Pantalla nueva', undefined]])
  })
  it('el asesor en su nivel: todo en "Plan Asesor", en el orden del celular', () => {
    const p = (to) => ({ to, label: to, icon: Star })
    const secciones = seccionesDelMenuMas(
      ['/alertas', '/cobros', '/dashboard', '/clientes'].map(p), { atOwnLevel: true })
    expect(secciones.map(s => s.label)).toEqual(['Plan Asesor'])
    expect(secciones[0].items.map(i => i.to)).toEqual(['/dashboard', '/clientes', '/cobros', '/alertas'])
  })
})
