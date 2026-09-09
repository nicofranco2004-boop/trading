// Premium dólar-cripto para la valuación de cripto.
// ───────────────────────────────────────────────────────────────────────────
// Modelo (confirmado por producto): la cripto de un BROKER argentino (Cocos,
// Balanz…) se valúa al dólar MEP que muestra el broker; en un EXCHANGE (Binance,
// Ripio…) se queda al spot/USDT. El factor cripto/MEP se multiplica al VALOR y al
// COSTO por igual → el P&L% queda invariante, solo suben ~5% los montos para
// matchear el broker.
//
// CRYPTO_SYMBOLS está PORTADO de backend/main.py:4863. La paridad la garantiza
// crypto.test.js (si el back agrega un símbolo, el test falla hasta sincronizar).
// `isCrypto` se usa además para que la cripto NUNCA se rutee a `.BA` (no existe
// 'BTC.BA') aunque viva en un broker con nombre AR.

export const CRYPTO_SYMBOLS = new Set([
  'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'AVAX', 'DOGE', 'TRX', 'DOT',
  'MATIC', 'POL', 'LINK', 'LTC', 'BCH', 'NEAR', 'UNI', 'ATOM', 'XLM', 'ETC',
  'APT', 'ARB', 'OP', 'AAVE', 'MKR', 'SNX', 'CRV', 'COMP', 'SUSHI', 'YFI',
  '1INCH', 'BAL', 'DYDX', 'GMX', 'BLUR', 'GRT', 'LRC', 'ZRX', 'BAT', 'REN',
  'ALGO', 'VET', 'EGLD', 'FTM', 'FLOW', 'HBAR', 'THETA', 'XTZ', 'EOS', 'WAVES',
  'ZIL', 'NEO', 'QTUM', 'ICX', 'ONT', 'IOTA', 'ZEC', 'XMR', 'KAVA',
  'SAND', 'MANA', 'AXS', 'ENJ', 'IMX', 'CHZ', 'GALA', 'ILV',
  'SHIB', 'PEPE', 'FLOKI', 'BONK', 'WIF', 'DEGEN',
  'SUI', 'SEI', 'TIA', 'INJ', 'JTO', 'PYTH', 'STRK', 'WLD', 'MANTA', 'ALT',
  'ORDI', 'RUNE', 'FIL', 'STX', 'CORE', 'CFX', 'ID', 'ARKM', 'CYBER',
  'RDNT', 'APE', 'LDO', 'RPL', 'FXS', 'FRAX', 'PENDLE', 'SSV',
  'WBTC', 'STETH',
])

export function isCrypto(asset) {
  return CRYPTO_SYMBOLS.has((asset || '').toUpperCase())
}

/**
 * cryptoBrokerFactor — factor para expresar en dólar-MEP una cripto que en la
 * cuenta está EN PESOS. Espejo EXACTO de backend main.crypto_broker_factor.
 *
 * QUÉ PREGUNTA CONTESTA (y por qué NO es "¿el broker es argentino?"):
 * el premium existe para UNA cosa: pasar a dólares algo cuyo valor natural está
 * en pesos. Una cripto en una cuenta EN PESOS vale spot×dólar-cripto pesos, y
 * esos pesos se pasan a USD por el MEP como TODO lo demás de la app → el factor
 * cripto/MEP. Si la cuenta está EN DÓLARES no hubo ningún peso en el medio: la
 * persona puso dólares, el broker le muestra dólares, y el valor es spot×qty.
 * Meter ahí un cripto/MEP inventa una conversión que nunca ocurrió — inflaba el
 * VALOR y también el "Invertido" (~4%: reporte de un usuario 2026-09-09, cuyo
 * broker mostraba USD 2.840 contra los USD 2.956 de Rendi).
 *
 * Devuelve 1 (sin premium = spot) si: hay override, no es cripto, el broker es
 * exchange, LA CUENTA NO ESTÁ EN PESOS, o falta/≤0 algún rate. Nunca NaN/0.
 *
 * ⚠️ `accountCurrency` NO tiene default a propósito de la semántica, pero un
 * caller que lo omita recibe undefined → 1 (sin premium). Ese es el lado
 * conservador (nunca infla), PERO en el riel ARS desincroniza con el precio
 * `.BA` que la Cartera usa — donde el premium viene embebido en el precio en
 * pesos, no por este factor. Si agregás un caller que valúa cripto de una
 * cuenta en pesos, PASALE la moneda. Los callers vivos están en crypto.test.js.
 *
 * @param {string}  asset           símbolo de la posición
 * @param {boolean} isExchange      broker.is_exchange (de /api/brokers)
 * @param {boolean} hasOverride     price_override != null
 * @param {number}  tcCripto        dólar cripto (dolar.cripto.venta)
 * @param {number}  tcMep           dólar MEP (cedearRate)
 * @param {string}  accountCurrency broker.currency ('ARS' | 'USD' | 'USDT')
 * @returns {number}
 */
export function cryptoBrokerFactor(asset, isExchange, hasOverride, tcCripto, tcMep, accountCurrency) {
  if (hasOverride) return 1
  if (!isCrypto(asset)) return 1
  if (isExchange) return 1
  // Cuenta en dólares → no hay pesos que convertir. Ver el bloque de arriba.
  if (String(accountCurrency || '').toUpperCase() !== 'ARS') return 1
  if (!(tcCripto > 0) || !(tcMep > 0)) return 1
  return tcCripto / tcMep
}
