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
  'Chat libre con Rendi AI (40 consultas/sem)',
  'Respuestas con causalidad y memoria persistente',
  'Brokers ilimitados + comportamiento completo',
]

const DEFAULT_BENEFITS_PLUS = [
  '9× más Chat Rendi AI (9 consultas/sem vs 1)',
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
 * ¿De qué cupo se quedó sin: del de análisis (el botón ✦) o del de consultas?
 *
 * 🔴 NO se puede escribir a mano en la superficie. Por el chat pasan LOS DOS
 * cupos, así que `kind="chat"` fijo hacía que a alguien sin ANÁLISIS la tarjeta
 * le dijera "Usaste 0 de 1 consultas al Coach IA": el sustantivo equivocado y
 * un número que se contradice con el título. Pasó en producción (2026-09-16).
 *
 * Orden: lo que dice el backend manda. Si no lo dice —un backend más viejo que
 * este bundle, o un 429 armado en otro lado— se DEDUCE de los contadores: el
 * cupo que quedó en cero es el que frenó. Sólo si los dos están en cero (o
 * ninguno) se usa `porDefecto`, que es el contexto de la pantalla.
 */
export function kindDeCuota(usage, kindDelBackend, porDefecto = 'chat') {
  if (kindDelBackend === 'chat' || kindDelBackend === 'analyses') return kindDelBackend
  const sinAnalisis = usage?.analyses_remaining === 0
  const sinChat = usage?.chat_remaining === 0
  if (sinAnalisis && !sinChat) return 'analyses'
  if (sinChat && !sinAnalisis) return 'chat'
  return porDefecto
}

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
  codigo = null,
  mensaje = null,
  source = 'drawer_429',
}) {
  const isChat = kind === 'chat'
  // 🔴 NO todo lo que muestra esta tarjeta es una cuota agotada.
  //
  // El 403 'free_chat_not_allowed' es otra cosa: la pregunta libre no está en
  // el plan. No hay contador que se haya llenado. Como la tarjeta PISA el
  // banner de error, mostrarla con el layout de cuota le decía a un Free
  // "Llegaste al límite · Usaste 0 de 1 consultas" —un número que no frenó
  // nada— y de paso escondía el único texto útil, el que le dice qué SÍ puede
  // hacer (elegir una guiada, o registrar una operación). Producción 2026-09-16.
  const esBloqueoDePlan = codigo === 'free_chat_not_allowed'

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
  const resourceLabel = isChat ? 'consultas a Rendi AI' : 'análisis'
  // La frase ENTERA, no sólo el sustantivo: "Tu próxima {análisis}" concuerda
  // mal en castellano, y así se le mostró a todo el que se quedó sin análisis.
  // El backend ya la arma completa (_chat_quota_429); acá estaba partida.
  const proximaSeLibera = isChat
    ? 'Tu próxima consulta se libera'
    : 'Tu próximo análisis se libera'

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
            {esBloqueoDePlan
              ? `No llegaste a ningún límite`
              : `Llegaste al límite del plan ${currentLabel}`}
          </p>
          <h3 className="text-sm font-medium text-ink-0 leading-snug">
            {esBloqueoDePlan
              ? `Las preguntas libres son del plan ${targetLabel}`
              : `Usaste ${count} de ${limit} ${resourceLabel} esta semana`}
          </h3>
        </div>
      </div>

      {/* Qué SÍ puede hacer ahora mismo. El texto viene del backend: es el
          mismo que la tarjeta estaba tapando. No se reescribe acá — dos copias
          del mismo cartel se despegan a la primera edición. */}
      {esBloqueoDePlan && mensaje && (
        <p className="text-xs text-ink-2 leading-relaxed">{mensaje}</p>
      )}

      {/* Reset info — sólo si hay un contador que se renueve. */}
      {!esBloqueoDePlan && resetLabel && (
        <div className="flex items-center gap-1.5 text-xs text-ink-2">
          <Calendar size={11} strokeWidth={1.75} className="text-ink-3" />
          <span>{proximaSeLibera} el <span className="text-ink-0">{resetLabel}</span>.</span>
        </div>
      )}

      {/* Pitch al target tier */}
      <div className="pt-3 border-t border-line/40 space-y-2.5">
        <p className="text-xs text-ink-2">
          {esBloqueoDePlan ? 'Con' : `Para más cuota${isChat ? ' y chat libre sin restricción' : ' y respuestas más profundas'}, pasate a`} <span className="text-data-violet font-medium">Rendi {targetLabel}</span>:
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
