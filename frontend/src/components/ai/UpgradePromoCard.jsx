// UpgradePromoCard — card que se muestra en el drawer cuando el user Free
// llega al cap semanal de análisis.
// ═══════════════════════════════════════════════════════════════════════════
// UX:
//   - Reemplaza el banner de error rojo (que sale por defecto en 429).
//   - Tono explicativo, no agresivo. Muestra cap actual + fecha de reset +
//     beneficios concretos del upgrade.
//   - El CTA (por ahora) trackea el intent y vuelve a la app — el flujo de
//     pago real se conecta cuando exista.

import { Sparkles, Calendar, Check } from 'lucide-react'
import { track } from '../../utils/track'

const DEFAULT_BENEFITS = [
  'Análisis ilimitados',
  'Respuestas profundas con causalidad y comparaciones',
  'Un insight memorable por análisis',
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

export default function UpgradePromoCard({
  usage,
  upgrade,
  source = 'drawer_429',
}) {
  const benefits = (upgrade && upgrade.benefits && upgrade.benefits.length > 0)
    ? upgrade.benefits
    : DEFAULT_BENEFITS
  const resetsOn = upgrade?.resets_on || usage?.resets_on
  const resetLabel = fmtReset(resetsOn)
  const count = usage?.analyses_count ?? '—'
  const limit = usage?.analyses_limit ?? '—'

  function onUpgradeClick() {
    track('upgrade_promo_clicked', { source })
    // TODO: cuando exista el flujo de checkout, redirigir.
    // Por ahora abrimos un mailto / waitlist o solo trackeamos.
  }

  return (
    <div className="border border-data-violet/30 bg-data-violet/[0.05] rounded-sm p-5 space-y-4">
      {/* Header */}
      <div className="flex items-start gap-2">
        <Sparkles size={14} strokeWidth={1.75} className="text-data-violet mt-0.5 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-mono uppercase tracking-caps text-data-violet leading-none mb-1">
            Llegaste al límite semanal
          </p>
          <h3 className="text-sm font-medium text-ink-0 leading-snug">
            Usaste {count} de {limit} análisis del plan Free
          </h3>
        </div>
      </div>

      {/* Reset info */}
      {resetLabel && (
        <div className="flex items-center gap-1.5 text-xs text-ink-2">
          <Calendar size={11} strokeWidth={1.75} className="text-ink-3" />
          <span>Tu cuota se renueva el <span className="text-ink-0">{resetLabel}</span>.</span>
        </div>
      )}

      {/* Pro pitch */}
      <div className="pt-3 border-t border-line/40 space-y-2.5">
        <p className="text-xs text-ink-2">
          Para uso ilimitado con respuestas más profundas, pasate a <span className="text-data-violet font-medium">Rendi Pro</span>:
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
        Conocer Rendi Pro
      </button>

      <p className="text-[10px] text-ink-3 text-center">
        Pro está en desarrollo — te avisamos cuando esté listo.
      </p>
    </div>
  )
}
