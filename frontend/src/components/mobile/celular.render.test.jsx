import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'

// Lo que rodea al menú "Más" en el celular, DIBUJADO: la franja del cliente
// abierto, el encabezado de la Guía y el Blog con la sesión abierta, y a dónde
// lleva la lupa. Cada caso es un hallazgo de auditoría que se veía en pantalla.
let usuario = { tier: 'pro' }
let cliente = null
let esCelular = true
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: usuario, logout: () => {} }) }))
vi.mock('../../contexts/AdvisorContext', () => ({
  useAdvisorContext: () => ({ clientCtx: cliente, enterClient: () => {}, exitClient: () => {} }),
}))
vi.mock('../../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('../../hooks/useIsMobile', () => ({ useIsMobile: () => esCelular, MOBILE_BREAKPOINT_PX: 768 }))
vi.mock('../CurrencySwitcher', () => ({ default: () => null }))
vi.mock('../Toast', () => ({ useToast: () => null }))

import MobileTopBar from './MobileTopBar'
import ClientContextBar from '../advisor/ClientContextBar'
import Guia from '../../pages/Guia'
import Blog from '../../pages/Blog'
import GuiaEmpezar from '../../pages/guia/Empezar'
import BlogFifoCedears from '../../pages/blog/articles/FifoCedearsArgentina'
import MobileSearch, { destinoDelTicker } from '../../pages/MobileSearch'
import { opcionesDeActivos, opcionesDeEmpresas } from '../../utils/buscadorRapido'

const dibujar = (Componente, { u = usuario, c = cliente, celular = esCelular } = {}) => {
  usuario = u; cliente = c; esCelular = celular
  // HelmetProvider: la Guía y el Blog ponen su <title> como en producción (main.jsx).
  return renderToStaticMarkup(<HelmetProvider context={{}}><MemoryRouter><Componente /></MemoryRouter></HelmetProvider>)
}
const ANA = { id: 7, label: 'Ana' }

describe('"Estás viendo la cuenta de…" en el celular', () => {
  // Iba en el contenido, pegada a 64 px del borde, que era el alto de la barra
  // de arriba hasta que se le sumó la cinta de cotizaciones: al bajar la
  // pantalla quedaba escondida detrás. Ahora va ADENTRO de la barra.
  it('va adentro de la barra de arriba, no suelta en el contenido', () => {
    const barra = dibujar(MobileTopBar, { u: { tier: 'advisor' }, c: ANA, celular: true })
    const header = barra.slice(barra.indexOf('<header'), barra.indexOf('</header>'))
    expect(header).toContain('Estás viendo la cuenta de')
    expect(header).toContain('Ana')
    // La copia del contenido no se dibuja en el celular (si no, saldría dos veces).
    expect(dibujar(ClientContextBar, { celular: true })).toBe('')
  })
  it('en la compu sigue en el contenido, pegada arriba, y no en la barra', () => {
    const contenido = dibujar(ClientContextBar, { u: { tier: 'advisor' }, c: ANA, celular: false })
    expect(contenido).toContain('Estás viendo la cuenta de')
    expect(contenido).toMatch(/class="[^"]*\bsticky top-0\b/)
    expect(renderToStaticMarkup(<MemoryRouter><ClientContextBar enLaBarra /></MemoryRouter>)).toBe('')
  })
  it('sin cliente abierto no aparece en ningún lado', () => {
    expect(dibujar(MobileTopBar, { u: { tier: 'advisor' }, c: null, celular: true })).not.toContain('Estás viendo')
  })
})

describe('Guía y Blog con la sesión abierta', () => {
  // Se dibujan adentro de la app (menú o barra del celular): el encabezado de
  // la página pública le ofrecía "Iniciar sesión" a quien ya estaba adentro.
  const PAGINAS = [['Guía', Guia], ['un capítulo de la Guía', GuiaEmpezar], ['Blog', Blog], ['una nota del Blog', BlogFifoCedears]]
  for (const [cual, Pagina] of PAGINAS) {
    it(`${cual}: sin "Iniciar sesión" ni "Probar gratis" arriba si ya entraste; con, si no`, () => {
      // El encabezado público es el <header> de borde simple (los capítulos y
      // las notas tienen otro <header> adentro, el del título). El texto de un
      // capítulo puede explicar cómo crear una cuenta: eso es contenido y queda.
      const cabecera = /<header class="border-b border-line">/
      const adentro = dibujar(Pagina, { u: { tier: 'pro' }, c: null })
      expect(adentro).not.toMatch(cabecera)
      expect(adentro).not.toMatch(/>\s*(Iniciar sesión|Probar gratis)\s*</)
      expect(adentro).not.toContain('Probá Rendi con tu cartera')   // el recuadro del final del Blog
      const afuera = dibujar(Pagina, { u: null, c: null })
      expect(afuera).toMatch(cabecera)
    })
  }
})

describe('la lupa del celular (/buscar)', () => {
  it('lleva a donde lleva el buscador ⌘K de la compu', () => {
    // Tuyo → la ficha del activo; no tuyo → la empresa en Calidad de cartera.
    for (const sim of ['NVDA', 'BRK.B', 'AL30']) {
      expect(destinoDelTicker({ symbol: sim, fromUser: true })).toBe(opcionesDeActivos([{ asset: sim }])[0].ir)
      expect(destinoDelTicker({ symbol: sim })).toBe(opcionesDeEmpresas([{ symbol: sim, name: sim }])[0].ir)
    }
  })
  it('al asesor en su nivel no le ofrece watchlist propia; a los demás, sí', () => {
    const estrella = 'aria-label="Agregar a watchlist"'
    expect(dibujar(MobileSearch, { u: { tier: 'pro' }, c: null })).toContain(estrella)
    expect(dibujar(MobileSearch, { u: { tier: 'advisor' }, c: ANA })).toContain(estrella)
    expect(dibujar(MobileSearch, { u: { tier: 'advisor' }, c: null })).not.toContain(estrella)
  })
})
