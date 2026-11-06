/**
 * Qué dirección recibe Google en CADA envío, no sólo en el page_view.
 *
 * gtag.js lee la barra de direcciones por su cuenta en todo lo que manda (el
 * scroll, los clics, el tiempo en la página, cada evento): hasta el 2026-11-05
 * así le llegaban la cartera de «Una cartera» y el token del informe público
 * aunque el page_view estuviera filtrado. La app le fija la dirección limpia
 * con gtag('set', …) antes de cada envío. Acá se mira la cola (dataLayer) tal
 * como la arma la app; que gtag.js la respeta lo prueba, con el gtag.js real de
 * la propiedad, audit/_scripts/fugas_a_terceros/.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { PARAMS_PERMITIDOS } from './rutasSensibles.js'

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })

const SITIO = 'https://rendi.finance'

function pestana(direccion, { referrer = '', titulo = 'Rendi' } = {}) {
  const u = new URL(direccion, SITIO)
  const win = {
    location: { hostname: 'rendi.finance', pathname: u.pathname, search: u.search, href: u.href, origin: u.origin },
    addEventListener() {},
  }
  const doc = { referrer, title: titulo, createElement: () => ({}), head: { appendChild() {} } }
  win.window = win
  win.document = doc
  vi.stubGlobal('window', win)
  vi.stubGlobal('document', doc)
  // React Router cambia la dirección sin recargar la página.
  const ir = (destino) => {
    const d = new URL(destino, SITIO)
    Object.assign(win.location, { pathname: d.pathname, search: d.search, href: d.href })
  }
  const cola = () => (win.dataLayer || []).map((a) => [...a])
  const sets = () => cola().filter((a) => a[0] === 'set' && a[1] && 'page_location' in a[1]).map((a) => a[1])
  const vistas = () => cola().filter((a) => a[0] === 'event' && a[1] === 'page_view').map((a) => a[2])
  return { win, ir, cola, sets, vistas }
}

async function arrancar(direccion, opciones) {
  const p = pestana(direccion, opciones)
  const ga = await import('./analytics.js')
  ga.initAnalytics()
  return { ...p, ga }
}

const CARTERA = '/analisis-tecnico?tab=backtesting&modo=cartera&activos=AAPL,GGAL,BTC&pesos=50,30,20&local=GGAL&anios=2'

describe('Google recibe la dirección limpia en todo lo que manda', () => {
  it('antes del primer envío ya tiene la dirección limpia (gtag.js la usa para el scroll, los clics y cada evento)', async () => {
    const { cola, sets } = await arrancar(CARTERA)
    expect(sets()).toEqual([{
      page_location: `${SITIO}/analisis-tecnico?tab=backtesting&modo=cartera&anios=2`,
      page_referrer: '',
      page_title: undefined,
    }])
    const primerSet = cola().findIndex((a) => a[0] === 'set')
    const primerEnvio = cola().findIndex((a) => a[0] === 'event')
    expect(primerEnvio === -1 || primerSet < primerEnvio).toBe(true)
  })

  it('el page_view también lleva la limpia, y nada de la cartera sale por ningún lado', async () => {
    const { ga, cola, vistas, win } = await arrancar(CARTERA)
    ga.trackPageView(win.location.pathname)
    ga.trackEvent('ai_chat_sent', { source: 'chat' })
    expect(vistas()).toHaveLength(1)
    expect(vistas()[0].page_location).toBe(`${SITIO}/analisis-tecnico?tab=backtesting&modo=cartera&anios=2`)
    const todo = JSON.stringify(cola())
    for (const dato of ['AAPL', 'BTC', 'pesos', '50,30,20', 'local']) expect(todo).not.toContain(dato)
  })

  it('el informe público: ninguna vista, sólo /i/ y el título «Rendi» (el de la página nombra al cliente)', async () => {
    const { ga, cola, vistas, sets } = await arrancar('/i/TOKENSECRETO', { titulo: 'Informe de cartera — Ana Pérez' })
    ga.trackPageView('/i/TOKENSECRETO')
    expect(vistas()).toEqual([])
    expect(sets()).toEqual([{ page_location: `${SITIO}/i/`, page_referrer: '', page_title: 'Rendi' }])
    const todo = JSON.stringify(cola())
    expect(todo).not.toContain('TOKENSECRETO')
    expect(todo).not.toContain('Ana')
  })

  it('al cambiar de dirección: la nueva limpia, la anterior como «de dónde venía», y vuelve el título real', async () => {
    const { ga, ir, sets } = await arrancar('/i/TOKENSECRETO')
    ir('/cartera?tab=resumen')
    ga.actualizarDireccionParaGoogle()
    ir(CARTERA)
    ga.actualizarDireccionParaGoogle()
    expect(sets().slice(1)).toEqual([
      { page_location: `${SITIO}/cartera?tab=resumen`, page_referrer: `${SITIO}/i/`, page_title: undefined },
      { page_location: `${SITIO}/analisis-tecnico?tab=backtesting&modo=cartera&anios=2`, page_referrer: `${SITIO}/cartera?tab=resumen`, page_title: undefined },
    ])
  })

  it('sólo cuando cambia: cambiar un parámetro que no sale no repite el set', async () => {
    const { ga, ir, sets } = await arrancar(CARTERA)
    ir(CARTERA.replace('50,30,20', '60,20,20'))
    ga.actualizarDireccionParaGoogle()
    expect(sets()).toHaveLength(1)
  })

  it('al entrar, de dónde venía: la página de Rendi limpia, la de afuera sin su query', async () => {
    const { sets } = await arrancar('/', { referrer: `${SITIO}/login?email=ana%40x.com&next=%2Fcartera` })
    expect(sets()[0].page_referrer).toBe(`${SITIO}/login`)
    vi.resetModules()
    const otra = await arrancar('/?utm_source=ig', { referrer: 'https://l.instagram.com/?u=https%3A%2F%2Frendi.finance&e=AT0' })
    expect(otra.sets()[0]).toEqual({ page_location: `${SITIO}/?utm_source=ig`, page_referrer: 'https://l.instagram.com/', page_title: undefined })
  })

  it('desde la app de Gmail o del buscador de Google en Android, Google sigue viendo de qué app vino', async () => {
    const { sets } = await arrancar('/', { referrer: 'android-app://com.google.android.googlequicksearchbox/https/www.google.com' })
    expect(sets()[0].page_referrer).toBe('android-app://com.google.android.googlequicksearchbox/https/www.google.com')
  })

  it('falla cerrado: con parámetros inventados, cada dirección que sale tiene sólo permitidos', async () => {
    const { ga, ir, cola } = await arrancar('/')
    for (const n of ['zz', 'cartera', 'Tab', 'saldo_usd', 'x_1', 'q', 'search', 'email2']) {
      ir(`/cartera?tab=resumen&${n}=DATO&utm_source=ig`)
      ga.actualizarDireccionParaGoogle()
      ga.trackPageView('/cartera')
    }
    const direcciones = cola().flatMap((a) => [a[1]?.page_location, a[1]?.page_referrer, a[2]?.page_location]).filter(Boolean)
    expect(direcciones.length).toBeGreaterThan(8)
    for (const d of direcciones) {
      for (const k of new URL(d).searchParams.keys()) expect(PARAMS_PERMITIDOS, `${k} en ${d}`).toContain(k)
    }
  })
})

describe('el número de cuenta no se le manda a Google', () => {
  it('setUserId no agrega nada a la cola: ni un config (descartado por la propiedad), ni el número', async () => {
    const { ga, cola } = await arrancar('/cartera?tab=resumen')
    const antes = cola().length
    ga.setUserId(1234)
    ga.setUserId(null)
    expect(cola()).toHaveLength(antes)
    expect(cola().filter((a) => a[0] === 'config')).toHaveLength(1)
    expect(JSON.stringify(cola())).not.toContain('1234')
  })
})
