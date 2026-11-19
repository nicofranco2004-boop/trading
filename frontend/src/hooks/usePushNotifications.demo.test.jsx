// En el demo, «Activar» los avisos al celular dice «creá una cuenta» ANTES de
// pedirle permiso al navegador (19/11/2026).
//
// POR QUÉ. El demo no contestaba la clave de los avisos (GET
// /push/vapid-public-key) y no tiene cuenta donde anotar el celular: el
// visitante tocaba «Activar», el navegador le pedía permiso, lo daba, y
// terminaba en «No pudimos activarlas en este navegador» — con el permiso ya
// dado a rendi.finance para nada.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { usePushNotifications } from './usePushNotifications'
import { MENSAJE_DEMO } from '../utils/notificaciones'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

function montar() {
  let api = null
  function Prueba() { api = usePushNotifications(); return null }
  renderToStaticMarkup(createElement(Prueba))
  return api
}

function navegadorConPush({ demo }) {
  // «Bloquear»: así la activación de afuera del demo termina ahí, sin salir a la red.
  const requestPermission = vi.fn(() => Promise.resolve('denied'))
  const Notification = Object.assign(function Notification() {}, { permission: 'default', requestPermission })
  vi.stubGlobal('Notification', Notification)
  vi.stubGlobal('PushManager', function PushManager() {})
  vi.stubGlobal('window', Object.assign(Object.create(globalThis), {
    Notification, PushManager() {}, addEventListener() {}, removeEventListener() {},
  }))
  vi.stubGlobal('navigator', { userAgent: 'Mozilla/5.0 (Macintosh)', serviceWorker: { getRegistration: vi.fn(), register: vi.fn() } })
  vi.stubGlobal('localStorage', {
    getItem: (k) => (demo && k === 'rendi_demo_mode' ? String(Date.now()) : null), setItem() {}, removeItem() {},
  })
  return { requestPermission }
}

describe('activar los avisos en el demo', () => {
  it('dice «creá una cuenta» y no le pide permiso al navegador', async () => {
    const { requestPermission } = navegadorConPush({ demo: true })
    const push = montar()
    expect(push.supported).toBe(true)
    await expect(push.subscribe()).rejects.toMatchObject({ motivo: 'demo', message: MENSAJE_DEMO })
    expect(requestPermission).not.toHaveBeenCalled()
  })

  it('fuera del demo sí lo pide (la prueba ve el permiso)', async () => {
    const { requestPermission } = navegadorConPush({ demo: false })
    const push = montar()
    await expect(push.subscribe()).rejects.toMatchObject({ motivo: 'bloqueadas' })
    expect(requestPermission).toHaveBeenCalled()
  })
})
