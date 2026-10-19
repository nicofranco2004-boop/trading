// Las páginas públicas: las que ve alguien SIN cuenta y las que leen los
// buscadores y las IA. Esta lista es la ÚNICA fuente de cuáles son.
//
// La leen:
//   - App.jsx, que arma con ella los componentes de cada ruta.
//   - src/prerender/entry-server.jsx + scripts/prerender.mjs, que al publicar
//     escriben cada una YA ARMADA (con su texto adentro del HTML). Sin eso, las
//     23 le devolvían al robot de una IA el mismo index.html vacío: para Grok o
//     ChatGPT, la guía que explica Sharpe y alfa era idéntica a la portada.
//   - main.jsx, que antes de montar baja el pedazo de la página que llegó
//     escrita, para no pasar por el esqueleto gris (ver lazyPublica).
//
// Si agregás una página pública: sumala acá, con su <Route path="..."> en los
// DOS árboles de App.jsx, su rewrite en vercel.json y su línea en sitemap.xml.
// `paginasPublicas.test.js` se pone rojo si falta alguna de las cuatro.
import { lazy } from 'react'

export const PAGINAS_PUBLICAS = {
  '/': () => import('./pages/Landing'),
  '/planes': () => import('./pages/Planes'),
  '/terminos': () => import('./pages/Terminos'),
  '/reembolso': () => import('./pages/Reembolso'),
  '/privacidad': () => import('./pages/Privacidad'),
  '/brokers/cocos': () => import('./pages/keywords/Cocos'),
  '/brokers/iol': () => import('./pages/keywords/IOL'),
  '/brokers/binance': () => import('./pages/keywords/Binance'),
  '/cedears': () => import('./pages/keywords/Cedears'),
  '/bonos-argentinos': () => import('./pages/keywords/BonosAR'),
  '/afip-cripto': () => import('./pages/keywords/AfipCripto'),
  '/blog': () => import('./pages/Blog'),
  '/blog/fifo-cedears-argentina': () => import('./pages/blog/articles/FifoCedearsArgentina'),
  '/blog/pnl-real-usd-blue-argentina': () => import('./pages/blog/articles/PnlRealUsdBlue'),
  '/blog/comparativa-brokers-argentina': () => import('./pages/blog/articles/ComparativaBrokersArgentina'),
  '/guia': () => import('./pages/Guia'),
  '/guia/empezar': () => import('./pages/guia/Empezar'),
  '/guia/cartera-y-operaciones': () => import('./pages/guia/CarteraYOperaciones'),
  '/guia/insights-y-reportes': () => import('./pages/guia/InsightsYReportes'),
  '/guia/coach-ia': () => import('./pages/guia/CoachIA'),
  '/guia/novedades': () => import('./pages/guia/Novedades'),
  '/guia/cuenta-y-planes': () => import('./pages/guia/CuentaYPlanes'),
  '/guia/asesores': () => import('./pages/guia/Asesores'),
}

// Como `lazy()`, pero se puede bajar ANTES de montar la app.
//
// Por qué: la página llega escrita en el HTML y React, al montar, la reemplaza.
// Con un lazy común, React primero no tiene el componente, muestra el esqueleto
// gris y recién después la página: la persona veía texto → gris → texto. Si el
// pedazo ya se bajó, devolvemos un "then" que contesta en el acto (React lo
// acepta así) y la página se monta sin pasar por el esqueleto.
export function lazyPublica(cargar) {
  let modulo = null
  const precargar = () => cargar().then((m) => { modulo = m; return m })
  const Componente = lazy(() => (modulo ? { then: (listo) => listo(modulo) } : precargar()))
  Componente.precargar = precargar
  return Componente
}

// Un componente por ruta, salvo '/', que App.jsx importa directo (la portada
// es lo primero que ve un visitante y no espera a ningún pedazo).
export const COMPONENTES_PUBLICOS = Object.fromEntries(
  Object.entries(PAGINAS_PUBLICAS)
    .filter(([ruta]) => ruta !== '/')
    .map(([ruta, cargar]) => [ruta, lazyPublica(cargar)]),
)

// Si la página llegó escrita, baja su pedazo antes de montar. Nunca falla: si
// la descarga se cae, se monta igual y el lazy común vuelve a intentar.
export function precargarPaginaPublica(ruta) {
  const Componente = COMPONENTES_PUBLICOS[ruta.replace(/\/+$/, '') || '/']
  if (!Componente) return Promise.resolve()
  return Componente.precargar().catch(() => {})
}
