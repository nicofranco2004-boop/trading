// assetPnl — cuánto ganaste con cada clase de activo / sector.
// ═══════════════════════════════════════════════════════════════════════════
// El complemento de assetClass/assetSector: esos dicen CUÁNTO tenés en cada
// porción, éste dice CÓMO TE FUE en cada una.
//
// ── Las tres patas del resultado ──────────────────────────────────────────
// Un rendimiento por clase que solo mire las posiciones abiertas miente, y no
// poco. Medido contra la base de dev: los dividendos suman US$10.972 y los
// intereses US$9.695, contra US$2.652 de ventas realizadas. Un bono que te
// pagó renta toda su vida tiene su rendimiento EN LOS CUPONES, no en la
// variación del precio — mostrarlo sin ellos lo pinta como si no hubiera
// rendido nada. Así que sumamos:
//     no realizado (posiciones abiertas) + realizado (ventas) + renta
//     (dividendos, cupones, intereses)
//
// ── El denominador: por qué NO usamos entry_price ─────────────────────────
// Para el % hace falta el costo en USD de lo que se cerró. Las candidatas:
//   • `cost_basis_consumed` → está 100% NULL en las filas reales. Descartada.
//   • `entry_price × quantity` → está en la MONEDA NATIVA de la operación, y
//     hay un bug abierto conocido donde entry y exit quedan en monedas
//     distintas en la misma fila. Mezclarlo con USD da errores de ~1400×.
//   • `pnl_usd / (pnl_pct/100)` → ✅ las dos puntas ya están normalizadas a
//     USD y son mutuamente consistentes. Verificado contra filas reales.
// Por eso el costo de una venta se DESPEJA del par (pnl_usd, pnl_pct).
//
// La renta (dividendos/cupones) NO aporta costo al denominador: no invertiste
// para cobrar el cupón — el capital ya está contado, por la posición abierta o
// por el costo de la venta que la cerró. Suma arriba, no abajo.

import { normalizeTicker } from './assetClass'

// Operaciones que no son un activo: conversiones de moneda (ARS→USDT). Tienen
// pnl 0, pero clasificarlas ensucia la porción "Sin clasificar".
function isRealAssetOp(op) {
  const asset = String(op?.asset || '')
  if (!asset || asset.includes('→')) return false
  if (String(op?.op_type || '').toUpperCase().startsWith('CONVERSION')) return false
  return true
}

const emptyBucket = () => ({
  realized: 0, unrealized: 0, income: 0, cost: 0,
  costIncomplete: false, byAsset: new Map(),
})

function bucketFor(map, key) {
  if (!map.has(key)) map.set(key, emptyBucket())
  return map.get(key)
}

function assetFor(bucket, ticker) {
  if (!bucket.byAsset.has(ticker)) {
    bucket.byAsset.set(ticker, { pnl: 0, cost: 0, costIncomplete: false })
  }
  return bucket.byAsset.get(ticker)
}

/**
 * computePnlByKey
 *
 * @param {Array}    positions   posiciones abiertas ya valuadas
 *                               ({ asset, broker, asset_type, value_usd, pnl_usd })
 * @param {Array}    operations  filas de /api/operations (ventas, dividendos…)
 * @param {Array}    brokers     [{ name, currency }]
 * @param {Function} classify    classifyAsset o classifySector
 * @returns {Map<string, {total, realized, unrealized, income, cost, pct, costIncomplete, byAsset}>}
 *          `pct` es null cuando no hay costo confiable con el que dividir.
 */
export function computePnlByKey(positions = [], operations = [], brokers = [], classify) {
  const out = new Map()

  // Hint de tipo para las operaciones: las filas de `operations` no guardan
  // asset_type, pero si todavía tenés el activo abierto en ese broker sabemos
  // qué es. Sin esto, la venta de un CEDEAR en un broker USD se clasificaría
  // como acción US y la ganancia caería en la porción equivocada.
  const typeHint = new Map()
  for (const p of positions) {
    if (!p?.asset_type) continue
    typeHint.set(`${p.broker}|${normalizeTicker(p.asset)}`, p.asset_type)
  }

  // ── Pata 1: posiciones abiertas ──────────────────────────────────────────
  for (const p of positions) {
    if (p?.is_cash) continue           // el efectivo no tiene rendimiento acá
    if (p?.pnl_usd == null) continue   // sin precio no sabemos cómo le fue
    const key = classify(p, brokers)
    const b = bucketFor(out, key)
    const cost = (p.value_usd ?? 0) - p.pnl_usd
    b.unrealized += p.pnl_usd
    b.cost += cost
    const a = assetFor(b, normalizeTicker(p.asset))
    a.pnl += p.pnl_usd
    a.cost += cost
  }

  // ── Patas 2 y 3: lo cerrado y la renta ───────────────────────────────────
  for (const op of operations) {
    if (!isRealAssetOp(op)) continue
    const pnl = op.pnl_usd
    if (pnl == null || pnl === 0) continue

    const ticker = normalizeTicker(op.asset)
    const hinted = typeHint.get(`${op.broker}|${ticker}`) || null
    const key = classify({ asset: op.asset, broker: op.broker, asset_type: hinted, is_cash: 0 }, brokers)
    const b = bucketFor(out, key)
    const a = assetFor(b, ticker)

    const tipo = String(op.op_type || '').toUpperCase()
    const esRenta = tipo.includes('DIVIDENDO') || tipo.includes('INTER') || tipo.includes('CUPON')

    if (esRenta) {
      // Renta: suma al resultado, no al capital invertido.
      b.income += pnl
      a.pnl += pnl
      continue
    }

    b.realized += pnl
    a.pnl += pnl
    // Costo despejado del par (pnl_usd, pnl_pct) — ver cabecera.
    const pct = op.pnl_pct
    if (pct != null && pct !== 0) {
      const cost = pnl / (pct / 100)
      if (Number.isFinite(cost) && cost > 0) {
        b.cost += cost
        a.cost += cost
      } else {
        b.costIncomplete = true
        a.costIncomplete = true
      }
    } else {
      // Sin % no hay con qué despejar el costo. El monto sigue siendo válido;
      // el porcentaje de esta porción deja de serlo y lo decimos.
      b.costIncomplete = true
      a.costIncomplete = true
    }
  }

  // ── Cierre ───────────────────────────────────────────────────────────────
  for (const b of out.values()) {
    b.total = b.realized + b.unrealized + b.income
    b.pct = (!b.costIncomplete && b.cost > 0) ? (b.total / b.cost) * 100 : null
    b.byAsset = [...b.byAsset]
      .map(([asset, v]) => ({
        asset,
        total: v.pnl,
        cost: v.cost,
        pct: (!v.costIncomplete && v.cost > 0) ? (v.pnl / v.cost) * 100 : null,
      }))
      .sort((x, y) => y.total - x.total)
  }
  return out
}

/**
 * mergePnl — combina el resultado calculado de una porción con el que trae una
 * porción sintética (plazos fijos). Devuelve null si no hay ninguno, para que
 * la UI sepa distinguir "sin datos" de "cero".
 */
export function mergePnl(computed, extra) {
  if (!computed && !extra) return null
  if (!extra) return computed
  const total = (computed?.total || 0) + (extra.total || 0)
  const cost = (computed?.cost || 0) + (extra.cost || 0)
  const incomplete = Boolean(computed?.costIncomplete)
  return {
    ...(computed || { realized: 0, unrealized: 0, income: 0, byAsset: [] }),
    total,
    cost,
    costIncomplete: incomplete,
    pct: (!incomplete && cost > 0) ? (total / cost) * 100 : null,
  }
}
