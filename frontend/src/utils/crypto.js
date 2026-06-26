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
 * cryptoBrokerFactor — factor para llevar la cripto de un BROKER (no exchange) del
 * spot al dólar MEP. Espejo EXACTO de backend main.crypto_broker_factor.
 *
 * Devuelve 1 (sin premium = spot, comportamiento actual) si: hay override, no es
 * cripto, el broker es exchange, o falta/≤0 algún rate. Nunca NaN/0.
 *
 * @param {string}  asset       símbolo de la posición
 * @param {boolean} isExchange  broker.is_exchange (de /api/brokers)
 * @param {boolean} hasOverride price_override != null
 * @param {number}  tcCripto    dólar cripto (dolar.cripto.venta)
 * @param {number}  tcMep       dólar MEP (cedearRate)
 * @returns {number}
 */
export function cryptoBrokerFactor(asset, isExchange, hasOverride, tcCripto, tcMep) {
  if (hasOverride) return 1
  if (!isCrypto(asset)) return 1
  if (isExchange) return 1
  if (!(tcCripto > 0) || !(tcMep > 0)) return 1
  return tcCripto / tcMep
}
