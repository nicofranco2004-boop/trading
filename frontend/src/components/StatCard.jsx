// StatCard — el componente más visible del producto.
// ═══════════════════════════════════════════════════════════════════════════
// Tres tonos de jerarquía:
//   tone="hero"      → hero único de la pantalla. Instrument Serif italic.
//                       Solo 1 por página (Valor actual del Dashboard).
//   tone="primary"   → métrica importante con tratamiento de card.
//                       Para cards secundarias del hero (Capital aportado,
//                       Resultado total).
//   tone="cell"      → KPI cell sin caja, con divisor 1px a la izquierda.
//                       Para tiras densas de KPIs (P&L Realizado, No Realizado,
//                       Win rate, Mejor operación).
//   tone="secondary" → fallback compatible con uso anterior. Card simple.
//
// API (no cambia respecto a la versión anterior):
//   label        → string (label uppercase mono pequeño arriba)
//   value        → string | number (la cifra principal)
//   sub          → string | ReactNode (subtítulo opcional debajo)
//   hint         → string (texto adicional gris pequeño abajo)
//   positive     → bool | null (colorea valor: rendi-pos | rendi-neg | neutro)
//   pnlPositive  → bool | null (colorea solo el segmento "P&L: ..." de sub)
//   tone         → 'hero' | 'primary' | 'cell' | 'secondary' (default)
//   icon         → ReactNode (chip de icono a la derecha del label)
//   tooltip      → ReactNode (despliega ⓘ con explicación al hover)
//
// Reglas semánticas (audit visual mayo 2026):
// • rendi-pos solo aparece cuando positive=true y la cifra es la métrica
//   principal del bloque. Nunca decorativo.
// • Labels en mono uppercase pequeño + tracking amplio.
// • Valores numéricos con tabular-nums para que no salten al actualizar.

import InfoTooltip from './InfoTooltip'

export default function StatCard({
  label,
  value,
  sub,
  hint,
  positive,
  pnlPositive,
  tone = 'secondary',
  icon,
  tooltip,
}) {
  const isHero = tone === 'hero'
  const isPrimary = tone === 'primary'
  const isCell = tone === 'cell'

  // Color del valor según semántica financiera
  const valueColor =
    positive == null
      ? 'text-ink-0'
      : positive
      ? 'text-rendi-pos'
      : 'text-rendi-neg'

  const subPnlColor =
    pnlPositive == null
      ? ''
      : pnlPositive
      ? 'text-rendi-pos'
      : 'text-rendi-neg'

  // Split "P&L:" segment for color (compat con uso anterior)
  let subNode = sub
  if (sub && pnlPositive != null && typeof sub === 'string' && sub.includes('P&L:')) {
    const [before, after] = sub.split('P&L:')
    subNode = (
      <span>
        {before}
        <span className={subPnlColor}>P&L: {after}</span>
      </span>
    )
  }

  // ─── Container según tono ───────────────────────────────────────────────
  const containerCls = isHero
    ? 'py-2 sm:py-3'  // hero no tiene caja, solo padding mínimo
    : isCell
    ? 'kpi-cell py-2'  // cell con divisor 1px vertical, sin caja
    : isPrimary
    ? 'bg-bg-1 border border-line rounded-xl p-5 sm:p-6'  // card grande sutil
    : 'bg-bg-1 border border-line rounded-xl p-3 sm:p-4'  // card chica (legacy)

  // ─── Label común a todos los tonos ──────────────────────────────────────
  const labelCls = 'label-mono mb-1.5'

  // ─── Valor según tono ───────────────────────────────────────────────────
  const valueCls = isHero
    ? `hero-number ${valueColor}`
    : isCell
    ? `data-hero ${valueColor} mt-1`
    : isPrimary
    ? `font-sans font-medium num text-2xl sm:text-3xl ${valueColor} tracking-tight`
    : `font-sans font-medium num text-lg sm:text-2xl ${valueColor} break-words`

  // ─── Sub debajo del valor ───────────────────────────────────────────────
  const subCls = isHero
    ? 'mt-3 text-sm text-ink-2'
    : isCell
    ? 'mt-1 text-[11px] font-mono text-ink-3'
    : 'mt-1 text-[11px] sm:text-xs text-ink-2 truncate'

  return (
    <div className={containerCls}>
      <div className="flex items-center gap-2 justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          <p className={labelCls}>{label}</p>
          {tooltip && <InfoTooltip>{tooltip}</InfoTooltip>}
        </div>
        {icon && <span className="text-ink-3 flex-shrink-0">{icon}</span>}
      </div>
      <p className={valueCls}>{value}</p>
      {sub && <p className={subCls}>{subNode}</p>}
      {hint && (
        <p className="mt-1.5 text-[11px] text-ink-3 font-mono">{hint}</p>
      )}
    </div>
  )
}
