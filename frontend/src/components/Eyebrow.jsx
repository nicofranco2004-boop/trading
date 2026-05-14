// Eyebrow — kicker uppercase mono para arriba de títulos y secciones.
// Estándar visual v2: tracking 0.12em, font-mono, text-ink-3 default.
//
// Uso:
//   <Eyebrow>Performance</Eyebrow>
//   <Eyebrow tone="signal">Live</Eyebrow>
//   <Eyebrow tone="red">Stale</Eyebrow>

const TONE = {
  default: 'text-ink-3',
  signal:  'text-rendi-pos',
  red:     'text-rendi-neg',
  warn:    'text-rendi-warn',
  cyan:    'text-data-cyan',
}

export default function Eyebrow({ children, tone = 'default', className = '' }) {
  return (
    <span className={`font-mono text-[10px] sm:text-[11px] uppercase tracking-label font-medium ${TONE[tone] || TONE.default} ${className}`}>
      {children}
    </span>
  )
}
