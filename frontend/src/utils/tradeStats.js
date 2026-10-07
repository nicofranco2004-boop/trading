// tradeStats — la definición de win rate de la pantalla Operaciones.
// ═══════════════════════════════════════════════════════════════════════════
// Espejo literal de backend/reporting/builder.py:352-363 (`_is_trade` + el
// cálculo de `win_rate`). El backend es la casa: si esto y el backend divergen,
// el que está mal es esto.
//
// POR QUÉ EXISTE: había TRES definiciones vivas sobre los mismos datos. Sobre
// 495 ops reales de un usuario daban 93% (desktop), 100% (mobile) y 85%
// (backend). Las dos del frontend contaban 258 Dividendos y 8 Interés como
// trades GANADORES — plata que entró, sí, pero no es una operación que hayas
// ganado o perdido. El backend ya los excluía.
//
// ⚠️ NO es (todavía) la única del frontend. Lo consume Operations.jsx, que desde
// la Fase 3 es la única pantalla de operaciones (antes eran dos, con el fork por
// viewport). Siguen vivas con criterio propio:
//   · Insights.jsx:1310-1325 — mismo predicado de tipo, pero denominador
//     `wins + losses` y además descarta los micro-trades (|P&L| < US$1,50).
//     Su número alimenta el payload de la IA, así que unificarlo cambia lo que
//     dice el análisis: es una decisión de producto, no una limpieza.
//   · AssetDetail.jsx:158-160 — win rate POR ACTIVO, sin filtro de tipo.
// Y el predicado de tipo está copiado a mano en useMonthlyData.js:48-54 y en
// profileMatch.js:445-451. Antes de agregar un cuarto, migrá esos.
//
// LOS CEROS CUENTAN EN EL DENOMINADOR. `pnl_usd` es REAL DEFAULT 0 en el
// schema, así que una venta a resultado exactamente cero es el caso REAL (los
// nulls son la excepción). No es win ni loss, pero es un trade cerrado: sale
// del numerador y se queda en el denominador. Por eso win rate baja.

// Los tipos que NO son un trade cerrado. `Compra` abre, no cierra; `Dividendo`
// e `Interés` son renta, no resultado de una operación.
const TIPOS_NO_TRADE = ['Compra', 'Dividendo', 'Interés']

// Las conversiones de moneda entran con DOS prefijos distintos según de qué
// importador vengan ('Conversión ARS→USD' del parser, 'CONVERSION_USD' del
// normalizador). El backend chequea los dos; acá también.
const PREFIJOS_CONVERSION = ['Conversión', 'CONVERSION']

/**
 * ¿Es una conversión de moneda (comprar/vender USD)? Espejo de
 * `realized_pnl.es_conversion` del backend. NO es un trade aunque venga en la
 * misma lista: su `quantity` son los pesos que salieron y su "precio" el TC.
 * Es LA regla del frontend: antes estaba copiada a mano en useMonthlyData,
 * Insights, profileMatch y assetPnl.
 *
 * @param {string} opType — `op_type` crudo
 * @returns {boolean}
 */
export function esConversion(opType) {
  const tipo = String(opType || '').trim()
  return PREFIJOS_CONVERSION.some(p => tipo.startsWith(p))
}

/**
 * ¿Esta operación es un trade cerrado, o sea algo que se puede haber ganado o
 * perdido? Espejo de `_is_trade` + el filtro `pnl_usd is not None`.
 *
 * @param {object} op — operación cruda del backend
 * @returns {boolean}
 */
export function esTradeCerrado(op) {
  const tipo = (op?.op_type || '').trim()
  if (TIPOS_NO_TRADE.includes(tipo)) return false
  if (esConversion(tipo)) return false
  // `== null` a propósito: cubre null y undefined de una (el backend sólo tiene
  // None, pero acá una fila puede llegar sin la clave).
  if (op?.pnl_usd == null) return false
  return true
}

/**
 * Estadísticas de trades cerrados sobre una lista de operaciones.
 *
 * @param {Array<object>} ops
 * @returns {{trades: number, wins: number, losses: number, winRate: number|null}}
 *          `winRate` es una FRACCIÓN (0..1), no un porcentaje — el backend
 *          devuelve 0..100, las superficies del frontend hacen `*100` al pintar.
 *          Con 0 trades es `null`, NUNCA 0: "0%" le miente al que no operó.
 */
export function computeTradeStats(ops) {
  let trades = 0
  let wins = 0
  let losses = 0
  for (const op of (ops || [])) {
    if (!esTradeCerrado(op)) continue
    trades += 1
    // Ni `wins` ni `losses` si es exactamente 0 — pero `trades` ya lo contó.
    if (op.pnl_usd > 0) wins += 1
    else if (op.pnl_usd < 0) losses += 1
  }
  return { trades, wins, losses, winRate: trades > 0 ? wins / trades : null }
}

/**
 * La operación con mejor P&L, para el KPI "Mejor trade" de Operaciones.
 *
 * Guarda la OP entera (no el escalar) para que la pantalla la formatee con SU FX
 * histórico, y elige el máximo sobre el valor que se VA A MOSTRAR (`valorMostrado`):
 * en pesos el ranking puede diferir del de USD (un trade viejo con dólar barato
 * rinde menos pesos que uno nuevo con el mismo USD), y si se eligiera por USD el
 * "Mejor trade" podía quedar por debajo de una fila visible de la tabla. El viejo
 * `Math.max(..., o.pnl_usd || 0)` además mapeaba null→0 y con todas las ops en
 * pérdida mostraba "$0" (un trade inexistente).
 *
 * Sin conversiones de moneda: una venta de USD con ganancia cambiaria salía como
 * "Mejor trade", y si todo lo demás perdía, la compra de USD (P&L 0).
 *
 * @param {Array<object>} ops
 * @param {(op: object) => number|null} valorMostrado — P&L ya convertido a la moneda de pantalla
 * @returns {object|null}
 */
export function mejorTrade(ops, valorMostrado) {
  let best = null, bestVal = -Infinity
  for (const o of (ops || [])) {
    if (esConversion(o.op_type)) continue
    if (o.pnl_usd == null || !Number.isFinite(o.pnl_usd)) continue
    const v = valorMostrado(o)
    if (v != null && v > bestVal) { bestVal = v; best = o }
  }
  return best
}

/**
 * Patrones derivados de las operaciones — las observaciones escaneables arriba
 * de la tabla de Operaciones: activo más operado (con líder claro, ≥3 veces) y
 * racha ganadora más larga (≥3 seguidas, por fecha).
 *
 * Las conversiones de moneda no entran: no son un activo ni una operación ganada
 * o perdida. "ARS→USDT" podía ser "el activo que más operaste", y una compra de
 * USD (P&L 0) cortaba la racha.
 *
 * @param {Array<object>} ops
 * @returns {Array<{key: 'most_traded', asset: string, count: number} | {key: 'win_streak', streak: number}>}
 */
export function patronesDeOperaciones(ops) {
  const activos = (ops || []).filter(o => !esConversion(o.op_type))
  if (activos.length < 3) return []
  const out = []

  // (1) Activo más operado (cualquier op_type). Solo si hay líder claro.
  const countByAsset = {}
  for (const o of activos) {
    const a = (o.asset || '').trim()
    if (!a) continue
    countByAsset[a] = (countByAsset[a] || 0) + 1
  }
  const ranked = Object.entries(countByAsset).sort((a, b) => b[1] - a[1])
  if (ranked.length > 0 && ranked[0][1] >= 3 && (ranked.length === 1 || ranked[0][1] > ranked[1][1])) {
    out.push({ key: 'most_traded', asset: ranked[0][0], count: ranked[0][1] })
  }

  // (2) Racha ganadora más larga (cronológica, pnl_usd > 0 consecutivos).
  const chron = [...activos]
    .filter(o => o.date && o.pnl_usd != null)
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
  let best = 0, cur = 0
  for (const o of chron) {
    if (o.pnl_usd > 0) { cur++; if (cur > best) best = cur }
    else cur = 0
  }
  if (best >= 3) out.push({ key: 'win_streak', streak: best })

  return out
}
