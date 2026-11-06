import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo } from './testing/navegadorMinimo'

// RouteTracker (App.jsx) es el que le avisa a Google y al píxel de Meta cada
// cambio de dirección. Lo que gtag.js manda solo (scroll, tiempo en la página)
// lleva la última dirección que se le dio, y el píxel tiene que callarse en una
// dirección con datos: por eso el aviso va en TODO cambio de dirección, también
// cuando sólo cambian los parámetros (elegir una pestaña, tocar un porcentaje),
// y la vista de página sólo cuando cambia la pantalla. RouteTracker montado de
// verdad con react-router (testing/navegadorMinimo.js); lo que cada aviso hace
// lo prueban analytics.test.js y metaPixel.test.js.

const avisos = []
vi.mock('./utils/analytics', async (original) => ({
  ...(await original()),
  trackPageView: (p) => avisos.push(['vista Google', p]),
  actualizarDireccionParaGoogle: () => avisos.push(['dirección Google']),
}))
vi.mock('./utils/metaPixel', async (original) => ({
  ...(await original()),
  trackMetaPageView: () => avisos.push(['vista Meta']),
  sincronizarPixelConLaDireccion: () => avisos.push(['dirección Meta']),
}))
vi.mock('./utils/autoUpdate', async (original) => ({ ...(await original()), useAutoUpdate: () => {} }))
vi.mock('./utils/track', async (original) => ({ ...(await original()), trackRoute: () => {} }))
vi.mock('./utils/uso', async (original) => ({ ...(await original()), registrarPantalla: () => {} }))

let RouteTracker, RR
beforeAll(async () => {
  instalarNavegadorMinimo()
  RR = await import('react-router-dom')
  ;({ RouteTracker } = await import('./App'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null })

const mando = {}
function Control() {
  mando.ir = RR.useNavigate()
  ;[, mando.parametros] = RR.useSearchParams()
  return null
}

async function abrir(direccion) {
  avisos.length = 0
  montado = await montar(h(RR.MemoryRouter, { initialEntries: [direccion] }, h(RouteTracker), h(Control)))
}

describe('RouteTracker avisa cada cambio de dirección', () => {
  it('al abrir: la vista de Google y la dirección a los dos', async () => {
    await abrir('/cartera?tab=resumen')
    expect(avisos).toEqual([['vista Google', '/cartera'], ['dirección Google'], ['dirección Meta']])
  })

  it('sólo cambian los parámetros (setSearchParams con replace): la dirección a los dos, ninguna vista', async () => {
    await abrir('/analisis-tecnico?tab=backtesting')
    avisos.length = 0
    await enActo(() => mando.parametros({ tab: 'backtesting', activos: 'AAPL', pesos: '100' }, { replace: true }))
    expect(avisos).toEqual([['dirección Google'], ['dirección Meta']])
  })

  it('cambia la pantalla: las dos vistas y la dirección a los dos', async () => {
    await abrir('/cartera?tab=resumen')
    avisos.length = 0
    await enActo(() => mando.ir('/analisis?tab=resumen'))
    expect(avisos).toEqual([['vista Google', '/analisis'], ['vista Meta'], ['dirección Google'], ['dirección Meta']])
  })
})
