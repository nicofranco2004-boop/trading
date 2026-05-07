// Consistent empty-state component. Always explains WHAT is missing and WHAT
// the user can do next — never just "Sin datos".

export default function EmptyState({ icon, title, description, action, dense = false }) {
  return (
    <div className={`text-center ${dense ? 'py-6' : 'py-10'}`}>
      {icon && (
        <div className="mx-auto mb-3 w-10 h-10 rounded-full bg-slate-100 dark:bg-slate-700/40 flex items-center justify-center text-slate-400 dark:text-slate-500">
          {icon}
        </div>
      )}
      {title && (
        <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{title}</p>
      )}
      {description && (
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-sm mx-auto leading-relaxed">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
