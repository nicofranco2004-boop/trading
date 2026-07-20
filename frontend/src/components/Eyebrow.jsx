// Eyebrow — kicker para arriba de títulos y secciones.
// Clean pass 2026-07: de mono-MAYÚSCULA-micro (look terminal) a sans legible
// sentence-case. El mono queda reservado para NÚMEROS; los labels son texto.
//
// Uso:
//   <Eyebrow>Performance</Eyebrow>
//   <Eyebrow tone="signal">Live</Eyebrow>
//   <Eyebrow tone="red">Stale</Eyebrow>

const TONE = {
  default: 'text-ink-2',
  signal:  'text-rendi-pos',
  red:     'text-rendi-neg',
  warn:    'text-rendi-warn',
  cyan:    'text-data-cyan',
}

export default function Eyebrow({ children, tone = 'default', className = '' }) {
  return (
    <span className={`text-[13px] font-semibold ${TONE[tone] || TONE.default} ${className}`}>
      {children}
    </span>
  )
}
