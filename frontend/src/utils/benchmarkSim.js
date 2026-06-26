// benchmarkSim.js
// ────────────────
// Simuladores de portafolios paralelos para responder la pregunta:
// "¿qué hubiera pasado si la misma plata, con los mismos aportes y retiros
//  en las mismas fechas, hubiera ido a otro lado?"
//
// Diferencia clave vs el cálculo viejo (`(price_end/price_start − 1) * 100`):
// el viejo asume que vos pusiste TODO al principio. Si depositaste durante un
// drawdown del benchmark, el rendimiento real hubiera sido distinto.
//
// Granularidad: mensual. Los datos `bench.*` del backend son mensuales
// (último cierre del mes para S&P, blue/MEP de ese mes para FX, IPC
// mensual para inflación). Para MVP es suficiente.
//
// Convenciones:
//  • Todas las funciones devuelven `null` cuando faltan datos para simular.
//  • `series` está en USD (o ARS donde se aclare) para comparar contra el
//    portfolio del usuario, que está en USD.
//  • `monthKey` = 'YYYY-MM' (compatible con `bench.*`).

function sortGlobalMonthly(globalMonthly) {
  return [...(globalMonthly || [])].sort((a, b) =>
    a.year !== b.year ? a.year - b.year : a.month - b.month
  )
}

function monthKey(year, month) {
  return `${year}-${String(month).padStart(2, '0')}`
}

/**
 * lookupMonthly
 *
 * Busca el valor para una clave 'YYYY-MM' con fallback al último mes anterior
 * disponible (si no hay ese mes específico). Si tampoco hay anteriores, usa
 * el primero disponible.
 *
 * Esto es importante porque los datos de `bench.sp500` y `bench.dolar_blue`
 * pueden tener gaps (feriados, fines de semana, datos no actualizados).
 */
export function lookupMonthly(map, key) {
  if (!map) return null
  if (map[key] != null) return map[key]
  const sorted = Object.keys(map).sort()
  if (sorted.length === 0) return null
  let found = null
  for (const k of sorted) {
    if (k <= key) found = k
    else break
  }
  return found ? map[found] : map[sorted[0]]
}

// ─── Simulador genérico ─────────────────────────────────────────────────────
/**
 * simulateBenchmark
 *
 * Construye un portafolio paralelo que arranca con el `capital_inicio` del
 * primer mes y recibe los mismos flujos (deposits − withdrawals) cada mes,
 * ejecutados al precio del benchmark de ese mes.
 *
 * @param {Array}    globalMonthly  entradas del broker `global`
 * @param {Function} priceLookup    (monthKey) => price | null
 * @returns {{ finalValue, series, finalUnits } | null}
 *          series = [{ key, value }] en la misma moneda que priceLookup.
 */
export function simulateBenchmark(globalMonthly, priceLookup) {
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return null

  const firstKey = monthKey(sorted[0].year, sorted[0].month)
  const firstPrice = priceLookup(firstKey)
  if (firstPrice == null || firstPrice <= 0) return null

  // Capital inicial → unidades del benchmark al precio del primer mes.
  let units = (sorted[0].capital_inicio || 0) / firstPrice
  const series = []
  // priceSeries = precio CRUDO del índice por mes (sin flujos). Lo usa el chart de
  // benchmark para el retorno SIMPLE del índice (price[k]/price[first] − 1) =
  // "¿cuánto rindió el S&P?", time-weighted, igual que el broker. El `series`
  // flow-matched queda para back-compat / otros usos.
  const priceSeries = []

  for (const m of sorted) {
    const k = monthKey(m.year, m.month)
    const price = priceLookup(k) ?? firstPrice
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    // Cada flujo del mes se ejecuta al precio de ese mes.
    if (price > 0) units += net / price
    series.push({ key: k, value: units * price })
    priceSeries.push({ key: k, price })
  }

  return {
    finalValue: series[series.length - 1].value,
    series,
    finalUnits: units,
    priceSeries,
    firstPrice,
  }
}

// ─── S&P 500 (USD) ──────────────────────────────────────────────────────────
/**
 * Simula tus aportes en S&P 500.
 * Output en USD.
 */
export function simulateSp500(globalMonthly, sp500Map) {
  if (!sp500Map || Object.keys(sp500Map).length === 0) return null
  return simulateBenchmark(globalMonthly, k => lookupMonthly(sp500Map, k))
}

// ─── Dólar cash (USD held flat) ─────────────────────────────────────────────
/**
 * "Si hubieras dejado tus dólares quietos."
 * El precio es siempre 1 USD = 1 USD. Sin rendimiento ni fricción.
 * Útil para visualizar cuánto "perdiste" o "ganaste" en USD vs no hacer nada.
 *
 * Output en USD = capital aportado total.
 */
export function simulateDolarCash(globalMonthly) {
  return simulateBenchmark(globalMonthly, () => 1)
}

// ─── Pesos AR (cash en ARS al blue de cada mes) ─────────────────────────────
/**
 * "Si hubieras convertido cada depósito a pesos al blue del día y los
 *  hubieras dejado quietos en pesos."
 *
 * Cada flujo USD se convierte a ARS al blue de ese mes y se acumula en pesos.
 * El valor final en USD se obtiene dividiendo los pesos totales por el blue
 * del último mes — captura cuánto poder de compra "en USD" perdiste o
 * ganaste por sostener pesos.
 *
 * @returns {{ finalValue, series, finalPesos } | null}
 *          series = [{ key, value }] en USD-equivalente (pesos / blue del mes)
 */
export function simulateArsCash(globalMonthly, blueMap) {
  if (!blueMap || Object.keys(blueMap).length === 0) return null
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return null

  const firstKey = monthKey(sorted[0].year, sorted[0].month)
  const firstBlue = lookupMonthly(blueMap, firstKey)
  if (firstBlue == null || firstBlue <= 0) return null

  // Convertir capital inicial USD a pesos al blue del primer mes.
  let pesos = (sorted[0].capital_inicio || 0) * firstBlue
  const series = []
  // priceSeries = "precio" USD-equiv de 1 peso sostenido = 1/blue. Permite al
  // chart medir el benchmark como índice simple (en pesos da 0%; en USD da la
  // pérdida por devaluación). Ver buildShadowFromSim/Ars en Insights.
  const priceSeries = []
  const firstPrice = 1 / firstBlue

  for (const m of sorted) {
    const k = monthKey(m.year, m.month)
    const blue = lookupMonthly(blueMap, k) ?? firstBlue
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    pesos += net * blue
    series.push({ key: k, value: blue > 0 ? pesos / blue : 0 })
    priceSeries.push({ key: k, price: blue > 0 ? 1 / blue : firstPrice })
  }

  return {
    finalValue: series[series.length - 1].value,
    series,
    finalPesos: pesos,
    priceSeries,
    firstPrice,
  }
}

// ─── Inflación AR (acumulada del período) ──────────────────────────────────
/**
 * Calcula la inflación INDEC acumulada entre el primer mes registrado y el
 * último, multiplicando los IPCs mensuales: Π(1 + ipc_m).
 *
 * No es un portafolio simulado — es un número de contexto para que el usuario
 * sepa contra qué tenía que rendir para mantener poder de compra.
 *
 * @returns {{ cumPct, monthlyValues, fromKey, toKey } | null}
 */
export function computeInflationCumulative(globalMonthly, inflationMap) {
  if (!inflationMap) return null
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return null

  const fromKey = monthKey(sorted[0].year, sorted[0].month)
  const toKey = monthKey(sorted[sorted.length - 1].year, sorted[sorted.length - 1].month)

  // Tomamos los IPCs entre fromKey y toKey inclusive.
  // bench.inflation_ar trae el IPC del MES (cambio de un mes al siguiente).
  // El IPC del mes de "fromKey" se cuenta desde fromKey+1 en adelante.
  // Para MVP, multiplicamos todos los meses entre los dos, que aproxima bien.
  let cum = 1
  let count = 0
  for (const k of Object.keys(inflationMap).sort()) {
    if (k <= fromKey) continue
    if (k > toKey) break
    const ipc = inflationMap[k]
    if (ipc != null) {
      cum *= 1 + ipc / 100
      count += 1
    }
  }
  if (count === 0) return null

  return {
    cumPct: (cum - 1) * 100,
    monthsCounted: count,
    fromKey,
    toKey,
  }
}

// ─── T-Bill USD (SHV ETF) ───────────────────────────────────────────────────
/**
 * Simula tus aportes en T-Bills USD (proxy: ETF SHV — iShares 0-3 Month Treasury).
 * Mismo flow que simulateSp500. Output en USD.
 */
export function simulateShv(globalMonthly, shvMap) {
  if (!shvMap || Object.keys(shvMap).length === 0) return null
  return simulateBenchmark(globalMonthly, k => lookupMonthly(shvMap, k))
}

// ─── Oro (GLD ETF) ──────────────────────────────────────────────────────────
/**
 * Simula tus aportes en oro (proxy: ETF GLD — SPDR Gold Trust).
 * Mismo flow que simulateSp500. Output en USD.
 */
export function simulateGold(globalMonthly, gldMap) {
  if (!gldMap || Object.keys(gldMap).length === 0) return null
  return simulateBenchmark(globalMonthly, k => lookupMonthly(gldMap, k))
}

// ─── Merval (índice AR en ARS) ──────────────────────────────────────────────
/**
 * Simula tus aportes en el Merval (índice acciones argentinas, en ARS).
 *
 * IMPORTANTE: el Merval cotiza en pesos. Para hacer apples-to-apples con un
 * user que tiene flujos en USD, convertimos cada flow USD → ARS al blue del
 * mes, compramos puntos del Merval ese mes, y al final dividimos por el blue
 * actual para volver a USD-equivalente.
 *
 * @returns {{ finalValue, series, finalUnits } | null}  series en USD-equiv
 */
export function simulateMerval(globalMonthly, mervalArsMap, blueMap) {
  if (!mervalArsMap || Object.keys(mervalArsMap).length === 0) return null
  if (!blueMap || Object.keys(blueMap).length === 0) return null
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return null

  const firstKey = monthKey(sorted[0].year, sorted[0].month)
  const firstMerv = lookupMonthly(mervalArsMap, firstKey)
  const firstBlue = lookupMonthly(blueMap, firstKey)
  if (!firstMerv || !firstBlue || firstMerv <= 0 || firstBlue <= 0) return null

  // Capital USD inicial → ARS al blue del primer mes → puntos del Merval
  let units = ((sorted[0].capital_inicio || 0) * firstBlue) / firstMerv
  const series = []
  // priceSeries = "precio" USD-equiv de 1 punto del Merval = merv/blue. En pesos
  // (×blue) reproduce el retorno del Merval; en USD lo ajusta por FX.
  const priceSeries = []
  const firstPrice = firstMerv / firstBlue

  for (const m of sorted) {
    const k = monthKey(m.year, m.month)
    const merv = lookupMonthly(mervalArsMap, k) ?? firstMerv
    const blue = lookupMonthly(blueMap, k) ?? firstBlue
    const netUsd = (m.deposits || 0) - (m.withdrawals || 0)
    if (merv > 0 && blue > 0) {
      // Flow USD → ARS al blue del mes → compramos puntos del Merval
      units += (netUsd * blue) / merv
    }
    // Valor en USD-equiv = (puntos * merv_ars) / blue_actual
    const valueArs = units * merv
    const valueUsd = blue > 0 ? valueArs / blue : 0
    series.push({ key: k, value: valueUsd })
    priceSeries.push({ key: k, price: blue > 0 ? merv / blue : firstPrice })
  }

  return {
    finalValue: series[series.length - 1].value,
    series,
    finalUnits: units,
    priceSeries,
    firstPrice,
  }
}

// ─── Plazo fijo UVA (CER-ajustado) ──────────────────────────────────────────
/**
 * Simula tus aportes en Plazo Fijo UVA — el PF retail más popular en AR.
 *
 * El PF UVA ajusta el saldo en pesos por el coeficiente UVA (= IPC INDEC),
 * más un spread chico (~0.5-1% TNA, despreciable). Asumimos spread = 0.
 *
 * Factor de capitalización mensual = UVA_t / UVA_{t-1} (= 1 + inflación_t).
 *
 * El "Plazo Fijo Tradicional" (TNA Minorista) NO se simula porque ninguna
 * API pública tiene serie histórica confiable. UVA es el reemplazo más
 * representativo y con data verificable.
 *
 * @param {Array}  globalMonthly  global monthly entries
 * @param {Object} uvaMap         { 'YYYY-MM': uva_value } UVA al cierre del mes
 * @param {Object} blueMap        { 'YYYY-MM': blue_venta } para conversión USD↔ARS
 * @returns {{ finalValue, series, finalArs } | null}
 *          series con value en USD-equiv (apples-to-apples con otros benchmarks)
 */
export function simulatePlazoFijoUva(globalMonthly, uvaMap, blueMap) {
  if (!uvaMap || Object.keys(uvaMap).length === 0) return null
  if (!blueMap || Object.keys(blueMap).length === 0) return null
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return null

  const firstKey = monthKey(sorted[0].year, sorted[0].month)
  const firstBlue = lookupMonthly(blueMap, firstKey)
  const firstUva = lookupMonthly(uvaMap, firstKey)
  if (!firstBlue || firstBlue <= 0) return null
  if (!firstUva || firstUva <= 0) return null

  // Capital USD inicial → ARS al blue del primer mes. Mantenemos saldo en
  // ARS para capitalizar con UVA; convertimos a USD-eq al blue del mes en
  // cada punto.
  let valueArs = (sorted[0].capital_inicio || 0) * firstBlue
  let prevUva = firstUva  // primer mes: ratio = 1 → no capitaliza (alineado con S&P)
  const series = []
  // priceSeries = "precio" USD-equiv del índice UVA = uva/blue. En pesos (×blue)
  // reproduce el ajuste UVA (≈ inflación); en USD lo ajusta por FX.
  const priceSeries = []
  const firstPrice = firstUva / firstBlue

  for (const m of sorted) {
    const k = monthKey(m.year, m.month)
    const uva = lookupMonthly(uvaMap, k) ?? prevUva
    const blue = lookupMonthly(blueMap, k) ?? firstBlue

    // Capitalizar con ratio UVA. En el primer mes prevUva === firstUva === uva
    // → ratio = 1 → no genera retorno (alineado con simulateBenchmark donde
    // el primer mes tiene price = firstPrice).
    if (uva > 0 && prevUva > 0) {
      valueArs *= uva / prevUva
    }

    // Agregar flow al blue del mes (apples-to-apples)
    const netUsd = (m.deposits || 0) - (m.withdrawals || 0)
    valueArs += netUsd * blue

    // Update prevUva para próxima iteración
    if (uva > 0) prevUva = uva

    // Value USD-equiv = ARS / blue del mes
    const valueUsd = blue > 0 ? valueArs / blue : 0
    series.push({ key: k, value: valueUsd })
    priceSeries.push({ key: k, price: (blue > 0 && uva > 0) ? uva / blue : firstPrice })
  }

  return {
    finalValue: series[series.length - 1].value,
    series,
    finalArs: valueArs,
    priceSeries,
    firstPrice,
  }
}
