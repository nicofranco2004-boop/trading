// PageHeader — bloque de título consistente (V2).
// ═══════════════════════════════════════════════════════════════════════════
// V2: estilo más compacto + Eyebrow opcional arriba del título. Tracking
// negativo más agresivo. Mismo API estable hacia los componentes existentes.
//
// API estable + nuevo opcional `eyebrow`:
//   eyebrow     → string opcional (uppercase mono pequeño arriba del título)
//   title       → string (requerido)
//   subtitle    → string opcional
//   action      → ReactNode a la derecha
//   meta        → string (timestamp / contexto live)
//   bordered    → bool (divider abajo)

export default function PageHeader({ title, subtitle, action, meta, bordered = false, eyebrow }) {
  const isLive = meta && /precios|live|actualizado/i.test(meta)

  return (
    <div
      className={`flex items-start justify-between gap-4 mb-6 flex-wrap ${
        bordered ? 'pb-5 border-b border-line' : ''
      }`}
    >
      <div className="min-w-0">
        {eyebrow && (
          <p className="font-mono text-[11px] uppercase tracking-label text-ink-2 font-medium mb-1">
            {eyebrow}
          </p>
        )}
        <h1 className="text-xl sm:text-2xl font-medium text-ink-0 tracking-tight leading-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="text-sm text-ink-2 mt-1 leading-relaxed max-w-2xl">
            {subtitle}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3 flex-shrink-0">
        {meta && (
          <span className="inline-flex items-center gap-2 text-[11px] font-mono text-ink-2 uppercase tracking-caps">
            {isLive && <span className="live-dot" aria-hidden />}
            {meta}
          </span>
        )}
        {action}
      </div>
    </div>
  )
}
