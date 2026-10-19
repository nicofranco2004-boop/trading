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
//      A los 3 días vuelve solo, como sugerencia otra vez.
//   3. Lo que sabe el servidor tilda los pasos aunque se mire desde la compu, y
//      los de «tener Rendi a mano» se VAN de la lista apenas se hacen.
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
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36'

let pasosDelServidor
let importo
function servidor() {
  api.get.mockImplementation(async (url) => {
    if (url === '/auth/investor-profile') return {}
    if (url === '/imports') return importo ? [{ id: 1 }] : []
    if (url === '/primeros-pasos') return pasosDelServidor
    if (url === '/push/vapid-public-key') return { public_key: 'BEl62iUYgUivxIkv69yViEuiBIa' }
    throw new Error(`GET inesperado ${url}`)
  })
  api.post.mockResolvedValue({ ok: true })
  api.patch.mockResolvedValue({ ok: true, enabled: true })
}

// Un teléfono o una compu. `conPush` arma lo que un navegador con
// notificaciones trae (service worker + PushManager + Notification).
function dispositivo({ ua, conPush, instalada = false, permiso = 'default' }) {
  const nav = { userAgent: ua, maxTouchPoints: ua === IPHONE ? 5 : 0, language: 'es-AR' }
  if (conPush) {
    const sub = { endpoint: 'https://push.example/abc', toJSON: () => ({ endpoint: 'https://push.example/abc', keys: { p256dh: 'p', auth: 'a' } }) }
    const reg = { pushManager: { getSubscription: vi.fn(async () => null), subscribe: vi.fn(async () => sub) } }
    nav.serviceWorker = { getRegistration: vi.fn(async () => undefined), register: vi.fn(async () => reg), ready: Promise.resolve(reg) }
  }
  vi.stubGlobal('navigator', nav)
  const { local } = instalarNavegadorMinimo()
  // `instalada` = abierta desde el ícono (sin las barras del navegador).
  window.matchMedia = (q) => ({ matches: instalada && /standalone/.test(q), addEventListener() {}, removeEventListener() {} })
  if (conPush) {
    const Notification = { permission: permiso, requestPermission: vi.fn(async () => { Notification.permission = 'granted'; return 'granted' }) }
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
  vi.clearAllMocks()   // las llamadas al servidor no se arrastran de una prueba a otra
  pasosDelServidor = { app_instalada: false, dispositivos_push: 0, alertas: 0, resumen_activo: false }
  importo = false
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
    const guardado = JSON.parse(local.get('rendi_checklist_omitidos'))
    expect(Object.keys(guardado)).toEqual(['instalar'])
    expect(Math.abs(guardado.instalar - Date.now())).toBeLessThan(5000)   // cuándo lo dijo
    await montado.desmontar()
    montado = await montarLista()
    expect(texto(montado.contenedor)).toContain('Agregá Rendi a tu celular · para después')
    await tocar('Retomar')
    t = texto(montado.contenedor)
    expect(t).not.toContain('para después')
    expect(t).toContain('Queda con su ícono en tu inicio')
  })

  it('«Ahora no» dura 3 días: al día siguiente sigue escondido, a los 4 vuelve a su lugar', async () => {
    const DIA = 24 * 60 * 60 * 1000
    let { local } = dispositivo({ ua: IPHONE, conPush: false })
    local.set('rendi_checklist_omitidos', JSON.stringify({ instalar: Date.now() - 1 * DIA, push: Date.now() - 4 * DIA }))
    montado = await montarLista()
    const t = texto(montado.contenedor)
    expect(t).toContain('Agregá Rendi a tu celular · para después')       // 1 día: escondido
    expect(t).not.toContain('Activá las notificaciones · para después')   // 4 días: volvió
    expect(t).toContain('Te avisamos al momento cuando se mueve lo que seguís')
    // Volvió en su lugar (arriba, en «a mano»), no al final.
    expect(t.indexOf('Activá las notificaciones')).toBeLessThan(t.indexOf('Para tener tu cartera bien'))

    // Justo antes de los 3 días, todavía no.
    await montado.desmontar()
    ;({ local } = dispositivo({ ua: IPHONE, conPush: false }))
    local.set('rendi_checklist_omitidos', JSON.stringify({ push: Date.now() - (3 * DIA - 60_000) }))
    montado = await montarLista()
    expect(texto(montado.contenedor)).toContain('Activá las notificaciones · para después')
  })

  it('lo hecho de «tener Rendi a mano» se va de la lista (no queda tachado)', async () => {
    pasosDelServidor = { app_instalada: true, dispositivos_push: 1, alertas: 2, resumen_activo: true }
    dispositivo({ ua: MAC, conPush: false })
    montado = await montarLista()
    const t = texto(montado.contenedor)
    expect(t).toContain('3 de 7 listos')
    expect(t).not.toContain('Agregá Rendi a tu celular')
    expect(t).not.toContain('Activá las notificaciones')
    expect(t).not.toContain('Armá tu primera alerta')
    expect(t).not.toContain('Para tener Rendi a mano')       // el grupo vacío tampoco queda
    expect(t).toContain('Importá tu historial')
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
    importo = true
    montado = await montarLista()
    await tocar('Activar')
    expect(Notification.requestPermission).toHaveBeenCalledTimes(1)    // lo pidió porque la persona tocó
    expect(api.post).toHaveBeenCalledWith('/push/subscribe', expect.objectContaining({ endpoint: 'https://push.example/abc' }))
    let t = texto(montado.contenedor)
    expect(t).toContain('¿Te mandamos también el resumen del mercado?')
    expect(t).toContain('2 de 7 listos')                     // importó + notificaciones
    expect(t).not.toContain('Activá las notificaciones')     // hecho → se fue
    await tocar('Sí, mandámelo')
    expect(api.patch).toHaveBeenCalledWith('/market-brief/prefs', { enabled: true })
    t = texto(montado.contenedor)
    expect(t).not.toContain('¿Te mandamos también')
  })

  it('sin cartera cargada no se ofrece el resumen (no le llegaría: habla de lo que tiene)', async () => {
    dispositivo({ ua: MAC, conPush: true })
    montado = await montarLista()
    await tocar('Activar')
    expect(api.post).toHaveBeenCalledWith('/push/subscribe', expect.anything())
    expect(texto(montado.contenedor)).not.toContain('¿Te mandamos también el resumen')
  })

  it('al montar no pide permiso solo: sólo cuando la persona toca', async () => {
    dispositivo({ ua: MAC, conPush: true })
    montado = await montarLista()
    expect(Notification.requestPermission).not.toHaveBeenCalled()
  })
})

describe('auditoría 2026-10-19: celular ≠ compu', () => {
  it('en la compu el aviso «se puede instalar» del navegador no ofrece instalar (instalaría en la compu)', async () => {
    dispositivo({ ua: MAC, conPush: false })
    const { escucharInstalador } = await import('../../utils/instalarApp')
    escucharInstalador(window)
    window.dispatchEvent(Object.assign(new Event('beforeinstallprompt'), { prompt: vi.fn(), userChoice: Promise.resolve({ outcome: 'accepted' }) }))
    montado = await montarLista()
    const t = texto(montado.contenedor)
    expect(t).toContain('Agregá Rendi a tu celular')
    expect(t).toContain('Ver cómo')
    expect(buscarBoton(montado.contenedor, 'Instalar')).toBe(null)
  })

  it('en Android, el mismo aviso sí da «Instalar» en un toque, y al aceptar el paso se va', async () => {
    dispositivo({ ua: ANDROID, conPush: false })
    const { escucharInstalador } = await import('../../utils/instalarApp')
    escucharInstalador(window)
    window.dispatchEvent(Object.assign(new Event('beforeinstallprompt'), { prompt: vi.fn(async () => {}), userChoice: Promise.resolve({ outcome: 'accepted' }) }))
    montado = await montarLista()
    await tocar('Instalar')
    expect(texto(montado.contenedor)).not.toContain('Agregá Rendi a tu celular')
    // Y el servidor se entera ya: si no, en Chrome y en la compu el paso volvía.
    expect(api.post).toHaveBeenCalledWith('/primeros-pasos/instalada', {})
  })

  it('Rendi instalada en la COMPU no tilda «en tu celular» ni le avisa al servidor', async () => {
    dispositivo({ ua: MAC, conPush: false, instalada: true })
    const { avisarSiEstaInstalada } = await import('../../utils/instalarApp')
    expect(avisarSiEstaInstalada(7, window)).toBe(false)
    montado = await montarLista()
    expect(texto(montado.contenedor)).toContain('Agregá Rendi a tu celular')
    expect(api.post).not.toHaveBeenCalledWith('/primeros-pasos/instalada', expect.anything())
  })

  it('abierta desde el ícono del iPhone: le avisa al servidor UNA vez por persona y teléfono, sin esperar un toque', async () => {
    const { local } = dispositivo({ ua: IPHONE, conPush: false, instalada: true })
    let { avisarSiEstaInstalada } = await import('../../utils/instalarApp')
    expect(avisarSiEstaInstalada(7, window)).toBe(true)
    expect(avisarSiEstaInstalada(7, window)).toBe(false)       // mientras va, no repite
    await enActo(async () => {})
    expect(api.post).toHaveBeenCalledTimes(1)
    expect(api.post).toHaveBeenCalledWith('/primeros-pasos/instalada', {})
    expect(local.get('rendi_instalada_avisada')).toBe('7')
    // Otra apertura (otra carga de la página): ya está avisado, no escribe de nuevo.
    vi.resetModules()
    ;({ avisarSiEstaInstalada } = await import('../../utils/instalarApp'))
    expect(avisarSiEstaInstalada(7, window)).toBe(false)
    // Otra cuenta en el mismo teléfono: sí.
    expect(avisarSiEstaInstalada(8, window)).toBe(true)
    expect(api.post).toHaveBeenCalledTimes(2)
  })

  it('si el aviso de «instalada» falla, no se recuerda: se reintenta la próxima vez', async () => {
    const { local } = dispositivo({ ua: IPHONE, conPush: false, instalada: true })
    api.post.mockRejectedValueOnce(new Error('sin red'))
    const { avisarSiEstaInstalada } = await import('../../utils/instalarApp')
    expect(avisarSiEstaInstalada(7, window)).toBe(true)
    await enActo(async () => {})
    expect(local.get('rendi_instalada_avisada')).toBeUndefined()
    expect(avisarSiEstaInstalada(7, window)).toBe(true)
  })

  it('el aviso de «instalada» no hace releer la cartera', async () => {
    dispositivo({ ua: IPHONE, conPush: false })
    const { escrituraTocaLaCartera } = await vi.importActual('../../utils/api')
    expect(escrituraTocaLaCartera('/primeros-pasos/instalada')).toBe(false)
  })

  it('activó en la compu → en el celular se le siguen sugiriendo (cuenta ESTE teléfono)', async () => {
    pasosDelServidor = { app_instalada: true, dispositivos_push: 1, alertas: 0, resumen_activo: false }
    dispositivo({ ua: ANDROID, conPush: true })
    montado = await montarLista()
    expect(texto(montado.contenedor)).toContain('Activá las notificaciones')
    await montado.desmontar()
    // En la compu, con el mismo servidor, ya está hecho.
    dispositivo({ ua: MAC, conPush: true })
    montado = await montarLista()
    expect(texto(montado.contenedor)).not.toContain('Activá las notificaciones')
  })

  it('doble toque en «Activar» pide el permiso una sola vez', async () => {
    dispositivo({ ua: MAC, conPush: true })
    montado = await montarLista()
    const boton = buscarBoton(montado.contenedor, 'Activar')
    await enActo(async () => { clic(montado.contenedor, boton); clic(montado.contenedor, boton) })
    expect(Notification.requestPermission).toHaveBeenCalledTimes(1)
    expect(api.post.mock.calls.filter(([u]) => u === '/push/subscribe')).toHaveLength(1)
  })

  it('las destrabó en Ajustes y volvió: deja de decir «bloqueadas» sin recargar', async () => {
    dispositivo({ ua: MAC, conPush: true, permiso: 'denied' })
    montado = await montarLista()
    await tocar('Activar')
    expect(texto(montado.contenedor)).toContain('Las notificaciones están bloqueadas')
    Notification.permission = 'default'
    await enActo(async () => { window.dispatchEvent(new Event('focus')) })
    expect(texto(montado.contenedor)).not.toContain('Las notificaciones están bloqueadas')
  })

  it('la alerta también se puede dejar para después', async () => {
    dispositivo({ ua: IPHONE, conPush: false })
    montado = await montarLista()
    const boton = buscarBoton(montado.contenedor, 'Ahora no')
    expect(boton).not.toBe(null)
    // Tres «Ahora no»: instalar, notificaciones y alerta.
    let n = 0
    const pila = [montado.contenedor]
    while (pila.length) { const x = pila.shift(); if (x.nodeName === 'BUTTON' && texto(x) === 'Ahora no') n++; pila.push(...(x.childNodes || [])) }
    expect(n).toBe(3)
  })
})

describe('auditoría 2 (2026-10-19)', () => {
  it('si el servidor no recibe la suscripción, se deshace (el teléfono no se cree activado)', async () => {
    dispositivo({ ua: ANDROID, conPush: true })
    api.post.mockImplementation(async (url) => { if (url === '/push/subscribe') throw new Error('sin red'); return { ok: true } })
    montado = await montarLista()
    const reg = await navigator.serviceWorker.register()
    const sub = await reg.pushManager.subscribe()
    sub.unsubscribe = vi.fn(async () => true)
    reg.pushManager.subscribe.mockResolvedValue(sub)
    await tocar('Activar')
    expect(sub.unsubscribe).toHaveBeenCalledTimes(1)
    expect(texto(montado.contenedor)).toContain('Activá las notificaciones')   // sigue pendiente
  })

  it('iPhone en Safari con Rendi ya en el inicio y notificaciones activas: no se las vuelve a pedir', async () => {
    pasosDelServidor = { app_instalada: true, dispositivos_push: 1, alertas: 0, resumen_activo: false }
    dispositivo({ ua: IPHONE, conPush: false })
    montado = await montarLista()
    expect(texto(montado.contenedor)).not.toContain('Activá las notificaciones')
  })

  it('iPhone en Safari con Rendi ya en el inicio pero sin notificaciones: le dice que la abra desde el ícono', async () => {
    pasosDelServidor = { app_instalada: true, dispositivos_push: 0, alertas: 0, resumen_activo: false }
    dispositivo({ ua: IPHONE, conPush: false })
    montado = await montarLista()
    await tocar('Activar')
    const t = texto(montado.contenedor)
    expect(t).toContain('Abrí Rendi desde el ícono de tu inicio')
    expect(t).not.toContain('Primero, agregá Rendi a tu inicio')
    expect(buscarBoton(montado.contenedor, 'Ver cómo agregarla')).toBe(null)
  })

  it('la cartera completa se resume en una línea, sin las 4 filas tachadas', async () => {
    api.get.mockImplementation(async (url) => {
      if (url === '/auth/investor-profile') return { horizonte: 'largo' }
      if (url === '/imports') return [{ id: 1 }]
      if (url === '/primeros-pasos') return pasosDelServidor
      throw new Error(url)
    })
    const { local } = dispositivo({ ua: IPHONE, conPush: false })
    local.set('rendi_positions_discovered', '1')
    local.set('rendi_ai_discovered', '1')
    montado = await montarLista()
    const t = texto(montado.contenedor)
    expect(t).toContain('Para tener tu cartera bien: 4 de 4 listos')
    expect(t).not.toContain('Importá tu historial')
    expect(t).toContain('Agregá Rendi a tu celular')
  })

  it('con todo hecho y la oferta del resumen abierta, no dice «faltan 0»', async () => {
    pasosDelServidor = { app_instalada: true, dispositivos_push: 0, alertas: 1, resumen_activo: false }
    api.get.mockImplementation(async (url) => {
      if (url === '/auth/investor-profile') return { horizonte: 'largo' }
      if (url === '/imports') return [{ id: 1 }]
      if (url === '/primeros-pasos') return pasosDelServidor
      if (url === '/push/vapid-public-key') return { public_key: 'BEl62iUYgUivxIkv69yViEuiBIa' }
      throw new Error(url)
    })
    const { local } = dispositivo({ ua: MAC, conPush: true })
    local.set('rendi_positions_discovered', '1')
    local.set('rendi_ai_discovered', '1')
    montado = await montarLista()
    await tocar('Activar')
    const t = texto(montado.contenedor)
    expect(t).toContain('¿Te mandamos también el resumen del mercado?')
    expect(t).toContain('Todo listo.')
    expect(t).not.toContain('faltan 0')
  })
})
