// assetSector — clasificación de una posición por SECTOR económico.
// ═══════════════════════════════════════════════════════════════════════════
// El segundo eje de composición: no "qué instrumento es" sino "a qué parte de
// la economía estás expuesto". Complementa assetClass.js, no lo reemplaza.
//
// ── Regla #1: el sector se apoya en la CLASE ───────────────────────────────
// Un bono soberano, un FCI money-market, un plazo fijo o el efectivo no tienen
// sector económico — pedirle "sector" a yfinance para AL30 devuelve vacío. El
// mapa sectorial del backend (behavioral._SECTOR_MAP) no hace esta distinción
// y por eso el 72% de una cartera argentina real le cae en "Otros": no porque
// falten datos, sino porque le está preguntando el sector a instrumentos que
// no tienen. Acá resolvemos primero la clase con classifyAsset() y solo las
// acciones/CEDEARs/ETFs pasan por el mapa. Todo lo demás va a su propia
// porción, que es la respuesta correcta.
//
// ── Regla #2: "Sin dato" es honesto ───────────────────────────────────────
// Un equity que no está en el mapa NO se adivina. computeSectorBreakdown
// devuelve cuánto pesa lo desconocido para que la UI lo diga en vez de
// dibujar porcentajes que no se sostienen.
//
// ── Sobre "Semiconductores" ───────────────────────────────────────────────
// En GICS los semis son una INDUSTRIA dentro de Tecnología, no un sector. Los
// separamos igual porque para el que invierte son una apuesta distinta (ciclo
// propio, concentración en pocas manos) y es la granularidad que se pide en la
// práctica. Misma lógica para Commodities.

import { classifyAsset, normalizeTicker } from './assetClass'
import { computePnlByKey, mergePnl } from './assetPnl'

// ─── Vocabulario ────────────────────────────────────────────────────────────
// El orden es el de las porciones. Colores: los data accents del design system
// primero (los sectores más habituales en una cartera), después variantes de la
// misma familia. Nunca rendi-neg (#FF5360): en esta app el rojo es pérdida.

export const SECTOR_META = {
  tecnologia:    { label: 'Tecnología',          color: '#5B9DF9' },
  semis:         { label: 'Semiconductores',     color: '#7C6BF5' },
  comunicacion:  { label: 'Comunicación y medios', color: '#8B7DFF' },
  consumo_disc:  { label: 'Consumo discrecional', color: '#D97BE0' },
  consumo_bas:   { label: 'Consumo básico',      color: '#E08AA8' },
  salud:         { label: 'Salud',               color: '#46C6E0' },
  financiero:    { label: 'Financiero',          color: '#21D07A' },
  energia:       { label: 'Energía',             color: '#E8B14A' },
  utilities:     { label: 'Servicios públicos',  color: '#C98A2E' },
  industria:     { label: 'Industria',           color: '#9AA85C' },
  materiales:    { label: 'Materiales',          color: '#A87C5C' },
  inmobiliario:  { label: 'Inmobiliario',        color: '#6FA8A0' },
  commodities:   { label: 'Oro y commodities',   color: '#D4A24C' },
  diversificado: { label: 'Diversificado (ETF)', color: '#4F7CA8' },
  cripto:        { label: 'Cripto',              color: '#F2994A' },
  renta_fija:    { label: 'Renta fija',          color: '#8D8FA8' },
  fci:           { label: 'FCI',                 color: '#7E86A0' },
  efectivo:      { label: 'Efectivo',            color: '#5A6478' },
  sin_dato:      { label: 'Sin dato',            color: '#8A93A6' },
}

export const SECTOR_ORDER = Object.keys(SECTOR_META)

// ─── Mapa ticker → sector ───────────────────────────────────────────────────
// Cubre el universo curado de la app: STOCKS_US, CEDEARS_LIST, ETFS, el panel
// líder y general de BYMA, y los ADRs argentinos. Los CEDEARs comparten símbolo
// con su subyacente US, así que una sola entrada sirve para los dos mercados —
// que es justo lo que querés: un CEDEAR de NVDA ES exposición a semis.
//
// Los ETFs sectoriales (XLK, XLF, SOXX…) van a SU sector, no a "Diversificado":
// comprar XLE es una apuesta a energía, no diversificación.

const M = (sector, tickers) => tickers.map(t => [t, sector])

const SECTOR_MAP = new Map([
  ...M('tecnologia', [
    'AAPL', 'MSFT', 'ORCL', 'CRM', 'ADBE', 'IBM', 'CSCO', 'ACN', 'NOW', 'INTU',
    'PANW', 'CRWD', 'SNOW', 'PLTR', 'SHOP', 'DDOG', 'NET', 'ZS', 'OKTA', 'MDB',
    'TWLO', 'DOCU', 'ZM', 'ADSK', 'WDAY', 'TEAM', 'ANET', 'BB', 'XLK', 'GLOB',
    'CRWV', 'NBIS', 'NOKA', 'PATH', 'RGTI', 'ONDS',
  ]),
  ...M('semis', [
    'NVDA', 'AMD', 'INTC', 'QCOM', 'AVGO', 'MU', 'TXN', 'AMAT', 'LRCX', 'KLAC',
    'ASML', 'TSM', 'MRVL', 'SOXX', 'SMH', 'SOXL',
    'ALAB', 'SNDK',
  ]),
  ...M('comunicacion', [
    'GOOGL', 'GOOG', 'META', 'NFLX', 'DIS', 'WBD', 'PARA', 'T', 'VZ', 'TMUS',
    'CMCSA', 'SPOT', 'ROKU', 'SNAP', 'PINS', 'EA', 'TTWO', 'RBLX', 'BIDU',
    'XLC', 'TECO2', 'CVH', 'GCLA', 'TEO',
    'DISN',
  ]),
  ...M('consumo_disc', [
    'AMZN', 'TSLA', 'HD', 'LOW', 'MCD', 'SBUX', 'NKE', 'TGT', 'BKNG', 'ABNB',
    'UBER', 'LYFT', 'DASH', 'CMG', 'ETSY', 'F', 'GM', 'RIVN', 'LCID', 'NIO',
    'LI', 'XPEV', 'BABA', 'JD', 'PDD', 'MELI', 'GME', 'AMC', 'CVNA', 'XLY',
    'DESP', 'MIRG', 'GRIM', 'LONG', 'DOME', 'BOLT', 'U',
    'JMIA', 'SE', 'TRIP',
  ]),
  ...M('consumo_bas', [
    'WMT', 'COST', 'KO', 'PEP', 'PG', 'MDLZ', 'ABEV', 'XLP',
    'HAVA', 'PATA', 'MORI', 'SAMI', 'MOLA', 'SEMI', 'LEDE', 'INVJ',
  ]),
  ...M('salud', [
    'LLY', 'UNH', 'JNJ', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'AMGN', 'GILD',
    'BSX', 'MRNA', 'BNTX', 'NVAX', 'BMY', 'AZN', 'NOVN', 'XLV', 'ARKG',
    'RICH', 'ROSE',
    'HIMS', 'NVO', 'NVS',
  ]),
  ...M('financiero', [
    'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'C', 'AXP', 'BLK', 'SPGI',
    'BX', 'PYPL', 'SQ', 'COIN', 'HOOD', 'SOFI', 'AFRM', 'UPST', 'ITUB', 'NU',
    'BBD', 'BRK.B', 'BRKB', 'XLF',
    'GGAL', 'BMA', 'BBAR', 'SUPV', 'BYMA', 'VALO', 'BPAT', 'BHIP',
    'A3', 'BRK-B', 'PAGS', 'STNE', 'XYZ',
  ]),
  ...M('energia', [
    'XOM', 'CVX', 'COP', 'OXY', 'SLB', 'EOG', 'PSX', 'MPC', 'VIST', 'PBR',
    'XLE', 'USO', 'UNG', 'YPF', 'YPFD', 'PAMP', 'PAM', 'CAPU', 'CAPX', 'PCAR',
    'GPRK', 'URA',
  ]),
  ...M('utilities', [
    'XLU', 'CEPU', 'EDN', 'TRAN', 'METR', 'GBAN', 'CGPA2', 'DGCU2', 'CECO2',
    'TGNO4', 'TGSU2', 'TGS',
    'CEG', 'ECOG', 'OKLO', 'VST',
  ]),
  ...M('industria', [
    'BA', 'CAT', 'GE', 'LMT', 'RTX', 'NOC', 'GD', 'RKLB', 'ASTS', 'XLI',
    'AUSO', 'OEST', 'CARC', 'DYCA', 'POLL', 'FERR', 'AGRO', 'COME',
    'AAL', 'DE', 'HON', 'KEEL', 'MMM', 'SATL', 'SPCE', 'SPCX',
  ]),
  ...M('materiales', [
    'LIN', 'VALE', 'XLB', 'ALUA', 'TXAR', 'LOMA', 'HARG', 'CELU', 'FIPL', 'INAG',
    'BAK', 'BIOX', 'COPX', 'DOW', 'HMY', 'LAC', 'LAR', 'MP', 'MUX', 'RIO', 'SID',
  ]),
  ...M('inmobiliario', [
    'XLRE', 'IRSA', 'IRCP', 'IRS', 'CRES', 'CRESY', 'CTIO', 'TGLT', 'CADO',
    'O',
  ]),
  ...M('commodities', ['GLD', 'IAU', 'SLV', 'DBC']),
  ...M('diversificado', [
    'SPY', 'VOO', 'IVV', 'QQQ', 'QQQM', 'DIA', 'IWM', 'VTI', 'VEA', 'VWO',
    'EEM', 'EFA', 'EWZ', 'ARGT', 'MCHI', 'INDA', 'EWJ', 'ARKK', 'TQQQ',
    'SQQQ', 'UPRO',
    'ACWI', 'EWY', 'FXI',
  ]),
  // ETFs de exposición cripto: el subyacente es cripto aunque el envoltorio
  // sea un ETF listado en US.
  ...M('cripto', ['IBIT', 'FBTC', 'GBTC', 'ETHE',
    'BMNR', 'HUT', 'IREN', 'MSTR', 'RIOT', 'ETHA',]),
])

// Clases que NO tienen sector económico: su porción es la clase misma.
const CLASS_TO_SECTOR = {
  cash: 'efectivo',
  cripto: 'cripto',
  bono: 'renta_fija',
  plazo_fijo: 'renta_fija',
  fci: 'fci',
}

/**
 * classifySector
 *
 * @param {Object} position  { asset, asset_type, broker, is_cash }
 * @param {Array}  brokers   [{ name, currency }]
 * @returns {string} una clave de SECTOR_META
 */
export function classifySector(position, brokers = []) {
  if (!position) return 'sin_dato'

  const klass = classifyAsset(position, brokers)
  const direct = CLASS_TO_SECTOR[klass]
  if (direct) return direct

  // Acá quedan cedear / accion_ar / accion_us / etf / otro: los únicos que
  // tienen sector económico de verdad.
  const ticker = normalizeTicker(position.asset)
  const hit = SECTOR_MAP.get(ticker)
  if (hit) return hit
  // Un ETF que no está en el mapa es, casi por definición, diversificado.
  if (klass === 'etf') return 'diversificado'
  return 'sin_dato'
}

/**
 * computeSectorBreakdown
 *
 * Mismo contrato que computeClassBreakdown (assetClass.js) para que la torta
 * pueda renderizar los dos ejes sin ramificar.
 *
 * @param {Array} extraSlices  [{ key, value }] — igual que en assetClass: los
 *                             plazos fijos entran acá como 'renta_fija'.
 * @returns {{ items: Array<{key,label,color,value,pct}>, total: number,
 *            unclassified: { value, pct, assets: string[] } }}
 * @param {Array} operations   filas de /api/operations. OPCIONAL: si vienen, cada
 *                            porción trae `pnl` (realizado + renta + no realizado)
 *                            y cada activo el suyo. Sin esto la torta es solo peso.
 */
export function computeSectorBreakdown(positions = [], brokers = [], extraSlices = [], operations = null) {
  const bySector = new Map()
  const assetsByKey = new Map()
  const unknownAssets = new Set()
  let total = 0

  for (const p of positions) {
    const value = p?.value_usd
    if (value == null || !(value > 0)) continue
    const key = classifySector(p, brokers)
    bySector.set(key, (bySector.get(key) || 0) + value)
    total += value
    // Detalle: qué activos componen la porción. Consolidamos por ticker DENTRO
    // de la porción — el mismo ticker en dos brokers del mismo tipo es una sola
    // línea, pero AAPL-CEDEAR y AAPL-acción caen en porciones distintas y no se
    // mezclan (los separó el clasificador antes de llegar acá).
    const ticker = String(p.asset || '').toUpperCase()
    if (!assetsByKey.has(key)) assetsByKey.set(key, new Map())
    const bucket = assetsByKey.get(key)
    bucket.set(ticker, (bucket.get(ticker) || 0) + value)
    if (key === 'sin_dato') unknownAssets.add(String(p.asset || '').toUpperCase())
  }

  const extraPnl = new Map()
  for (const extra of extraSlices) {
    if (!extra?.key || !(extra.value > 0)) continue
    bySector.set(extra.key, (bySector.get(extra.key) || 0) + extra.value)
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
  const pnlByKey = operations ? computePnlByKey(positions, operations, brokers, classifySector) : null

  const items = SECTOR_ORDER
    .filter(key => bySector.has(key))
    .map(key => ({
      key,
      label: SECTOR_META[key].label,
      color: SECTOR_META[key].color,
      value: bySector.get(key),
      pct: (bySector.get(key) / total) * 100,
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

  const unknownValue = bySector.get('sin_dato') || 0
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
