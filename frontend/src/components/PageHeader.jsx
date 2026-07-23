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
        {/* Clean pass 2026-07: eyebrow sans violeta (antes mono uppercase),
            título más grande y pesado — jerarquía editorial, no de terminal. */}
        {eyebrow && (
          <p className="text-[12.5px] font-semibold text-data-violet mb-1.5">
            {eyebrow}
          </p>
        )}
        <h1 className="text-2xl sm:text-[27px] font-semibold text-ink-0 tracking-tight leading-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="text-[14px] text-ink-2 mt-1.5 leading-relaxed max-w-2xl">
            {subtitle}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3 flex-shrink-0">
        {meta && (
          <span className="inline-flex items-center gap-2 text-[12px] text-ink-2 font-medium">
            {isLive && <span className="live-dot" aria-hidden />}
            {meta}
          </span>
        )}
        {action}
      </div>
    </div>
  )
}
