// Panel — átomo de superficie unificado (V2).
// ═══════════════════════════════════════════════════════════════════════════
// Reemplaza Card. Filosofía v2:
//   • bg-bg-1 (charcoal cold) en lugar de bg-white/bg-bg-2
//   • Borde más sutil (line, no slate-200/800)
//   • Radius = rounded-xl (12px). Es EL radio de superficie del sistema nuevo;
//     el mismo que usan las cards del Plan Asesor. Ver frontend/CLAUDE.md R5.
//   • Sin shadows, sin backdrop-blur, sin gradient
//   • Padding alineado a spacing scale 4-8-12-16-24-32
//
// API:
//   children   → contenido
//   className  → clases extras
//   padding    → 'none' | 'sm' (p-3) | 'md' (p-4, default) | 'lg' (p-5)
//   as         → 'div' (default), 'section', etc.
//   hoverable  → bool, hover sutil de border (Linear-style)
//   accent     → bool, border en signal verde (para KPI principal o estado live)
//   elevated   → bool, bg-bg-raised (la superficie que flota: modales,
//                menús, globos). En oscuro vale lo mismo que bg-2 valía; en
//                claro se queda blanco y la sombra hace la elevación.

export default function Panel({
  children,
  className = '',
  padding = 'md',
  as = 'div',
  hoverable = false,
  accent = false,
  elevated = false,
  ...rest
}) {
  const Tag = as
  const padClass =
    padding === 'none' ? '' :
    padding === 'sm'   ? 'p-3' :
    padding === 'lg'   ? 'p-5' :
                         'p-4'

  const bg = elevated ? 'bg-bg-raised' : 'bg-bg-1'
  const borderClass = accent
    ? 'border border-rendi-pos/40'
    : 'border border-line'
  const hover = hoverable
    ? 'transition-colors hover:border-line-2'
    : ''

  // Lo elevado necesita sombra en claro: ahí `bg-raised` es blanco y el panel
  // de abajo también, así que sin sombra no habría nada que los separe. En
  // oscuro la variable vale `none` — el sistema eleva aclarando, no con sombra.
  //
  // Va por estilo y NO como `shadow-[var(--shadow-raised)]`: esa clase compila,
  // pero Tailwind toma el valor arbitrario como COLOR de sombra y emite
  // `--tw-shadow-color` en vez de la sombra — o sea, no pinta nada y no avisa.
  // Se ve en el CSS compilado, no en los tests.
  const { style: styleDelLlamador, ...resto } = rest
  const style = elevated
    ? { boxShadow: 'var(--shadow-raised)', ...styleDelLlamador }
    : styleDelLlamador

  return (
    <Tag
      className={`${bg} ${borderClass} rounded-xl ${padClass} ${hover} ${className}`}
      style={style}
      {...resto}
    >
      {children}
    </Tag>
  )
}

// PanelHeader — header estándar dentro de cualquier Panel.
// API estable con la vieja CardHeader. Tipografía v2 (uppercase tracking + mono eyebrow).
export function PanelHeader({ title, subtitle, action, icon, eyebrow }) {
  return (
    <div className="flex items-start justify-between gap-3 mb-3">
      <div className="min-w-0 flex items-start gap-2">
        {icon && (
          <span className="mt-0.5 text-ink-3 flex-shrink-0">{icon}</span>
        )}
        <div className="min-w-0">
          {eyebrow && (
            <p className="text-[12px] font-medium text-ink-2 mb-0.5">
              {eyebrow}
            </p>
          )}
          <h2 className="text-[15px] font-semibold text-ink-0 leading-tight">
            {title}
          </h2>
          {subtitle && (
            <p className="text-[12.5px] text-ink-3 mt-0.5 leading-snug">
              {subtitle}
            </p>
          )}
        </div>
      </div>
      {action && <div className="flex-shrink-0">{action}</div>}
    </div>
  )
}
