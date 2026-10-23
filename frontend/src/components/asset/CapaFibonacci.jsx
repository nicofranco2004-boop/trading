// CapaFibonacci — el Fibonacci automático encima del gráfico de la ficha.
// ════════════════════════════════════════════════════════════════════════════
// Se ve de entrada; el botón «Fibonacci» de la leyenda la apaga y la prende. Dibuja
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
import { rayas, rotuloNivel, rotulosQueEntran, tarjetaFibonacci } from '../../utils/fibonacci'

// Magenta: no se confunde con ninguna otra línea del gráfico (precio, media de
// 200 azul, media de 50 naranja, velas verdes y rojas). Variable del tema (R8),
// con transparencia por canal: `rgb(var(--x) / a)`.
const magenta = (a = 1) => `rgb(var(--cat-magenta) / ${a})`
export const COLOR_FIB = magenta()

/**
 * Los precios que el gráfico tiene que mostrar para que la capa entre entera.
 * Nada si lo que se dibuja empieza después de lo que se ve (la ventana está
 * corrida al pasado): estirar la escala por algo invisible aplastaría las velas.
 */
export function preciosDeLaCapa(f, puntos) {
  if (!f) return []
  if (f.disponible) {
    return posicion(puntos, f.desde.fecha).donde === 'despues' ? [] : [f.desde.precio, f.hasta.precio]
  }
  const e = f.en_curso
  if (!e || posicion(puntos, e.se_rompe_si_cierra.fecha).donde === 'despues') return []
  return [e.se_rompe_si_cierra.debajo_de ?? e.se_rompe_si_cierra.encima_de]
}

/**
 * La ventana del gráfico ({ n, fin }, como el zoom de la ruedita) que muestra
 * el tramo medido con aire a los costados: desde un poco antes de su arranque
 * hasta hoy. null si ya se ve con lo que hay (`nVista` ruedas) o si el tramo
 * arranca antes de los datos del gráfico. Un tramo de 3 semanas en un gráfico
 * de 1 año ocupa un 5 % del ancho y los rótulos de sus niveles no entran.
 */
export const RUEDAS_MINIMAS_FIB = 63
export function ventanaDelTramo(puntos, f, nVista) {
  const fecha = f?.disponible ? f.desde.fecha : null
  if (!fecha || !puntos?.length || fecha < puntos[0].d) return null
  const i = indiceDeFecha(puntos, fecha)
  const desdeElTramo = puntos.length - i
  const n = Math.min(puntos.length, Math.max(RUEDAS_MINIMAS_FIB, Math.round(desdeElTramo * 1.6)))
  return n < nVista ? { n, fin: puntos.length } : null
}

/**
 * Dónde cae una fecha en lo que se ve: { donde: 'antes'|'adentro'|'despues', i }.
 * Una vela semanal cubre hasta 6 días después de su fecha (la del lunes).
 * Con zoom o arrastre la ventana puede no incluir el tramo: lo que cae afuera
 * no se dibuja en un lugar que no es el suyo.
 */
export function posicion(puntos, fecha) {
  if (!puntos?.length || !fecha) return { donde: 'despues', i: null }
  if (fecha < puntos[0].d) return { donde: 'antes', i: null }
  const ultimo = puntos[puntos.length - 1]
  const limite = ultimo.semana
    ? new Date(Date.parse(ultimo.d + 'T00:00:00Z') + 6 * 86400000).toISOString().slice(0, 10)
    : ultimo.d
  if (fecha > limite) return { donde: 'despues', i: null }
  return { donde: 'adentro', i: indiceDeFecha(puntos, fecha) }
}

export default function CapaFibonacci({ fib, puntos, pctX, pctY, precio }) {
  if (!fib || !puntos.length) return null
  if (!fib.disponible) return <CorteEnCurso e={fib.en_curso} puntos={puntos} pctX={pctX} pctY={pctY} precio={precio} />

  const p0 = posicion(puntos, fib.desde.fecha)
  if (p0.donde === 'despues') return null
  const p1 = posicion(puntos, fib.hasta.fecha)
  // El rombo va en el cierre que pasó del otro lado (puede ser unos días antes
  // de que se supiera: el pico se confirma 3 ruedas después).
  const rup = fib.ruptura.cerro_fuera_fecha
    ? { fecha: fib.ruptura.cerro_fuera_fecha, cierre: fib.ruptura.cerro_fuera_cierre }
    : fib.ruptura
  const pr = posicion(puntos, rup.fecha)
  // Las rayas arrancan en el arranque del tramo, o en el borde si arrancó antes.
  const x0 = p0.donde === 'adentro' ? pctX(p0.i) : 0
  const x1 = p1.donde === 'adentro' ? pctX(p1.i) : null
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
        <div className="absolute"
          style={{ background: magenta(0.1), left: `${x0}%`, right: 0, top: `${Math.min(...franja)}%`, height: `${Math.abs(franja[0] - franja[1])}%` }} />
      )}
      {lista.map((r, k) => (
        <div key={r.nivel} className="absolute h-0"
          style={{ left: `${x0}%`, right: 0, top: `${tops[k]}%`, borderTop: `1px ${r.extremo ? 'solid' : 'dashed'} ${COLOR_FIB}`, opacity: r.extremo ? 0.9 : 0.7 }}>
          {conRotulo.has(k) && (
            <span className={`absolute rounded bg-bg-1/85 px-1 text-[10.5px] leading-tight tabular whitespace-nowrap text-ink-1 ${rotuloAdentro ? 'left-1 -translate-y-full' : 'right-full mr-1 -translate-y-1/2'}`}>
              {rotuloNivel(r.nivel, fib.dir)} · {precio(r.precio)}
            </span>
          )}
        </div>
      ))}
      {/* El tramo medido, del arranque al final: sólo si se ven los dos (una
          raya cortada en el borde tendría una inclinación que no es la suya). */}
      {p0.donde === 'adentro' && x1 != null && (
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
          <line x1={x0} y1={pctY(fib.desde.precio)} x2={x1} y2={pctY(fib.hasta.precio)} stroke={COLOR_FIB}
            strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke" opacity="0.85" />
        </svg>
      )}
      {p0.donde === 'adentro' && <Punto x={x0} y={pctY(fib.desde.precio)} titulo="Arranque del tramo" />}
      {x1 != null && <Punto x={x1} y={pctY(fib.hasta.precio)} titulo="Final del tramo" />}
      {pr.donde === 'adentro' && (
        <span className="absolute -translate-x-1/2 -translate-y-1/2 w-2.5 h-2.5 rotate-45 border-2 bg-bg-1"
          style={{ left: `${pctX(pr.i)}%`, top: `${pctY(rup.cierre)}%`, borderColor: COLOR_FIB }}
          title={`Ruptura: cerró ${precio(rup.cierre)}`} />
      )}
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
  const pos = posicion(puntos, e.se_rompe_si_cierra.fecha)
  if (pos.donde === 'despues') return null
  const x = pos.donde === 'adentro' ? pctX(pos.i) : 0
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
    <div className="col-span-full rounded-lg border px-3.5 py-3" style={{ borderColor: magenta(0.4), background: magenta(0.05) }}>
      <div className="text-[12px] text-ink-2 font-medium">{t.titulo}</div>
      <div className="text-[15px] font-semibold mt-0.5 text-ink-0">{t.veredicto}</div>
      <div className="text-[12.5px] text-ink-1 leading-relaxed mt-1.5">{t.texto}</div>
      {t.explicacion && <div className="text-[12.5px] text-ink-1 leading-relaxed mt-1.5">{t.explicacion}</div>}
      <div className="text-[11.5px] text-ink-3 leading-relaxed mt-2">{t.pie}</div>
    </div>
  )
}
