import { createContext, useContext, useEffect, useState, useMemo } from 'react'

// Fase A — Toggle global ARS/USD (2026-05-31).
// El user elige en qué moneda ver TODOS los números del Dashboard / Home /
// Cartera. La conversión usa el `tcBlue` actual (live) — para data histórica
// (snapshots viejos) eso significa que la línea del chart en ARS view se
// recalcula al TC actual, no al TC del momento de cada snapshot (limitación
// conocida del MVP; Fase C agregará TC histórico tracking).
//
// El user que mide en USD ve TC swings reflejados en sus posiciones ARS
// (CEDEARs valen menos USD cuando el blue sube). El user que mide en ARS
// ve TC swings reflejados en sus posiciones USD (BTC vale más ARS cuando
// el blue sube). Comportamiento simétrico — ambas vistas son válidas,
// la decisión es del user según cómo mide su capital.

const CurrencyContext = createContext(null)

const STORAGE_KEY = 'rendi_display_currency'

export function CurrencyProvider({ children }) {
  const [currency, setCurrencyRaw] = useState(() => {
    if (typeof window === 'undefined') return 'USD'
    try {
      const v = localStorage.getItem(STORAGE_KEY)
      return v === 'ARS' ? 'ARS' : 'USD'
    } catch {
      return 'USD'
    }
  })

  function setCurrency(next) {
    const norm = next === 'ARS' ? 'ARS' : 'USD'
    setCurrencyRaw(norm)
    try { localStorage.setItem(STORAGE_KEY, norm) } catch {}
  }

  function toggle() {
    setCurrency(currency === 'ARS' ? 'USD' : 'ARS')
  }

  const value = useMemo(
    () => ({ currency, setCurrency, toggle, isArs: currency === 'ARS', isUsd: currency === 'USD' }),
    [currency],
  )

  return <CurrencyContext.Provider value={value}>{children}</CurrencyContext.Provider>
}

export const useCurrency = () => {
  const ctx = useContext(CurrencyContext)
  if (!ctx) {
    // Fallback si se usa fuera del provider — devuelve USD default sin romper.
    return { currency: 'USD', setCurrency: () => {}, toggle: () => {}, isArs: false, isUsd: true }
  }
  return ctx
}

// ── Helpers de conversión ────────────────────────────────────────────────────
// Estos NO formatean (eso lo hace `fmtMoney` en utils/format.js) — solo
// convierten valores. Útil para callers que necesitan el valor convertido
// para operaciones matemáticas (suma, comparación, etc).

/** Convierte un valor USD a la moneda de display.
 * @param {number} usdValue — valor en USD
 * @param {string} currency — 'USD' | 'ARS'
 * @param {number} tcBlue — rate ARS/USD actual
 * @returns {number} valor en la moneda elegida
 */
export function fromUsd(usdValue, currency, tcBlue) {
  if (usdValue == null || isNaN(usdValue)) return usdValue
  if (currency === 'ARS' && tcBlue > 0) return usdValue * tcBlue
  return usdValue
}

/** Convierte un valor ARS a la moneda de display.
 * @param {number} arsValue — valor en ARS
 * @param {string} currency — 'USD' | 'ARS'
 * @param {number} tcBlue — rate ARS/USD actual
 * @returns {number} valor en la moneda elegida
 */
export function fromArs(arsValue, currency, tcBlue) {
  if (arsValue == null || isNaN(arsValue)) return arsValue
  if (currency === 'USD' && tcBlue > 0) return arsValue / tcBlue
  return arsValue
}
