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
const usuario = { tier: 'advisor', name: 'Asesor' }
vi.mock('./contexts/AuthContext', () => ({
  AuthProvider: ({ children }) => children,
  useAuth: () => ({ user: usuario, logout: () => {}, loading: false }),
}))
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
