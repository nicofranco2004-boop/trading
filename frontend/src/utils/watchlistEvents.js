// watchlistEvents — broadcast simple cross-componente para cambios de watchlist.
// ═══════════════════════════════════════════════════════════════════════════
// Problema que resuelve: el componente <Watchlist> en /home fetcheaba al
// montar pero no escuchaba cambios externos. Si agregabas un ticker desde
// /buscar, MobileSearch o AssetQuickView, el watchlist quedaba stale hasta
// que volvieras a recargar la página o re-montar el componente.
//
// Patrón: window-level CustomEvent. Sin store global (no Zustand/Redux),
// sin lift-state. Cada mutator dispara `notify`, cada renderer escucha
// `subscribe`. Compatible con SSR (guard typeof window).

const EVENT_NAME = 'rendi:watchlist-changed'

export function notifyWatchlistChanged(detail = {}) {
  if (typeof window === 'undefined') return
  try {
    window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail }))
  } catch {
    // CustomEvent unavailable in some legacy contexts — fail silent.
  }
}

export function subscribeWatchlistChanged(handler) {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(EVENT_NAME, handler)
  return () => window.removeEventListener(EVENT_NAME, handler)
}
