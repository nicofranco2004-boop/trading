// EmptyState — bloque consistente para "no hay datos" (Sprint M3, item 17).
// ═══════════════════════════════════════════════════════════════════════════
// Patrón unificado: explica QUÉ falta y QUÉ puede hacer el user. Nunca solo
// "Sin datos".
//
// Props:
//   icon        — JSX (ej. <Brain size={20} />)
//   eyebrow     — mono caps arriba del título (ej. "WATCHLIST" · "OPERACIONES")
//   title       — frase principal
//   description — explicación + sugerencia
//   action      — botón / link CTA
//   dense       — versión compacta (menos padding)
//   tone        — 'default' | 'positive' | 'warn' (cambia el color del eyebrow)

const TONE_CLASS = {
  default:  'text-ink-3',
  positive: 'text-rendi-pos',
  warn:     'text-rendi-warn',
}

export default function EmptyState({
  icon,
  eyebrow,
  title,
  description,
  action,
  dense = false,
  tone = 'default',
}) {
  return (
    <div className={`text-center ${dense ? 'py-6' : 'py-10'}`}>
      {icon && (
        <div className="mx-auto mb-3 w-10 h-10 rounded-sm bg-bg-2 border border-line/40 flex items-center justify-center text-ink-3">
          {icon}
        </div>
      )}
      {eyebrow && (
        <p className={`text-[12px] mb-1.5 ${TONE_CLASS[tone] || TONE_CLASS.default} font-medium`}>
          {eyebrow}
        </p>
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
