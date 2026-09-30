// BarraIntensidad — la barrita de color detrás de una fila de mercado, más
// larga cuanto más se movió el activo en el día. Verde si subió, roja si bajó.
// La usan los movers y la watchlist del inicio.
//
// Escala FIJA, no relativa al más movido de la lista: con escala relativa el
// primero de la lista siempre llena la barra, y en un día tranquilo un +0,8 %
// se vería igual de "fuerte" que un +5 % en un día de pánico. Con la fija, un
// día tranquilo se ve tranquilo. TOPE = 5 %: para una acción grande ya es un
// movimiento enorme; de ahí para arriba la barra queda en el máximo.
//
// Se dibuja DETRÁS del contenido: la fila tiene que llevar `relative isolate`
// (isolate crea el contexto donde el -z-10 queda arriba del fondo de la fila y
// abajo del texto).

import { pctVarSign } from '../utils/format'

export const TOPE_BARRA_PCT = 5
const ANCHO_MAX = 55 // % del ancho de la fila que ocupa la barra llena

export function anchoBarra(pct, tope = TOPE_BARRA_PCT) {
  if (pct == null || Number.isNaN(Number(pct))) return 0
  return Math.min(Math.abs(Number(pct)) / tope, 1)
}

export default function BarraIntensidad({ pct, visto = true }) {
  const dir = pctVarSign(pct)
  if (dir === 0) return null
  const ancho = visto ? anchoBarra(pct) * ANCHO_MAX : 0
  return (
    <span
      aria-hidden="true"
      className={`barra-intensidad pointer-events-none absolute inset-y-1 right-0 -z-10 rounded-l ${dir > 0 ? 'bg-rendi-pos/10' : 'bg-rendi-neg/10'}`}
      style={{ width: `${ancho}%` }}
    />
  )
}
