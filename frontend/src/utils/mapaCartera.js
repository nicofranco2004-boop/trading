// mapaCartera.js — «Mapa de tu cartera» del Panorama de Análisis técnico
// (lienzo «1 · Panorama», aprobado por Nico el 30/10): un cuadrito por activo,
// de tamaño proporcional a lo que pesa y pintado según su tendencia de largo
// plazo.
// ════════════════════════════════════════════════════════════════════════════
// Nada se calcula de nuevo acá:
//   · CUÁNTO PESA cada activo: el `peso` de las filas de Tu lista
//     (utils/listaTecnica.filasDeLaLista), que es `tenencias` de POST
//     /api/tecnico/lista = senales_semana.peso, LA misma cuenta del % alcista;
//   · la TENDENCIA: `fondo` de la misma fila (utils/radiografia.tendencia, la
//     tarjeta «Largo plazo» de la ficha con la regla de la lectura vieja), la
//     que usa el servidor para repartir el % (senales_semana._alcista);
//   · el EFECTIVO y los plazos fijos: el servidor los cuenta en el total (y en
//     «sin lectura» del %), pero no vienen como tenencia: son lo que falta para
//     llegar a 100 %.
//
// Con «Ocultar saldos» el TAMAÑO delataría cuánto pesa cada uno, y el ORDEN
// (de más a menos) cuál pesa más: todos iguales, en orden alfabético y sin %.

import { clave } from './radiografia'
import { polarityColor, CORTES_DIA, CORTES_PROMEDIO } from './polarityScale'
import { leer, guardar } from './almacen'
import { CATALOGO } from './catalogoDelAlmacen'

// ─── De qué se pinta cada cuadrito («Color por», Nico 30/10: «Sí, sumarlo») ──
// Tendencia de entrada (lo del lienzo del Panorama). «Hoy» y «Contra tu
// promedio» salen de GET /api/cartera/mapa-del-dia: el servidor los cuenta con
// LA cuenta de «qué se movió hoy» (main._lotes_del_dia, la misma del chat), el
// mismo par precio / cierre anterior que la «Var. día» de la Cartera.
export const MODOS = [
  { id: 'hoy', label: 'Hoy' },
  { id: 'tendencia', label: 'Tendencia' },
  { id: 'promedio', label: 'Contra tu promedio' },
]
export const MODO_DE_ENTRADA = 'tendencia'
/** El renglón de arriba del mapa, según el modo: cada término explicado. */
export const QUE_ES_EL_COLOR = {
  hoy: 'color = cuánto se movió hoy contra el cierre anterior',
  tendencia: 'color = tendencia de largo plazo',
  promedio: 'color = cuánto está arriba o abajo de lo que pagaste',
}

export function modoGuardado() {
  try {
    const m = leer(CATALOGO.mapaColor)
    return MODOS.some(x => x.id === m) ? m : MODO_DE_ENTRADA
  } catch { return MODO_DE_ENTRADA }
}
export function guardarModo(m) {
  try { guardar(CATALOGO.mapaColor, m) } catch { /* sin almacenamiento: dura la visita */ }
}

/**
 * «Contra tu promedio» de un activo en la moneda en que se mira. El servidor
 * manda los dos % (cartera_hoy.por_activo): `promedio_pct_ars` (en pesos: el
 * costo en los pesos que se pagaron, que es también la base «al dólar de hoy»)
 * y `promedio_pct_usd` (en dólares, al dólar de la compra). Se elige con la
 * regla de `noRealizadoEnVista` (utils/valuation): en pesos, o en dólares con
 * «costo al dólar de hoy», el de hoy; si no, el de la compra. Como
 * `pctEnMoneda`: si falta el de esta moneda NO cae al otro (sería un % en
 * pesos rotulado en dólares) y dice por qué. → { pct (fracción) | null, sinDato }
 */
export function promedioEnMoneda(a, { currency = 'USD', costBasis = 'purchase' } = {}) {
  const pct = currency === 'ARS' || costBasis === 'today' ? a?.promedio_pct_ars : a?.promedio_pct_usd
  if (pct != null) return { pct: pct / 100, sinDato: null }
  return { pct: null, sinDato: a?.promedio_sin_dato || null }
}

/**
 * Los cuadritos con lo del día de cada uno: `delDia.activos` del servidor
 * ([{asset, local, hoy: {pct, usd} | null, dia_txt, promedio_pct_ars,
 * promedio_pct_usd, promedio_sin_dato}], % en puntos) por la MISMA clave de Tu
 * lista (`clave(asset, local)`: GGAL de BYMA y el ADR son dos). → cada cuadrito
 * con `hoy` ({pct (fracción), usd} | null), `diaTxt`, `promedio` (fracción |
 * null, en la moneda de `moneda`: {currency, costBasis}) y `promedioSinDato`
 * (por qué no hay). El efectivo y «y N más» no tienen.
 */
export function conElDia(cuadritos = [], delDia = null, moneda = {}) {
  const por = new Map((delDia?.activos || []).map(a => [clave(String(a.asset).toUpperCase(), a.local), a]))
  return cuadritos.map(c => {
    const a = c.clave !== 'efectivo' && c.clave !== 'otros' ? por.get(c.clave) : null
    const prom = promedioEnMoneda(a, moneda)
    return {
      ...c,
      hoy: a?.hoy ? { pct: a.hoy.pct / 100, usd: a.hoy.usd } : null,
      diaTxt: a?.dia_txt || null,
      promedio: prom.pct,
      promedioSinDato: prom.sinDato,
    }
  })
}

const SIN_DATO = { bg: 'rgb(var(--bg-3))', ink: 'rgb(var(--ink-2))' }
/** El color de un cuadrito en «Hoy» o «Contra tu promedio» ({bg, ink} para
 *  `style`; sin dato, gris). En «Tendencia», null: van los tonos del lienzo. */
export function colorDelModo(c, modo) {
  if (modo === 'hoy') return c.hoy ? polarityColor(c.hoy.pct * 100, CORTES_DIA) : SIN_DATO
  if (modo === 'promedio') return c.promedio != null ? polarityColor(c.promedio * 100, CORTES_PROMEDIO) : SIN_DATO
  return null
}

/** Lo que más sumó y lo que más restó HOY, en plata (un +8 % de US$ 20 no le
 *  cambia el día a nadie), de TODOS los activos que tenés (no sólo los que
 *  entran con nombre en el mapa). `nombres`: clave → el nombre del cuadrito.
 *  → { sumo, resto }: cada uno { nombre, usd, pct (fracción) } o null. */
export function losExtremosDeHoy(delDia = null, nombres = new Map()) {
  let sumo = null, resto = null
  for (const a of delDia?.activos || []) {
    if (!a.hoy) continue
    const x = { nombre: nombres.get(clave(String(a.asset).toUpperCase(), a.local)) || a.asset,
                usd: a.hoy.usd, pct: a.hoy.pct / 100 }
    if (x.usd > 0 && (!sumo || x.usd > sumo.usd)) sumo = x
    if (x.usd < 0 && (!resto || x.usd < resto.usd)) resto = x
  }
  return { sumo, resto }
}

// Cuántos cuadritos con nombre propio; el resto va junto en «y N más».
export const MAX_CUADRITOS = 10
// Debajo de esto (en % de tu cartera) el efectivo no lleva cuadrito.
const EFECTIVO_MINIMO = 0.5
// La proporción del mapa (ancho : alto). La pantalla dibuja la caja con la
// misma, en compu y en celular, así los cuadritos se ven como se calcularon.
export const PROPORCION = 7 / 4

/**
 * Los cuadritos, de más a menos peso. `filas`: las de Tu lista (sólo cuentan
 * las que tenés); `sinLectura`: los nombres que el servidor puso en el grupo
 * «sin lectura» del % (para saber si el resto es efectivo, plazos fijos o los
 * dos). → [{ clave, nombre, ruta | null, peso (0–100) | null, tendencia:
 * 'alcista' | 'bajista' | 'sin' | 'otros', cuantos? }]
 */
export function cuadritosDelMapa(filas = [], { hidden = false, sinLectura = [] } = {}) {
  const tuyas = filas.filter(f => f.tenes && f.peso > 0)
  let out = tuyas.map(f => ({
    clave: f.clave, nombre: f.detalle ? `${f.nombre} ${f.detalle}` : f.nombre, ruta: f.ruta,
    peso: f.peso, tendencia: f.fondo?.id || 'sin',
  }))
  const resto = 100 - tuyas.reduce((s, f) => s + f.peso, 0)
  if (tuyas.length && resto >= EFECTIVO_MINIMO) {
    const efectivo = sinLectura.includes('efectivo'), pf = sinLectura.includes('plazos fijos')
    const nombre = efectivo && !pf ? 'Efectivo' : pf && !efectivo ? 'Plazos fijos' : 'Efectivo y plazos fijos'
    out.push({ clave: 'efectivo', nombre, ruta: null, peso: resto, tendencia: 'sin' })
  }
  if (hidden) {
    out = out.map(c => ({ ...c, peso: null })).sort((a, b) => a.nombre.localeCompare(b.nombre, 'es'))
  } else {
    out.sort((a, b) => b.peso - a.peso || a.nombre.localeCompare(b.nombre, 'es'))
  }
  if (out.length <= MAX_CUADRITOS) return out
  // Los que no entran, juntos en uno (sin color: tienen tendencias distintas).
  const vistos = out.slice(0, MAX_CUADRITOS - 1)
  const otros = out.slice(MAX_CUADRITOS - 1)
  return [...vistos, {
    clave: 'otros', nombre: `y ${otros.length} más`, ruta: null, tendencia: 'otros', cuantos: otros.length,
    peso: hidden ? null : otros.reduce((s, c) => s + c.peso, 0),
  }]
}

/**
 * Qué hay en lo que falta para 100 %: los nombres del grupo «sin lectura» que
 * no son tenencias, con `sin_medir` de POST /api/tecnico/lista (senales_semana.
 * pesos_sin_medir, el mismo pedido de las filas). → ['efectivo', 'plazos fijos']
 * o parte; [] si no vino.
 */
export function sinLecturaDe(sinMedir) {
  if (!sinMedir) return []
  return [sinMedir.efectivo > 0 && 'efectivo', sinMedir.plazos_fijos > 0 && 'plazos fijos'].filter(Boolean)
}

/**
 * Dónde va cada cuadrito: el método «squarified» (Bruls, Huizing y van Wijk),
 * que arma rectángulos lo más cuadrados posible con el área proporcional al
 * valor. `valores` de más a menos; con `null` (ocultar saldos) todos valen lo
 * mismo. → [{ x, y, w, h }] en % de la caja, en el mismo orden.
 */
export function ubicarCuadritos(valores, proporcion = PROPORCION) {
  const n = valores.length
  if (!n) return []
  const vs = valores.map(v => (v == null || !(v > 0) ? 1 : v))
  const total = vs.reduce((s, v) => s + v, 0)
  // Se trabaja en una caja de `proporcion` × 1 y al final se pasa a %.
  const W = proporcion, H = 1
  const areas = vs.map(v => (v / total) * W * H)
  const rects = new Array(n)
  let caja = { x: 0, y: 0, w: W, h: H }
  let i = 0
  const peor = (fila, lado) => {
    const s = fila.reduce((a, b) => a + b, 0)
    const max = Math.max(...fila), min = Math.min(...fila)
    return Math.max((lado * lado * max) / (s * s), (s * s) / (lado * lado * min))
  }
  while (i < n) {
    const lado = Math.min(caja.w, caja.h)
    const fila = [areas[i]]
    let j = i + 1
    while (j < n && peor([...fila, areas[j]], lado) <= peor(fila, lado)) { fila.push(areas[j]); j++ }
    const s = fila.reduce((a, b) => a + b, 0)
    if (caja.w >= caja.h) {
      // Una columna a la izquierda, de arriba a abajo.
      const ancho = s / caja.h
      let y = caja.y
      fila.forEach((a, k) => { const alto = a / ancho; rects[i + k] = { x: caja.x, y, w: ancho, h: alto }; y += alto })
      caja = { x: caja.x + ancho, y: caja.y, w: caja.w - ancho, h: caja.h }
    } else {
      // Una fila arriba, de izquierda a derecha.
      const alto = s / caja.w
      let x = caja.x
      fila.forEach((a, k) => { const ancho = a / alto; rects[i + k] = { x, y: caja.y, w: ancho, h: alto }; x += ancho })
      caja = { x: caja.x, y: caja.y + alto, w: caja.w, h: caja.h - alto }
    }
    i = j
  }
  return rects.map(r => ({ x: (r.x / W) * 100, y: (r.y / H) * 100, w: (r.w / W) * 100, h: (r.h / H) * 100 }))
}
