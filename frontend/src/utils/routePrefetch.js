// routePrefetch — prefetch on hover de chunks lazy.
// ═══════════════════════════════════════════════════════════════════════════
// Funciona junto con `React.lazy` de App.jsx: cuando el user hace hover sobre
// un NavLink del Sidebar, disparamos el `import()` del chunk en background.
// Para cuando el user hace click, el chunk ya está descargado y el render
// es instant (sin Suspense fallback).
//
// Vite/browser dedupean dynamic imports identicos: si Sidebar fired el
// import al hacer hover y luego lazy() lo dispara al click, es la misma
// promise resuelta — la red corre 1 sola vez.
//
// El `prefetched` Set evita disparar múltiples imports si el user pasa
// varias veces sobre el mismo link. Si falla la red, se borra del set
// para reintentar en el próximo hover.

const importMap = {
  '/':                () => import('../pages/Home'),
  // Wrappers del restructure 2026-05-27. /posiciones AHORA carga Cartera
  // (no Positions). /analisis es un wrapper nuevo. Las páginas internas
  // siguen siendo lazy-loaded por los wrappers, pero el hover sobre el
  // sidebar dispara el prefetch del wrapper + su tab default.
  '/posiciones':      () => import('../pages/Cartera'),
  '/analisis':        () => import('../pages/Analisis'),
  // Rutas viejas: aunque ahora son redirects, mantenerlas en el map ayuda
  // si algún link interno apunta directamente a ellas.
  '/dashboard':       () => import('../pages/Dashboard'),
  '/insights':        () => import('../pages/Insights'),
  '/comportamiento':  () => import('../pages/Behavioral'),
  '/mensual':         () => import('../pages/Monthly'),
  '/reportes':        () => import('../pages/Reports'),
  '/novedades':       () => import('../pages/Novedades'),
  '/operaciones':     () => import('../pages/Operations'),
  '/config':          () => import('../pages/Config'),
  '/perfil-inversor': () => import('../pages/PerfilInversor'),
  '/objetivos':       () => import('../pages/Goals'),
  '/wrapped':         () => import('../pages/Wrapped'),
  '/imports':         () => import('../pages/Imports'),
  '/planes':          () => import('../pages/Planes'),
  '/admin':           () => import('../pages/Admin'),
  '/mas':             () => import('../pages/More'),
}

const prefetched = new Set()

export function prefetchRoute(path) {
  if (!path || prefetched.has(path)) return
  const fn = importMap[path]
  if (!fn) return
  prefetched.add(path)
  // Disparar import en background. Catch silencioso — si la red falla,
  // borramos del set para reintentar la próxima vez que el user pase hover.
  fn().catch(() => { prefetched.delete(path) })
}
