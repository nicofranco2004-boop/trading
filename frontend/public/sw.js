// Rendi — Service Worker para Web Push (Sprint M4).
// ═══════════════════════════════════════════════════════════════════════════
// Recibe eventos 'push' del browser y muestra notificaciones nativas.
// También maneja 'notificationclick' para deeplink a la pantalla relevante.
//
// Payload esperado (JSON):
//   { title, body, url?, tag?, icon?, badge? }
//
// El SW se sirve desde la raíz del origin (/sw.js) para tener scope global.
// Vite copia automáticamente lo que está en public/ al build, mismo dev.

/* eslint-disable no-restricted-globals */

const APP_ICON = '/rendi-icon-192.png'      // si existe, sirve como icono
const APP_BADGE = '/rendi-badge-72.png'     // badge monocromo Android

self.addEventListener('install', (event) => {
  // Activarse inmediatamente sin esperar a que se cierren las pestañas viejas
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  // Tomar control de las pestañas abiertas (no requiere refresh)
  event.waitUntil(self.clients.claim())
})

self.addEventListener('push', (event) => {
  let payload = {}
  if (event.data) {
    try { payload = event.data.json() }
    catch {
      try { payload = { title: 'Rendi', body: event.data.text() } }
      catch { payload = { title: 'Rendi', body: 'Notificación' } }
    }
  }
  const {
    title = 'Rendi',
    body = '',
    url = '/',
    tag,
    icon = APP_ICON,
    badge = APP_BADGE,
    requireInteraction = false,
  } = payload

  const options = {
    body,
    icon,
    badge,
    tag,
    data: { url },
    requireInteraction,
    // vibrate solo en Android — Chrome iOS lo ignora
    vibrate: [80, 40, 80],
  }

  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = (event.notification.data && event.notification.data.url) || '/'

  event.waitUntil((async () => {
    // Buscar una pestaña abierta del mismo origin → enfocarla y navegar
    const allClients = await self.clients.matchAll({
      type: 'window',
      includeUncontrolled: true,
    })
    for (const client of allClients) {
      const clientUrl = new URL(client.url)
      if (clientUrl.origin === self.location.origin) {
        client.focus()
        // Si soporta navigate (HTTPS only), usar; sino postMessage para que
        // el cliente haga history.push
        if ('navigate' in client) {
          try { await client.navigate(target) } catch { /* ignore */ }
        } else {
          client.postMessage({ type: 'push-navigate', url: target })
        }
        return
      }
    }
    // No hay tab abierta — abrir una nueva
    if (self.clients.openWindow) {
      await self.clients.openWindow(target)
    }
  })())
})
