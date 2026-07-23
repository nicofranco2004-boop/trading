// ConcentrationDonut — donut CSS de concentración (top 3 tenencias vs cartera).
// ═══════════════════════════════════════════════════════════════════════════
// Body del módulo de concentración en el perfil: donut por conic-gradient
// (sin libs de charts) + leyenda con swatches + nota con el veredicto según
// el perfil declarado (comparison: above/within/below). El header lo pone
// la card contenedora — acá solo va el cuerpo.

const SLICE_COLORS = ['#8B7DFF', '#A79BFF', '#C4BCFF', '#2E3650', '#232B3E']
const REST_COLOR = '#1B2230'

export default function ConcentrationDonut({ holdings, top3Pct, comparison }) {
  if (!holdings?.length || top3Pct == null) return null

  // Slices acumulados para el conic-gradient; el resto (100 − Σ) va en gris.
  const slices = holdings.slice(0, 5)
  let acc = 0
  const stops = slices.map((h, i) => {
    const start = acc
    acc = Math.min(100, acc + Math.max(0, h.pct))
    return `${SLICE_COLORS[i]} ${start}% ${acc}%`
  })
  if (acc < 100) stops.push(`${REST_COLOR} ${acc}% 100%`)

  const toneCls =
    comparison === 'above'
      ? 'text-rendi-warn'
      : comparison === 'below'
        ? 'text-rendi-pos'
        : 'text-ink-1'
  const suffix =
    comparison === 'above'
      ? ' — por encima de lo típico para tu perfil.'
      : comparison === 'below'
        ? ' — bien repartida para tu perfil.'
        : '.'

  return (
    <div>
      <div className="flex flex-wrap items-center gap-4">
        {/* Donut — conic-gradient puro; el agujero es un div del color de la card */}
        <div
          role="img"
          aria-label={`Tus 3 mayores tenencias concentran el ${top3Pct}% de la cartera`}
          className="relative w-[110px] h-[110px] rounded-full flex-shrink-0"
          style={{ background: `conic-gradient(${stops.join(', ')})` }}
        >
          <div className="absolute inset-[18px] rounded-full bg-bg-1 flex flex-col items-center justify-center">
            <div className="text-xl font-semibold text-ink-0 tabular-nums leading-none">
              {top3Pct}%
            </div>
            <div className="text-[12.5px] text-ink-2 mt-1 font-medium">
              Top 3
            </div>
          </div>
        </div>

        {/* Leyenda — una fila por tenencia, swatch del color de su slice */}
        <div className="flex-1 min-w-[140px] space-y-1.5">
          {slices.map((h, i) => (
            <div key={i} className="flex items-center gap-2">
              <span
                className="w-2 h-2 rounded-sm flex-shrink-0"
                style={{ background: SLICE_COLORS[i] }}
              />
              <span className="text-xs text-ink-1 truncate flex-1">{h.name}</span>
              <span className="font-mono text-[11px] text-ink-2 tabular-nums">{h.pct}%</span>
            </div>
          ))}
        </div>
      </div>

      <p className="text-xs text-ink-2 mt-4">
        Tus 3 mayores tenencias concentran{' '}
        <span className={`${toneCls} tabular-nums`}>{top3Pct}%</span> de la cartera
        {suffix}
      </p>
    </div>
  )
}
