// CapaElliott — un conteo posible de ondas de Elliott encima del gráfico.
// ════════════════════════════════════════════════════════════════════════════
// Se prende con el botón «Ondas de Elliott» de la leyenda (apagado de entrada).
// Dibuja la línea que une los picos y pozos contados (llena en el impulso,
// cortada en la corrección), la etiqueta de cada onda (1 2 3 4 5 / A B C) en su
// punto —arriba de un pico, abajo de un pozo—, la raya del precio que
// invalida el conteo y, si hay, la franja donde suele terminar la onda en
// curso con cuánto acertó en la historia (backend/elliott.py, `zona`). Convive con la capa del Fibonacci (CapaFibonacci.jsx):
// otro color y otras formas.
//
// Las cuentas vienen hechas del servidor (backend/elliott.py); las palabras, de
// utils/elliott.js. En HTML encima del SVG, como el Fibonacci: una etiqueta
// dentro del SVG estirado se deformaría. Colores sólo por variables del tema (R8).

import { posicion } from './CapaFibonacci'
import { rotuloOnda, tarjetaElliott } from '../../utils/elliott'

// Índigo: no se confunde con el magenta del Fibonacci, el azul de la media de
// 200, el naranja de la de 50 ni las velas verdes y rojas.
const indigo = (a = 1) => `rgb(var(--cat-indigo) / ${a})`
export const COLOR_ELLIOTT = indigo()

const LETRAS = new Set(['A', 'B', 'C'])

/** Los precios que el gráfico tiene que mostrar para que la capa entre: los
 *  puntos que se ven y el precio que invalida (si el conteo se ve). */
export function preciosDelConteo(e, puntos) {
  const c = e?.disponible ? e.principal : null
  if (!c) return []
  const visibles = c.ondas.filter(o => posicion(puntos, o.fecha).donde === 'adentro').map(o => o.precio)
  if (!visibles.length) return []
  return [...visibles, c.invalida.precio, ...(zonaVisible(c, puntos) ? [c.zona.desde, c.zona.hasta] : [])]
}

/**
 * ¿Se dibuja la zona? Es sobre lo que viene después del último punto contado:
 * si la ventana está corrida al pasado y ese punto todavía no llegó, la zona
 * quedaría sobre velas viejas, en un lugar que no es el suyo.
 */
export function zonaVisible(c, puntos) {
  return !!c?.zona && posicion(puntos, c.ondas[c.ondas.length - 1].fecha).donde !== 'despues'
}

/** La fecha desde la que hay que ver el gráfico para que entre el conteo. */
export const fechaDelConteo = (e) => (e?.disponible ? e.principal.ondas[0].fecha : null)

export default function CapaElliott({ elliott, puntos, pctX, pctY, precio }) {
  const c = elliott?.disponible ? elliott.principal : null
  if (!c || !puntos.length) return null
  const pos = c.ondas.map(o => ({ ...o, p: posicion(puntos, o.fecha) }))
  if (pos.every(o => o.p.donde !== 'adentro')) return null
  // Segmentos: sólo entre dos puntos que se ven (uno cortado en el borde
  // tendría una inclinación que no es la suya).
  const segs = []
  for (let k = 1; k < pos.length; k++) {
    const a = pos[k - 1], b = pos[k]
    if (a.p.donde === 'adentro' && b.p.donde === 'adentro') {
      segs.push({ k, x1: pctX(a.p.i), y1: pctY(a.precio), x2: pctX(b.p.i), y2: pctY(b.precio), corr: LETRAS.has(b.onda) })
    }
  }
  const xInv = pos[0].p.donde === 'adentro' ? pctX(pos[0].p.i) : 0
  const yInv = pctY(c.invalida.precio)
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden="true">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
        {segs.map(s => (
          <line key={s.k} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} stroke={COLOR_ELLIOTT}
            strokeWidth="2" strokeLinecap="round" strokeDasharray={s.corr ? '5 4' : undefined}
            vectorEffect="non-scaling-stroke" opacity="0.85" />
        ))}
      </svg>
      {/* La zona donde suele terminar la onda en curso: desde el último punto
          contado hasta hoy, con cuánto acertó en la historia medida. */}
      {zonaVisible(c, puntos) && (() => {
        const ult = pos[pos.length - 1]
        const x = ult.p.donde === 'adentro' ? pctX(ult.p.i) : 0
        const y1 = pctY(c.zona.hasta), y2 = pctY(c.zona.desde)
        return (
          <div className="absolute" style={{ left: `${x}%`, right: 0, top: `${Math.min(y1, y2)}%`, height: `${Math.abs(y2 - y1)}%`,
            background: indigo(0.12), borderTop: `1px dashed ${indigo(0.6)}`, borderBottom: `1px dashed ${indigo(0.6)}` }}>
            <span className="absolute right-1 top-0.5 rounded bg-bg-1/85 px-1 text-[10.5px] leading-tight tabular whitespace-nowrap text-ink-1">
              Podría terminar acá · acertó {Math.round((c.zona.aciertos / c.zona.casos) * 100)} %
            </span>
          </div>
        )
      })()}
      {/* Las rayas donde el conteo dejaría de tener sentido: desde el
          arranque del conteo hasta hoy. La segunda (del otro lado), sólo si cae
          dentro de lo que se ve: no estira la escala. */}
      {[c.invalida, c.invalida.otro].filter(Boolean).map((r, k) => {
        const y = k === 0 ? yInv : pctY(r.precio)
        if (k > 0 && (y < 0 || y > 100)) return null
        return (
          <div key={k} className="absolute h-0" style={{ left: `${xInv}%`, right: 0, top: `${y}%`, borderTop: `1.5px dashed ${indigo(0.8)}` }}>
            <span className={`absolute ${r.lado === 'debajo' ? 'top-0.5' : '-translate-y-full'} ${xInv < 60 ? 'left-1' : 'right-1'} rounded bg-bg-1/85 px-1 text-[10.5px] leading-tight tabular whitespace-nowrap text-ink-1`}>
              Dejaría de valer · {precio(r.precio)}
            </span>
          </div>
        )
      })}
      {pos.map(o => {
        if (o.p.donde !== 'adentro') return null
        const r = rotuloOnda(o)
        const x = pctX(o.p.i), y = pctY(o.precio)
        // El arranque: un punto sin número.
        if (!r) {
          return <span key={o.onda} className="absolute -translate-x-1/2 -translate-y-1/2 w-2 h-2 rounded-full" style={{ left: `${x}%`, top: `${y}%`, background: COLOR_ELLIOTT }} />
        }
        const arriba = o.tipo === 'pico'
        return (
          <span key={o.onda} title={`Onda ${o.onda}: ${precio(o.precio)}`}
            className={`absolute -translate-x-1/2 ${arriba ? '-translate-y-[calc(100%+4px)]' : 'translate-y-1'} inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full border bg-bg-1 text-[11px] font-semibold leading-none tabular text-ink-0`}
            style={{ left: `${x}%`, top: `${y}%`, borderColor: COLOR_ELLIOTT }}>
            {o.onda}
          </span>
        )
      })}
    </div>
  )
}

/** La tarjeta en castellano, con el mismo formato que la del Fibonacci. */
export function TarjetaElliott({ elliott, precio, fecha }) {
  const t = tarjetaElliott(elliott, precio, fecha)
  if (!t) return null
  return (
    <div className="col-span-full rounded-lg border px-3.5 py-3" style={{ borderColor: indigo(0.4), background: indigo(0.05) }}>
      <div className="text-[12px] text-ink-2 font-medium">{t.titulo}</div>
      <div className="text-[15px] font-semibold mt-0.5 text-ink-0">{t.veredicto}</div>
      <div className="text-[12.5px] text-ink-1 leading-relaxed mt-1.5">{t.texto}</div>
      {t.invalida && <div className="text-[12.5px] text-ink-1 leading-relaxed mt-1.5">{t.invalida}</div>}
      {t.zona && <div className="text-[12.5px] text-ink-1 leading-relaxed mt-1.5">{t.zona}</div>}
      {t.confianza && (
        <div className="mt-1.5">
          <div className="text-[12.5px] text-ink-1 font-medium">{t.confianza}</div>
          <ul className="mt-1 space-y-0.5">
            {t.pautas.map((p, k) => (
              <li key={k} className="text-[12px] text-ink-2 leading-relaxed flex gap-1.5">
                <span aria-hidden="true" className={p.cumple ? 'text-rendi-pos' : 'text-ink-3'}>{p.cumple ? '✓' : '·'}</span>
                <span><span className="sr-only">{p.cumple ? 'Se cumple: ' : 'No se cumple: '}</span>{p.texto}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {t.alternativo && <div className="text-[12.5px] text-ink-1 leading-relaxed mt-1.5">{t.alternativo}</div>}
      <div className="text-[11.5px] text-ink-3 leading-relaxed mt-2">{t.pie}</div>
    </div>
  )
}
