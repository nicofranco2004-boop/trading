// listaTecnica.js — «Tu lista, con su lectura técnica»: lo que tenés y lo que
// seguís (watchlist), juntos en una tabla (inicio → Watchlist → «Ver como tablero»).
// ════════════════════════════════════════════════════════════════════════════
// Nada se recalcula acá:
//   · los NÚMEROS técnicos vienen de POST /api/tecnico/lista (backend/tecnico.py,
//     la misma `lectura` que la ficha y la radiografía);
//   · las PALABRAS son las de la ficha: `tendencia` (la tarjeta «Largo plazo»),
//     la tarjeta «Corto plazo» de `tarjetas`, `veredictoRsi`, `fmtAdx` y la
//     línea de 23 del ADX (`ADX_CLAVE`);
//   · CUÁNTO PESA cada activo y QUÉ tenés: lo manda el servidor (`tenencias`
//     de POST /api/tecnico/lista, con la valuación de senales_semana.cartera,
//     LA misma del % alcista y de la pestaña Señales): el 12 % de Tu lista es
//     el 12 % de Señales.
//   · el ÚLTIMO CAMBIO lo cuenta el servidor con `cambios_desde`, la cuenta
//     única de «qué cambió esta semana».
// Ninguna palabra habla del futuro ni dice qué hacer: describe cómo se movió.

import { inferType } from './tickers'
import { esLocalSinTenencia } from './accionLocal'
import { isCrypto } from './crypto'
import { hoyISO } from './fecha'
import { tarjetas, fmtAdx, ADX_CLAVE } from './tecnico'
import { fciLabel } from './valuation'
import { clave, tendencia, fuerza, lecturaVieja, MOTIVOS_SIN_LECTURA } from './radiografia'

/**
 * Cómo se lee un símbolo de la watchlist, con la regla de la ficha para lo que
 * no tenés: una acción argentina (GGAL o GGAL.BA) se mira en BYMA ÷ MEP, no por
 * su ADR; un CEDEAR (AAPL.BA) por su acción de afuera; una cripto guardada con
 * '-USD' (BTC-USD) es la misma BTC que tenés. → { asset, local, simbolo }
 * (`asset` sin '.BA' ni '-USD': la clave con que la Cartera nombra el activo).
 * `tipo`: el `asset_type` de la fila, si lo trae. Uno que no es de acción
 * argentina manda sobre la lista: «AGRO» de tipo STOCK es Adecoagro de Nueva
 * York, no Agrometal. Espejo de backend/accion_local.seguido (misma tabla de
 * casos: fixtures/accionLocal.json).
 */
export function lecturaDeSeguido(simbolo, tipo = null) {
  const s = String(simbolo || '').trim().toUpperCase()
  const local = esLocalSinTenencia(s, tipo)
  let asset = s.endsWith('.BA') ? s.slice(0, -3) : s
  if (asset.endsWith('-USD') && isCrypto(asset.slice(0, -4))) asset = asset.slice(0, -4)
  return { asset, local, simbolo: s }
}

// Lo que el servidor deja leer por pedido (tecnico.MAX_ACTIVOS_CARTERA). La
// watchlist tiene tope de 100 (main.WATCHLIST_TOPE): entra en uno.
export const MAX_POR_PEDIDO = 200

/** Lo que se le pide al servidor: lo que seguís, cada uno una vez, con la marca
 *  `local` de la ficha. Lo que TENÉS lo pone el servidor (sus `tenencias`). */
export function activosDeLaLista(seguidos = []) {
  const vistos = new Map()
  for (const it of seguidos) {
    const { asset, local } = lecturaDeSeguido(it?.symbol, it?.asset_type)
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

/**
 * El cambio en palabras, las que manda el servidor (`senales_semana.texto_del_cambio`,
 * las mismas de «Tus señales» y del mail de los sábados). En la celda va la
 * frase hasta los dos puntos («Pasó arriba de su promedio de 200 días»); la
 * entera, con su aclaración (`extra`), en el globo. null sin texto.
 */
export function textoDelCambio(c) {
  if (!c?.texto) return null
  const mayus = (t) => t.charAt(0).toUpperCase() + t.slice(1)
  const corta = c.texto.split(':')[0].replace(/\.$/, '')
  return { corta: mayus(corta), completa: [mayus(c.texto), c.extra].filter(Boolean).join(' '), tono: c.tono || null }
}

/**
 * Las filas de la tabla. `tenencias`: lo que tenés y cuánto pesa, como lo manda
 * el servidor ([{ asset, local, peso (fracción), tipo }], de más a menos);
 * `seguidos`: los ítems de /watchlist; `indice`: clave → lectura del servidor.
 * Cada fila:
 *   { clave, nombre, ruta, tenes, peso (0–100), vigente, motivo,
 *     fondo, corto, rsi, adx, desdeMax, linea, cambio }
 * `vigente` false = «Sin lectura» (sin velas, bono/fondo o velas de hace más
 * de 10 días): esa fila no muestra números y `motivo` dice por qué.
 */
export function filasDeLaLista({ tenencias = [], seguidos = [], indice, hoy = hoyISO() }) {
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
      cambio: c?.fecha ? { ...textoDelCambio(c), fecha: c.fecha, hace: haceCuanto(c.fecha, hoy) } : null,
    })
  }
  for (const t of tenencias) {
    const asset = String(t.asset || '').toUpperCase()
    if (!asset) continue
    armar(clave(asset, t.local), {
      nombre: fciLabel(asset), ruta: asset, tenes: true, peso: (t.peso || 0) * 100,
      p: { asset, asset_type: t.tipo || null },
    })
  }
  for (const it of seguidos) {
    const { asset, local, simbolo } = lecturaDeSeguido(it?.symbol, it?.asset_type)
    const k = clave(asset, local)
    if (!asset || filas.has(k)) continue
    armar(k, { nombre: isCrypto(asset) ? asset : simbolo, ruta: simbolo, tenes: false, peso: 0, p: loteDeSeguido(it, asset) })
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

