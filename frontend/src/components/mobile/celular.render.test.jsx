import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'

// Lo que rodea al menú "Más" en el celular, DIBUJADO: la barra de arriba y
// sus avisos, lo que se pega debajo al bajar, las páginas públicas con la
// sesión abierta y a dónde lleva la lupa. Cada caso es un hallazgo de auditoría
// que se veía en pantalla. (Dónde pone App.jsx cada aviso, en cada armado, lo
// prueba appShell.render.test.jsx dibujando la app entera.)
let usuario = { tier: 'pro' }
let cliente = null
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: usuario, logout: () => {} }) }))
vi.mock('../../contexts/AdvisorContext', () => ({
  useAdvisorContext: () => ({ clientCtx: cliente, enterClient: () => {}, exitClient: () => {} }),
}))
vi.mock('../../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('../CurrencySwitcher', () => ({ default: () => null }))
vi.mock('../Toast', () => ({ useToast: () => null }))

import MobileTopBar, { anotarAltoDeLaBarra, VARIABLE_ALTO_BARRA } from './MobileTopBar'
import fuenteBarra from './MobileTopBar.jsx?raw'
import ClientContextBar from '../advisor/ClientContextBar'
import MobileSearch from '../../pages/MobileSearch'
import fuenteDeApp from '../../App.jsx?raw'
import { CTA_PRUEBA } from '../../data/prueba'

const dibujar = (Componente, { u = usuario, c = cliente, props = {} } = {}) => {
  usuario = u; cliente = c
  // HelmetProvider: las páginas públicas ponen su <title> como en producción (main.jsx).
  return renderToStaticMarkup(<HelmetProvider context={{}}><MemoryRouter><Componente {...props} /></MemoryRouter></HelmetProvider>)
}
const ANA = { id: 7, label: 'Ana' }
const rutas = (html) => [...html.matchAll(/href="([^"]+)"/g)].map(m => m[1].replace(/&amp;/g, '&'))
const cabeceraDelCelular = (html) => html.slice(html.indexOf('<header'), html.indexOf('</header>') + 9)

describe('la barra de arriba del celular', () => {
  it('lo que le pasa App.jsx (los avisos) va ADENTRO de la barra, que se queda fija al bajar', () => {
    const html = dibujar(MobileTopBar, { props: { children: <p>AVISO-DE-PRUEBA</p> } })
    const header = cabeceraDelCelular(html)
    expect(header).toContain('AVISO-DE-PRUEBA')
    expect(header).toMatch(/^<header[^>]*class="[^"]*\bsticky top-0\b/)
  })
  it('la franja del cliente, dentro de la barra: corta, con el nombre a la vista', () => {
    // A 360-375 px "Estás viendo la cuenta de" + "Volver a mis clientes" no
    // dejaban lugar y el nombre del cliente quedaba cortado.
    const enLaBarra = dibujar(ClientContextBar, { u: { tier: 'advisor' }, c: ANA, props: { enLaBarra: true } })
    expect(enLaBarra).toMatch(/Cuenta de\s*<span[^>]*>Ana<\/span>/)
    expect(enLaBarra).toContain('aria-label="Volver a mis clientes"')
    expect(enLaBarra).not.toMatch(/\bsticky\b/)   // la que se queda fija es la barra
  })
  it('en la compu la franja va en el contenido, pegada arriba', () => {
    const contenido = dibujar(ClientContextBar, { u: { tier: 'advisor' }, c: ANA })
    expect(contenido).toContain('Estás viendo la cuenta de')
    expect(contenido).toMatch(/class="[^"]*\bsticky top-0\b/)
  })
  it('la lupa no aparece para el asesor en su nivel (busca para una cartera propia, que no tiene)', () => {
    expect(rutas(dibujar(MobileTopBar, { u: { tier: 'pro' }, c: null }))).toContain('/buscar')
    expect(rutas(dibujar(MobileTopBar, { u: { tier: 'advisor' }, c: ANA }))).toContain('/buscar')
    expect(rutas(dibujar(MobileTopBar, { u: { tier: 'advisor' }, c: null }))).not.toContain('/buscar')
  })
})

describe('la barra anota su alto, y lo que se pega debajo lo lee', () => {
  // Las cabeceras de Cartera y Movimientos, la burbuja de Rendi, la ficha de
  // una tenencia y el Onboarding se pegan DEBAJO de la barra al bajar. Cuando
  // cada una tenía el alto escrito a mano (88 px, 0) quedaban tapadas, o
  // tapaban la barra, cada vez que la barra cambió de alto.
  const raizFalsa = () => {
    const vars = {}
    return { vars, style: { setProperty: (k, v) => { vars[k] = v }, removeProperty: (k) => { delete vars[k] } } }
  }
  it('mide, vuelve a medir cuando la barra cambia y se borra al desarmarse', () => {
    let alto = 140.4
    const el = { getBoundingClientRect: () => ({ height: alto }) }
    let avisar = null, observado = null, desconectado = false
    class Observador { constructor(cb) { avisar = cb } observe(x) { observado = x } disconnect() { desconectado = true } }
    const raiz = raizFalsa()
    const deshacer = anotarAltoDeLaBarra(el, raiz, Observador)
    expect(raiz.vars[VARIABLE_ALTO_BARRA]).toBe('140px')
    expect(observado).toBe(el)
    alto = 93; avisar()                              // se cerró el cliente: la barra achicó
    expect(raiz.vars[VARIABLE_ALTO_BARRA]).toBe('93px')
    deshacer()                                       // se pasó al armado de compu
    expect(VARIABLE_ALTO_BARRA in raiz.vars).toBe(false)
    expect(desconectado).toBe(true)
  })
  it('sin ResizeObserver (Safari viejo) igual mide una vez', () => {
    const raiz = raizFalsa()
    anotarAltoDeLaBarra({ getBoundingClientRect: () => ({ height: 93 }) }, raiz, undefined)
    expect(raiz.vars[VARIABLE_ALTO_BARRA]).toBe('93px')
  })
  it('lo que mide es la barra ENTERA (el <header>), no una parte', () => {
    expect(fuenteBarra).toMatch(/<header\s+ref={barraRef}/)
    expect(fuenteBarra).toMatch(/useAnotarAlto\(barraRef\)/)
  })
})

// El árbol entero: cada elemento que se pega arriba (`sticky` con `top-…`). Se
// recorren las clases, no el archivo (un comentario que nombra la variable no
// cuenta), y se reconocen todas las formas de escribir un alto fijo.
describe('nada se pega arriba con un alto escrito a mano', () => {
  const fuentes = import.meta.glob(['/src/**/*.{js,jsx}', '!/src/**/*.test.{js,jsx}'], { query: '?raw', import: 'default', eager: true })
  // Los que pueden pegarse con un número, y por qué. Un archivo nuevo que se
  // pegue arriba tiene que leer la variable o anotarse acá con su motivo.
  const PERMITIDOS = {
    'components/mobile/MobileTopBar.jsx': 'es la barra',
    'components/mobile/avisos.js': 'los avisos en la compu (en el celular van dentro de la barra)',
    'components/import/ImportWizard.jsx': 'encabezado de una tabla con su propio scroll',
    'components/import/TenenciaUpload.jsx': 'encabezado de una tabla con su propio scroll',
    'pages/Admin.jsx': 'encabezados de tablas con su propio scroll',
    'pages/AdminPruebas.jsx': 'encabezados de tablas con su propio scroll',
    'pages/Positions.jsx': 'encabezado de la tabla de la compu',
    'pages/Landing.jsx': 'portada pública: no tiene la barra de la app',
  }
  const pegadosArriba = (src) => {
    const out = []
    for (const m of src.matchAll(/["'`]([^"'`\n]*\bsticky\b[^"'`\n]*)["'`]/g)) {
      for (const t of m[1].matchAll(/(?:^|\s)((?:[a-z]+:)?top-\S+)/g)) out.push(t[1])
    }
    return out
  }
  it('recorre la app entera', () => {
    expect(Object.keys(fuentes).length).toBeGreaterThan(200)
  })
  it('la barra anota el MISMO nombre que leen los demás', () => {
    // Si la barra cambia el nombre y los que lo leen no, todos caen a su valor
    // de respaldo (93 px) y la regresión vuelve sin que nada falle.
    expect(VARIABLE_ALTO_BARRA).toBe('--alto-barra-celular')
  })
  it('todo `sticky` con `top-…` lee --alto-barra-celular (o está en la lista, con su motivo)', () => {
    const malos = []
    for (const [ruta, src] of Object.entries(fuentes)) {
      const corta = ruta.replace('/src/', '')
      if (PERMITIDOS[corta]) continue
      for (const top of pegadosArriba(src)) {
        if (top.startsWith('md:') || top.startsWith('lg:')) continue   // sólo compu
        if (!top.includes(VARIABLE_ALTO_BARRA)) malos.push(`${corta}: ${top}`)
      }
    }
    expect(malos).toEqual([])
  })
  it('y los que tienen que leerla, la leen en la CLASE (no en un comentario)', () => {
    for (const nombre of ['pages/PositionsMobile.jsx', 'pages/Operations.jsx', 'pages/PositionDetailMobile.jsx', 'pages/Onboarding.jsx']) {
      const src = fuentes[`/src/${nombre}`]
      expect(pegadosArriba(src).some(t => t.includes(VARIABLE_ALTO_BARRA)), nombre).toBe(true)
    }
    expect(fuentes['/src/components/voz/RendiMate.jsx']).toMatch(/className="fixed top-\[calc\(var\(--alto-barra-celular/)
  })
})

describe('páginas públicas con la sesión abierta', () => {
  // Se dibujan adentro de la app. El encabezado público le ofrecía "Iniciar
  // sesión" a quien ya estaba adentro, "Probar demo" le cambiaba la cuenta por
  // la de la demo, y "Probar 20 días gratis" aparecía al final de las notas.
  // Se toman de las RUTAS que App.jsx registra para el que ya entró (AppRoutes):
  // una página nueva entra sola. Cuentan las que tienen algo para visitantes.
  const modulos = import.meta.glob(['/src/pages/**/*.jsx', '!/src/pages/**/*.test.jsx'], { import: 'default', eager: true })
  const fuentes = import.meta.glob(['/src/pages/**/*.jsx', '!/src/pages/**/*.test.jsx'], { query: '?raw', import: 'default', eager: true })
  const desde = fuenteDeApp.indexOf('function AppRoutes()')
  const rutasDeAdentro = fuenteDeApp.slice(desde, fuenteDeApp.indexOf('</Routes>', desde))
  const componentes = new Set([...rutasDeAdentro.matchAll(/element={<([A-Z]\w*)/g)].map(m => m[1]))
  const archivoDe = Object.fromEntries([
    ...fuenteDeApp.matchAll(/const (\w+) = lazy\(\(\) => import\('\.\/(pages\/[^']+)'\)\)/g),
    ...fuenteDeApp.matchAll(/import (\w+) from '\.\/(pages\/[^']+)'/g),
  ].map(m => [m[1], `/src/${m[2].replace(/\.jsx$/, '')}.jsx`]))
  // Una página "pública" es la que tiene algo para visitantes: el encabezado
  // público (directo o por su plantilla: GuidePage, BlogPost, KeywordLanding),
  // la demo, o un encabezado con el logo copiado a mano (justo lo que no tiene
  // que volver).
  const esPublica = (src) => /CabeceraPublica|SoloVisitantes|GuidePage|BlogPost|KeywordLanding|\?demo=1/.test(src)
    || (/<header/.test(src) && /RendiLogo/.test(src) && /to="\/(planes|login)/.test(src))
  const paginas = [...componentes].map(c => [c, archivoDe[c]]).filter(([, f]) => f && fuentes[f] && esPublica(fuentes[f]))

  const OFERTAS = [/>\s*Iniciar sesión\s*</, /Probar gratis/, new RegExp(CTA_PRUEBA), /Probar demo/, /Probá Rendi con tu cartera/, /Probalo con tu propia cartera/]
  const cabecera = /<header class="border-b border-line">/

  it('son por lo menos las 21 de hoy (Guía, Blog, landings de búsqueda, legales)', () => {
    expect(paginas.length).toBeGreaterThanOrEqual(21)
  })
  for (const [nombre, archivo] of paginas) {
    it(`${nombre}: con sesión, nada para visitantes; sin sesión, su encabezado`, () => {
      const Pagina = modulos[archivo]
      const adentro = dibujar(Pagina, { u: { tier: 'pro' }, c: null })
      expect(adentro).not.toMatch(cabecera)
      for (const oferta of OFERTAS) expect(adentro, String(oferta)).not.toMatch(oferta)
      // Por destino, no sólo por texto: un "Crear mi cuenta" también cuenta.
      expect(rutas(adentro).filter(r => r.startsWith('/login') || r.includes('demo=1'))).toEqual([])
      expect(dibujar(Pagina, { u: null, c: null })).toMatch(cabecera)
    })
  }
  it('al visitante no se le esconde nada de más', () => {
    const afuera = (n) => dibujar(modulos[archivoDe[n]], { u: null, c: null })
    // Guía: el encabezado con "Iniciar sesión" y la tarjeta de la demo.
    expect(afuera('Guia')).toMatch(/>\s*Iniciar sesión\s*</)
    expect(rutas(afuera('Guia'))).toContain('/?demo=1')
    // Landing de búsqueda: el "Probar gratis" de arriba, el botón grande y el
    // del final — los tres llevan a registrarse (se mira a dónde, no el texto).
    const cedears = afuera('LandingCedears')
    expect(rutas(cedears).filter(r => r === '/login?mode=register').length).toBeGreaterThanOrEqual(3)
    expect(cedears).toContain('Probalo con tu propia cartera')
    // Nota del Blog: el recuadro del final.
    expect(afuera('BlogFifoCedears')).toContain('Probá Rendi con tu cartera')
  })
})

describe('la lupa del celular (/buscar)', () => {
  // Cada fila es un enlace: se ve en el dibujo a dónde lleva. Sin nada escrito
  // ofrece los activos populares (los tuyos llegan después, del servidor). La
  // regla de cada tipo (CEDEAR, bono, ADR) la prueba utils/buscadorRapido.test.js.
  const destinos = (u, c) => rutas(dibujar(MobileSearch, { u, c }))
  it('lleva a donde lleva el ⌘K, nunca al destino viejo que nadie leía', () => {
    const r = destinos({ tier: 'pro' }, null)
    expect(r).toContain('/fundamentals?ticker=AAPL')
    expect(r).toContain('/fundamentals?ticker=YPF')                // YPFD → su ADR
    expect(r.filter(x => x.includes('.BA'))).toEqual([])
    expect(r.some(x => x.startsWith('/posiciones'))).toBe(false)
  })
  it('una acción argentina sin ADR se ofrece pero no lleva a ningún lado ni se ilumina al tocarla', () => {
    const html = dibujar(MobileSearch, { u: { tier: 'pro' }, c: null })
    expect(html).toContain('>COME<')
    expect(rutas(html).filter(x => x.includes('COME'))).toEqual([])
    const fila = html.slice(html.lastIndexOf('<div class="flex items-center gap-3 px-3', html.indexOf('>COME<')), html.indexOf('>COME<'))
    expect(fila).not.toContain('active:bg-bg-3')
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
