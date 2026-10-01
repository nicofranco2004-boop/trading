import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'

// La app ENTERA, dibujada en sus dos armados (celular y compu). App.jsx es el
// que decide qué piezas van en pantalla y dónde; ninguna otra prueba lo dibujaba,
// así que sacar la franja "Estás viendo la cuenta de…" de un armado, o dibujarla
// dos veces, pasaba en verde. Se reemplaza sólo lo que necesita un servidor: la
// sesión, el cliente abierto y el ancho de la pantalla.
let esCelular = true
let cliente = { id: 7, label: 'Ana' }
let usuario = { tier: 'advisor', name: 'Asesor' }
let enDemo = false
let enPrueba = false
vi.mock('./contexts/AuthContext', () => ({
  AuthProvider: ({ children }) => children,
  useAuth: () => ({ user: usuario, logout: () => {}, loading: false, isDemo: enDemo, exitDemo: () => {} }),
}))
// La prueba gratis llega del servidor; acá se la prende a mano (el resto del
// hook queda el de verdad).
vi.mock('./hooks/usePlanFeatures', async (original) => {
  const real = await original()
  return {
    ...real,
    usePlanFeatures: () => {
      const r = real.usePlanFeatures()
      return enPrueba ? { ...r, trial: { active: true, stage: 'pro', days_left: 12 } } : r
    },
  }
})
vi.mock('./contexts/AdvisorContext', () => ({
  AdvisorProvider: ({ children }) => children,
  useAdvisorContext: () => ({ clientCtx: cliente, enterClient: () => {}, exitClient: () => {} }),
}))
vi.mock('./hooks/useIsMobile', () => ({ useIsMobile: () => esCelular, MOBILE_BREAKPOINT_PX: 768 }))

beforeAll(() => {
  vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => {}, removeItem: () => {} })
})
afterAll(() => { vi.unstubAllGlobals() })

import App from './App'
import fuenteDeApp from './App.jsx?raw'

const dibujar = (celular, c, en = '/dashboard') => {
  esCelular = celular; cliente = c
  return renderToStaticMarkup(
    <HelmetProvider context={{}}><MemoryRouter initialEntries={[en]}><App /></MemoryRouter></HelmetProvider>)
}
const veces = (html, texto) => html.split(texto).length - 1

describe('la franja del cliente abierto, en la app entera', () => {
  it('celular: una sola vez, adentro de la barra de arriba', () => {
    const html = dibujar(true, { id: 7, label: 'Ana' })
    expect(veces(html, 'aria-label="Volver a mis clientes"')).toBe(1)
    const barra = html.slice(html.indexOf('<header'), html.indexOf('</header>'))
    expect(barra).toContain('aria-label="Volver a mis clientes"')
  })
  it('compu: una sola vez, en el contenido', () => {
    const html = dibujar(false, { id: 7, label: 'Ana' })
    expect(veces(html, 'Estás viendo la cuenta de')).toBe(1)
  })
  it('sin cliente abierto, en ningún armado', () => {
    expect(dibujar(true, null)).not.toContain('Volver a mis clientes')
    expect(dibujar(false, null)).not.toContain('Volver a mis clientes')
  })
})

describe('el armado del celular', () => {
  it('tiene la barra de arriba y la de abajo con "Más", y "Más" es una ruta de la app', () => {
    const html = dibujar(true, null, '/mas')
    expect(html).toContain('aria-label="Navegación principal"')
    expect(html).toContain('href="/mas"')
    // Las pantallas se cargan aparte (lazy): el dibujo no llega a ellas, la ruta se mira en App.jsx.
    expect(fuenteDeApp).toMatch(/<Route path="\/mas" element={<More \/>} \/>/)
  })
})

describe('los avisos de arriba de todo (demo, prueba gratis), en la app entera', () => {
  // En el celular van ADENTRO de la barra: pegados por su cuenta, la barra de la
  // prueba se montaba sobre el logo y, después, tapaba el total de Cartera.
  const conAviso = (celular, { demo = false, prueba = false } = {}) => {
    usuario = { tier: 'pro', name: 'Usuario' }; enDemo = demo; enPrueba = prueba
    try { return dibujar(celular, null) } finally { usuario = { tier: 'advisor', name: 'Asesor' }; enDemo = false; enPrueba = false }
  }
  const dentroDeLaBarra = (html, texto) => html.slice(html.indexOf('<header'), html.indexOf('</header>')).includes(texto)
  it('prueba gratis: celular, una vez y en la barra; compu, una vez', () => {
    const cel = conAviso(true, { prueba: true })
    expect(veces(cel, 'Estás probando Rendi')).toBe(1)
    expect(dentroDeLaBarra(cel, 'Estás probando Rendi')).toBe(true)
    expect(veces(conAviso(false, { prueba: true }), 'Estás probando Rendi')).toBe(1)
  })
  it('demo: celular, una vez y en la barra; compu, una vez', () => {
    const cel = conAviso(true, { demo: true })
    expect(veces(cel, 'Modo demo activo.')).toBe(1)
    expect(dentroDeLaBarra(cel, 'Modo demo activo.')).toBe(true)
    expect(veces(conAviso(false, { demo: true }), 'Modo demo activo.')).toBe(1)
  })
})
