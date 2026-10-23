// ejesGrafico.js — arrastrar los ejes del gráfico técnico, como en TradingView.
// ════════════════════════════════════════════════════════════════════════════
// · La columna de PRECIOS (derecha): arrastrar hacia abajo achica el gráfico en
//   vertical (entra más rango de precio); hacia arriba lo estira. El centro de lo
//   que se ve queda quieto. Desde ese momento el precio queda "a mano": un rango
//   fijo { lo, hi } que ya no se acomoda solo, y arrastrar el gráfico también lo
//   mueve hacia arriba o hacia abajo.
// · La fila de FECHAS (abajo): arrastrar hacia la derecha acerca (menos días,
//   velas más anchas); hacia la izquierda aleja. El último día queda quieto.
// · Doble click en cualquiera de los dos, o el botón «Automático»: vuelve a lo
//   automático. Otro rango, moneda o tipo de gráfico también.
// Acá sólo las cuentas; el gráfico (LecturaTecnica.jsx) las usa.

// Cuántos píxeles de arrastre duplican (o reducen a la mitad) la escala.
export const PIXELES_POR_DOBLE = 140
// Topes de un arrastre de la columna de precios: de 5 veces más cerca a 6 más lejos.
export const ESCALA_Y_MIN = 0.2
export const ESCALA_Y_MAX = 6

/** El factor de un arrastre de `px` píxeles: 1 = nada; 2 = el doble. */
export function factorDeArrastre(px) {
  return Math.pow(2, px / PIXELES_POR_DOBLE)
}

/** El rango de precios después de arrastrar la columna `dy` píxeles (positivo =
 *  hacia abajo = entra más rango), partiendo de [lo, hi]. Centro quieto, con topes. */
export function rangoEstirado(lo, hi, dy) {
  const k = Math.min(ESCALA_Y_MAX, Math.max(ESCALA_Y_MIN, factorDeArrastre(dy)))
  const c = (lo + hi) / 2
  const m = ((hi - lo) / 2) * k
  return { lo: c - m, hi: c + m }
}

/** El rango de precios después de arrastrar el gráfico hacia abajo una
 *  fracción `f` de su alto: el dibujo baja con el mouse, o sea que a la vista
 *  entran precios más altos. Negativo: hacia arriba. */
export function rangoCorrido(lo, hi, f) {
  const d = f * (hi - lo)
  return { lo: lo + d, hi: hi + d }
}

/** El zoom de la fila de fechas: arrastrar `dx` píxeles a la derecha acerca
 *  (factor < 1, menos días a la vista); a la izquierda aleja. */
export function factorDeFechas(dx) {
  return factorDeArrastre(-dx)
}
