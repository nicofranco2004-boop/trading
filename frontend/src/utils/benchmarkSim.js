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

  for (const m of sorted) {
    const k = monthKey(m.year, m.month)
    const price = priceLookup(k) ?? firstPrice
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    // Cada flujo del mes se ejecuta al precio de ese mes.
    if (price > 0) units += net / price
    series.push({ key: k, value: units * price })
  }

  return {
    finalValue: series[series.length - 1].value,
    series,
    finalUnits: units,
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

  for (const m of sorted) {
    const k = monthKey(m.year, m.month)
    const blue = lookupMonthly(blueMap, k) ?? firstBlue
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    pesos += net * blue
    series.push({ key: k, value: blue > 0 ? pesos / blue : 0 })
  }

  return {
    finalValue: series[series.length - 1].value,
    series,
    finalPesos: pesos,
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
