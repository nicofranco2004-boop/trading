// ProfileRadar — radar declarado vs cartera real (Análisis › Perfil).
// ═══════════════════════════════════════════════════════════════════════════
// Chart SVG puro (sin recharts): n ejes variables (3-5). Contorno gris
// punteado = lo que declaraste en el test; área violeta = tu cartera real.
// Renderiza solo el BODY del módulo — header/badge viven en el shell.

const CX = 118
const CY = 100
const R = 66

const clamp = (v) => Math.max(0, Math.min(100, Number(v) || 0))

// Punto (x,y) del eje i de n, a radio r (unidades del viewBox)
function point(i, n, r) {
  const angle = -Math.PI / 2 + (i * 2 * Math.PI) / n
  return [CX + r * Math.cos(angle), CY + r * Math.sin(angle)]
}

function polygon(axes, key) {
  return axes
    .map((a, i) => point(i, axes.length, (R * clamp(a[key])) / 100).join(','))
    .join(' ')
}

export default function ProfileRadar({ axes }) {
  if (!axes || axes.length < 3) return null
  const n = axes.length
  const gridPts = (pct) => axes.map((_, i) => point(i, n, (R * pct) / 100).join(',')).join(' ')
  // Ejes donde la cartera real supera lo declarado por >15 pts → nota al pie
  const exceeded = axes
    .filter((a) => clamp(a.actual) - clamp(a.declared) > 15)
    .map((a) => a.label.toLowerCase())

  return (
    <div>
      <svg
        viewBox="0 0 236 200"
        width="100%"
        style={{ maxWidth: 320 }}
        className="block mx-auto"
        role="img"
        aria-label={`Radar del perfil: declarado vs cartera real en ${n} ejes`}
      >
        {/* Grilla — polígonos concéntricos + rayos */}
        <g aria-hidden="true" stroke="#1B2230" strokeWidth="1" fill="none">
          {[25, 50, 75, 100].map((pct) => (
            <polygon key={pct} points={gridPts(pct)} />
          ))}
          {axes.map((_, i) => {
            const [x, y] = point(i, n, R)
            return <line key={i} x1={CX} y1={CY} x2={x} y2={y} />
          })}
        </g>
        {/* Perfil declarado — contorno gris punteado */}
        <polygon
          points={polygon(axes, 'declared')}
          fill="none"
          stroke="#9CA3B5"
          strokeWidth="1.5"
          strokeDasharray="3 3"
        />
        {/* Cartera real — área violeta */}
        <polygon
          points={polygon(axes, 'actual')}
          fill="rgba(139,125,255,.20)"
          stroke="#8B7DFF"
          strokeWidth="2"
        />
        {/* Labels de eje, afuera de la grilla */}
        {axes.map((a, i) => {
          const [x, y] = point(i, n, R * 1.24)
          return (
            <text
              key={i}
              x={x}
              y={y}
              fill="#9CA3B5"
              fontSize="9"
              textAnchor="middle"
              dominantBaseline="middle"
            >
              {a.label}
            </text>
          )
        })}
      </svg>

      {/* Leyenda */}
      <div className="flex items-center justify-center gap-4 mt-2">
        <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-2">
          <span
            className="inline-block w-4 border-t border-dashed"
            style={{ borderColor: '#9CA3B5' }}
            aria-hidden="true"
          />
          Perfil declarado
        </span>
        <span className="inline-flex items-center gap-1.5 text-[11px] text-ink-2">
          <span
            className="inline-block w-3 h-2 rounded-[2px]"
            style={{ background: 'rgba(139,125,255,.20)', border: '1px solid #8B7DFF' }}
            aria-hidden="true"
          />
          Tu cartera real
        </span>
      </div>

      <p className="text-xs text-ink-2 leading-relaxed mt-2">
        Donde el violeta se sale del contorno gris, tu cartera real va más allá de lo que
        declaraste.
        {exceeded.length > 0 && (
          <>
            {' '}
            Típico en <b className="text-ink-1">{exceeded.join(' y ')}</b>.
          </>
        )}
      </p>
    </div>
  )
}
