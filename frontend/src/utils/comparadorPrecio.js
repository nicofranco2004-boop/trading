// comparadorPrecio — lo que la pestaña «Precio» de Comparar necesita de tus lotes
// y las palabras de abajo del gráfico (pieza 16).
// ═══════════════════════════════════════════════════════════════════════════
// LA CUENTA NO ESTÁ ACÁ. Arrancar en 100 el mismo día y pasar a pesos o a
// dólares lo hace el servidor (backend/comparar.py, GET /api/comparar/precio),
// con la serie de la ficha. Acá sólo se decide qué pedir —qué activo es una
// acción argentina y desde cuándo lo tenés— con las MISMAS reglas que la ficha,
// y se ponen en palabras los números que vuelven. Nunca recomienda: describe.
import { isBymaHolding } from './valuation'
import { esAccionLocal } from './accionLocal'
import { mismoPapel, miradaSinTenencia } from './buscadorRapido'
import { primeraCompra, fechaCorta } from './cuantoSeMueve'

export const MAX_ACTIVOS = 4
export const PLAZOS = [['compra', 'Desde tu primera compra'], ['1a', '1 año'], ['3a', '3 años']]

// ¿Este lote u operación tuyo es el activo pedido? La regla de la ficha
// (`esElMismo` en pages/AssetDetail.jsx): el mismo papel con o sin ".BA", y si
// se pidió con ".BA", sólo lo que tenés en BYMA (GGAL.BA no es tu ADR de Schwab).
export function esElMismo(pedido, x) {
  if (!x || x.is_cash || mismoPapel(x.asset) !== mismoPapel(pedido)) return false
  return !pedido.endsWith('.BA') || isBymaHolding(x)
}

/** ¿Se mira como acción argentina (su precio de BYMA)? La marca `local` de la
 *  ficha: si lo tenés, deciden tus lotes (o tus operaciones, si lo vendiste);
 *  si no, el ticker (GGAL y GGAL.BA sí; NVDA no). */
export function marcaLocal(asset, posiciones = [], operaciones = []) {
  const lotes = posiciones.filter(p => esElMismo(asset, p))
  const ops = operaciones.filter(o => esElMismo(asset, o))
  if (!lotes.length && !ops.length) return miradaSinTenencia(asset).accionLocal
  return esAccionLocal(asset, lotes.length ? lotes : ops)
}

/** El día de tu primera compra de lo que tenés HOY de alguno de los activos
 *  (el lote abierto más viejo, la regla de «Desde que lo tenés» de la ficha).
 *  null si no tenés ninguno. */
export function primeraCompraDe(activos = [], posiciones = []) {
  return primeraCompra(posiciones.filter(p => activos.some(a => esElMismo(a, p))))
}

/** La dirección del pedido. */
export function urlDelPedido({ activos, locales, moneda, plazo, desde }) {
  const q = new URLSearchParams({ activos: activos.join(','), moneda, plazo })
  if (locales.length) q.set('local', locales.join(','))
  if (plazo === 'compra' && desde) q.set('desde', desde)
  return `/comparar/precio?${q}`
}

/** Las series en filas para el gráfico: una por día, con el valor de cada
 *  serie que tuvo dato ese día (la cripto tiene sábados; la bolsa no). */
export function filasDelGrafico(series = []) {
  const porDia = new Map()
  for (const s of series) {
    for (const p of s.puntos || []) {
      if (!porDia.has(p.d)) porDia.set(p.d, { d: p.d })
      porDia.get(p.d)[s.clave] = p.v
    }
  }
  return [...porDia.values()].sort((a, b) => (a.d < b.d ? -1 : a.d > b.d ? 1 : 0))
}

/** «Cada US$ 100 del 14/03/25 hoy son US$ 158». */
export function monto(v, moneda) {
  const n = Math.round(v).toLocaleString('es-AR')
  return `${moneda === 'ars' ? '$' : 'US$'} ${n}`
}

function lista(nombres) {
  if (nombres.length <= 1) return nombres.join('')
  return `${nombres.slice(0, -1).join(', ')} y ${nombres[nombres.length - 1]}`
}

// Se compara lo que se VE: los números redondeados de la pantalla. Con 136,7
// contra 137,3 la pantalla dice «137» y «137»; la frase no puede decir que uno
// le ganó al otro.
const r = (s) => Math.round(s.final)

/**
 * Lo que dicen los números, en una o dos frases. Describe lo que pasó desde el
 * día del 100; no dice qué hacer.
 */
export function fraseComparacion(res) {
  const series = res?.series || []
  const activos = series.filter(s => s.tipo === 'activo')
  if (!activos.length || !res.base) return ''
  const vara = (k) => series.find(s => s.clave === k)
  const sp = vara('sp500'), mep = vara('mep'), cer = vara('cer')
  const desde = res.plazo === 'compra' && !res.base_corrida_por
    ? 'desde tu primera compra'
    : `desde el ${fechaCorta(res.base)}`
  const partes = []

  if (sp) {
    const ganaron = activos.filter(a => r(a) > r(sp))
    const iguales = activos.filter(a => r(a) === r(sp)).map(a => a.nombre)
    if (activos.length === 1) {
      partes.push(`${activos[0].nombre} ${ganaron.length ? 'le ganó al' : iguales.length ? 'quedó igual que el' : 'quedó abajo del'} S&P 500 ${desde}.`)
    } else {
      const n = ganaron.length
      partes.push(n === 0
        ? `Ninguno de los ${activos.length} le ganó al S&P 500 ${desde}.`
        : n === activos.length
          ? `Los ${activos.length} le ganaron al S&P 500 ${desde}.`
          : `${n} de los ${activos.length} le ${n === 1 ? 'ganó' : 'ganaron'} al S&P 500 ${desde}.`)
      if (iguales.length) partes.push(`${lista(iguales)} ${iguales.length === 1 ? 'quedó' : 'quedaron'} igual.`)
    }
  }
  if (mep) {
    const abajo = activos.filter(a => r(a) < r(mep)).map(a => a.nombre)
    if (abajo.length) {
      partes.push(res.moneda === 'ars'
        ? `${lista(abajo)} ${abajo.length === 1 ? 'subió' : 'subieron'} menos que el dólar MEP.`
        : `${lista(abajo)} ${abajo.length === 1 ? 'quedó' : 'quedaron'} abajo de lo que habría dado guardar los dólares.`)
    }
  }
  if (cer && res.moneda === 'ars') {
    const abajo = activos.filter(a => r(a) < r(cer))
    const conPesos = abajo.filter(a => r(a) >= 100).map(a => a.nombre)
    const sinPesos = abajo.filter(a => r(a) < 100).map(a => a.nombre)
    if (conPesos.length) {
      partes.push(`${lista(conPesos)} ${conPesos.length === 1 ? 'subió' : 'subieron'} menos que la inflación: en pesos hay más, pero alcanza para menos.`)
    }
    if (sinPesos.length) {
      partes.push(`${lista(sinPesos)} ${sinPesos.length === 1 ? 'terminó' : 'terminaron'} con menos pesos que al principio.`)
    }
  }
  return partes.join(' ')
}
