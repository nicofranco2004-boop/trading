// Consistent page title block. Use at the top of every page so spacing,
// typography, and action button placement are identical.

export default function PageHeader({ title, subtitle, action, meta }) {
  return (
    <div className="flex items-start justify-between gap-4 mb-6 flex-wrap">
      <div className="min-w-0">
        <h1 className="text-xl sm:text-2xl font-bold text-slate-900 dark:text-slate-100 tracking-tight">{title}</h1>
        {subtitle && (
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{subtitle}</p>
        )}
      </div>
      <div className="flex items-center gap-3 flex-shrink-0">
        {meta && <span className="text-xs text-slate-400 dark:text-slate-500">{meta}</span>}
        {action}
      </div>
    </div>
  )
}
