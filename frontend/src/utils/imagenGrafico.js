// imagenGrafico — lo que lleva la imagen del gráfico técnico para compartir.
// ════════════════════════════════════════════════════════════════════════════
// El botón «Compartir» del gráfico de la ficha (LecturaTecnica.jsx) arma una
// imagen para mandar por WhatsApp con lo que se está mirando: las mismas velas
// (el período y la temporalidad que se ven), la misma escala de precios
// (también si se estiró a mano), las capas prendidas y TUS dibujos en su
// color. Se arma desde los DATOS, no fotografiando la pantalla: la cuenta de
// dónde va cada cosa es la del gráfico (trazosDeDibujos, trazosDelFibonacci,
// marcasDePrecio…), en lugares de 0 a 100, y utils/shareCard.js la pinta en el
// canvas (pintarGrafico), oscura siempre (R8: el canvas no resuelve var()).
//
// Privacidad: la imagen NO lleva nada de tu cartera. Esta función ni siquiera
// recibe tu precio promedio, tus compras y ventas, tus montos ni tus avisos:
// sólo el precio, los indicadores y tus dibujos. Tampoco lo que es de un
// momento (lo que estás midiendo, el dibujo elegido, el globo del mouse). Ni
// tus NOTAS (lo que escribiste: «compré acá por…») ni tu tesis: son
// personales. La tesis ni llega acá; las notas viajan con tus dibujos y se
// sacan acá abajo (`tuyos`), que es el único lugar por donde pasa la imagen.

import { indiceDeFecha, velaCompleta, ADX_CLAVE, RSI_CASTIGADO, RSI_ESTIRADO } from './tecnico'
import { marcasDeFechas, marcasDePrecio } from './ejesGrafico'
import { extensionFibonacci, fibonacciAMano, nivelPct, rayas, rotuloNivel, rotulosQueEntran } from './fibonacci'
import { rotuloOnda } from './elliott'
import { etiquetasDe } from './dibujos'
import { PRIORIDAD, rotuloCorteFib, rotuloInvalidaElliott } from './rotulos'
import { fechaDeHoy } from './shareCard'
import { colorDe, trazosDeDibujos } from '../components/asset/CapaDibujos'
import { posicion, trazosDelFibonacci } from '../components/asset/CapaFibonacci'

// Con cuánto aire se eligen los precios del costado y las fechas de abajo en
// la imagen: su letra es más grande que la de la pantalla (se mira achicada en
// un celular), así que entran menos.
const PX_ALTO_NOMINAL = 600
const PX_POR_PRECIO = 95
const PX_POR_FECHA = 120
/** El ancho del gráfico en la imagen, en px (shareCard.pintarGrafico: 1080 − 2 × 72 − 118). */
export const ANCHO_DEL_GRAFICO = 818
// Dos balances o dividendos a menos de esto (en % del ancho) van en una marca.
const MARCAS_JUNTAS = 5

const fechaCorta = (iso) => {
  if (!iso) return ''
  const [y, m, d] = iso.split('-')
  return `${d}/${m}/${y.slice(2)}`
}
const pctTexto = (x) => `${x > 0 ? '+' : x < 0 ? '−' : ''}${Math.abs(x * 100).toLocaleString('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`

/**
 * El spec de la imagen ({ kind: 'grafico', … }) o null si no hay precios.
 *
 * @param {object} a
 * @param {string} a.activo     el ticker («AAPL»)
 * @param {string} a.moneda     'usd' | 'ars'
 * @param {Array}  a.puntos     las velas que se ven (ya semanales si son semanales)
 * @param {number} a.huecos     los lugares vacíos de la derecha (el aire hacia el futuro)
 * @param {number} a.lo, a.hi   la escala de precios de la pantalla (abajo y arriba)
 * @param {object} a.ver        las capas prendidas (BarraGrafico)
 * @param {Array}  a.dibujos    tus dibujos, ya ubicados en lo que se ve (con `k`)
 * @param {Function} a.precio   formatea un precio como la ficha («US$ 1,23»)
 * @param {object} a.colores    los colores del gráfico (`rgb(var(--x))`, los de la pantalla)
 * @param {string} a.ultimaFecha el último día con precio (si lo que se ve termina antes, el precio grande dice de qué día es)
 * @param {Function} a.amontonados (eventos, pctX) → true si los dividendos se pisarían (la regla de la pantalla)
 */
export function specDelGrafico({
  activo, moneda = 'usd', puntos = [], huecos = 0, lo, hi, ver = {}, tipo = 'linea', semanales = false,
  dibujos = [], fibonacci = null, elliott = null, eventos = [], convertida = null, fechaDatos = null, ultimaFecha = null,
  precio = (x) => String(x), colores = {}, volAlto = 0.15, adxTope = 50, squeeze = {}, amontonados = null, now = new Date(),
}) {
  if (!puntos?.length || !(puntos[puntos.length - 1]?.c > 0)) return null
  // La escala: la de la pantalla. Sin ella (no debería pasar), los cierres con aire.
  if (!(Number.isFinite(lo) && Number.isFinite(hi) && hi > lo)) {
    const cs = puntos.map(p => p.c).filter(c => c > 0)
    const a = Math.min(...cs), b = Math.max(...cs)
    const m = (b - a) * 0.08 || b * 0.02 || 1
    lo = a - m; hi = b + m
  }
  const lugares = puntos.length + Math.max(0, huecos || 0)
  const pctX = (i) => (lugares > 1 ? (i / (lugares - 1)) * 100 : 50)
  const pctY = (val) => (1 - (val - lo) / (hi - lo)) * 100
  const conVelas = tipo === 'velas'
  const anchoLugar = 100 / Math.max(lugares, 1)

  // Una serie de los puntos como tramos seguidos (se corta donde falta el dato).
  const serie = (k, y = pctY) => {
    const tramos = []
    let actual = null
    puntos.forEach((p, i) => {
      if (p[k] == null) { actual = null; return }
      if (!actual) { actual = []; tramos.push(actual) }
      actual.push([pctX(i), y(p[k])])
    })
    return tramos.filter(t => t.length > 1)
  }

  const lineas = []
  const poligonos = []
  const trazos = []
  const rotulos = []
  const puntitos = []
  const leyenda = []

  // ── El precio: velas o línea (con su área) ──────────────────────────────
  let velas = []
  let area = null
  if (conVelas) {
    let pc = null
    velas = puntos.map((p, i) => {
      const v = velaCompleta(p, pc)
      pc = p.c
      return { x: pctX(i), o: pctY(v.o), c: pctY(v.c), h: pctY(v.h), l: pctY(v.l), sube: v.c >= v.o }
    })
  } else {
    area = serie('c')
  }

  // ── Volumen, abajo de todo (la franja de `volAlto` del alto) ────────────
  let volumen = []
  if (ver.vol) {
    const maxVol = Math.max(0, ...puntos.map(p => p.v || 0))
    if (maxVol > 0) {
      volumen = puntos.map((p, i) => {
        if (!(p.v > 0)) return null
        const antes = i > 0 ? puntos[i - 1].c : null
        const v = velaCompleta(p, antes)
        const sube = conVelas ? v.c >= v.o : (antes == null || p.c >= antes)
        return { x: pctX(i), y: 100 - (p.v / maxVol) * volAlto * 100, sube }
      }).filter(Boolean)
      leyenda.push({ nombre: 'Volumen', color: colores.sube, forma: 'barra' })
    }
  }

  // ── Bandas, promedios ───────────────────────────────────────────────────
  if (ver.bb && puntos.some(p => p.bb_arriba != null && p.bb_abajo != null)) {
    let tramo = []
    const cerrar = () => {
      if (tramo.length > 1) {
        poligonos.push({ color: colores.bandas, alpha: 0.06,
          puntos: [...tramo.map(i => [pctX(i), pctY(puntos[i].bb_arriba)]), ...[...tramo].reverse().map(i => [pctX(i), pctY(puntos[i].bb_abajo)])] })
      }
      tramo = []
    }
    puntos.forEach((p, i) => { if (p.bb_arriba != null && p.bb_abajo != null) tramo.push(i); else cerrar() })
    cerrar()
    for (const k of ['bb_arriba', 'bb_abajo']) for (const t of serie(k)) lineas.push({ puntos: t, color: colores.bandas, ancho: 1.6, alpha: 0.75 })
    leyenda.push({ nombre: 'Bandas de Bollinger', color: colores.bandas, forma: 'banda' })
  }
  if (ver.s200 && puntos.some(p => p.s200 != null)) {
    for (const t of serie('s200')) lineas.push({ puntos: t, color: colores.media200, ancho: 4 })
    leyenda.push({ nombre: 'Promedio 200 días', color: colores.media200, forma: 'linea' })
  }
  if (ver.s50 && puntos.some(p => p.s50 != null)) {
    for (const t of serie('s50')) lineas.push({ puntos: t, color: colores.media50, ancho: 2.6 })
    leyenda.push({ nombre: 'Promedio 50 días', color: colores.media50, forma: 'linea' })
  }

  // ── El Fibonacci automático (CapaFibonacci) ─────────────────────────────
  if (ver.fib && fibonacci) {
    const antes = trazos.length
    const colorFib = colores.fibonacci
    if (fibonacci.disponible) {
      const p0 = posicion(puntos, fibonacci.desde.fecha)
      if (p0.donde !== 'despues') {
        const x0 = p0.donde === 'adentro' ? pctX(p0.i) : 0
        const lista = rayas(fibonacci)
        const tops = lista.map(r => pctY(r.precio))
        const conRotulo = rotulosQueEntran(lista, tops, fibonacci.entre)
        if (fibonacci.entre) {
          const [a, b] = fibonacci.entre
          const ya = pctY(lista.find(r => r.nivel === a).precio), yb = pctY(lista.find(r => r.nivel === b).precio)
          poligonos.push({ color: colorFib, alpha: 0.1, puntos: [[x0, ya], [100, ya], [100, yb], [x0, yb]] })
        }
        lista.forEach((r, k) => {
          trazos.push({ x1: x0, y1: tops[k], x2: 100, y2: tops[k], color: colorFib, ancho: 2, punteada: !r.extremo, alpha: r.extremo ? 0.9 : 0.7 })
          if (conRotulo.has(k)) rotulos.push(rotuloDeRaya(x0, tops[k], `${rotuloNivel(r.nivel, fibonacci.dir)} · ${precio(r.precio)}`, colorFib, PRIORIDAD.nivelFib))
        })
        const p1 = posicion(puntos, fibonacci.hasta.fecha)
        if (p0.donde === 'adentro' && p1.donde === 'adentro') {
          trazos.push({ x1: x0, y1: pctY(fibonacci.desde.precio), x2: pctX(p1.i), y2: pctY(fibonacci.hasta.precio), color: colorFib, ancho: 5, alpha: 0.85 })
          puntitos.push({ x: x0, y: pctY(fibonacci.desde.precio), color: colorFib }, { x: pctX(p1.i), y: pctY(fibonacci.hasta.precio), color: colorFib })
        }
      }
    } else if (fibonacci.en_curso) {
      // Sin tramo medido: la raya del cierre que daría por terminado el tramo vivo.
      const e = fibonacci.en_curso
      const t = trazosDelFibonacci(fibonacci, puntos, pctX, pctY)[0]
      if (t) {
        const suba = e.dir === 'suba'
        const corte = suba ? e.se_rompe_si_cierra.debajo_de : e.se_rompe_si_cierra.encima_de
        trazos.push({ ...t, color: colorFib, ancho: 2.5, punteada: true })
        rotulos.push({ x: t.x1 < 70 ? t.x1 : 100, y: t.y1, ancla: t.x1 < 70 ? 'izq' : 'der', vertical: suba ? 'abajo' : 'arriba',
          // El texto de la pantalla, como posibilidad (D2: una sola función).
          texto: rotuloCorteFib(suba, precio(corte)), borde: colorFib, prioridad: PRIORIDAD.corteFib })
      }
    }
    if (trazos.length > antes) leyenda.push({ nombre: 'Fibonacci automático', color: colorFib, forma: 'punteada' })
  }

  // ── Las ondas de Elliott automáticas (CapaElliott) ──────────────────────
  if (ver.ell && elliott?.disponible) {
    const c = elliott.principal
    const colorEll = colores.elliott
    const pos = c.ondas.map(o => ({ ...o, p: posicion(puntos, o.fecha) }))
    if (pos.some(o => o.p.donde === 'adentro')) {
      // Los tramos entre dos ondas que se ven (punteados los de la corrección
      // A-B-C) y las rayas de «dejaría de valer», como en la pantalla.
      for (let k = 1; k < pos.length; k++) {
        const a = pos[k - 1], b = pos[k]
        if (a.p.donde !== 'adentro' || b.p.donde !== 'adentro') continue
        trazos.push({ x1: pctX(a.p.i), y1: pctY(a.precio), x2: pctX(b.p.i), y2: pctY(b.precio), color: colorEll, ancho: 3, punteada: /^[ABC]$/.test(b.onda), alpha: 0.85 })
      }
      const xInv = pos[0].p.donde === 'adentro' ? pctX(pos[0].p.i) : 0
      ;[c.invalida, c.invalida.otro].filter(Boolean).forEach(r => {
        const y = pctY(r.precio)
        if (y < 0 || y > 100) return
        trazos.push({ x1: xInv, y1: y, x2: 100, y2: y, color: colorEll, ancho: 2.2, punteada: true, alpha: 0.8 })
        rotulos.push({ x: xInv < 60 ? xInv : 100, y, ancla: xInv < 60 ? 'izq' : 'der', vertical: r.lado === 'debajo' ? 'abajo' : 'arriba',
          texto: rotuloInvalidaElliott(precio(r.precio)), borde: colorEll, prioridad: PRIORIDAD.invalidaElliott })
      })
      for (const o of pos) {
        if (o.p.donde !== 'adentro') continue
        const r = rotuloOnda(o)
        const x = pctX(o.p.i), y = pctY(o.precio)
        if (!r) { puntitos.push({ x, y, color: colorEll }); continue }
        rotulos.push({ x, y, ancla: 'centro', vertical: o.tipo === 'pico' ? 'arriba' : 'abajo', texto: String(o.onda), borde: colorEll, forma: 'circulo', prioridad: PRIORIDAD.onda })
      }
      leyenda.push({ nombre: 'Ondas de Elliott', color: colorEll, forma: 'linea' })
    }
  }

  // ── Tus dibujos, en su color (CapaDibujos) ──────────────────────────────
  // Sin `extendidos`: la línea que sigue punteada es la de un AVISO tuyo, y
  // tus avisos no van en la imagen.
  // Las notas no: son lo que escribiste (ver arriba, «Privacidad»).
  const tuyos = dibujos.filter(d => d && d.tipo !== 'nota')
  for (const d of tuyos.filter(d => d.tipo === 'canal')) {
    poligonos.push({ color: colorDe(d), alpha: 0.08,
      puntos: [[d.a.k, d.a.precio], [d.b.k, d.b.precio], [d.b.k, d.b.precio + d.ancho], [d.a.k, d.a.precio + d.ancho]].map(([k, p]) => [pctX(k), pctY(p)]) })
  }
  for (const t of trazosDeDibujos(tuyos, pctX, pctY, [])) {
    trazos.push({ x1: t.x1, y1: t.y1, x2: t.x2, y2: t.y2, color: t.color, ancho: t.nivel || t.medio ? 2 : 4,
      punteada: !!(t.correccion || (t.nivel && !t.nivel.extremo)), alpha: t.nivel ? 0.85 : 1 })
  }
  for (const d of tuyos) {
    const color = colorDe(d)
    if (d.tipo === 'fibonacci') {
      const fib = fibonacciAMano(d.a.precio, d.b.precio)
      const lista = rayas(fib)
      const tops = lista.map(r => pctY(r.precio))
      const conRotulo = rotulosQueEntran(lista, tops, null)
      const x0 = Math.min(pctX(d.a.k), pctX(d.b.k))
      lista.forEach((r, k) => { if (conRotulo.has(k)) rotulos.push(rotuloDeRaya(x0, tops[k], `${rotuloNivel(r.nivel, fib.dir)} · ${precio(r.precio)}`, color, PRIORIDAD.nivelFib)) })
    } else if (d.tipo === 'extension' && d.c) {
      const lista = extensionFibonacci(d.a.precio, d.b.precio, d.c.precio).map(n => ({ ...n, extremo: n.nivel === 0 || n.nivel === 1 }))
      const tops = lista.map(n => pctY(n.precio))
      const conRotulo = rotulosQueEntran(lista, tops, null)
      const x0 = pctX(d.c.k)
      lista.forEach((n, k) => { if (conRotulo.has(k)) rotulos.push(rotuloDeRaya(x0, tops[k], `${nivelPct(n.nivel)} · ${precio(n.precio)}`, color, PRIORIDAD.nivelFib)) })
    } else if (d.tipo === 'elliott') {
      const etiquetas = etiquetasDe(d.forma)
      d.puntos.forEach((p, k) => {
        const x = pctX(p.k), y = pctY(p.precio)
        if (!etiquetas[k]) { puntitos.push({ x, y, color }); return }
        const vecino = d.puntos[k === 0 ? 1 : k - 1]
        const pico = vecino ? p.precio >= vecino.precio : true
        rotulos.push({ x, y, ancla: 'centro', vertical: pico ? 'arriba' : 'abajo', texto: etiquetas[k], borde: color, forma: 'circulo', prioridad: PRIORIDAD.onda })
      })
    }
  }
  // La referencia, sólo con los que se ven (uno fuera de la vista no se dibuja).
  const aLaVista = trazosDeDibujos(tuyos, pctX, pctY, []).filter(cruzaLaVista)
  const vistos = tuyos.filter(d => aLaVista.some(t => t.id === d.id))
  if (vistos.length) leyenda.push({ nombre: vistos.length === 1 ? 'Tu dibujo' : 'Tus dibujos', color: colorDe(vistos[0]), forma: 'linea' })

  // ── La columna de precios y la fila de fechas ───────────────────────────
  const ultimo = puntos[puntos.length - 1]
  const penultimo = puntos[puntos.length - 2]
  const colorDelDia = !penultimo || ultimo.c === penultimo.c ? colores.precio : ultimo.c > penultimo.c ? colores.positivo : colores.negativo
  const sinUS = (x) => precio(x).replace(/^US\$ /, '')
  const ticks = marcasDePrecio(lo, hi, PX_ALTO_NOMINAL, PX_POR_PRECIO)
  const enteros = ticks.every(t => Number.isInteger(t))
  const eje = ticks.map(t => ({ y: pctY(t), texto: enteros ? t.toLocaleString('es-AR') : sinUS(t) })).filter(t => t.y >= 0 && t.y <= 100)
  // Las etiquetas de color del costado: el último precio y tus horizontales.
  const etiquetas = [{ y: pctY(ultimo.c), texto: sinUS(ultimo.c), color: colorDelDia, principal: true },
    ...tuyos.filter(d => d.tipo === 'horizontal').map(d => ({ y: pctY(d.precio), texto: sinUS(d.precio), color: colorDe(d) }))]
    .filter(e => e.y >= 0 && e.y <= 100)
  const anchoDias = (ANCHO_DEL_GRAFICO * puntos.length) / Math.max(lugares, 1)
  const fechas = marcasDeFechas(puntos, anchoDias, PX_POR_FECHA).map(m => ({ x: pctX(m.i), texto: m.texto }))

  // ── Balances y dividendos de la empresa (no son tuyos) ──────────────────
  const marcas = []
  if (ver.eventos) {
    const hasta = ultimo.d
    const visibles = eventos
      .filter(e => e.fecha >= puntos[0].d && e.fecha <= hasta)
      .map(e => ({ ...e, i: indiceDeFecha(puntos, e.fecha) }))
      .filter(e => e.i != null)
      .sort((a, b) => a.i - b.i)
    const sinDividendos = !!amontonados?.(visibles, pctX)
    for (const e of visibles.filter(e => !sinDividendos || e.tipo !== 'dividendo')) {
      const x = pctX(e.i)
      const previa = marcas[marcas.length - 1]
      if (previa && x - previa.x0 < MARCAS_JUNTAS) {
        previa.cuantos++
        if (previa.tipo !== e.tipo) previa.tipo = 'mixto'
        previa.x = (previa.x0 + x) / 2
      } else marcas.push({ x0: x, x, tipo: e.tipo, cuantos: 1 })
    }
    if (marcas.length) leyenda.push({ nombre: 'Balances (B) y dividendos (D)', color: colores.balance, forma: 'letra' })
  }

  // ── Los paneles de abajo: RSI y fuerza de la tendencia ──────────────────
  let rsi = null
  if (ver.rsi !== false && puntos.some(p => p.rsi != null)) {
    rsi = { lineas: serie('rsi', r => 100 - r), niveles: [RSI_ESTIRADO, RSI_CASTIGADO].map(n => ({ y: 100 - n, texto: String(n) })),
      ultimo: ultimo.rsi != null ? { y: 100 - ultimo.rsi, texto: String(Math.round(ultimo.rsi)) } : null, color: colores.precio }
  }
  let fuerza = null
  const conAdx = puntos.filter(p => p.adx != null)
  const conSq = puntos.filter(p => p.squeeze != null)
  if (ver.fuerza !== false && (conAdx.length || conSq.length)) {
    const tope = Math.max(adxTope, ...conAdx.map(p => p.adx))
    const yAdx = (a) => 100 - (a / tope) * 100
    const maxSq = Math.max(...conSq.map(p => Math.abs(p.squeeze)), 0) || 1
    fuerza = {
      lineas: serie('adx', yAdx), clave: { y: yAdx(ADX_CLAVE), texto: String(ADX_CLAVE) }, color: colores.precio,
      barras: puntos.map((p, i) => {
        if (!p.squeeze || !squeeze[p.squeeze_color]) return null
        const [color, alpha] = squeeze[p.squeeze_color]
        const alto = Math.max((Math.abs(p.squeeze) / maxSq) * 46, 0.5)
        return { x: pctX(i), y: p.squeeze > 0 ? 50 - alto : 50, alto, color, alpha }
      }).filter(Boolean),
    }
  }

  // ── Los textos ──────────────────────────────────────────────────────────
  const desde = puntos[0].d
  const cambio = puntos[0].c > 0 ? ultimo.c / puntos[0].c - 1 : null
  const pie = [
    fechaDatos ? `Datos al cierre del ${fechaCorta(fechaDatos)}.` : null,
    convertida === 'mep' ? (moneda === 'usd'
      ? 'El precio en pesos de cada día está pasado a dólares con el MEP de ese día.'
      : 'El precio en dólares de cada día está pasado a pesos con el MEP de ese día.') : null,
    'Muestra cómo se movió el precio: no es una recomendación para comprar ni vender.',
  ].filter(Boolean)

  return {
    kind: 'grafico',
    activo: String(activo || '').toUpperCase(),
    subtitulo: `${conVelas ? (semanales ? 'Velas semanales' : 'Velas diarias') : 'Línea'} · del ${fechaCorta(desde)} al ${fechaCorta(ultimo.d)} · en ${moneda === 'ars' ? 'pesos' : 'dólares'}`,
    // Mirando el pasado (arrastrado o acercado), el precio grande no es el de
    // hoy: dice de qué día es.
    precio: { texto: precio(ultimo.c), ...((ultimaFecha || fechaDatos) > ultimo.d ? { fecha: `Cierre del ${fechaCorta(ultimo.d)}` } : {}) },
    cambio: cambio == null ? null : { texto: `${pctTexto(cambio)} en el período`, tono: cambio > 0 ? 'green' : cambio < 0 ? 'red' : 'gray' },
    leyenda,
    grafico: {
      anchoVela: anchoLugar * 0.65, area, velas, volumen, lineas, poligonos, trazos, rotulos, puntitos, eje, etiquetas,
      precio: colores.precio, sube: colores.sube, baja: colores.baja, grilla: colores.grilla,
    },
    fechas,
    marcas: marcas.map(m => ({ x: m.x, letra: m.tipo === 'balance' ? 'B' : m.tipo === 'dividendo' ? 'D' : 'B·D', cuantos: m.cuantos,
      color: m.tipo === 'dividendo' ? colores.dividendo : colores.balance })),
    rsi,
    fuerza,
    pie,
    date: `Hecho con Rendi el ${fechaDeHoy(now)}`,
  }
}

// ¿La raya pasa por lo que se ve (el cuadro de 0 a 100)? Recorte de Liang-Barsky.
function cruzaLaVista({ x1, y1, x2, y2 }) {
  let t0 = 0, t1 = 1
  const dx = x2 - x1, dy = y2 - y1
  for (const [p, q] of [[-dx, x1], [dx, 100 - x1], [-dy, y1], [dy, 100 - y1]]) {
    if (p === 0) { if (q < 0) return false; continue }
    const r = q / p
    if (p < 0) t0 = Math.max(t0, r)
    else t1 = Math.min(t1, r)
  }
  return t0 <= t1
}

// El rótulo de un nivel (de un Fibonacci): adentro, arriba de la raya, si la
// raya arranca en la primera mitad; si no, afuera, a la izquierda de donde arranca.
function rotuloDeRaya(x0, y, texto, borde, prioridad) {
  const adentro = x0 < 45
  return { x: Math.max(0, x0), y, ancla: adentro ? 'izq' : 'der', vertical: adentro ? 'arriba' : 'medio', texto, borde, prioridad }
}

/** El nombre del archivo: «aapl-grafico-2026-10-29.png». */
export function archivoDelGrafico(activo, now = new Date()) {
  const dia = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const t = String(activo || 'grafico').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'grafico'
  return `${t}-grafico-${dia}.png`
}
