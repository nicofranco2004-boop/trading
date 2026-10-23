// ejesGrafico.js — arrastrar los ejes del gráfico técnico, como en TradingView.
// ════════════════════════════════════════════════════════════════════════════
// · La columna de PRECIOS (derecha): arrastrar hacia abajo achica el gráfico en
//   vertical (entra más rango de precio); hacia arriba lo estira. El centro de lo
//   que se ve queda quieto.
// · La fila de FECHAS (abajo): arrastrar hacia la derecha acerca (menos días,
//   velas más anchas); hacia la izquierda aleja. El último día queda quieto.
// · Doble click en cualquiera de los dos: vuelve a lo automático.
// Acá sólo las cuentas; el gráfico (LecturaTecnica.jsx) las usa.

// Cuántos píxeles de arrastre duplican (o reducen a la mitad) la escala.
export const PIXELES_POR_DOBLE = 140
// Topes del estirado vertical: de 5 veces más cerca a 6 veces más lejos.
export const ESCALA_Y_MIN = 0.2
export const ESCALA_Y_MAX = 6

/** El factor de un arrastre de `px` píxeles: 1 = nada; 2 = el doble. */
export function factorDeArrastre(px) {
  return Math.pow(2, px / PIXELES_POR_DOBLE)
}

/** La escala vertical nueva después de arrastrar `dy` píxeles (positivo =
 *  hacia abajo = achica el gráfico), partiendo de `k`. Con topes. */
export function escalaYDespuesDe(k, dy) {
  return Math.min(ESCALA_Y_MAX, Math.max(ESCALA_Y_MIN, k * factorDeArrastre(dy)))
}

/** El rango de precios [lo, hi] estirado por `k` alrededor de su centro. */
export function rangoConEscala(lo, hi, k) {
  if (!k || k === 1) return [lo, hi]
  const c = (lo + hi) / 2
  const m = ((hi - lo) / 2) * k
  return [c - m, c + m]
}

/** El zoom de la fila de fechas: arrastrar `dx` píxeles a la derecha acerca
 *  (factor < 1, menos días a la vista); a la izquierda aleja. */
export function factorDeFechas(dx) {
  return factorDeArrastre(-dx)
}
