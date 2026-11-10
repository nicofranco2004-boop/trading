import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo } from '../testing/navegadorMinimo'

// «Importá tu historial» abre la ventana de carga directo (pedido de Nico,
// 10/11/2026). Antes el botón del Dashboard vacío —y los de Reportes, Sesgos y
// Diagnóstico— dejaban en Configuración, y había que encontrar «Importar CSV»
// adentro de Cuenta. Ahora todos van por `rutaParaImportar` (utils/navegacion)
// a /imports?from=<botón>, y la pantalla de importaciones abre el wizard sola.
// Acá se monta la pantalla REAL con react-router, igual que en la app: llega la
// dirección que arma cada botón y se mira si el wizard queda abierto.

vi.mock('../utils/api', async (original) => ({
  ...(await original()),
  api: { get: vi.fn(async () => []), post: vi.fn(async () => ({})), delete: vi.fn(async () => ({})) },
}))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { tier: 'free' } }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))
vi.mock('../components/import/ImportWizard', () => ({
  default: ({ onClose }) => h('dialog', { 'data-wizard': 'abierto', onClick: onClose }),
}))
vi.mock('../components/import/WallbitConnect', () => ({ default: () => null }))
vi.mock('../components/import/TenenciaUpload', () => ({ default: () => null }))

let RR, Imports, rutaParaImportar
beforeAll(async () => {
  instalarNavegadorMinimo()
  RR = await import('react-router-dom')
  ;({ default: Imports } = await import('./Imports'))
  ;({ rutaParaImportar } = await import('../utils/navegacion'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null })

const mando = {}
function Control() {
  mando.ir = RR.useNavigate()
  mando.donde = RR.useLocation()
  return null
}

const wizardAbierto = () => {
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.atributos?.['data-wizard'] === 'abierto') return true
    pila.push(...(n.childNodes || []))
  }
  return false
}

async function abrir(direccion) {
  montado = await montar(h(RR.MemoryRouter, { initialEntries: [direccion] },
    h(RR.Routes, null, h(RR.Route, { path: '/imports', element: h(Imports) })),
    h(Control)))
}

describe('«Importá tu historial» abre la ventana de carga directo', () => {
  it('el camino que arman los botones es la pantalla de importaciones con su origen', () => {
    expect(rutaParaImportar('dashboard')).toBe('/imports?from=dashboard')
  })

  it.each(['dashboard', 'reportes', 'sesgos', 'diagnostico', 'cartera', 'registrar', 'onboarding', 'checklist'])(
    'llegando desde «%s»: el wizard queda abierto', async (origen) => {
      await abrir(rutaParaImportar(origen))
      expect(wizardAbierto()).toBe(true)
    })

  it('entrando a la pantalla a secas (Ver historial, el buscador): el wizard NO se abre', async () => {
    await abrir('/imports')
    expect(wizardAbierto()).toBe(false)
  })

  it('al abrirse saca el ?from= de la dirección (recargar no lo reabre)', async () => {
    await abrir(rutaParaImportar('dashboard'))
    expect(mando.donde.pathname).toBe('/imports')
    expect(mando.donde.search).toBe('')
  })

  it('ya en la pantalla, con el wizard cerrado: tocar «Importar historial» otra vez lo reabre', async () => {
    await abrir(rutaParaImportar('registrar'))
    // cerrar el wizard (el mock llama a onClose con un clic)
    const { clic } = await import('../testing/navegadorMinimo')
    const pila = [montado.contenedor]; let dialogo = null
    while (pila.length) { const n = pila.shift(); if (n.nodeName === 'DIALOG') { dialogo = n; break } pila.push(...(n.childNodes || [])) }
    await enActo(() => clic(montado.contenedor, dialogo))
    expect(wizardAbierto()).toBe(false)
    await enActo(() => mando.ir(rutaParaImportar('registrar')))
    expect(wizardAbierto()).toBe(true)
  })
})
