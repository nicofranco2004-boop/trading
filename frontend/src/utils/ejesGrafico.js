// ejesGrafico.js — arrastrar los ejes del gráfico técnico, como en TradingView.
// ════════════════════════════════════════════════════════════════════════════
// · La columna de PRECIOS (derecha): arrastrar hacia abajo achica el gráfico en
//   vertical (entra más rango de precio); hacia arriba lo estira. El centro de lo
//   que se ve queda quieto. Desde ese momento el precio queda "a mano": un rango
//   fijo { lo, hi } que ya no se acomoda solo, y arrastrar el gráfico también lo
//   mueve hacia arriba o hacia abajo.
// · La fila de FECHAS (abajo): arrastrar hacia la izquierda acerca (menos días,
//   velas más anchas); hacia la derecha aleja. El último día queda quieto.
//   (Al revés de la primera versión: Nico lo pidió así, 23/10.)
// · Doble click en cualquiera de los dos, o el botón «Automático»: vuelve a lo
//   automático. Otro rango, moneda, tipo de gráfico o escala también.
// · En la escala logarítmica (utils/escalaPrecio.js) estirar y correr se hacen
//   en el eje de esa escala: correr multiplica en vez de sumar, así el borde de
//   abajo nunca cruza el cero (que en log no existe) y el gráfico se mueve
//   parejo en cualquier parte.
// Acá sólo las cuentas; el gráfico (LecturaTecnica.jsx) las usa.

import { aEje, deEje, esLog, marcasLog } from './escalaPrecio'

// Cuántos píxeles de arrastre duplican (o reducen a la mitad) la escala.
export const PIXELES_POR_DOBLE = 140
// Topes de un arrastre de la columna de precios: de 5 veces más cerca a 6 más lejos.
export const ESCALA_Y_MIN = 0.2
export const ESCALA_Y_MAX = 6
// En logarítmica, lo más que se puede alejar: seis décadas para cada lado del
// medio (de 0,000001 a 1.000.000 veces), y los bordes, dentro de e^±690.
export const MEDIO_RANGO_LOG_MAXIMO = 6 * Math.LN10
const BORDE_LOG = 690

/** El factor de un arrastre de `px` píxeles: 1 = nada; 2 = el doble. */
export function factorDeArrastre(px) {
  return Math.pow(2, px / PIXELES_POR_DOBLE)
}

/** Lo arrastrado en la columna de precios, sin pasar los topes. El arrastre se
 *  cuenta desde donde empezó; si lo que pasa del tope se guardara, al darse
 *  vuelta primero habría que devolverlo antes de que el gráfico se mueva (Nico,
 *  31/10: «en los extremos cuesta mucho»). Con esto el punto de partida se corre
 *  con el mouse mientras empuja contra el tope. */
export function arrastreDentroDelTope(dy) {
  const max = PIXELES_POR_DOBLE * Math.log2(ESCALA_Y_MAX)
  const min = PIXELES_POR_DOBLE * Math.log2(ESCALA_Y_MIN)
  return Math.min(max, Math.max(min, dy))
}

/** El rango de precios después de arrastrar la columna `dy` píxeles (positivo =
 *  hacia abajo = entra más rango), partiendo de [lo, hi]. Centro quieto (en el
 *  eje de la `escala`), con topes. */
export function rangoEstirado(lo, hi, dy, escala) {
  const k = Math.min(ESCALA_Y_MAX, Math.max(ESCALA_Y_MIN, factorDeArrastre(dy)))
  const a = aEje(lo, escala), b = aEje(hi, escala)
  const c = (a + b) / 2
  // En log, los estirones se suman (cada uno parte del anterior) y en el eje
  // cada uno ya multiplica el rango: sin tope, a la cuarta vez los precios se
  // van de los números. Hasta MEDIO_RANGO_LOG_MAXIMO para cada lado.
  const m = Math.min(((b - a) / 2) * k, esLog(escala) ? MEDIO_RANGO_LOG_MAXIMO : Infinity)
  return { lo: deEje(c - m, escala), hi: deEje(c + m, escala) }
}

/** El rango de precios después de arrastrar el gráfico hacia abajo una
 *  fracción `f` de su alto: el dibujo baja con el mouse, o sea que a la vista
 *  entran precios más altos. Negativo: hacia arriba. */
export function rangoCorrido(lo, hi, f, escala) {
  const a = aEje(lo, escala), b = aEje(hi, escala)
  // En log, sin salirse de los números que existen (e^±690).
  const d = esLog(escala) ? Math.max(-BORDE_LOG - a, Math.min(BORDE_LOG - b, f * (b - a))) : f * (b - a)
  return { lo: deEje(a + d, escala), hi: deEje(b + d, escala) }
}

// ─── El precio «a mano» lleva DOS rangos (auditoría D4, 31/10) ────────────────
// El de la pantalla (`lo`, `hi`) y el de la imagen de «Compartir» (`comp`). En
// automático la pantalla se estira hasta tu precio de compra y la imagen no
// (`compartible`, LecturaTecnica: si se estirara, la franja vacía diría más o
// menos a cuánto compraste). Antes, al arrastrar, el rango a mano arrancaba del
// de la PANTALLA y ése era el que se compartía: la imagen llevaba tu precio en
// la escala. Ahora cada arrastre mueve los dos con el mismo gesto, y el de la
// imagen arranca de `compartible`: nunca sabe de tu precio.

/** El rango a mano al empezar a arrastrar: [lo, hi] de la pantalla y de la imagen. */
export function empezarAMano([lo, hi], [cLo, cHi]) {
  return { lo, hi, comp: { lo: cLo, hi: cHi } }
}

/** Arrastrar el gráfico una fracción `f` de su alto (ver rangoCorrido), los dos rangos. */
export function correrAMano(mano, f, escala) {
  return { ...rangoCorrido(mano.lo, mano.hi, f, escala), comp: rangoCorrido(mano.comp.lo, mano.comp.hi, f, escala) }
}

/** Arrastrar la columna de precios `dy` píxeles desde `inicio` (ver rangoEstirado), los dos rangos. */
export function estirarAMano(inicio, dy, escala) {
  return { ...rangoEstirado(inicio.lo, inicio.hi, dy, escala), comp: rangoEstirado(inicio.comp.lo, inicio.comp.hi, dy, escala) }
}

/** El zoom de la fila de fechas: arrastrar `dx` píxeles a la izquierda acerca
 *  (factor < 1, menos días a la vista); a la derecha aleja. */
export function factorDeFechas(dx) {
  return factorDeArrastre(dx)
}

// ─── Los rótulos de los ejes, como TradingView (Nico, 29/10) ─────────────────
// · Precios: números redondos y parejos (…, 240, 260, 280, …) a lo largo de
//   toda la columna, uno cada ~56 px: con más alto, más rótulos.
// · Fechas: el detalle cambia con el zoom. Se rotula lo más fino que entra (un
//   rótulo cada ~80 px): años, trimestres, meses, quincenas, semanas o días. Cada
//   rótulo dice lo más grande que cambia ahí: «2026» al empezar el año, «mar»
//   al empezar el mes, y si no el número del día.

const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

/** Los precios redondos para la columna entre `lo` y `hi` (lo de abajo y lo de
 *  arriba de lo que se ve), para un gráfico de `altoPx` de alto. */
export function marcasDePrecio(lo, hi, altoPx, cadaPx = 56) {
  if (!(hi > lo) || !(altoPx > 0)) return []
  const cuantos = Math.max(2, Math.floor(altoPx / cadaPx))
  const crudo = (hi - lo) / cuantos
  const base = Math.pow(10, Math.floor(Math.log10(crudo)))
  const m = crudo / base
  const paso = (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * base
  const out = []
  // Redondeado al paso para no arrastrar 0,30000000000000004.
  const dec = Math.max(0, -Math.floor(Math.log10(paso)) + 2)
  for (let v = Math.ceil(lo / paso) * paso; v <= hi + paso * 1e-9 && out.length < 60; v += paso) {
    out.push(Number(v.toFixed(dec)))
  }
  return out
}

/** Los precios de la columna en la `escala` del gráfico: en lineal, los
 *  redondos parejos de `marcasDePrecio`; en logarítmica, los que se reparten
 *  multiplicando (utils/escalaPrecio.marcasLog), con un poco menos de lugar
 *  entre ellos porque no quedan a la misma distancia. */
export function marcasDePrecioEn(lo, hi, altoPx, escala, cadaPx = 56) {
  if (!esLog(escala)) return marcasDePrecio(lo, hi, altoPx, cadaPx)
  return marcasLog(lo, hi, altoPx, (a, b, alto) => marcasDePrecio(a, b, alto, cadaPx), cadaPx * 0.72)
}

// Qué cambia entre un día y el anterior, de lo más grande a lo más chico.
function cambio(antes, d) {
  if (!antes) return 'anio'
  if (antes.slice(0, 4) !== d.slice(0, 4)) return 'anio'
  const ma = Number(antes.slice(5, 7)), md = Number(d.slice(5, 7))
  if (ma !== md) return (md - 1) % 3 === 0 ? 'trimestre' : 'mes'
  const da = Number(antes.slice(8, 10)), dd = Number(d.slice(8, 10))
  if (da < 15 && dd >= 15) return 'quincena'
  const sem = (iso) => Math.floor((Date.parse(iso + 'T12:00:00Z') / 86400000 + 3) / 7)   // semanas desde un lunes
  if (sem(antes) !== sem(d)) return 'semana'
  return 'dia'
}
const NIVELES = ['anio', 'trimestre', 'mes', 'quincena', 'semana', 'dia']

/**
 * Los rótulos de la fila de fechas: [{ i, texto }] (`i`: el índice del punto).
 * `anchoPx`: el ancho de lo que ocupan los `puntos` en la pantalla.
 */
export function marcasDeFechas(puntos, anchoPx, cadaPx = 80) {
  if (!puntos?.length || !(anchoPx > 0)) return []
  const pxPorPunto = anchoPx / Math.max(1, puntos.length)
  const nivelDe = puntos.map((p, i) => (i === 0 ? null : NIVELES.indexOf(cambio(puntos[i - 1].d, p.d))))
  // El nivel más fino cuyos rótulos entran sin pisarse.
  let elegido = 0
  for (let n = 0; n < NIVELES.length; n++) {
    const idx = nivelDe.map((v, i) => (v != null && v <= n ? i : null)).filter(i => i != null)
    const minimo = idx.slice(1).reduce((m, i, k) => Math.min(m, (i - idx[k]) * pxPorPunto), Infinity)
    if (idx.length && minimo < cadaPx * 0.55) break
    elegido = n
    if (idx.length * cadaPx > anchoPx * 1.15) break
  }
  const out = []
  let ultimo = -Infinity
  for (let i = 1; i < puntos.length; i++) {
    const v = nivelDe[i]
    if (v == null || v > elegido) continue
    if ((i - ultimo) * pxPorPunto < cadaPx * 0.75) continue        // demasiado cerca del anterior
    const [y, m, d] = puntos[i].d.split('-')
    out.push({ i, texto: v === 0 ? y : v <= 2 ? MESES_CORTOS[Number(m) - 1] : String(Number(d)) })
    ultimo = i
  }
  return out
}

/** La fecha del día bajo el mouse, para la fila de abajo: «jue 29 oct '26». */
export function fechaDeLaMira(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  const dia = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'][new Date(Date.UTC(+y, +m - 1, +d)).getUTCDay()]
  return `${dia} ${Number(d)} ${MESES_CORTOS[Number(m) - 1]} '${y.slice(2)}`
}
