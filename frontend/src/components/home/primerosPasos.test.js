// La lista de primeros pasos con instalar y notificaciones (2026-10-19).
//
// Se monta la lista DE VERDAD (react-dom, sus efectos, el hook real de
// notificaciones) y se toca como una persona: no se llama a funciones sueltas.
// Lo único de mentira es el servidor (api) y el teléfono (navigator/window).
//
// Lo que tiene que pasar:
//   1. En un iPhone con Rendi abierta en Safari, «Activar» NO tira un error:
//      muestra «Primero, agregá Rendi a tu inicio» con el botón al paso a paso.
//   2. «Ahora no» manda el paso al final («para después») y «Retomar» lo trae.
//   3. Lo que sabe el servidor tilda los pasos aunque se mire desde la compu.
//   4. En la compu, «Activar» suscribe de verdad y después ofrece el resumen;
//      «Sí, mandámelo» lo prende en el servidor.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic, enActo } from '../../testing/navegadorMinimo'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../../utils/api', () => ({ api }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn(), useLocation: () => ({ pathname: '/' }) }))

const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
const MAC = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36'

let pasosDelServidor
function servidor() {
  api.get.mockImplementation(async (url) => {
    if (url === '/auth/investor-profile') return {}
    if (url === '/imports') return []
    if (url === '/primeros-pasos') return pasosDelServidor
    if (url === '/push/vapid-public-key') return { public_key: 'BEl62iUYgUivxIkv69yViEuiBIa' }
    throw new Error(`GET inesperado ${url}`)
  })
  api.post.mockResolvedValue({ ok: true })
  api.patch.mockResolvedValue({ ok: true, enabled: true })
}

// Un teléfono o una compu. `conPush` arma lo que un navegador con
// notificaciones trae (service worker + PushManager + Notification).
function dispositivo({ ua, conPush }) {
  const nav = { userAgent: ua, maxTouchPoints: ua === IPHONE ? 5 : 0, language: 'es-AR' }
  if (conPush) {
    const sub = { endpoint: 'https://push.example/abc', toJSON: () => ({ endpoint: 'https://push.example/abc', keys: { p256dh: 'p', auth: 'a' } }) }
    const reg = { pushManager: { getSubscription: vi.fn(async () => null), subscribe: vi.fn(async () => sub) } }
    nav.serviceWorker = { getRegistration: vi.fn(async () => undefined), register: vi.fn(async () => reg), ready: Promise.resolve(reg) }
  }
  vi.stubGlobal('navigator', nav)
  const { local } = instalarNavegadorMinimo()
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
  if (conPush) {
    const Notification = { permission: 'default', requestPermission: vi.fn(async () => { Notification.permission = 'granted'; return 'granted' }) }
    window.PushManager = class {}
    window.Notification = Notification
    vi.stubGlobal('Notification', Notification)
  }
  return { local }
}

async function montarLista() {
  const { default: OnboardingChecklist } = await import('./OnboardingChecklist')
  return montar(h(OnboardingChecklist))
}

let montado
beforeEach(() => {
  vi.resetModules()
  pasosDelServidor = { app_instalada: false, dispositivos_push: 0, alertas: 0, resumen_activo: false }
  servidor()
})
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  vi.unstubAllGlobals()
})

const tocar = (parte) => enActo(() => clic(montado.contenedor, buscarBoton(montado.contenedor, parte)))

describe('primeros pasos: tener Rendi a mano', () => {
  it('arranca por instalar, notificaciones y alerta, y después la cartera', async () => {
    dispositivo({ ua: IPHONE, conPush: false })
    montado = await montarLista()
    const t = texto(montado.contenedor)
    const orden = ['Para tener Rendi a mano', 'Agregá Rendi a tu celular', 'Recomendado',
      'Activá las notificaciones', 'Armá tu primera alerta', 'Para tener tu cartera bien',
      'Importá tu historial', 'Conocé tus posiciones activas', 'Probá Mervall-E AI', 'Quiz de perfil inversor']
    let desde = 0
    for (const parte of orden) {
      const i = t.indexOf(parte, desde)
      expect(i, `«${parte}» falta o está fuera de orden`).toBeGreaterThanOrEqual(0)
      desde = i
    }
    expect(t).toContain('0 de 7 listos')
  })

  it('iPhone en Safari: «Activar» explica que primero hay que agregarla al inicio, con el botón al paso a paso', async () => {
    dispositivo({ ua: IPHONE, conPush: false })
    montado = await montarLista()
    await tocar('Activar')
    const t = texto(montado.contenedor)
    expect(t).toContain('Primero, agregá Rendi a tu inicio')
    expect(t).toContain('Apple sólo deja mandar notificaciones')
    expect(t).not.toMatch(/no soporta|browser|push/i)   // ni el error viejo ni jerga
    expect(api.post).not.toHaveBeenCalled()             // no intentó suscribir
    await tocar('Ver cómo agregarla')
    expect(texto(montado.contenedor)).toContain('Rendi en tu celular')   // el paso a paso
  })

  it('«Ahora no» lo deja para después (también al recargar) y «Retomar» lo trae de vuelta', async () => {
    const { local } = dispositivo({ ua: IPHONE, conPush: false })
    montado = await montarLista()
    // El primer «Ahora no» es el de instalar.
    await tocar('Ahora no')
    let t = texto(montado.contenedor)
    expect(t).toContain('Agregá Rendi a tu celular · para después')
    expect(JSON.parse(local.get('rendi_checklist_omitidos'))).toEqual(['instalar'])
    await montado.desmontar()
    montado = await montarLista()
    expect(texto(montado.contenedor)).toContain('Agregá Rendi a tu celular · para después')
    await tocar('Retomar')
    t = texto(montado.contenedor)
    expect(t).not.toContain('para después')
    expect(t).toContain('Queda con su ícono en tu inicio')
  })

  it('lo que sabe el servidor tilda los pasos, y con todo resuelto la lista no aparece', async () => {
    pasosDelServidor = { app_instalada: true, dispositivos_push: 1, alertas: 2, resumen_activo: true }
    dispositivo({ ua: MAC, conPush: false })
    montado = await montarLista()
    expect(texto(montado.contenedor)).toContain('3 de 7 listos')
    await montado.desmontar()

    // Los cuatro de la cartera hechos (o dejados para después) → nada que mostrar.
    api.get.mockImplementation(async (url) => {
      if (url === '/auth/investor-profile') return { horizonte: 'largo' }
      if (url === '/imports') return [{ id: 1 }]
      if (url === '/primeros-pasos') return pasosDelServidor
      throw new Error(url)
    })
    const { local } = dispositivo({ ua: MAC, conPush: false })
    local.set('rendi_positions_discovered', '1')
    local.set('rendi_ai_discovered', '1')
    montado = await montarLista()
    expect(texto(montado.contenedor)).toBe('')
  })
})

describe('primeros pasos: activar desde la compu', () => {
  it('«Activar» suscribe este dispositivo y ofrece el resumen; «Sí, mandámelo» lo prende', async () => {
    dispositivo({ ua: MAC, conPush: true })
    montado = await montarLista()
    await tocar('Activar')
    expect(Notification.requestPermission).toHaveBeenCalledTimes(1)    // lo pidió porque la persona tocó
    expect(api.post).toHaveBeenCalledWith('/push/subscribe', expect.objectContaining({ endpoint: 'https://push.example/abc' }))
    let t = texto(montado.contenedor)
    expect(t).toContain('¿Te mandamos también el resumen del mercado?')
    expect(t).toContain('1 de 7 listos')
    await tocar('Sí, mandámelo')
    expect(api.patch).toHaveBeenCalledWith('/market-brief/prefs', { enabled: true })
    t = texto(montado.contenedor)
    expect(t).not.toContain('¿Te mandamos también')
  })

  it('al montar no pide permiso solo: sólo cuando la persona toca', async () => {
    dispositivo({ ua: MAC, conPush: true })
    montado = await montarLista()
    expect(Notification.requestPermission).not.toHaveBeenCalled()
  })
})
