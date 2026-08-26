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

// ── Cuándo el % deja de ser un rendimiento ────────────────────────────────
// El % sale de total/costo, y el costo es el que la posición tiene HOY. Eso se
// rompe cuando la plata se ganó sobre un capital que ya no está: un bono que
// amortizó casi todo, o una posición vendida en su mayor parte, sigue sumando
// años de cupones o dividendos contra un costo residual de dos pesos. Medido
// en el libro demo: GD35 con US$15 de posición y US$1.463 de renta cobrada
// daba +9.804%. Eso no comunica un rendimiento, comunica que el denominador
// se evaporó.
//
// No hay forma de reconstruir el capital histórico desde acá (haría falta el
// costo de lo amortizado, que no está en `positions`). Así que aplicamos la
// misma regla que el resto del archivo ya usa para el costo incompleto:
// cuando el número no se sostiene, mostramos el MONTO y ocultamos la tasa —
// falta el costo, no el dato. El umbral es una heurística declarada, no una
// verdad: arriba de 10× el costo (>1000%) ya no hay lectura posible.
const MAX_PNL_TO_COST = 10

// ── `pnl_usd` no siempre es USD ───────────────────────────────────────────
// La columna se llama así, pero en las COBRANZAS DE RENTA FIJA guarda el monto
// en la MONEDA DEL BROKER: bond_cashflow inserta `net_amount` tal cual. Un
// cupón de $125.000 en un broker en pesos entra a la columna como 125000, y
// cualquiera que la sume cruda cuenta 125.000 DÓLARES.
//
// El backend tiene un módulo entero para esto (backend/realized_pnl.py) porque
// el criterio estaba copiado a mano en cuatro lugares y divergió: el síntoma en
// producción fue un cupón que el dashboard mostraba como US$100 y la IA, en el
// MISMO request, le contaba al usuario como US$125.000. Acá va el espejo en JS,
// con la MISMA lista y la misma regla — hay un test de paridad que lee el
// módulo Python y falla si alguien mueve una sola de las dos.
//
// Por qué acá y no en GET /api/operations: ese endpoint devuelve la fila como
// está guardada, y Operations.jsx carga `pnl_usd` en su formulario de edición y
// lo vuelve a escribir (Operations.jsx:115 y :134). Convertir en el endpoint
// haría que editar cualquier campo de un cupón le reescriba el monto en la DB.
//
// Las filas VIEJAS (sin `fx_to_usd` sellado) caen al ELSE y quedan como están.
// Es deliberado y está medido en el docstring del módulo: de los 276 cupones
// marcados ARS sin FX, ~125 son de bonos en dólares que YA están bien, y
// convertirlos a todos los haría 1250× más chicos — un bug peor que el que
// arregla.
const NATIVE_CCY_OPS = ['Cupón', 'Amortización']

/**
 * opPnlUsd — el `pnl_usd` de la fila, en USD de verdad.
 * Espejo de realized_usd() / realized_usd_sql() (backend/realized_pnl.py).
 */
export function opPnlUsd(op) {
  const raw = op == null ? null : op.pnl_usd
  if (raw == null) return raw
  if (!NATIVE_CCY_OPS.includes(String(op.op_type || '').trim())) return raw
  if (String(op.currency || '').toUpperCase() !== 'ARS') return raw
  const fx = Number(op.fx_to_usd)
  if (!Number.isFinite(fx) || fx <= 0) return raw
  return raw / fx
}

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
 * ratePct — la tasa, o null cuando no hay tasa que valga.
 *
 * Tres motivos para no publicarla, y los tres devuelven null en vez de un
 * número inventado: no hay costo, el costo está incompleto (alguna venta no
 * trajo con qué despejarlo), o el costo es tan chico contra el resultado que
 * el cociente ya no es un rendimiento (ver MAX_PNL_TO_COST arriba).
 */
export function ratePct(total, cost, costIncomplete) {
  if (costIncomplete || !(cost > 0)) return null
  if (Math.abs(total) > cost * MAX_PNL_TO_COST) return null
  return (total / cost) * 100
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
    // NO `op.pnl_usd` crudo: un cupón en pesos entraría 1250× inflado.
    const pnl = opPnlUsd(op)
    if (pnl == null) continue
    // `cost_usd` explícito: SOLO lo manda el libro del asesor, que agrega las
    // ventas en el backend y ya sabe el costo exacto. Una fila con resultado
    // NETO cero (un cliente vendió +500 y otro −500) igual tiene capital que va
    // al denominador, así que no se puede saltear por pnl === 0.
    const explicitCost = Number(op.cost_usd)
    const hasExplicitCost = Number.isFinite(explicitCost) && explicitCost > 0
    if (pnl === 0 && !hasExplicitCost) continue

    const ticker = normalizeTicker(op.asset)
    // El hint puede venir en la fila: el libro del asesor agrega las
    // operaciones en el backend y ahí ya se resolvió el tipo y el mercado
    // (no hay `positions` del cliente en el navegador con qué inferirlos).
    // En retail las filas de /api/operations no traen ninguno de los dos, así
    // que los dos fallbacks quedan en undefined y no cambia nada.
    const hinted = typeHint.get(`${op.broker}|${ticker}`) || op.asset_type || null
    const key = classify({
      asset: op.asset, broker: op.broker, asset_type: hinted, is_cash: 0,
      is_ar_market: op.is_ar_market,
    }, brokers)
    const b = bucketFor(out, key)
    const a = assetFor(b, ticker)

    // Sin acentos: la app escribe op_type='Cupón' (main.py, 6 lugares) y
    // 'CUPÓN'.includes('CUPON') es FALSE — los cupones caían en `realized`
    // como si fueran una venta. El monto igual entraba en el total, pero sin
    // pnl_pct con qué despejar el costo marcaban costIncomplete y le borraban
    // el rendimiento % a TODA la porción de bonos, que es justo donde los
    // cupones son el rendimiento.
    const tipo = String(op.op_type || '').toUpperCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    const esRenta = tipo.includes('DIVIDENDO') || tipo.includes('INTER') || tipo.includes('CUPON')

    if (esRenta) {
      // Renta: suma al resultado, no al capital invertido.
      b.income += pnl
      a.pnl += pnl
      continue
    }

    b.realized += pnl
    a.pnl += pnl
    // Con el costo explícito no hace falta despejarlo: es exacto y sobrevive
    // al caso de resultado neto cero.
    if (hasExplicitCost) {
      b.cost += explicitCost
      a.cost += explicitCost
      continue
    }
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
    b.pct = ratePct(b.total, b.cost, b.costIncomplete)
    b.byAsset = [...b.byAsset]
      .map(([asset, v]) => ({
        asset,
        total: v.pnl,
        cost: v.cost,
        pct: ratePct(v.pnl, v.cost, v.costIncomplete),
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
    pct: ratePct(total, cost, incomplete),
  }
}
