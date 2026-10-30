// parteDeTuPlata.js — «qué parte de tu plata es» en palabras: «12%» o «menos
// de 1%». Una sola manera de decirlo para la ficha (cuantoSeMueve), Tu lista,
// el Panorama (RadiografiaTecnica) y Señales (tusSenales): antes cada una
// tenía la suya y YPFD salía «0 %» en una y «menos de 1 %» en otra
// (auditoría D12, 29/10).

/** `pct` de 0 a 100 → «12%», «menos de 1%» o «0%» (null si no hay dato). */
export function parteDeTuPlata(pct) {
  if (pct == null || !Number.isFinite(Number(pct))) return null
  if (pct > 0 && pct < 1) return 'menos de 1%'
  return `${Math.round(pct)}%`
}

/** «Es el 12% de tu cartera» / «Es menos de 1% de tu cartera». */
export function esElDeTuCartera(pct) {
  const p = parteDeTuPlata(pct)
  return p == null ? null : p.startsWith('menos') ? `Es ${p} de tu cartera` : `Es el ${p} de tu cartera`
}

/**
 * El peso de un activo en tu cartera, para dibujarlo: null con «Ocultar
 * saldos» prendido (la proporción también es información de tu cartera). La
 * usan TODAS las pantallas que dibujan un peso; lo vigila
 * __guards__/peso-de-tu-cartera.test.js (re-test de la auditoría D, 29/10:
 * Eventos tapaba el peso en un renglón y no en otros dos).
 */
export function pesoVisible(pct, oculto) {
  return oculto ? null : parteDeTuPlata(pct)
}

/** «12% de tu cartera» / «menos de 1% de tu cartera»; null con el ojito prendido. */
export function deTuCartera(pct, oculto) {
  const p = pesoVisible(pct, oculto)
  return p == null ? null : `${p} de tu cartera`
}
