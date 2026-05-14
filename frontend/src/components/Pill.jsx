// Pill — chip compacto para status / labels / metadatos.
// Estándar visual v2: uppercase mono, padding tight, border + bg sutil.
//
// Tones (semánticos, no decorativos):
//   default → neutral (label genérico)
//   signal  → verde (live, positivo, success)
//   red     → rojo (negativo, error)
//   warn    → ámbar (atención, stale)
//   info    → azul (información secundaria)
//   off     → muy sutil (deshabilitado / pasado)
//
// Uso:
//   <Pill>SP500</Pill>
//   <Pill tone="signal" dot>Live</Pill>
//   <Pill tone="warn">Stale 4h</Pill>

const TONE = {
  default: { border: 'border-line', bg: 'bg-bg-2', text: 'text-ink-2', dot: 'bg-ink-2' },
  signal:  { border: 'border-rendi-pos/30', bg: 'bg-rendi-pos/10', text: 'text-rendi-pos', dot: 'bg-rendi-pos' },
  red:     { border: 'border-rendi-neg/30', bg: 'bg-rendi-neg/10', text: 'text-rendi-neg', dot: 'bg-rendi-neg' },
  warn:    { border: 'border-rendi-warn/30', bg: 'bg-rendi-warn/10', text: 'text-rendi-warn', dot: 'bg-rendi-warn' },
  info:    { border: 'border-data-blue/30', bg: 'bg-data-blue/10', text: 'text-data-blue', dot: 'bg-data-blue' },
  off:     { border: 'border-line', bg: 'bg-bg-1', text: 'text-ink-3', dot: 'bg-ink-3' },
}

export default function Pill({ children, tone = 'default', dot = false, className = '' }) {
  const t = TONE[tone] || TONE.default
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-1.5 py-0.5 rounded-sm border ${t.border} ${t.bg} ${t.text} font-mono text-[10px] uppercase tracking-caps font-medium ${className}`}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${t.dot}`} aria-hidden="true" />}
      {children}
    </span>
  )
}
