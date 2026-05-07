// InsightLine — short, dynamic plain-Spanish explanation that goes below
// the hero number on the Dashboard. Designed to grow into more sophisticated
// auto-generated diagnostics later.
//
// tone: 'positive' | 'negative' | 'neutral' | 'warning'

const TONE_CLASS = {
  positive: 'text-emerald-600 dark:text-emerald-400 bg-emerald-500/[0.06] border-emerald-500/20',
  negative: 'text-red-600 dark:text-red-400 bg-red-500/[0.06] border-red-500/20',
  warning:  'text-amber-600 dark:text-amber-400 bg-amber-500/[0.06] border-amber-500/20',
  neutral:  'text-slate-600 dark:text-slate-300 bg-slate-500/[0.06] border-slate-500/20',
}

export default function InsightLine({ tone = 'neutral', icon, children, className = '' }) {
  const cls = TONE_CLASS[tone] || TONE_CLASS.neutral
  return (
    <div className={`inline-flex items-start gap-2 px-3 py-2 rounded-lg border text-sm leading-snug ${cls} ${className}`}>
      {icon && <span className="flex-shrink-0 mt-0.5">{icon}</span>}
      <span>{children}</span>
    </div>
  )
}
