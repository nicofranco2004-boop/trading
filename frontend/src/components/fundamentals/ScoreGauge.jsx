// ScoreGauge — anillo circular SVG con el "Rendi Score" overall.
// ═══════════════════════════════════════════════════════════════════════════
// props: { score (0-100), label ('Excelente'|'Bueno'|'Mixto'|'Débil'|'Sin datos') }
// Color del anillo por label: Excelente/Bueno → verde, Mixto → ámbar, Débil → rojo.
// SVG a mano: stroke-dasharray sobre un círculo (sin libs).

import Pill from '../Pill'

// Mapea label → { stroke (hex var de CSS), tone (Pill) }.
// Usamos los hex de los tokens directamente para el stroke del SVG.
const COLORS = {
  pos:  { stroke: '#21D07A', tone: 'signal' },
  warn: { stroke: '#E8B14A', tone: 'warn' },
  neg:  { stroke: '#FF5360', tone: 'red' },
  off:  { stroke: '#6B7280', tone: 'default' },
}

function colorForLabel(label) {
  const l = (label || '').toLowerCase()
  if (l === 'excelente' || l === 'bueno') return COLORS.pos
  if (l === 'mixto') return COLORS.warn
  if (l === 'débil' || l === 'debil') return COLORS.neg
  return COLORS.off
}

export default function ScoreGauge({ score, label, size = 168 }) {
  const hasScore = typeof score === 'number' && !Number.isNaN(score)
  const pct = hasScore ? Math.max(0, Math.min(100, score)) : 0
  const c = colorForLabel(label)

  const stroke = 12
  const r = (size - stroke) / 2
  const cx = size / 2
  const cy = size / 2
  const circumference = 2 * Math.PI * r
  const dash = (pct / 100) * circumference

  return (
    <div className="flex flex-col items-center justify-center text-center">
      <p className="text-[10px] font-mono uppercase tracking-caps text-ink-2 mb-3">
        Rendi Score
      </p>
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="block">
          {/* Pista de fondo */}
          <circle
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke="currentColor"
            className="text-bg-2"
            strokeWidth={stroke}
          />
          {/* Progreso */}
          {hasScore && (
            <circle
              cx={cx} cy={cy} r={r}
              fill="none"
              stroke={c.stroke}
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={`${dash} ${circumference - dash}`}
              transform={`rotate(-90 ${cx} ${cy})`}
              style={{ transition: 'stroke-dasharray 600ms ease-out' }}
            />
          )}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-4xl font-semibold text-ink-0 tabular leading-none">
            {hasScore ? pct : '—'}
          </span>
          <span className="text-xs text-ink-3 mt-1">/100</span>
        </div>
      </div>
      <div className="mt-3">
        <Pill tone={c.tone}>{label || 'Sin datos'}</Pill>
      </div>
    </div>
  )
}
