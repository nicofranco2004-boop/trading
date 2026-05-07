/**
 * lookupHistoricalDolar
 * ─────────────────────
 * Find the dolar-blue venta rate for a given (year, month).
 *
 * Source: backend /api/benchmarks → bench.dolar_blue, a `{YYYY-MM: rate}` map
 * keyed by the LAST observation of each month from argentinadatos.com.
 *
 * Lookup strategy
 * ───────────────
 * 1. Current calendar month → use `liveTc` (live blue rate). Historical map
 *    only has the last observation of finished months; for "this month"
 *    today's live rate is more accurate.
 * 2. Exact match `YYYY-MM` in the map.
 * 3. Most recent month ≤ the target (no future-FX leakage).
 * 4. Earliest known month if no prior data exists.
 * 5. Final fallback to `liveTc` (the bench fetch may have failed entirely).
 *
 * @param {Object|null} bench  bench.dolar_blue map, or null/undefined if unavailable
 * @param {number}      year   target year
 * @param {number}      month  1-12
 * @param {number}      liveTc current live tcBlue (used for current month + final fallback)
 * @param {Date}        now    optional override for "today" — useful in tests
 * @returns {number}
 */
export function lookupHistoricalDolar(bench, year, month, liveTc, now = new Date()) {
  const todayY = now.getFullYear()
  const todayM = now.getMonth() + 1
  if (year === todayY && month === todayM) return liveTc

  const map = bench && bench.dolar_blue
  if (!map) return liveTc

  const key = `${year}-${String(month).padStart(2, '0')}`
  if (map[key] != null) return map[key]

  const keys = Object.keys(map).sort()
  if (keys.length === 0) return liveTc

  // Most recent month ≤ key (binary-walk via sort).
  let found = null
  for (const k of keys) {
    if (k <= key) found = k
    else break
  }
  if (!found) found = keys[0] // before earliest data → use earliest known
  return map[found] != null ? map[found] : liveTc
}
