// Sparkline — V2.
// ═══════════════════════════════════════════════════════════════════════════
// Reemplaza MiniSparkline con tres variantes preset:
//   variant="inline" → 80×20px, para chips/pills/labels
//   variant="row"    → 120×24px, para filas de tabla (default)
//   variant="kpi"    → 200×48px, para cards de KPI grandes
//
// Cambios vs MiniSparkline:
// • Default color = positive (verde) o negative (rojo) según delta de serie
// • Gradient bajo curva más sutil (opacity 0.18 → 0)
// • Stroke 1.5px en variant row/kpi, 1.25px en inline
// • Soporta data como números puros o {value: number}
//
// API:
//   data: Array<number|{value:number}>
//   variant: 'inline' | 'row' | 'kpi'
//   positive: bool (override del autodetect)
//   className: extra clases
//   width / height: override de variant (para casos especiales)

const VARIANTS = {
  inline: { w: 80,  h: 20, stroke: 1.25 },
  row:    { w: 120, h: 24, stroke: 1.5  },
  kpi:    { w: 200, h: 48, stroke: 1.75 },
}

export default function Sparkline({
  data,
  variant = 'row',
  positive,
  className = '',
  width,
  height,
}) {
  if (!Array.isArray(data) || data.length < 2) return null
  const values = data.map(d => typeof d === 'number' ? d : d.value)
  const cfg = VARIANTS[variant] || VARIANTS.row
  const w = width  || cfg.w
  const h = height || cfg.h

  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1

  // Autodetect positive si no se especifica (último vs primero)
  const autoPos = values[values.length - 1] >= values[0]
  const isPos = positive !== undefined ? positive : autoPos

  const stepX = w / (values.length - 1)
  const points = values.map((v, i) => {
    const x = i * stepX
    const y = h - ((v - min) / range) * h
    return [x, y]
  })

  const path = points
    .map(([x, y], i) => (i === 0 ? `M${x.toFixed(1)},${y.toFixed(1)}` : `L${x.toFixed(1)},${y.toFixed(1)}`))
    .join(' ')

  const areaPath = `${path} L${w.toFixed(1)},${h} L0,${h} Z`

  const color = isPos ? '#21D07A' : '#FF5360'
  const gradId = `spark-${variant}-${isPos ? 'p' : 'n'}-${data.length}`

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className={`w-full h-full ${className}`}
      style={{ minWidth: w, height: h }}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"  stopColor={color} stopOpacity={0.18} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} />
      <path
        d={path}
        stroke={color}
        strokeWidth={cfg.stroke}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
