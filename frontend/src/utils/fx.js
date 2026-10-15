/**
 * lookupHistoricalDolar
 * ─────────────────────
 * El dólar ELEGIDO al cierre de (year, month) — ver utils/tcHistorico.js.
 *
 * Source: `dolarMes` de `useDolarMensual` (`dolarMensualDe` sobre /api/fx-rates),
 * a `{YYYY-MM: rate}` map con la última cotización de cada mes (MEP; blue antes
 * de 2018). Hasta el 2026-10-15 recibía `bench` y leía `bench.dolar_blue`: lo
 * viejo iba al BLUE mientras lo de hoy (`liveTc`) iba al MEP.
 *
 * Lookup strategy
 * ───────────────
 * 1. Current calendar month → use `liveTc` (el dólar de hoy). Historical map
 *    only has the last observation of finished months; for "this month"
 *    today's live rate is more accurate.
 * 2. Exact match `YYYY-MM` in the map.
 * 3. Most recent month ≤ the target (no future-FX leakage).
 * 4. Earliest known month if no prior data exists.
 * 5. Final fallback to `liveTc` (the bench fetch may have failed entirely).
 *
 * @param {Object|null} dolarMes  `{YYYY-MM: rate}`, or null/undefined if unavailable
 * @param {number}      year   target year
 * @param {number}      month  1-12
 * @param {number}      liveTc current live tcValuacion (used for current month + final fallback)
 * @param {Date}        now    optional override for "today" — useful in tests
 * @returns {number}
 */
export function lookupHistoricalDolar(dolarMes, year, month, liveTc, now = new Date()) {
  const todayY = now.getFullYear()
  const todayM = now.getMonth() + 1
  if (year === todayY && month === todayM) return liveTc

  const map = dolarMes
  if (!map || typeof map !== 'object') return liveTc

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
