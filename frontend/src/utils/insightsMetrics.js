// insightsMetrics.js
// ─────────────────────
// Métricas pro de performance: Sharpe Ratio, Volatilidad anualizada.
//
// Pensado para inversores que vienen de cuentas Schwab/IBKR — la primera
// pregunta clásica de un user con experiencia es "¿cuál es mi Sharpe?".
//
// Fórmulas usadas (alineadas con industry standard):
//
//   1. Returns mensuales (TWRR vía Modified Dietz):
//      r_t = (end - start - net_flow) / (start + net_flow * 0.5)
//
//      Modified Dietz asume que los flujos del mes están distribuidos
//      uniformemente (weight 0.5). Aproximación buena vs alternativas
//      más complejas (IRR/XIRR) cuando los flows son moderados.
//
//   2. Volatilidad anualizada:
//      σ_mensual = stdev sample de returns
//      σ_anual = σ_mensual × √12
//
//   3. Sharpe Ratio:
//      μ_anual = mean(returns_mensuales) × 12  (anualización lineal — industry std)
//      sharpe = (μ_anual − rf_anual) / σ_anual
//
//   4. Risk-free rate (rf):
//      Derivada del ETF SHV (T-Bills 0-3M USD). Anualizamos su retorno
//      en el período disponible. Fallback: 4.5% (TNA T-Bills típica 2025-2026).
//
// Interpretación de Sharpe:
//   < 0    → Le perdés a la tasa libre de riesgo (mejor estar en T-Bills)
//   0-1    → Subóptimo: tomás riesgo pero el premium es bajo
//   1-2    → Bueno
//   > 2    → Excelente (alto premium por riesgo asumido)
//   > 3    → Excepcional / sospechoso (validar que no haya outliers)
//
// Validaciones:
//   • Mínimo 3 meses de returns para que el cálculo sea estadísticamente útil
//   • Returns mensuales |r| > 300% se descartan como outliers (probable bug)
//   • Si stdev = 0 (returns constantes), Sharpe es undefined → null

const RF_RATE_FALLBACK = 0.045  // 4.5% anual — TNA T-Bills típica 2025-2026
const MIN_MONTHS_FOR_STATS = 3
const MAX_MONTHLY_RETURN = 3  // ±300% → outlier, probable bug en data

/**
 * Computa los retornos mensuales TWRR (Modified Dietz) del portfolio.
 *
 * @param {Array} globalMonthly  entries del broker 'global'
 * @returns {Array<{key, return}>}  retornos mensuales en fracción (0.05 = +5%)
 */
export function computeMonthlyReturns(globalMonthly) {
  if (!globalMonthly || globalMonthly.length === 0) return []
  const sorted = [...globalMonthly].sort((a, b) =>
    a.year !== b.year ? a.year - b.year : a.month - b.month
  )
  const out = []
  for (const m of sorted) {
    const start = m.capital_inicio || 0
    const end = m.capital_final || 0
    const netFlow = (m.deposits || 0) - (m.withdrawals || 0)
    // Skip meses sin capital significativo (evita divisiones por números chicos)
    if (start <= 100 && Math.abs(netFlow) <= 100) continue
    // Modified Dietz: denominator = start + flow_weight × net_flow
    const denom = start + netFlow * 0.5
    if (denom <= 100) continue  // denominador muy chico → return inestable
    const gain = end - start - netFlow
    const ret = gain / denom
    // Descartar outliers (>±300% mensual indica bug en data)
    if (Math.abs(ret) > MAX_MONTHLY_RETURN) continue
    out.push({
      key: `${m.year}-${String(m.month).padStart(2, '0')}`,
      return: ret,
    })
  }
  return out
}

/**
 * Volatilidad anualizada de los returns mensuales.
 *
 * σ_anual = stdev_sample(returns_mensuales) × √12
 *
 * @param {Array} monthlyReturns  output de computeMonthlyReturns
 * @returns {number | null}  volatilidad anualizada en fracción (0.15 = 15%)
 */
export function computeAnnualizedVolatility(monthlyReturns) {
  if (!monthlyReturns || monthlyReturns.length < MIN_MONTHS_FOR_STATS) return null
  const returns = monthlyReturns.map(r => r.return)
  const n = returns.length
  const mean = returns.reduce((s, r) => s + r, 0) / n
  // Sample variance (n-1 en el denominador)
  const variance = returns.reduce((s, r) => s + Math.pow(r - mean, 2), 0) / (n - 1)
  const stdDev = Math.sqrt(variance)
  return stdDev * Math.sqrt(12)
}

/**
 * Sortino Ratio — variante de Sharpe que penaliza SOLO la volatilidad
 * a la baja (downside deviation), no la volatilidad total.
 *
 *   downside_dev = √(Σ min(R_t - target, 0)² / n) × √12
 *   sortino = (μ_anual − rf_anual) / downside_dev
 *
 * Más justo que Sharpe porque el inversor real no se asusta por
 * volatilidad upside (returns positivos altos no son "riesgo").
 *
 * Target = rf_mensual (mismo benchmark que Sharpe).
 *
 * @param {Array}  monthlyReturns
 * @param {number} rfAnnual
 * @returns {{sortino, downsideDev, returnAnnual, months} | null}
 */
export function computeSortino(monthlyReturns, rfAnnual = RF_RATE_FALLBACK) {
  if (!monthlyReturns || monthlyReturns.length < MIN_MONTHS_FOR_STATS) return null
  const returns = monthlyReturns.map(r => r.return)
  const n = returns.length
  const mean = returns.reduce((s, r) => s + r, 0) / n
  const rfMonthly = rfAnnual / 12

  // Downside deviation: solo considera retornos por debajo del target.
  // Formal: √(Σ min(R - target, 0)² / n) × √12
  // Nota: el denominador es n (no n-1) porque NO es muestra de stdev clásica,
  // sino "semivarianza" — ver Sortino (1991).
  let sumSquaredDownside = 0
  for (const r of returns) {
    const dev = r - rfMonthly
    if (dev < 0) sumSquaredDownside += dev * dev
  }
  const downsideDev = Math.sqrt(sumSquaredDownside / n) * Math.sqrt(12)
  if (downsideDev === 0) return null  // sin downside → sortino indefinido

  const returnAnnual = mean * 12
  const sortino = (returnAnnual - rfAnnual) / downsideDev
  return {
    sortino,
    downsideDev,
    returnAnnual,
    months: n,
  }
}

/**
 * Estima la risk-free rate anualizada desde el ETF SHV (T-Bills 0-3M).
 *
 * Anualiza el return del SHV en el período disponible (últimos ≤13 meses).
 *
 * @param {Object} shvMonthly  { 'YYYY-MM': close } del SHV ETF
 * @returns {number}  tasa anualizada en fracción (e.g. 0.045 = 4.5%)
 */
export function estimateRiskFreeRate(shvMonthly) {
  if (!shvMonthly || typeof shvMonthly !== 'object') return RF_RATE_FALLBACK
  const keys = Object.keys(shvMonthly).sort()
  if (keys.length < 2) return RF_RATE_FALLBACK
  // Últimos ≤13 meses para tener referencia reciente (no diluir con histórico).
  const recent = keys.slice(-13)
  if (recent.length < 2) return RF_RATE_FALLBACK
  const first = shvMonthly[recent[0]]
  const last = shvMonthly[recent[recent.length - 1]]
  if (!first || !last || first <= 0) return RF_RATE_FALLBACK
  const numMonths = recent.length - 1
  const totalReturn = last / first - 1
  // Anualizar — si tenemos 12 meses, totalReturn ≈ rf anual.
  const annualized = Math.pow(1 + totalReturn, 12 / numMonths) - 1
  // Sanity check — rf > 30% o < 0% es probable data corrupta
  if (annualized < 0 || annualized > 0.30) return RF_RATE_FALLBACK
  return annualized
}

/**
 * Sharpe Ratio del portfolio.
 *
 * sharpe = (return_anualizado − rf_anualizada) / volatilidad_anualizada
 *
 * Anualización lineal (industry standard para Sharpe): mean(r_m) × 12.
 *
 * @param {Array} monthlyReturns  output de computeMonthlyReturns
 * @param {number} rfAnnual  tasa libre de riesgo anualizada (fracción)
 * @returns {{sharpe, returnAnnual, rfAnnual, volatility, months} | null}
 */
export function computeSharpe(monthlyReturns, rfAnnual = RF_RATE_FALLBACK) {
  if (!monthlyReturns || monthlyReturns.length < MIN_MONTHS_FOR_STATS) return null
  const returns = monthlyReturns.map(r => r.return)
  const n = returns.length
  const mean = returns.reduce((s, r) => s + r, 0) / n
  const returnAnnual = mean * 12
  const volatility = computeAnnualizedVolatility(monthlyReturns)
  if (volatility == null || volatility === 0) return null
  const sharpe = (returnAnnual - rfAnnual) / volatility
  return {
    sharpe,
    returnAnnual,
    rfAnnual,
    volatility,
    months: n,
  }
}

/**
 * Computa returns mensuales de una serie de precios mensuales.
 * Usado para derivar la serie del benchmark (S&P, etc.).
 *
 * @param {Object} priceMap  { 'YYYY-MM': close_price }
 * @returns {Array<{key, return}>}  retornos en fracción
 */
export function computePriceMapReturns(priceMap) {
  if (!priceMap || typeof priceMap !== 'object') return []
  const sortedKeys = Object.keys(priceMap).sort()
  if (sortedKeys.length < 2) return []
  const out = []
  for (let i = 1; i < sortedKeys.length; i++) {
    const prev = priceMap[sortedKeys[i - 1]]
    const curr = priceMap[sortedKeys[i]]
    if (!prev || prev <= 0 || curr == null || curr <= 0) continue
    out.push({
      key: sortedKeys[i],
      return: curr / prev - 1,
    })
  }
  return out
}

/**
 * Alpha + Beta del portfolio vs un benchmark (CAPM / Jensen's Alpha).
 *
 *   Beta  = Cov(R_p, R_b) / Var(R_b)
 *   Alpha = mean(R_p) − [Rf_m + Beta × (mean(R_b) − Rf_m)]
 *   R²    = Cov² / (Var(R_p) × Var(R_b))
 *
 * Interpretación:
 *   • Beta = 1.0  → te movés igual que el benchmark
 *   • Beta > 1.0  → más volátil que el mercado (más riesgo de mercado)
 *   • Beta < 1.0  → más defensivo (menos sensible)
 *   • Beta ≈ 0    → no correlacionado
 *   • Beta < 0    → te movés contrario (poco común, hedge)
 *
 *   • Alpha > 0   → outperformaste lo que CAPM predice (skill o suerte)
 *   • Alpha = 0   → matchearás al modelo
 *   • Alpha < 0   → underperformaste
 *
 * R² indica qué tanto del portfolio se explica por el benchmark:
 *   1.0 = idéntico; 0 = independiente. R² alto + Alpha alto = outperform real.
 *
 * Mínimo 6 meses de overlap para que las estadísticas sean confiables.
 *
 * @param {Array}  portfolioReturns  output de computeMonthlyReturns
 * @param {Array}  benchmarkReturns  output de computePriceMapReturns
 * @param {number} rfAnnual          tasa libre de riesgo anualizada
 * @returns {{alpha, alphaAnnual, beta, rSquared, months} | null}
 */
export function computeAlphaBeta(portfolioReturns, benchmarkReturns, rfAnnual = RF_RATE_FALLBACK) {
  if (!portfolioReturns || !benchmarkReturns) return null

  // Index benchmark por key para lookup O(1)
  const benchByKey = {}
  for (const b of benchmarkReturns) benchByKey[b.key] = b.return

  // Pares (R_p, R_b) solo para meses donde AMBOS tienen return
  const pairs = []
  for (const p of portfolioReturns) {
    const b = benchByKey[p.key]
    if (b != null) pairs.push({ rp: p.return, rb: b })
  }

  if (pairs.length < 6) return null  // mínimo 6 meses overlap para confiabilidad

  const n = pairs.length
  const meanP = pairs.reduce((s, x) => s + x.rp, 0) / n
  const meanB = pairs.reduce((s, x) => s + x.rb, 0) / n

  // Covariance y variance (sample, n-1)
  let cov = 0
  let varB = 0
  let varP = 0
  for (const p of pairs) {
    cov += (p.rp - meanP) * (p.rb - meanB)
    varB += Math.pow(p.rb - meanB, 2)
    varP += Math.pow(p.rp - meanP, 2)
  }
  cov /= n - 1
  varB /= n - 1
  varP /= n - 1

  if (varB === 0) return null  // benchmark sin volatilidad → Beta indefinido

  const beta = cov / varB
  const rSquared = varP > 0 ? (cov * cov) / (varP * varB) : 0

  // CAPM: alpha_mensual = mean(R_p) − [Rf_m + Beta × (mean(R_b) − Rf_m)]
  const rfMonthly = rfAnnual / 12  // aprox lineal — industry std
  const alpha = meanP - (rfMonthly + beta * (meanB - rfMonthly))
  const alphaAnnual = alpha * 12  // anualización lineal

  return {
    alpha,
    alphaAnnual,
    beta,
    rSquared,
    months: n,
  }
}

/**
 * Information Ratio — mide el "active return" por unidad de tracking error.
 *
 *   active_return_t = R_p_t - R_b_t
 *   tracking_error  = stdev(active_return) × √12   (anualizado)
 *   IR              = (mean(R_p) − mean(R_b)) × 12 / tracking_error
 *
 * Diferencia con Sharpe: IR compara contra el BENCHMARK (S&P), no contra
 * la tasa libre de riesgo. Mide "skill activo" — qué tan consistentemente
 * superás al índice por encima del nivel de desviación que asumís.
 *
 * Interpretación:
 *   > 0.5  → consistencia en outperformance
 *   > 1.0  → excelente (raro mantener sostenido)
 *   < 0    → underperformance crónica
 *
 * @param {Array} portfolioReturns
 * @param {Array} benchmarkReturns
 * @returns {{infoRatio, trackingError, activeReturn, months} | null}
 */
export function computeInformationRatio(portfolioReturns, benchmarkReturns) {
  if (!portfolioReturns || !benchmarkReturns) return null
  const benchByKey = {}
  for (const b of benchmarkReturns) benchByKey[b.key] = b.return

  const pairs = []
  for (const p of portfolioReturns) {
    const b = benchByKey[p.key]
    if (b != null) pairs.push({ rp: p.return, rb: b })
  }
  if (pairs.length < 6) return null

  const n = pairs.length
  const meanP = pairs.reduce((s, x) => s + x.rp, 0) / n
  const meanB = pairs.reduce((s, x) => s + x.rb, 0) / n

  // Active returns y su stdev (tracking error)
  const activeReturns = pairs.map(p => p.rp - p.rb)
  const meanActive = activeReturns.reduce((s, r) => s + r, 0) / n
  const varActive = activeReturns.reduce((s, r) => s + Math.pow(r - meanActive, 2), 0) / (n - 1)
  const trackingError = Math.sqrt(varActive) * Math.sqrt(12)
  // Guard: si TE es muy chico (<0.1% anual), el IR puede explotar a valores
  // absurdos por floating-point. En la práctica eso indica returns casi
  // idénticos al benchmark, sin alpha real para medir.
  if (trackingError < 0.001) return null

  const activeReturnAnnual = (meanP - meanB) * 12
  const infoRatio = activeReturnAnnual / trackingError
  // Cap visual: IR > 10 es matemáticamente posible pero clínicamente raro.
  // Mantenemos el valor real pero los users lo ven con disclaimer en UI.
  return {
    infoRatio,
    trackingError,
    activeReturn: activeReturnAnnual,
    months: n,
  }
}

/**
 * Helper combinado: dado globalMonthly + bench, devuelve TODAS las métricas pro.
 *
 * Métricas incluidas:
 *   • Volatilidad anualizada  (Plus)
 *   • Beta vs S&P 500          (Plus)
 *   • Sharpe Ratio             (Pro)
 *   • Sortino Ratio            (Pro)
 *   • Alpha (Jensen's CAPM)    (Pro)
 *   • Information Ratio        (Pro)
 *
 * @param {Array}  globalMonthly  entries del broker 'global'
 * @param {Object} bench          { sp500, shv, ... } del endpoint /benchmarks
 * @returns {{returns, volatility, sharpe, sortino, alphaBeta, infoRatio} | null}
 */
export function computeProMetrics(globalMonthly, bench) {
  const returns = computeMonthlyReturns(globalMonthly)
  if (returns.length < MIN_MONTHS_FOR_STATS) return null

  // Risk-free rate anualizada para Sharpe/Sortino/Alpha (constante).
  // Posible mejora: rf temporal por mes (rf_t para cada mes) si los rangos
  // son largos y la TNA varió mucho. Para portfolios <= 24 meses, la
  // aproximación constante introduce <50bps de sesgo en Alpha.
  const rf = estimateRiskFreeRate(bench?.shv)

  const volatility = computeAnnualizedVolatility(returns)
  const sharpe = computeSharpe(returns, rf)
  const sortino = computeSortino(returns, rf)

  // Alpha/Beta + Information Ratio vs S&P 500 (benchmark de referencia global).
  const sp500Returns = computePriceMapReturns(bench?.sp500)
  const alphaBeta = sp500Returns.length >= 6
    ? computeAlphaBeta(returns, sp500Returns, rf)
    : null
  const infoRatio = sp500Returns.length >= 6
    ? computeInformationRatio(returns, sp500Returns)
    : null

  return {
    returns,
    volatility,
    sharpe,
    sortino,
    alphaBeta,
    infoRatio,
  }
}
