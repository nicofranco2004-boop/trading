// CapaDibujos — lo que la persona dibuja a mano sobre el gráfico de la ficha.
// ════════════════════════════════════════════════════════════════════════════
// Líneas de tendencia y horizontales, un retroceso de Fibonacci propio (el tramo
// que elige, con los mismos niveles y rótulos que el automático:
// utils/fibonacci.js), una extensión de Fibonacci (tres toques: los niveles hacia
// adelante) y conteos propios de Elliott: el impulso 0-1-2-3-4-5 y la corrección
// A-B-C, por separado, uno por toque. Todo en
// el color de lo tuyo (cian), para no confundirlo con lo calculado: el
// Fibonacci automático es magenta y las ondas automáticas, índigo.
//
// Recibe los dibujos ya ubicados en lo que se ve (`k`: el lugar en el ancho;
// LecturaTecnica los pasa de día a lugar) y los dibuja en un SVG de 0 a 100,
// como las capas automáticas; los textos van en HTML encima (adentro del SVG
// estirado se deformarían). Guardado y formato: utils/dibujos.js.

import { etiquetasDe } from '../../utils/dibujos'
import { extensionFibonacci, fibonacciAMano, nivelPct, rayas, rotuloNivel, rotulosQueEntran } from '../../utils/fibonacci'
import { PRIORIDAD } from '../../utils/rotulos'

export const COLOR_DIBUJO = 'rgb(var(--data-cyan))'

/**
 * Los trazos de cada dibujo en lo que se ve (de 0 a 100), para dibujarlos y
 * para saber a cuál se le tocó encima: [{ id, tipo, x1, y1, x2, y2, precio? }].
 * Una horizontal va de borde a borde; un Fibonacci, el tramo y cada nivel
 * desde donde arranca hasta el borde derecho; un conteo, de onda a onda.
 */
export function trazosDeDibujos(dibujos, pctX, pctY) {
  const out = []
  for (const d of dibujos) {
    if (d.tipo === 'horizontal') {
      out.push({ id: d.id, tipo: d.tipo, x1: 0, y1: pctY(d.precio), x2: 100, y2: pctY(d.precio), precio: d.precio })
    } else if (d.tipo === 'tendencia') {
      out.push({ id: d.id, tipo: d.tipo, x1: pctX(d.a.k), y1: pctY(d.a.precio), x2: pctX(d.b.k), y2: pctY(d.b.precio) })
    } else if (d.tipo === 'fibonacci') {
      const x0 = pctX(d.a.k)
      out.push({ id: d.id, tipo: d.tipo, x1: x0, y1: pctY(d.a.precio), x2: pctX(d.b.k), y2: pctY(d.b.precio), tramo: true })
      for (const r of rayas(fibonacciAMano(d.a.precio, d.b.precio))) {
        out.push({ id: d.id, tipo: d.tipo, x1: Math.min(x0, pctX(d.b.k)), y1: pctY(r.precio), x2: 100, y2: pctY(r.precio), nivel: r })
      }
    } else if (d.tipo === 'extension') {
      // El movimiento (a → b) y el retroceso (b → c); los niveles, desde c.
      out.push({ id: d.id, tipo: d.tipo, x1: pctX(d.a.k), y1: pctY(d.a.precio), x2: pctX(d.b.k), y2: pctY(d.b.precio), tramo: true })
      if (d.c) {
        out.push({ id: d.id, tipo: d.tipo, x1: pctX(d.b.k), y1: pctY(d.b.precio), x2: pctX(d.c.k), y2: pctY(d.c.precio), tramo: true, correccion: true })
        for (const n of extensionFibonacci(d.a.precio, d.b.precio, d.c.precio)) {
          out.push({ id: d.id, tipo: d.tipo, x1: pctX(d.c.k), y1: pctY(n.precio), x2: 100, y2: pctY(n.precio), nivel: { ...n, extremo: n.nivel === 0 || n.nivel === 1 } })
        }
      }
    } else if (d.tipo === 'elliott') {
      for (let k = 1; k < d.puntos.length; k++) {
        const a = d.puntos[k - 1], b = d.puntos[k]
        // La corrección (A-B-C), cortada: sola o después de la 5 en un conteo viejo.
        const corr = d.forma === 'correccion' || (d.forma == null && k >= 6)
        out.push({ id: d.id, tipo: d.tipo, x1: pctX(a.k), y1: pctY(a.precio), x2: pctX(b.k), y2: pctY(b.precio), correccion: corr })
      }
    }
  }
  return out
}

/**
 * `trazo`: lo que se está dibujando ({ tipo, puntos: [{ k, precio }] }) y
 * `cursor` dónde está el mouse: la línea, el Fibonacci o el conteo siguen al
 * mouse hasta el próximo toque.
 */
export default function CapaDibujos({ dibujos, elegido, trazo, cursor, pctX, pctY, precio }) {
  // Lo que se está dibujando, como si ya estuviera: hasta el mouse.
  const enCurso = trazo && cursor?.precio != null ? enCursoHasta(trazo, cursor) : null
  const todos = enCurso ? [...dibujos, enCurso] : dibujos
  const trazos = trazosDeDibujos(todos, pctX, pctY)
  if (!trazos.length && !trazo) return null
  const grueso = (id) => (id === elegido ? 3 : 1.8)
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden="true">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
        {trazos.map((t, k) => {
          const provisorio = t.id === '__en_curso__'
          const punteado = provisorio || t.correccion || (t.nivel && !t.nivel.extremo)
          return (
            <line key={`${t.id}-${k}`} data-dibujo={provisorio ? undefined : t.id} data-tipo={t.tipo}
              x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} stroke={COLOR_DIBUJO}
              strokeWidth={t.nivel ? (t.id === elegido ? 1.8 : 1) : grueso(t.id)} strokeLinecap="round"
              strokeDasharray={punteado ? '5 4' : undefined} opacity={t.nivel ? 0.85 : 1} vectorEffect="non-scaling-stroke" />
          )
        })}
      </svg>
      {todos.filter(d => d.tipo === 'fibonacci').map(d => (
        <RotulosFibonacci key={d.id} d={d} pctX={pctX} pctY={pctY} precio={precio} />
      ))}
      {todos.filter(d => d.tipo === 'extension' && d.c).map(d => (
        <RotulosExtension key={d.id} d={d} pctX={pctX} pctY={pctY} precio={precio} />
      ))}
      {todos.filter(d => d.tipo === 'elliott').map(d => (
        <RotulosElliott key={d.id} d={d} pctX={pctX} pctY={pctY} precio={precio} />
      ))}
      {/* Las puntas: los toques ya hechos de lo que se está dibujando, y las
          de la línea o el Fibonacci elegidos. */}
      {[
        ...(trazo && !ELLIOTT[trazo.tipo] ? trazo.puntos.map((p, k) => ({ k: `t${k}`, x: pctX(p.k), y: pctY(p.precio) })) : []),
        ...dibujos.filter(d => d.id === elegido && (d.tipo === 'tendencia' || d.tipo === 'fibonacci' || d.tipo === 'extension'))
          .flatMap(d => [d.a, d.b, d.c].filter(Boolean).map((p, k) => ({ k: `e${k}`, x: pctX(p.k), y: pctY(p.precio) }))),
      ].filter(p => p.x >= 0 && p.x <= 100 && p.y >= 0 && p.y <= 100).map(p => (
        <span key={p.k} className="absolute w-2.5 h-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg-1"
          style={{ left: `${p.x}%`, top: `${p.y}%`, background: COLOR_DIBUJO }} />
      ))}
    </div>
  )
}

// Las herramientas de Elliott a mano y la forma que dibujan.
const ELLIOTT = { impulso: 'impulso', correccion: 'correccion', elliott: undefined }

// Lo que se está dibujando, con el mouse como el próximo toque.
function enCursoHasta(trazo, cursor) {
  const ps = [...trazo.puntos, { k: cursor.k, precio: cursor.precio }]
  if (trazo.tipo in ELLIOTT) return ps.length >= 2 ? { id: '__en_curso__', tipo: 'elliott', forma: ELLIOTT[trazo.tipo], puntos: ps } : null
  if (ps.length < 2) return null
  if (trazo.tipo === 'extension') return { id: '__en_curso__', tipo: 'extension', a: ps[0], b: ps[1], c: ps[2] }
  return { id: '__en_curso__', tipo: trazo.tipo === 'fibonacci' ? 'fibonacci' : 'tendencia', a: ps[0], b: ps[1] }
}

// Los rótulos de tu extensión: cuánto del movimiento (a → b) se proyecta desde
// c, y su precio.
function RotulosExtension({ d, pctX, pctY, precio }) {
  const lista = extensionFibonacci(d.a.precio, d.b.precio, d.c.precio).map(n => ({ ...n, extremo: n.nivel === 0 || n.nivel === 1 }))
  const tops = lista.map(n => pctY(n.precio))
  const conRotulo = rotulosQueEntran(lista, tops, null)
  const x0 = pctX(d.c.k)
  const adentro = x0 < 45
  return lista.map((n, k) => conRotulo.has(k) && tops[k] >= 0 && tops[k] <= 100 && (
    <span key={n.nivel} data-rotulo={PRIORIDAD.nivelFib}
      className={`absolute rounded bg-bg-1/85 px-1 text-[10.5px] leading-tight tabular whitespace-nowrap text-ink-1 ${adentro ? '-translate-y-full' : '-translate-x-full -translate-y-1/2'}`}
      style={{ left: adentro ? `calc(${Math.max(0, x0)}% + 4px)` : `calc(${x0}% - 4px)`, top: `${tops[k]}%`, borderLeft: `2px solid ${COLOR_DIBUJO}` }}>
      {nivelPct(n.nivel)} · {precio(n.precio)}
    </span>
  ))
}

// Los rótulos de los niveles de tu Fibonacci: como los del automático (el
// nombre del nivel y su precio), los que entran sin pisarse.
function RotulosFibonacci({ d, pctX, pctY, precio }) {
  const fib = fibonacciAMano(d.a.precio, d.b.precio)
  const lista = rayas(fib)
  const tops = lista.map(r => pctY(r.precio))
  const conRotulo = rotulosQueEntran(lista, tops, null)
  const x0 = Math.min(pctX(d.a.k), pctX(d.b.k))
  const adentro = x0 < 45
  return lista.map((r, k) => conRotulo.has(k) && tops[k] >= 0 && tops[k] <= 100 && (
    <span key={r.nivel} data-rotulo={PRIORIDAD.nivelFib}
      className={`absolute rounded bg-bg-1/85 px-1 text-[10.5px] leading-tight tabular whitespace-nowrap text-ink-1 ${adentro ? '-translate-y-full' : '-translate-x-full -translate-y-1/2'}`}
      style={{ left: adentro ? `calc(${Math.max(0, x0)}% + 4px)` : `calc(${x0}% - 4px)`, top: `${tops[k]}%`, borderLeft: `2px solid ${COLOR_DIBUJO}` }}>
      {rotuloNivel(r.nivel, fib.dir)} · {precio(r.precio)}
    </span>
  ))
}

// Las etiquetas de tu conteo: arriba de un pico, abajo de un pozo. El arranque
// de una corrección no tiene nombre: un punto.
function RotulosElliott({ d, pctX, pctY, precio }) {
  const etiquetas = etiquetasDe(d.forma)
  return d.puntos.map((p, k) => {
    const x = pctX(p.k), y = pctY(p.precio)
    if (x < 0 || x > 100 || y < 0 || y > 100) return null
    if (!etiquetas[k]) {
      return <span key={k} className="absolute -translate-x-1/2 -translate-y-1/2 w-2 h-2 rounded-full" style={{ left: `${x}%`, top: `${y}%`, background: COLOR_DIBUJO }} />
    }
    const vecino = d.puntos[k === 0 ? 1 : k - 1]
    const pico = vecino ? p.precio >= vecino.precio : true
    return (
      <span key={k} data-rotulo={PRIORIDAD.onda} title={`Onda ${etiquetas[k]}: ${precio(p.precio)}`}
        className={`absolute -translate-x-1/2 ${pico ? '-translate-y-[calc(100%+4px)]' : 'translate-y-1'} inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full border bg-bg-1 text-[11px] font-semibold leading-none tabular text-ink-0`}
        style={{ left: `${x}%`, top: `${y}%`, borderColor: COLOR_DIBUJO }}>
        {etiquetas[k]}
      </span>
    )
  })
}
