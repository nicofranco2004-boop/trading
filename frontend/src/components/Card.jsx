// Single source of truth for the panel/card chrome used across the app.
// Replaces the repeated `bg-white dark:bg-slate-800/60 border border-slate-200/80
// dark:border-slate-700/50 shadow-sm dark:shadow-none rounded-xl` pattern.

export default function Card({ children, className = '', padding = 'md', as = 'div', hoverable = false, accent = false, ...rest }) {
  const Tag = as
  const padClass = padding === 'none' ? '' : padding === 'sm' ? 'p-3' : padding === 'lg' ? 'p-6' : 'p-4 sm:p-5'
  const base = 'bg-white dark:bg-slate-800/60 backdrop-blur-[2px] rounded-xl shadow-sm dark:shadow-none border'
  const borderClass = accent
    ? 'border-rendi-green/40 dark:border-rendi-green/30'
    : 'border-slate-200/80 dark:border-slate-700/50'
  const hover = hoverable ? 'transition-colors hover:border-slate-300 dark:hover:border-slate-600' : ''
  return (
    <Tag className={`${base} ${borderClass} ${padClass} ${hover} ${className}`} {...rest}>
      {children}
    </Tag>
  )
}

// Section header inside a Card (or anywhere). Keeps spacing consistent.
export function CardHeader({ title, subtitle, action, icon }) {
  return (
    <div className="flex items-start justify-between gap-3 mb-4">
      <div className="min-w-0 flex items-start gap-2">
        {icon && <span className="mt-0.5 text-slate-400 dark:text-slate-500 flex-shrink-0">{icon}</span>}
        <div className="min-w-0">
          <h2 className="font-semibold text-slate-800 dark:text-slate-200 leading-tight">{title}</h2>
          {subtitle && <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 leading-snug">{subtitle}</p>}
        </div>
      </div>
      {action && <div className="flex-shrink-0">{action}</div>}
    </div>
  )
}
