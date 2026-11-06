/**
 * Google Analytics y el píxel de Meta miden sólo en rendi.finance.
 *
 * Hasta el 2026-09-26 se cargaban en cualquier dirección: cada prueba en el
 * servidor local sumaba visitas en GA, PageViews en la audiencia de los
 * anuncios y, al probar el registro, un CompleteRegistration que Meta tomaba
 * como conversión real.
 *
 * Se prueba lo que corre en el navegador: `initAnalytics` e `initMetaPixel`
 * como los llama main.jsx, y el bloque del píxel de `index.html` tal cual está
 * escrito (corre antes que la app y tiene su propia copia de la lista).
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { SITIOS_MEDIDOS, seMideEn } from './medicion.js'
import { PARAMS_PERMITIDOS, RUTAS_SENSIBLES, referenteConDatos, urlTieneDatosSensibles } from './rutasSensibles.js'

const DE_PRUEBA = ['localhost', '127.0.0.1', '192.168.0.23', '[::1]', 'rendi-git-main-nico.vercel.app', 'rendi.finance.localhost', '']

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })

// Un navegador de mentira: registra cada <script> que la página intenta cargar.
// `direccion` puede traer parámetros ('/x?tab=1'); `referrer`, la página anterior.
function navegador(hostname, direccion = '/', referrer = '') {
  const cargados = []
  const script = () => ({})
  const u = new URL(direccion, `https://${hostname || 'x'}`)
  const win = {
    location: { hostname, pathname: u.pathname, search: u.search, href: `https://${hostname}${u.pathname}${u.search}`, origin: `https://${hostname}` },
    addEventListener() {},
  }
  const doc = {
    referrer,
    createElement: script,
    head: { appendChild: (el) => cargados.push(el.src) },
    getElementsByTagName: () => [{ parentNode: { insertBefore: (el) => cargados.push(el.src) } }],
  }
  win.window = win
  win.document = doc
  return { win, doc, cargados }
}

async function arrancarApp(hostname) {
  const nav = navegador(hostname)
  vi.stubGlobal('window', nav.win)
  vi.stubGlobal('document', nav.doc)
  const { initAnalytics, trackEvent } = await import('./analytics.js')
  const { initMetaPixel, trackMetaEvent } = await import('./metaPixel.js')
  initAnalytics()
  initMetaPixel()
  return { ...nav, trackEvent, trackMetaEvent }
}

// El bloque del píxel de index.html, ejecutado con el `window` de mentira.
// `with` hace que `fbq`, `location` y `document` sueltos lean ese objeto,
// igual que en el navegador leen el `window` de verdad.
function bloqueDelHtml() {
  const html = readFileSync(new URL('../../index.html', import.meta.url), 'utf8')
  const bloque = html.match(/<!-- Meta Pixel -->[\s\S]*?<script>([\s\S]*?)<\/script>/)
  expect(bloque, 'no encontré el bloque del píxel en index.html').not.toBeNull()
  return bloque[1]
}

function correrSnippetDelHtml(hostname, direccion = '/', referrer = '') {
  const nav = navegador(hostname, direccion, referrer)
  // eslint-disable-next-line no-new-func
  new Function('win', `with (win) {\n${bloqueDelHtml()}\n}`)(nav.win)
  return nav
}

const cola = (win) => win.fbq.queue.map((a) => [...a])
const seInicio = (win) => cola(win).some((a) => a[0] === 'init')

describe('qué direcciones se miden', () => {
  it('rendi.finance y www.rendi.finance, nada más', () => {
    for (const h of SITIOS_MEDIDOS) expect(seMideEn(h), h).toBe(true)
    for (const h of DE_PRUEBA) expect(seMideEn(h), h).toBe(false)
  })
})

describe('la app (main.jsx) no carga GA ni Meta fuera de rendi.finance', () => {
  it.each(DE_PRUEBA.filter(Boolean))('en %s no se pide ningún script ni se manda nada', async (host) => {
    const { win, cargados, trackEvent, trackMetaEvent } = await arrancarApp(host)
    expect(cargados).toEqual([])
    expect(win.gtag).toBeUndefined()
    expect(win.fbq).toBeUndefined()
    // Aunque algo (una extensión, otra pestaña) haya dejado un fbq/gtag
    // colgado, los eventos de registro no salen.
    win.fbq = vi.fn()
    win.gtag = vi.fn()
    trackMetaEvent('CompleteRegistration')
    trackEvent('sign_up')
    expect(win.fbq).not.toHaveBeenCalled()
    expect(win.gtag).not.toHaveBeenCalled()
  })

  it('en rendi.finance se cargan los dos, como siempre', async () => {
    const { win, cargados, trackMetaEvent } = await arrancarApp('rendi.finance')
    expect(cargados.some(u => u.startsWith('https://www.googletagmanager.com/gtag/js'))).toBe(true)
    expect(cargados.some(u => u.startsWith('https://connect.facebook.net/'))).toBe(true)
    expect(typeof win.gtag).toBe('function')
    trackMetaEvent('CompleteRegistration')
    expect(win.fbq.queue.map(a => [...a])).toContainEqual(['track', 'CompleteRegistration', {}])
  })
})

describe('el píxel de index.html (corre antes que la app) respeta la misma lista', () => {
  it.each(DE_PRUEBA)('en "%s" no carga fbevents ni crea fbq', (host) => {
    const { win, cargados } = correrSnippetDelHtml(host)
    expect(cargados).toEqual([])
    expect(win.fbq).toBeUndefined()
  })

  it.each(SITIOS_MEDIDOS)('en %s carga fbevents y manda init + PageView', (host) => {
    const { win, cargados } = correrSnippetDelHtml(host)
    expect(cargados).toEqual(['https://connect.facebook.net/en_US/fbevents.js'])
    const cola = win.fbq.queue.map(a => [...a])
    expect(cola).toContainEqual(['init', '1281911210681122'])
    expect(cola).toContainEqual(['track', 'PageView'])
  })

  it('en rendi.finance/claim sigue sin mandar el PageView (la URL lleva un secreto)', () => {
    const { win } = correrSnippetDelHtml('rendi.finance', '/claim/abc')
    expect(cola(win).filter((a) => a[0] === 'init' || a[0] === 'track')).toEqual([])
    expect(win.__rendiPixel).toBe('esperando')
  })
})

// fbevents lee la dirección por su cuenta y la copia que manda al servidor de
// Meta en Amazon la lleva completa (verificado con el fbevents real:
// audit/_scripts/fugas_a_terceros/). El bloque decide si se inicia.
describe('el píxel de index.html sólo se inicia en una dirección limpia (lista de PERMITIDOS)', () => {
  it('sus listas son las de rutasSensibles.js, una por una', () => {
    const bloque = bloqueDelHtml()
    const lista = (nombre) => JSON.parse(bloque.match(new RegExp(`var ${nombre} = (\\[[\\s\\S]*?\\]);`))[1].replace(/'/g, '"'))
    expect(lista('rutas')).toEqual(RUTAS_SENSIBLES)
    expect(lista('permitidos')).toEqual(PARAMS_PERMITIDOS)
    expect(lista('sitios')).toEqual(SITIOS_MEDIDOS)
  })

  it('siempre: sin vistas solas al cambiar la dirección, sin eventos automáticos, antes del init', () => {
    const { win } = correrSnippetDelHtml('rendi.finance', '/?utm_source=ig')
    expect(win.fbq.disablePushState).toBe(true)
    expect(win.fbq.allowDuplicatePageViews).toBe(true)
    const c = cola(win)
    const autoConfig = c.findIndex((a) => a[0] === 'set' && a[1] === 'autoConfig' && a[2] === false && a[3] === '1281911210681122')
    expect(autoConfig).toBeGreaterThanOrEqual(0)
    expect(autoConfig).toBeLessThan(c.findIndex((a) => a[0] === 'init'))
    expect(win.__rendiPixel).toBe('iniciado')
  })

  it('la cartera de «Una cartera» en la dirección: no se inicia (queda esperando)', () => {
    const { win } = correrSnippetDelHtml('rendi.finance', '/analisis-tecnico?tab=backtesting&modo=cartera&activos=AAPL,GGAL&pesos=50,50')
    expect(seInicio(win)).toBe(false)
    expect(win.__rendiPixel).toBe('esperando')
  })

  it('viniendo de una página de Rendi con datos (el login con el email), tampoco', () => {
    const { win } = correrSnippetDelHtml('rendi.finance', '/', 'https://rendi.finance/login?email=ana%40x.com')
    expect(seInicio(win)).toBe(false)
  })

  it('decide igual que rutasSensibles.js en cada dirección (también con parámetros inventados)', () => {
    const casos = [
      ['/', ''], ['/planes?plan=pro&period=annual', ''], ['/login?mode=register', ''],
      ['/?d=x-20261019&utm_source=ig&fbclid=IwAR0', 'https://l.instagram.com/'],
      ['/?gclid=Cj0&gad_source=1&gad_campaignid=9', 'https://www.google.com/'],
      ['/analisis-tecnico?tab=grafico&activo=GGAL', ''], ['/i/TOKEN', ''], ['/I/TOKEN', ''],
      ['/reset-password?token=abc', ''], ['/verify-email', ''], ['/cartera?tab=resumen#GGAL', ''],
      ['/', 'https://rendi.finance/'], ['/', 'https://www.rendi.finance/cartera?tab=resumen'],
      ['/', 'https://rendi.finance/analisis-tecnico?pesos=50'], ['/', 'https://rendi.finance/i/TOKEN'],
      ['/cartera?tab=resumen&otro=1', ''], ['/?utm_source=ig&utm_source=fb', ''],
    ]
    for (const n of ['zz', 'a_b', 'Tab', 'UTM_SOURCE', 'email2', 'x9']) casos.push([`/cartera?tab=resumen&${n}=1`, ''])
    for (const [direccion, referrer] of casos) {
      const { win } = correrSnippetDelHtml('rendi.finance', direccion, referrer)
      const u = new URL(direccion, 'https://rendi.finance')
      const esperado = !urlTieneDatosSensibles(u.pathname, u.search) && !referenteConDatos(referrer)
      expect(seInicio(win), `${direccion} viniendo de «${referrer}»`).toBe(esperado)
    }
  })
})
