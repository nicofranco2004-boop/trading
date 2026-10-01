import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'

// Lo que rodea al menú "Más" en el celular, DIBUJADO: la franja del cliente
// abierto, el encabezado de las páginas públicas con la sesión abierta, y a
// dónde lleva la lupa. Cada caso es un hallazgo de auditoría que se veía en
// pantalla.
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
import MobileSearch from '../../pages/MobileSearch'
import { CTA_PRUEBA } from '../../data/prueba'

const dibujar = (Componente, { u = usuario, c = cliente, celular = esCelular, props = {} } = {}) => {
  usuario = u; cliente = c; esCelular = celular
  // HelmetProvider: las páginas públicas ponen su <title> como en producción (main.jsx).
  return renderToStaticMarkup(<HelmetProvider context={{}}><MemoryRouter><Componente {...props} /></MemoryRouter></HelmetProvider>)
}
const ANA = { id: 7, label: 'Ana' }
const rutas = (html) => [...html.matchAll(/href="([^"]+)"/g)].map(m => m[1].replace(/&amp;/g, '&'))
const cabeceraDelCelular = (html) => html.slice(html.indexOf('<header'), html.indexOf('</header>') + 9)

describe('la barra de arriba del celular', () => {
  // La franja iba en el contenido, pegada a 64 px del borde, que era el alto
  // de la barra hasta que se le sumó la cinta: al bajar quedaba escondida.
  it('la franja del cliente va adentro, con el nombre a la vista', () => {
    const barra = dibujar(MobileTopBar, { u: { tier: 'advisor' }, c: ANA, celular: true })
    const header = cabeceraDelCelular(barra)
    expect(header).toMatch(/Cuenta de\s*<span[^>]*>Ana<\/span>/)
    expect(header).toContain('aria-label="Volver a mis clientes"')
    // La copia del contenido no se dibuja en el celular (si no, saldría dos veces).
    expect(dibujar(ClientContextBar, { celular: true })).toBe('')
  })
  it('la barra se queda fija arriba al bajar (si no, la franja se iría con el scroll)', () => {
    const header = cabeceraDelCelular(dibujar(MobileTopBar, { u: { tier: 'advisor' }, c: ANA, celular: true }))
    expect(header).toMatch(/^<header[^>]*class="[^"]*\bsticky top-0\b/)
  })
  it('en la compu la franja sigue en el contenido, pegada arriba, y no en la barra', () => {
    const contenido = dibujar(ClientContextBar, { u: { tier: 'advisor' }, c: ANA, celular: false })
    expect(contenido).toContain('Estás viendo la cuenta de')
    expect(contenido).toMatch(/class="[^"]*\bsticky top-0\b/)
    expect(dibujar(ClientContextBar, { celular: false, props: { enLaBarra: true } })).toBe('')
  })
  it('sin cliente abierto no aparece en ningún lado', () => {
    expect(dibujar(MobileTopBar, { u: { tier: 'advisor' }, c: null, celular: true })).not.toContain('Cuenta de')
  })
  it('la lupa no aparece para el asesor en su nivel (busca para una cartera propia, que no tiene)', () => {
    expect(rutas(dibujar(MobileTopBar, { u: { tier: 'pro' }, c: null }))).toContain('/buscar')
    expect(rutas(dibujar(MobileTopBar, { u: { tier: 'advisor' }, c: ANA }))).toContain('/buscar')
    expect(rutas(dibujar(MobileTopBar, { u: { tier: 'advisor' }, c: null }))).not.toContain('/buscar')
  })
})

// Lo que se pega arriba al bajar se ubica debajo de la barra del celular, cuyo
// alto anota MobileTopBar en --alto-barra-celular. Con un número escrito a
// mano (88 px, top-0) quedaban tapados — o tapaban la barra — cada vez que la
// barra cambió de alto. Esto se pone en rojo si alguien vuelve a escribirlo.
describe('nadie tiene escrito a mano el alto de la barra de arriba', () => {
  const fuentes = import.meta.glob(['../../**/*.jsx', '!../../**/*.test.jsx'], { query: '?raw', import: 'default', eager: true })
  it('no hay `top-[88px]`, `top-16` ni `top-[64px]` en lo que se dibuja', () => {
    expect(Object.keys(fuentes).length).toBeGreaterThan(200)
    const conAlto = Object.entries(fuentes)
      .filter(([, src]) => /\btop-\[(88|64|93)px\]|(^|[\s"'`])top-16\b/.test(src))
      .map(([ruta]) => ruta)
    expect(conAlto).toEqual([])
  })
  it('lo que se pega arriba en el contenido del celular lee la variable, en CADA lugar', () => {
    const deben = Object.entries(fuentes).filter(([ruta]) => /\/(PositionsMobile|Operations|TrialCta|DemoBanner|RendiMate)\.jsx$/.test(ruta))
    expect(deben).toHaveLength(5)
    for (const [ruta, src] of deben) {
      expect(src, ruta).toContain('--alto-barra-celular')
      // Con `sticky top-0` se monta encima de la barra al bajar (TrialCta tiene dos).
      expect(src, ruta).not.toMatch(/\bsticky top-0\b/)
    }
  })
})

describe('páginas públicas con la sesión abierta (Guía, Blog, landings de búsqueda)', () => {
  // Se dibujan adentro de la app. El encabezado público le ofrecía "Iniciar
  // sesión" a quien ya estaba adentro, "Probar demo" le cambiaba la cuenta por
  // la de la demo, y "Probar 20 días gratis" aparecía al final de las notas.
  // Se recorre la carpeta: una página nueva entra sola.
  const paginas = {
    ...import.meta.glob(['../../pages/guia/*.jsx', '../../pages/blog/articles/*.jsx', '../../pages/keywords/*.jsx'], { import: 'default', eager: true }),
    ...import.meta.glob(['../../pages/Guia.jsx', '../../pages/Blog.jsx'], { import: 'default', eager: true }),
  }
  const OFERTAS_DE_VISITANTE = [/>\s*Iniciar sesión\s*</, /Probar gratis/, new RegExp(CTA_PRUEBA), /Probar demo/, /\?demo=1/, /Probá Rendi con tu cartera/, /Probalo con tu propia cartera/]
  const cabecera = /<header class="border-b border-line">/

  it('son por lo menos las 18 que hay hoy', () => {
    expect(Object.keys(paginas).length).toBeGreaterThanOrEqual(18)
  })
  for (const [ruta, Pagina] of Object.entries(paginas)) {
    const cual = ruta.replace('../../pages/', '')
    it(`${cual}: con sesión, nada para visitantes; sin sesión, el encabezado con "Iniciar sesión" o "Probar gratis"`, () => {
      const adentro = dibujar(Pagina, { u: { tier: 'pro' }, c: null })
      expect(adentro).not.toMatch(cabecera)
      for (const oferta of OFERTAS_DE_VISITANTE) expect(adentro, String(oferta)).not.toMatch(oferta)
      const afuera = dibujar(Pagina, { u: null, c: null })
      expect(afuera).toMatch(cabecera)
      const desde = afuera.search(cabecera)
      expect(afuera.slice(desde, afuera.indexOf('</header>', desde))).toMatch(/Iniciar sesión|Probar gratis/)
    })
  }
  it('al visitante, el Blog le sigue ofreciendo la prueba al final de cada nota', () => {
    const notas = Object.entries(paginas).filter(([r]) => r.includes('/blog/articles/'))
    expect(notas.length).toBeGreaterThan(0)
    for (const [ruta, Nota] of notas) expect(dibujar(Nota, { u: null, c: null }), ruta).toContain('Probá Rendi con tu cartera')
  })
})

describe('la lupa del celular (/buscar)', () => {
  // Cada fila es un enlace: se ve en el dibujo a dónde lleva. Sin nada escrito
  // ofrece los activos populares (los tuyos llegan después, del servidor).
  const destinos = (u, c) => rutas(dibujar(MobileSearch, { u, c }))
  it('lleva a donde lleva el ⌘K: la empresa, y un CEDEAR por su acción de EE.UU.', () => {
    const r = destinos({ tier: 'pro' }, null)
    expect(r).toContain('/fundamentals?ticker=AAPL')
    expect(r.filter(x => x.includes('.BA'))).toEqual([])            // ningún CEDEAR en pesos
    expect(r.some(x => x.startsWith('/posiciones'))).toBe(false)    // el destino viejo que nadie leía
  })
  it('cada fila usa la regla compartida (destinoDeTicker): una fila sin destino no es enlace', () => {
    // Sin escribir nada, la lupa muestra acciones (con destino). Bonos y cripto
    // (sin destino) recién aparecen al buscar; su regla la prueba
    // utils/buscadorRapido.test.js. Acá: que la fila respete lo que diga la regla.
    const html = dibujar(MobileSearch, { u: { tier: 'pro' }, c: null })
    const filas = (html.match(/aria-label="Agregar a watchlist"/g) || []).length
    expect(filas).toBeGreaterThan(10)
    expect(rutas(html).filter(x => x.startsWith('/fundamentals')).length).toBe(filas * 2) // la fila y su flecha
    expect(rutas(html)).toContain('/fundamentals?ticker=GGAL')     // acción argentina con ADR
  })
  it('al asesor en su nivel no le ofrece cartera, watchlist ni empresas; adentro de un cliente, sí', () => {
    const estrella = 'aria-label="Agregar a watchlist"'
    expect(dibujar(MobileSearch, { u: { tier: 'pro' }, c: null })).toContain(estrella)
    expect(dibujar(MobileSearch, { u: { tier: 'advisor' }, c: ANA })).toContain(estrella)
    expect(destinos({ tier: 'advisor' }, ANA)).toContain('/fundamentals?ticker=AAPL')
    const suNivel = dibujar(MobileSearch, { u: { tier: 'advisor' }, c: null })
    expect(suNivel).not.toContain(estrella)
    expect(rutas(suNivel).filter(x => x.startsWith('/fundamentals') || x.startsWith('/activo'))).toEqual([])
  })
})
