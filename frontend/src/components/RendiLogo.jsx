// Rendi logo — referencia 1:1 al archivo de branding.
// ════════════════════════════════════════════════════════════════════════════
// PERFORMANCE FIX (audit 2026-05-25): antes usábamos `rendi-mark.png` que era
// un PNG de 1.27MB a 1254x1254px, renderizado en sizes 28-48px. Eso bloqueaba
// LCP en mobile 4G por ~8-10s. Ahora usamos versiones optimizadas:
//   - rendi-mark-64.png   (5.3KB)  → para size ≤ 32
//   - rendi-mark-128.png  (14KB)   → para size ≤ 64
//   - rendi-mark-256.png  (43KB)   → para size > 64 (típicamente NO se usa)
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

  // Elegir variante por tamaño objetivo. Renderizamos al 2× para retina sin
  // pagar el peso de la versión gigante. La mayoría del uso es size 28-48.
  let src
  if (size <= 32) {
    src = '/brand/rendi-mark-64.png'
  } else if (size <= 64) {
    src = '/brand/rendi-mark-128.png'
  } else {
    src = '/brand/rendi-mark-256.png'
  }

  return (
    <img
      src={src}
      alt="Rendi"
      width={size}
      height={size}
      style={{ display: 'block' }}
      className={className}
      loading={size > 48 ? 'lazy' : 'eager'}
    />
  )
}
