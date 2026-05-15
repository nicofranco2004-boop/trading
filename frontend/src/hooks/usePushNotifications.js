// usePushNotifications — gestiona el flow de Web Push end-to-end (Sprint M4).
// ═══════════════════════════════════════════════════════════════════════════
// Estados del permiso del browser:
//   default  → el user no decidió todavía (prompt disponible)
//   granted  → el user aceptó (puede haber sub o no)
//   denied   → el user rechazó (no podemos volver a pedir; tiene que ir a
//              ajustes del browser para revertir)
//
// Estado adicional propio:
//   supported   → el browser tiene SW + PushManager
//   subscribed  → tenemos sub activa en este device
//   loading     → operación en curso
//   error       → último error
//
// API:
//   const {
//     supported, permission, subscribed, loading, error,
//     subscribe, unsubscribe, sendTest,
//   } = usePushNotifications()

import { useCallback, useEffect, useState } from 'react'
import { api } from '../utils/api'

const SW_PATH = '/sw.js'

// Helper: convertir base64url (público VAPID) → Uint8Array que pushManager espera.
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const arr = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i)
  return arr
}

function arrayBufferToBase64Url(buffer) {
  if (!buffer) return ''
  const bytes = new Uint8Array(buffer)
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function subscriptionToPayload(sub) {
  if (!sub) return null
  const json = sub.toJSON ? sub.toJSON() : null
  if (json && json.keys) {
    return {
      endpoint: json.endpoint,
      p256dh: json.keys.p256dh,
      auth: json.keys.auth,
      user_agent: typeof navigator !== 'undefined' ? navigator.userAgent.slice(0, 500) : null,
    }
  }
  // Fallback: extraer keys manualmente
  return {
    endpoint: sub.endpoint,
    p256dh: arrayBufferToBase64Url(sub.getKey('p256dh')),
    auth: arrayBufferToBase64Url(sub.getKey('auth')),
    user_agent: typeof navigator !== 'undefined' ? navigator.userAgent.slice(0, 500) : null,
  }
}

export function usePushNotifications() {
  const [supported, setSupported] = useState(false)
  const [permission, setPermission] = useState('default')
  const [subscribed, setSubscribed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Detectar capabilities + estado inicial al montar
  useEffect(() => {
    if (typeof window === 'undefined') return
    const isSupported =
      'serviceWorker' in navigator &&
      'PushManager' in window &&
      'Notification' in window
    setSupported(isSupported)
    if (!isSupported) return
    setPermission(Notification.permission)

    // Si ya hay registración, ver si tiene sub
    navigator.serviceWorker.getRegistration(SW_PATH).then(async (reg) => {
      if (!reg) return
      try {
        const sub = await reg.pushManager.getSubscription()
        setSubscribed(!!sub)
      } catch { /* ignore */ }
    })
  }, [])

  // Registra el SW si no está, devuelve la registración.
  async function ensureSWRegistered() {
    let reg = await navigator.serviceWorker.getRegistration(SW_PATH)
    if (!reg) {
      reg = await navigator.serviceWorker.register(SW_PATH, { scope: '/' })
    }
    // Esperar que esté activo (ready)
    await navigator.serviceWorker.ready
    return reg
  }

  const subscribe = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (!supported) throw new Error('Tu browser no soporta notificaciones push.')
      // Pedir permiso si está en default
      if (Notification.permission === 'default') {
        const result = await Notification.requestPermission()
        setPermission(result)
        if (result !== 'granted') {
          throw new Error('Permiso denegado. Activá las notificaciones en los ajustes del navegador.')
        }
      } else if (Notification.permission === 'denied') {
        throw new Error('Notificaciones bloqueadas. Activalas en los ajustes del navegador y refrescá.')
      }

      const reg = await ensureSWRegistered()
      // Pedir public key al backend
      const { public_key } = await api.get('/push/vapid-public-key')
      if (!public_key) throw new Error('Backend no tiene VAPID configurado.')

      // Crear o reusar sub
      let sub = await reg.pushManager.getSubscription()
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(public_key),
        })
      }

      const payload = subscriptionToPayload(sub)
      await api.post('/push/subscribe', payload)
      setSubscribed(true)
    } catch (ex) {
      setError(ex?.message || 'No pudimos suscribir.')
      throw ex
    } finally {
      setLoading(false)
    }
  }, [supported])

  const unsubscribe = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const reg = await navigator.serviceWorker.getRegistration(SW_PATH)
      const sub = reg ? await reg.pushManager.getSubscription() : null
      if (sub) {
        const payload = subscriptionToPayload(sub)
        await api.delete('/push/subscribe', payload).catch(() => { /* silent */ })
        await sub.unsubscribe()
      }
      setSubscribed(false)
    } catch (ex) {
      setError(ex?.message || 'No pudimos desuscribir.')
    } finally {
      setLoading(false)
    }
  }, [])

  const sendTest = useCallback(async () => {
    setError(null)
    try {
      const { sent } = await api.post('/push/test', {})
      return sent
    } catch (ex) {
      setError(ex?.message || 'No pudimos enviar el test.')
      throw ex
    }
  }, [])

  return { supported, permission, subscribed, loading, error, subscribe, unsubscribe, sendTest }
}
