// CapaDibujos — lo que la persona dibuja a mano sobre el gráfico de la ficha.
// ════════════════════════════════════════════════════════════════════════════
// Líneas de tendencia y horizontales, un retroceso de Fibonacci propio (el tramo
// que elige, con los mismos niveles y rótulos que el automático:
// utils/fibonacci.js), una extensión de Fibonacci (tres toques: los niveles hacia
// adelante) y conteos propios de Elliott: el impulso 0-1-2-3-4-5 y la corrección
// A-B-C, por separado, uno por toque. Y (Nico, 29/10) el canal paralelo (la
// línea de abajo, su paralela y la del medio, con la franja sombreada) y el
// pincel (un trazo a mano alzada). Y (Nico, 03/11) la posición, como la de
// TradingView: dónde entraste, tu objetivo (la franja verde) y tu stop (la
// roja), con cuánto ganás o perdés en cada uno y qué pasó desde que entraste.
// Todo lo demás en
// el color de lo tuyo (celeste, o el que elijas para cada dibujo: utils/dibujos
// COLORES_DIBUJO), para no confundirlo con lo calculado: el Fibonacci
// automático es magenta y las ondas automáticas, índigo.
//
// Recibe los dibujos ya ubicados en lo que se ve (`k`: el lugar en el ancho;
// LecturaTecnica los pasa de día a lugar) y los dibuja en un SVG de 0 a 100,
// como las capas automáticas; los textos van en HTML encima (adentro del SVG
// estirado se deformarían). Guardado y formato: utils/dibujos.js.
//
// La escala (Nico, 12/11): la línea de tendencia y el canal son rectos en la
// escala en que se dibujaron (`escala` del dibujo) y se dibujan así en
// cualquiera: mirados en la otra (`vista`), se ven curvos. Es la misma línea
// mirada con otra regla, y es la que mira el aviso. Lo demás (horizontales,
// Fibonacci, Elliott, posición, pincel, notas) son precios sueltos: van a su
// precio en la escala que se mire.

import { COLORES_DIBUJO, cuentasDePosicion, etiquetasDe, puntasDe } from '../../utils/dibujos'
import { aEje, deEje, escalaDe, esLog, precioEnLaRecta, precioMasAncho } from '../../utils/escalaPrecio'
import { pctConSigno } from '../../utils/cuantoSeMueve'
import { extensionFibonacci, fibonacciAMano, nivelPct, rayas, rotuloNivel, rotulosQueEntran } from '../../utils/fibonacci'
import { PRIORIDAD } from '../../utils/rotulos'

export const COLOR_DIBUJO = 'rgb(var(--data-cyan))'
/** El color de un dibujo (el que eligió la persona, o el celeste de siempre). */
export const colorDe = (d) => {
  const c = COLORES_DIBUJO.find(x => x.id === d?.color)
  return c ? `rgb(var(--${c.token}))` : COLOR_DIBUJO
}

// Cuántos tramos lleva una recta mirada en la otra escala (se ve curva): esa
// cantidad parejos en días y otra tanta parejos en la altura.
const TRAMOS_DE_CURVA = 24

/** Los puntos ([x, y] en lo que se ve, de 0 a 100) de la recta de a a b, recta
 *  en `escala`, entre los lugares k1 y k2, corrida `mas` en el eje de su escala
 *  (la paralela de un canal). Mirada en su misma escala es recta: dos puntos;
 *  en la otra, una curva. Con puntos parejos sólo en días, una línea que
 *  multiplica mucho su precio se apartaba varios píxeles de la de verdad donde
 *  se empina (auditoría 12/11): por eso también van puntos parejos en la
 *  altura, que se juntan justo ahí. */
export function puntosDeLaRecta(a, b, k1, k2, escala, vista, pctX, pctY, mas = 0) {
  // Las dos puntas en el mismo lugar (en semanales, dos días de la misma
  // semana): una raya de una a la otra, como siempre.
  if (a.k === b.k) return [a, b].map(p => [pctX(p.k), pctY(precioMasAncho(p.precio, mas, escala))])
  const precioEn = (k) => precioMasAncho(precioEnLaRecta(a, b, k, escala), mas, escala)
  if (escalaDe(escala) === escalaDe(vista)) return [k1, k2].map(k => [pctX(k), pctY(precioEn(k))])
  const ks = new Set()
  for (let j = 0; j <= TRAMOS_DE_CURVA; j++) ks.add(k1 + ((k2 - k1) * j) / TRAMOS_DE_CURVA)
  // A cada altura pareja (en el eje de lo que se ve), el lugar donde la recta
  // pasa por ahí: su precio en el eje de la recta, sin la paralela.
  const v1 = aEje(precioEn(k1), vista), v2 = aEje(precioEn(k2), vista)
  const ua = aEje(a.precio, escala), ub = aEje(b.precio, escala)
  if (Number.isFinite(v1) && Number.isFinite(v2) && v1 !== v2 && ub !== ua) {
    for (let j = 1; j < TRAMOS_DE_CURVA; j++) {
      const precio = deEje(v1 + ((v2 - v1) * j) / TRAMOS_DE_CURVA, vista)
      const k = a.k + ((aEje(precio, escala) - mas - ua) / (ub - ua)) * (b.k - a.k)
      if (Number.isFinite(k) && k > Math.min(k1, k2) && k < Math.max(k1, k2)) ks.add(k)
    }
  }
  return [...ks].sort((x, y) => (k2 >= k1 ? x - y : y - x)).map(k => [pctX(k), pctY(precioEn(k))])
}

// La recta de a a b seguida desde q hasta el borde derecho (hasta donde la
// mira el aviso), con el último punto justo en el borde.
function hastaElBorde(d, q, kFin, vista, pctX, pctY, mas = 0) {
  const ps = puntosDeLaRecta(d.a, d.b, q.k, kFin, d.escala, vista, pctX, pctY, mas)
  ps[ps.length - 1][0] = 100
  return ps
}

// Una lista de puntos como trazos seguidos, cada uno con `datos` (id, tipo…).
// Los de una curva (más de dos puntos) llevan `curva`: el mismo número para
// todos los de esa curva, así se pueden juntar para dibujarla de un trazo
// (`juntarCurvas`). Para tocarla, siguen sueltos.
let curvas = 0
function tramos(puntos, datos) {
  const out = []
  const curva = puntos.length > 2 ? ++curvas : null
  for (let j = 1; j < puntos.length; j++) {
    out.push({ ...datos, x1: puntos[j - 1][0], y1: puntos[j - 1][1], x2: puntos[j][0], y2: puntos[j][1], ...(curva ? { curva } : {}) })
  }
  return out
}

/** Los trazos con cada curva hecha uno solo, con todos sus `puntos`: una
 *  punteada en pedacitos arrancaría el punteado de nuevo en cada uno y se
 *  vería llena. Lo demás queda igual. */
export function juntarCurvas(trazos) {
  const out = [], abiertas = new Map()
  for (const t of trazos) {
    if (t.curva == null) { out.push(t); continue }
    const g = abiertas.get(t.curva)
    if (g) { g.puntos.push([t.x2, t.y2]); g.x2 = t.x2; g.y2 = t.y2; continue }
    const nueva = { ...t, puntos: [[t.x1, t.y1], [t.x2, t.y2]] }
    abiertas.set(t.curva, nueva)
    out.push(nueva)
  }
  return out
}

/**
 * Los trazos de cada dibujo en lo que se ve (de 0 a 100), para dibujarlos y
 * para saber a cuál se le tocó encima: [{ id, tipo, x1, y1, x2, y2, precio? }].
 * Una horizontal va de borde a borde; un Fibonacci, el tramo y cada nivel
 * desde donde arranca hasta el borde derecho; un conteo, de onda a onda.
 * `vista`: la escala del gráfico ('lineal' o 'log'); una línea de tendencia o
 * un canal de la otra escala va en varios tramos (se ve curvo).
 */
export function trazosDeDibujos(dibujos, pctX, pctY, extendidos = [], vista = 'lineal') {
  const out = []
  for (const d of dibujos) {
    const desde = out.length
    if (d.tipo === 'horizontal') {
      out.push({ id: d.id, tipo: d.tipo, x1: 0, y1: pctY(d.precio), x2: 100, y2: pctY(d.precio), precio: d.precio })
    } else if (d.tipo === 'tendencia') {
      out.push(...tramos(puntosDeLaRecta(d.a, d.b, d.a.k, d.b.k, d.escala, vista, pctX, pctY), { id: d.id, tipo: d.tipo }))
      // Con un aviso, la línea sigue hacia la derecha, punteada: así la mira el
      // aviso (backend/tecnico.valor_de_linea), en la misma dirección y en su escala.
      const [p, q] = d.a.k <= d.b.k ? [d.a, d.b] : [d.b, d.a]
      if (extendidos.includes(d.id) && q.k > p.k && pctX(q.k) < 100) {
        const kFin = p.k + ((100 - pctX(p.k)) / (pctX(q.k) - pctX(p.k))) * (q.k - p.k)
        out.push(...tramos(hastaElBorde(d, q, kFin, vista, pctX, pctY), { id: d.id, tipo: d.tipo, correccion: true }))
      }
    } else if (d.tipo === 'canal') {
      // La de abajo (a → b), su paralela `ancho` más arriba (o más abajo) y la
      // del medio, punteada, como el canal paralelo de TradingView. En un canal
      // logarítmico la paralela multiplica (utils/escalaPrecio.precioMasAncho).
      for (const [mas, medio] of [[0, false], [d.ancho, false], [d.ancho / 2, true]]) {
        out.push(...tramos(puntosDeLaRecta(d.a, d.b, d.a.k, d.b.k, d.escala, vista, pctX, pctY, mas),
          { id: d.id, tipo: d.tipo, correccion: medio, medio }))
      }
      // Con un aviso, sus dos bordes siguen hacia la derecha, punteados: así
      // los mira el aviso (backend/tecnico.bordes_de_canal), como la tendencia.
      const [p, q] = d.a.k <= d.b.k ? [d.a, d.b] : [d.b, d.a]
      if (extendidos.includes(d.id) && q.k > p.k && pctX(q.k) < 100) {
        const kFin = p.k + ((100 - pctX(p.k)) / (pctX(q.k) - pctX(p.k))) * (q.k - p.k)
        for (const mas of [0, d.ancho]) {
          out.push(...tramos(hastaElBorde(d, q, kFin, vista, pctX, pctY, mas), { id: d.id, tipo: d.tipo, correccion: true }))
        }
      }
    } else if (d.tipo === 'pincel') {
      for (let k = 1; k < d.puntos.length; k++) {
        const a = d.puntos[k - 1], b = d.puntos[k]
        out.push({ id: d.id, tipo: d.tipo, x1: pctX(a.k), y1: pctY(a.precio), x2: pctX(b.k), y2: pctY(b.precio), pincel: true })
      }
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
    } else if (d.tipo === 'posicion') {
      // La entrada, a la vista; los bordes de la caja, invisibles: sirven para
      // tocarla (adentro de la caja también se toca: posicionBajo).
      const x1 = pctX(d.a.k), x2 = pctX(d.b.k)
      out.push({ id: d.id, tipo: d.tipo, x1, y1: pctY(d.a.precio), x2, y2: pctY(d.a.precio), entrada: true, color: COLOR_ENTRADA })
      for (const p of [d.objetivo, d.stop]) out.push({ id: d.id, tipo: d.tipo, x1, y1: pctY(p), x2, y2: pctY(p), oculto: true })
      for (const x of [x1, x2]) out.push({ id: d.id, tipo: d.tipo, x1: x, y1: pctY(d.objetivo), x2: x, y2: pctY(d.stop), oculto: true })
      continue
    } else if (d.tipo === 'elliott') {
      for (let k = 1; k < d.puntos.length; k++) {
        const a = d.puntos[k - 1], b = d.puntos[k]
        // La corrección (A-B-C), cortada: sola o después de la 5 en un conteo viejo.
        const corr = d.forma === 'correccion' || (d.forma == null && k >= 6)
        out.push({ id: d.id, tipo: d.tipo, x1: pctX(a.k), y1: pctY(a.precio), x2: pctX(b.k), y2: pctY(b.precio), correccion: corr })
      }
    }
    const color = colorDe(d)
    for (let k = desde; k < out.length; k++) out[k].color = color
  }
  return out
}

/** La posición que tiene a (x, y) adentro de su caja (en % de lo que se ve), o
 *  null: como en TradingView, se agarra de cualquier lado, no sólo del borde. */
export function posicionBajo(dibujos, x, y, pctX, pctY) {
  for (const d of [...dibujos].reverse()) {
    if (d.tipo !== 'posicion' || !d.a || !d.b) continue
    const [x1, x2] = [pctX(d.a.k), pctX(d.b.k)].sort((p, q) => p - q)
    const [y1, y2] = [pctY(d.objetivo), pctY(d.stop)].sort((p, q) => p - q)
    if (x >= x1 && x <= x2 && y >= y1 && y <= y2) return d.id
  }
  return null
}

/**
 * Dónde está tu línea en el lugar `k` (la última vela, la que mira el aviso):
 * un precio para una horizontal o una de tendencia, dos para un canal (sus
 * bordes). La recta sigue en la misma dirección después de su segundo punto,
 * en su escala, como la mira el aviso (backend/tecnico.valor_de_linea). [] si
 * no se puede saber.
 */
export function preciosAlBorde(d, k) {
  if (d.tipo === 'horizontal') return [d.precio]
  if ((d.tipo !== 'tendencia' && d.tipo !== 'canal') || !d.a || !d.b || d.a.k === d.b.k) return []
  const base = precioEnLaRecta(d.a, d.b, k, d.escala)
  return d.tipo === 'canal' ? [base, precioMasAncho(base, d.ancho, d.escala)] : [base]
}

/**
 * `trazo`: lo que se está dibujando ({ tipo, puntos: [{ k, precio }] }) y
 * `cursor` dónde está el mouse: la línea, el Fibonacci o el conteo siguen al
 * mouse hasta el próximo toque.
 */
export default function CapaDibujos({ dibujos, elegido, resaltado = null, trazo, cursor, pctX, pctY, precio, extendidos = [], colorNuevo = null, resultados = {}, escalaDePrecio = 'lineal' }) {
  // Lo que se está dibujando, como si ya estuviera: hasta el mouse (en el
  // color que va a tener y en la escala que se está mirando).
  const enCursoSolo = trazo && cursor?.precio != null ? enCursoHasta(trazo, cursor, escalaDePrecio) : null
  const enCurso = enCursoSolo && colorNuevo ? { ...enCursoSolo, color: colorNuevo } : enCursoSolo
  const todos = enCurso ? [...dibujos, enCurso] : dibujos
  const trazos = trazosDeDibujos(todos, pctX, pctY, extendidos, escalaDePrecio)
  if (!trazos.length && !trazo) return null
  // Elegido, el más grueso; con el mouse encima (`resaltado`), un poco más.
  const grueso = (id) => (id === elegido ? 3 : id === resaltado ? 2.6 : 1.8)
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden="true">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
        {/* La franja de cada canal, apenas sombreada: por su línea de ida y por
            su paralela de vuelta (curvas, si el canal es de la otra escala). */}
        {todos.filter(d => d.tipo === 'canal').map(d => (
          <polygon key={`f-${d.id}`} fill={colorDe(d)} fillOpacity={d.id === elegido ? 0.12 : 0.07} stroke="none"
            points={[...puntosDeLaRecta(d.a, d.b, d.a.k, d.b.k, d.escala, escalaDePrecio, pctX, pctY),
              ...puntosDeLaRecta(d.a, d.b, d.b.k, d.a.k, d.escala, escalaDePrecio, pctX, pctY, d.ancho)]
              .map(([x, y]) => `${x},${y}`).join(' ')} />
        ))}
        {todos.filter(d => d.tipo === 'posicion').map(d => (
          <CajaPosicion key={`p-${d.id}`} d={d} pctX={pctX} pctY={pctY} fuerte={d.id === elegido || d.id === resaltado} resultado={resultados[d.id]} />
        ))}
        {juntarCurvas(trazos.filter(t => !t.oculto)).map((t, k) => {
          const provisorio = t.id === '__en_curso__'
          const punteado = provisorio || t.correccion || (t.nivel && !t.nivel.extremo)
          const comun = {
            'data-dibujo': provisorio ? undefined : t.id, 'data-tipo': t.tipo, stroke: t.entrada ? COLOR_ENTRADA : t.color || COLOR_DIBUJO,
            strokeWidth: t.nivel || t.medio ? (t.id === elegido || t.id === resaltado ? 1.8 : 1) : grueso(t.id), strokeLinecap: 'round',
            strokeDasharray: punteado ? '5 4' : undefined, opacity: t.nivel ? 0.85 : 1, vectorEffect: 'non-scaling-stroke',
          }
          // Una línea o un canal de la otra escala: una curva, de un trazo.
          return t.puntos
            ? <polyline key={`${t.id}-${k}`} {...comun} fill="none" strokeLinejoin="round" points={t.puntos.map(([x, y]) => `${x},${y}`).join(' ')} />
            : <line key={`${t.id}-${k}`} {...comun} x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2} />
        })}
      </svg>
      {todos.filter(d => d.tipo === 'fibonacci').map(d => (
        <RotulosFibonacci key={d.id} d={d} pctX={pctX} pctY={pctY} precio={precio} />
      ))}
      {todos.filter(d => d.tipo === 'extension' && d.c).map(d => (
        <RotulosExtension key={d.id} d={d} pctX={pctX} pctY={pctY} precio={precio} />
      ))}
      {todos.filter(d => d.tipo === 'posicion').map(d => (
        <RotulosPosicion key={d.id} d={d} pctX={pctX} pctY={pctY} precio={precio} resultado={resultados[d.id]} />
      ))}
      {todos.filter(d => d.tipo === 'elliott').map(d => (
        <RotulosElliott key={d.id} d={d} pctX={pctX} pctY={pctY} precio={precio} />
      ))}
      {/* Las puntas: los toques ya hechos de lo que se está dibujando, y las
          de la línea o el Fibonacci elegidos. */}
      {[
        ...(trazo && !ELLIOTT[trazo.tipo] ? trazo.puntos.map((p, k) => ({ k: `t${k}`, x: pctX(p.k), y: pctY(p.precio) })) : []),
        ...dibujos.filter(d => d.id === elegido && (d.tipo === 'tendencia' || d.tipo === 'fibonacci' || d.tipo === 'extension' || d.tipo === 'canal' || d.tipo === 'posicion'))
          .flatMap(d => puntasDe(d).map(([, p], k) => ({ k: `e${k}`, x: pctX(p.k), y: pctY(p.precio), color: colorDe(d) }))),
      ].filter(p => p.x >= 0 && p.x <= 100 && p.y >= 0 && p.y <= 100).map(p => (
        <span key={p.k} className="absolute w-2.5 h-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg-1"
          style={{ left: `${p.x}%`, top: `${p.y}%`, background: p.color || COLOR_DIBUJO }} />
      ))}
    </div>
  )
}

// La posición: la franja de tu objetivo en verde y la de tu stop en rojo,
// desde la entrada hasta su borde derecho. Lo que ya pasó, más fuerte: desde
// la entrada hasta la vela en que tocó el objetivo o el stop (o hasta la
// última, si sigue abierta), entre la entrada y ese precio.
const COLOR_ENTRADA = 'rgb(var(--ink-2))'
function CajaPosicion({ d, pctX, pctY, fuerte, resultado }) {
  const x1 = pctX(d.a.k), x2 = pctX(d.b.k), ye = pctY(d.a.precio)
  const franja = (p, color) => {
    const y = pctY(p)
    return <rect x={Math.min(x1, x2)} y={Math.min(y, ye)} width={Math.abs(x2 - x1)} height={Math.abs(y - ye)} fill={color} fillOpacity={fuerte ? 0.24 : 0.16} />
  }
  const hecho = resultado?.k != null && resultado.precio > 0 ? resultado : null
  const xh = hecho ? Math.min(Math.max(pctX(hecho.k), x1), x2) : null
  const yh = hecho ? pctY(hecho.precio) : null
  const gano = hecho && (d.lado === 'venta' ? hecho.precio < d.a.precio : hecho.precio > d.a.precio)
  return (
    <g data-posicion={d.id}>
      {franja(d.objetivo, 'rgb(var(--rendi-pos))')}
      {franja(d.stop, 'rgb(var(--rendi-neg))')}
      {hecho && xh > x1 && (
        <rect x={x1} y={Math.min(yh, ye)} width={xh - x1} height={Math.abs(yh - ye)}
          fill={gano ? 'rgb(var(--rendi-pos))' : 'rgb(var(--rendi-neg))'} fillOpacity={0.22} />
      )}
    </g>
  )
}

// Los carteles de la posición, como en TradingView: arriba y abajo de la caja
// el objetivo y el stop (su precio y cuánto es, en % de la entrada); en la
// entrada, el ratio y lo que pasó desde que entraste.
function RotulosPosicion({ d, pctX, pctY, precio, resultado }) {
  const { gana, pierde, ratio } = cuentasDePosicion(d)
  const xm = (Math.max(0, Math.min(pctX(d.a.k), 100)) + Math.max(0, Math.min(pctX(d.b.k), 100))) / 2
  if (Math.max(pctX(d.a.k), pctX(d.b.k)) < 0 || Math.min(pctX(d.a.k), pctX(d.b.k)) > 100) return null
  const yo = pctY(d.objetivo), ys = pctY(d.stop), ye = pctY(d.a.precio)
  const arriba = (y) => Math.max(0, Math.min(100, y))
  const cartel = (y, clase, texto, encima) => (
    <span className={`absolute -translate-x-1/2 ${encima ? '-translate-y-[calc(100%+3px)]' : 'translate-y-[3px]'} rounded px-1.5 py-0.5 text-[10.5px] leading-tight tabular whitespace-nowrap ${clase}`}
      style={{ left: `${xm}%`, top: `${arriba(y)}%` }}>{texto}</span>
  )
  const objetivoArriba = yo < ys
  const r = resultado
  const estado = !r || r.estado === 'adelante' ? null
    : r.estado === 'objetivo' ? `Llegó al objetivo: ${pctConSigno(gana)}`
      : r.estado === 'stop' ? `Tocó el stop: ${pctConSigno(-pierde)}`
        : r.pct != null ? `${r.termino ? 'Al cierre de la caja' : 'Abierta'}: ${pctConSigno(r.pct)}` : null
  return (
    <>
      {cartel(yo, 'bg-rendi-pos text-bg-1', `Objetivo: ${precio(d.objetivo)} (${pctConSigno(gana)})`, objetivoArriba)}
      {cartel(ys, 'bg-rendi-neg text-bg-1', `Stop: ${precio(d.stop)} (${pctConSigno(-pierde)})`, !objetivoArriba)}
      {ye >= 0 && ye <= 100 && (
        <span data-rotulo={PRIORIDAD.nivelFib}
          className="absolute -translate-x-1/2 -translate-y-1/2 rounded border border-line bg-bg-1/90 px-1.5 py-0.5 text-[10.5px] leading-tight tabular whitespace-nowrap text-ink-0 text-center"
          style={{ left: `${xm}%`, top: `${ye}%` }}>
          {d.lado === 'venta' ? 'Venta' : 'Compra'} en {precio(d.a.precio)}
          {ratio != null && <> · ratio {ratio.toLocaleString('es-AR', { maximumFractionDigits: 2 })}</>}
          {estado && <><br />{estado}</>}
        </span>
      )}
    </>
  )
}

// Las herramientas de Elliott a mano y la forma que dibujan.
const ELLIOTT = { impulso: 'impulso', correccion: 'correccion', elliott: undefined }

/** Cuánto más arriba (o abajo) de la línea a → b está el punto c, en el eje
 *  de `escala`: el ancho del canal (plata en lineal; en log, el logaritmo de
 *  cuánto multiplica). Con a y b en el mismo lugar, contra el precio de a. */
export function anchoDelCanal(a, b, c, escala) {
  return aEje(c.precio, escala) - aEje(precioEnLaRecta(a, b, c.k, escala), escala)
}

/** La marca de escala de una línea o canal que se dibuja ahora, mirando en
 *  `vista`: { escala: 'log' } o nada (la de siempre se guarda sin marca, como
 *  todas las de antes). */
export const marcaDeEscala = (vista) => (esLog(vista) ? { escala: 'log' } : {})

// Lo que se está dibujando, con el mouse como el próximo toque, en la escala que se mira.
function enCursoHasta(trazo, cursor, vista) {
  const ps = [...trazo.puntos, { k: cursor.k, precio: cursor.precio }]
  if (trazo.tipo in ELLIOTT) return ps.length >= 2 ? { id: '__en_curso__', tipo: 'elliott', forma: ELLIOTT[trazo.tipo], puntos: ps } : null
  if (ps.length < 2) return null
  if (trazo.tipo === 'extension') return { id: '__en_curso__', tipo: 'extension', a: ps[0], b: ps[1], c: ps[2] }
  // El canal: con dos toques, la línea de abajo; el tercero (el mouse) dice el ancho.
  if (trazo.tipo === 'canal' && ps.length >= 3) {
    return { id: '__en_curso__', tipo: 'canal', a: ps[0], b: ps[1], ancho: anchoDelCanal(ps[0], ps[1], ps[2], vista) || 1e-9, ...marcaDeEscala(vista) }
  }
  if (trazo.tipo === 'fibonacci') return { id: '__en_curso__', tipo: 'fibonacci', a: ps[0], b: ps[1] }
  return { id: '__en_curso__', tipo: 'tendencia', a: ps[0], b: ps[1], ...marcaDeEscala(vista) }
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
      style={{ left: adentro ? `calc(${Math.max(0, x0)}% + 4px)` : `calc(${x0}% - 4px)`, top: `${tops[k]}%`, borderLeft: `2px solid ${colorDe(d)}` }}>
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
      style={{ left: adentro ? `calc(${Math.max(0, x0)}% + 4px)` : `calc(${x0}% - 4px)`, top: `${tops[k]}%`, borderLeft: `2px solid ${colorDe(d)}` }}>
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
      return <span key={k} className="absolute -translate-x-1/2 -translate-y-1/2 w-2 h-2 rounded-full" style={{ left: `${x}%`, top: `${y}%`, background: colorDe(d) }} />
    }
    const vecino = d.puntos[k === 0 ? 1 : k - 1]
    const pico = vecino ? p.precio >= vecino.precio : true
    return (
      <span key={k} data-rotulo={PRIORIDAD.onda} title={`Onda ${etiquetas[k]}: ${precio(p.precio)}`}
        className={`absolute -translate-x-1/2 ${pico ? '-translate-y-[calc(100%+4px)]' : 'translate-y-1'} inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full border bg-bg-1 text-[11px] font-semibold leading-none tabular text-ink-0`}
        style={{ left: `${x}%`, top: `${y}%`, borderColor: colorDe(d) }}>
        {etiquetas[k]}
      </span>
    )
  })
}
