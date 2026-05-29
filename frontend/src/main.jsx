import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'
import App from './App'
import { ToastProvider } from './components/Toast'
import { initAnalytics } from './utils/analytics'
import { initMetaPixel } from './utils/metaPixel'
import './index.css'

// Inicializar GA4 al arranque. No-op si VITE_GA_MEASUREMENT_ID no está seteada
// (dev local, o si decidimos no usar tracking).
initAnalytics()

// Inicializar Meta Pixel (Facebook/Instagram Ads). No-op mientras META_PIXEL_ID
// esté vacío en utils/metaPixel.js (o sea, hasta que tengamos la cuenta Meta).
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
const CHUNK_ERROR_PATTERNS = [
  'Loading chunk',
  'Loading CSS chunk',
  'Failed to fetch dynamically imported module',
  'Importing a module script failed',
  "MIME type ('text/html')",
  'is not executable',
  'Unexpected token',  // safari cuando parsea HTML como JS
]

function isChunkLoadError(msg) {
  const s = String(msg || '')
  return CHUNK_ERROR_PATTERNS.some(p => s.includes(p))
}

function maybeReloadOnce() {
  try {
    const KEY = 'rendi_chunk_reload_at'
    const lastReload = parseInt(sessionStorage.getItem(KEY) || '0', 10)
    const now = Date.now()
    if (now - lastReload > 10_000) {
      sessionStorage.setItem(KEY, String(now))
      // location.reload() sin args usa el cache. Para forzar bypass del
      // bfcache de Safari, navegamos con un cache-buster query.
      const url = new URL(window.location.href)
      url.searchParams.set('_t', String(Date.now()))
      window.location.replace(url.toString())
    }
  } catch {
    // sessionStorage puede no estar disponible en private mode iOS.
    // Como último recurso, reload normal.
    window.location.reload()
  }
}

window.addEventListener('error', (event) => {
  if (isChunkLoadError(event.message) || isChunkLoadError(event.error?.message)) {
    maybeReloadOnce()
  }
})

window.addEventListener('unhandledrejection', (event) => {
  if (isChunkLoadError(event.reason?.message) || isChunkLoadError(event.reason)) {
    maybeReloadOnce()
  }
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <HelmetProvider>
    <BrowserRouter>
      <ToastProvider>
        <App />
      </ToastProvider>
    </BrowserRouter>
  </HelmetProvider>
)
