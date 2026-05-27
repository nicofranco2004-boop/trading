// LockedSection — placeholder reutilizable para features Pro-only.
// ═══════════════════════════════════════════════════════════════════════════
// 3 variantes según el caso:
//
//   <LockedSection.Placeholder ... />     ← Card completa bloqueada (Tipo B)
//                                            ej: Distribución por activo
//
//   <LockedSection.BlurredList items={hiddenItems} ... />
//                                          ← Lista con items blureados al final (Tipo A)
//                                            ej: Comportamiento, Insights diagnóstico
//
//   <LockedSection.Card variant="last_unlocked" ... />
//                                          ← Item locked en una lista existente (Tipo B')
//                                            ej: meses históricos en Reportes
//
// Todas trackean `feature_blocked_clicked` cuando el user clickea el CTA
// (telemetría para Fase 3 — entender qué features generan más conversiones).

import { Lock, Sparkles, ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { track } from '../../utils/track'

// Hook helper para que cada variante use navigate sin duplicar boilerplate.
function useGoToPlanes() {
  const navigate = useNavigate()
  return (feature, source) => {
    track('feature_blocked_clicked', { feature, source: source || 'unknown' })
    navigate('/planes')
  }
}

// ── Variante A: Placeholder full-card ────────────────────────────────────────
// Card que reemplaza totalmente a la feature original. La describe pero
// sin mostrar la data. CTA grande para upgrade.
//
// `targetTier`: 'plus' | 'pro' (default 'pro'). Cambia el copy del CTA y la
// paleta. Features Plus-tier (Volatilidad, Beta) usan acento cyan; features
// Pro (Sharpe, Sortino, Alpha, IR) mantienen el violet histórico.
function Placeholder({
  feature,
  title,
  description,
  source,
  icon: Icon = Sparkles,
  className = '',
  targetTier = 'pro',
}) {
  const go = useGoToPlanes()
  const tier = targetTier === 'plus' ? 'plus' : 'pro'
  const tierLabel = tier === 'plus' ? 'Plus' : 'Pro'
  // Paleta condicional según target tier. Plus = cyan (acento secundario),
  // Pro = violet (acento principal de upsell).
  const styles = tier === 'plus'
    ? {
        wrap: 'border-data-cyan/30 bg-data-cyan/[0.05]',
        iconBg: 'bg-data-cyan/15',
        iconText: 'text-data-cyan',
        cta: 'bg-data-cyan/15 hover:bg-data-cyan/25 text-data-cyan border-data-cyan/40',
      }
    : {
        wrap: 'border-data-violet/30 bg-data-violet/[0.04]',
        iconBg: 'bg-data-violet/15',
        iconText: 'text-data-violet',
        cta: 'bg-data-violet/15 hover:bg-data-violet/25 text-data-violet border-data-violet/40',
      }
  return (
    <div className={`relative border rounded p-6 text-center ${styles.wrap} ${className}`}>
      <div className={`inline-flex items-center justify-center w-10 h-10 rounded-full mb-3 ${styles.iconBg}`}>
        <Icon size={18} strokeWidth={1.75} className={styles.iconText} />
      </div>
      <h3 className="text-base font-medium text-ink-0 mb-1.5">{title}</h3>
      <p className="text-sm text-ink-2 leading-relaxed max-w-md mx-auto mb-4">
        {description}
      </p>
      <button
        type="button"
        onClick={() => go(feature, source)}
        className={`inline-flex items-center gap-1.5 text-sm font-medium border rounded-sm px-4 py-2 transition-colors ${styles.cta}`}
      >
        <Sparkles size={13} strokeWidth={1.75} />
        Desbloquear con Rendi {tierLabel}
      </button>
    </div>
  )
}

// ── Variante B: Lista con items blureados al final ──────────────────────────
// Muestra el primer slot (o slots) visible y al final un bloque blureado
// con count de items ocultos + CTA upgrade.
// `hiddenCount` o `children` permiten controlar el contenido blureado.
function BlurredList({
  feature,
  hiddenCount,
  noun = 'observaciones',
  source,
  children,
  className = '',
}) {
  const go = useGoToPlanes()
  return (
    <div className={`relative ${className}`}>
      {children && (
        <div
          aria-hidden
          className="select-none pointer-events-none filter blur-sm opacity-60"
        >
          {children}
        </div>
      )}
      <div
        className={`${children ? 'mt-3' : ''} border border-data-violet/30 bg-data-violet/[0.04] rounded p-4 text-center`}
      >
        <div className="inline-flex items-center justify-center gap-2 mb-2">
          <Lock size={14} strokeWidth={1.75} className="text-data-violet" />
          <p className="text-sm font-medium text-ink-0">
            {hiddenCount > 0
              ? `Desbloqueá ${hiddenCount} ${hiddenCount === 1 ? noun.replace(/s$/, '') : noun} más con Rendi Pro`
              : `Más ${noun} disponibles en Rendi Pro`}
          </p>
        </div>
        <p className="text-xs text-ink-2 mb-3 max-w-sm mx-auto">
          Análisis completo con causalidad, comparaciones y observaciones priorizadas.
        </p>
        <button
          type="button"
          onClick={() => go(feature, source)}
          className="inline-flex items-center gap-1.5 text-xs font-medium bg-data-violet/15 hover:bg-data-violet/25 text-data-violet border border-data-violet/40 rounded-sm px-3 py-1.5 transition-colors"
        >
          <Sparkles size={11} strokeWidth={1.75} />
          Ver planes
        </button>
      </div>
    </div>
  )
}

// ── Variante C: Card individual locked (para listas) ─────────────────────────
// Card chiquita que se renderea como item bloqueado en una lista de items.
// Ej: en Reportes, cada mes anterior al último.
function Card({
  feature,
  title,
  subtitle,
  source,
  className = '',
}) {
  const go = useGoToPlanes()
  return (
    <button
      type="button"
      onClick={() => go(feature, source)}
      className={`relative w-full text-left border border-data-violet/25 bg-data-violet/[0.03] hover:bg-data-violet/[0.06] hover:border-data-violet/40 rounded p-4 transition-colors group ${className}`}
    >
      <div className="flex items-start gap-3">
        <div className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-data-violet/15 flex-shrink-0 mt-0.5">
          <Lock size={12} strokeWidth={1.75} className="text-data-violet" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-ink-1 group-hover:text-ink-0 leading-snug truncate">
            {title}
          </p>
          {subtitle && (
            <p className="text-xs text-ink-3 mt-0.5 leading-snug">{subtitle}</p>
          )}
        </div>
        <ArrowRight size={13} strokeWidth={1.75} className="text-data-violet flex-shrink-0 mt-1 opacity-60 group-hover:opacity-100" />
      </div>
    </button>
  )
}

export default {
  Placeholder,
  BlurredList,
  Card,
}
