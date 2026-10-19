// Arma el HTML de una página pública FUERA del navegador (al publicar), con el
// mismo componente que ve la gente. Lo usa `scripts/prerender.mjs`; la lista de
// páginas es la de `paginasPublicas.js`, la misma que usa App.jsx.
import { renderToString } from 'react-dom/server'
import { StaticRouter } from 'react-router-dom/server'
import { HelmetProvider } from 'react-helmet-async'
import { Routes, Route } from 'react-router-dom'
import { ThemeProvider } from '../contexts/ThemeContext'
import { AuthProvider } from '../contexts/AuthContext'
import { PAGINAS_PUBLICAS } from '../paginasPublicas'
import { sembrarParaPrerender } from '../hooks/usePlanFeatures'

export const RUTAS = Object.keys(PAGINAS_PUBLICAS)

// Lo que ve un visitante sin cuenta (ver usePlanFeatures).
sembrarParaPrerender({ tier: 'free' })

export async function render(url) {
  const cargar = PAGINAS_PUBLICAS[url]
  if (!cargar) throw new Error(`Ruta pública sin página: ${url}`)
  const { default: Pagina } = await cargar()
  const helmetContext = {}
  const html = renderToString(
    <HelmetProvider context={helmetContext}>
      <StaticRouter location={url}>
        <ThemeProvider>
          <AuthProvider>
            <Routes>
              <Route path={url} element={<Pagina />} />
            </Routes>
          </AuthProvider>
        </ThemeProvider>
      </StaticRouter>
    </HelmetProvider>,
  )
  return { html, helmet: helmetContext.helmet }
}
