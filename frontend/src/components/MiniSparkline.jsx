// MiniSparkline — sparkline ultra-liviana en SVG puro.
// ════════════════════════════════════════════════════════════════════════════
// Sin Recharts. Pensada para grids con muchas instancias (ej. 12 meses por
// año en /reportes). El path se calcula en cliente con scale lineal entre
// min y max de la serie.
//
// Props:
//   • data:     Array<number> — serie de valores (ej. snapshot total_value)
//   • positive: bool          — color verde / rojo según delta del período
//   • width:    number        — ancho px (default 100, el SVG escala con CSS)
//   • height:   number        — alto px (default 24)
//
// Si la serie tiene <2 puntos no renderiza (no se puede trazar línea).

export default function MiniSparkline({ data, positive, width = 100, height = 24 }) {
  if (!Array.isArray(data) || data.length < 2) return null
  // Soporta data como números puros o como objetos { value: number }
  const values = data.map(d => typeof d === 'number' ? d : d.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1   // evita división por cero en serie plana

  const stepX = width / (values.length - 1)
  const points = values.map((v, i) => {
    const x = i * stepX
    // Invertimos Y porque SVG tiene origen arriba-izquierda (y=0 = top)
    const y = height - ((v - min) / range) * height
    return [x, y]
  })

  const path = points
    .map(([x, y], i) => (i === 0 ? `M${x.toFixed(1)},${y.toFixed(1)}` : `L${x.toFixed(1)},${y.toFixed(1)}`))
    .join(' ')

  // Path para el área de relleno (cierra el path hasta la baseline)
  const areaPath = `${path} L${width.toFixed(1)},${height} L0,${height} Z`

  const color = positive ? '#6FE3A3' : '#F17A7A'
  const gradId = `spark-grad-${positive ? 'pos' : 'neg'}`

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className="w-full h-full"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.18} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} />
      <path
        d={path}
        stroke={color}
        strokeWidth={1.25}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
