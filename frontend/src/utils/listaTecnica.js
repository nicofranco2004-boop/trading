// listaTecnica.js — «Tu lista, con su lectura técnica»: lo que tenés y lo que
// seguís (watchlist), juntos en una tabla (inicio → Watchlist → «Ver como tablero»).
// ════════════════════════════════════════════════════════════════════════════
// Nada se recalcula acá:
//   · los NÚMEROS técnicos vienen de POST /api/tecnico/lista (backend/tecnico.py,
//     la misma `lectura` que la ficha y la radiografía);
//   · las PALABRAS son las de la ficha: `tendencia` (la tarjeta «Largo plazo»),
//     la tarjeta «Corto plazo» de `tarjetas`, `veredictoRsi`, `fmtAdx` y la
//     línea de 23 del ADX (`ADX_CLAVE`);
//   · CUÁNTO PESA cada activo, con `valorPorActivo` de la radiografía y la
//     valuación de la Cartera (`valorDe`): el 12 % de acá es el 12 % de allá.
//   · el ÚLTIMO CAMBIO lo cuenta el servidor con `cambios_desde`, la cuenta
//     única de «qué cambió esta semana».
// Ninguna palabra habla del futuro ni dice qué hacer: describe cómo se movió.

import { inferType } from './tickers'
import { isCrypto } from './crypto'
import { hoyISO } from './fecha'
import { tarjetas, fmtAdx, ADX_CLAVE } from './tecnico'
import {
  activosParaLeer, clave, valorPorActivo, tendencia, fuerza, lecturaVieja, MOTIVOS_SIN_LECTURA,
} from './radiografia'

/**
 * Cómo se lee un símbolo de la watchlist, con la regla de la ficha para lo que
 * no tenés: una acción argentina (GGAL o GGAL.BA) se mira en BYMA ÷ MEP, no por
 * su ADR; un CEDEAR (AAPL.BA) por su acción de afuera; una cripto guardada con
 * '-USD' (BTC-USD) es la misma BTC que tenés. → { asset, local, simbolo }
 * (`asset` sin '.BA' ni '-USD': la clave con que la Cartera nombra el activo).
 */
export function lecturaDeSeguido(simbolo) {
  const s = String(simbolo || '').trim().toUpperCase()
  const local = inferType(s) === 'stock_ar'
  let asset = s.endsWith('.BA') ? s.slice(0, -3) : s
  if (asset.endsWith('-USD') && isCrypto(asset.slice(0, -4))) asset = asset.slice(0, -4)
  return { asset, local, simbolo: s }
}

// Lo que el servidor deja leer por pedido (tecnico.MAX_ACTIVOS_CARTERA).
export const MAX_POR_PEDIDO = 200

/** Lo que se le pide al servidor: tus activos (con su marca `local`, como la
 *  Cartera) y los que seguís, cada uno una vez. */
export function activosDeLaLista(lotes = [], seguidos = []) {
  const vistos = new Map(activosParaLeer(lotes).map(a => [clave(a.asset, a.local), a]))
  for (const it of seguidos) {
    const { asset, local } = lecturaDeSeguido(it?.symbol)
    if (asset && !vistos.has(clave(asset, local))) vistos.set(clave(asset, local), { asset, local })
  }
  return [...vistos.values()].sort((a, b) => clave(a.asset, a.local).localeCompare(clave(b.asset, b.local)))
}

/** Un lote de mentira para lo que seguís y no tenés: sólo para que «Sin
 *  lectura» diga bien por qué (un bono o un fondo no se miden). */
function loteDeSeguido(it, asset) {
  const tipo = String(it?.asset_type || '').toUpperCase()
  const inferido = inferType(asset)
  return { asset, asset_type: tipo || (inferido === 'bond' ? 'BONO' : inferido === 'fci' ? 'FCI' : null) }
}

const DIA = 86400000
const dias = (desde, hasta) => Math.round((Date.parse(hasta + 'T00:00:00Z') - Date.parse(desde + 'T00:00:00Z')) / DIA)

/** «hoy», «ayer», «hace 3 días», «hace 2 semanas», «hace 5 meses». */
export function haceCuanto(fecha, hoy = hoyISO()) {
  if (!fecha) return null
  const d = dias(fecha, hoy)
  if (d <= 0) return 'hoy'
  if (d === 1) return 'ayer'
  if (d < 14) return `hace ${d} días`
  if (d < 60) return `hace ${Math.floor(d / 7)} semanas`
  const m = Math.floor(d / 30)
  return m >= 12 ? 'hace un año' : `hace ${m} meses`
}

/** El cambio en palabras: las que manda la cuenta única (`texto`). */
export function textoDelCambio(c) {
  return c?.texto || null
}

/**
 * Las filas de la tabla. `lotes`: tus posiciones (efectivo incluido, para el
 * total); `valorDe(p)`: el valor en dólares de ese lote, el de la Cartera;
 * `extra`: los plazos fijos ({ nombre, valor }); `seguidos`: los ítems de
 * /watchlist; `indice`: clave → lectura del servidor. Cada fila:
 *   { clave, nombre, ruta, tenes, valor, peso (0–100), vigente, motivo,
 *     fondo, corto, rsi, adx, desdeMax, linea, cambio }
 * `vigente` false = «Sin lectura» (sin velas, bono/fondo o velas de hace más
 * de 10 días): esa fila no muestra números y `motivo` dice por qué.
 */
export function filasDeLaLista({ lotes = [], valorDe, extra = [], seguidos = [], indice, hoy = hoyISO() }) {
  const { porActivo, total } = valorPorActivo(lotes, valorDe, extra)
  const filas = new Map()
  const armar = (k, base) => {
    const x = indice?.get(k) || null
    const vigente = !!(x?.disponible && x.lectura && !lecturaVieja(x, hoy))
    const fondo = tendencia(x, hoy, base.p)
    const l = vigente ? x.lectura : null
    const corto = l ? tarjetas(l).find(t => t.id === 'corto') : null
    const linea = vigente && x.linea?.length > 1 ? x.linea : null
    const c = vigente ? x.ultimo_cambio : null
    filas.set(k, {
      ...base, clave: k, vigente,
      motivo: vigente ? null : fondo.motivo,
      porque: vigente ? null : fondo.porque,
      fondo,
      corto: corto ? { palabra: corto.veredicto, motivo: corto.texto } : null,
      rsi: vigente ? fuerza(x, hoy) : null,
      adx: l?.adx != null ? { valor: l.adx, texto: fmtAdx(l.adx), palabra: l.adx >= ADX_CLAVE ? 'marcada' : 'de costado' } : null,
      desdeMax: l?.dist_maximo_12m != null ? { pct: l.dist_maximo_12m, enMaximo: l.dist_maximo_12m >= -0.1, anioCompleto: !!l.anio_completo } : null,
      linea,
      cambio: c?.fecha ? { texto: textoDelCambio(c), fecha: c.fecha, hace: haceCuanto(c.fecha, hoy) } : null,
    })
  }
  for (const [k, a] of porActivo) {
    if (k === 'efectivo' || k.startsWith('extra:')) continue
    const asset = String(a.p.asset).toUpperCase()
    armar(k, { nombre: a.nombre, ruta: asset, tenes: true, valor: a.valor, peso: total > 0 ? (a.valor / total) * 100 : 0, p: a.p })
  }
  for (const it of seguidos) {
    const { asset, local, simbolo } = lecturaDeSeguido(it?.symbol)
    const k = clave(asset, local)
    if (!asset || filas.has(k)) continue
    armar(k, { nombre: isCrypto(asset) ? asset : simbolo, ruta: simbolo, tenes: false, valor: 0, peso: 0, p: loteDeSeguido(it, asset) })
  }
  return conDetalle([...filas.values()])
}

/** Dos filas con el mismo ticker (GGAL de IOL y el ADR GGAL de Schwab) son dos
 *  papeles distintos con dos lecturas: cada una dice dónde cotiza. */
function conDetalle(filas) {
  const base = (n) => n.replace(/\.BA$/, '')
  const cuantas = {}
  for (const f of filas) cuantas[base(f.nombre)] = (cuantas[base(f.nombre)] || 0) + 1
  return filas.map(f => (cuantas[base(f.nombre)] > 1
    ? { ...f, detalle: f.clave.endsWith('|1') ? 'en BYMA' : String(f.p?.asset_type).toUpperCase() === 'CEDEAR' ? 'CEDEAR' : 'en Nueva York' }
    : f))
}

/** Cuántas hay en cada filtro. «Watchlist» = lo que seguís y no tenés. */
export function contarFilas(filas) {
  const tenes = filas.filter(f => f.tenes).length
  return { todo: filas.length, tenes, watchlist: filas.length - tenes }
}

export const FILTROS = [
  { id: 'todo', label: 'Todo' },
  { id: 'tenes', label: 'Lo que tenés' },
  { id: 'watchlist', label: 'Watchlist' },
]

export function filtrarFilas(filas, filtro) {
  if (filtro === 'tenes') return filas.filter(f => f.tenes)
  if (filtro === 'watchlist') return filas.filter(f => !f.tenes)
  return filas
}

// Cada orden con su valor y su sentido de entrada (el que se lee primero).
// `desc`: de mayor a menor.
export const ORDENES = [
  { id: 'cambio', label: 'Lo último que cambió', valor: f => f.cambio?.fecha ?? null, desc: true },
  { id: 'fuerza', label: 'Fuerza (RSI)', valor: f => f.rsi?.rsi ?? null, desc: true },
  { id: 'maximo', label: 'Desde el máximo', valor: f => f.desdeMax?.pct ?? null, desc: true },
  { id: 'peso', label: 'Lo que más pesa', valor: f => (f.tenes ? f.peso : null), desc: true },
]

/**
 * Ordena por `por` (un id de ORDENES). `desc` null = el sentido de entrada de
 * ese orden. Lo que no tiene el dato va al final (en cualquier sentido) y las
 * filas «Sin lectura», al final de todo; los empates, por nombre.
 */
export function ordenarFilas(filas, por = 'cambio', desc = null) {
  const o = ORDENES.find(x => x.id === por) || ORDENES[0]
  const bajando = desc ?? o.desc
  return [...filas].sort((a, b) => {
    if (a.vigente !== b.vigente && por !== 'peso') return a.vigente ? -1 : 1
    const va = o.valor(a), vb = o.valor(b)
    if (va == null || vb == null) {
      if (va != null) return -1
      if (vb != null) return 1
      return a.nombre.localeCompare(b.nombre)
    }
    if (va === vb) return a.nombre.localeCompare(b.nombre)
    return (va < vb ? -1 : 1) * (bajando ? -1 : 1)
  })
}

/** El «por qué» de las filas sin lectura, agrupado como en la radiografía. */
export function motivosSinLectura(filas) {
  const por = {}
  for (const f of filas) if (!f.vigente) (por[f.porque] ||= []).push(f.nombre)
  return Object.keys(MOTIVOS_SIN_LECTURA).filter(k => por[k])
    .map(k => ({ porque: k, nombres: por[k], texto: MOTIVOS_SIN_LECTURA[k] }))
}

/** El trazo de la línea chica (ancho × alto en px). null si no hay línea. */
export function trazoDeLinea(linea, ancho = 64, alto = 22) {
  if (!linea || linea.length < 2) return null
  const cs = linea.map(p => p.c)
  const lo = Math.min(...cs), hi = Math.max(...cs)
  const rango = hi - lo || 1
  const x = (i) => (i / (linea.length - 1)) * ancho
  const y = (c) => alto - 1 - ((c - lo) / rango) * (alto - 2)
  const d = linea.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.c).toFixed(1)}`).join('')
  return { d, sube: cs[cs.length - 1] >= cs[0] }
}

