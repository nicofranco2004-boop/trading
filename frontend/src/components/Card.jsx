// Card — single source of truth para panel/card chrome.
// ═══════════════════════════════════════════════════════════════════════════
// Audit visual mayo 2026: cards con borde + gradiente + sombra + backdrop-blur
// se ven "templated dashboard". Linear/Mercury/Stripe usan menos contención
// visual: divisores finos, espacios negativos, jerarquía por tamaño y peso.
//
// Cambios:
// • Eliminado backdrop-blur (no aporta).
// • Eliminado shadow en dark mode (audit: elevación = borde + cambio de fondo).
// • Border más sutil (line tokens, no slate-200/800).
// • bg-bg-1 en dark (más cálido, menos navy).
// • Padding alineado a spacing scale (no ad-hoc).
// • Radius por default = rounded (10px del audit).
//
// API estable:
//   children    → contenido
//   className   → clases extras
//   padding     → 'none' | 'sm' | 'md' (default) | 'lg'
//   as          → 'div' (default), 'section', etc.
//   hoverable   → bool, hover sutil de border
//   accent      → bool, border en rendi-pos (KPI principal)

export default function Card({
  children,
  className = '',
  padding = 'md',
  as = 'div',
  hoverable = false,
  accent = false,
  ...rest
}) {
  const Tag = as
  const padClass =
    padding === 'none' ? '' :
    padding === 'sm' ? 'p-3' :
    padding === 'lg' ? 'p-6 sm:p-8' :
    'p-4 sm:p-5'

  // Light mode mantiene un look limpio con borde sutil; dark mode usa
  // bg-bg-1 (más cálido que slate-800) y border-line.
  const base = 'bg-white dark:bg-bg-1 rounded'
  const borderClass = accent
    ? 'border border-rendi-pos/40 dark:border-rendi-pos/30'
    : 'border border-slate-200 dark:border-line'
  const hover = hoverable
    ? 'transition-colors hover:border-slate-300 dark:hover:border-line-2'
    : ''

  return (
    <Tag
      className={`${base} ${borderClass} ${padClass} ${hover} ${className}`}
      {...rest}
    >
      {children}
    </Tag>
  )
}

// CardHeader — header consistente dentro de cualquier Card.
// Mantiene API estable. Tipografía actualizada al sistema nuevo.
export function CardHeader({ title, subtitle, action, icon }) {
  return (
    <div className="flex items-start justify-between gap-3 mb-4">
      <div className="min-w-0 flex items-start gap-2">
        {icon && (
          <span className="mt-0.5 text-ink-3 flex-shrink-0">{icon}</span>
        )}
        <div className="min-w-0">
          <h2 className="font-semibold text-slate-800 dark:text-ink-0 leading-tight">
            {title}
          </h2>
          {subtitle && (
            <p className="text-xs text-slate-500 dark:text-ink-2 mt-0.5 leading-snug">
              {subtitle}
            </p>
          )}
        </div>
      </div>
      {action && <div className="flex-shrink-0">{action}</div>}
    </div>
  )
}
