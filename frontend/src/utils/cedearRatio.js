// cedearRatio.js — cuántos CEDEARs entran en UNA acción del subyacente.
// ════════════════════════════════════════════════════════════════════════════
// POR QUÉ EXISTE
// ──────────────
// Un CEDEAR no es una acción: es una fracción. Hacen falta 58 CEDEARs de GOOGL
// para tener una acción de Alphabet, y 39 de AVGO para una de Broadcom. Todo
// dato que yfinance publica "por acción" (dividendos, y mañana cualquier otro)
// está en la escala del SUBYACENTE, no del CEDEAR.
//
// Reportado por un usuario el 2026-09-17: Rendi le anunciaba US$40 de dividendo
// de GOOGL y el broker le depositó US$0,70. La app hacía
// `dividendo_por_acción × cantidad_de_CEDEARs` sin dividir por el ratio, así que
// el cobro salía inflado tantas veces como CEDEARs entran en una acción — 58×
// en ese caso. La cuenta con el ratio da US$0,69 contra los US$0,70 reales.
//
// El mismo problema existe al revés para las acciones ARGENTINAS: yfinance no
// cotiza la acción local, cotiza su ADR de Nueva York. 10 acciones de GGAL en
// BYMA son 1 ADR, así que el dividendo del ADR aplicado a la tenencia local
// inflaba 10×.
//
// DE DÓNDE SALEN LOS NÚMEROS
// ──────────────────────────
// Fuente primaria: la **lista oficial de Banco Comafi**, emisor de los programas
// de CEDEARs ("LISTA TOTAL DE CEDEARS", columna "Ratio Cedear/Acción ó ADR"),
// bajada el 2026-09-17:
//   https://www.comafi.com.ar/custodiaglobal/Multimedios/otros/14779.xlsx
// Cubre 362 acciones. NO cubre los ETFs (SPY, QQQ, GLD…) ni los CEDEARs de otros
// emisores: esos 22 llevan el ratio MEDIDO del precio (acción US ÷ precio del
// CEDEAR en BYMA ÷ dólar), y están marcados abajo como tales.
//
// El método medido se validó contra la lista oficial: de 131 símbolos que se
// pudieron cruzar, acertó 128 y falló 3 (HOOD 30 vs 29, AZN 4 vs 2, OKLO 29 vs
// 28) — ~2% de error, por eso la oficial manda donde existe.
//
// Una tercera fuente sirvió de desempate: el nombre que BYMA publica para el
// símbolo .BA vía yfinance, que lleva el ratio adentro ('ALPHABET INC CEDEAR
// EACH 58 REP'). Es útil pero NO confiable sola, por dos motivos medidos:
//   · yfinance lo trunca a 31 caracteres — MELI llegaba como "EACH 12" con el
//     ratio real en 120, un error de 10×;
//   · no se actualiza cuando el CEDEAR cambia de ratio — GM decía 20 con el
//     ratio ya en 6. En esos casos (GM, TWLO, IREN, DOW) el precio tenía razón,
//     y la lista de Comafi lo confirmó después: 6, 36, 12 y 6.
//
// Lo que ninguna fuente cubre queda FUERA de la tabla a propósito: sin ratio, el
// consumidor no publica el monto. Un número ausente es honesto; uno inflado 58×
// no.
//
// CUANDO ESTA TABLA ENVEJEZCA
// ───────────────────────────
// Los CEDEARs cambian de ratio (el repo ya tiene esa maquinaria en
// SplitRatioBanner / POST /positions/:id/adjust-ratio). Por eso
// `deriveCedearRatio` recalcula del precio en vivo: si un ratio de acá queda
// viejo, el derivado lo corrige solo cuando hay ambos precios a mano.

import { isBymaHolding, hasBrokersRegistry } from './valuation'
import { cedearEspecieBase, CEDEAR_TICKERS } from './tickers'

// ─── CEDEARs: cuántos CEDEARs = 1 acción del subyacente ─────────────────────
// Un valor < 1 (ej. ABEV 1/3) significa lo contrario: 1 CEDEAR = 3 acciones.
export const CEDEAR_RATIOS = {
  // ── Ratio OFICIAL de Comafi (lista del 17.9.2026) ─────────────────────
  AAL: 2, AAPL: 20, ABBV: 10, ABEV: 1/3, ACWI: 26, ADBE: 44, ALAB: 44, AMD: 10,
  AMGN: 30, AMZN: 144, ANET: 29, ASML: 146, ASTS: 15, AVGO: 39, AXP: 15, AZN: 2,
  BA: 24, BABA: 9, BAC: 4, BAK: 2, BB: 3, BBD: 1, BIDU: 11, BIOX: 1, BMNR: 8, BMY: 3,
  'BRK-B': 22, BRKB: 22, C: 3, CAT: 20, CEG: 45, COIN: 27, COP: 25, COPX: 14, COST: 48,
  CRM: 18, CRWD: 79, CRWV: 27, CSCO: 5, CVX: 16, DE: 40, DISN: 12, DOCU: 22, DOW: 6,
  FXI: 5, GE: 8, GILD: 4, GLOB: 18, GM: 6, GOOGL: 58, GPRK: 1, GS: 13, HD: 32, HIMS: 4,
  HMY: 1, HON: 8, HOOD: 29, IBIT: 10, IBM: 15, INTC: 5, IREN: 12, ITUB: 1, JD: 4,
  JNJ: 15, JPM: 15, KO: 5, LAC: 1, LAR: 1, LLY: 56, LMT: 20, MA: 33, MCD: 24, MELI: 120,
  META: 24, MMM: 10, MP: 10, MRK: 5, MRNA: 19, MS: 41, MSFT: 30, MUX: 2, NBIS: 27,
  NFLX: 48, NIO: 4, NKE: 12, NOKA: 1, NOW: 172, NU: 2, NVDA: 24, NVO: 7, NVS: 4,
  O: 13, OKLO: 28, ONDS: 2, ORCL: 3, PAGS: 3, PATH: 2, PBR: 1, PDD: 25, PEP: 18,
  PFE: 4, PINS: 7, PLTR: 3, PYPL: 8, QCOM: 11, RGTI: 2, RIO: 8, RIOT: 3, RKLB: 12,
  ROKU: 13, RTX: 5, SBUX: 12, SE: 32, SHOP: 107, SID: 1/8, SNAP: 1, SNDK: 170,
  SNOW: 30, SPCE: 1/2, SPCX: 50, SPOT: 28, STNE: 3, T: 3, TGT: 24, TRIP: 2, TSLA: 15,
  TSM: 9, TWLO: 36, UNH: 33, V: 18, VALE: 2, VIG: 39, VIST: 3, VST: 26, WFC: 5,
  WMT: 18, XLV: 29, XOM: 10, XYZ: 20, ZM: 47,

  // ── Sin fila en la lista de Comafi (ETFs, y acciones de otros emisores):
  //    ratio MEDIDO del precio. Contra los 131 que sí se pudieron cruzar, el
  //    método acertó 128 — o sea que acá puede haber alguno corrido en 1.
  ABNB: 15, ARKK: 10, EA: 14, EEM: 5, ETHA: 5, EWY: 50, EWZ: 2, F: 1, GLD: 50, HUT: 5,
  JMIA: 1, KEEL: 1/5, MSTR: 20, MU: 5, PANW: 50, QQQ: 20, SATL: 1, SPY: 60, UBER: 2,
  URA: 5, XLE: 2, XLF: 2,
}

// Símbolos que ninguna de las tres fuentes cubre: no están en la lista de
// Comafi y el día del barrido no tenían precio en BYMA con el que derivarlos
// (son CEDEARs poco líquidos). Para éstos NO se publica un cobro estimado, salvo
// que `deriveCedearRatio` consiga el ratio del precio en vivo. Se listan para
// que la ausencia sea explícita y no un olvido.
export const CEDEAR_RATIO_DESCONOCIDO = new Set(['AMC', 'BLK', 'DDOG', 'GME', 'NET', 'TTWO'])

// ─── Acciones argentinas: cuántas acciones locales = 1 ADR ──────────────────
// Sólo las que comparten símbolo entre BYMA y el ADR, que son las únicas que
// hoy llegan a yfinance: el backend manda el símbolo pelado, así que 'PAMP',
// 'YPFD', 'TGSU2', 'TECO2', 'IRSA' y 'CRES' devuelven 404 y nunca generan un
// evento. Medidos el 2026-09-17 con el mismo método y la misma calibración.
export const AR_ADR_RATIOS = {
  GGAL: 10, BMA: 10, CEPU: 10, EDN: 20, SUPV: 5, LOMA: 5, BBAR: 3,
}

/**
 * cedearRatio — el ratio de la TABLA para un símbolo, o null si no lo sabemos.
 *
 * Acepta el alias de especie (el CEDEAR que cotiza en pesos con código propio),
 * igual que holdingHasReliableFundamentals.
 */
export function cedearRatio(asset) {
  const base = cedearEspecieBase(asset)
  if (!base) return null
  const r = CEDEAR_RATIOS[base]
  return typeof r === 'number' && r > 0 ? r : null
}

/**
 * arAdrRatio — cuántas acciones locales entran en 1 ADR, o null.
 */
export function arAdrRatio(asset) {
  const base = (asset || '').toUpperCase()
  const r = AR_ADR_RATIOS[base]
  return typeof r === 'number' && r > 0 ? r : null
}

/**
 * deriveCedearRatio — el ratio calculado del precio en vivo, para lo que la
 * tabla no cubre (un CEDEAR nuevo, o uno cuyo ratio cambió después del barrido).
 *
 *   ratio = precio de la acción US ÷ (precio del CEDEAR en BYMA ÷ dólar)
 *
 * Es el MISMO cálculo que ya hacía DetailPortfolioBlocks para llevar el costo a
 * la escala de la acción US — vive acá para que exista una sola copia.
 *
 * ⚠️ Arrastra el sesgo de escala descrito arriba (~4%: el dólar implícito de los
 * CEDEARs no es el MEP), así que sirve para un monto rotulado "estimado", NO
 * para decidir un ratio exacto. Por eso la tabla manda y esto es el respaldo.
 *
 * @param {string} asset   símbolo base ('GOOGL')
 * @param {Object} prices  mapa de precios { GOOGL: 347.45, 'GOOGL.BA': 9565 }
 * @param {number} tc      dólar de valuación (MEP)
 * @returns {number|null}
 */
export function deriveCedearRatio(asset, prices, tc) {
  const base = cedearEspecieBase(asset)
  if (!base || !prices || !(tc > 0)) return null
  const us = Number(prices[base])
  const ba = Number(prices[`${base}.BA`])
  if (!(us > 0) || !(ba > 0)) return null
  const cedearUsd = ba / tc
  if (!(cedearUsd > 0)) return null
  const ratio = us / cedearUsd
  // Cotas de sanidad: fuera de este rango es un precio corrupto o dos
  // instrumentos distintos bajo el mismo símbolo (el caso BAC/Boeing daba
  // 10.269), no un ratio.
  if (!Number.isFinite(ratio) || ratio < 0.05 || ratio > 1000) return null
  return ratio
}

/**
 * resolveCedearRatio — la política ÚNICA de resolución: primero la tabla (exacta
 * y sin sesgo), después el precio en vivo (aproximado pero al día). Todo el que
 * necesite el ratio pasa por acá, para que no existan dos criterios distintos.
 *
 * @returns {{ratio:number, source:'table'|'derived'}|null}
 */
export function resolveCedearRatio(asset, prices, tc) {
  const tabla = cedearRatio(asset)
  if (tabla) return { ratio: tabla, source: 'table' }
  const vivo = deriveCedearRatio(asset, prices, tc)
  if (vivo) return { ratio: vivo, source: 'derived' }
  return null
}

/**
 * underlyingShares — cuántas acciones del SUBYACENTE equivalen a UNA posición.
 *
 * Ésta es la función que arregla el bug: convierte la tenencia a la escala en la
 * que yfinance publica los datos "por acción", en vez de asumir que 130 CEDEARs
 * son 130 acciones.
 *
 *   • Acción/ETF en un broker de verdad en dólares → la cantidad tal cual.
 *   • CEDEAR (o cualquier tenencia que se valúe por BYMA) → cantidad ÷ ratio.
 *   • Acción argentina con ADR de mismo símbolo      → cantidad ÷ ratio del ADR.
 *   • Sin ratio conocido                             → null (no se publica monto).
 *
 * Devolver null NO es un caso de borde que se pueda ignorar: es la diferencia
 * entre callarse y mentir. Todo consumidor tiene que tratarlo como "no sé".
 *
 * @param {Object} p       posición ({ asset, quantity, broker, asset_type, ... })
 * @param {Object} [opts]  { prices, tc } para habilitar el ratio derivado
 * @returns {{shares:number, ratio:number, scale:string, source:string}|null}
 */
export function underlyingShares(p, opts = {}) {
  if (!p || p.is_cash) return null
  const qty = Number(p.quantity)
  if (!(qty > 0)) return null

  const base = cedearEspecieBase(p.asset)
  if (!base) return null

  // ¿Se valúa por BYMA? Mismo discriminador que la valuación (CEDEAR explícito,
  // broker ARS, sub-broker "· USD" de un padre argentino, o lote con costo en
  // pesos). Si no, es una acción/ETF real en un broker en dólares.
  if (!isBymaHolding(p)) {
    // OJO: "no es BYMA" puede significar "todavía no sé". El registro de brokers
    // se vacía en cada login y sólo lo repueblan algunas pantallas, así que si
    // entrás y vas derecho a Novedades puede estar vacío. Con el registro vacío,
    // un CEDEAR cuyo lote no trae asset_type ni currency (los importadores que no
    // los marcan, ej. IEB) se veía como acción real y el cobro volvía a salir
    // inflado por el ratio entero — reproducido en la app el 2026-09-17: AVGO
    // volvía a decir US$84,50. Si el ticker PODRÍA ser un CEDEAR y no tenemos con
    // qué decidir, no se publica monto.
    if (!hasBrokersRegistry() && !p.asset_type && !p.currency && CEDEAR_TICKERS.has(base)) {
      return null
    }
    return { shares: qty, ratio: 1, scale: 'share', source: 'us' }
  }

  // Acción argentina local: lo que cotiza afuera es el ADR.
  const adr = arAdrRatio(base)
  if (adr && !CEDEAR_TICKERS.has(base)) {
    return { shares: qty / adr, ratio: adr, scale: 'adr', source: 'table' }
  }

  const r = resolveCedearRatio(base, opts.prices, opts.tc)
  if (r) return { shares: qty / r.ratio, ratio: r.ratio, scale: 'cedear', source: r.source }

  return null   // no sabemos el ratio → el consumidor NO publica monto
}

/**
 * underlyingSharesForTicker — convierte TODA la tenencia de un ticker a la escala
 * del subyacente, en una sola pasada.
 *
 * Por qué no alcanza con sumar `quantity`: una misma empresa puede estar en dos
 * escalas a la vez — el CEDEAR de AVGO en Balanz y la acción real de AVGO en una
 * cuenta del exterior. Sumar las cantidades y multiplicar por el dividendo mete
 * los CEDEARs en la escala de la acción.
 *
 * `units` cuenta SÓLO lo que se pudo convertir, y `unitsUnknown` lo que no. Esa
 * separación importa: si el consumidor publica "tenés N nominales → cobrás $X"
 * con N incluyendo tenencia que $X no cubre, el número miente igual que antes,
 * sólo que menos.
 *
 * @returns {{shares:number, units:number, unitsUnknown:number, partial:boolean,
 *            scales:Set<string>, ratio:number|null, scale:string}}
 */
export function underlyingSharesForTicker(positions, ticker, opts = {}) {
  const base = cedearEspecieBase(ticker)
  let shares = 0, units = 0, unitsUnknown = 0, ratio = null
  const scales = new Set()
  for (const p of positions || []) {
    if (p.is_cash) continue
    if (cedearEspecieBase(p.asset) !== base) continue
    const qty = Number(p.quantity)
    if (!(qty > 0)) continue
    const eq = underlyingShares(p, opts)
    if (!eq) { unitsUnknown += qty; continue }
    shares += eq.shares
    units += qty
    ratio = eq.ratio
    scales.add(eq.scale)
  }
  const scale = scales.size === 1 ? [...scales][0] : (scales.size ? 'mixed' : 'unknown')
  return {
    shares, units, unitsUnknown,
    partial: unitsUnknown > 0,
    scales,
    // Sin sentido si hay dos escalas mezcladas bajo el mismo ticker.
    ratio: scale === 'mixed' ? null : ratio,
    scale,
  }
}
