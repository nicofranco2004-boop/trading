// AIDiscoveryBanner — onboarding chico para descubrir la IA contextual.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint AI v2 — fix del "discovery problem". Aparece una sola vez por user
// (localStorage) en el Dashboard, explica el patrón ✦ y se cierra.
//
// Se complementa con AskAIAbout en "modo prominente" hasta el primer click:
// si el user cierra el banner sin tocar nada, el ✦ queda visible (no solo
// hover) hasta que descubre por su cuenta.

import { useEffect, useState } from 'react'
import { Sparkles, X } from 'lucide-react'
import { track } from '../../utils/track'

export const AI_DISCOVERY_KEY = 'rendi_ai_discovered'

export function isAIDiscovered() {
  try { return localStorage.getItem(AI_DISCOVERY_KEY) === '1' }
  catch { return true }   // si no hay storage, asumimos descubierto
}

export function markAIDiscovered() {
  try {
    localStorage.setItem(AI_DISCOVERY_KEY, '1')
    // Dispatch custom event para que OnboardingChecklist (en Home) y otros
    // listeners reactivos detecten el cambio EN EL MISMO tab. localStorage
    // NO dispara 'storage' event para el tab que escribió — solo cross-tab.
    // Sin esto, el checklist queda con state viejo hasta que el user cambia
    // de tab + vuelve (lo cual dispara `focus`).
    window.dispatchEvent(new Event('ai-discovered'))
  } catch { /* ignore */ }
}

export default function AIDiscoveryBanner() {
  const [visible, setVisible] = useState(false)

  // Mostramos solo si nunca cerró el banner Y nunca usó la feature
  useEffect(() => {
    if (!isAIDiscovered()) {
      setVisible(true)
      track('ai_discovery_banner_shown')
    }
  }, [])

  function dismiss() {
    markAIDiscovered()
    setVisible(false)
    track('ai_discovery_banner_dismissed')
  }

  if (!visible) return null

  return (
    <div
      className="mb-5 flex items-start gap-3 px-4 py-3 rounded-md border border-data-violet/30 bg-data-violet/[0.06]"
      role="region"
      aria-label="Tip sobre la IA contextual"
    >
      <div className="flex-shrink-0 w-8 h-8 rounded-sm bg-data-violet/15 border border-data-violet/30 flex items-center justify-center">
        <Sparkles size={14} strokeWidth={1.75} className="text-data-violet" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[12px] text-data-violet mb-1 font-medium">
          Nuevo · IA contextual
        </div>
        <p className="text-sm text-ink-1 leading-relaxed">
          Cada gráfico y sección de Rendi tiene su propio análisis IA.
          Pasá el mouse sobre cualquier card (o tocá en mobile) y vas a ver
          el botón <Sparkles size={11} strokeWidth={1.75} className="inline mb-0.5 text-data-violet" /> arriba a la derecha. También funciona con doble click.
        </p>
      </div>
      <button
        onClick={dismiss}
        aria-label="Cerrar tip"
        className="flex-shrink-0 text-data-violet/70 hover:text-data-violet p-1 transition-colors"
      >
        <X size={14} strokeWidth={1.75} />
      </button>
    </div>
  )
}
