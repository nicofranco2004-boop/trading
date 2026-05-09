// ═══════════════════════════════════════════════════════════════════════════
// Number formatting utilities
// ═══════════════════════════════════════════════════════════════════════════
// Audit visual mayo 2026: el formato "+USD 1,037.74" tiene el signo separado
// del número por el currency code, awkward de leer. Nueva convención:
// "+$1,037.74 USD" — signo pegado al dígito, currency code después.
//
// API:
// • fmtUsd(n)               → "USD 1,037.74"      (legacy, sin signo)
// • fmtArs(n)               → "ARS 1.037"          (legacy, sin signo)
// • fmtMoney(n, ccy, opts)  → "+$1,037.74 USD"    (nuevo, signed/no signed)
// • fmtSigned(n, ccy)       → "+$1,037.74 USD"    (shorthand de fmtMoney signed)
// • pct, pctSigned          → "+5.2%" etc.
// • colorClass              → tokens rendi-pos/neg/ink-2

// ── Raw number formatting (sin currency code) ────────────────────────────────

export const usd = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const formatted = abs.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  return n < 0 ? `(${formatted})` : formatted
}

export const ars = (n) => {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const formatted = abs.toLocaleString('es-AR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })
  return n < 0 ? `(${formatted})` : formatted
}

// ── Currency labelled (legacy: prefix "USD" o "ARS") ─────────────────────────
// Mantenidos por compat. La API es estable. Nuevos llamados deben usar
// fmtMoney/fmtSigned.

export const fmtUsd = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return '—'
  return `USD ${usd(n, decimals)}`
}

export const fmtArs = (n) => {
  if (n == null || isNaN(n)) return '—'
  return `ARS ${ars(n)}`
}

export const fmtCurrency = (n, currency) => {
  const c = String(currency || 'USD').toUpperCase()
  if (c === 'ARS') return fmtArs(n)
  return fmtUsd(n)
}

// ── Currency con formato del audit: "+$1,037.74 USD" ─────────────────────────
// signed=true incluye + cuando positivo, − cuando negativo (sin paréntesis).
// signed=false omite signo en positivo (igual al formato bancario clásico).

export function fmtMoney(n, currency = 'USD', { signed = false, decimals } = {}) {
  if (n == null || isNaN(n)) return '—'

  const c = String(currency).toUpperCase()
  const isArs = c === 'ARS'
  const dec = decimals != null ? decimals : isArs ? 0 : 2
  const symbol = '$'
  const code = isArs ? 'ARS' : 'USD'
  const locale = isArs ? 'es-AR' : 'en-US'

  const abs = Math.abs(n)
  const formatted = abs.toLocaleString(locale, {
    minimumFractionDigits: dec,
    maximumFractionDigits: dec,
  })

  let sign = ''
  if (signed) {
    if (n > 0) sign = '+'
    else if (n < 0) sign = '−'  // signo unicode minus, no hyphen
  } else if (n < 0) {
    sign = '−'
  }

  return `${sign}${symbol}${formatted} ${code}`
}

export const fmtSigned = (n, currency = 'USD') =>
  fmtMoney(n, currency, { signed: true })

// ── Compact para axes de charts ──────────────────────────────────────────────

export const usdCompact = (n) => {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '−' : ''
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}k`
  return `${sign}$${abs.toFixed(0)}`
}

// ── Percent ──────────────────────────────────────────────────────────────────
// pct: con paréntesis para negativos (legacy)
// pctSigned: con + o − explícito (formato chart axis)

export const pct = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return '—'
  const val = (n * 100).toFixed(decimals)
  return n < 0 ? `(${Math.abs(val).toFixed(decimals)}%)` : `${val}%`
}

export const pctSigned = (n, decimals = 1) => {
  if (n == null || isNaN(n)) return '—'
  const v = n * 100
  const sign = v >= 0 ? '+' : '−'
  return `${sign}${Math.abs(v).toFixed(decimals)}%`
}

// ── Color helper para values ─────────────────────────────────────────────────
// Usa tokens semánticos del audit: rendi-pos / rendi-neg / ink-2 (neutro).
// Reemplaza los emerald-400/red-400 que se usaban legacy.

export const colorClass = (n) =>
  n == null || isNaN(n) || n === 0
    ? 'text-ink-2'
    : n > 0
    ? 'text-rendi-pos'
    : 'text-rendi-neg'

// ── Misc ─────────────────────────────────────────────────────────────────────

export const MONTHS = [
  'ENERO','FEBRERO','MARZO','ABRIL','MAYO','JUNIO',
  'JULIO','AGOSTO','SEPTIEMBRE','OCTUBRE','NOVIEMBRE','DICIEMBRE'
]
