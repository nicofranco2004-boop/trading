import { createContext, useContext, useEffect, useState, useMemo } from 'react'
import { api } from '../utils/api'

// Fase A — Toggle global ARS/USD (2026-05-31).
// El user elige en qué moneda ver TODOS los números del Dashboard / Home /
// Cartera. UNIFICACIÓN FX (2026-06): la conversión USD↔ARS usa el dólar MEP
// (el mismo de la valuación de holdings), NO el blue. Por compatibilidad la
// variable se sigue llamando `tcBlue` pero TIENE EL VALOR DEL MEP (cascada
// mep→ccl→blue). La conversión usa el rate actual (live) — para data histórica
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
const DEFAULT_TC_BLUE = 1415

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

  // tcBlue compartido entre páginas — la primera que fetcha /dolar lo
  // publica acá vía `setTcBlue`. Los components que solo necesitan
  // convertir para display (Reports cards, charts) lo leen sin re-fetchear.
  // Default 1415 evita división-por-cero y NaN durante el primer render.
  const [tcBlue, setTcBlueRaw] = useState(DEFAULT_TC_BLUE)

  // Audit fix H2 (2026-05-31): el Provider fetcha /dolar al mount para que
  // el tcBlue real esté disponible desde el primer render — antes había una
  // ventana de ~500ms donde Reports cards / Operations renderizaban ARS con
  // el default 1415 hasta que Dashboard publicara su valor.
  // Refresh cada 5min para mantenerlo sincronizado con el resto de la app
  // (las páginas individuales todavía fetchean /dolar para sus live prices,
  // pero al menos el FX de display ya está listo desde la primera pintada).
  useEffect(() => {
    let cancelled = false
    const fetchAndPublish = () => {
      api.get('/dolar').then(d => {
        if (cancelled) return
        // dólar MEP (cascada mep→ccl→blue) — rate de display unificado.
        const mep = d?.mep?.venta || d?.ccl?.venta || d?.blue?.venta
        if (mep > 0) setTcBlueRaw(Number(mep))
      }).catch(() => { /* silent — usa default + páginas publican lo que tengan */ })
    }
    fetchAndPublish()
    const id = setInterval(fetchAndPublish, 300_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  function setCurrency(next) {
    const norm = next === 'ARS' ? 'ARS' : 'USD'
    setCurrencyRaw(norm)
    try { localStorage.setItem(STORAGE_KEY, norm) } catch {}
  }

  function toggle() {
    setCurrency(currency === 'ARS' ? 'USD' : 'ARS')
  }

  function setTcBlue(next) {
    const n = Number(next)
    if (!Number.isFinite(n) || n <= 0) return
    setTcBlueRaw(n)
  }

  const value = useMemo(
    () => ({
      currency, setCurrency, toggle,
      isArs: currency === 'ARS', isUsd: currency === 'USD',
      tcBlue, setTcBlue,
    }),
    [currency, tcBlue],
  )

  return <CurrencyContext.Provider value={value}>{children}</CurrencyContext.Provider>
}

export const useCurrency = () => {
  const ctx = useContext(CurrencyContext)
  if (!ctx) {
    // Fallback si se usa fuera del provider — devuelve USD default sin romper.
    return {
      currency: 'USD', setCurrency: () => {}, toggle: () => {},
      isArs: false, isUsd: true,
      tcBlue: DEFAULT_TC_BLUE, setTcBlue: () => {},
    }
  }
  return ctx
}

// ── Helpers de formato puros (testeables sin React) ──────────────────────────
//
// fmtMoneyRaw(usdValue, currency, tcBlue, opts) → string
// fmtMoneyCompactRaw(usdValue, currency, tcBlue, opts) → string
//
// Input siempre es USD canónico. Convierten a ARS si currency==='ARS' y
// tcBlue>0; sino dejan en USD. Símbolos: '$' para ARS, 'US$' para USD.
// Devuelven '—' para null / NaN.

export function fmtMoneyRaw(usdValue, currency, tcBlue, opts = {}) {
  if (usdValue == null || !Number.isFinite(usdValue)) return '—'
  const { signed = false, decimals = 0 } = opts
  const isArs = currency === 'ARS' && tcBlue > 0
  const v = isArs ? usdValue * tcBlue : usdValue
  const abs = Math.abs(v)
  const sign = signed ? (v < 0 ? '−' : '+') : (v < 0 ? '−' : '')
  const sym = isArs ? '$' : 'US$'
  return `${sign}${sym}${abs.toLocaleString('es-AR', { maximumFractionDigits: decimals })}`
}

// fmtConvertedRaw: formatea un valor que YA está en la currency target.
// Útil cuando hicimos la conversión nosotros mismos (ej. FX histórico) y
// solo queremos el formato final (símbolo + locale).
export function fmtConvertedRaw(value, targetCurrency, opts = {}) {
  if (value == null || !Number.isFinite(value)) return '—'
  const { signed = false, decimals = 0 } = opts
  const isArs = targetCurrency === 'ARS'
  const abs = Math.abs(value)
  const sign = signed ? (value < 0 ? '−' : '+') : (value < 0 ? '−' : '')
  const sym = isArs ? '$' : 'US$'
  return `${sign}${sym}${abs.toLocaleString('es-AR', { maximumFractionDigits: decimals })}`
}

export function fmtConvertedCompactRaw(value, targetCurrency, opts = {}) {
  if (value == null || !Number.isFinite(value)) return '—'
  const { signed = false } = opts
  const abs = Math.abs(value)
  const sign = signed ? (value < 0 ? '−' : '+') : (value < 0 ? '−' : '')
  const sym = targetCurrency === 'ARS' ? '$' : 'US$'
  let body
  if (abs >= 1e9) {
    const b = abs / 1e9
    body = (b < 9.95 ? b.toFixed(1) : String(Math.round(b))) + 'B'
  } else if (abs >= 1e6) {
    const m = abs / 1e6
    body = (m < 9.95 ? m.toFixed(1) : String(Math.round(m))) + 'M'
  } else if (abs >= 1e3) {
    const k = abs / 1e3
    body = (k < 9.95 ? k.toFixed(1) : String(Math.round(k))) + 'k'
  } else {
    body = Math.round(abs).toLocaleString('es-AR')
  }
  return `${sign}${sym}${body}`
}

export function fmtMoneyCompactRaw(usdValue, currency, tcBlue, opts = {}) {
  if (usdValue == null || !Number.isFinite(usdValue)) return '—'
  const { signed = false } = opts
  const isArs = currency === 'ARS' && tcBlue > 0
  const v = isArs ? usdValue * tcBlue : usdValue
  const abs = Math.abs(v)
  const sign = signed ? (v < 0 ? '−' : '+') : (v < 0 ? '−' : '')
  const sym = isArs ? '$' : 'US$'
  // Smooth boundaries: cuando la representación con 1 decimal redondearía
  // a "10.X" (>= 9.95), saltamos al siguiente bucket SIN decimal para
  // evitar "10.0k → 10k" flicker en el borde 9999/10000.
  let body
  if (abs >= 1e9) {
    const b = abs / 1e9
    body = (b < 9.95 ? b.toFixed(1) : String(Math.round(b))) + 'B'
  } else if (abs >= 1e6) {
    const m = abs / 1e6
    body = (m < 9.95 ? m.toFixed(1) : String(Math.round(m))) + 'M'
  } else if (abs >= 1e3) {
    const k = abs / 1e3
    body = (k < 9.95 ? k.toFixed(1) : String(Math.round(k))) + 'k'
  } else {
    body = Math.round(abs).toLocaleString('es-AR')
  }
  return `${sign}${sym}${body}`
}

// ── Hook reusable: formatter atado al toggle global ─────────────────────────
// Devuelve helpers que ya saben sobre `currency` + `tcBlue` actuales:
//   - fmtMoney(usdValue, { signed, decimals })
//   - fmtMoneyCompact(usdValue, { signed }) → k / M / B abbreviation
// El input siempre es USD canónico (lo que devuelve el backend).
// La conversión a ARS usa tcBlue ACTUAL (Phase B) — para histórico usar
// `useHistoricalMoneyFormat()` que combina FX stamped + lookup por fecha.
export function useMoneyFormat() {
  const { currency, tcBlue } = useCurrency()
  const isArs = currency === 'ARS'

  function convert(usdValue) {
    if (usdValue == null || !Number.isFinite(usdValue)) return null
    return isArs ? usdValue * tcBlue : usdValue
  }

  function fmtMoney(usdValue, opts) {
    return fmtMoneyRaw(usdValue, currency, tcBlue, opts)
  }

  function fmtMoneyCompact(usdValue, opts) {
    return fmtMoneyCompactRaw(usdValue, currency, tcBlue, opts)
  }

  return {
    currency, tcBlue, isArs,
    convert, fmtMoney, fmtMoneyCompact,
  }
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
