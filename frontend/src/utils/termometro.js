// termometro.js — las palabras del termómetro del mercado (pieza 7).
// ════════════════════════════════════════════════════════════════════════════
// El número y cada una de sus partes vienen armados de GET /api/termometro
// (backend/termometro.py, que guarda uno por día). Acá no se calcula nada de
// nuevo: sólo se ponen las palabras de cada parte y las del número entero.
//
// Las palabras DESCRIBEN cómo se viene moviendo el mercado. Nunca dicen qué
// hacer ni cuánto tener invertido: la medición de la ficha encontró que estos
// indicadores describen bien y no anticipan mejor que el azar.

import { pesoVisible } from './parteDeTuPlata'

export const LEYENDA = 'Describe cómo se mueve el mercado. No dice cuánto tener invertido ni es una recomendación.'

// Los cortes del número. Los mismos tramos que pinta el arco.
export const CORTE_DEBIL = 40
export const CORTE_FIRME = 60

const num = (x, dec = 0) => Number(x).toLocaleString('es-AR', {
  minimumFractionDigits: 0, maximumFractionDigits: dec,
})

/** «28/10» de un 'YYYY-MM-DD'. */
export function diaCorto(iso) {
  const [, m, d] = String(iso || '').split('-')
  return d && m ? `${d}/${m}` : ''
}

/** { texto, tono } del número entero. Tono: 'neg' | 'neutro' | 'pos'. */
export function zona(puntaje) {
  if (puntaje == null) return { texto: 'Sin dato', tono: 'neutro' }
  if (puntaje < CORTE_DEBIL) return { texto: 'Mercado débil', tono: 'neg' }
  if (puntaje <= CORTE_FIRME) return { texto: 'Mercado mixto', tono: 'neutro' }
  return { texto: 'Mercado firme', tono: 'pos' }
}

/** «Al cierre del 28/10», o de qué día es si quedó viejo. */
export function cuando(t) {
  if (!t?.fecha) return ''
  return t.viejo ? `Último dato: cierre del ${diaCorto(t.fecha)}` : `Al cierre del ${diaCorto(t.fecha)}`
}

/** «Hace una semana: 64» o por qué todavía no está. Para atrás no se inventa. */
export function semanaPasadaTxt(t) {
  const s = t?.semana_pasada
  if (s?.puntaje != null) return `Hace una semana (${diaCorto(s.fecha)}): ${s.puntaje}`
  return 'Hace una semana: todavía no hay dato. Se guarda uno por día desde que existe el termómetro.'
}

function textoIndice(i) {
  if (i.arriba200 && i.arriba50) return 'Arriba de sus promedios de 50 y de 200 días'
  if (i.arriba200) return 'Arriba del promedio de 200 días, abajo del de 50'
  if (i.arriba50) return 'Arriba del promedio de 50 días, abajo del de 200'
  return 'Abajo de sus promedios de 50 y de 200 días'
}

/**
 * Las tres partes, cada una con lo que suma al número. [{ id, titulo, valor,
 * detalle, barra (0–100), suma, de }]. `barra` es cuánto de su parte llenó.
 */
export function partes(t) {
  if (!t?.disponible) return []
  const p = t.fuente?.pesos || { amplitud: 50, indice: 25, maximos: 25 }
  const a = t.amplitud, i = t.indice, m = t.maximos
  const sp = a.sp500 || {}, panel = a.panel || {}
  const extremos = m.maximos + m.minimos
  return [
    {
      id: 'amplitud',
      titulo: 'Cuántas acciones suben de fondo',
      valor: `${num(a.pct)} %`,
      detalle: `${num(a.alcistas)} de ${num(a.medidas)} están arriba de su promedio de 200 días. ` +
        `S&P 500: ${num(sp.pct)} % · panel argentino: ${num(panel.pct)} %.`,
      barra: a.pct,
      suma: a.puntos, de: p.amplitud,
    },
    {
      id: 'indice',
      titulo: 'Tendencia del S&P 500',
      valor: textoIndice(i),
      detalle: `Está ${num(Math.abs(i.dist200), 1)} % ${i.dist200 >= 0 ? 'arriba' : 'abajo'} del de 200 días ` +
        `y ${num(Math.abs(i.dist50), 1)} % ${i.dist50 >= 0 ? 'arriba' : 'abajo'} del de 50.`,
      barra: (i.puntos / p.indice) * 100,
      suma: i.puntos, de: p.indice,
    },
    {
      id: 'maximos',
      titulo: 'Máximos contra mínimos del año',
      valor: `${num(m.maximos)} contra ${num(m.minimos)}`,
      detalle: 'Acciones que cerraron en su precio más alto de los últimos 12 meses, contra las que cerraron en el más bajo.' +
        (extremos ? '' : ' Ninguna en los extremos: cuenta como mitad y mitad.'),
      barra: extremos ? (m.maximos / extremos) * 100 : 50,
      suma: m.puntos, de: p.maximos,
    },
  ]
}

/** «Suma 28 de 50». */
export function sumaTxt(x) {
  return `Suma ${num(x.suma, 1)} de ${x.de}`
}

/** Cómo se arma, en una frase. */
export function comoSeArma(t) {
  const p = t?.fuente?.pesos || { amplitud: 50, indice: 25, maximos: 25 }
  const n = t?.universo
  return `De 0 a 100: ${p.amplitud} puntos salen de cuántas acciones suben de fondo, ${p.indice} de la ` +
    `tendencia del S&P 500 y ${p.maximos} de máximos contra mínimos. Mide ${n ? `${num(n)} acciones` : 'las acciones'}: ` +
    'las del S&P 500 y las 25 del panel argentino (el índice Merval no tiene una fuente confiable), cada una con la misma ' +
    'lectura que su ficha, en dólares.'
}

/**
 * El arco del termómetro: el punto del borde para un valor de 0 a 100 (0 a la
 * izquierda, 100 a la derecha, pasando por arriba). Centro (cx, cy), radio r.
 */
export function puntoDelArco(valor, cx, cy, r) {
  const v = Math.max(0, Math.min(100, Number(valor) || 0))
  const ang = Math.PI * (1 - v / 100)
  return [cx + r * Math.cos(ang), cy - r * Math.sin(ang)]
}

/** El trazo SVG del arco de `desde` a `hasta` (0–100). */
export function tramo(desde, hasta, cx, cy, r) {
  const [x1, y1] = puntoDelArco(desde, cx, cy, r)
  const [x2, y2] = puntoDelArco(hasta, cx, cy, r)
  const f = n => Math.round(n * 100) / 100
  return `M${f(x1)},${f(y1)} A${r},${r} 0 0 1 ${f(x2)},${f(y2)}`
}

// ─── Tu plata por sector ─────────────────────────────────────────────────────
// Viene armado de GET /api/termometro (`tu_plata`, backend termometro.tu_plata):
// el sector de cada papel tuyo es el del termómetro (la clasificación del S&P,
// GICS), no el de la torta de la Cartera. Acá sólo van las palabras.

const y = xs => (xs.length <= 1 ? xs.join('') : `${xs.slice(0, -1).join(', ')} y ${xs[xs.length - 1]}`)

/**
 * Las frases de «tu plata por sector»: [{ id, pct, cifra, texto }], una por
 * grupo con plata: la pantalla resalta `cifra` («54 %») y sigue con `texto`. `nombre(sector)` da la etiqueta del sector. Con `oculto` («Ocultar
 * saldos») el % no se muestra.
 */
export function frasesTuPlata(tp, nombre, oculto = false) {
  if (!tp) return []
  // El % con LA manera de decirlo de toda la app («12%», «menos de 1%») y su
  // ojito (`pesoVisible`, utils/parteDeTuPlata; al juntar la pieza 7, 30/10).
  const pct = p => pesoVisible(p, oculto) ?? '—'
  const out = []
  if (tp.suben?.pct > 0) {
    out.push({ id: 'suben', pct: tp.suben.pct, cifra: pct(tp.suben.pct), texto: `de tu plata está en sectores donde la mayoría de las acciones sube de fondo (${y(tp.suben.sectores.map(s => nombre(s.sector)))}).` })
  }
  if (tp.bajan?.pct > 0) {
    out.push({ id: 'bajan', pct: tp.bajan.pct, cifra: pct(tp.bajan.pct), texto: `está en sectores donde la mayoría baja (${y(tp.bajan.sectores.map(s => nombre(s.sector)))}).` })
  }
  if (tp.sin_sector?.pct > 0) {
    out.push({ id: 'sin', pct: tp.sin_sector.pct, cifra: pct(tp.sin_sector.pct), texto: `no tiene sector en esta cuenta.` })
  }
  return out
}

/** Las filas del detalle: cada sector con tus papeles, y al final «sin sector». */
export function filasTuPlata(tp, nombre) {
  if (!tp) return []
  const sectores = [...(tp.suben?.sectores || []), ...(tp.bajan?.sectores || [])]
    .map(s => ({
      id: s.sector, nombre: nombre(s.sector), pct: s.pct, papeles: s.papeles, sube: s.mercado_pct >= 50,
      mercado: `${num(s.mercado_pct)} % de sus acciones sube de fondo`,
    }))
  if (tp.sin_sector?.papeles?.length) {
    sectores.push({
      id: 'sin_sector', nombre: 'Sin sector', pct: tp.sin_sector.pct, papeles: tp.sin_sector.papeles, sube: null,
      mercado: 'No están en el S&P 500 ni en el panel argentino (ETFs, cripto, bonos, efectivo…)',
    })
  }
  return sectores
}
