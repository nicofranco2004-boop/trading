// tecnico.js — lo que la ficha del activo dibuja encima de la lectura técnica.
// ════════════════════════════════════════════════════════════════════════════
// Los NÚMEROS (medias, RSI, máximo del año) vienen hechos de GET /api/tecnico
// (backend/tecnico.py), en UN lugar. Acá viven las palabras de cada tarjeta y lo
// que sólo sabe la ficha: tus compras, tus ventas y tu precio promedio.
//
// Tu precio promedio se dibuja con el resultado que ya muestra la ficha arriba
// (`pnlPct`), no recalculado: la línea va en `último precio ÷ (1 + resultado)`.
// Así la distancia entre el precio y la línea es EXACTAMENTE el % de tu
// resultado, en la escala del gráfico — aunque el gráfico sea la acción de Nueva
// York y vos tengas CEDEARs (otra escala), o una acción argentina pasada a
// dólares día por día.

import { esTradeCerrado } from './tradeStats'

// Cuántas ruedas muestra cada rango del gráfico.
export const RANGOS = [
  { id: '3m', label: '3M', ruedas: 63 },
  { id: '1a', label: '1A', ruedas: 252 },
  { id: '2a', label: '2A', ruedas: 504 },
]

// Los cortes del RSI que usa todo el mundo (TradingView incluido).
export const RSI_CASTIGADO = 30
export const RSI_ESTIRADO = 70

const pct1 = (v) => `${Math.abs(v).toLocaleString('es-AR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`

/** Los últimos `ruedas` puntos. */
export function recortar(puntos = [], ruedas) {
  return ruedas >= puntos.length ? puntos : puntos.slice(puntos.length - ruedas)
}

/**
 * Las tarjetas de la lectura técnica, en castellano. Cada una: { id, titulo,
 * veredicto, tono: 'pos'|'neg'|'neutro', texto }. Con pocos datos la tarjeta lo
 * dice en vez de inventar.
 */
export function tarjetas(l) {
  if (!l || !l.ruedas) return []
  const out = []

  if (l.media200 != null && l.dist_media200 != null) {
    const arriba = l.dist_media200 >= 0
    const sube = (l.pendiente_media200 ?? 0) >= 0
    out.push({
      id: 'fondo', titulo: 'Tendencia de fondo',
      veredicto: arriba ? 'Alcista' : 'Bajista', tono: arriba ? 'pos' : 'neg',
      texto: `Está ${pct1(l.dist_media200)} ${arriba ? 'arriba' : 'abajo'} de su media de 200 días, y esa media viene ${sube ? 'subiendo' : 'bajando'}.`,
    })
  } else {
    out.push({
      id: 'fondo', titulo: 'Tendencia de fondo', veredicto: 'Faltan datos', tono: 'neutro',
      texto: `La media de 200 días necesita 200 ruedas y hay ${l.ruedas}.`,
    })
  }

  if (l.media50 != null && l.dist_media50 != null) {
    const arriba = l.dist_media50 >= 0
    out.push({
      id: 'corto', titulo: 'Corto plazo',
      veredicto: arriba ? 'Firme' : 'Débil', tono: arriba ? 'pos' : 'neg',
      texto: `Está ${pct1(l.dist_media50)} ${arriba ? 'arriba' : 'abajo'} de su media de 50 días.`,
    })
  }

  if (l.rsi != null) {
    out.push({
      id: 'rsi', titulo: 'Fuerza del movimiento (RSI)',
      veredicto: veredictoRsi(l.rsi), tono: 'neutro', rsi: l.rsi,
      texto: `${Math.round(l.rsi)} de 100. Mide si en las últimas 14 ruedas pesaron más las subas o las bajas (50 es parejo). `
        + `Abajo de ${RSI_CASTIGADO}: bajas muy fuertes, a veces viene un rebote. `
        + `Arriba de ${RSI_ESTIRADO}: subas muy fuertes, a veces viene una pausa.`,
      cruce: textoCruceRsi(l.rsi_cruce),
    })
  }

  if (l.dist_maximo_12m != null) {
    const enMaximo = l.dist_maximo_12m > -0.05
    out.push({
      id: 'maximo', titulo: l.anio_completo ? 'Máximo del año' : 'Máximo del período',
      veredicto: enMaximo ? 'En su máximo' : `${pct1(l.dist_maximo_12m)} abajo`, tono: 'neutro',
      texto: l.anio_completo
        ? 'Contra el precio más alto de los últimos 12 meses.'
        : `Contra el precio más alto de las ${l.ruedas} ruedas que hay.`,
    })
  }
  return out
}

// El RSI dicho como quién viene ganando: las subas o las bajas de las últimas
// 14 ruedas. «Castigado/estirado» no se entendía (Nico, 2026-10-22).
export function veredictoRsi(rsi) {
  if (rsi < RSI_CASTIGADO) return 'Bajó muy fuerte y rápido'
  if (rsi < 45) return 'Pesan más las bajas'
  if (rsi <= 55) return 'Parejo'
  if (rsi <= RSI_ESTIRADO) return 'Pesan más las subas'
  return 'Subió muy fuerte y rápido'
}

/** El último cruce de 30 o 70 (de `lectura.rsi_cruce`), en palabras. null si no hubo. */
export function textoCruceRsi(c) {
  if (!c) return null
  const cuando = c.hace === 0 ? 'En la última rueda' : c.hace === 1 ? 'Hace 1 rueda' : `Hace ${c.hace} ruedas`
  if (c.tipo === 'salio_de_abajo') return `${cuando} volvió a pasar ${RSI_CASTIGADO} para arriba: muchos lo leen como que vuelve a tomar fuerza.`
  if (c.tipo === 'salio_de_arriba') return `${cuando} bajó de ${RSI_ESTIRADO}: muchos lo leen como que pierde fuerza.`
  return null
}

/**
 * Dónde va tu precio promedio en el gráfico: `último ÷ (1 + resultado)`. null si
 * no hay resultado (no tenés el activo) o el resultado no tiene sentido.
 */
export function lineaPromedio(puntos = [], pnlPct) {
  const ultimo = puntos.length ? puntos[puntos.length - 1].c : null
  if (!(ultimo > 0) || pnlPct == null || !(1 + pnlPct > 0)) return null
  return ultimo / (1 + pnlPct)
}

/**
 * Tus compras y ventas como marcas del gráfico: [{ fecha, tipo: 'compra'|'venta' }].
 *   · compras: la fecha de entrada de cada lote abierto y de cada operación cerrada;
 *   · ventas: la fecha de cada operación cerrada.
 * Los cobros (dividendos, cupones) no son compras ni ventas.
 */
export function marcas(lotes = [], operaciones = []) {
  const out = []
  for (const l of lotes) {
    if (l.is_cash || !l.entry_date) continue
    out.push({ fecha: String(l.entry_date).slice(0, 10), tipo: 'compra' })
  }
  for (const o of operaciones) {
    // La regla de "esto fue una compra y una venta" es la de las estadísticas de
    // la ficha (`esTradeCerrado`): deja afuera cobros y conversiones de moneda.
    if (!esTradeCerrado(o)) continue
    if (o.entry_date) out.push({ fecha: String(o.entry_date).slice(0, 10), tipo: 'compra' })
    if (o.date) out.push({ fecha: String(o.date).slice(0, 10), tipo: 'venta' })
  }
  const vistas = new Set()
  return out.filter(m => {
    const k = `${m.fecha}|${m.tipo}`
    if (vistas.has(k)) return false
    vistas.add(k)
    return true
  }).sort((a, b) => a.fecha.localeCompare(b.fecha))
}

/** El índice del punto de esa fecha, o del último anterior (un fin de semana
 *  cae en el viernes). null si la fecha es anterior al gráfico. */
export function indiceDeFecha(puntos, fecha) {
  let lo = 0, hi = puntos.length - 1, mejor = null
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (puntos[mid].d <= fecha) { mejor = mid; lo = mid + 1 } else hi = mid - 1
  }
  return mejor
}

/**
 * ¿En pesos parece otra cosa que en dólares? Es el aviso de la ficha: un CEDEAR
 * en pesos sube con el dólar aunque la empresa no se mueva.
 */
export function tendenciasDistintas(lUsd, lArs) {
  const a = lUsd?.dist_media200, b = lArs?.dist_media200
  if (a == null || b == null) return false
  return (a >= 0) !== (b >= 0)
}
