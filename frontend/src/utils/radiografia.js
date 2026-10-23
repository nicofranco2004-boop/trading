// radiografia.js — la radiografía técnica de la Cartera: cuánto de tu plata está
// en activos con tendencia de fondo alcista.
// ════════════════════════════════════════════════════════════════════════════
// Tres fuentes, ninguna recalculada acá:
//   · el VALOR de cada tenencia lo pone la pantalla que la dibuja (`valorDe`),
//     con la misma valuación que arma su total — así el «54 %» cierra contra el
//     número de arriba de la Cartera;
//   · los NÚMEROS técnicos vienen de POST /api/tecnico/cartera (backend/tecnico.py,
//     la misma `lectura` que la ficha de cada activo);
//   · las PALABRAS («Alcista», «Toma fuerza») son las de la ficha
//     (`tarjetas` y `veredictoRsi` de utils/tecnico.js): un activo no puede
//     decir «Alcista» en la Cartera y «Bajista» en su ficha.

import { isBymaHolding, fciLabel, isFciSym, isFixedIncome } from './valuation'
import { isCrypto } from './crypto'
import { cedearRatio } from './cedearRatio'
import { tarjetas, veredictoRsi, RSI_CASTIGADO, RSI_ESTIRADO } from './tecnico'
import { hoyISO } from './fecha'

// Una lectura cuya última vela tiene más días corridos que esto no describe el
// precio de hoy (Yahoo dejó de mandar velas, cambió el ticker): va «sin
// lectura» con su fecha, en vez de contarse en el porcentaje. Un fin de semana
// largo con feriados son 5 días; las velas se guardan cada noche.
export const DIAS_LECTURA_VIEJA = 10

/**
 * ¿Este lote es una acción ARGENTINA (no un CEDEAR)? Entonces su lectura en
 * dólares es su precio de BYMA ÷ el MEP de cada día, no el ADR de Nueva York
 * (GGAL "de afuera" son 10 acciones). La regla de la ficha, lote por lote.
 */
export function esLoteLocal(p) {
  if (!p || p.is_cash || cedearRatio(p.asset) || isCrypto(p.asset)) return false
  return p.asset_type !== 'CEDEAR' && isBymaHolding(p)
}

/** La marca `local` de la ficha: todos los lotes del activo son acción argentina. */
export function esAccionLocal(asset, lots) {
  if (!lots.length || cedearRatio(asset) || isCrypto(asset)) return false
  return lots.every(esLoteLocal)
}

const clave = (asset, local) => `${asset}|${local ? 1 : 0}`

/** Lo que se le pide al servidor: cada activo (con su marca `local`) una vez. */
export function activosParaLeer(lotes = []) {
  const vistos = new Map()
  for (const p of lotes) {
    if (!p || p.is_cash || !p.asset) continue
    const local = esLoteLocal(p)
    const k = clave(p.asset, local)
    if (!vistos.has(k)) vistos.set(k, { asset: p.asset, local })
  }
  return [...vistos.values()].sort((a, b) => clave(a.asset, a.local).localeCompare(clave(b.asset, b.local)))
}

/** {clave → lectura del servidor}. */
export function indexarLecturas(lecturas = []) {
  const out = new Map()
  for (const x of lecturas) out.set(clave(x.asset, x.local), x)
  return out
}

/** La lectura de una fila de la tabla (un lote o una fila que junta lotes del
 *  mismo broker). null si es efectivo o no llegó. */
export function lecturaDeFila(indice, p) {
  if (!indice || !p || p.is_cash) return null
  const lots = p._lots || [p]
  return indice.get(clave(String(p.asset || '').toUpperCase(), esAccionLocal(p.asset, lots))) || null
}

// Por qué algo va «sin lectura», del más permanente al más pasajero. Cada uno
// con su explicación: un bono no se mide así y nunca va a tener; una acción
// recién agregada sí, a partir de la noche en que se guardan sus precios.
export const MOTIVOS_SIN_LECTURA = {
  no_se_mide: 'bonos, fondos, efectivo y plazos fijos no tienen historia de precios en Rendi: no se les mide la tendencia.',
  sin_historia: 'todavía no hay historia de precios guardada. Se guarda cada noche: aparece en un día.',
  pocos_dias: 'para leer la tendencia hacen falta 200 días de mercado de precios guardados, y todavía no los tienen.',
  vieja: `su último precio guardado tiene más de ${DIAS_LECTURA_VIEJA} días: no describe el de hoy.`,
}

/** ¿Este lote es de los que no se miden con velas? (efectivo, fondo, bono, plazo fijo) */
function noSeMide(p) {
  return !!p && (p.is_cash || p.es_plazo_fijo || isFciSym(p.asset) || isFixedIncome(p.asset_type)
    || ['FUND', 'FCI'].includes(String(p.asset_type || '').toUpperCase()))
}

/**
 * La tendencia de fondo con las palabras de la ficha: { id: 'alcista' |
 * 'bajista' | 'sin', palabra, motivo, porque }. «Sin lectura» trae `porque`
 * (una clave de MOTIVOS_SIN_LECTURA) y un `motivo` para el globo de la fila,
 * según qué le falta: `p` (un lote del activo) dice si es un bono o un fondo.
 */
export function tendencia(x, hoy = hoyISO(), p = null) {
  const sin = (porque, motivo) => ({ id: 'sin', palabra: 'Sin lectura', porque, motivo })
  if (!x || !x.disponible || !x.lectura) {
    if (noSeMide(p)) return sin('no_se_mide', 'Bonos, fondos y efectivo no tienen historia de precios en Rendi: no se les mide la tendencia.')
    return sin('sin_historia', 'Todavía no hay historia de precios guardada para este activo. Se guarda cada noche: aparece en un día.')
  }
  if (lecturaVieja(x, hoy)) {
    return sin('vieja', `El último precio guardado es del ${fechaCorta(x.lectura.fecha)}: no describe el de hoy.`)
  }
  const fondo = tarjetas(x.lectura).find(t => t.id === 'fondo')
  if (fondo?.veredicto === 'Alcista') return { id: 'alcista', palabra: 'Alcista', motivo: fondo.texto }
  if (fondo?.veredicto === 'Bajista') return { id: 'bajista', palabra: 'Bajista', motivo: fondo.texto }
  return sin('pocos_dias', fondo?.texto || 'Faltan datos.')
}

/** ¿La última vela es de hace más de DIAS_LECTURA_VIEJA días corridos? */
export function lecturaVieja(x, hoy = hoyISO()) {
  const f = x?.lectura?.fecha
  if (!f) return false
  return (Date.parse(hoy + 'T00:00:00Z') - Date.parse(f + 'T00:00:00Z')) / 86400000 > DIAS_LECTURA_VIEJA
}

function fechaCorta(iso) {
  const [y, m, d] = String(iso).split('-')
  return `${d}/${m}/${y}`
}

/** El RSI de la fila y su palabra (`veredictoRsi`, «Toma fuerza»). null si no hay o
 *  si la lectura es vieja. */
export function fuerza(x, hoy = hoyISO()) {
  const rsi = x?.disponible && !lecturaVieja(x, hoy) ? x.lectura?.rsi : null
  if (rsi == null) return null
  return { rsi, palabra: veredictoRsi(rsi) }
}

/**
 * Porcentajes enteros que suman 100 (el método del resto mayor): redondear cada
 * uno por su lado puede dar 99 o 101 y la barra no cerraría.
 */
export function repartirCien(valores) {
  const total = valores.reduce((s, v) => s + v, 0)
  if (!(total > 0)) return valores.map(() => 0)
  const crudos = valores.map(v => (v / total) * 100)
  const pisos = crudos.map(Math.floor)
  let falta = 100 - pisos.reduce((s, v) => s + v, 0)
  const orden = crudos.map((c, i) => [c - pisos[i], i]).sort((a, b) => b[0] - a[0])
  for (const [, i] of orden) {
    if (falta <= 0) break
    pisos[i] += 1
    falta -= 1
  }
  return pisos
}

const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado']
function cuando(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  const f = new Date(Date.UTC(y, m - 1, d))
  return `${DIAS[f.getUTCDay()]} ${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')}`
}

/**
 * La radiografía. `lotes`: todas las posiciones (efectivo incluido); `valorDe(p)`:
 * el valor en dólares de ESE lote, el que usa la pantalla para su total;
 * `extra`: [{ nombre, valor }] lo que suma al total sin ser una posición (los
 * plazos fijos). Devuelve:
 *   { total, grupos: { alcista, bajista, sin } con { valor, pct, nombres[] },
 *     cambios: [{ asset, tono: 'pos'|'neg'|'aviso', texto }] }
 */
export function radiografia(lotes = [], valorDe, indice, extra = [], hoy = hoyISO()) {
  const porActivo = new Map()   // clave → { nombre, valor, x, p (un lote, para el motivo) }
  const sumar = (k, nombre, valor, x, p) => {
    if (!(valor > 0)) return
    const a = porActivo.get(k) || { nombre, valor: 0, x, p }
    a.valor += valor
    porActivo.set(k, a)
  }
  for (const p of lotes) {
    if (!p) continue
    const v = Number(valorDe(p))
    if (p.is_cash) { sumar('efectivo', 'efectivo', v, null, p); continue }
    const local = esLoteLocal(p)
    const k = clave(String(p.asset).toUpperCase(), local)
    sumar(k, fciLabel(p.asset), v, indice?.get(k) || null, p)
  }
  for (const e of extra) sumar(`extra:${e.nombre}`, e.nombre, Number(e.valor), null, { es_plazo_fijo: true })

  const grupos = { alcista: [], bajista: [], sin: [] }
  const motivos = {}   // porque → [nombres], en el orden de MOTIVOS_SIN_LECTURA
  for (const a of porActivo.values()) {
    a.t = tendencia(a.x, hoy, a.p)
    grupos[a.t.id].push(a)
  }
  const ids = ['alcista', 'bajista', 'sin']
  const valores = ids.map(id => grupos[id].reduce((s, a) => s + a.valor, 0))
  const pcts = repartirCien(valores)
  const total = valores.reduce((s, v) => s + v, 0)
  const salida = {}
  ids.forEach((id, i) => {
    const nombres = [...new Set(grupos[id].sort((a, b) => b.valor - a.valor).map(a => a.nombre))]
    salida[id] = { valor: valores[i], pct: pcts[i], fraccion: total > 0 ? valores[i] / total : 0, nombres }
  })
  for (const a of grupos.sin) (motivos[a.t.porque] ||= []).includes(a.nombre) || motivos[a.t.porque].push(a.nombre)
  // [{ porque, nombres, texto }]: el «por qué» de cada uno de los sin lectura.
  salida.sin.motivos = Object.keys(MOTIVOS_SIN_LECTURA).filter(k => motivos[k])
    .map(k => ({ porque: k, nombres: motivos[k], texto: MOTIVOS_SIN_LECTURA[k] }))

  // Lo que cambió: primero los cruces del promedio de 200 (la tendencia de
  // fondo), después los de 50, después el RSI en un extremo; dentro de cada
  // uno, lo que más pesa en tu cartera primero.
  // Sólo lecturas de hoy: una serie cortada no tiene «esta semana» (el servidor
  // ya cuenta los cruces desde hoy; el RSI viejo se saca acá).
  const conLectura = [...porActivo.values()].filter(a => a.x?.disponible && !lecturaVieja(a.x, hoy)).sort((a, b) => b.valor - a.valor)
  const cambios = []
  for (const n of [200, 50]) {
    for (const a of conLectura) {
      const c = (a.x.cambios || []).find(c => c.media === n)
      if (!c) continue
      const arriba = c.direccion === 'arriba'
      cambios.push({
        asset: a.nombre, tono: arriba ? 'pos' : 'neg',
        texto: `${arriba ? 'pasó arriba' : 'quedó abajo'} de su promedio de ${n} días (${cuando(c.fecha)})`,
      })
    }
  }
  for (const a of conLectura) {
    const r = a.x.lectura?.rsi
    if (r == null || (r >= RSI_CASTIGADO && r <= RSI_ESTIRADO)) continue
    cambios.push({
      asset: a.nombre, tono: 'aviso',
      texto: `tiene la fuerza en ${Math.round(r)} de 100: ${veredictoRsi(r).toLowerCase()}`,
    })
  }
  return { total, grupos: salida, cambios }
}
