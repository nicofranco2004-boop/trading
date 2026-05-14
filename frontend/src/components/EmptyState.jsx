// Consistent empty-state component. Always explains WHAT is missing and WHAT
// the user can do next — never just "Sin datos".

export default function EmptyState({ icon, title, description, action, dense = false }) {
  return (
    <div className={`text-center ${dense ? 'py-6' : 'py-10'}`}>
      {icon && (
        <div className="mx-auto mb-3 w-10 h-10 rounded-full bg-bg-2 dark:bg-bg-2/40 flex items-center justify-center text-ink-3">
          {icon}
        </div>
      )}
      {title && (
        <p className="text-sm font-medium text-ink-1">{title}</p>
      )}
      {description && (
        <p className="text-xs text-ink-3 mt-1 max-w-sm mx-auto leading-relaxed">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
