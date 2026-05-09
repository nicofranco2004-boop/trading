// StatCard — supports two visual tones for hierarchy:
//   tone="primary"   → larger, hero metric (Portfolio Total)
//   tone="secondary" → standard (default)
//
// `positive` colors the main value (use for P&L)
// `pnlPositive` colors only the "P&L: $..." segment of `sub`
// `tooltip` (ReactNode) → si se pasa, renderiza un ⓘ al lado del label que
//   despliega el contenido al hacer hover. Usar para aclarar definiciones
//   financieras (CAGR, P&L realizado vs no realizado, etc.).

import InfoTooltip from './InfoTooltip'

export default function StatCard({ label, value, sub, hint, positive, pnlPositive, tone = 'secondary', icon, tooltip }) {
  const isPrimary = tone === 'primary'

  const valueColor =
    positive == null
      ? 'text-slate-900 dark:text-slate-100'
      : positive
      ? 'text-emerald-500 dark:text-emerald-400'
      : 'text-red-500 dark:text-red-400'

  const subPnlColor = pnlPositive == null ? '' : pnlPositive ? 'text-emerald-500 dark:text-emerald-400' : 'text-red-500 dark:text-red-400'

  // Split "P&L:" segment for color
  let subNode = sub
  if (sub && pnlPositive != null && typeof sub === 'string' && sub.includes('P&L:')) {
    const [before, after] = sub.split('P&L:')
    subNode = (
      <span>
        {before}
        <span className={subPnlColor}>P&L: {after}</span>
      </span>
    )
  }

  const containerCls = isPrimary
    ? 'bg-gradient-to-br from-white to-slate-50 dark:from-slate-800/80 dark:to-slate-800/40 border border-slate-200 dark:border-slate-700/60 rounded-xl shadow-sm dark:shadow-none p-5 sm:p-6'
    : 'bg-white dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/50 shadow-sm dark:shadow-none rounded-xl p-3 sm:p-4'

  const labelCls = isPrimary
    ? 'text-slate-500 dark:text-slate-400 text-xs uppercase tracking-[0.12em] font-medium mb-2'
    : 'text-slate-500 dark:text-slate-400 text-[10px] sm:text-xs uppercase tracking-wider mb-1 truncate'

  const valueCls = isPrimary
    ? `text-3xl sm:text-4xl font-bold tracking-tight ${valueColor} break-words`
    : `text-lg sm:text-2xl font-bold ${valueColor} break-words`

  const subCls = isPrimary
    ? 'text-sm text-slate-500 dark:text-slate-400 mt-2'
    : 'text-slate-400 dark:text-slate-500 text-[10px] sm:text-xs mt-1 truncate'

  return (
    <div className={containerCls}>
      <div className="flex items-center gap-2 justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          <p className={labelCls}>{label}</p>
          {tooltip && <InfoTooltip>{tooltip}</InfoTooltip>}
        </div>
        {icon && <span className="text-slate-400 dark:text-slate-500 flex-shrink-0">{icon}</span>}
      </div>
      <p className={valueCls}>{value}</p>
      {sub && <p className={subCls}>{subNode}</p>}
      {hint && <p className="text-[11px] text-slate-400 dark:text-slate-500 mt-1.5">{hint}</p>}
    </div>
  )
}
