import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo, clic, buscarBoton, texto } from '../testing/navegadorMinimo'

// EL RECORRIDO de la bienvenida obligatoria (pages/Onboarding.jsx), montado de
// verdad: los pedidos salen por utils/api (respondidos acá), el plan por
// usePlanFeatures, la cartera por useCarteraRecienCargada. Se reemplazan el
// importador (se prueba aparte, con `plataformaInicial`), Mervall-E (su motor
// necesita un navegador; acá se mira qué cara le piden) y el formulario del
// perfil.

let respuestas = {}
vi.mock('../utils/api', async (o) => ({
  ...(await o()),
  api: {
    get: vi.fn(async (url) => {
      const clave = Object.keys(respuestas).find(k => url.startsWith(k))
      if (!clave) return new Promise(() => {})
      const r = respuestas[clave]
      if (r instanceof Error) throw r
      return typeof r === 'function' ? r(url) : r
    }),
    post: vi.fn(async () => ({})),
  },
}))
const auth = { user: null, isDemo: false, bootstrapped: true }
const refreshUser = vi.fn(async () => auth.user)
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ ...auth, refreshUser, logout: () => {} }),
}))
vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => false, MOBILE_BREAKPOINT_PX: 768 }))
vi.mock('../components/ai/MervallE', () => ({ default: ({ estado }) => h('span', { 'data-mervalle': estado }) }))
vi.mock('../components/PageMeta', () => ({ default: () => null }))
vi.mock('../components/InvestorProfileForm', () => ({ default: () => h('div', { 'data-perfil': '' }) }))
vi.mock('../components/InstalarAppModal', () => ({ default: ({ open }) => (open ? h('div', { 'data-instalar': '' }) : null) }))
const eventos = []
vi.mock('../utils/track', async (o) => ({ ...(await o()), track: (ev) => { eventos.push(ev) } }))
// El importador: una marca con la plataforma que le pasan y dos botones, uno
// que confirma (como el real al importar) y otro que cierra.
vi.mock('../components/import/ImportWizard', async (o) => ({
  ...(await o()),
  default: ({ plataformaInicial, onConfirmed, onClose }) => h('div', { 'data-wizard': String(plataformaInicial) },
    h('button', { type: 'button', onClick: () => onConfirmed?.({ imported: 3 }) }, 'wizard-confirmar'),
    h('button', { type: 'button', onClick: () => onClose?.() }, 'wizard-cerrar')),
}))

let RR, Onboarding, local, sesion, navegadorDeNode, refreshPlanFeatures
beforeAll(async () => {
  ;({ local, sesion } = instalarNavegadorMinimo())
  navegadorDeNode = globalThis.navigator
  RR = await import('react-router-dom')
  ;({ refreshPlanFeatures } = await import('../hooks/usePlanFeatures'))
  ;({ default: Onboarding } = await import('./Onboarding'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  eventos.length = 0
  refreshUser.mockClear()
  local.clear(); sesion.clear()
  Object.assign(auth, { user: null, isDemo: false, bootstrapped: true })
  vi.stubGlobal('navigator', navegadorDeNode)
})

// Días que NO son los del catálogo: si la frase los dice, salen del servidor.
const PRUEBA = { active: true, stage: 'pro', pro_days: 7, plus_days: 13, total_days: 20, days_left: 20 }
const GRUPOS = [
  { platform: 'generic', platform_label: 'Genérico', exports: [{ id: 'rendi_generic', supported: true }] },
  { platform: 'cocos', platform_label: 'Cocos Capital', exports: [{ id: 'cocos', supported: true }] },
  { platform: 'iol', platform_label: 'IOL (InvertirOnline)', exports: [{ id: 'iol', supported: true }] },
]
const CARTERA = {
  '/positions': [{ id: 1, asset: 'AAPL', quantity: 10, invested: 1000, broker: 'Schwab', currency: 'USD', is_cash: false, asset_type: 'STOCK' }],
  '/brokers': [{ id: 1, name: 'Schwab', currency: 'USD' }],
  '/dolar': null,
  '/prices': { AAPL: 200 },
}

const donde = {}
function Control() { donde.ahora = RR.useLocation().pathname; return null }

async function vueltas(n = 6) {
  for (let i = 0; i < n; i++) await enActo(async () => { await new Promise(r => setTimeout(r, 0)) })
}
async function abrir({ user = { name: 'Ana Pérez', email: 'ana@prueba.test', falta_cargar_historial: true }, trial = PRUEBA } = {}) {
  auth.user = user
  respuestas = { '/plan/features': { tier: 'pro', trial }, '/imports/parsers/grouped': GRUPOS, ...CARTERA }
  // El plan se guarda en memoria entre pantallas (como en la app, que lo vuelve
  // a pedir al entrar): cada prueba entra con el suyo.
  refreshPlanFeatures()
  montado = await montar(h(RR.MemoryRouter, { initialEntries: ['/onboarding'] },
    h(RR.Routes, null,
      h(RR.Route, { path: '/onboarding', element: h(Onboarding) }),
      h(RR.Route, { path: '/', element: h('div', { 'data-inicio': '' }) })),
    h(Control)))
  await vueltas()
}
const todo = () => texto(montado.contenedor)
const atributo = (nombre) => {
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.atributos && nombre in n.atributos) return n.atributos[nombre]
    pila.push(...(n.childNodes || []))
  }
  return null
}
async function tocar(parte) {
  const b = buscarBoton(montado.contenedor, parte)
  expect(b, `botón «${parte}»`).toBeTruthy()
  await enActo(() => clic(montado.contenedor, b))
  await vueltas()
}

describe('1 · hola: Mervall-E saluda y cuenta la prueba con los días del servidor', () => {
  it('lee los días de /plan/features (nunca escritos a mano)', async () => {
    await abrir()
    expect(todo()).toContain('¡Hola, Ana! Soy Mervall-E, y te voy a ayudar a armar tu Rendi.')
    expect(todo()).toContain('Arrancás con 7 días de Rendi Pro y después 13 de Plus, gratis y sin tarjeta.')
    expect(todo()).toContain('Para mostrarte tu plata necesito tu historial.')
    expect(eventos).toContain('bienvenida_hola')
    expect(atributo('data-mervalle')).toBe('saludo')
  })
  it('si ya pasaron días, dice cuántos le quedan', async () => {
    await abrir({ trial: { ...PRUEBA, days_left: 12 } })
    expect(todo()).toContain('te quedan 12 días')
  })
  it('sin prueba activa, la frase no va', async () => {
    await abrir({ trial: { active: false, can_start: false } })
    expect(todo()).not.toContain('Rendi Pro')
    expect(todo()).toContain('Para mostrarte tu plata necesito tu historial.')
  })
})

describe('2-3 · broker e historial', () => {
  it('la grilla es la del importador (sin el genérico) + «Otro»; elegir uno abre el asistente con su plataforma', async () => {
    await abrir()
    await tocar('Empecemos')
    expect(todo()).toContain('¿Con qué broker invertís?')
    expect(buscarBoton(montado.contenedor, 'Cocos Capital')).toBeTruthy()
    expect(buscarBoton(montado.contenedor, 'IOL (InvertirOnline)')).toBeTruthy()
    expect(buscarBoton(montado.contenedor, 'Genérico')).toBeNull()
    await tocar('Cocos Capital')
    expect(eventos).toContain('bienvenida_broker_elegido')
    // Mervall-E festeja la elección y nombra el broker corto (el de su guía).
    expect(atributo('data-mervalle')).toBe('contento')
    expect(todo()).toContain('¡Cocos, buenísimo!')
    expect(atributo('data-wizard')).toBeNull()
    await tocar('Subir el archivo')
    expect(eventos).toContain('bienvenida_subir_abierto')
    expect(atributo('data-wizard')).toBe('cocos')
  })

  it('«Otro / mi broker no está» va a la planilla de Rendi', async () => {
    await abrir()
    await tocar('Empecemos')
    await tocar('Otro / mi broker no está')
    expect(todo()).toContain('Usamos la planilla de Rendi')
    await tocar('Subir el archivo')
    expect(atributo('data-wizard')).toBe('personal')
  })

  it('cerrar el asistente sin confirmar: se queda, y Mervall-E espera', async () => {
    await abrir()
    await tocar('Empecemos')
    await tocar('Cocos Capital')
    await tocar('Subir el archivo')
    await tocar('wizard-cerrar')
    expect(atributo('data-wizard')).toBeNull()
    expect(todo()).toContain('Cuando tengas el archivo, acá estoy.')
    expect(atributo('data-mervalle')).toBe('atento')
    expect(todo()).not.toContain('Tu cartera hoy')
    expect(refreshUser).not.toHaveBeenCalled()
  })

  it('«Cambiar de broker» vuelve a la grilla', async () => {
    await abrir()
    await tocar('Empecemos')
    await tocar('Cocos Capital')
    await tocar('Cambiar de broker')
    expect(todo()).toContain('¿Con qué broker invertís?')
  })
})

describe('4 · al confirmar el archivo: «tu cartera vale…»', () => {
  it('confirmar refresca el usuario y, al cerrar el asistente, muestra la cartera con el mismo cálculo', async () => {
    await abrir()
    await tocar('Empecemos')
    await tocar('Cocos Capital')
    await tocar('Subir el archivo')
    await tocar('wizard-confirmar')
    expect(refreshUser).toHaveBeenCalled()
    expect(eventos).toContain('bienvenida_historial_cargado')
    // El servidor ya dice que cargó: la página SIGUE con sus pasos.
    auth.user = { ...auth.user, falta_cargar_historial: false }
    await tocar('wizard-cerrar')
    await vueltas(10)
    expect(donde.ahora).toBe('/onboarding')
    expect(todo()).toContain('¡Listo! Esto es lo que tenés hoy.')
    expect(todo()).toContain('Tu cartera hoy')
    expect(todo()).toContain('1 posición en 1 broker')
    expect(eventos).toContain('bienvenida_cartera_vista')
    expect(atributo('data-mervalle')).toBe('festejo')
  })
})

describe('5-6 · los opcionales y el final', () => {
  async function hastaElPerfil() {
    await abrir()
    await tocar('Empecemos')
    await tocar('Cocos Capital')
    await tocar('Subir el archivo')
    await tocar('wizard-confirmar')
    await tocar('wizard-cerrar')
    await vueltas(10)
    await tocar('Seguir')
    expect(atributo('data-perfil')).not.toBeNull()
  }

  it('en la compu: «Más tarde» en el perfil termina (no hay paso del celular) y entra a Rendi', async () => {
    await hastaElPerfil()
    // El tramo «Últimos detalles» tiene 2 pasos en la compu.
    expect(todo()).toContain('Últimos detalles')
    expect(todo()).toContain('2 de 2')
    await tocar('Más tarde')
    expect(eventos).toContain('bienvenida_perfil_despues')
    expect(eventos).toContain('bienvenida_terminada')
    expect(eventos).not.toContain('bienvenida_celular_despues')
    expect(donde.ahora).toBe('/')
    // El tutorial de novedades espera a la próxima visita, y el próximo import
    // no vuelve a mandar a la primera lectura.
    expect(sesion.get('rendi_bienvenida_recien')).toBe('1')
    expect(local.get('rendi_first_import_done')).toBe('1')
  })

  it('«Listo» en el perfil cuenta como hecho', async () => {
    await hastaElPerfil()
    await tocar('Listo')
    expect(eventos).toContain('bienvenida_perfil_hecho')
    expect(donde.ahora).toBe('/')
  })

  it('en el celular sin la app instalada aparece el último paso, con «Mostrame cómo» y «Más tarde»', async () => {
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', maxTouchPoints: 5 })
    await hastaElPerfil()
    expect(todo()).toContain('2 de 3')
    await tocar('Más tarde')
    expect(todo()).toContain('¿Me ponés en la pantalla de inicio?')
    expect(donde.ahora).toBe('/onboarding')
    await tocar('Mostrame cómo')
    expect(eventos).toContain('bienvenida_celular_hecho')
    expect(atributo('data-instalar')).not.toBeNull()
  })

  it('en el celular, «Más tarde» del último paso termina', async () => {
    vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Linux; Android 14)', maxTouchPoints: 5 })
    await hastaElPerfil()
    await tocar('Más tarde')
    await tocar('Más tarde')
    expect(eventos).toContain('bienvenida_celular_despues')
    expect(donde.ahora).toBe('/')
  })
})

describe('a quién le toca', () => {
  it('a quien no le falta nada, al montar lo manda al inicio', async () => {
    await abrir({ user: { name: 'Bruno', email: 'b@prueba.test', falta_cargar_historial: false } })
    expect(donde.ahora).toBe('/')
  })
  it('antes de que el servidor confirme la sesión no decide (ni manda al inicio ni arranca)', async () => {
    auth.bootstrapped = false
    await abrir({ user: { name: 'Bruno', email: 'b@prueba.test', falta_cargar_historial: false } })
    expect(donde.ahora).toBe('/onboarding')
    expect(todo()).not.toContain('Soy Mervall-E')
  })
})
