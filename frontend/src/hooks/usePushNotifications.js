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
//     supported, permission, subscribed, revisado, loading, error,
//     plataforma, motivo,
//     subscribe, unsubscribe, sendTest,
//   } = usePushNotifications()
//
// `motivo` dice por qué NO se pueden activar acá ('iphone-sin-instalar',
// 'bloqueadas'…; null si se puede) y lo traduce a palabras
// utils/notificaciones.js — el mismo texto en todas las pantallas. Los errores
// de `subscribe()` salen en castellano y llevan `.motivo`: nunca el mensaje
// crudo del navegador (que llega en inglés y sin decir qué hacer).

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../utils/api'
import { plataformaDe, yaInstalada } from '../utils/instalarApp'
import {
  motivoSinPush, textoSinPush, MENSAJE_CERRO_EL_PEDIDO, MENSAJE_FALLA,
} from '../utils/notificaciones'

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

function hayPush() {
  return typeof window !== 'undefined' &&
    'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

function errorCon(motivo, mensaje) {
  return Object.assign(new Error(mensaje), { motivo })
}

export function usePushNotifications() {
  // Se detecta en el PRIMER render, no en un efecto: si arrancara en «no
  // soportado» y se corrigiera después, en la compu se vería por un instante
  // el cartel de «este navegador no deja recibir notificaciones».
  const [supported] = useState(hayPush)
  const [permission, setPermission] = useState(() => (hayPush() ? Notification.permission : 'default'))
  const [subscribed, setSubscribed] = useState(false)
  // ¿Ya se miró si ESTE dispositivo está suscripto? Hasta entonces `subscribed`
  // es un «no sé», no un «no» (la lista del celular espera esto para no
  // mostrar el paso y sacarlo un instante después).
  const [revisado, setRevisado] = useState(() => !hayPush())
  const [loading, setLoading] = useState(false)
  const enCurso = useRef(null)
  const [error, setError] = useState(null)
  const [plataforma] = useState(() => (typeof navigator === 'undefined' ? 'otro' : plataformaDe(navigator)))
  const [instalada] = useState(() => yaInstalada())
  const motivo = motivoSinPush({ supported, permission, plataforma, instalada })

  // ¿Este dispositivo tiene la suscripción, y qué dice el permiso? Al montar y
  // cada vez que la persona VUELVE a la pantalla: si fue a Ajustes a
  // destrabarlas, al volver tiene que dejar de decir «bloqueadas» sin cerrar
  // la app (en el iPhone instalada no hay botón de recargar).
  useEffect(() => {
    if (!supported) return
    let vivo = true
    function revisar() {
      try { setPermission(Notification.permission) } catch { /* ignore */ }
      Promise.resolve(navigator.serviceWorker.getRegistration(SW_PATH))
        .then(async (reg) => {
          const sub = reg ? await reg.pushManager.getSubscription() : null
          if (vivo) setSubscribed(!!sub)
        })
        .catch(() => { /* ignore */ })
        .finally(() => { if (vivo) setRevisado(true) })
    }
    function alVolver() { if (document.visibilityState !== 'hidden') revisar() }
    revisar()
    document.addEventListener('visibilitychange', alVolver)
    window.addEventListener('focus', alVolver)
    return () => {
      vivo = false
      document.removeEventListener('visibilitychange', alVolver)
      window.removeEventListener('focus', alVolver)
    }
  }, [supported])

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

  // Un doble toque en «Activar» no arranca dos activaciones: el segundo recibe
  // la misma respuesta que el primero.
  const subscribe = useCallback(() => {
    if (!enCurso.current) enCurso.current = suscribir().finally(() => { enCurso.current = null })
    return enCurso.current
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supported, plataforma, instalada])

  async function suscribir() {
    setLoading(true)
    setError(null)
    try {
      const sinPush = motivoSinPush({
        supported, permission: supported ? Notification.permission : 'default', plataforma, instalada,
      })
      if (sinPush) throw errorCon(sinPush, textoSinPush(sinPush, plataforma).titulo)
      // Pedir permiso si está en default
      if (Notification.permission === 'default') {
        const result = await Notification.requestPermission()
        setPermission(result)
        if (result === 'denied') throw errorCon('bloqueadas', textoSinPush('bloqueadas', plataforma).titulo)
        // Cerró el cartel del navegador sin elegir: no es un error, puede volver a tocar.
        if (result !== 'granted') throw errorCon('cerro-el-pedido', MENSAJE_CERRO_EL_PEDIDO)
      }

      const reg = await ensureSWRegistered()
      // Pedir public key al backend
      const { public_key } = await api.get('/push/vapid-public-key')
      if (!public_key) throw new Error('el servidor no devolvió la clave pública de push (VAPID)')

      // Crear o reusar sub
      let sub = await reg.pushManager.getSubscription()
      let nueva = false
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(public_key),
        })
        nueva = true
      }

      const payload = subscriptionToPayload(sub)
      try {
        await api.post('/push/subscribe', payload)
      } catch (ex) {
        // El navegador quedó suscripto pero el servidor no se enteró (corte de
        // red): se deshace. Si no, al volver a la pantalla el teléfono se daba
        // por activado y nunca le llegaba nada (auditoría 2026-10-19).
        if (nueva) { try { await sub.unsubscribe() } catch { /* ya se pierde igual */ } }
        throw ex
      }
      setSubscribed(true)
    } catch (ex) {
      // Lo que no es uno de nuestros motivos (el navegador falló, el servidor
      // no respondió) se cuenta en la consola tal cual —para quien lo tenga que
      // investigar— y a la persona se le dice algo que entienda.
      const e = ex?.motivo ? ex : errorCon('falla', MENSAJE_FALLA)
      if (!ex?.motivo) console.warn('[push] no se pudo activar:', ex)
      setError(e.message)
      throw e
    } finally {
      setLoading(false)
    }
  }

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

  return { supported, permission, subscribed, revisado, loading, error, plataforma, motivo, subscribe, unsubscribe, sendTest }
}
