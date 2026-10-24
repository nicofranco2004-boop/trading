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

import { esCobro, esTradeCerrado } from './tradeStats'

// Cuánto tiempo muestra cada rango del gráfico, en días CORRIDOS: una cripto
// cotiza los 7 días y la bolsa 5, así que contar velas daba 8 meses en "1A"
// para Bitcoin (auditoría 22/10).
export const RANGOS = [
  { id: '3m', label: '3M', dias: 91 },
  { id: '1a', label: '1A', dias: 365 },
  { id: '2a', label: '2A', dias: 730 },
]

/** Cuántos de los últimos puntos caen en los últimos `dias` días corridos. */
export function puntosEnDias(puntos = [], dias) {
  if (!puntos.length) return 0
  const fin = Date.parse(puntos[puntos.length - 1].d + 'T00:00:00Z')
  const piso = new Date(fin - dias * 86400000).toISOString().slice(0, 10)
  let n = 0
  for (let i = puntos.length - 1; i >= 0 && puntos[i].d > piso; i--) n++
  return n
}

// Los cortes del RSI que usa todo el mundo (TradingView incluido).
export const RSI_CASTIGADO = 30
export const RSI_ESTIRADO = 70

const pct1 = (v) => `${Math.abs(v).toLocaleString('es-AR', { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`

/**
 * La vela de un punto, completa: apertura, máximo, mínimo y cierre. Si a la vela
 * guardada le falta algo (Yahoo a veces manda el máximo roto y se guarda sólo el
 * cierre), se completa con lo que hay: la apertura con el cierre anterior y el
 * máximo/mínimo con la apertura y el cierre. Nunca se inventa una mecha.
 */
export function velaCompleta(p, cierreAnterior) {
  const c = p.c
  const o = p.o ?? cierreAnterior ?? c
  const h = p.h != null ? Math.max(p.h, o, c) : Math.max(o, c)
  const l = p.l != null ? Math.min(p.l, o, c) : Math.min(o, c)
  return { o, h, l, c }
}

/**
 * Velas SEMANALES a partir de las diarias (para el rango de 2 años: 500 velas
 * diarias en un celular son rayitas). Cada semana: la apertura del primer día,
 * el máximo y el mínimo de la semana, el cierre del último día, el volumen
 * sumado; las medias y el
 * RSI son los del último día. `d` es el primer día de la semana, así una compra
 * a mitad de semana cae en su vela.
 */
export function velasSemanales(puntos = []) {
  const out = []
  let actual = null
  let clave = null
  let prevC = null
  for (const p of puntos) {
    const f = new Date(p.d + 'T00:00:00Z')
    const lunes = new Date(f.getTime() - ((f.getUTCDay() + 6) % 7) * 86400000).toISOString().slice(0, 10)
    const v = velaCompleta(p, prevC)
    prevC = p.c
    if (lunes !== clave) {
      if (actual) out.push(actual)
      clave = lunes
      actual = { ...p, d: p.d, o: v.o, h: v.h, l: v.l, c: v.c, v: p.v ?? null, semana: true }
    } else {
      actual = { ...actual, h: Math.max(actual.h, v.h), l: Math.min(actual.l, v.l), c: v.c,
        v: p.v == null ? actual.v : (actual.v || 0) + p.v,
        s50: p.s50, s200: p.s200, rsi: p.rsi }
    }
  }
  if (actual) out.push(actual)
  return out
}

/**
 * La ventana del gráfico se mide en LUGARES, no en velas: además de los días
 * que hay, puede tener lugares vacíos a la derecha (el futuro), como en
 * TradingView. Así la última vela no queda pegada al borde y se puede
 * arrastrar el gráfico hacia adelante (Nico, 23/10: «tosco»). `fin` puede
 * pasar de `total` (los días que hay) hasta la mitad de lo que se ve.
 *
 * El aire de entrada a la derecha: un 5 % de lo que se ve, nunca menos de 3.
 */
export function margenDerecho(dias) {
  return Math.max(3, Math.round(dias * 0.05))
}
/** Lo más lejos que se puede ir hacia el futuro con `n` lugares a la vista. */
export function futuroMaximo(n) {
  return Math.floor(n * 0.5)
}
/** La ventana de entrada para ver `dias` días: esos días más el aire de la derecha. */
export function ventanaInicial(dias, total) {
  const d = Math.min(dias, total)
  const m = margenDerecho(d)
  return { n: d + m, fin: total + m }
}

/**
 * El zoom de la ruedita: cuántos lugares se ven y hasta cuál. `vista` = { n,
 * fin, total } (fin sin incluir; puede pasar de `total`), `factor` > 1 aleja y
 * < 1 acerca, `f` (0 a 1) es qué punto del ancho queda quieto. Nunca menos de
 * 20 ruedas ni más de las que hay (más su aire). null si no cambia nada.
 */
export const RUEDAS_MINIMAS = 20
export function zoomVentana({ n, fin, total }, factor, f) {
  const n2 = Math.round(Math.min(total + margenDerecho(total), Math.max(RUEDAS_MINIMAS, n * factor)))
  if (n2 === n) return null
  const bajoMouse = fin - n + f * n
  const fin2 = Math.round(Math.min(total + futuroMaximo(n2), Math.max(n2, bajoMouse - f * n2 + n2)))
  return { n: n2, fin: fin2 }
}

/** Arrastrar: corre la ventana en el tiempo. `frac` es cuánto del ancho se
 *  arrastró (a la derecha = para atrás en el tiempo; a la izquierda, hacia el
 *  futuro, hasta la mitad de lo que se ve). null si ya está en el borde. */
export function moverVentana({ n, fin, total }, frac) {
  const fin2 = Math.round(Math.min(total + futuroMaximo(n), Math.max(n, fin - frac * n)))
  return fin2 === fin ? null : { n, fin: fin2 }
}

/** Los últimos `ruedas` puntos. */
export function recortar(puntos = [], ruedas) {
  return ruedas >= puntos.length ? puntos : puntos.slice(puntos.length - ruedas)
}

/**
 * Las tarjetas del análisis técnico, en castellano del día a día: «promedio de
 * 200 días» y no «media móvil», «días de mercado» y no «ruedas», y el RSI dicho
 * como fuerza que se gana o se pierde (Nico, 22/10: «claro, conciso, sin
 * tecnicismos que no sirven»). Cada una: { id, titulo,
 * veredicto, tono: 'pos'|'neg'|'neutro', texto }. Con pocos datos la tarjeta lo
 * dice en vez de inventar.
 */
export function tarjetas(l) {
  if (!l || !l.ruedas) return []
  const out = []

  if (l.media200 != null && l.dist_media200 != null) {
    const arriba = l.dist_media200 >= 0
    // Sin el dato de hace un mes (un activo con 200 a 220 ruedas) no se sabe
    // hacia dónde va la media: se corta la frase, no se supone "subiendo".
    const hacia = l.pendiente_media200 == null ? ''
      : ` Ese promedio viene ${l.pendiente_media200 >= 0 ? 'subiendo' : 'bajando'}.`
    out.push({
      id: 'fondo', titulo: 'Largo plazo',
      veredicto: arriba ? 'Alcista' : 'Bajista', tono: arriba ? 'pos' : 'neg',
      texto: `El precio está ${pct1(l.dist_media200)} ${arriba ? 'arriba' : 'abajo'} de su promedio de los últimos 200 días.${hacia} `
        + `Estar ${arriba ? 'arriba' : 'abajo'} de ese promedio es la señal más usada de que la tendencia de fondo es ${arriba ? 'alcista' : 'bajista'}.`,
    })
  } else {
    out.push({
      id: 'fondo', titulo: 'Largo plazo', veredicto: 'Faltan datos', tono: 'neutro',
      texto: `Para leerlo hacen falta 200 días de mercado y este activo tiene ${l.ruedas}.`,
    })
  }

  if (l.media50 != null && l.dist_media50 != null) {
    const arriba = l.dist_media50 >= 0
    out.push({
      id: 'corto', titulo: 'Corto plazo',
      veredicto: arriba ? 'Alcista' : 'Bajista', tono: arriba ? 'pos' : 'neg',
      texto: `El precio está ${pct1(l.dist_media50)} ${arriba ? 'arriba' : 'abajo'} de su promedio de los últimos 50 días (unos dos meses y medio): `
        + `${arriba ? 'viene subiendo' : 'viene bajando'} en los últimos meses.`,
    })
  }

  if (l.rsi != null) {
    out.push({
      id: 'rsi', titulo: 'Fuerza (RSI)',
      veredicto: veredictoRsi(l.rsi), tono: 'neutro', rsi: l.rsi,
      texto: `${Math.round(l.rsi)} de 100. Compara las subas con las bajas de las últimas 3 semanas. `
        + `Arriba de 50 el precio toma fuerza; abajo de 50, la pierde. `
        + `Pasar ${RSI_ESTIRADO} es subir muy rápido, y suele frenar. Bajar de ${RSI_CASTIGADO} es caer muy rápido, y suele rebotar.`,
      cruce: textoCruceRsi(l.rsi_cruce),
    })
  }

  if (l.dist_maximo_12m != null) {
    // El máximo es de CIERRE (el servidor): cerrar en récord da exactamente 0.
    const enMaximo = l.dist_maximo_12m >= -0.1
    out.push({
      id: 'maximo', titulo: l.anio_completo ? 'Máximo del año' : 'Máximo del período',
      veredicto: enMaximo ? 'En su máximo' : `${pct1(l.dist_maximo_12m)} por debajo`, tono: 'neutro',
      texto: enMaximo
        ? `Cerró en el precio más alto ${l.anio_completo ? 'de los últimos 12 meses' : `de los ${l.ruedas} días de mercado que hay`}.`
        : `Lo que le falta para volver al precio más alto ${l.anio_completo ? 'de los últimos 12 meses' : `de los ${l.ruedas} días de mercado que hay`}.`,
    })
  }
  return out
}

// El RSI dicho como fuerza que el precio gana o pierde. «Castigado/estirado»
// no se entendía, y «pesan más las subas» tampoco decía cuándo toma fuerza y
// cuándo no (Nico, 2026-10-22).
export function veredictoRsi(rsi) {
  if (rsi < RSI_CASTIGADO) return 'Cayó muy rápido'
  if (rsi < 45) return 'Pierde fuerza'
  if (rsi <= 55) return 'Sin fuerza clara'
  if (rsi <= RSI_ESTIRADO) return 'Toma fuerza'
  return 'Subió muy rápido'
}

/** El último cruce de 30 o 70 (de `lectura.rsi_cruce`), en palabras. null si no hubo. */
export function textoCruceRsi(c) {
  if (!c) return null
  const cuando = c.hace === 0 ? 'En el último día de mercado' : c.hace === 1 ? 'Hace 1 día de mercado' : `Hace ${c.hace} días de mercado`
  if (c.tipo === 'salio_de_abajo') return `${cuando} volvió a pasar ${RSI_CASTIGADO} para arriba: suele leerse como que dejó de caer y empieza a tomar fuerza.`
  if (c.tipo === 'salio_de_arriba') return `${cuando} bajó de ${RSI_ESTIRADO}: suele leerse como que empieza a perder fuerza.`
  return null
}

/**
 * Dónde va tu precio promedio en el gráfico: `último ÷ (1 + resultado) × (1 +
 * variación de hoy)`. El último punto del gráfico es el cierre de AYER (las
 * velas se guardan de noche) y el resultado es con el precio de AHORA: sin la
 * variación de hoy, un día que el papel se mueve 10 % la línea se corría 10 %
 * (auditoría 22/10). null si no hay resultado o no tiene sentido.
 */
export function lineaPromedio(puntos = [], pnlPct, variacionHoy = 0) {
  const ultimo = puntos.length ? puntos[puntos.length - 1].c : null
  if (!(ultimo > 0) || pnlPct == null || !(1 + pnlPct > 0)) return null
  return (ultimo / (1 + pnlPct)) * (1 + (variacionHoy || 0))
}

/** Cuánto se movió hoy el precio en vivo contra el último cierre guardado del
 *  MISMO instrumento. 0 si falta alguno de los dos. */
export function variacionDeHoy(precioVivo, cierreRef) {
  return precioVivo > 0 && cierreRef?.cierre > 0 ? precioVivo / cierreRef.cierre - 1 : 0
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
    // la ficha (`esTradeCerrado`): deja afuera conversiones de moneda. Los cobros
    // (dividendo, cupón, renta, amortización) con `esCobro`, que los tiene a
    // todos: `esTradeCerrado` sólo excluye algunos.
    if (esCobro(o.op_type) || !esTradeCerrado(o)) continue
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
