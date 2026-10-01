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
// Se comparan los dos dibujos enteros (no la lista compartida): un menú que
// la lea bien y después se olvide de dibujar una parte tiene que dar rojo.

// El menú lateral recuerda en localStorage si estaba plegado; se prueban las
// dos formas, porque plegado dibuja otra lista (íconos sueltos, sin grupos).
let plegado = false
beforeAll(() => {
  vi.stubGlobal('localStorage', {
    getItem: (k) => (k === 'rendi_sidebar_collapsed' ? String(plegado) : null),
    setItem: () => {}, removeItem: () => {},
  })
})
afterAll(() => { vi.unstubAllGlobals() })

let usuario = { tier: 'pro' }
let cliente = null
let sinVer = 0
let push = { supported: false }
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: usuario, logout: () => {} }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: cliente }) }))
vi.mock('../contexts/AlertsContext', () => ({ useAlertsContext: () => ({ unseenCount: sinVer, markSeen: () => {} }) }))
vi.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ dark: true, toggle: () => {} }) }))
vi.mock('../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('../components/CurrencySwitcher', () => ({ default: () => null }))
vi.mock('../components/RecommendationsModal', () => ({ default: () => null }))
vi.mock('../components/Toast', () => ({ useToast: () => null }))
vi.mock('../hooks/usePushNotifications', () => ({ usePushNotifications: () => push }))

import More, { seccionesDelMenuMas } from './More'
import Sidebar from '../components/Sidebar'
import MobileTabBar, { QUICK_ACTIONS } from '../components/mobile/MobileTabBar'
import fuenteDeApp from '../App.jsx?raw'
import fuenteDeCarteraCelular from './PositionsMobile.jsx?raw'

const rutas = (html) => [...html.matchAll(/href="([^"]+)"/g)].map(m => m[1].replace(/&amp;/g, '&'))
const dibujar = (Componente, u, c) => {
  usuario = u; cliente = c
  return renderToStaticMarkup(<MemoryRouter initialEntries={['/mas']}><Componente /></MemoryRouter>)
}
// Arriba del <nav> del menú lateral va el logo, que lleva a "/" para todos
// (también al asesor, que no tiene esa pantalla en su menú): es el logo, no
// una entrada del menú. Se exige que sea lo ÚNICO que hay ahí arriba: un
// enlace nuevo en esa franja tiene que estar también en el celular.
const menuCompu = (u, c) => {
  const html = dibujar(Sidebar, u, c)
  const corte = html.indexOf('<nav')
  expect(corte, 'el menú lateral perdió su <nav>').toBeGreaterThan(0)
  expect(rutas(html.slice(0, corte)), 'arriba del menú lateral sólo va el logo').toEqual(['/'])
  return { html, rutas: rutas(html.slice(corte)) }
}
const menuMas = (u, c) => {
  const html = dibujar(More, u, c)
  return { html, rutas: rutas(html) }
}
const titulos = (html) => [...html.matchAll(/<h2[^>]*>\s*([^<]*?)\s*<\/h2>/g)].map(m => m[1])
const ordenadas = (r) => [...new Set(r)].sort()
const sinRepetidos = (r) => expect(r).toHaveLength(new Set(r).size)
// Los botones que no son pantallas y que el usuario tiene que encontrar en los
// dos: el modo claro en el celular vivió una vez SÓLO en la compu.
const ACCIONES = ['Rendi AI', 'data-tour="tema"', 'Recomendaciones', 'Cerrar sesión']

const CLIENTE = { id: 7, label: 'Ana' }
const CASOS = [
  ['usuario común', { tier: 'pro' }, null],
  ['asesor en su nivel', { tier: 'advisor' }, null],
  ['asesor adentro de un cliente', { tier: 'advisor' }, CLIENTE],
  ['admin sin plan asesor', { tier: 'pro', is_admin: true }, null],
  ['admin con plan admin', { tier: 'admin', is_admin: true }, null],
  ['asesor que además es admin, en su nivel', { tier: 'advisor', is_admin: true }, null],
  ['asesor que además es admin, adentro de un cliente', { tier: 'advisor', is_admin: true }, CLIENTE],
]

describe.each([['desplegado', false], ['plegado', true]])('menú de la compu %s', (_, estaPlegado) => {
  beforeAll(() => { plegado = estaPlegado })
  afterAll(() => { plegado = false })

  describe('"Más" (celular) y el menú lateral (compu) llevan a los mismos lugares', () => {
    for (const [quien, u, c] of CASOS) {
      it(quien, () => {
        const compu = menuCompu(u, c)
        const mas = menuMas(u, c)
        // Contra el falso verde: si un dibujo sale vacío, "iguales" no prueba nada.
        expect(compu.rutas.length).toBeGreaterThan(3)
        expect(ordenadas(mas.rutas)).toEqual(ordenadas(compu.rutas))
        // Cada lugar una sola vez en cada menú (Dashboard está en dos listas).
        sinRepetidos(compu.rutas)
        sinRepetidos(mas.rutas)
        for (const a of ACCIONES) {
          expect(compu.html, `compu: ${a}`).toContain(a)
          expect(mas.html, `celular: ${a}`).toContain(a)
        }
      })
    }
  })
})

describe('"Más": cómo se agrupa', () => {
  it('el asesor en su nivel: sólo "Plan Asesor", con el Dashboard del libro', () => {
    const { html, rutas: r } = menuMas({ tier: 'advisor' }, null)
    const t = titulos(html)
    expect(t).toContain('Plan Asesor')
    for (const no of ['Tu portfolio', 'Mercado', 'Análisis', 'Otras secciones']) expect(t).not.toContain(no)
    expect(html).toContain('Total administrado')        // el Dashboard del libro
    expect(html).not.toContain('de dónde sale la ganancia') // no el de una cartera
    expect(r).toContain('/cobros')
    expect(r).not.toContain('/posiciones')
  })

  it('adentro de un cliente: su cartera se llama con su nombre, y "Clientes" para volver', () => {
    const { html, rutas: r } = menuMas({ tier: 'advisor' }, CLIENTE)
    const t = titulos(html)
    expect(t).toContain('Cartera de Ana')
    expect(t).not.toContain('Tu portfolio')
    expect(t).toContain('Plan Asesor')
    expect(r).toContain('/clientes')
    expect(r).not.toContain('/cobros')
    expect(html).toContain('la cartera de Ana')          // Rendi AI trabaja sobre la de Ana
  })

  it('la compu dice lo mismo: adentro de un cliente su grupo es "Cartera de Ana", no "Tu Cartera"', () => {
    const { html } = menuCompu({ tier: 'advisor' }, CLIENTE)
    expect(html).toContain('Cartera de Ana')
    expect(html).not.toContain('>Tu Cartera<')
    expect(menuCompu({ tier: 'pro' }, null).html).toContain('>Tu Cartera<')
  })

  it('usuario común: las secciones de la compu, ninguna de relleno', () => {
    const t = titulos(menuMas({ tier: 'pro' }, null).html)
    for (const s of ['Tu portfolio', 'Mercado', 'Análisis']) expect(t).toContain(s)
    for (const no of ['Plan Asesor', 'Otras secciones']) expect(t).not.toContain(no)
  })

  it('ser admin no da "Clientes" (es del plan Asesor); sí el panel de Admin', () => {
    expect(menuMas({ tier: 'pro', is_admin: true }, null).rutas).not.toContain('/clientes')
    expect(menuMas({ tier: 'pro', is_admin: true }, null).rutas).toContain('/admin')
    expect(menuMas({ tier: 'pro' }, null).rutas).not.toContain('/admin')
  })
})

describe('el puntito de alertas sin ver', () => {
  afterAll(() => { sinVer = 0 })
  for (const [quien, u, c] of CASOS.slice(0, 3)) {
    it(`${quien}: si la compu lo muestra, el celular también (en "Más" y en su pestaña)`, () => {
      sinVer = 2
      expect(menuCompu(u, c).html).toContain('Tenés alertas sin ver')
      expect(menuMas(u, c).html).toContain('Tenés alertas sin ver')
      expect(dibujar(MobileTabBar, u, c)).toContain('Tenés alertas sin ver')
      sinVer = 0
      expect(menuMas(u, c).html).not.toContain('Tenés alertas sin ver')
      expect(dibujar(MobileTabBar, u, c)).not.toContain('Tenés alertas sin ver')
    })
  }
})

describe('la barra de abajo del celular', () => {
  // Es una tercera lista (las pestañas fijas), escrita a mano a propósito:
  // cuáles van abajo es una decisión de diseño. Lo que no puede pasar es que
  // ofrezca un lugar que el menú de ese usuario no tiene.
  const destinos = (u, c) => rutas(dibujar(MobileTabBar, u, c))
    .filter(r => r !== '/mas').map(r => r.split('?')[0])
  for (const [quien, u, c] of CASOS) {
    it(`${quien}: cada pestaña está en su menú`, () => {
      const menu = new Set(menuCompu(u, c).rutas)
      for (const d of destinos(u, c)) expect(menu, d).toContain(d)
    })
  }
  it('la pantalla de análisis se llama igual que en los menús: "Métricas"', () => {
    const barra = dibujar(MobileTabBar, { tier: 'pro' }, null)
    expect(barra).toMatch(/href="\/analisis\?tab=diagnostico"[^>]*>[\s\S]*?Métricas/)
    expect(barra).not.toContain('Insights')
  })
  it('el "+" (cargar compras) sólo con una cartera a la vista', () => {
    const conMas = (u, c) => dibujar(MobileTabBar, u, c).includes('Abrir acciones rápidas')
    expect(conMas({ tier: 'pro' }, null)).toBe(true)
    expect(conMas({ tier: 'advisor' }, CLIENTE)).toBe(true)
    expect(conMas({ tier: 'pro', is_admin: true }, null)).toBe(true)
    expect(conMas({ tier: 'advisor' }, null)).toBe(false)
  })
})

describe('seccionesDelMenuMas', () => {
  const p = (to, extra = {}) => ({ to, label: to, icon: Star, ...extra })
  const donde = (secciones, to) => secciones.find(s => s.items.some(i => i.to === to))?.label

  it('una pantalla nueva sin renglón propio en el celular aparece igual, en su grupo', () => {
    const s = seccionesDelMenuMas([p('/posiciones', { grupo: 'Tu Cartera' }), p('/nueva', { grupo: 'Mercado', label: 'Nueva' })])
    expect(s.find(x => x.label === 'Mercado').items.map(i => [i.to, i.label, i.sub])).toEqual([['/nueva', 'Nueva', undefined]])
  })
  it('una pantalla nueva del grupo "Tu Cartera" va a "Tu portfolio", no a una sección aparte', () => {
    const s = seccionesDelMenuMas([p('/posiciones', { grupo: 'Tu Cartera' }), p('/watchlist', { grupo: 'Tu Cartera' })])
    expect(s.map(x => x.label)).toEqual(['Tu portfolio'])
  })
  it('adentro de un cliente, lo del asesor que no es de la cartera va con "Clientes"', () => {
    // Si mañana navegacion.js deja "Cobros" adentro de un cliente (sin grupo,
    // como "Clientes"), tiene que ir en "Plan Asesor" y no en una sección suelta.
    const s = seccionesDelMenuMas([p('/clientes'), p('/cobros'), p('/dashboard', { grupo: 'Tu Cartera' })], { cliente: 'Ana' })
    expect(donde(s, '/clientes')).toBe('Plan Asesor')
    expect(donde(s, '/cobros')).toBe('Plan Asesor')
    expect(donde(s, '/dashboard')).toBe('Cartera de Ana')
  })
  it('el asesor en su nivel: todo en "Plan Asesor", en el orden del celular', () => {
    const s = seccionesDelMenuMas(['/alertas', '/cobros', '/dashboard', '/clientes'].map(to => p(to)), { atOwnLevel: true })
    expect(s.map(x => x.label)).toEqual(['Plan Asesor'])
    expect(s[0].items.map(i => i.to)).toEqual(['/dashboard', '/clientes', '/cobros', '/alertas'])
  })
})

describe('"+" de la barra de abajo: cada acción va a una pantalla que la entiende', () => {
  // "Agregar a watchlist" iba a `/?action=watchlist`: la ruta existía, pero
  // ninguna pantalla leía esa acción y quedabas en el Inicio sin nada abierto.
  const rutasDeApp = new Set([...fuenteDeApp.matchAll(/path="([^"]+)"/g)].map(m => m[1]))
  for (const a of QUICK_ACTIONS) {
    it(a.label, () => {
      const [ruta, consulta = ''] = a.to.split('?')
      expect(rutasDeApp, ruta).toContain(ruta)
      const accion = new URLSearchParams(consulta).get('action')
      if (!accion) return
      // Hoy la única pantalla que lee `?action=` es la Cartera del celular.
      expect(ruta).toBe('/posiciones')
      expect(fuenteDeCarteraCelular).toContain(`action === '${accion}'`)
    })
  }
})

describe('notificaciones push: el texto dice lo que de verdad se manda', () => {
  // Prometían "earnings, drawdowns y nuevos sesgos": sólo salen los avisos de
  // precio/variación (alerts_engine) y, al asesor, los movimientos de sus
  // clientes (advisor_alerts).
  afterAll(() => { push = { supported: false } })
  for (const subscribed of [false, true]) {
    it(subscribed ? 'activadas' : 'sin activar', () => {
      push = { supported: true, permission: 'default', subscribed, loading: false }
      const comun = menuMas({ tier: 'pro' }, null).html
      const asesor = menuMas({ tier: 'advisor' }, null).html
      expect(comun).toContain('avisos de precio y de variación')
      expect(asesor).toContain('movimientos de tus clientes')
      for (const html of [comun, asesor]) expect(html).not.toMatch(/earnings|drawdowns|sesgos/)
    })
  }
})
