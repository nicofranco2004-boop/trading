// insightsModel.js
// ─────────────────
// Cálculos puros y testeables para la página Insights.
// Antes vivían inline dentro de Insights.jsx (1.187 líneas) — hacían difícil
// validar correcciones financieras y reusarlos.
//
// Convenciones:
//  • Nada acá toca el DOM ni hace fetches: todo es entrada/salida pura.
//  • Las funciones devuelven `null` en vez de objetos vacíos cuando faltan
//    datos suficientes para calcular — el caller decide qué mostrar.
//  • Los amounts vienen y salen en la moneda de origen (USD si la pasa el
//    caller; ARS si la pasa así). Sin conversiones implícitas.

// ─── Helpers ────────────────────────────────────────────────────────────────

function sortGlobalMonthly(globalMonthly) {
  return [...(globalMonthly || [])].sort((a, b) =>
    a.year !== b.year ? a.year - b.year : a.month - b.month
  )
}

function monthKey(year, month) {
  return `${year}-${String(month).padStart(2, '0')}`
}

// ─── Capital aportado consolidado ───────────────────────────────────────────
/**
 * netCapitalContributed
 * Una sola fórmula para "capital aportado" usada en todas partes:
 *   capital_inicio del PRIMER mes + Σ(deposits − withdrawals).
 *
 * Sin la baseline, el % "sobre lo aportado" se infla porque divide por un
 * monto chiquito (solo los flujos explícitos, no la plata que ya estaba
 * cuando empezó a trackear).
 *
 * @param {Array} globalMonthly — entradas del broker `global`
 * @returns {number} capital aportado total (USD)
 */
export function netCapitalContributed(globalMonthly) {
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return 0
  const baseline = sorted[0].capital_inicio || 0
  const flows = sorted.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)
  return baseline + flows
}

// ─── Serie de retorno acumulado (TWRR) ──────────────────────────────────────
/**
 * buildCumulativeReturnSeries
 *
 * Construye un índice de retorno acumulado time-weighted (TWRR) a partir de
 * monthly_entries del broker `global`. Es el estándar para medir "rendimiento
 * del manager" porque NEUTRALIZA depósitos y retiros — un aporte grande no
 * cuenta como ganancia, un retiro no cuenta como caída.
 *
 * Para cada mes (Modified Dietz):
 *   net_flow      = deposits − withdrawals
 *   avg_capital   = capital_inicio + 0.5 × net_flow
 *   monthly_return = (capital_final − capital_inicio − net_flow) / avg_capital
 *
 * Modified Dietz (vs el "TWRR ingenuo" anterior con denominador = capital_inicio)
 * tiene dos ventajas:
 *   1. Funciona cuando capital_inicio = 0 (primer mes) si hay depósitos.
 *   2. No infla artificialmente el retorno cuando un depósito grande llega
 *      sobre un capital chico (e.g. start=$1k, deposit=$10k, gain=$200 →
 *      la fórmula vieja daba 20%; Modified Dietz da ~3%).
 *
 * El monthly_return se clampea a ≥ −0.99 para evitar que un mes con
 * `capital_final` muy negativo (drift de cash en negativo tras imports/reverts)
 * haga colapsar el índice acumulado a 0 o lo invierta — el peor caso "real"
 * de un mes es perder ~todo lo invertido.
 *
 * El índice empieza en 1.0 antes del primer mes y se compone:
 *   index_t = index_(t-1) × (1 + monthly_return_t)
 *
 * Para el mes en curso (último entry), si se pasa `liveValue` se usa como
 * `capital_final` actual, así el último punto de la serie refleja el
 * rendimiento al día de hoy en vez del último cierre del mes pasado.
 *
 * @param {Array}  globalMonthly  entradas del broker `global`
 * @param {number} liveValue      valor live opcional para el mes en curso (USD)
 * @returns {Array<{ key: string, label: string, year: number, month: number,
 *                   index: number, monthlyReturn: number, capInicio: number,
 *                   capFinal: number, netFlow: number }> | null}
 */
export function buildCumulativeReturnSeries(globalMonthly, liveValue = null) {
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return null

  const out = []
  let idx = 1

  for (let i = 0; i < sorted.length; i++) {
    const m = sorted[i]
    const isLast = i === sorted.length - 1
    const capInicio = m.capital_inicio || 0
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    const capFinal = (isLast && liveValue != null && liveValue > 0)
      ? liveValue
      : (m.capital_final || 0)

    const avgCapital = capInicio + 0.5 * net
    const rawReturn = avgCapital > 0
      ? (capFinal - capInicio - net) / avgCapital
      : 0
    // Clamp inferior: un mes individual no puede perder más del 99% en TWRR.
    // Sin clamp, datos corruptos (cap_final < 0) propagan el daño a TODOS los
    // meses posteriores vía multiplicación, inflando el drawdown a cientos.
    const monthlyReturn = Math.max(rawReturn, -0.99)

    idx = idx * (1 + monthlyReturn)

    out.push({
      key: monthKey(m.year, m.month),
      label: monthKey(m.year, m.month),
      year: m.year,
      month: m.month,
      index: idx,
      monthlyReturn,
      capInicio,
      capFinal,
      netFlow: net,
    })
  }

  return out
}

// ─── Drawdown sobre la serie TWRR ───────────────────────────────────────────
/**
 * computeDrawdownOnReturns
 *
 * Drawdown calculado sobre la serie de retorno acumulado, NO sobre valor
 * absoluto. La diferencia es importante:
 *   • Sobre valor absoluto: un retiro grande aparece como drawdown, lo
 *     cual es engañoso (no perdiste plata, te la sacaste).
 *   • Sobre TWRR: el drawdown refleja únicamente movimientos de mercado.
 *
 * Devuelve drawdown máximo histórico y drawdown actual (vs HWM).
 *
 * @param {Array} series — output de buildCumulativeReturnSeries
 * @returns {{ maxPct, currentPct, peakKey, peakIndex, troughKey, troughIndex } | null}
 */
export function computeDrawdownOnReturns(series) {
  if (!series || series.length < 2) return null

  let hwm = series[0].index
  let curHwmIdx = 0
  let maxDd = 0
  let peakIdx = 0
  let troughIdx = 0

  for (let i = 1; i < series.length; i++) {
    if (series[i].index > hwm) {
      hwm = series[i].index
      curHwmIdx = i
    }
    const dd = (series[i].index - hwm) / hwm
    if (dd < maxDd) {
      maxDd = dd
      peakIdx = curHwmIdx
      troughIdx = i
    }
  }

  // Drawdown actual = retorno actual vs HWM histórico
  const allTimeHwm = series.reduce((mx, s) => Math.max(mx, s.index), -Infinity)
  const last = series[series.length - 1].index
  const currentDd = (last - allTimeHwm) / allTimeHwm

  return {
    maxPct: maxDd * 100,           // negativo o 0
    currentPct: currentDd * 100,   // negativo o 0
    peakKey: series[peakIdx].key,
    peakIndex: series[peakIdx].index,
    troughKey: series[troughIdx].key,
    troughIndex: series[troughIdx].index,
    // Como % de retorno acumulado en el peak / trough (más legible que el índice).
    peakReturnPct: (series[peakIdx].index - 1) * 100,
    troughReturnPct: (series[troughIdx].index - 1) * 100,
  }
}

// ─── Mejor / peor mes (excluyendo mes en curso) ─────────────────────────────
/**
 * computeBestWorstMonth
 *
 * Detecta el mes con mayor y menor rendimiento porcentual sobre el capital
 * de inicio. Excluye el mes calendario actual porque está incompleto.
 *
 * Fórmula:
 *   pnl_mes = capital_final − capital_inicio − (depósitos − retiros)
 *   pct     = pnl_mes / capital_inicio
 *
 * @param {Array}  globalMonthly      entradas del broker `global`
 * @param {Date}   today              fecha de referencia (default = ahora)
 * @returns {{ best, worst, count } | null}  best/worst tienen { year, month, pnl, pct }
 */
export function computeBestWorstMonth(globalMonthly, today = new Date()) {
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return null

  const todayY = today.getFullYear()
  const todayM = today.getMonth() + 1

  // Excluye el mes en curso — está incompleto y comparar contra meses
  // cerrados es injusto.
  const closed = sorted.filter(m => !(m.year === todayY && m.month === todayM))

  const months = closed
    .map(m => {
      const capInicio = m.capital_inicio || 0
      const capFinal = m.capital_final || 0
      const net = (m.deposits || 0) - (m.withdrawals || 0)
      const pnl = capFinal - capInicio - net
      const pct = capInicio > 0 ? (pnl / capInicio) * 100 : null
      return { year: m.year, month: m.month, pnl, pct }
    })
    .filter(m => m.pct != null)

  if (months.length === 0) return null

  const best = months.reduce((a, b) => (a.pct >= b.pct ? a : b))
  const worst = months.reduce((a, b) => (a.pct <= b.pct ? a : b))
  return { best, worst, count: months.length }
}

// ─── Contribución por activo (realized + unrealized) ────────────────────────
/**
 * computeAssetContribution
 *
 * Suma del P&L total por activo, combinando:
 *   • Operaciones cerradas (realized) — pnl_usd ya viene calculado.
 *   • Posiciones abiertas (unrealized) — se le pasa el pnl_usd al caller.
 *
 * Reemplaza la métrica vieja "Activo estrella" que solo miraba operaciones
 * cerradas: si tu mejor activo todavía está abierto, no aparecía.
 *
 * @param {Array} operations  [{ asset, pnl_usd, ... }]
 * @param {Array} openPositions  [{ asset, pnl_usd, ... }] (cash excluido por el caller)
 * @returns {Array<{ asset, pnl, realized, unrealized, hasOpen, hasClosed }>}
 *          ordenado por pnl desc.
 */
export function computeAssetContribution(operations = [], openPositions = []) {
  const map = new Map()

  for (const op of operations) {
    const k = (op.asset || '').toUpperCase()
    if (!k) continue
    const cur = map.get(k) || { asset: k, realized: 0, unrealized: 0, hasClosed: false, hasOpen: false }
    cur.realized += (op.pnl_usd || 0)
    cur.hasClosed = true
    map.set(k, cur)
  }

  for (const p of openPositions) {
    const k = (p.asset || '').toUpperCase()
    if (!k) continue
    if (p.pnl_usd == null) continue  // sin precio no contribuye
    const cur = map.get(k) || { asset: k, realized: 0, unrealized: 0, hasClosed: false, hasOpen: false }
    cur.unrealized += p.pnl_usd
    cur.hasOpen = true
    map.set(k, cur)
  }

  return [...map.values()]
    .map(x => ({ ...x, pnl: x.realized + x.unrealized }))
    .sort((a, b) => b.pnl - a.pnl)
}

// ─── Mejor operación cerrada individual ─────────────────────────────────────
/**
 * computeBestWorstClosedOp
 *
 * La operación cerrada individual con mayor / menor pnl_usd.
 * Se separa de computeAssetContribution: no es lo mismo "el activo que más
 * te dio en total" que "la operación más grande que cerraste".
 *
 * @param {Array} operations
 * @returns {{ best, worst } | null}
 */
export function computeBestWorstClosedOp(operations = []) {
  const valid = operations.filter(o => o.pnl_usd != null)
  if (valid.length === 0) return null
  const best = valid.reduce((a, b) => (a.pnl_usd >= b.pnl_usd ? a : b))
  const worst = valid.reduce((a, b) => (a.pnl_usd <= b.pnl_usd ? a : b))
  return { best, worst, count: valid.length }
}

// ─── Consistencia mensual ──────────────────────────────────────────────────
/**
 * computeMonthlyConsistency
 *
 * Mide qué tan estable es tu rendimiento mes a mes:
 *   • % de meses positivos: cuántos meses cerraron con retorno > 0.
 *   • std deviation del retorno mensual: dispersión.
 *
 * Entrada: la serie TWRR ya construida (cada elemento tiene `monthlyReturn`).
 * Excluye automáticamente el mes en curso si `excludeCurrent === true`.
 *
 * @param {Array} returnSeries  output de buildCumulativeReturnSeries
 * @param {Date}  today         referencia para excluir mes en curso (opcional)
 * @returns {{ positivePct, stdDev, positiveCount, negativeCount, total } | null}
 */
export function computeMonthlyConsistency(returnSeries, today = new Date()) {
  if (!returnSeries || returnSeries.length === 0) return null

  const todayY = today.getFullYear()
  const todayM = today.getMonth() + 1

  // Excluye mes en curso (incompleto)
  const closed = returnSeries.filter(s => !(s.year === todayY && s.month === todayM))
  if (closed.length === 0) return null

  const returns = closed.map(s => s.monthlyReturn)
  const positive = returns.filter(r => r > 0).length
  const negative = returns.filter(r => r < 0).length
  const total = returns.length

  // Std dev poblacional (no muestral) — estamos describiendo la distribución
  // observada, no inferiendo a una población.
  const mean = returns.reduce((s, r) => s + r, 0) / total
  const variance = returns.reduce((s, r) => s + (r - mean) ** 2, 0) / total
  const stdDev = Math.sqrt(variance)

  return {
    positivePct: (positive / total) * 100,
    stdDev: stdDev * 100,                    // % puntos
    positiveCount: positive,
    negativeCount: negative,
    total,
    meanReturn: mean * 100,
  }
}

// ─── Drawdown como serie temporal ───────────────────────────────────────────
/**
 * buildDrawdownTimeSeries
 *
 * Para cada punto de la serie TWRR, calcula el drawdown actual (% por debajo
 * del HWM hasta ese momento). Sirve para graficar la curva de drawdown — la
 * imagen mental clásica de "underwater chart" usada en finanzas profesionales.
 *
 * @param {Array} returnSeries  output de buildCumulativeReturnSeries
 * @returns {Array<{ key, label, ddPct }>}  ddPct en (-∞, 0]
 */
export function buildDrawdownTimeSeries(returnSeries) {
  if (!returnSeries || returnSeries.length === 0) return []
  let hwm = returnSeries[0].index
  return returnSeries.map(p => {
    if (p.index > hwm) hwm = p.index
    const dd = ((p.index - hwm) / hwm) * 100   // siempre ≤ 0
    // Label: "Feb '26" format — p.key is "YYYY-MM"
    const [yr, mo] = p.key.split('-')
    const MON = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']
    const label = `${MON[(+mo) - 1] || mo} '${yr.slice(2)}`
    return { key: p.key, label, ddPct: +dd.toFixed(2) }
  })
}

// ─── Mejor / peor posición abierta ──────────────────────────────────────────
/**
 * computeOpenPositionExtremes
 *
 * Devuelve la posición abierta con mayor pnl_usd y la de menor (peor pérdida
 * no realizada). Excluye posiciones cash y posiciones sin precio resuelto.
 *
 * @param {Array} openPositions  [{ asset, broker, pnl_usd, pnl_pct, value_usd }]
 * @returns {{ best, worst, count } | null}
 */
export function computeOpenPositionExtremes(openPositions = []) {
  const valid = openPositions.filter(p => p.pnl_usd != null && !p.is_cash)
  if (valid.length === 0) return null
  const best = valid.reduce((a, b) => (a.pnl_usd >= b.pnl_usd ? a : b))
  const worst = valid.reduce((a, b) => (a.pnl_usd <= b.pnl_usd ? a : b))
  return { best, worst, count: valid.length }
}

// ─── Concentración por broker ──────────────────────────────────────────────
/**
 * computeBrokerConcentration
 *
 * Calcula el % del valor total del portfolio que tiene cada broker, ordenado
 * de mayor a menor. Útil para detectar dependencia de un solo broker
 * (riesgo de contraparte).
 *
 * @param {Array<{ name, value }>} brokerTotals  brokers con value en USD
 * @returns {{ top, brokers: Array<{ name, value, sharePct }>, total } | null}
 */
export function computeBrokerConcentration(brokerTotals = []) {
  const positive = brokerTotals.filter(b => b.value > 0)
  if (positive.length === 0) return null
  const total = positive.reduce((s, b) => s + b.value, 0)
  if (total === 0) return null
  const sorted = [...positive].sort((a, b) => b.value - a.value)
  const enriched = sorted.map(b => ({ ...b, sharePct: (b.value / total) * 100 }))
  return { top: enriched[0], brokers: enriched, total }
}

// ─── Distribución por tipo de activo ───────────────────────────────────────
const CRYPTO_TICKERS = new Set([
  'BTC','ETH','SOL','BNB','ADA','XRP','MATIC','DOT','AVAX','LINK','LTC','BCH',
  'ATOM','UNI','USDT','USDC','DAI','DOGE','SHIB','TRX','XLM','VET','FIL','ICP',
  'APT','NEAR','ARB','OP','SUI','TON','PEPE','WBTC','STETH','HYPE','BONK','WLD',
])

/**
 * classifyAssetType
 *
 * Heurística para clasificar un activo en una categoría de alto nivel.
 * No requiere campo `type` en el modelo de datos — usa el ticker y la
 * moneda del broker.
 *
 * Categorías:
 *   • Cash      — posición marcada is_cash
 *   • Cripto    — ticker en lista de cripto conocidos
 *   • CEDEAR/AR — broker ARS (acción argentina o CEDEAR)
 *   • Acción/ETF — broker USD, ticker no cripto (fallback razonable)
 *
 * @param {Object} position  { asset, broker, is_cash }
 * @param {Array}  brokers   [{ name, currency }]
 * @returns {string} categoría
 */
export function classifyAssetType(position, brokers = []) {
  if (!position) return 'Otro'
  if (position.is_cash) return 'Cash'
  const ticker = String(position.asset || '').toUpperCase()
  if (CRYPTO_TICKERS.has(ticker)) return 'Cripto'
  const broker = brokers.find(b => b.name === position.broker)
  if (broker?.currency === 'ARS') return 'CEDEAR/AR'
  return 'Acción/ETF'
}

/**
 * computeAssetTypeBreakdown
 *
 * Suma el valor en USD de cada posición por categoría.
 *
 * @param {Array} positions     [{ asset, broker, is_cash, value_usd }]
 *                              value_usd debe estar pre-resuelto por el caller.
 * @param {Array} brokers       [{ name, currency }]
 * @returns {Array<{ type, value, sharePct }>}  ordenado por value desc.
 */
export function computeAssetTypeBreakdown(positions = [], brokers = []) {
  const map = new Map()
  for (const p of positions) {
    if (p.value_usd == null || p.value_usd <= 0) continue
    const t = classifyAssetType(p, brokers)
    map.set(t, (map.get(t) || 0) + p.value_usd)
  }
  const total = [...map.values()].reduce((s, v) => s + v, 0)
  if (total === 0) return []
  return [...map.entries()]
    .map(([type, value]) => ({ type, value, sharePct: (value / total) * 100 }))
    .sort((a, b) => b.value - a.value)
}

// ─── Profit factor ──────────────────────────────────────────────────────────
/**
 * computeProfitFactor
 *
 * Profit factor = ganancia bruta / pérdida bruta. Métrica complementaria al
 * win rate: te dice cuántos dólares ganados hay por cada dólar perdido.
 * Más significativo que win rate solo, porque captura la asimetría de tamaño
 * (5 ganadoras chicas + 2 perdedoras grandes pueden tener PF < 1 con WR alto).
 *
 *   PF > 1: el sistema gana plata neta.
 *   PF = 1: empatado.
 *   PF < 1: el sistema pierde plata neta.
 *
 * @param {Array} operations
 * @returns {{ profitFactor, grossWin, grossLoss, total } | null}
 *          profitFactor === Infinity si no hubo pérdidas (no calculable real).
 */
export function computeProfitFactor(operations = []) {
  const valid = operations.filter(o => o.pnl_usd != null)
  if (valid.length === 0) return null

  let grossWin = 0
  let grossLoss = 0
  for (const o of valid) {
    if (o.pnl_usd > 0) grossWin += o.pnl_usd
    else if (o.pnl_usd < 0) grossLoss += Math.abs(o.pnl_usd)
  }
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : (grossWin > 0 ? Infinity : 0)

  return { profitFactor, grossWin, grossLoss, total: valid.length }
}
