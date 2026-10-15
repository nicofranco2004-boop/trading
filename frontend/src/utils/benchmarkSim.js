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
// (último cierre del mes para S&P, el dólar elegido de ese mes para FX, IPC
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
  // ⚠️ ANTES DEL PRIMER DATO NO HAY PRECIO. Acá se devolvía `map[sorted[0]]`: el
  // primer precio disponible para cualquier mes anterior. Con la serie de 5 años
  // del backend, un aporte de 2015 "compraba" S&P al precio de septiembre de
  // 2021 y la card "Comparativa" le regalaba seis años de índice al usuario —
  // 56 de 673 usuarios de producción tienen `monthly_entries` anteriores al
  // arranque de esa serie. Sin dato, null: `simulateBenchmark` devuelve null y
  // la card dice "Datos insuficientes", que es la verdad. (El backend pasó a
  // bajar la historia completa, así que el caso quedó raro; pero raro no es
  // imposible, y un precio inventado sigue siendo un precio inventado.)
  return found ? map[found] : null
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

// ─── Pesos AR (cash en ARS al dólar de cada mes) ─────────────────────────────
/**
 * "Si hubieras convertido cada depósito a pesos al dólar del día y los
 *  hubieras dejado quietos en pesos."
 *
 * Cada flujo USD se convierte a ARS al dólar de ese mes y se acumula en pesos.
 * El valor final en USD se obtiene dividiendo los pesos totales por el tc
 * del último mes — captura cuánto poder de compra "en USD" perdiste o
 * ganaste por sostener pesos.
 *
 * @returns {{ finalValue, series, finalPesos } | null}
 *          series = [{ key, value }] en USD-equivalente (pesos / tc del mes)
 */
export function simulateArsCash(globalMonthly, tcMap) {
  if (!tcMap || Object.keys(tcMap).length === 0) return null
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return null

  const firstKey = monthKey(sorted[0].year, sorted[0].month)
  const firstTc = lookupMonthly(tcMap, firstKey)
  if (firstTc == null || firstTc <= 0) return null

  // Convertir capital inicial USD a pesos al dólar del primer mes.
  let pesos = (sorted[0].capital_inicio || 0) * firstTc
  const series = []
  // priceSeries = "precio" USD-equiv de 1 peso sostenido = 1/dólar. Permite al
  // chart medir el benchmark como índice simple (en pesos da 0%; en USD da la
  // pérdida por devaluación). Ver buildShadowFromSim/Ars en Insights.
  const priceSeries = []
  const firstPrice = 1 / firstTc

  for (const m of sorted) {
    const k = monthKey(m.year, m.month)
    const tc = lookupMonthly(tcMap, k) ?? firstTc
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    pesos += net * tc
    series.push({ key: k, value: tc > 0 ? pesos / tc : 0 })
    priceSeries.push({ key: k, price: tc > 0 ? 1 / tc : firstPrice })
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
 * user que tiene flujos en USD, convertimos cada flow USD → ARS al dólar del
 * mes, compramos puntos del Merval ese mes, y al final dividimos por el tc
 * actual para volver a USD-equivalente.
 *
 * @returns {{ finalValue, series, finalUnits } | null}  series en USD-equiv
 */
export function simulateMerval(globalMonthly, mervalArsMap, tcMap) {
  if (!mervalArsMap || Object.keys(mervalArsMap).length === 0) return null
  if (!tcMap || Object.keys(tcMap).length === 0) return null
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return null

  const firstKey = monthKey(sorted[0].year, sorted[0].month)
  const firstMerv = lookupMonthly(mervalArsMap, firstKey)
  const firstTc = lookupMonthly(tcMap, firstKey)
  if (!firstMerv || !firstTc || firstMerv <= 0 || firstTc <= 0) return null

  // Capital USD inicial → ARS al dólar del primer mes → puntos del Merval
  let units = ((sorted[0].capital_inicio || 0) * firstTc) / firstMerv
  const series = []
  // priceSeries = "precio" USD-equiv de 1 punto del Merval = merv/dólar. En pesos
  // (×tc) reproduce el retorno del Merval; en USD lo ajusta por FX.
  const priceSeries = []
  const firstPrice = firstMerv / firstTc

  for (const m of sorted) {
    const k = monthKey(m.year, m.month)
    const merv = lookupMonthly(mervalArsMap, k) ?? firstMerv
    const tc = lookupMonthly(tcMap, k) ?? firstTc
    const netUsd = (m.deposits || 0) - (m.withdrawals || 0)
    if (merv > 0 && tc > 0) {
      // Flow USD → ARS al dólar del mes → compramos puntos del Merval
      units += (netUsd * tc) / merv
    }
    // Valor en USD-equiv = (puntos * merv_ars) / tc_actual
    const valueArs = units * merv
    const valueUsd = tc > 0 ? valueArs / tc : 0
    series.push({ key: k, value: valueUsd })
    priceSeries.push({ key: k, price: tc > 0 ? merv / tc : firstPrice })
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
 * @param {Object} tcMap        { 'YYYY-MM': tc } para conversión USD↔ARS
 * @returns {{ finalValue, series, finalArs } | null}
 *          series con value en USD-equiv (apples-to-apples con otros benchmarks)
 */
export function simulatePlazoFijoUva(globalMonthly, uvaMap, tcMap) {
  if (!uvaMap || Object.keys(uvaMap).length === 0) return null
  if (!tcMap || Object.keys(tcMap).length === 0) return null
  const sorted = sortGlobalMonthly(globalMonthly)
  if (sorted.length === 0) return null

  const firstKey = monthKey(sorted[0].year, sorted[0].month)
  const firstTc = lookupMonthly(tcMap, firstKey)
  const firstUva = lookupMonthly(uvaMap, firstKey)
  if (!firstTc || firstTc <= 0) return null
  if (!firstUva || firstUva <= 0) return null

  // Capital USD inicial → ARS al dólar del primer mes. Mantenemos saldo en
  // ARS para capitalizar con UVA; convertimos a USD-eq al dólar del mes en
  // cada punto.
  let valueArs = (sorted[0].capital_inicio || 0) * firstTc
  let prevUva = firstUva  // primer mes: ratio = 1 → no capitaliza (alineado con S&P)
  const series = []
  // priceSeries = "precio" USD-equiv del índice UVA = uva/dólar. En pesos (×tc)
  // reproduce el ajuste UVA (≈ inflación); en USD lo ajusta por FX.
  const priceSeries = []
  const firstPrice = firstUva / firstTc

  for (const m of sorted) {
    const k = monthKey(m.year, m.month)
    const uva = lookupMonthly(uvaMap, k) ?? prevUva
    const tc = lookupMonthly(tcMap, k) ?? firstTc

    // Capitalizar con ratio UVA. En el primer mes prevUva === firstUva === uva
    // → ratio = 1 → no genera retorno (alineado con simulateBenchmark donde
    // el primer mes tiene price = firstPrice).
    if (uva > 0 && prevUva > 0) {
      valueArs *= uva / prevUva
    }

    // Agregar flow al dólar del mes (apples-to-apples)
    const netUsd = (m.deposits || 0) - (m.withdrawals || 0)
    valueArs += netUsd * tc

    // Update prevUva para próxima iteración
    if (uva > 0) prevUva = uva

    // Value USD-equiv = ARS / tc del mes
    const valueUsd = tc > 0 ? valueArs / tc : 0
    series.push({ key: k, value: valueUsd })
    priceSeries.push({ key: k, price: (tc > 0 && uva > 0) ? uva / tc : firstPrice })
  }

  return {
    finalValue: series[series.length - 1].value,
    series,
    finalArs: valueArs,
    priceSeries,
    firstPrice,
  }
}
