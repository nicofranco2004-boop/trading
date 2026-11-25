import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo } from '../testing/navegadorMinimo'

// LA PUERTA de la bienvenida obligatoria, con la app ENTERA (App.jsx): sus dos
// armazones, el muro de plan, la isla de Mervall-E. Se reemplazan por marcas
// las piezas que necesitan un servidor o un navegador de verdad (las páginas,
// la barra lateral, las barras del celular, los proveedores); lo que se prueba
// es el armado de App.jsx: quién manda a /onboarding, qué se dibuja ahí y qué
// gana cuando dos cosas tapan la pantalla.

const auth = { user: null, isDemo: false, bootstrapped: true }
let esCelular = false
vi.mock('../contexts/AuthContext', () => ({
  AuthProvider: ({ children }) => children,
  useAuth: () => ({ ...auth, logout: () => {}, refreshUser: async () => auth.user }),
}))
vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => esCelular, MOBILE_BREAKPOINT_PX: 768 }))

const pasa = ({ children }) => children
const marca = (nombre) => () => h('div', { 'data-pieza': nombre })
vi.mock('../contexts/ThemeContext', async (o) => ({ ...(await o()), ThemeProvider: pasa }))
vi.mock('../contexts/CurrencyContext', async (o) => ({ ...(await o()), CurrencyProvider: pasa }))
vi.mock('../contexts/PrivacyContext', async (o) => ({ ...(await o()), PrivacyProvider: pasa }))
vi.mock('../contexts/ModoRendimientoContext', async (o) => ({ ...(await o()), ModoRendimientoProvider: pasa }))
vi.mock('../contexts/CoachDrawerContext', async (o) => ({ ...(await o()), CoachDrawerProvider: pasa }))
vi.mock('../contexts/AlertsContext', async (o) => ({ ...(await o()), AlertsProvider: pasa }))
vi.mock('../contexts/VozContext', async (o) => ({ ...(await o()), VozProvider: pasa }))
vi.mock('../contexts/AdvisorContext', () => ({ AdvisorProvider: pasa, useAdvisorContext: () => ({ clientCtx: null }) }))
vi.mock('../components/TransicionDePantalla', () => ({ default: pasa, FUNDIDO_MS: 0, seccionDe: () => '' }))
vi.mock('../components/Sidebar', () => ({ default: marca('menu') }))
vi.mock('../components/mobile/MobileTopBar', () => ({ default: marca('barra-arriba') }))
vi.mock('../components/mobile/MobileTabBar', () => ({ default: marca('barra-abajo') }))
vi.mock('../components/MarketTicker', () => ({ default: marca('cinta') }))
vi.mock('../components/DemoBanner', () => ({ default: () => null }))
vi.mock('../components/advisor/ClientContextBar', () => ({ default: () => null }))
vi.mock('../components/CuentaCambiadaEnOtraPestana', () => ({ default: () => null }))
vi.mock('../components/BuscadorRapido', () => ({ default: marca('buscador') }))
vi.mock('../components/plan/TrialCta', async (o) => ({ ...(await o()), TrialBanner: marca('barra-prueba') }))
vi.mock('../components/plan/MuroElegirPlan', () => ({ default: marca('muro') }))
vi.mock('../components/plan/AvisoPrecios', () => ({ default: () => null }))
vi.mock('../components/SupportWhatsAppFab', async (o) => ({ ...(await o()), default: marca('whatsapp') }))
vi.mock('../components/voz/RendiMate', () => ({ default: marca('isla') }))
vi.mock('../components/tour/TourNovedades', () => ({ default: () => null }))
vi.mock('../components/tour/TourTecnico', () => ({ default: () => null }))
vi.mock('../utils/autoUpdate', () => ({ useAutoUpdate: () => {} }))
vi.mock('./Home', () => ({ default: marca('inicio') }))
vi.mock('./Onboarding', () => ({ default: marca('bienvenida') }))
vi.mock('../paginasPublicas', () => ({
  COMPONENTES_PUBLICOS: new Proxy({}, { get: (_, ruta) => marca(`publica:${String(ruta)}`) }),
  precargarPaginaPublica: () => {},
}))

let RR, App
beforeAll(async () => {
  instalarNavegadorMinimo()
  RR = await import('react-router-dom')
  ;({ default: App } = await import('../App'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  esCelular = false
  Object.assign(auth, { user: null, isDemo: false, bootstrapped: true })
})

const donde = {}
function Control() { donde.ahora = RR.useLocation().pathname; return null }
const arbol = (ruta) => h(RR.MemoryRouter, { initialEntries: [ruta] }, h(App), h(Control))

async function abrir(ruta) {
  montado = await montar(arbol(ruta))
  // La página llega por import diferido (lazy): unas vueltas para que aparezca.
  for (let i = 0; i < 4; i++) await enActo(async () => { await new Promise(r => setTimeout(r, 0)) })
}

function piezas() {
  const out = new Set()
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.atributos?.['data-pieza']) out.add(n.atributos['data-pieza'])
    pila.push(...(n.childNodes || []))
  }
  return out
}

const NUEVA = { name: 'Ana', email: 'ana@prueba.test', tier: 'pro', falta_cargar_historial: true }

describe('la puerta: a quien le falta cargar su historial', () => {
  it('compu: desde «/» termina en /onboarding, sin menú, sin barra de la prueba, sin cinta, sin ⌘K y sin la isla', async () => {
    auth.user = NUEVA
    await abrir('/')
    expect(donde.ahora).toBe('/onboarding')
    const p = piezas()
    expect(p.has('bienvenida')).toBe(true)
    for (const no of ['menu', 'barra-prueba', 'cinta', 'buscador', 'isla', 'inicio']) expect(p.has(no), no).toBe(false)
    // WhatsApp sí: es la ayuda a mano.
    expect(p.has('whatsapp')).toBe(true)
  })

  it('celular: lo mismo, sin las barras de arriba y de abajo', async () => {
    esCelular = true
    auth.user = NUEVA
    await abrir('/posiciones')
    expect(donde.ahora).toBe('/onboarding')
    const p = piezas()
    expect(p.has('bienvenida')).toBe(true)
    for (const no of ['barra-arriba', 'barra-abajo', 'isla']) expect(p.has(no), no).toBe(false)
    expect(p.has('whatsapp')).toBe(true)
  })

  it('/planes y lo legal quedan a la vista (por ahí se sale de una pausa y se lee lo que se acepta)', async () => {
    auth.user = NUEVA
    for (const ruta of ['/planes', '/terminos', '/privacidad']) {
      await abrir(ruta)
      expect(donde.ahora, ruta).toBe(ruta)
      expect(piezas().has(`publica:${ruta}`), ruta).toBe(true)
      await montado.desmontar(); montado = null
    }
  })

  it('no decide antes de que el servidor confirme la sesión (bootstrapped): espera, y después manda', async () => {
    auth.user = NUEVA
    auth.bootstrapped = false
    await abrir('/')
    expect(donde.ahora).toBe('/')
    expect(piezas().has('inicio')).toBe(false)   // no asoma la app mientras tanto
    auth.bootstrapped = true
    await montado.redibujar(arbol('/'))
    for (let i = 0; i < 4; i++) await enActo(async () => { await new Promise(r => setTimeout(r, 0)) })
    expect(donde.ahora).toBe('/onboarding')
  })
})

describe('la puerta no se mete con nadie más', () => {
  it('sin la marca del servidor: no redirige y la app se ve entera', async () => {
    auth.user = { ...NUEVA, falta_cargar_historial: false }
    await abrir('/')
    expect(donde.ahora).toBe('/')
    const p = piezas()
    expect(p.has('inicio')).toBe(true)
    expect(p.has('menu')).toBe(true)
    expect(p.has('isla')).toBe(true)
  })

  it('con la cuenta en pausa gana el muro de plan', async () => {
    auth.user = { ...NUEVA, cuenta_en_pausa: true }
    await abrir('/')
    expect(donde.ahora).toBe('/')
    expect(piezas().has('muro')).toBe(true)
    expect(piezas().has('bienvenida')).toBe(false)
  })

  it('el demo: nada', async () => {
    auth.user = { ...NUEVA, demo: true }
    auth.isDemo = true
    await abrir('/')
    expect(donde.ahora).toBe('/')
    expect(piezas().has('inicio')).toBe(true)
  })

  it('/onboarding se dibuja sin el armazón aunque no le falte nada (la página decide adónde va)', async () => {
    auth.user = { ...NUEVA, falta_cargar_historial: false }
    await abrir('/onboarding')
    const p = piezas()
    expect(p.has('bienvenida')).toBe(true)
    expect(p.has('menu')).toBe(false)
    expect(p.has('barra-prueba')).toBe(false)
  })
})
