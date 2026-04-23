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

export const pct = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return '—'
  const val = (n * 100).toFixed(decimals)
  return n < 0 ? `(${Math.abs(val).toFixed(decimals)}%)` : `${val}%`
}

export const colorClass = (n) =>
  n == null || isNaN(n) || n === 0 ? 'text-slate-400' : n > 0 ? 'text-emerald-400' : 'text-red-400'

export const MONTHS = [
  'ENERO','FEBRERO','MARZO','ABRIL','MAYO','JUNIO',
  'JULIO','AGOSTO','SEPTIEMBRE','OCTUBRE','NOVIEMBRE','DICIEMBRE'
]
