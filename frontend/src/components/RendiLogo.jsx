// Rendi logo — chevron mark in green neon (#37FF68 default).
// Inline SVG with transparent background so it adapts to light/dark themes.
// Backward-compatible API: <RendiLogo size={28} /> still works.
//
// Variants:
//   - "icon" (default): just the chevron mark, transparent bg
//   - "horizontal": full lockup with RENDI wordmark + tagline (uses public asset)
export default function RendiLogo({ size = 28, color = '#37FF68', variant = 'icon', className = '' }) {
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

  // Inline icon: chevron arrows mark, scaled to `size`. No background → adapts to theme.
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 512 512"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="Rendi"
    >
      <g>
        <path d="M132 333V271L260 143C278 125 309 138 309 164C309 172 306 180 300 186L154 333H132Z" fill={color} />
        <path d="M214 333V284L358 140C376 122 407 135 407 161C407 169 404 177 398 183L248 333H214Z" fill={color} />
        <path d="M301 333V294L374 221C391 204 420 216 420 241C420 249 417 256 412 261L340 333H301Z" fill={color} />
        <circle cx="405" cy="328" r="31" fill={color} />
      </g>
    </svg>
  )
}
