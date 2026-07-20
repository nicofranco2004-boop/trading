// ProfileSummaryBlock — lectura IA personalizada del perfil (topic profile.summary).
// ═══════════════════════════════════════════════════════════════════════════
// Bloque INLINE (no drawer) que vive arriba de las cards del cruce en
// Análisis › Perfil. Genera on-click (autoload:false), cachea 24h y descuenta
// del cupo semanal — reusa TODA la infra de /api/ai/analyze (useAIAnalysis).
//
// La IA va ARRIBA de los hechos: los números (las cards) los calcula el
// backend determinístico; acá la IA solo arma la lectura a medida. Free/Plus
// reciben el modo descriptivo, Pro el causal (lo resuelve el prompt por tier).

import { Sparkles, Loader2, RefreshCw } from 'lucide-react'
import { useAIAnalysis } from '../../hooks/useAIAnalysis'
import { useAuth } from '../../contexts/AuthContext'
import AnalysisCard from './AnalysisCard'
import UpgradePromoCard from './UpgradePromoCard'

const VIOLET_BORDER = 'rgba(139,125,255,.32)'
const VIOLET_BG = 'linear-gradient(180deg, rgba(139,125,255,.07), rgba(139,125,255,.025))'

export default function ProfileSummaryBlock({ className = '' }) {
  const { user } = useAuth()
  const { result, loading, error, upgrade, usage, tier, analyze, refresh } =
    useAIAnalysis({ screen: 'profile.summary', autoload: false })

  // Antes de generar no sabemos qué tier usó el backend → usamos el del auth
  // como default (evita mostrar "Free" a un Pro). El del hook lo pisa después.
  const effectiveTier = tier || user?.tier
  const tierLabel =
    effectiveTier === 'pro' || effectiveTier === 'admin'
      ? 'Pro'
      : effectiveTier === 'plus'
        ? 'Plus'
        : 'Free'
  const count = usage?.analyses_count
  const limit = usage?.analyses_limit
  // 429 (cupo agotado) trae upgrade.available → card promocional en vez de
  // banner rojo, igual que AnalysisDrawer.
  const showUpgradeCard = !!(upgrade && upgrade.available)

  return (
    <section
      className={`border rounded-lg overflow-hidden mb-5 ${className}`}
      style={{ borderColor: VIOLET_BORDER, background: VIOLET_BG }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between gap-3 px-4 py-3 border-b"
        style={{ borderColor: 'rgba(139,125,255,.15)' }}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <span
            className="w-6 h-6 rounded-md grid place-items-center flex-shrink-0"
            style={{ background: 'rgba(139,125,255,.16)' }}
          >
            <Sparkles size={13} strokeWidth={1.9} className="text-data-violet" />
          </span>
          <div className="min-w-0">
            <div className="text-[12.5px] text-data-violet font-semibold leading-none">
              Lectura IA · {tierLabel}
            </div>
            <h3 className="text-sm font-semibold text-ink-0 leading-tight mt-0.5">
              Tu lectura personalizada
            </h3>
          </div>
        </div>
        {result && !loading && (
          <button
            onClick={refresh}
            className="inline-flex items-center gap-1.5 text-xs text-ink-2 hover:text-ink-0 bg-bg-2/50 hover:bg-bg-2 border border-line-2/60 rounded-sm px-2.5 py-1.5 transition-colors flex-shrink-0"
          >
            <RefreshCw size={12} strokeWidth={1.75} /> Regenerar
          </button>
        )}
      </div>

      {/* Body por estado. Upgrade (429) y error se renderizan INDEPENDIENTES
          del result — si el user regenera y se queda sin cupo, el 429 no borra
          el result viejo (useAIAnalysis no limpia result en error), así que un
          ternario result-primero se comería la UpgradePromoCard. Mismo patrón
          que AnalysisDrawer: card de upgrade / error arriba, result debajo. */}
      <div className="p-4 space-y-4">
        {showUpgradeCard && !loading && (
          <UpgradePromoCard usage={usage} upgrade={upgrade} source="profile_summary_429" />
        )}
        {error && !loading && !showUpgradeCard && (
          <div className="space-y-2">
            <p className="text-sm text-ink-1 leading-snug">
              {typeof error === 'string' ? error : 'No pudimos generar el análisis.'}
            </p>
            <button onClick={analyze} className="text-xs text-data-violet hover:underline">
              Reintentar
            </button>
          </div>
        )}

        {loading ? (
          <div className="flex items-center gap-3 py-6 justify-center text-ink-2">
            <Loader2 size={18} className="animate-spin text-data-violet" strokeWidth={1.75} />
            <span className="text-sm">Analizando tu perfil vs tu cartera…</span>
          </div>
        ) : result ? (
          <AnalysisCard result={result} hideFollowUps />
        ) : showUpgradeCard || error ? null : (
          // Estado inicial (sin generar) — CTA
          <div className="text-center py-4">
            <div
              className="w-10 h-10 rounded-xl grid place-items-center mx-auto mb-3"
              style={{ background: 'rgba(139,125,255,.14)' }}
            >
              <Sparkles size={19} strokeWidth={1.7} className="text-data-violet" />
            </div>
            <h4 className="text-sm font-semibold text-ink-0 mb-1">Analizá tu perfil con la IA</h4>
            <p className="text-xs text-ink-2 max-w-md mx-auto mb-4 leading-relaxed">
              El Coach lee tu test y tu cartera real, y arma una lectura a medida: qué importa
              para vos y por qué. Se genera cuando la pedís y queda cacheada unas horas.
            </p>
            <button
              onClick={analyze}
              className="inline-flex items-center gap-2 text-sm font-medium bg-data-violet hover:bg-data-violet/90 text-white border border-data-violet rounded-sm px-4 py-2.5 transition-colors press"
            >
              <Sparkles size={14} strokeWidth={1.75} /> Analizar mi perfil
            </button>
            <div className="mt-3 font-mono text-[10px] text-ink-3">
              {count != null && limit != null
                ? `Análisis IA · usaste ${count}/${limit} esta semana`
                : 'Usa 1 de tus análisis IA de la semana'}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
