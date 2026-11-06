/**
 * El píxel de Meta sólo habla en una dirección limpia (rutasSensibles.js).
 *
 * fbevents lee la dirección y la página anterior por su cuenta, y la copia que
 * manda al servidor de Meta en Amazon las lleva completas: el email de cada
 * persona que se registra (/verify-email?email=…) y la cartera de «Una
 * cartera». Hoy no sale sólo porque la política de seguridad de vercel.json no
 * incluye ese servidor (y el envío directo a Meta recorta la dirección); el
 * píxel no puede depender de eso. Acá se mira qué le pide la app al píxel; que
 * fbevents se comporta así lo prueba, con el fbevents real,
 * audit/_scripts/fugas_a_terceros/.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })

const SITIO = 'https://rendi.finance'
const PIXEL = '1281911210681122'

// `estado`: lo que dejó el bloque de index.html ('iniciado' / 'esperando'), o
// null si el bloque no estaba (initMetaPixel hace todo).
function pestana(direccion, { referrer = '', estado = 'iniciado' } = {}) {
  const u = new URL(direccion, SITIO)
  const llamadas = []
  const win = {
    location: { hostname: 'rendi.finance', pathname: u.pathname, search: u.search, href: u.href, origin: u.origin },
    addEventListener() {},
  }
  if (estado) {
    win.fbq = (...a) => llamadas.push(a)
    win.__rendiPixel = estado
  }
  const doc = {
    referrer,
    createElement: () => ({}),
    getElementsByTagName: () => [{ parentNode: { insertBefore() {} } }],
  }
  win.window = win
  win.document = doc
  vi.stubGlobal('window', win)
  vi.stubGlobal('document', doc)
  const ir = (destino) => {
    const d = new URL(destino, SITIO)
    Object.assign(win.location, { pathname: d.pathname, search: d.search, href: d.href })
  }
  return { win, ir, llamadas }
}

async function cargar(direccion, opciones) {
  const p = pestana(direccion, opciones)
  const mp = await import('./metaPixel.js')
  mp.initMetaPixel()
  return { ...p, mp }
}

const enviados = (llamadas) => llamadas.filter((a) => a[0] === 'track').map((a) => a[1])

describe('lo pedido en una dirección que no es limpia espera a la próxima limpia', () => {
  it('el registro (la conversión de los anuncios) sale al llegar a /onboarding, no en /verify-email', async () => {
    const { mp, ir, llamadas } = await cargar('/verify-email')
    mp.trackMetaEvent('CompleteRegistration', { content_name: 'signup', status: true })
    expect(enviados(llamadas)).toEqual([])
    ir('/onboarding')
    mp.trackMetaPageView()
    expect(llamadas.filter((a) => a[0] === 'track')).toEqual([
      ['track', 'PageView', {}],
      ['track', 'CompleteRegistration', { content_name: 'signup', status: true }],
    ])
  })

  it('en la dirección con la cartera, ni la vista ni los eventos', async () => {
    const { mp, llamadas } = await cargar('/analisis-tecnico?tab=backtesting&activos=AAPL&pesos=100')
    mp.trackMetaPageView()
    mp.trackMetaEvent('Lead', {})
    expect(enviados(llamadas)).toEqual([])
  })

  it('viniendo de una página de Rendi con datos (recarga entera desde el login con email), nada sale', async () => {
    const { mp, llamadas } = await cargar('/', { referrer: `${SITIO}/login?email=ana%40x.com` })
    mp.trackMetaPageView()
    mp.trackMetaEvent('Lead', {})
    expect(enviados(llamadas)).toEqual([])
  })
})

describe('si se entró por una dirección que no es limpia, el píxel se inicia en la primera limpia', () => {
  it('init antes de la primera vista, y una sola vez', async () => {
    const { mp, ir, llamadas, win } = await cargar('/analisis-tecnico?tab=grafico&activo=GGAL', { estado: 'esperando' })
    mp.trackMetaPageView()
    expect(llamadas).toEqual([])
    ir('/cartera?tab=resumen')
    mp.trackMetaPageView()
    ir('/analisis?tab=resumen')
    mp.trackMetaPageView()
    expect(llamadas).toEqual([['init', PIXEL], ['track', 'PageView', {}], ['track', 'PageView', {}]])
    expect(win.__rendiPixel).toBe('iniciado')
  })
})

describe('en una dirección que no es limpia el píxel queda callado', () => {
  it('se calla al llegar y se abre al salir (lo que fbevents manda solo espera hasta entonces)', async () => {
    const { mp, ir, llamadas } = await cargar('/cartera?tab=resumen')
    mp.sincronizarPixelConLaDireccion()
    ir('/analisis-tecnico?tab=backtesting&activos=AAPL&pesos=100')
    mp.sincronizarPixelConLaDireccion()
    mp.sincronizarPixelConLaDireccion()
    ir('/analisis-tecnico?tab=backtesting&activos=AAPL&pesos=90')
    mp.sincronizarPixelConLaDireccion()
    ir('/cartera?tab=resumen')
    mp.sincronizarPixelConLaDireccion()
    expect(llamadas).toEqual([['consent', 'revoke'], ['consent', 'grant']])
  })

  it('una vista en la dirección limpia abre antes de mandar, aunque RouteTracker no haya avisado todavía', async () => {
    const { mp, ir, llamadas } = await cargar('/cartera')
    ir('/analisis-tecnico?activos=AAPL&pesos=100')
    mp.sincronizarPixelConLaDireccion()
    ir('/cartera')
    mp.trackMetaPageView()
    expect(llamadas).toEqual([['consent', 'revoke'], ['consent', 'grant'], ['track', 'PageView', {}]])
  })

  it('si nunca se inició, no hace falta callarlo', async () => {
    const { mp, llamadas } = await cargar('/analisis-tecnico?activo=GGAL', { estado: 'esperando' })
    mp.sincronizarPixelConLaDireccion()
    expect(llamadas).toEqual([])
  })
})

describe('sin el bloque de index.html, initMetaPixel hace lo mismo', () => {
  it('en una dirección con datos: sin vistas solas ni eventos automáticos, y esperando', async () => {
    const { win } = await cargar('/analisis-tecnico?activos=AAPL&pesos=100', { estado: null })
    expect(win.fbq.disablePushState).toBe(true)
    expect(win.fbq.allowDuplicatePageViews).toBe(true)
    const cola = win.fbq.queue.map((a) => [...a])
    expect(cola).toEqual([['set', 'autoConfig', false, PIXEL]])
    expect(win.__rendiPixel).toBe('esperando')
  })

  it('en una limpia: init + PageView', async () => {
    const { win } = await cargar('/?utm_source=ig', { estado: null })
    const cola = win.fbq.queue.map((a) => [...a])
    expect(cola).toEqual([['set', 'autoConfig', false, PIXEL], ['init', PIXEL], ['track', 'PageView']])
    expect(win.__rendiPixel).toBe('iniciado')
  })
})
