// Configuración → WhatsApp, montado de verdad (testing/navegadorMinimo) con el
// servidor simulado en la frontera (utils/api): lo que ve la persona en cada
// estado que devuelve /api/whatsapp/estado, y qué le pide al servidor al tocar.
//
//   encendido=false → «todavía no está disponible»
//   permitido=false → lo manda a /planes
//   vinculado=true  → el número tapado y «Desconectar»
//   codigo          → el código, el link que abre WhatsApp y «Esperando…»
//
// Las pruebas corren en node, sin navegador: lo que se verifica es el texto y
// los pedidos, no los píxeles.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic, enActo } from '../testing/navegadorMinimo'

let estado = {}
const pedidos = []
vi.mock('../utils/api', () => ({
  getClientContext: () => null,
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
  api: {
    get: vi.fn((ruta) => { pedidos.push(['get', ruta]); return Promise.resolve(estado) }),
    post: vi.fn((ruta) => { pedidos.push(['post', ruta]); return Promise.resolve(estado) }),
    delete: vi.fn((ruta) => { pedidos.push(['delete', ruta]); return Promise.resolve(estado) }),
  },
}))
const avisos = []
vi.mock('../components/Toast', () => ({ useToast: () => ({ push: (t) => avisos.push(t) }) }))
vi.mock('../utils/track', () => ({ track: vi.fn() }))
vi.mock('../utils/confirmar', () => ({ confirmar: () => Promise.resolve(true) }))
// Lo demás que importa Config.jsx y que acá no se usa.
vi.mock('./Planes', () => ({ default: () => null }))
vi.mock('../components/import/ImportWizard', () => ({ default: () => null }))
vi.mock('../components/InvestorProfileForm', () => ({ default: () => null }))
vi.mock('../components/CurrencyRail', () => ({ default: () => null }))
vi.mock('../components/PageHeader', () => ({ default: () => null }))
vi.mock('../components/plan/TrialCta', () => ({ default: () => null, trialProStageLabel: () => '' }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: {}, logout: () => {} }) }))
vi.mock('../contexts/CurrencyContext', () => ({ useCurrency: () => ({ costBasis: 'purchase', setCostBasis: () => {} }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientId: null }) }))
vi.mock('../hooks/usePlanFeatures', () => ({ usePlanFeatures: () => ({ features: {}, loading: false }) }))

let WhatsAppPanel
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ WhatsAppPanel } = await import('./Config'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar(); montado = null
  pedidos.length = 0; avisos.length = 0
})

async function panel(e) {
  estado = e
  const el = () => h(MemoryRouter, null, h(WhatsAppPanel))
  montado = await montar(el())
  await montado.redibujar(el())
  return texto(montado.contenedor)
}

const BASE = { encendido: true, permitido: true, vinculado: false, telefono: null, codigo: null,
  texto_codigo: null, link: null, vence_min: 15 }

describe('Configuración → WhatsApp', () => {
  it('apagado: «todavía no está disponible», sin botón', async () => {
    const t = await panel({ ...BASE, encendido: false })
    expect(t).toContain('Todavía no está disponible')
    expect(buscarBoton(montado.contenedor, 'Conectar')).toBeNull()
  })

  it('sin plan Pro: lo manda a los planes', async () => {
    const t = await panel({ ...BASE, permitido: false })
    expect(t).toContain('plan Pro')
    expect(t).toContain('Ver planes')
    expect(buscarBoton(montado.contenedor, 'Conectar')).toBeNull()
  })

  it('«Conectar» pide el código y la pantalla lo muestra con el link que abre WhatsApp', async () => {
    const t0 = await panel(BASE)
    expect(t0).toContain('política de privacidad')
    const boton = buscarBoton(montado.contenedor, 'Conectar mi WhatsApp')
    expect(boton).not.toBeNull()
    estado = { ...BASE, codigo: 'ABC234', texto_codigo: 'RENDI ABC234',
      link: 'https://wa.me/5491100000000?text=RENDI%20ABC234' }
    await enActo(async () => clic(montado.contenedor, boton))
    expect(pedidos).toContainEqual(['post', '/whatsapp/codigo'])
    const t = texto(montado.contenedor)
    expect(t).toContain('RENDI ABC234')
    expect(t).toContain('Dura 15 minutos')
    expect(t).toContain('Abrir WhatsApp con el código')
    expect(t).toContain('Esperando tu mensaje')
  })

  it('vinculado: el número tapado, y «Desconectar» borra el vínculo', async () => {
    const t = await panel({ ...BASE, vinculado: true, telefono: '•••• 0001' })
    expect(t).toContain('Conectado al número •••• 0001')
    expect(t).toContain('mismo cupo semanal')
    const boton = buscarBoton(montado.contenedor, 'Desconectar')
    estado = BASE
    await enActo(async () => clic(montado.contenedor, boton))
    expect(pedidos).toContainEqual(['delete', '/whatsapp/vinculo'])
    expect(avisos).toContain('WhatsApp desconectado')
    expect(buscarBoton(montado.contenedor, 'Conectar mi WhatsApp')).not.toBeNull()
  })
})
