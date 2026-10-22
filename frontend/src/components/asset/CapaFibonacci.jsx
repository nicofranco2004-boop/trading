// CapaFibonacci — el Fibonacci automático encima del gráfico de la ficha.
// ════════════════════════════════════════════════════════════════════════════
// Se prende con el botón «Fibonacci» de la leyenda (apagado de entrada). Dibuja
// el último tramo confirmado (pozo → pico de una suba, o techo → piso de una
// bajada) resaltado, las rayas de cada nivel con su precio, la franja entre las
// dos rayas donde está hoy el precio y el día de la ruptura. Si no hay tramo
// para medir, la raya del cierre que daría por terminado el tramo vivo.
//
// Las cuentas vienen hechas del servidor (backend/estructura.py); las palabras,
// de utils/fibonacci.js. Va en HTML encima del SVG, como las marcas de tus
// compras: un círculo o un texto dentro del SVG estirado se deformarían. Colores
// sólo por variables del tema (R8).

import { indiceDeFecha } from '../../utils/tecnico'
import { nivelTexto, rayas, rotulosQueEntran, tarjetaFibonacci } from '../../utils/fibonacci'

export const COLOR_FIB = 'rgb(var(--data-amber))'

/** Los precios que el gráfico tiene que mostrar para que la capa entre entera. */
export function preciosDeLaCapa(f) {
  if (!f) return []
  if (f.disponible) return [f.desde.precio, f.hasta.precio]
  const e = f.en_curso
  if (!e) return []
  return [e.se_rompe_si_cierra.debajo_de ?? e.se_rompe_si_cierra.encima_de]
}

// x (0 a 100) de una fecha; antes del gráfico, el borde izquierdo.
function xDe(puntos, fecha, pctX) {
  const i = indiceDeFecha(puntos, fecha)
  return i == null ? 0 : pctX(i)
}

export default function CapaFibonacci({ fib, puntos, pctX, pctY, precio }) {
  if (!fib || !puntos.length) return null
  if (!fib.disponible) return <CorteEnCurso e={fib.en_curso} puntos={puntos} pctX={pctX} pctY={pctY} precio={precio} />

  const x0 = xDe(puntos, fib.desde.fecha, pctX)
  const x1 = xDe(puntos, fib.hasta.fecha, pctX)
  const xr = xDe(puntos, fib.ruptura.fecha, pctX)
  const lista = rayas(fib)
  const tops = lista.map(r => pctY(r.precio))
  const conRotulo = rotulosQueEntran(lista, tops, fib.entre)
  const [a, b] = fib.entre || []
  const franja = fib.entre ? [pctY(lista.find(r => r.nivel === a).precio), pctY(lista.find(r => r.nivel === b).precio)] : null
  // Los rótulos van ADENTRO de las rayas si el tramo arranca en la primera
  // mitad del gráfico; si arranca más a la derecha, AFUERA, a la izquierda de
  // donde empieza la raya (ahí no hay velas del tramo que tapar). En un
  // celular, con 1 año en pantalla, el último tramo casi siempre está al final.
  const rotuloAdentro = x0 < 45

  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden="true">
      {franja && (
        <div className="absolute bg-data-amber/10"
          style={{ left: `${x0}%`, right: 0, top: `${Math.min(...franja)}%`, height: `${Math.abs(franja[0] - franja[1])}%` }} />
      )}
      {lista.map((r, k) => (
        <div key={r.nivel} className="absolute h-0"
          style={{ left: `${x0}%`, right: 0, top: `${tops[k]}%`, borderTop: `1px ${r.extremo ? 'solid' : 'dashed'} ${COLOR_FIB}`, opacity: r.extremo ? 0.9 : 0.7 }}>
          {conRotulo.has(k) && (
            <span className={`absolute rounded bg-bg-1/85 px-1 text-[10.5px] leading-tight tabular whitespace-nowrap text-ink-1 ${rotuloAdentro ? 'left-1 -translate-y-full' : 'right-full mr-1 -translate-y-1/2'}`}>
              {nivelTexto(r.nivel)} · {precio(r.precio)}
            </span>
          )}
        </div>
      ))}
      {/* El tramo medido: del arranque al final. */}
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
        <line x1={x0} y1={pctY(fib.desde.precio)} x2={x1} y2={pctY(fib.hasta.precio)} stroke={COLOR_FIB}
          strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke" opacity="0.85" />
      </svg>
      <Punto x={x0} y={pctY(fib.desde.precio)} titulo="Arranque del tramo" />
      <Punto x={x1} y={pctY(fib.hasta.precio)} titulo="Final del tramo" />
      <span className="absolute -translate-x-1/2 -translate-y-1/2 w-2.5 h-2.5 rotate-45 border-2 bg-bg-1"
        style={{ left: `${xr}%`, top: `${pctY(fib.ruptura.cierre)}%`, borderColor: COLOR_FIB }}
        title={`Ruptura: cerró ${precio(fib.ruptura.cierre)}`} />
    </div>
  )
}

function Punto({ x, y, titulo }) {
  return (
    <span className="absolute -translate-x-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full border-2 border-bg-1"
      style={{ left: `${x}%`, top: `${y}%`, background: COLOR_FIB }} title={titulo} />
  )
}

// Sin tramo para medir: el tramo vivo y el cierre que lo daría por terminado.
function CorteEnCurso({ e, puntos, pctX, pctY, precio }) {
  if (!e) return null
  const suba = e.dir === 'suba'
  const corte = suba ? e.se_rompe_si_cierra.debajo_de : e.se_rompe_si_cierra.encima_de
  const x = xDe(puntos, e.se_rompe_si_cierra.fecha, pctX)
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden="true">
      <div className="absolute h-0" style={{ left: `${x}%`, right: 0, top: `${pctY(corte)}%`, borderTop: `1.5px dashed ${COLOR_FIB}` }}>
        <span className={`absolute ${suba ? 'top-0.5' : '-translate-y-full'} ${x < 70 ? 'left-1' : 'right-1'} rounded bg-bg-1/85 px-1 text-[10.5px] leading-tight tabular whitespace-nowrap text-ink-1`}>
          {suba ? 'Cierre debajo: termina la suba' : 'Cierre encima: termina la bajada'} · {precio(corte)}
        </span>
      </div>
    </div>
  )
}

/** La tarjeta en castellano, con el mismo formato que las de la lectura. */
export function TarjetaFibonacci({ fib, precio, fecha }) {
  const t = tarjetaFibonacci(fib, precio, fecha)
  if (!t) return null
  return (
    <div className="sm:col-span-2 rounded-lg border border-data-amber/40 bg-data-amber/5 px-3.5 py-3">
      <div className="text-[12px] text-ink-2 font-medium">{t.titulo}</div>
      <div className="text-[15px] font-semibold mt-0.5 text-ink-0">{t.veredicto}</div>
      <div className="text-[12.5px] text-ink-1 leading-relaxed mt-1.5">{t.texto}</div>
      <div className="text-[11.5px] text-ink-3 leading-relaxed mt-2">{t.pie}</div>
    </div>
  )
}
