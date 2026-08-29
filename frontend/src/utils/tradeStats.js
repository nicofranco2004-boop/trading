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
// ⚠️ NO es (todavía) la única del frontend. Consumen ESTE helper Operations.jsx
// y OperationsMobile.jsx. Siguen vivas con criterio propio:
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
 * ¿Esta operación es un trade cerrado, o sea algo que se puede haber ganado o
 * perdido? Espejo de `_is_trade` + el filtro `pnl_usd is not None`.
 *
 * @param {object} op — operación cruda del backend
 * @returns {boolean}
 */
export function esTradeCerrado(op) {
  const tipo = (op?.op_type || '').trim()
  if (TIPOS_NO_TRADE.includes(tipo)) return false
  if (PREFIJOS_CONVERSION.some(p => tipo.startsWith(p))) return false
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
