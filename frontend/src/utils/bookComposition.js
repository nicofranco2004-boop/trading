// bookComposition — el libro del asesor, agregado para las tres tortas.
// ═══════════════════════════════════════════════════════════════════════════
// Traduce lo que devuelve GET /api/advisor/book/composition al shape que ya
// consumen CompositionDonut + computeClassBreakdown + computeSectorBreakdown.
//
// ── Por qué las filas del backend se pueden usar como si fueran posiciones ──
// El contrato del endpoint está diseñado para eso: cada fila trae `asset`,
// `asset_type`, `is_cash` y `value_usd`, que es exactamente lo que leen los
// clasificadores del retail. La única señal que classifyAsset saca de la lista
// de brokers — si la posición cotiza en BYMA — viene pre-resuelta en
// `is_ar_market` (ver la cabecera de assetClass.js). Así el libro y la cartera
// de cada cliente se clasifican con EL MISMO código: no pueden divergir.
//
// ── Lo único que este módulo agrega de verdad: la torta POR ACTIVO ─────────
// Las de tipo y sector salen tal cual de computeClassBreakdown /
// computeSectorBreakdown. La de activo no existe en retail: ahí el corte por
// activo es una BARRA top-5 (AssetBreakdownBar), y la razón es la cola larga.
// En una cartera de ~30 activos un donut funciona; un libro de 100 clientes
// toca ~486 tickers distintos, así que casi todos caen bajo el 1,5% que
// CompositionDonut manda a "Otros" y el "Otros" se come la torta.
//
// La respuesta acá es explícita en vez de emergente: top-N por valor como
// porciones reales, y TODO el resto en una sola porción "Resto (N activos)"
// que se puede desplegar para ver qué hay adentro. Un "Otros" que dice cuántos
// son y se abre no es el mismo objeto que un "Otros" del 60% sin explicación.

import { normalizeTicker } from './assetClass'
import { fciLabel } from './valuation'
import { toDistributionAiParams } from './distributionAi'

// Cuántos activos se muestran como porción propia antes del "Resto". 12 entra
// cómodo en la leyenda del donut y cubre la parte de la torta que un asesor
// puede efectivamente mirar de a uno.
export const DEFAULT_TOP_ASSETS = 12

// Cuántos activos dispersos entran en el packet de la IA (vienen ordenados
// por amplitud desde el backend, así que son los que más se abren).
const MAX_DISPERSOS = 4

// Paleta de porciones. Son los data accents del design system (los mismos que
// usan ASSET_CLASS_META y SECTOR_META). Nunca rendi-neg (#FF5360): en esta app
// el rojo es pérdida, no una categoría.
const ASSET_PALETTE = [
  '#5B9DF9', '#21D07A', '#8B7DFF', '#E8B14A', '#46C6E0', '#D97BE0',
  '#9AA85C', '#F2994A', '#7C6BF5', '#E08AA8', '#6FA8A0', '#A87C5C',
  '#4F7CA8', '#C98A2E',
]
const REST_COLOR = '#5A6478'

/**
 * assetSlicesFromRows — la torta "Distribución de activos" del libro.
 *
 * Consolida por TICKER, no por (ticker, mercado): la exposición a Apple es la
 * exposición a Apple, la haya comprado el cliente como CEDEAR en Balanz o como
 * acción en Schwab. Las tortas de tipo y sector sí los separan, porque ahí la
 * pregunta es otra. Normalizamos el `.BA` que algunos importadores dejan
 * pegado, si no el mismo activo saldría partido en dos porciones.
 *
 * @param {Array} rows         filas de /advisor/book/composition
 * @param {Array} extraSlices  porciones que no son filas (plazos fijos)
 * @param {number} topN        cuántos activos como porción propia
 * @returns {{items, total, unclassified}} — mismo contrato que
 *          computeClassBreakdown, así CompositionDonut no ramifica.
 */
export function assetSlicesFromRows(rows = [], extraSlices = [], topN = DEFAULT_TOP_ASSETS) {
  const byAsset = new Map()
  let total = 0

  for (const r of rows) {
    const value = r?.value_usd
    if (value == null || !(value > 0)) continue
    const ticker = normalizeTicker(r.asset)
    if (!ticker) continue
    if (!byAsset.has(ticker)) byAsset.set(ticker, { value: 0, clients: 0 })
    const b = byAsset.get(ticker)
    b.value += value
    // `clients` es un conteo de DISTINTOS por fila, así que sumar dos filas del
    // mismo ticker (CEDEAR + acción US) puede contar dos veces al mismo
    // cliente. Nos quedamos con el máximo: es el piso correcto y nunca miente
    // para arriba, que es lo que importa en un dato que se lee como "en cuánta
    // gente está".
    b.clients = Math.max(b.clients, r.clients || 0)
    total += value
  }

  for (const extra of extraSlices) {
    if (!extra?.key || !(extra.value > 0)) continue
    total += extra.value
  }

  if (total <= 0) {
    return { items: [], total: 0, unclassified: { value: 0, pct: 0, assets: [] } }
  }

  const sorted = [...byAsset.entries()]
    .map(([asset, b]) => ({ asset, ...b }))
    .sort((a, b) => b.value - a.value)

  const head = sorted.slice(0, topN)
  const tail = sorted.slice(topN)

  const items = head.map((a, i) => ({
    key: a.asset,
    label: fciLabel(a.asset),
    color: ASSET_PALETTE[i % ASSET_PALETTE.length],
    value: a.value,
    pct: (a.value / total) * 100,
    clients: a.clients,
    // Sin `assets`: la porción YA es un activo, desplegarla no tendría qué
    // mostrar. CompositionDonut solo pone el chevron si hay detalle.
  }))

  // Las porciones sintéticas (plazos fijos) van después de los activos: no
  // tienen ticker, así que no compiten por el top-N.
  for (const extra of extraSlices) {
    if (!extra?.key || !(extra.value > 0)) continue
    items.push({
      key: extra.key,
      label: extra.label || extra.key,
      color: extra.color || REST_COLOR,
      value: extra.value,
      pct: (extra.value / total) * 100,
      pnl: extra.pnl || null,
    })
  }

  if (tail.length > 0) {
    const restValue = tail.reduce((s, a) => s + a.value, 0)
    items.push({
      key: '__resto__',
      label: `Resto (${tail.length} ${tail.length === 1 ? 'activo' : 'activos'})`,
      color: REST_COLOR,
      value: restValue,
      pct: (restValue / total) * 100,
      // Acá sí hay detalle, y es el punto: "resto" tiene que poder contestar
      // "resto de QUÉ". Los % son sobre el total de la torta, así que la lista
      // se lee como una descomposición de la porción.
      assets: tail.map(a => ({
        asset: a.asset, value: a.value, pct: (a.value / total) * 100,
      })),
    })
  }

  // No hay "sin clasificar" en el eje activo: un ticker es un ticker.
  return { items, total, unclassified: { value: 0, pct: 0, assets: [] } }
}

/**
 * mostHeldAssets — los activos que más clientes tienen.
 *
 * La torta es por VALOR (es la distribución del libro, ponderada por
 * patrimonio administrado). Pero para un asesor "¿en qué están casi todos?" es
 * una pregunta distinta y a veces más útil que "¿dónde está la plata?" — un
 * activo chico que está en 20 de 25 carteras es una decisión suya, no del
 * mercado. Va como pie de la card, sin inventar una segunda métrica adentro
 * del donut.
 */
export function mostHeldAssets(rows = [], limit = 4) {
  const byAsset = new Map()
  for (const r of rows) {
    const ticker = normalizeTicker(r.asset)
    if (!ticker || !(r.value_usd > 0)) continue
    byAsset.set(ticker, Math.max(byAsset.get(ticker) || 0, r.clients || 0))
  }
  return [...byAsset.entries()]
    .map(([asset, clients]) => ({ asset: fciLabel(asset), clients }))
    .filter(a => a.clients > 1)
    .sort((a, b) => b.clients - a.clients || a.asset.localeCompare(b.asset))
    .slice(0, limit)
}

/**
 * pfSlice — los plazos fijos del libro como porción sintética.
 *
 * No son posiciones (viven en su propia tabla) pero sí son patrimonio
 * administrado. Mismo mecanismo que usa el Dashboard retail: `extraSlices`.
 * Devuelve null si no hay ninguno, para no dibujar una porción en cero.
 */
export function pfSlice(included, key, label = null, color = null) {
  const value = included?.plazos_fijos_usd || 0
  if (!(value > 0)) return null
  const cost = included?.plazos_fijos_invested_usd || 0
  const slice = { key, value }
  // El interés devengado es el resultado del plazo fijo. Sin el costo al lado,
  // su capital entraría en el peso de la porción pero no en el denominador
  // del rendimiento.
  if (cost > 0) slice.pnl = { total: value - cost, cost }
  // `label`/`color` solo los usa la torta por activo: en las de tipo y sector
  // la porción ya existe en el vocabulario (plazo_fijo / renta_fija) y se
  // dibuja con su meta.
  if (label) slice.label = label
  if (color) slice.color = color
  return slice
}

/**
 * realizedToOps — lo cerrado y la renta del libro, con forma de operaciones.
 *
 * computePnlByKey (assetPnl.js) suma tres patas: no realizado (posiciones
 * abiertas), realizado (ventas) y renta (dividendos, cupones, intereses). Las
 * posiciones abiertas del libro ya vienen como `rows`; esto convierte el
 * agregado de `realized_by_asset` en las filas que esa función espera, para
 * que el resultado por porción del asesor salga del MISMO motor que el del
 * cliente en su Dashboard.
 *
 * ── El % de la venta ──────────────────────────────────────────────────────
 * computePnlByKey despeja el costo de cada venta del par (pnl_usd, pnl_pct) —
 * no de `cost_basis_consumed`, que está 100% NULL en las filas reales, ni de
 * `entry_price × quantity`, que está en moneda nativa y tiene un bug abierto
 * de monedas mezcladas en la misma fila. Así que le devolvemos el `pnl_pct`
 * que reconstruye EXACTAMENTE el `cost_usd` que el backend ya sumó.
 *
 * Si al backend le faltó el costo de alguna venta (`cost_incomplete`),
 * mandamos el % en null: el monto sigue siendo válido, la tasa no, y
 * computePnlByKey la oculta en vez de publicar una inflada.
 */
export function realizedToOps(rows = []) {
  const ops = []
  for (const r of rows || []) {
    if (!r?.asset) continue
    const base = {
      asset: r.asset,
      broker: null,               // el hint de tipo viene en la fila, no de posiciones
      asset_type: r.asset_type || null,
      is_ar_market: r.is_ar_market,
    }
    if (r.realized_usd) {
      const pct = (!r.cost_incomplete && r.cost_usd > 0)
        ? (r.realized_usd / r.cost_usd) * 100
        : null
      ops.push({ ...base, op_type: 'Venta', pnl_usd: r.realized_usd, pnl_pct: pct })
    }
    if (r.income_usd) {
      // La renta no aporta costo al denominador (ver la cabecera de assetPnl).
      ops.push({ ...base, op_type: 'Dividendo', pnl_usd: r.income_usd, pnl_pct: null })
    }
  }
  return ops
}

/**
 * toBookCompositionAiParams — el corte del libro, listo para mandarle a la IA.
 *
 * Extiende el packet de retail (toDistributionAiParams) con lo que solo tiene
 * sentido sobre un libro: sobre cuántos clientes está medido, y qué activos
 * están en más carteras. Sin `mas_difundidos` el modelo no puede distinguir
 * una postura del asesor (muchas carteras) de una cartera grande dominando el
 * promedio ponderado (una sola) — y son dos conversaciones distintas.
 *
 * Claves cortas (`a`/`c`) por el mismo motivo que en distributionAi: viajan
 * por red y entran en el contexto del modelo.
 */
export function toBookCompositionAiParams(breakdown, { clients, mostHeld, spread } = {}) {
  const params = toDistributionAiParams(breakdown)
  if (clients > 0) params.clientes = clients
  const difundidos = (mostHeld || []).map(a => ({ a: a.asset, c: a.clients }))
  if (difundidos.length) params.mas_difundidos = difundidos
  // Los activos donde más se abren los clientes entre sí. Sin esto el modelo
  // solo ve el % agrupado y no puede decir lo único que de verdad importa en
  // un libro: que un promedio sano puede tener a alguien en rojo adentro.
  const dispersos = (spread || [])
    .slice(0, MAX_DISPERSOS)
    .map(s => ({ a: s.asset, c: s.clients, min: s.min_pct, max: s.max_pct }))
  if (dispersos.length) params.mas_dispersos = dispersos
  return params
}

/**
 * attachSpread — pega el rango de retorno entre clientes a cada activo del
 * breakdown, sin tocar los agregadores compartidos.
 *
 * Por qué acá y no dentro de computeClassBreakdown: ese módulo es el del
 * retail y no sabe de clientes. El rango es información del libro, así que se
 * adosa después, sobre el resultado ya calculado. Las porciones y los % no se
 * tocan — solo se agrega un campo a cada activo del desglose.
 *
 * La clave es el ticker normalizado, juntando los dos mercados: el backend ya
 * junta AAPL-CEDEAR con AAPL-acción para el rango, porque "de los clientes que
 * tienen AAPL, el peor está en X y el mejor en Y" sigue siendo cierto y es
 * cómo la torta por activo ya consolida.
 */
export function attachSpread(breakdown, spreadRows) {
  const bySpread = new Map(
    (spreadRows || []).map(s => [normalizeTicker(s.asset), s]),
  )
  if (bySpread.size === 0 || !breakdown?.items?.length) return breakdown
  return {
    ...breakdown,
    items: breakdown.items.map(i => (
      i.assets?.length
        ? { ...i, assets: i.assets.map(a => {
            const s = bySpread.get(normalizeTicker(a.asset))
            return s ? { ...a, spread: s } : a
          }) }
        : i
    )),
  }
}
