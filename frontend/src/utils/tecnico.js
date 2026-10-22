// tecnico.js — lo que la ficha del activo dibuja encima de la lectura técnica.
// ════════════════════════════════════════════════════════════════════════════
// Los NÚMEROS (medias, RSI, ADX, Squeeze, máximo del año) vienen hechos de GET /api/tecnico
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
 * el máximo y el mínimo de la semana, el cierre del último día; las medias y el
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
      actual = { ...p, d: p.d, o: v.o, h: v.h, l: v.l, c: v.c, semana: true }
    } else {
      actual = { ...actual, h: Math.max(actual.h, v.h), l: Math.min(actual.l, v.l), c: v.c,
        s50: p.s50, s200: p.s200, rsi: p.rsi, adx: p.adx, squeeze: p.squeeze, squeeze_color: p.squeeze_color }
    }
  }
  if (actual) out.push(actual)
  return out
}

/**
 * El zoom de la ruedita: cuántas ruedas se ven y hasta cuál. `vista` = { n, fin,
 * total } (fin sin incluir), `factor` > 1 aleja y < 1 acerca, `f` (0 a 1) es
 * dónde está el mouse: ese día queda quieto. Nunca menos de 20 ruedas ni más de
 * las que hay. null si no cambia nada.
 */
export const RUEDAS_MINIMAS = 20
export function zoomVentana({ n, fin, total }, factor, f) {
  const n2 = Math.round(Math.min(total, Math.max(RUEDAS_MINIMAS, n * factor)))
  if (n2 === n) return null
  const bajoMouse = fin - n + f * n
  const fin2 = Math.round(Math.min(total, Math.max(n2, bajoMouse - f * n2 + n2)))
  return { n: n2, fin: fin2 }
}

/** Arrastrar: corre la ventana en el tiempo. `frac` es cuánto del ancho se
 *  arrastró (a la derecha = para atrás en el tiempo). null si ya está en el borde. */
export function moverVentana({ n, fin, total }, frac) {
  const fin2 = Math.round(Math.min(total, Math.max(n, fin - frac * n)))
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

  const fuerza = tarjetaFuerza(l)
  if (fuerza) out.push(fuerza)

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

// ─── Fuerza de la tendencia: ADX + Squeeze ──────────────────────────────────
// El combo de TradingView «DMI/ADX/KEYLEVEL 14 14 23» + «SQZMOM_LB»: el ADX
// dice CUÁNTA fuerza tiene la tendencia (no para dónde va) y arriba de 23 se lee
// como "hay tendencia"; el Squeeze dice para DÓNDE empuja.

// La línea clave del ADX (la misma que `tecnico.ADX_CLAVE` del servidor).
export const ADX_CLAVE = 23
// Lo que tiene que subir o bajar el ADX en 3 días de mercado para decir que la
// fuerza crece o se afloja (menos es ruido).
const ADX_QUIETO = 0.5

/** El color del Squeeze dicho en palabras: hacia dónde empuja y si con más o
 *  menos empuje que el día anterior. */
export function textoSqueeze(color) {
  switch (color) {
    case 'verde_fuerte': return 'está en verde: empuja a favor de la suba'
    case 'verde_apagado': return 'está en verde, a favor de la suba, pero con menos empuje que el día anterior'
    case 'rojo_fuerte': return 'está en rojo: empuja a favor de la baja'
    case 'rojo_apagado': return 'está en rojo, a favor de la baja, pero con menos empuje que el día anterior'
    default: return null
  }
}

/**
 * La tarjeta «Fuerza de la tendencia». Veredicto por el ADX (si hay tendencia
 * con fuerza o no); el color, por el Squeeze (verde, a favor de la suba; rojo,
 * de la baja). Con pocos datos lo dice en vez de inventar. null sin lectura.
 */
export function tarjetaFuerza(l) {
  if (!l || !l.ruedas) return null
  if (l.adx == null || l.squeeze == null) {
    return {
      id: 'fuerza', titulo: 'Fuerza de la tendencia', veredicto: 'Faltan datos', tono: 'neutro',
      texto: `Para medirla hacen falta unos 40 días de mercado y este activo tiene ${l.ruedas}.`,
    }
  }
  const conFuerza = l.adx >= ADX_CLAVE
  const sube = l.squeeze > 0
  const cruce = l.adx_cruce
  const veredicto = !conFuerza ? 'Sin tendencia clara'
    : cruce?.tipo === 'paso_arriba' ? 'Toma fuerza'
      : (l.adx_pendiente ?? 0) < -ADX_QUIETO ? 'La fuerza afloja'
        : 'Tendencia con fuerza'
  const hacia = l.adx_pendiente == null ? ''
    : l.adx_pendiente > ADX_QUIETO ? ', y subiendo'
      : l.adx_pendiente < -ADX_QUIETO ? ', y bajando' : ''
  const sq = textoSqueeze(l.squeeze_color)
  return {
    id: 'fuerza', titulo: 'Fuerza de la tendencia',
    veredicto, tono: conFuerza ? (sube ? 'pos' : 'neg') : 'neutro', adx: l.adx,
    texto: `El ADX está en ${Math.round(l.adx)}, ${conFuerza ? 'arriba' : 'abajo'} de la línea de ${ADX_CLAVE}${hacia}. `
      + `El ADX mide cuánta fuerza tiene la tendencia, no para dónde va: arriba de ${ADX_CLAVE} hay tendencia con fuerza; abajo, el precio va más de costado. `
      + (sq ? `La dirección la marca el Squeeze, que ${sq}.` : '')
      + (l.squeeze_activo ? ' Además el precio se mueve poco («apretado»): suele ser la antesala de un movimiento más grande, para cualquier lado.' : ''),
    cruce: textoCruceAdx(cruce, l.squeeze),
  }
}

/**
 * El último cruce del ADX por 23 (de `lectura.adx_cruce`), en palabras. Si pasó
 * para arriba con el Squeeze del mismo lado ese día y hoy, la frase dice para
 * dónde. null si no hubo.
 */
export function textoCruceAdx(c, squeezeHoy) {
  if (!c) return null
  const cuando = c.hace === 0 ? 'En el último día de mercado' : c.hace === 1 ? 'Hace 1 día de mercado' : `Hace ${c.hace} días de mercado`
  if (c.tipo === 'paso_abajo') {
    return `${cuando} la fuerza (ADX) bajó de ${ADX_CLAVE}: suele leerse como que la tendencia se queda sin fuerza y el precio pasa a moverse de costado.`
  }
  if (c.tipo !== 'paso_arriba') return null
  const hoy = squeezeHoy > 0 ? 1 : squeezeHoy < 0 ? -1 : 0
  if (hoy !== 0 && c.squeeze === hoy) {
    return `${cuando} la fuerza (ADX) pasó ${ADX_CLAVE} para arriba con el Squeeze en ${hoy > 0 ? 'verde' : 'rojo'}: `
      + `suele leerse como el arranque de una ${hoy > 0 ? 'suba' : 'baja'} con fuerza.`
  }
  return `${cuando} la fuerza (ADX) pasó ${ADX_CLAVE} para arriba: suele leerse como que la tendencia toma fuerza.`
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
