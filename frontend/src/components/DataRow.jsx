// DataRow — fila densa estandarizada para tablas y listas v2.
// ═══════════════════════════════════════════════════════════════════════════
// El "átomo de tabla" de Rendi v2. 40-44px de alto, padding compacto, type
// 13-14px. Reemplaza filas custom dispersas en /posiciones, /operaciones,
// /reportes, /home/*.
//
// API (compositional — pasás children con estructura libre):
//   density   → 'compact' (40px), 'default' (44px), 'cozy' (52px)
//   hoverable → bool, hover state sutil
//   onClick   → si está presente, renderea como <button> y agrega cursor
//   selected  → bool, accent border-left signal
//   className → extras
//
// Patrón de uso típico:
//   <DataRow hoverable onClick={...}>
//     <DataRow.Cell>AAPL</DataRow.Cell>
//     <DataRow.Cell align="right">+2.4%</DataRow.Cell>
//   </DataRow>

const DENSITY = {
  compact: 'min-h-[36px] py-1.5 px-3',
  default: 'min-h-[44px] py-2 px-3',
  cozy:    'min-h-[52px] py-2.5 px-4',
}

export default function DataRow({
  children,
  density = 'default',
  hoverable = false,
  selected = false,
  onClick,
  className = '',
  ...rest
}) {
  const Tag = onClick ? 'button' : 'div'
  const interactive = onClick ? 'text-left w-full' : ''
  const hover = hoverable ? 'hover:bg-bg-2/60 transition-colors' : ''
  const sel = selected ? 'border-l-2 border-l-rendi-pos pl-[10px]' : ''

  return (
    <Tag
      onClick={onClick}
      className={`flex items-center gap-3 ${DENSITY[density] || DENSITY.default} ${hover} ${interactive} ${sel} ${className}`}
      {...rest}
    >
      {children}
    </Tag>
  )
}

// DataRow.Cell — celda interna con alineación y truncado por defecto.
DataRow.Cell = function Cell({
  children,
  align = 'left',
  mono = false,
  tabular = false,
  muted = false,
  className = '',
  width,
}) {
  const alignClass =
    align === 'right' ? 'text-right justify-end' :
    align === 'center' ? 'text-center justify-center' :
                         'text-left'
  const fontClass = mono ? 'font-mono' : ''
  const tabClass = tabular ? 'num' : ''
  const colorClass = muted ? 'text-ink-3' : 'text-ink-1'
  const widthStyle = width ? { minWidth: width, maxWidth: width } : {}

  return (
    <div
      className={`flex items-center min-w-0 truncate ${alignClass} ${fontClass} ${tabClass} ${colorClass} ${className}`}
      style={widthStyle}
    >
      {children}
    </div>
  )
}

// DataRow.Header — fila de header tipográficamente consistente.
// Eyebrows uppercase mono, separator inferior 1px.
DataRow.Header = function Header({ children, className = '' }) {
  return (
    <div className={`flex items-center gap-3 min-h-[32px] px-3 border-b border-line text-[10px] uppercase tracking-label font-mono text-ink-3 font-medium ${className}`}>
      {children}
    </div>
  )
}
