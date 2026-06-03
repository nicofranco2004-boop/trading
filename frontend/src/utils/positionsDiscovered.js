// Flag "descubrió la pantalla de posiciones" — para el Paso 2 del onboarding.
// ════════════════════════════════════════════════════════════════════════════
// El Paso 2 ("Cargá tus posiciones activas") NO se completa cargando una
// posición ni con las que reconstruye el import: se completa por DESCUBRIMIENTO,
// apenas el user ve la tab de Posiciones (donde aparece seleccionar/crear
// broker y el alta de posiciones). Así importar (que pasa por /imports) no lo
// tilda solo, y no forzamos cargar/duplicar para poder completarlo.
//
// Mismo patrón que AIDiscoveryBanner (isAIDiscovered / markAIDiscovered): flag
// en localStorage + custom event para que OnboardingChecklist re-chequee en el
// mismo tab (localStorage no dispara `storage` para el tab que escribió).

export const POSITIONS_DISCOVERED_KEY = 'rendi_positions_discovered'

export function isPositionsDiscovered() {
  try {
    return localStorage.getItem(POSITIONS_DISCOVERED_KEY) === '1'
  } catch {
    return false
  }
}

export function markPositionsDiscovered() {
  try {
    if (localStorage.getItem(POSITIONS_DISCOVERED_KEY) === '1') return
    localStorage.setItem(POSITIONS_DISCOVERED_KEY, '1')
    window.dispatchEvent(new Event('positions-discovered'))
  } catch {
    /* localStorage no disponible — no-op */
  }
}
