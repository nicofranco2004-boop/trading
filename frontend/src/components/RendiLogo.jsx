// Rendi logo — referencia 1:1 al archivo de branding.
// Usa el PNG hi-res (989x989) que provee branding. Para tamaños chicos
// (favicon 16-32px), el browser hace downsampling sin pérdida visual notable.
// Si más adelante se reemplaza por un .svg vectorial, basta cambiar la extensión.
//
// Backward-compatible API: <RendiLogo size={28} variant="icon" />

export default function RendiLogo({ size = 28, variant = 'icon', className = '' }) {
  if (variant === 'horizontal') {
    return (
      <img
        src="/brand/rendi-logo-horizontal.svg"
        alt="Rendi - Entendé tu inversión"
        style={{ height: size, width: 'auto' }}
        className={className}
      />
    )
  }

  return (
    <img
      src="/brand/rendi-mark.png"
      alt="Rendi"
      width={size}
      height={size}
      style={{ display: 'block' }}
      className={className}
    />
  )
}
