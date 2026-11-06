import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'
import App from './App'
import { precargarPaginaPublica } from './paginasPublicas'
import ErrorBoundary from './components/ErrorBoundary'
import { ToastProvider } from './components/Toast'
import ConfirmarHost from './components/ConfirmarHost'
import { initAnalytics } from './utils/analytics'
import { initMetaPixel } from './utils/metaPixel'
import { isChunkLoadError, recargarUnaVez } from './utils/chunkErrors'
import { escucharInstalador } from './utils/instalarApp'
import { anotarOrigen } from './utils/origen'
import { ordenarCopiasSinDueno } from './utils/copiasSinDueno'
import './index.css'

// De qué post viene la visita (`?d=x-20261019` o `utm_*`). Va PRIMERO, antes
// de montar la app: el demo borra todo lo que hay después del `?` al arrancar
// y se llevaría el código (ver utils/origen.js).
anotarOrigen()

// Las copias del navegador que dejó la versión anterior a la regla de dueño
// (utils/duenoDeLaPestana): las que dicen de quién son pasan a su dueño, las
// demás se borran, para que no quede en la pestaña nada de la persona anterior
// (ver utils/copiasSinDueno.js).
ordenarCopiasSinDueno()

// Inicializar GA4 y el Meta Pixel (Facebook/Instagram Ads) al arranque.
// No-op fuera de rendi.finance (servidor local, previews): ver utils/medicion.js.
initAnalytics()
initMetaPixel()

// Chrome en Android avisa UNA vez, al cargar, que Rendi se puede instalar. Hay
// que estar escuchando desde ya para que el cartel «Descargar app» tenga el
// botón de un toque cuando alguien lo abra (ver utils/instalarApp.js).
escucharInstalador()

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
// La reparación y la recarga (una sola vez cada 10 s) viven en utils/chunkErrors.js:
// las usan estos dos avisos del navegador y el cartel de error (components/
// ErrorBoundary), que es quien se entera cuando el pedazo que no baja es una
// pantalla que React carga aparte (verificación 05/11, V3).
window.addEventListener('error', (event) => {
  const mensaje = event.error?.message || event.message
  if (isChunkLoadError(event.message) || isChunkLoadError(event.error?.message)) {
    recargarUnaVez(`${mensaje} ${event.filename || ''}`)
  }
})

window.addEventListener('unhandledrejection', (event) => {
  if (isChunkLoadError(event.reason?.message) || isChunkLoadError(event.reason)) {
    recargarUnaVez(event.reason?.message || event.reason)
  }
})

function montar() {
  ReactDOM.createRoot(document.getElementById('root')).render(
    <ErrorBoundary>
      <HelmetProvider>
        <BrowserRouter>
          <ToastProvider>
            <App />
            {/* El "¿Seguro?" de Rendi, uno para toda la app (utils/confirmar.js). */}
            <ConfirmarHost />
          </ToastProvider>
        </BrowserRouter>
      </HelmetProvider>
    </ErrorBoundary>
  )
}

// Si la página llegó YA ESCRITA (las públicas: scripts/prerender.mjs), primero
// bajamos su pedazo y recién después montamos. Si no, React mostraba el
// esqueleto gris mientras lo bajaba y la persona veía texto → gris → texto.
// precargarPaginaPublica nunca falla: en el peor caso, monta como siempre.
if (document.querySelector('[data-prerender]')) {
  precargarPaginaPublica(window.location.pathname).then(montar)
} else {
  montar()
}
