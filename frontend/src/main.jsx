import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import { ToastProvider } from './components/Toast'
import { initAnalytics } from './utils/analytics'
import { initMetaPixel } from './utils/metaPixel'
import { isChunkLoadError, urlsAReparar, repararAssets } from './utils/chunkErrors'
import './index.css'

// Inicializar GA4 y el Meta Pixel (Facebook/Instagram Ads) al arranque.
// No-op fuera de rendi.finance (servidor local, previews): ver utils/medicion.js.
initAnalytics()
initMetaPixel()

// ─── Auto-reload on stale chunk error ────────────────────────────────────────
// Safari (especialmente iOS) es agresivo cacheando HTML aunque el header
// diga max-age=0. Cuando se hace un deploy nuevo con code splitting, el
// HTML cacheado sigue referenciando los hashes viejos de los chunks JS.
// El nuevo deploy YA NO tiene esos archivos físicos, así que Vercel los
// trata como 404 y devuelve index.html como SPA fallback.
//
// El browser entonces intenta ejecutar HTML como JavaScript →
// "Failed to fetch dynamically imported module" o
// "Refused to execute script because its MIME type ('text/html') is not
//  executable" en Safari/Chrome.
//
// Detectamos esos errores y hacemos un reload una sola vez. El reload
// fuerza al browser a re-pedir el HTML, esta vez con `Cache-Control` que
// agrega un timestamp via beacon (ver loop guard abajo). Después del reload
// el browser tiene HTML fresco que apunta a chunks que SÍ existen.
//
// Loop guard: usamos sessionStorage para evitar reload-loops infinitos si
// el reload no soluciona el problema (caso: el deploy realmente está roto).
// Si hace > 10s desde el último reload, intentamos de nuevo. Si no,
// dejamos el error visible para que React lo maneje.
// Antes de recargar hay que REPARAR, no alcanza con volver a pedir la página:
// si el navegador tiene un /assets/*.js envenenado (HTML guardado como si fuera
// JavaScript, con `immutable` de un año), recargar le vuelve a dar el HTML de su
// propio cache sin consultar al servidor — y el usuario queda en loop. El
// `cache: 'reload'` de repararAssets() es lo único que pisa esa entrada.
async function repararYRecargar(mensaje) {
  try {
    const recursos = performance.getEntriesByType('resource').map(r => r.name)
    const nodos = [...document.querySelectorAll('script[src], link[href]')]
      .map(n => n.src || n.href)
    await repararAssets(
      urlsAReparar({ mensaje, recursos, nodos, origin: window.location.origin }),
    )
  } catch {
    // La reparación es best-effort: si algo falla, recargamos igual.
  }
  try {
    // location.reload() sin args usa el cache. Para forzar bypass del
    // bfcache de Safari, navegamos con un cache-buster query.
    const url = new URL(window.location.href)
    url.searchParams.set('_t', String(Date.now()))
    window.location.replace(url.toString())
  } catch {
    window.location.reload()
  }
}

function maybeReloadOnce(mensaje) {
  try {
    const KEY = 'rendi_chunk_reload_at'
    const lastReload = parseInt(sessionStorage.getItem(KEY) || '0', 10)
    const now = Date.now()
    if (now - lastReload > 10_000) {
      sessionStorage.setItem(KEY, String(now))
      repararYRecargar(mensaje)
    }
  } catch {
    // sessionStorage puede no estar disponible en private mode iOS.
    // Como último recurso, reparamos y recargamos igual.
    repararYRecargar(mensaje)
  }
}

window.addEventListener('error', (event) => {
  const mensaje = event.error?.message || event.message
  if (isChunkLoadError(event.message) || isChunkLoadError(event.error?.message)) {
    maybeReloadOnce(`${mensaje} ${event.filename || ''}`)
  }
})

window.addEventListener('unhandledrejection', (event) => {
  if (isChunkLoadError(event.reason?.message) || isChunkLoadError(event.reason)) {
    maybeReloadOnce(event.reason?.message || event.reason)
  }
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <HelmetProvider>
      <BrowserRouter>
        <ToastProvider>
          <App />
        </ToastProvider>
      </BrowserRouter>
    </HelmetProvider>
  </ErrorBoundary>
)
