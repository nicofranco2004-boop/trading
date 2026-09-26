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

const DE_PRUEBA = ['localhost', '127.0.0.1', '192.168.0.23', '[::1]', 'rendi-git-main-nico.vercel.app', 'rendi.finance.localhost', '']

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })

// Un navegador de mentira: registra cada <script> que la página intenta cargar.
function navegador(hostname, pathname = '/') {
  const cargados = []
  const script = () => ({})
  const win = {
    location: { hostname, pathname, href: `https://${hostname}${pathname}`, origin: `https://${hostname}` },
    addEventListener() {},
  }
  const doc = {
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
function correrSnippetDelHtml(hostname, pathname = '/') {
  const html = readFileSync(new URL('../../index.html', import.meta.url), 'utf8')
  const bloque = html.match(/<!-- Meta Pixel -->[\s\S]*?<script>([\s\S]*?)<\/script>/)
  expect(bloque, 'no encontré el bloque del píxel en index.html').not.toBeNull()
  const nav = navegador(hostname, pathname)
  // eslint-disable-next-line no-new-func
  new Function('win', `with (win) {\n${bloque[1]}\n}`)(nav.win)
  return nav
}

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
    expect(win.fbq.queue).toHaveLength(0)
  })
})
