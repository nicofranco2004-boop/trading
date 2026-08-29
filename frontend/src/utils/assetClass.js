// assetClass — clasificación de una posición en una CLASE DE ACTIVO.
// ═══════════════════════════════════════════════════════════════════════════
// Fuente ÚNICA de verdad para "¿qué es este activo?" en las vistas de
// composición (torta por tipo del Dashboard y de Análisis).
//
// Por qué existe: el repo tenía 4 clasificadores en paralelo que se
// contradecían — classifyAssetType (insightsModel.js) colapsa CEDEAR + acción
// AR + bono + FCI en un solo bucket decidiendo por moneda del broker;
// classifyAssetBucket (profileAllocations.js) ignora asset_type y marca TGSU2
// (una acción) como renta fija; inferType (tickers.js) cae en silencio a
// 'stock_us', así que un FCI o una ON salían "Acción US". Ninguno separaba los
// tipos que el usuario quiere ver.
//
// ── El criterio: primero el MERCADO, después el INSTRUMENTO ────────────────
// El mismo ticker significa cosas distintas según dónde vive: SPY en Balanz es
// un CEDEAR, SPY en Schwab es un ETF; AAPL en Cocos es un CEDEAR, AAPL en IBKR
// es la acción. Por eso resolvemos primero si la posición es de BYMA o del
// exterior — con el MISMO criterio estructural que usa la valuación para
// decidir si el precio va por `.BA` (isArUsdBroker + broker.currency) — y
// recién ahí miramos el ticker. CEDEARS_LIST solapa 96 símbolos con STOCKS_US:
// pertenecer a la lista NO distingue un CEDEAR de la acción US, solo el
// mercado lo hace.
//
// ── Qué NO hace ────────────────────────────────────────────────────────────
// No escribe ni corrige `positions.asset_type`. Esa columna es load-bearing
// para el PRECIO (asset_type==='CEDEAR' fuerza valuar por .BA), así que
// "completarla" para mejorar la torta movería plata en pantalla. Acá la
// LEEMOS como señal y nada más.
//
// ── 'otro' es un resultado válido, no un bug ───────────────────────────────
// En un broker AR un ticker desconocido puede ser una ON, una letra, un FCI
// propietario o un bono provincial: no adivinamos, devolvemos 'otro' y la UI
// muestra cuáles son. En un broker del exterior el residuo (no cash, no
// cripto, no bono, no FCI) es casi con certeza un equity listado en US, así
// que ahí sí caemos a 'accion_us'. La asimetría es deliberada.

import { isCrypto } from './crypto'
import { isArUsdBroker, isFixedIncome } from './valuation'
import {
  CEDEARS_LIST, ARG_LIDER, ARG_GENERAL, STOCKS_US, ETFS, BOND_TICKERS,
} from './tickers'
import { computePnlByKey, mergePnl } from './assetPnl'

const syms = arr => new Set(arr.map(x => x.s))

/**
 * normalizeTicker — el símbolo con el que consultamos las listas curadas.
 *
 * Rendi guarda el activo SIN sufijo de mercado (`AMD`, no `AMD.BA`): el `.BA`
 * se agrega recién al pedir el precio. Pero no todos los importadores respetan
 * esa convención, y un `AMD.BA` que no matchea deja al activo sin sector — el
 * CEDEAR de AMD ES exposición a AMD, el sufijo no cambia eso. Lo sacamos antes
 * de cualquier lookup.
 */
export function normalizeTicker(asset) {
  return String(asset || '').toUpperCase().trim().replace(/\.BA$/, '')
}

const CEDEAR_SYMS = syms(CEDEARS_LIST)
const AR_STOCK_SYMS = new Set([...syms(ARG_LIDER), ...syms(ARG_GENERAL)])
const US_STOCK_SYMS = syms(STOCKS_US)
const US_ETF_SYMS = syms(ETFS)

// ADRs de empresas argentinas en NYSE (ticker propio, sin .BA). Portado de
// backend/behavioral.py:127 — misma lista, mismo criterio: son exposición
// económica AR aunque coticen en USD en un broker del exterior. NO incluye
// MELI ni GLOB (negocios globales, no riesgo-país AR).
const AR_ADR_SYMS = new Set([
  'YPF', 'PAM', 'BBAR', 'CRESY', 'SUPV', 'EDN', 'CEPU', 'LOMA', 'IRS',
  'TEO', 'TGS', 'BMA', 'GGAL', 'DESP',
])

// Stablecoins: son dólares, no una apuesta cripto. Van a Efectivo aunque la
// posición no venga marcada is_cash (muchos exchanges no la marcan). Nótese
// que CRYPTO_SYMBOLS (crypto.js) tampoco las incluye — ahí por otro motivo
// (no se rutean a .BA ni llevan premium MEP).
const STABLECOINS = new Set(['USDT', 'USDC', 'DAI', 'BUSD', 'TUSD', 'USDP', 'FDUSD'])

// Prefijos de letras del Tesoro que el allowlist de tickers.js no cubre.
// LECAPSA / LEDESA son códigos de broker, no tienen dígito, así que la
// heurística "prefijo + dígito" de profileAllocations.js no los agarra.
const LETRA_PREFIXES = ['LECAP', 'LEDES', 'LELIQ', 'BOTE', 'BONCER']
// Letras con formato fecha: S31E5, T30D5, X30N6.
const LETRA_DATE_RE = /^[STX]\d{1,2}[A-Z]\d{1,2}$/
// ONs argentinas: 5 chars terminados en 'O' (YCA0O, TLC1O, MGC1O). Mismo
// criterio que backend/importing/parsers/balanz.py:129.
const ON_RE = /^[A-Z]{2,4}\d?[A-Z]?O$/

// ─── Vocabulario ────────────────────────────────────────────────────────────
// El orden de las claves es el orden de las porciones en la torta: agrupa
// renta variable primero, después renta fija, después líquido. `color` sale de
// la paleta de charts de la app (ver PIE_COLORS en Insights.jsx).

export const ASSET_CLASS_META = {
  cedear:    { label: 'CEDEARs',        color: '#8B7DFF' },
  accion_ar: { label: 'Acciones AR',    color: '#46C6E0' },
  accion_us: { label: 'Acciones US',    color: '#5B9DF9' },
  etf:       { label: 'ETFs',           color: '#21D07A' },
  bono:      { label: 'Bonos y letras', color: '#E8B14A' },
  plazo_fijo:{ label: 'Plazo fijo',     color: '#C98A2E' },  // sintética, ver extraSlices
  fci:       { label: 'FCI',            color: '#D97BE0' },
  cripto:    { label: 'Cripto',         color: '#F2994A' },
  cash:      { label: 'Efectivo',       color: '#5A6478' },
  otro:      { label: 'Sin clasificar', color: '#8A93A6' },
}

// ─── El corte grueso: variable / fija / efectivo ────────────────────────────
// Un nivel ARRIBA de la clase de activo. La clase contesta "qué instrumento
// es"; esto contesta "cuánto de esto se puede mover", que es la primera
// pregunta que se hace alguien mirando una cartera ajena.
//
// Dos decisiones que son juicio, no dato, y por eso están acá arriba y
// escritas en el tooltip de la card:
//
//   • CRIPTO va en renta variable. No es una acción, pero es un activo de
//     riesgo y el corte que se pide es de tres. Ojo que en una cartera
//     argentina puede pesar mucho: la torta por tipo la sigue mostrando
//     aparte, que es donde se ve.
//   • FCI va en renta VARIABLE (decisión del dueño, 2026-08-27). El
//     importador no distingue el tipo de fondo, así que la elección es entre
//     equivocarse con unos o con otros: un FCI money-market —el caso más común
//     en Argentina— queda contado como exposición al mercado, y un FCI de
//     acciones queda bien. Si algún día el catálogo distingue money-market de
//     renta variable, esto se parte en dos y deja de ser una apuesta.
//
// 'otro' NO se reparte: si el clasificador no supo qué es, meterlo en
// cualquiera de los dos lados sería inventar. Va a su propia barra, que la UI
// muestra solo si tiene peso.
export const RISK_GROUP_META = {
  variable: { label: 'Renta variable', color: '#8B7DFF' },
  fija:     { label: 'Renta fija',     color: '#E8B14A' },
  efectivo: { label: 'Efectivo',       color: '#5A6478' },
  otro:     { label: 'Sin clasificar', color: '#8A93A6' },
}

export const RISK_GROUP_ORDER = Object.keys(RISK_GROUP_META)

const CLASS_TO_RISK = {
  cedear: 'variable', accion_ar: 'variable', accion_us: 'variable',
  etf: 'variable', cripto: 'variable',
  fci: 'variable',
  bono: 'fija', plazo_fijo: 'fija',
  cash: 'efectivo',
  otro: 'otro',
}

/** riskGroupOf — de una clave de ASSET_CLASS_META a una de RISK_GROUP_META. */
export function riskGroupOf(classKey) {
  return CLASS_TO_RISK[classKey] || 'otro'
}

export const ASSET_CLASS_ORDER = Object.keys(ASSET_CLASS_META)

export function assetClassMeta(key) {
  return ASSET_CLASS_META[key] || ASSET_CLASS_META.otro
}

// ─── Helpers de instrumento ─────────────────────────────────────────────────

function isBondLike(ticker, assetType) {
  if (isFixedIncome(assetType)) return true          // BOND/BONO/ON/LETRA/LECAP
  if (BOND_TICKERS.has(ticker)) return true          // allowlist curada
  // Pata en dólares del mismo bono (AL30D, GD30C): solo si el ticker pelado
  // está en el allowlist, para no barrer tickers que terminan en D/C por azar.
  if (/[DC]$/.test(ticker) && BOND_TICKERS.has(ticker.slice(0, -1))) return true
  if (LETRA_DATE_RE.test(ticker)) return true        // S31E5, T30D5
  if (LETRA_PREFIXES.some(p => ticker.startsWith(p))) return true
  return false
}

function isFciLike(ticker, assetType) {
  if ((assetType || '').toUpperCase() === 'FUND') return true
  if (ticker.startsWith('FCI:')) return true         // símbolo canónico del catálogo
  return false
}

/**
 * ¿La posición cotiza en BYMA?
 *
 * Estructural, no por nombre — espejo de valuation.isArUsdBroker + la moneda
 * del broker, que es lo que decide si el precio se pide por `.BA`. Un CEDEAR
 * comprado por dólar-MEP vive en un sub-broker "Cocos · USD" y sigue siendo
 * BYMA aunque la moneda diga USD.
 *
 * ── `position.is_ar_market` pre-resuelto ──────────────────────────────────
 * Es la ÚNICA cosa que el clasificador saca de `brokers`. El libro del asesor
 * agrega las carteras de hasta 500 clientes: mandar la lista de brokers de
 * cada uno al navegador para que esta función la recorra sería mandar el
 * modelo de datos entero, y `isArUsdBroker` además lee un registro global
 * (setBrokersRegistry) que solo tiene los brokers de LA cuenta abierta — con
 * carteras ajenas devolvería cualquier cosa.
 *
 * Así que el backend resuelve el mercado (tiene los brokers de todos, con
 * parent_broker_id) y manda `is_ar_market` en la fila. Cuando viene, lo
 * respetamos y no consultamos `brokers`. Es un parámetro opcional del MISMO
 * clasificador, no una copia: la torta del asesor y la del cliente salen del
 * mismo código y no pueden divergir.
 */
function isArMarket(position, brokers) {
  if ((position.asset_type || '').toUpperCase() === 'CEDEAR') return true
  if (position.is_ar_market != null) return Boolean(position.is_ar_market)
  if (isArUsdBroker(position.broker)) return true
  const broker = (brokers || []).find(b => b.name === position.broker)
  return broker?.currency === 'ARS'
}

// ─── El clasificador ────────────────────────────────────────────────────────
/**
 * classifyAsset
 *
 * @param {Object} position  { asset, asset_type, broker, is_cash }
 *                            `is_ar_market` OPCIONAL: si viene definido gana
 *                            sobre `brokers` (ver isArMarket). Lo usa el libro
 *                            del asesor, donde el mercado lo resuelve el backend.
 * @param {Array}  brokers   [{ name, currency }] — de GET /api/brokers
 * @returns {string} una clave de ASSET_CLASS_META
 */
export function classifyAsset(position, brokers = []) {
  if (!position) return 'otro'
  if (position.is_cash) return 'cash'

  const ticker = normalizeTicker(position.asset)
  if (!ticker) return 'otro'
  const assetType = position.asset_type || null

  // 1. Efectivo disfrazado: un stablecoin es un dólar.
  if (STABLECOINS.has(ticker)) return 'cash'
  // 2. FCI antes que cripto/bono: el símbolo canónico es FCI:<slug> y el tipo
  //    del importador (FUND) es confiable cuando viene.
  if (isFciLike(ticker, assetType)) return 'fci'
  // 3. Cripto por la lista que ya gobierna la valuación (110 símbolos,
  //    con test de paridad contra el backend).
  if (isCrypto(ticker)) return 'cripto'
  // 4. Renta fija: bonos soberanos, ONs, letras. Antes del split de mercado
  //    porque un bono es un bono en cualquier broker.
  if (isBondLike(ticker, assetType)) return 'bono'

  // 5. Recién acá el mercado decide qué significa el ticker.
  if (isArMarket(position, brokers)) {
    if (AR_STOCK_SYMS.has(ticker)) return 'accion_ar'
    if (CEDEAR_SYMS.has(ticker)) return 'cedear'
    if ((assetType || '').toUpperCase() === 'CEDEAR') return 'cedear'
    // ON con formato reconocible que no está en el allowlist (el universo de
    // ONs es mucho más grande que la lista curada).
    if (ON_RE.test(ticker)) return 'bono'
    return 'otro'
  }

  // Broker del exterior.
  if (AR_ADR_SYMS.has(ticker)) return 'accion_ar'
  if (US_ETF_SYMS.has(ticker)) return 'etf'
  if (US_STOCK_SYMS.has(ticker)) return 'accion_us'
  return 'accion_us'
}

// ─── Agregado para la torta ─────────────────────────────────────────────────
/**
 * computeClassBreakdown
 *
 * Suma value_usd por clase. El caller resuelve value_usd (la valuación tiene
 * caveats — CEDEAR→MEP, premium cripto, bonos per-100 — que no viven acá).
 *
 * Devuelve también qué quedó sin clasificar, con los tickers: un "Sin
 * clasificar" del 30% no es un detalle de render, es la señal de que al
 * importador le falta tipar esos activos. La UI lo muestra en vez de dibujar
 * un número que no se sostiene.
 *
 * @param {Array} positions    [{ asset, asset_type, broker, is_cash, value_usd }]
 * @param {Array} brokers      [{ name, currency }]
 * @param {Array} extraSlices  [{ key, value }] — porciones que NO salen de
 *                             `positions` porque no son posiciones: los plazos
 *                             fijos viven en su propia tabla y llegan como un
 *                             total ya valuado. Sin esto la torta no suma el
 *                             patrimonio que muestra el hero del Dashboard.
 * @returns {{ items: Array<{key,label,color,value,pct}>, total: number,
 *            unclassified: { value, pct, assets: string[] } }}
 * @param {Array} operations   filas de /api/operations. OPCIONAL: si vienen, cada
 *                            porción trae `pnl` (realizado + renta + no realizado)
 *                            y cada activo el suyo. Sin esto la torta es solo peso.
 */
export function computeClassBreakdown(positions = [], brokers = [], extraSlices = [], operations = null) {
  const byClass = new Map()
  const assetsByKey = new Map()
  const unknownAssets = new Set()
  let total = 0

  for (const p of positions) {
    const value = p?.value_usd
    if (value == null || !(value > 0)) continue
    const key = classifyAsset(p, brokers)
    byClass.set(key, (byClass.get(key) || 0) + value)
    total += value
    // Detalle: qué activos componen la porción. Consolidamos por ticker DENTRO
    // de la porción — el mismo ticker en dos brokers del mismo tipo es una sola
    // línea, pero AAPL-CEDEAR y AAPL-acción caen en porciones distintas y no se
    // mezclan (los separó el clasificador antes de llegar acá).
    const ticker = String(p.asset || '').toUpperCase()
    if (!assetsByKey.has(key)) assetsByKey.set(key, new Map())
    const bucket = assetsByKey.get(key)
    bucket.set(ticker, (bucket.get(ticker) || 0) + value)
    if (key === 'otro') unknownAssets.add(String(p.asset || '').toUpperCase())
  }

  const extraPnl = new Map()
  for (const extra of extraSlices) {
    if (!extra?.key || !(extra.value > 0)) continue
    byClass.set(extra.key, (byClass.get(extra.key) || 0) + extra.value)
    total += extra.value
    // Una porción sintética puede traer su propio resultado (el plazo fijo
    // tiene interés devengado). Sin esto, su capital entraba en el peso de la
    // porción pero no en el denominador del rendimiento, y el % no cerraba
    // contra el monto que la fila mostraba al lado.
    if (extra.pnl) extraPnl.set(extra.key, extra.pnl)
  }

  if (total <= 0) {
    return { items: [], total: 0, unclassified: { value: 0, pct: 0, assets: [] } }
  }

  // P&L por porción — solo si el caller nos pasó las operaciones. La torta
  // funciona igual sin ellas (peso), pero el rendimiento sin lo cerrado ni
  // la renta sería un número equivocado, así que o están las tres patas o no
  // mostramos ninguna.
  const pnlByKey = operations ? computePnlByKey(positions, operations, brokers, classifyAsset) : null

  const items = ASSET_CLASS_ORDER
    .filter(key => byClass.has(key))
    .map(key => ({
      key,
      label: ASSET_CLASS_META[key].label,
      color: ASSET_CLASS_META[key].color,
      value: byClass.get(key),
      pct: (byClass.get(key) / total) * 100,
      pnl: mergePnl(pnlByKey?.get(key), extraPnl.get(key)),
      // Ordenado desc y con el % sobre el TOTAL de la cartera, no sobre la
      // porción: así los hijos suman exactamente el % del padre.
      assets: [...(assetsByKey.get(key) || new Map())]
        .map(([asset, v]) => ({
          asset, value: v, pct: (v / total) * 100,
          pnl: pnlByKey?.get(key)?.byAsset?.find(x => x.asset === asset) || null,
        }))
        .sort((a, b) => b.value - a.value),
    }))

  const unknownValue = byClass.get('otro') || 0
  return {
    items,
    total,
    unclassified: {
      value: unknownValue,
      pct: (unknownValue / total) * 100,
      assets: [...unknownAssets].sort(),
    },
  }
}
