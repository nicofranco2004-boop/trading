import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo } from '../testing/navegadorMinimo'

// El buscador ⌘K mientras a la cuenta le falta cargar su historial (la
// bienvenida obligatoria): NO se abre. Las pantallas que la puerta deja a la
// vista (/planes, lo legal) se ven con el armazón entero, y el buscador
// ofrecería ir a pantallas a las que todavía no puede entrar. Se monta el
// BuscadorRapido DE VERDAD y se aprieta el atajo como en el teclado: si alguien
// borra la condición de `faltaConfigurar` en el componente, esto se pone rojo.
// (El caso de control —sin la marca, sí abre— prueba que la prueba ve abrirse.)

let usuario = null
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: usuario, isDemo: false }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))
vi.mock('../contexts/CurrencyContext', () => ({ useCurrency: () => ({ currency: 'USD', setCurrency: () => {} }) }))
vi.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ dark: true, toggle: () => {} }) }))
vi.mock('../contexts/PrivacyContext', () => ({ usePrivacy: () => ({ hidden: false, toggle: () => {} }) }))
vi.mock('../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('../hooks/usePlanFeatures', () => ({ usePlanFeatures: () => ({ isPro: true, isAdmin: false }) }))
vi.mock('./ai/MervallE', () => ({ default: () => null }))
vi.mock('../utils/api', async (o) => ({ ...(await o()), api: { get: vi.fn(async () => []) } }))

let RR, BuscadorRapido, EVENTO_ABRIR_BUSCADOR, esMac
beforeAll(async () => {
  instalarNavegadorMinimo()
  RR = await import('react-router-dom')
  ;({ default: BuscadorRapido, EVENTO_ABRIR_BUSCADOR } = await import('./BuscadorRapido'))
  ;({ esMac } = await import('../utils/buscadorRapido'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null; usuario = null })

async function abrirEn(ruta, user) {
  usuario = user
  montado = await montar(h(RR.MemoryRouter, { initialEntries: [ruta] }, h(BuscadorRapido)))
}
async function apretarAtajo() {
  const mac = esMac()
  await enActo(async () => {
    window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'k', metaKey: mac, ctrlKey: !mac }))
  })
}
async function tocarBuscarDelMenu() {
  await enActo(async () => { window.dispatchEvent(new Event(EVENTO_ABRIR_BUSCADOR)) })
}
function hayDialogo() {
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.atributos?.role === 'dialog') return true
    pila.push(...(n.childNodes || []))
  }
  return false
}

describe('⌘K y la bienvenida obligatoria', () => {
  it('control: a una cuenta que ya cargó, el atajo le abre el buscador', async () => {
    await abrirEn('/planes', { tier: 'pro', falta_cargar_historial: false })
    expect(hayDialogo()).toBe(false)
    await apretarAtajo()
    expect(hayDialogo()).toBe(true)
  })

  it('a la cuenta que todavía no cargó su historial, en /planes, el atajo no abre nada', async () => {
    await abrirEn('/planes', { tier: 'pro', falta_cargar_historial: true })
    await apretarAtajo()
    expect(hayDialogo()).toBe(false)
  })

  it('tampoco el botón «Buscar» del menú', async () => {
    await abrirEn('/terminos', { tier: 'pro', falta_cargar_historial: true })
    await tocarBuscarDelMenu()
    expect(hayDialogo()).toBe(false)
  })
})
