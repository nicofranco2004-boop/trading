// ── Number formatting ────────────────────────────────────────────────────────

export const usd = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const formatted = abs.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
  return n < 0 ? `(${formatted})` : formatted
}

export const ars = (n) => {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const formatted = abs.toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
  return n < 0 ? `(${formatted})` : formatted
}

// ── Labelled currency ────────────────────────────────────────────────────────
// Use these instead of bare `$` so ARS vs USD is never ambiguous.

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

// Compact for charts axes: $20.5k, $1.2M
export const usdCompact = (n) => {
  if (n == null || isNaN(n)) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}k`
  return `${sign}$${abs.toFixed(0)}`
}

export const pct = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return '—'
  const val = (n * 100).toFixed(decimals)
  return n < 0 ? `(${Math.abs(val).toFixed(decimals)}%)` : `${val}%`
}

// Signed percent for chart axes (+5.2% / -3.1%) without parentheses
export const pctSigned = (n, decimals = 1) => {
  if (n == null || isNaN(n)) return '—'
  const v = n * 100
  return `${v >= 0 ? '+' : ''}${v.toFixed(decimals)}%`
}

export const colorClass = (n) =>
  n == null || isNaN(n) || n === 0 ? 'text-slate-400' : n > 0 ? 'text-emerald-400' : 'text-red-400'

export const MONTHS = [
  'ENERO','FEBRERO','MARZO','ABRIL','MAYO','JUNIO',
  'JULIO','AGOSTO','SEPTIEMBRE','OCTUBRE','NOVIEMBRE','DICIEMBRE'
]
