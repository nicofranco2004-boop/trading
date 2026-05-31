import { lookupHistoricalDolar } from './fx'

/**
 * buildPortfolioValueSeries
 * ─────────────────────────
 * Returns [{ date, label, valueUsd, netDeposited }, ...] from snapshots,
 * optionally filtered by `days`. Used by the Dashboard portfolio evolution
 * chart with the 1D / 1W / 1M / 6M / 1Y / MAX selector.
 *
 * If a `liveValue` is provided AND the latest snapshot is older than today
 * (or absent for today), we append a synthetic "today" point so the chart
 * always shows the current portfolio value as the rightmost data point.
 *
 * @param {Array}  snapshots  [{ date, total_value, total_invested, net_deposited }]
 * @param {number} days       window in days (null = all)
 * @param {number} liveValue  optional live portfolio value (USD) to append as today's point
 * @param {number} liveNet    optional live net_deposited (USD) for today's point
 *
 * @returns {Array<{ date, label, valueUsd, netDeposited }>}
 */
export function buildPortfolioValueSeries(snapshots, days = null, liveValue = null, liveNet = null, liveFx = null) {
  const sorted = [...(snapshots || [])].sort((a, b) => a.date < b.date ? -1 : 1)
  const points = sorted.map(s => ({
    date: s.date,
    label: s.date.slice(5), // MM-DD
    valueUsd: +(s.total_value || 0),
    netDeposited: +(s.net_deposited || s.total_invested || 0),
    // Phase C: fx_to_usd_blue stampeado al momento del snapshot. Cuando
    // el toggle global está en ARS, el chart usa este FX (no el actual)
    // para mostrar la realidad histórica. NULL en filas legacy → frontend
    // hace fallback al fx histórico de useFxHistory, después al tcBlue actual.
    fxToUsdBlue: s.fx_to_usd_blue != null ? +s.fx_to_usd_blue : null,
  }))

  // Append "today" if live value supplied and last snapshot isn't already today
  const today = new Date().toISOString().slice(0, 10)
  if (liveValue != null && (points.length === 0 || points[points.length - 1].date !== today)) {
    points.push({
      date: today,
      label: today.slice(5),
      valueUsd: +liveValue,
      netDeposited: liveNet != null ? +liveNet : (points[points.length - 1]?.netDeposited ?? +liveValue),
      fxToUsdBlue: liveFx != null ? +liveFx : null,
    })
  }

  if (days != null && days > 0 && points.length > 0) {
    const cutoff = Date.now() - days * 86400000
    const filtered = points.filter(p => new Date(p.date).getTime() >= cutoff)

    // AUDIT FOLLOW-UP (2026-05-31): siempre PREPEND el último snapshot
    // ANTES del cutoff como ancla del período. Sin este anchor, si el user
    // no entró a Rendi durante varios días al inicio del período, el chart
    // tomaba como `first.value` el primer snapshot DENTRO de la ventana
    // (ej: 22 de mayo) y mostraba un delta más chico que el KPI "Este mes"
    // (que sí ancla en el primer día calendar del mes). Resultado: 3
    // números distintos para "rendimiento del mes" en distintas pantallas.
    // Con el anchor, chart y KPI convergen al mismo número.
    const beforeCutoff = points.filter(p => new Date(p.date).getTime() < cutoff)
    const anchor = beforeCutoff.length > 0 ? beforeCutoff[beforeCutoff.length - 1] : null

    if (filtered.length >= 2) {
      return anchor ? [anchor, ...filtered] : filtered
    }
    if (filtered.length === 1 && anchor) {
      return [anchor, filtered[0]]
    }
    if (filtered.length === 1 && points.length >= 2) {
      // Sin anchor disponible (la ventana captura el primer snapshot de
      // todos los tiempos), preserve previous behavior.
      const idx = points.findIndex(p => p.date === filtered[0].date)
      if (idx > 0) return [points[idx - 1], filtered[0]]
    }
    return points.slice(-Math.max(2, filtered.length))
  }

  return points
}


/**
 * netDepositedOf — baseline para Total Return de un snapshot.
 * Phase 6+ guarda `net_deposited`; snapshots legacy lo tienen en 0 → fallback
 * a `total_invested` (cost basis) para no romper el cálculo. Misma convención
 * que buildPortfolioValueSeries / buildEvolutionFromSnapshots.
 */
function netDepositedOf(s) {
  return (s.net_deposited && s.net_deposited > 0) ? s.net_deposited : (s.total_invested || 0)
}

/**
 * computeReturnDelta
 * ──────────────────
 * Δ(Total Return) entre "hoy" y un punto de referencia, EXCLUYENDO cashflows
 * (depósitos / retiros). Es la base de `computeDailyPnl` (referencia = cierre
 * anterior) y de la variación mensual (referencia = cierre del mes pasado).
 *
 * EL BUG QUE CORRIGE: el cálculo viejo era `Δtotal_value` (valor de hoy − valor
 * de referencia). Pero total_value mezcla aportes con ganancias: si retirás
 * US$110, total_value baja US$110 y se mostraba "−$110" aunque no hayas perdido
 * un centavo. Lo mismo al revés con un depósito (variación inflada).
 *
 * FÓRMULA CORRECTA = Δ(Total Return), donde Total Return = value − net_deposited:
 *
 *   variación = (value − net_deposited)_hoy − (value − net_deposited)_referencia
 *
 * Esto equivale exactamente a "(realizado + no realizado) hoy − (realizado +
 * no realizado) en la referencia": value − net_deposited ES la ganancia
 * acumulada sobre el capital aportado (= realizado + no realizado).
 *
 * Usa el valor LIVE de hoy (si se pasa, refleja precios actuales) contra el
 * snapshot de referencia. Sin liveValue, usa el snapshot más reciente como "hoy".
 *
 * @param {Array}  snapshots               [{ date, total_value, total_invested, net_deposited }]
 * @param {Object} [opts]
 * @param {number} [opts.liveValue]         valor total USD actual (mark-to-market en vivo)
 * @param {number} [opts.liveNetDeposited]  net_deposited actual USD (baseline + flujos)
 * @param {string} [opts.sinceDate]         ISO (YYYY-MM-DD). Referencia = snapshot más
 *   reciente ANTERIOR a esta fecha (ej: cierre del mes pasado para month-to-date).
 *   Si empezaste DENTRO del período (no hay snapshot previo) cae al más antiguo.
 *   Sin sinceDate → modo diario: referencia = cierre más reciente anterior a hoy.
 * @returns {null | { usd:number, pct:number, prevDate:string, dayDiff:number }}
 */
export function computeReturnDelta(snapshots, { liveValue = null, liveNetDeposited = null, sinceDate = null } = {}) {
  if (!snapshots?.length) return null
  const today = new Date().toISOString().slice(0, 10)
  // Orden DESC por fecha — [0] = más reciente.
  const desc = [...snapshots].sort((a, b) => (a.date < b.date ? 1 : -1))

  // "Hoy": preferimos el valor live (refleja la cartera ahora). Fallback al snap más reciente.
  let todayValue, todayNetDep
  if (liveValue != null) {
    todayValue = +liveValue
    todayNetDep = liveNetDeposited != null ? +liveNetDeposited : netDepositedOf(desc[0])
  } else {
    todayValue = +(desc[0].total_value || 0)
    todayNetDep = netDepositedOf(desc[0])
  }

  // Referencia (cierre del período anterior).
  let prev
  if (sinceDate != null) {
    // Cierre más reciente ANTES del inicio del período (ej: último día del mes pasado).
    prev = desc.find(s => s.date < sinceDate)
    // Empezaste dentro del período → no hay cierre previo: usamos el más antiguo.
    if (!prev) prev = desc[desc.length - 1]
  } else if (liveValue != null) {
    // Modo diario con live: cierre más reciente con fecha < hoy (saltea el snap de hoy).
    prev = desc.find(s => s.date < today)
  } else {
    prev = desc[1]  // modo diario sin live: penúltimo snapshot
  }
  if (!prev || !prev.total_value) return null

  const usd = (todayValue - todayNetDep) - ((prev.total_value || 0) - netDepositedOf(prev))
  const prevValue = prev.total_value || 0
  const pct = prevValue > 0 ? usd / prevValue : 0
  const dayDiff = Math.max(1, Math.round((new Date(today) - new Date(prev.date)) / 86_400_000))
  return { usd, pct, prevDate: prev.date, dayDiff }
}

/**
 * computeDailyPnl — P&L del día (variación vs el cierre anterior).
 * Wrapper de computeReturnDelta sin `sinceDate` (modo diario).
 * Ver computeReturnDelta para la explicación del cálculo cashflow-adjusted.
 */
export function computeDailyPnl(snapshots, opts = {}) {
  return computeReturnDelta(snapshots, { ...opts, sinceDate: null })
}


/**
 * buildEvolutionFromSnapshots
 * ───────────────────────────
 * Phase 7 — daily-granularity portfolio evolution from snapshots.
 *
 * Each snapshot point produces:
 *   total %     = (value − baseline) / baseline × 100
 *   realized %  = (cumulative realized at snapshot's month) / baseline × 100
 *
 * `baseline` is the snapshot's `net_deposited` (Phase 6+) or, for legacy
 * snapshots predating Phase 6 (`net_deposited === 0`), falls back to
 * `total_invested` (cost basis) so the chart doesn't go to infinity.
 *
 * Cumulative `pnl_realized` is sourced from `monthly_entries` (the "global"
 * broker, sorted ascending), step-matched onto each snapshot by its YYYY-MM.
 *
 * ARS series: value & baseline are converted using the historical blue rate
 * for the snapshot's (year, month) via `lookupHistoricalDolar`.
 *
 * @param {Array}  snapshots     [{ date, total_value, total_invested, net_deposited }, ...]
 * @param {Array}  globalMonthly monthly_entries for broker='global', SORTED ASC by year/month
 * @param {Object} bench         bench.dolar_blue map (or null)
 * @param {number} tcBlue        live blue rate (used as fallback in lookupHistoricalDolar)
 *
 * @returns {{ seriesUsd: Array, seriesArs: Array } | null}
 *   null if there are <2 snapshots (caller should fall back to monthly logic).
 */
export function buildEvolutionFromSnapshots(snapshots, globalMonthly, bench, tcBlue) {
  if (!snapshots || snapshots.length < 2) return null

  // Pre-compute cumulative pnl_realized by YYYY-MM
  const cumRealizedByMonth = new Map()
  let cum = 0
  for (const m of globalMonthly || []) {
    cum += (m.pnl_realized || 0)
    const key = `${m.year}-${String(m.month).padStart(2, '0')}`
    cumRealizedByMonth.set(key, cum)
  }
  const sortedKeys = [...cumRealizedByMonth.keys()].sort()
  const realizedAt = (dateStr) => {
    const k = dateStr.slice(0, 7)
    if (cumRealizedByMonth.has(k)) return cumRealizedByMonth.get(k)
    let found = null
    for (const kk of sortedKeys) { if (kk <= k) found = kk; else break }
    return found ? cumRealizedByMonth.get(found) : 0
  }

  const sorted = [...snapshots].sort((a, b) => a.date < b.date ? -1 : 1)
  const seriesUsd = []
  const seriesArs = []

  // TWRR chain-linked vía Modified Dietz entre snapshots consecutivos.
  // La fórmula simple (value - net_deposited) / net_deposited es MWR — se
  // distorsiona cuando hay retiros/depósitos grandes (e.g. tras un withdrawal
  // de $177k, net_deposited baja y el ratio se infla a +90% sin que hubiera
  // ganancia real). TWRR usa el rendimiento por período (ajustado por flujos)
  // y los encadena multiplicativamente — neutraliza el timing de flujos.
  //
  //   flows_t       = net_deposited_t − net_deposited_t-1
  //   pnl_t         = (value_t − value_t-1) − flows_t
  //   period_return = pnl_t / (value_t-1 + 0.5 × flows_t)
  //   cum_t         = cum_t-1 × (1 + period_return)
  //
  // Clampeamos period_return ≥ −0.99 para que un período con value=0 (data
  // corrupta) no colapse el multiplicador. -99% es "perdiste casi todo".
  let cumUsd = 1
  let cumArs = 1
  let prevValueUsd = null
  let prevNetDep = null
  let prevValueArs = null
  let prevBaselineArs = null
  // Peak portfolio value alcanzado en toda la historia. Sirve como denominador
  // estable para realized% cuando hay retiros grandes: si la cartera llegó a
  // \$100k y después retirás \$70k para impuestos, net_deposited puede quedar
  // chico o negativo. Usar peakValue evita que el ratio (cumRealized / denom)
  // explote a 90%+ artificialmente — es la base "real" del capital trabajado.
  let peakValueUsd = 0
  let peakValueArs = 0

  for (const s of sorted) {
    const baselineUsd = (s.net_deposited && s.net_deposited > 0) ? s.net_deposited : s.total_invested
    const value = s.total_value || 0
    const netDep = baselineUsd || 0
    if (value > peakValueUsd) peakValueUsd = value

    // First snapshot → baseline = 0% TWRR
    if (prevValueUsd === null) {
      cumUsd = 1
      // Initialize ARS baselines too (snapshot por snapshot tiene su propio fx)
      const y0 = +s.date.slice(0, 4)
      const mo0 = +s.date.slice(5, 7)
      const fx0 = lookupHistoricalDolar(bench, y0, mo0, tcBlue)
      prevBaselineArs = netDep * fx0
      prevValueArs = value * fx0
    } else {
      // USD TWRR period return — Modified Dietz con heurística big-withdrawal.
      //
      // Cuando |flow| > 30% del capital inicial Y flow < 0, Modified Dietz
      // (avgCap = ci + 0.5×flow) achica demasiado el denominador y crea
      // spikes artificiales. Caso real: papá retira \$70k de \$100k de capital
      // y cierra una posición con +\$20k. Con MD clásico: 20/65 = +30.7%
      // que compunde a +91% acumulado. La verdad operativa: ganó \$20 sobre
      // \$100 ≈ +20%. Usamos prevValueUsd directo como denom en esos casos
      // (asumimos withdraw al final del período).
      const flows = netDep - prevNetDep
      const pnl = (value - prevValueUsd) - flows
      const flowRatio = prevValueUsd > 0 ? Math.abs(flows) / prevValueUsd : 0
      const isBigWithdraw = flows < 0 && flowRatio > 0.3
      const avgCap = isBigWithdraw ? prevValueUsd : (prevValueUsd + 0.5 * flows)
      const rRaw = avgCap > 0 ? pnl / avgCap : 0
      const r = Math.min(Math.max(rRaw, -0.99), 0.5)
      cumUsd *= (1 + r)
    }

    // Denominador estable para realized%: el MAYOR de net_deposited actual y
    // el peak portfolio value histórico. Así un withdrawal grande no infla el
    // % al achicar el denominador.
    const denomRealizedUsd = Math.max(baselineUsd, peakValueUsd * 0.8)
    const realPctUsd = denomRealizedUsd > 0 ? (realizedAt(s.date) / denomRealizedUsd) * 100 : 0
    seriesUsd.push({
      key: s.date,
      label: s.date.slice(5),       // MM-DD
      total: +((cumUsd - 1) * 100).toFixed(2),
      realized: +realPctUsd.toFixed(2),
    })

    // ARS: convertir value e invested al fx del snapshot — la conversión
    // afecta tanto numerador como denominador del period_return, así que
    // técnicamente el % se mantiene; sin embargo lo replicamos por simetría.
    const y = +s.date.slice(0, 4)
    const mo = +s.date.slice(5, 7)
    const fx = lookupHistoricalDolar(bench, y, mo, tcBlue)
    const valueArs    = value * fx
    const baselineArs = netDep * fx
    if (valueArs > peakValueArs) peakValueArs = valueArs

    if (prevValueArs !== null && prevBaselineArs !== null) {
      const flowsArs = baselineArs - prevBaselineArs
      const pnlArs = (valueArs - prevValueArs) - flowsArs
      const flowRatioArs = prevValueArs > 0 ? Math.abs(flowsArs) / prevValueArs : 0
      const isBigWithdrawArs = flowsArs < 0 && flowRatioArs > 0.3
      const avgArs = isBigWithdrawArs ? prevValueArs : (prevValueArs + 0.5 * flowsArs)
      const rRawArs = avgArs > 0 ? pnlArs / avgArs : 0
      const rArs = Math.min(Math.max(rRawArs, -0.99), 0.5)
      cumArs *= (1 + rArs)
    }
    const denomRealizedArs = Math.max(baselineArs, peakValueArs * 0.8)
    const realPctArs = denomRealizedArs > 0 ? ((realizedAt(s.date) * fx) / denomRealizedArs) * 100 : 0
    seriesArs.push({
      key: s.date,
      label: s.date.slice(5),
      total: +((cumArs - 1) * 100).toFixed(2),
      realized: +realPctArs.toFixed(2),
    })

    prevValueUsd = value
    prevNetDep = netDep
    prevValueArs = valueArs
    prevBaselineArs = baselineArs
  }

  return { seriesUsd, seriesArs }
}
