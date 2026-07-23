// ModuleShell — card contenedora de un módulo del Tablero del perfil.
// ═══════════════════════════════════════════════════════════════════════════
// Header (ícono + título + badge de relevancia) + body. Dos estados:
//   • avail  → children (la visualización del módulo).
//   • locked → candado + mensaje de desbloqueo + CTA (test / posiciones),
//              derivado del texto del lock (el motor manda el mensaje).
// El badge: el PRIMER módulo disponible del grid lleva "★ Lo más relevante";
// el resto muestra su score REL — así el orden deja de ser una caja negra.

import { Lock } from 'lucide-react'
import { Link } from 'react-router-dom'

export default function ModuleShell({ icon: Icon, title, rel, topPick = false, lock = null, wide = false, children }) {
  const locked = !!lock
  // CTA del lock según a dónde apunta el desbloqueo.
  const lockCta = locked
    ? /test|respond/i.test(lock)
      ? { to: '/config?tab=test', label: 'Completar test →' }
      : /posicion|cargá/i.test(lock)
        ? { to: '/posiciones', label: 'Cargar posiciones →' }
        : null
    : null

  return (
    <section
      className={`border border-line/70 dark:border-line rounded-lg bg-white/40 dark:bg-bg-1/40 p-4 flex flex-col gap-3 ${wide ? 'md:col-span-2' : ''} ${locked ? 'opacity-80' : ''}`}
    >
      {/* pr-9: deja lugar al pill ✦ de AskAIAbout (absolute top-2 right-2)
          para que no tape el badge REL/★, sobre todo en mobile donde el pill
          es siempre visible. */}
      <header className="flex items-center justify-between gap-2 pr-9">
        <div className="flex items-center gap-2 min-w-0">
          {Icon && <Icon size={14} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" aria-hidden />}
          <h4 className="text-sm font-semibold text-ink-0 truncate">{title}</h4>
        </div>
        {topPick ? (
          <span className="flex-shrink-0 text-[12.5px] font-semibold text-data-violet bg-data-violet/12 border border-data-violet/30 rounded-full px-2 py-1">
            ★ Lo más relevante
          </span>
        ) : rel != null ? (
          <span className="flex-shrink-0 text-[12.5px] text-ink-3 bg-bg-2/60 rounded-full px-2 py-1 font-medium">
            rel {rel}
          </span>
        ) : null}
      </header>

      {locked ? (
        <div className="flex-1 flex flex-col items-start gap-2 py-3">
          <div className="flex items-center gap-1.5 text-ink-3">
            <Lock size={13} strokeWidth={1.75} aria-hidden />
            <span className="text-[12.5px] font-medium">Bloqueado</span>
          </div>
          <p className="text-xs text-ink-2 leading-relaxed">{lock}</p>
          {lockCta && (
            <Link to={lockCta.to} className="text-xs font-medium text-data-violet hover:underline">
              {lockCta.label}
            </Link>
          )}
        </div>
      ) : (
        <div className="flex-1 min-w-0">{children}</div>
      )}
    </section>
  )
}
