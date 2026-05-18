// UpgradeModal — modal de upgrade que se abre cuando el user toca un
// gate (ej. agregar broker n°2 en Free).
// ═══════════════════════════════════════════════════════════════════════════
// Recibe el payload del 403 del backend (con quota + upgrade) y muestra el
// CTA + beneficios.

import { Sparkles, Check, X } from 'lucide-react'
import { track } from '../../utils/track'

const DEFAULT_BENEFITS = [
  'Brokers ilimitados',
  '10× más análisis IA (60/sem vs 6/sem)',
  'Comportamiento completo (todas las tags)',
  'Reportes históricos + Distribución por activo',
]

export default function UpgradeModal({
  title = 'Pasate a Rendi Pro',
  message,
  feature,
  source = 'upgrade_modal',
  benefits,
  onClose,
}) {
  const items = (benefits && benefits.length > 0) ? benefits : DEFAULT_BENEFITS

  function onUpgradeClick() {
    track('upgrade_modal_cta_clicked', { feature, source })
    // TODO: cuando exista checkout, redirigir.
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-bg-1 border border-line rounded-t-lg sm:rounded-lg w-full max-w-md p-5 shadow-xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-data-violet/15">
              <Sparkles size={15} strokeWidth={1.75} className="text-data-violet" />
            </div>
            <h2 className="text-base font-semibold text-ink-0">{title}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-sm text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition-colors"
            aria-label="Cerrar"
          >
            <X size={15} strokeWidth={1.75} />
          </button>
        </div>

        {message && (
          <p className="text-sm text-ink-2 leading-relaxed mb-4">{message}</p>
        )}

        <ul className="space-y-2 mb-5">
          {items.map((b, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-ink-1">
              <Check size={12} strokeWidth={2} className="text-data-violet mt-1 flex-shrink-0" />
              <span className="leading-snug">{b}</span>
            </li>
          ))}
        </ul>

        <button
          type="button"
          onClick={onUpgradeClick}
          className="w-full inline-flex items-center justify-center gap-1.5 text-sm font-medium bg-data-violet/15 hover:bg-data-violet/25 text-data-violet border border-data-violet/40 rounded-sm py-2.5 transition-colors"
        >
          <Sparkles size={13} strokeWidth={1.75} />
          Conocer Rendi Pro
        </button>
        <p className="mt-2 text-[10px] text-ink-3 text-center">
          Pro está en desarrollo — te avisamos cuando esté listo.
        </p>
      </div>
    </div>
  )
}
