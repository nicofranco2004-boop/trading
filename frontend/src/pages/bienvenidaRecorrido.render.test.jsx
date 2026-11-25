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
const updateUser = vi.fn((cambio) => { auth.user = { ...auth.user, ...cambio } })
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ ...auth, refreshUser, updateUser, logout: () => {} }),
}))
vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => false, MOBILE_BREAKPOINT_PX: 768 }))
vi.mock('../components/ai/MervallE', () => ({ default: ({ estado }) => h('span', { 'data-mervalle': estado }) }))
vi.mock('../components/PageMeta', () => ({ default: () => null }))
// El formulario del perfil: un botón que contesta una pregunta (como el real,
// que avisa cuántas hay respondidas con `onCambio`).
vi.mock('../components/InvestorProfileForm', () => ({
  default: ({ onCambio }) => h('div', { 'data-perfil': '' },
    h('button', { type: 'button', onClick: () => onCambio?.(1) }, 'perfil-responder')),
}))
vi.mock('../components/InstalarAppModal', () => ({ default: ({ open }) => (open ? h('div', { 'data-instalar': '' }) : null) }))
const eventos = []
vi.mock('../utils/track', async (o) => ({ ...(await o()), track: (ev) => { eventos.push(ev) } }))
// El importador: una marca con la plataforma que le pasan y tres botones: uno
// que confirma (como el real al importar), uno que conecta Wallbit (como
// WallbitConnect al conectarse) y otro que cierra.
vi.mock('../components/import/ImportWizard', async (o) => ({
  ...(await o()),
  default: ({ plataformaInicial, onConfirmed, onWallbitConnected, onClose }) => h('div', { 'data-wizard': String(plataformaInicial) },
    h('button', { type: 'button', onClick: () => onConfirmed?.({ imported: 3 }) }, 'wizard-confirmar'),
    h('button', { type: 'button', onClick: () => onWallbitConnected?.() }, 'wizard-wallbit'),
    h('button', { type: 'button', onClick: () => onClose?.() }, 'wizard-cerrar')),
}))

let RR, Onboarding, pasoQueVa, brokersDeLaBienvenida, urlDe, local, sesion, navegadorDeNode, refreshPlanFeatures
beforeAll(async () => {
  ;({ local, sesion } = instalarNavegadorMinimo())
  navegadorDeNode = globalThis.navigator
  RR = await import('react-router-dom')
  ;({ refreshPlanFeatures } = await import('../hooks/usePlanFeatures'))
  ;({ default: Onboarding, pasoQueVa, brokersDeLaBienvenida, urlDe } = await import('./Onboarding'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  eventos.length = 0
  refreshUser.mockReset()
  refreshUser.mockImplementation(async () => auth.user)
  updateUser.mockClear()
  if (enfocados) { enfocados.mockRestore(); enfocados = null }
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
function Control() {
  const l = RR.useLocation()
  donde.ahora = l.pathname
  donde.busqueda = l.search
  donde.navegar = RR.useNavigate()
  return null
}
// El «atrás» del celular (o deslizar para volver en el iPhone).
async function atras() {
  await enActo(async () => { donde.navegar(-1) })
  await vueltas()
}
// A qué se le dio el foco (el navegador mínimo no lo mueve: se anota).
let enfocados = null
function espiarFoco() {
  const proto = Object.getPrototypeOf(document.createElement('div'))
  const lista = []
  enfocados = vi.spyOn(proto, 'focus').mockImplementation(function () { lista.push(this) })
  return lista
}

async function vueltas(n = 6) {
  for (let i = 0; i < n; i++) await enActo(async () => { await new Promise(r => setTimeout(r, 0)) })
}
async function abrir({ user = { name: 'Ana Pérez', email: 'ana@prueba.test', falta_cargar_historial: true }, trial = PRUEBA, ruta = '/onboarding', cartera = CARTERA } = {}) {
  auth.user = user
  respuestas = { '/plan/features': { tier: 'pro', trial }, '/imports/parsers/grouped': GRUPOS, ...cartera }
  // El plan se guarda en memoria entre pantallas (como en la app, que lo vuelve
  // a pedir al entrar): cada prueba entra con el suyo.
  refreshPlanFeatures()
  montado = await montar(h(RR.MemoryRouter, { initialEntries: [ruta] },
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
    // Al cerrarse le pregunta al servidor si ya cargó (por si fue por otro
    // camino); como dice que no, se queda.
    expect(refreshUser).toHaveBeenCalledTimes(1)
    expect(eventos).not.toContain('bienvenida_historial_cargado')
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

  it('«Listo» con al menos una respuesta cuenta como perfil hecho', async () => {
    await hastaElPerfil()
    await tocar('perfil-responder')
    await tocar('Listo')
    expect(eventos).toContain('bienvenida_perfil_hecho')
    expect(eventos).not.toContain('bienvenida_perfil_despues')
    expect(donde.ahora).toBe('/')
  })

  it('«Listo» sin ninguna respuesta NO es un perfil hecho: cuenta como «más tarde»', async () => {
    await hastaElPerfil()
    await tocar('Listo')
    expect(eventos).not.toContain('bienvenida_perfil_hecho')
    expect(eventos).toContain('bienvenida_perfil_despues')
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

// ── Los arreglos de la revisión (25/11) ──────────────────────────────────────

async function hastaLaCartera(opciones = {}) {
  await abrir(opciones)
  await tocar('Empecemos')
  await tocar('Cocos Capital')
  await tocar('Subir el archivo')
  await tocar('wizard-confirmar')
  await tocar('wizard-cerrar')
  await vueltas(10)
}
const enlaces = () => {
  const out = []
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'A' && n.atributos?.href) out.push(n.atributos.href)
    pila.push(...(n.childNodes || []))
  }
  return out
}

describe('las piezas puras del recorrido', () => {
  it('la dirección de cada paso («hola» es la bienvenida pelada)', () => {
    expect(urlDe('hola')).toBe('/onboarding')
    expect(urlDe('broker')).toBe('/onboarding?paso=broker')
    expect(urlDe('historial', { subiendo: true })).toBe('/onboarding?paso=historial&subiendo=1')
  })
  it('pasoQueVa corrige lo que la dirección pide y no tiene sentido', () => {
    expect(pasoQueVa(null)).toBe('hola')
    expect(pasoQueVa('cualquiera')).toBe('hola')
    expect(pasoQueVa('broker')).toBe('broker')
    // De después de cargar, sin haber cargado → a elegir el broker.
    expect(pasoQueVa('perfil', { yaCargo: false })).toBe('broker')
    expect(pasoQueVa('cartera', { yaCargo: false })).toBe('broker')
    // El historial necesita saber de qué broker (si recargó, se perdió).
    expect(pasoQueVa('historial', { conBroker: false })).toBe('broker')
    expect(pasoQueVa('historial', { conBroker: true })).toBe('historial')
    // Ya cargado, no se vuelve a pedir el archivo… salvo que el importador
    // siga abierto (está mirando lo que importó).
    expect(pasoQueVa('historial', { yaCargo: true, conBroker: true })).toBe('cartera')
    expect(pasoQueVa('historial', { yaCargo: true, conBroker: true, subiendo: true })).toBe('historial')
    expect(pasoQueVa('hola', { yaCargo: true })).toBe('cartera')
    expect(pasoQueVa('perfil', { yaCargo: true })).toBe('perfil')
    // El paso del celular sólo donde va.
    expect(pasoQueVa('celular', { yaCargo: true, conPasoCelular: false })).toBe('perfil')
    expect(pasoQueVa('celular', { yaCargo: true, conPasoCelular: true })).toBe('celular')
  })
  it('la grilla: los argentinos más usados primero, Wallbit en su lugar y lo desconocido al final, en el orden en que vino', () => {
    const servidor = ['generic', 'binance', 'schwab', 'nuevo_b', 'balanz_internacional', 'inviu', 'ieb', 'ppi', 'bullmarket', 'iol', 'nuevo_a', 'balanz', 'cocos']
      .map(id => ({ platform: id, platform_label: id, exports: [{ id, supported: true }] }))
    expect(brokersDeLaBienvenida(servidor).map(g => g.platform)).toEqual([
      'cocos', 'balanz', 'iol', 'bullmarket', 'ppi', 'ieb', 'inviu', 'wallbit', 'balanz_internacional', 'schwab', 'binance',
      'nuevo_b', 'nuevo_a',
    ])
  })
  it('sin la lista del servidor, Wallbit igual está (no depende de ella)', () => {
    expect(brokersDeLaBienvenida([]).map(g => g.platform)).toEqual(['wallbit'])
    expect(brokersDeLaBienvenida(undefined).map(g => g.platform)).toEqual(['wallbit'])
  })
})

describe('Wallbit: se conecta en vez de subir un archivo', () => {
  it('tiene tarjeta propia; conectar cuenta como cargar y, al cerrar, aparece «tu cartera»', async () => {
    await abrir()
    await tocar('Empecemos')
    expect(buscarBoton(montado.contenedor, 'Wallbit')).toBeTruthy()
    await tocar('Wallbit')
    expect(todo()).toContain('¡Wallbit, buenísimo!')
    // No hay archivo: ni el aviso de bajarlo desde la compu ni «Subir el archivo».
    expect(buscarBoton(montado.contenedor, 'Subir el archivo')).toBeNull()
    await tocar('Conectar Wallbit')
    expect(atributo('data-wizard')).toBe('wallbit')
    await tocar('wizard-wallbit')
    expect(eventos).toContain('bienvenida_historial_cargado')
    expect(refreshUser).toHaveBeenCalled()
    await tocar('wizard-cerrar')
    await vueltas(10)
    expect(todo()).toContain('Tu cartera hoy')
  })

  it('si cargó por un camino que la página no escucha, al cerrar el importador le pregunta al servidor y sigue igual', async () => {
    await abrir()
    await tocar('Empecemos')
    await tocar('Otro / mi broker no está')
    await tocar('Subir el archivo')
    // Conectó Wallbit desde la tarjeta de integración del Paso 0 (o lo que
    // exista mañana): la página no se enteró, pero el servidor sí.
    refreshUser.mockImplementationOnce(async () => ({ ...auth.user, falta_cargar_historial: false }))
    await tocar('wizard-cerrar')
    await vueltas(10)
    expect(refreshUser).toHaveBeenCalledTimes(1)
    expect(todo()).toContain('Tu cartera hoy')
    expect(eventos).toContain('bienvenida_historial_cargado')
  })
})

describe('el «atrás» del celular', () => {
  it('cada paso va en la dirección y «atrás» vuelve al anterior, no al «¡Hola!»', async () => {
    await abrir()
    expect(donde.busqueda).toBe('')
    await tocar('Empecemos')
    expect(donde.busqueda).toBe('?paso=broker')
    await tocar('Cocos Capital')
    expect(donde.busqueda).toBe('?paso=historial')
    await atras()
    expect(donde.busqueda).toBe('?paso=broker')
    expect(todo()).toContain('¿Con qué broker invertís?')
    expect(todo()).not.toContain('Soy Mervall-E')
    await atras()
    expect(donde.busqueda).toBe('')
    expect(todo()).toContain('Soy Mervall-E')
  })

  it('con el importador abierto, «atrás» lo cierra y se queda en el historial', async () => {
    await abrir()
    await tocar('Empecemos')
    await tocar('Cocos Capital')
    await tocar('Subir el archivo')
    expect(donde.busqueda).toBe('?paso=historial&subiendo=1')
    await atras()
    expect(atributo('data-wizard')).toBeNull()
    expect(donde.ahora).toBe('/onboarding')
    expect(donde.busqueda).toBe('?paso=historial')
    expect(todo()).toContain('Cuando tengas el archivo, acá estoy.')
  })

  it('cerrar el importador con su botón saca su entrada: el próximo «atrás» va a la grilla', async () => {
    await abrir()
    await tocar('Empecemos')
    await tocar('Cocos Capital')
    await tocar('Subir el archivo')
    await tocar('wizard-cerrar')
    expect(donde.busqueda).toBe('?paso=historial')
    await atras()
    expect(donde.busqueda).toBe('?paso=broker')
  })

  it('un paso de después, abierto a mano sin haber cargado, va a «broker»', async () => {
    await abrir({ ruta: '/onboarding?paso=perfil' })
    expect(todo()).toContain('¿Con qué broker invertís?')
    expect(atributo('data-perfil')).toBeNull()
    expect(donde.busqueda).toBe('?paso=broker')
  })

  it('el historial sin broker elegido (recargó la página) va a «broker»; un paso que no existe, al «¡Hola!»', async () => {
    await abrir({ ruta: '/onboarding?paso=historial&subiendo=1' })
    expect(atributo('data-wizard')).toBeNull()
    expect(donde.busqueda).toBe('?paso=broker')
    await montado.desmontar(); montado = null
    await abrir({ ruta: '/onboarding?paso=cualquiera' })
    expect(todo()).toContain('Soy Mervall-E')
    expect(donde.busqueda).toBe('')
  })

  it('ya cargado: el cierre quedó hecho al cargar, y «atrás» desde «tu cartera» no vuelve a pedir el archivo', async () => {
    await hastaLaCartera()
    expect(donde.busqueda).toBe('?paso=cartera')
    // El cierre (sin tutorial de novedades en esta visita; el próximo import no
    // va a la primera lectura) se hizo al cargar, no recién al final.
    expect(eventos).not.toContain('bienvenida_terminada')
    expect(sesion.get('rendi_bienvenida_recien')).toBe('1')
    expect(local.get('rendi_first_import_done')).toBe('1')
    await atras()
    expect(todo()).toContain('Tu cartera hoy')
    expect(buscarBoton(montado.contenedor, 'Subir el archivo')).toBeNull()
    expect(donde.busqueda).toBe('?paso=cartera')
  })
})

describe('si el pedido del usuario falla justo después de confirmar (corte de señal)', () => {
  it('lo marca como cargado acá, así la puerta no lo devuelve al «¡Hola!»', async () => {
    await abrir()
    await tocar('Empecemos')
    await tocar('Cocos Capital')
    await tocar('Subir el archivo')
    refreshUser.mockRejectedValueOnce(new Error('sin señal'))
    await tocar('wizard-confirmar')
    expect(updateUser).toHaveBeenCalledWith({ falta_cargar_historial: false })
    await tocar('wizard-cerrar')
    await vueltas(10)
    expect(todo()).toContain('Tu cartera hoy')
  })
})

describe('el foco del teclado y del lector de pantalla', () => {
  it('al cambiar de paso va al título del paso nuevo; al cerrarse el importador, al del historial', async () => {
    const foco = espiarFoco()
    const ultimo = () => foco[foco.length - 1]
    await abrir()
    await tocar('Empecemos')
    expect(ultimo()?.nodeName).toBe('H1')
    expect(ultimo().atributos.tabindex).toBe('-1')
    expect(texto(ultimo())).toBe('Configurá tu Rendi: Tu broker')
    await tocar('Cocos Capital')
    expect(texto(ultimo())).toBe('Configurá tu Rendi: Tu historial')
    await tocar('Subir el archivo')
    const antes = foco.length
    await tocar('wizard-cerrar')
    expect(foco.length).toBeGreaterThan(antes)
    expect(texto(ultimo())).toBe('Configurá tu Rendi: Tu historial')
  })
})

describe('el pie', () => {
  it('además de WhatsApp y «Cerrar sesión», los links a Planes, Privacidad y Términos', async () => {
    await abrir()
    expect(enlaces()).toEqual(expect.arrayContaining(['/planes', '/privacidad', '/terminos']))
    expect(buscarBoton(montado.contenedor, 'Cerrar sesión')).toBeTruthy()
  })
})

describe('«tu cartera vale…»: lo que dice y cuándo se cuenta como vista', () => {
  it('una cuenta con su pata en dólares es UN broker («Cocos · USD» no se cuenta aparte)', async () => {
    await hastaLaCartera({
      cartera: {
        '/positions': [{ id: 1, asset: 'GGAL', quantity: 100, invested: 500000, broker: 'Cocos', currency: 'ARS', is_cash: false, asset_type: 'STOCK' }],
        '/brokers': [{ id: 1, name: 'Cocos', currency: 'ARS' }, { id: 2, name: 'Cocos · USD', currency: 'USDT', parent_broker_id: 1 }],
        '/dolar': null,
        '/prices': { 'GGAL.BA': 6000 },
      },
    })
    expect(todo()).toContain('Tu cartera hoy')
    expect(todo()).toContain('1 posición en 1 broker')
  })

  it('mientras dice «estoy sumando todo…» todavía no cuenta como vista', async () => {
    // Los precios no llegan nunca: se queda sumando.
    const { '/prices': _sinPrecios, ...sumando } = CARTERA
    await hastaLaCartera({ cartera: sumando })
    expect(todo()).toContain('Dame un segundo, estoy sumando todo…')
    expect(eventos).not.toContain('bienvenida_cartera_vista')
  })

  it('sin un valor que mostrar, no cuenta como vista', async () => {
    await hastaLaCartera({ cartera: { ...CARTERA, '/positions': [] } })
    expect(todo()).toContain('Todavía no tengo los precios')
    expect(eventos).not.toContain('bienvenida_cartera_vista')
  })
})
