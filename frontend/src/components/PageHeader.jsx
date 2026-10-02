// PageHeader — bloque de título consistente (V2).
// ═══════════════════════════════════════════════════════════════════════════
// V2: estilo más compacto + Eyebrow opcional arriba del título. Tracking
// negativo más agresivo. Mismo API estable hacia los componentes existentes.
//
// API estable + nuevo opcional `eyebrow`:
//   eyebrow     → string opcional (sans semibold violeta arriba del título)
//   title       → string (requerido)
//   subtitle    → string opcional
//   action      → ReactNode a la derecha
//   meta        → string (contexto) o un nodo que se dibuja tal cual — los
//                 precios van con <PreciosEnVivo>, que decide si su punto late
//   bordered    → bool (divider abajo)

export default function PageHeader({ title, subtitle, action, meta, bordered = false, eyebrow }) {
  // El punto que late lo decide quien SABE si el dato se mueve (un nodo como
  // <PreciosEnVivo>), nunca un texto fijo. Hasta el 2026-10-01 bastaba la
  // palabra "precios" o "live": Cartera, Dashboard y Novedades latían siempre,
  // con el mercado cerrado y con datos que nadie volvía a pedir.

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
      {/* En el celular las acciones pueden partirse en dos renglones (max-w-full
          + flex-wrap): con `flex-shrink-0` pelado medían lo que medía su
          contenido y empujaban la página de costado — Reportes medía 555 px en
          una pantalla de 375 (2026-10-02). Desde sm, como siempre. */}
      <div className="flex flex-wrap items-center gap-3 max-w-full sm:flex-shrink-0">
        {meta && typeof meta !== 'string' && meta}
        {meta && typeof meta === 'string' && (
          <span className="inline-flex items-center gap-2 text-[12px] text-ink-2 font-medium">
            {meta}
          </span>
        )}
        {action}
      </div>
    </div>
  )
}
