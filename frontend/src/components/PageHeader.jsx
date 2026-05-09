// PageHeader — bloque de título consistente para toda la app.
// ═══════════════════════════════════════════════════════════════════════════
// Estructura del audit visual:
// • Title: Manrope 600, 24-32px, tracking tight.
// • Subtitle: text-ink-2, sin tracking forzado.
// • Meta: chip con live-dot pulsante a la derecha (ej: "● Precios · 14:23").
//   Si meta empieza con "Precios" o contiene "Live", se renderiza con dot.
// • bordered: prop opcional que agrega divider inferior (no breaking).
//
// API estable:
//   title       → string (requerido)
//   subtitle    → string (opcional)
//   action      → ReactNode (botones a la derecha)
//   meta        → string (timestamp / contexto live)
//   bordered    → bool (divider abajo, default false)

export default function PageHeader({ title, subtitle, action, meta, bordered = false }) {
  // Detectar si el meta indica estado live (precios, datos, sync)
  const isLive = meta && /precios|live|actualizado/i.test(meta)

  return (
    <div
      className={`flex items-start justify-between gap-4 mb-6 sm:mb-8 flex-wrap ${
        bordered ? 'pb-6 border-b border-slate-200 dark:border-line' : ''
      }`}
    >
      <div className="min-w-0">
        <h1 className="text-xl sm:text-2xl font-semibold text-slate-900 dark:text-ink-0 tracking-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="text-sm text-slate-500 dark:text-ink-2 mt-1.5 leading-relaxed max-w-2xl">
            {subtitle}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3 flex-shrink-0">
        {meta && (
          <span className="inline-flex items-center gap-2 text-[11px] font-mono text-slate-400 dark:text-ink-2 tracking-wide">
            {isLive && <span className="live-dot" aria-hidden />}
            {meta}
          </span>
        )}
        {action}
      </div>
    </div>
  )
}
