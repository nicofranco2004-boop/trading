// UpgradePromoCard — card que se muestra en el drawer cuando el user Free
// o Plus llega al cap semanal de IA (análisis o chat).
// ═══════════════════════════════════════════════════════════════════════════
// UX:
//   - Reemplaza el banner de error rojo (que sale por defecto en 429).
//   - Tono explicativo, no agresivo. Muestra cap actual + fecha de reset +
//     beneficios concretos del upgrade.
//   - kind="analyses" o "chat" cambia los labels (de qué se quedó sin cuota).
//   - target_tier del backend define a qué plan upsell: Free→Plus o Plus→Pro.

import { Sparkles, Calendar, Check } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { track } from '../../utils/track'

const DEFAULT_BENEFITS_PRO = [
  '10× más análisis IA (60/sem vs 6/sem)',
  'Chat libre con el Coach IA (40 consultas/sem)',
  'Respuestas con causalidad y memoria persistente',
  'Brokers ilimitados + comportamiento completo',
]

const DEFAULT_BENEFITS_PLUS = [
  '3× más Chat Coach IA (9 consultas/sem vs 3)',
  'Hasta 3 brokers (vs 1 en Free)',
  'Reportes históricos + Export CSV',
  'Métricas de riesgo desbloqueadas + personalización ilimitada del diagnóstico',
]

function fmtReset(iso) {
  if (!iso) return null
  try {
    const d = new Date(iso + 'T00:00:00')
    const dayNum = d.getDate()
    const months = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
                    'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
    const day = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'][d.getDay()]
    return `${day} ${dayNum} ${months[d.getMonth()]}`
  } catch {
    return null
  }
}

const TIER_LABEL = { free: 'Free', plus: 'Plus', pro: 'Pro', advisor: 'Asesor', admin: 'Admin' }

/**
 * @param {object} props
 * @param {object} props.usage - { analyses_count?, analyses_limit?, chat_count?, chat_limit?, resets_on? }
 * @param {object} props.upgrade - { available, current_tier, target_tier, benefits, resets_on? }
 * @param {'analyses'|'chat'} [props.kind='analyses'] - de qué cuota se quedó sin
 * @param {string} [props.source='drawer_429']
 */
export default function UpgradePromoCard({
  usage,
  upgrade,
  kind = 'analyses',
  source = 'drawer_429',
}) {
  const isChat = kind === 'chat'

  // Resolver count/limit según el tipo de cuota agotada
  const count = isChat
    ? (usage?.chat_count ?? '—')
    : (usage?.analyses_count ?? '—')
  const limit = isChat
    ? (usage?.chat_limit ?? '—')
    : (usage?.analyses_limit ?? '—')

  // Resolver tier actual y target del upgrade
  const currentTier = upgrade?.current_tier || 'free'
  const targetTier = upgrade?.target_tier || 'pro'
  const currentLabel = TIER_LABEL[currentTier] || 'Free'
  const targetLabel = TIER_LABEL[targetTier] || 'Pro'

  // Benefits: backend > default según target
  const defaultBenefits = targetTier === 'plus' ? DEFAULT_BENEFITS_PLUS : DEFAULT_BENEFITS_PRO
  const benefits = (upgrade && upgrade.benefits && upgrade.benefits.length > 0)
    ? upgrade.benefits
    : defaultBenefits

  const resetsOn = upgrade?.resets_on || usage?.resets_on
  const resetLabel = fmtReset(resetsOn)
  const resourceLabel = isChat ? 'consultas al Coach IA' : 'análisis'
  const resourceShort = isChat ? 'consulta' : 'análisis'

  const navigate = useNavigate()

  function onUpgradeClick() {
    track('upgrade_promo_clicked', { source, kind, current_tier: currentTier, target_tier: targetTier })
    navigate('/planes')
  }

  return (
    <div className="border border-data-violet/30 bg-data-violet/[0.05] rounded-sm p-5 space-y-4">
      {/* Header */}
      <div className="flex items-start gap-2">
        <Sparkles size={14} strokeWidth={1.75} className="text-data-violet mt-0.5 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-[12px] text-data-violet leading-none mb-1 font-medium">
            Llegaste al límite del plan {currentLabel}
          </p>
          <h3 className="text-sm font-medium text-ink-0 leading-snug">
            Usaste {count} de {limit} {resourceLabel} esta semana
          </h3>
        </div>
      </div>

      {/* Reset info */}
      {resetLabel && (
        <div className="flex items-center gap-1.5 text-xs text-ink-2">
          <Calendar size={11} strokeWidth={1.75} className="text-ink-3" />
          <span>Tu próxima {resourceShort} se libera el <span className="text-ink-0">{resetLabel}</span>.</span>
        </div>
      )}

      {/* Pitch al target tier */}
      <div className="pt-3 border-t border-line/40 space-y-2.5">
        <p className="text-xs text-ink-2">
          Para más cuota{isChat ? ' y chat libre sin restricción' : ' y respuestas más profundas'}, pasate a <span className="text-data-violet font-medium">Rendi {targetLabel}</span>:
        </p>
        <ul className="space-y-1.5">
          {benefits.map((b, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-ink-1">
              <Check size={11} strokeWidth={2} className="text-data-violet mt-0.5 flex-shrink-0" />
              <span className="leading-snug">{b}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* CTA */}
      <button
        onClick={onUpgradeClick}
        className="w-full inline-flex items-center justify-center gap-1.5 text-xs font-medium bg-data-violet/15 hover:bg-data-violet/25 text-data-violet border border-data-violet/40 rounded-sm py-2.5 transition-colors"
      >
        <Sparkles size={12} strokeWidth={1.75} />
        Ver planes y mejorar
      </button>
    </div>
  )
}
