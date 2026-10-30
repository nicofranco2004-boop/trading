// mapaCartera.js — el mapa de calor de TU cartera (Dashboard, pieza 8): un
// cuadro por activo que tenés; el tamaño es lo que pesa en tu plata y el color
// sale del selector «Color por» (Hoy · Tendencia · Contra tu promedio).
// ════════════════════════════════════════════════════════════════════════════
// Nada se calcula acá por primera vez. Cada número viene de donde ya se cuenta:
//   · QUÉ tenés y CUÁNTO PESA: `tenencias` y `sin_medir` de POST /api/tecnico/lista
//     (senales_semana.cartera / peso: LA valuación de Tu lista, de Señales y del
//     % alcista de la Cartera). Las filas las arma `filasDeLaLista`, la misma
//     función de Tu lista: el 12 % de un cuadro es el «Sí · 12%» de su fila.
//   · la TENDENCIA: `tendencia()` de la radiografía (la tarjeta «Largo plazo» de
//     la ficha), sobre la lectura del mismo pedido.
//   · HOY: `variacionDelDiaUsd` (utils/variacionDelDia.js), la «Var. día» de la
//     Cartera, lote por lote; el cuadro suma sus lotes.
//   · CONTRA TU PROMEDIO: el resultado no realizado de cada lote que ya arma el
//     Dashboard (`positionsForInsight`, el de su frase de arriba y de las tortas):
//     lo que vale hoy contra lo que pagaste, que es tu precio de hoy contra tu
//     precio promedio de compra.
// Los lotes se juntan con la marca `local` lote por lote (`esLoteLocal`), la
// misma con que el servidor separa GGAL de BYMA del ADR de Nueva York.

import { clave } from './radiografia'
import { filasDeLaLista } from './listaTecnica'
import { esLoteLocal } from './accionLocal'
import { polarityColor, CORTES_DIA, CORTES_PROMEDIO } from './polarityScale'

export const MODOS = [
  { id: 'hoy', label: 'Hoy' },
  { id: 'tendencia', label: 'Tendencia' },
  { id: 'promedio', label: 'Contra tu promedio' },
]

/** Lo que dice el renglón de arriba del mapa según el modo. Cada término
 *  explicado en la misma oración. */
export const QUE_ES_EL_COLOR = {
  hoy: 'El color, cuánto se movió hoy contra el cierre de la rueda anterior.',
  tendencia: 'El color, su tendencia de fondo: alcista si el precio está arriba de su promedio de los últimos 200 días, bajista si está abajo.',
  promedio: 'El color, cuánto está el precio de hoy arriba o abajo de tu precio promedio de compra.',
}

const SIN_LECTURA = { bg: 'rgb(var(--bg-3))', ink: 'rgb(var(--ink-2))', sign: 0, step: 0 }
// La tendencia es sí o no, no tiene intensidad: alcista y bajista van con el
// paso del medio de la rampa (un +1,5 con estos cortes cae en el paso 2).
const CORTES_TENDENCIA = { plano: 0.5, pasos: [1, 2] }

/**
 * Los lotes del Dashboard, juntos por cuadro. `lotes`: [{ p (el lote de
 * /positions), dia ({ amount, base } en dólares | null), valueUsd, pnlUsd }].
 * → Map clave → { diaUsd, diaBase, conDia, diaPct, valor, resultado }
 */
export function sumarLotes(lotes = []) {
  const out = new Map()
  for (const { p, dia, valueUsd, pnlUsd } of lotes) {
    if (!p || p.is_cash || !p.asset) continue
    const k = clave(String(p.asset).toUpperCase(), esLoteLocal(p))
    const a = out.get(k) || { diaUsd: 0, diaBase: 0, conDia: false, diaPct: undefined, valor: 0, resultado: 0, conValor: false }
    if (dia) {
      a.diaUsd += dia.amount; a.diaBase += dia.base; a.conDia = true
      // Si todos los lotes se movieron el mismo % (cotizan con el mismo precio,
      // que es lo normal), ése es el % del cuadro, tal cual lo dice la fila de la
      // Cartera. Dividir los montos da el mismo número con otro último decimal, y
      // en un empate de redondeo la Cartera decía −3,8 % y el mapa −3,9 % (YPFD).
      a.diaPct = a.diaPct === undefined || a.diaPct === dia.pct ? dia.pct : null
    }
    if (valueUsd != null && pnlUsd != null) { a.valor += valueUsd; a.resultado += pnlUsd; a.conValor = true }
    out.set(k, a)
  }
  return out
}

/**
 * Los cuadros, de más a menos peso. Cada uno:
 *   { clave, nombre, detalle, ruta (null = no abre ficha), peso (fracción),
 *     fondo (la tendencia de la ficha), hoy: { pct, usd, base } | null,
 *     promedio: { pct } | null, tipo: 'activo' | 'efectivo' | 'plazos_fijos' }
 * `hoy` null = ese activo no tiene cierre anterior (un bono sin cobertura, un
 * fondo, un precio cargado a mano) o no llegó el precio.
 */
export function cuadrosDelMapa({ tenencias = [], sinMedir = null, indice = null, lotes = [], hoy } = {}) {
  const porClave = sumarLotes(lotes)
  const filas = filasDeLaLista({ tenencias, seguidos: [], indice, ...(hoy ? { hoy } : {}) })
  const cuadros = filas.filter(f => f.peso > 0).map(f => {
    const a = porClave.get(f.clave)
    const costo = a ? a.valor - a.resultado : 0
    return {
      clave: f.clave,
      nombre: f.nombre,
      detalle: f.detalle || null,
      ruta: f.ruta,
      peso: f.peso / 100,
      fondo: f.fondo,
      hoy: a?.conDia && a.diaBase > 0 ? { pct: a.diaPct ?? a.diaUsd / a.diaBase, usd: a.diaUsd, base: a.diaBase } : null,
      promedio: a?.conValor && costo > 0 ? { pct: a.resultado / costo } : null,
      tipo: 'activo',
    }
  })
  const sinLectura = (porque, motivo) => ({ id: 'sin', palabra: 'Sin lectura', porque, motivo })
  if (sinMedir?.efectivo > 0) {
    cuadros.push({
      clave: 'efectivo', nombre: 'Efectivo', detalle: null, ruta: null, peso: sinMedir.efectivo,
      fondo: sinLectura('no_se_mide', 'El efectivo no tiene historia de precios: no se le mide la tendencia.'),
      hoy: null, promedio: null, tipo: 'efectivo',
    })
  }
  if (sinMedir?.plazos_fijos > 0) {
    cuadros.push({
      clave: 'plazos_fijos', nombre: 'Plazos fijos', detalle: null, ruta: null, peso: sinMedir.plazos_fijos,
      fondo: sinLectura('no_se_mide', 'Un plazo fijo no tiene historia de precios: no se le mide la tendencia.'),
      hoy: null, promedio: null, tipo: 'plazos_fijos',
    })
  }
  return cuadros.sort((x, y) => y.peso - x.peso)
}

/** El color de un cuadro en un modo: { bg, ink } listos para `style`. */
export function colorDelCuadro(c, modo) {
  if (modo === 'tendencia') {
    if (c.fondo?.id === 'alcista') return polarityColor(1.5, CORTES_TENDENCIA)
    if (c.fondo?.id === 'bajista') return polarityColor(-1.5, CORTES_TENDENCIA)
    return SIN_LECTURA
  }
  if (modo === 'promedio') return c.promedio ? polarityColor(c.promedio.pct * 100, CORTES_PROMEDIO) : SIN_LECTURA
  return c.hoy ? polarityColor(c.hoy.pct * 100, CORTES_DIA) : SIN_LECTURA
}

/** Lo que más sumó y lo que más restó hoy, en dólares: { sumo, resto } (cada
 *  uno un cuadro, o null si nadie subió / nadie bajó). */
export function losExtremosDeHoy(cuadros = []) {
  let sumo = null, resto = null
  for (const c of cuadros) {
    if (!c.hoy) continue
    if (c.hoy.usd > 0 && (!sumo || c.hoy.usd > sumo.hoy.usd)) sumo = c
    if (c.hoy.usd < 0 && (!resto || c.hoy.usd < resto.hoy.usd)) resto = c
  }
  return { sumo, resto }
}

/** La suma de lo que se movió hoy cada cuadro (dólares) y su %. Para medirla
 *  contra el «Hoy» del Dashboard, que sale de otra cuenta (la foto de ayer). */
export function sumaDeHoy(cuadros = []) {
  let usd = 0, base = 0
  for (const c of cuadros) {
    if (!c.hoy) continue
    usd += c.hoy.usd
    base += c.hoy.base
  }
  return { usd, pct: base > 0 ? usd / base : null }
}
