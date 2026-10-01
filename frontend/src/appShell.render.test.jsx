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
      // `enPrueba`: true = día 12 de la etapa Pro; o la prueba entera que se quiera.
      return enPrueba ? { ...r, trial: enPrueba === true ? { active: true, stage: 'pro', days_left: 12 } : enPrueba } : r
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
    // En el celular, el renglón corto ("Prueba Pro · te quedan N días").
    const cel = conAviso(true, { prueba: true })
    expect(veces(cel, 'Prueba Pro')).toBe(1)
    expect(dentroDeLaBarra(cel, 'Prueba Pro')).toBe(true)
    expect(veces(conAviso(false, { prueba: true }), 'Estás probando Rendi')).toBe(1)
  })
  it('demo: celular, una vez y en la barra; compu, una vez', () => {
    const cel = conAviso(true, { demo: true })
    expect(veces(cel, 'Modo demo activo.')).toBe(1)
    expect(dentroDeLaBarra(cel, 'Modo demo activo.')).toBe(true)
    expect(veces(conAviso(false, { demo: true }), 'Modo demo activo.')).toBe(1)
  })
})

describe('qué VERSIÓN de cada aviso pide cada armado', () => {
  // App.jsx decide, pasando `enLaBarra`. Contar cuántos hay no alcanza: con la
  // versión equivocada, en el celular vuelve la franja larga (a 360-375 px no
  // deja ver el nombre del cliente) y en la compu los avisos dejan de quedar
  // fijos arriba (al bajar se van el contador de la prueba y "Crear cuenta").
  it('celular: la franja es la corta de la barra ("Cuenta de" + "Volver")', () => {
    const html = dibujar(true, { id: 7, label: 'Ana' })
    const barra = html.slice(html.indexOf('<header'), html.indexOf('</header>'))
    expect(barra).toMatch(/Cuenta de\s*<span[^>]*>Ana<\/span>/)
    expect(barra).not.toContain('Estás viendo la cuenta de')
  })
  it('compu: la prueba gratis y la demo quedan fijas arriba del contenido', () => {
    // La etiqueta que envuelve la fila de cada aviso.
    const contenedorDe = (h, texto) => {
      const fila = h.lastIndexOf('<div class="flex items-center justify-between gap-3 px-4 py-2 max-w-7xl', h.indexOf(texto))
      return h.slice(Math.max(0, fila - 400), fila)
    }
    for (const [demo, prueba, texto] of [[true, false, 'Modo demo activo.'], [false, true, 'Estás probando Rendi']]) {
      usuario = { tier: 'pro', name: 'U' }; enDemo = demo; enPrueba = prueba
      try {
        expect(contenedorDe(dibujar(false, null), texto), texto).toMatch(/<div class="sticky top-0 z-40[^"]*"[^>]*>$/)
      } finally { usuario = { tier: 'advisor', name: 'Asesor' }; enDemo = false; enPrueba = false }
    }
  })
  it('celular: la prueba gratis en UN renglón, con los días a la vista (primero el dato)', () => {
    usuario = { tier: 'pro', name: 'U' }; enPrueba = true
    try {
      const html = dibujar(true, null)
      const barra = html.slice(html.indexOf('<header'), html.indexOf('</header>'))
      expect(barra).toMatch(/<p class="[^"]*\btruncate\b[^"]*"><span[^>]*>Prueba Pro<\/span><span[^>]*> · te quedan 12 días<\/span>/)
    } finally { usuario = { tier: 'advisor', name: 'Asesor' }; enPrueba = false }
  })
})

describe('la barra de la prueba, cerca del final', () => {
  it('compu: el aviso ya dice los días, no se repiten al lado', () => {
    usuario = { tier: 'plus', name: 'U', requires_plan: true }
    enPrueba = { active: true, stage: 'plus', days_left: 2 }
    try {
      const html = dibujar(false, null)
      expect(veces(html, 'quedan 2 días')).toBe(1)
      expect(html).toContain('Te quedan 2 días: elegí un plan')
    } finally { usuario = { tier: 'advisor', name: 'Asesor' }; enPrueba = false }
  })
  it('celular: el último día no dice "0 días" y el aviso va primero', () => {
    usuario = { tier: 'plus', name: 'U', requires_plan: true }
    enPrueba = { active: true, stage: 'plus', days_left: 0 }
    try {
      const html = dibujar(true, null)
      const barra = html.slice(html.indexOf('<header'), html.indexOf('</header>'))
      expect(barra).toContain('Te queda menos de un día: elegí un plan')
      expect(html).not.toMatch(/0 días/)
    } finally { usuario = { tier: 'advisor', name: 'Asesor' }; enPrueba = false }
  })
})
