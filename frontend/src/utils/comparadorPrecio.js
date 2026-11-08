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
import { primeraCompra, fechaCorta, faltanLosPrecios } from './cuantoSeMueve'

export const MAX_ACTIVOS = 4
export const PLAZOS = [['compra', 'Desde tu primera compra'], ['1a', '1 año'], ['3a', '3 años']]

// ¿Este lote u operación tuyo es el activo pedido? La regla de la ficha
// (`esElMismo` en pages/AssetDetail.jsx): el mismo papel con o sin ".BA", y si
// se pidió con ".BA", sólo lo que tenés en BYMA (GGAL.BA no es tu ADR de Schwab).
export function esElMismo(pedido, x) {
  if (!x || x.is_cash || mismoPapel(x.asset) !== mismoPapel(pedido)) return false
  return !pedido.endsWith('.BA') || isBymaHolding(x)
}

/** Tus lotes y operaciones de un activo, como los junta la ficha
 *  (pages/AssetDetail.jsx, `loadAll`): los de ESE nombre; si no hay ninguno, la
 *  ficha te manda a tu activo con otro nombre (pediste GGAL.BA y lo tenés como
 *  GGAL) y junta los de ese. Por nombre exacto y no «cualquier forma del mismo
 *  papel»: con BRK.B en Schwab y el CEDEAR BRKB en IOL, son dos fichas.
 *  { lotes, ops } */
export function lotesDelActivo(asset, posiciones = [], operaciones = []) {
  const a = (asset || '').toUpperCase()
  const de = (nombre) => ({
    lotes: posiciones.filter(p => (p.asset || '').toUpperCase() === nombre),
    ops: operaciones.filter(o => (o.asset || '').toUpperCase() === nombre),
  })
  const exactos = de(a)
  if (exactos.lotes.length || exactos.ops.length) return exactos
  const otro = [...posiciones, ...operaciones].find(x => esElMismo(a, x))
  return otro ? de((otro.asset || '').toUpperCase()) : exactos
}

/** ¿Se mira como acción argentina (su precio de BYMA)? La marca `local` de la
 *  ficha: si lo tenés, deciden tus lotes (o tus operaciones, si lo vendiste);
 *  si no, el ticker (GGAL y GGAL.BA sí; NVDA no) y, si se sabe, su `tipo` (el que
 *  dice el buscador: uno que no es de acción argentina manda). La usan Comparar
 *  y «Una cartera» del Backtesting. */
export function marcaLocal(asset, posiciones = [], operaciones = [], tipo = null) {
  const { lotes, ops } = lotesDelActivo(asset, posiciones, operaciones)
  const abiertos = lotes.filter(p => !p.is_cash)
  if (!lotes.length && !ops.length) return miradaSinTenencia(asset, tipo).accionLocal
  return esAccionLocal(asset, abiertos.length ? abiertos : ops)
}

/** El día de tu primera compra de lo que tenés HOY de alguno de los activos
 *  (el lote abierto más viejo, la regla de «Desde que lo tenés» de la ficha).
 *  null si no tenés ninguno, o si es de hoy (no hay nada que comparar todavía).
 *  `hoy`: 'YYYY-MM-DD'. */
export function primeraCompraDe(activos = [], posiciones = [], hoy = null) {
  const f = primeraCompra(activos.flatMap(a => lotesDelActivo(a, posiciones).lotes))
  return f && (!hoy || f < hoy) ? f : null
}

/** La dirección de Comparar → Precio, con `activos` ya cargados (hasta 4). */
export function urlDeComparar(activos = []) {
  const lista = [...new Set(activos.map(a => (a || '').toUpperCase()).filter(Boolean))].slice(0, MAX_ACTIVOS)
  return `/fundamentals?vista=precio${lista.length ? `&cmp=${lista.map(encodeURIComponent).join(',')}` : ''}`
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

/**
 * Por qué todos arrancan en 100 ese día, para después de «Todos arrancan en 100 el
 * …»: entre paréntesis, o '' si es el día pedido. Un hueco de precios justo antes
 * (`base_corrida_hueco`: arrancan con el primer precio después, como «Una cartera» y
 * Una regla; Nico, 08/11), un activo que cotiza hace menos (`base_corrida_por`) o el
 * borde de lo guardado (`base_corrida` solo).
 */
export function porQueArrancaAhi(res) {
  if (res?.base_corrida_hueco && res.base_corrida_por) {
    return ` (${faltanLosPrecios(res.base_corrida_por, res.base_corrida_hueco)})`
  }
  if (res?.base_corrida_por) return ` (de ${res.base_corrida_por} tenemos precios desde ese día)`
  return res?.base_corrida ? ' (los precios guardados empiezan ese día)' : ''
}

/**
 * El panel vacío cuando ningún activo se pudo dibujar porque TODOS los pedidos
 * están sin precios de la última semana (contada desde hoy: comparar.py), o null
 * si falta por otra cosa (un bono, un fondo). Sin esto decía «Probá con otro
 * activo», al lado del aviso de que eran sus precios los viejos, y si la falla
 * era nuestra mandaba a probar otros que iban a decir lo mismo (auditoría 06/11, H1).
 */
export function vaciaPorVieja(res, activos = []) {
  const faltan = (res?.faltan || []).filter(f => activos.includes(f.clave))
  if (!faltan.length || faltan.some(f => f.motivo !== 'vieja')) return null
  const ultimo = faltan.map(f => f.hasta).filter(Boolean).sort().pop()
  return {
    titulo: 'No hay precios recientes para comparar',
    texto: ultimo
      ? `Para comparar hacen falta precios de la última semana, y los últimos que tenemos son del ${fechaCorta(ultimo)}.`
      : 'Para comparar hacen falta precios de la última semana.',
  }
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
  // «Tu primera compra» sólo si el 100 es ESE día: si se corrió, se dice la fecha.
  const desde = res.plazo === 'compra' && res.base === res.desde
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
    // «Quedó abajo» y no «subió menos»: lo que bajó no subió (auditoría 29/10).
    const abajo = activos.filter(a => r(a) < r(mep)).map(a => a.nombre)
    if (abajo.length) {
      partes.push(res.moneda === 'ars'
        ? `${lista(abajo)} ${abajo.length === 1 ? 'quedó' : 'quedaron'} abajo del dólar MEP.`
        : `${lista(abajo)} ${abajo.length === 1 ? 'quedó' : 'quedaron'} abajo de lo que habría dado guardar los dólares.`)
    }
  }
  if (cer && res.moneda === 'ars') {
    const abajo = activos.filter(a => r(a) < r(cer))
    const conPesos = abajo.filter(a => r(a) > 100).map(a => a.nombre)
    const sinPesos = abajo.filter(a => r(a) < 100).map(a => a.nombre)
    const iguales = abajo.filter(a => r(a) === 100).map(a => a.nombre)
    if (conPesos.length) {
      partes.push(`${lista(conPesos)} ${conPesos.length === 1 ? 'subió' : 'subieron'} menos que la inflación: en pesos hay más, pero alcanza para menos.`)
    }
    if (iguales.length) {
      partes.push(`${lista(iguales)} ${iguales.length === 1 ? 'terminó' : 'terminaron'} con los mismos pesos, que alcanzan para menos.`)
    }
    if (sinPesos.length) {
      partes.push(`${lista(sinPesos)} ${sinPesos.length === 1 ? 'terminó' : 'terminaron'} con menos pesos que al principio.`)
    }
  }
  return partes.join(' ')
}
