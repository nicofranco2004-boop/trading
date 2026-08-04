import { Clock } from 'lucide-react'

/**
 * StalePricesNotice — aviso único cuando algún activo se está mostrando con el
 * precio de una rueda anterior.
 *
 * POR QUÉ: yfinance devuelve barras de `.BA` con volumen pero con el cierre en
 * NaN. Rendi cae al último cierre válido, que puede ser de dos ruedas antes, y lo
 * muestra igual que uno de hoy. Eso lo descubrió un usuario comparando contra su
 * broker, no nosotros: el número EXISTÍA, sólo que era viejo, y nada en pantalla
 * lo distinguía. Ahora `/api/prices` estampa cada precio con su fuente y su rueda
 * (`__meta`), y acá se muestra.
 *
 * Un aviso arriba y no un marcador por fila: la pregunta que contesta es "¿está
 * todo al día?", que se responde una vez, no treinta veces.
 *
 * `meta` es `prices.__meta`; `symbols` los que están efectivamente en pantalla —
 * si el usuario filtró por un broker, no tiene sentido avisarle por un activo que
 * no está viendo.
 */
export default function StalePricesNotice({ meta, symbols }) {
  if (!meta) return null
  const enPantalla = symbols && symbols.length ? new Set(symbols) : null
  const viejos = Object.entries(meta)
    .filter(([sym, m]) => m?.stale && (!enPantalla || enPantalla.has(sym)))
    .map(([sym, m]) => ({ sym: sym.replace(/\.BA$/, ''), as_of: m.as_of }))
  if (!viejos.length) return null

  // Todos de la misma fecha (el caso normal) → se nombra una sola vez.
  const fechas = [...new Set(viejos.map(v => v.as_of).filter(Boolean))]
  const fecha = fechas.length === 1 ? fechas[0] : null
  const dm = fecha ? `${fecha.slice(8, 10)}/${fecha.slice(5, 7)}` : null
  const lista = viejos.slice(0, 6).map(v => v.sym).join(', ')
  const resto = viejos.length - 6

  return (
    <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-line bg-bg-2/40 px-3.5 py-2.5 text-xs leading-relaxed text-ink-2">
      <Clock size={14} strokeWidth={1.75} className="mt-0.5 flex-shrink-0 text-ink-3" />
      <div>
        <span className="font-medium text-ink-1">
          {viejos.length === 1 ? '1 activo' : `${viejos.length} activos`} con precio
          {dm ? ` del ${dm}` : ' de una rueda anterior'}
        </span>
        {': '}{lista}{resto > 0 ? ` y ${resto} más` : ''}.{' '}
        <span className="text-ink-3">
          El mercado todavía no publicó su cotización de hoy. El valor de esas filas
          es el de su último cierre, así que el total puede quedar corto.
        </span>
      </div>
    </div>
  )
}
