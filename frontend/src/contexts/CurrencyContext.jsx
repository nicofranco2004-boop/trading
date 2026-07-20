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
const VAL_STORAGE_KEY = 'rendi_valuation_dollar'   // 'mep' | 'ccl'
const CB_STORAGE_KEY = 'rendi_cost_basis'          // 'today' | 'purchase'
const DEFAULT_TC_BLUE = 1415

/**
 * pickFinancialRate — dólar "financiero" para valuar holdings y convertir ARS↔USD,
 * según la preferencia del user (Configuración): MEP (default) o CCL.
 *
 * Por qué CCL como opción: es el dólar IMPLÍCITO en el precio de un CEDEAR
 * (precio.BA = precioUS × CCL ÷ ratio). Dividir el valor en pesos por el CCL
 * recupera el valor real en USD; dividir por el MEP deja un residuo (CCL/MEP) que
 * hace "temblar" la cartera cuando se mueve la brecha, sin que la empresa cambie.
 * El MEP es defendible como "dólar local que podés sacar acá" → es el default.
 *
 * Cascada: el elegido primero, el otro como fallback, después el blue. NO afecta a
 * la cripto de exchange (esa usa el dólar cripto / crypto_broker_factor, aparte).
 *
 * @param {object} dolar — respuesta de /api/dolar ({blue,mep,ccl,cripto}.venta)
 * @param {'mep'|'ccl'} pref — preferencia del user
 * @returns {number|undefined} rate ARS/USD, o undefined si no hay dato (caller pone fallback)
 */
export function pickFinancialRate(dolar, pref) {
  const mep = dolar?.mep?.venta, ccl = dolar?.ccl?.venta, blue = dolar?.blue?.venta
  return (pref === 'ccl' ? (ccl || mep) : (mep || ccl)) || blue
}

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

  // Dólar de valuación elegido por el user (MEP default / CCL). Persistido en
  // localStorage como el toggle de moneda — preferencia de display per-device.
  const [valuationDollar, setValuationDollarRaw] = useState(() => {
    if (typeof window === 'undefined') return 'mep'
    try {
      return localStorage.getItem(VAL_STORAGE_KEY) === 'ccl' ? 'ccl' : 'mep'
    } catch {
      return 'mep'
    }
  })

  // "Costo en dólares" — con qué dólar contamos lo INVERTIDO en un lote en pesos:
  //   • 'today'    (default) → el dólar de hoy, igual que el valor (FX-neutral): el
  //     P&L USD refleja solo cómo rindió el activo.
  //   • 'purchase' → el tc_compra del lote (los dólares que realmente pusiste): el
  //     P&L incluye la devaluación del peso desde que compraste.
  // SOLO afecta el COSTO (columna Invertido USD) de lotes en pesos; el valor de
  // mercado siempre va al dólar de hoy. Preferencia de display per-device, igual
  // que el dólar de valuación — NO viaja al backend ni a la IA (que razonan a hoy).
  const [costBasis, setCostBasisRaw] = useState(() => {
    if (typeof window === 'undefined') return 'today'
    try {
      return localStorage.getItem(CB_STORAGE_KEY) === 'purchase' ? 'purchase' : 'today'
    } catch {
      return 'today'
    }
  })

  // tcBlue compartido entre páginas — la primera que fetcha /dolar lo
  // publica acá vía `setTcBlue`. Los components que solo necesitan
  // convertir para display (Reports cards, charts) lo leen sin re-fetchear.
  // Default 1415 evita división-por-cero y NaN durante el primer render.
  const [tcBlue, setTcBlueRaw] = useState(DEFAULT_TC_BLUE)

  // Cotizaciones crudas del último /dolar ({mep,ccl,blue,cripto}.venta), para que
  // el selector de moneda (CurrencyRail) muestre la tasa de cada dólar debajo de
  // cada opción sin tener que re-fetchear. Se publican en el mismo effect que tcBlue.
  const [dolar, setDolar] = useState(null)

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
        setDolar(d)   // exponer tasas crudas para el selector (mep/ccl .venta)
        // dólar financiero según preferencia (MEP default / CCL), cascada con
        // fallback al otro y al blue. Re-resuelve al cambiar valuationDollar.
        const rate = pickFinancialRate(d, valuationDollar)
        if (rate > 0) setTcBlueRaw(Number(rate))
      }).catch(() => { /* silent — usa default + páginas publican lo que tengan */ })
    }
    fetchAndPublish()
    const id = setInterval(fetchAndPublish, 300_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [valuationDollar])

  function setCurrency(next) {
    const norm = next === 'ARS' ? 'ARS' : 'USD'
    setCurrencyRaw(norm)
    try { localStorage.setItem(STORAGE_KEY, norm) } catch {}
  }

  function setValuationDollar(next) {
    const norm = next === 'ccl' ? 'ccl' : 'mep'
    setValuationDollarRaw(norm)
    try { localStorage.setItem(VAL_STORAGE_KEY, norm) } catch {}
  }

  function setCostBasis(next) {
    const norm = next === 'purchase' ? 'purchase' : 'today'
    setCostBasisRaw(norm)
    try { localStorage.setItem(CB_STORAGE_KEY, norm) } catch {}
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
      valuationDollar, setValuationDollar,
      costBasis, setCostBasis,
      dolar,
    }),
    [currency, tcBlue, valuationDollar, costBasis, dolar],
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
      valuationDollar: 'mep', setValuationDollar: () => {},
      costBasis: 'today', setCostBasis: () => {},
      dolar: null,
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
