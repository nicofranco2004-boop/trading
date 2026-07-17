// DiagnosticoSummaryBlock — lectura IA personalizada del Diagnóstico.
// ═══════════════════════════════════════════════════════════════════════════
// Gemelo de ProfileSummaryBlock pero para el tab Diagnóstico (topic
// insights.summary). Bloque INLINE arriba del tablero: la IA sintetiza el
// diagnóstico de la cartera en UNA lectura conectada. Genera on-click
// (autoload:false), cachea, descuenta cupo — reusa la infra /api/ai/analyze.
//
// Le pasa al backend, como params, lo que el frontend YA computó y muestra
// (archetype + findings + verdicts + flags de calidad) para que la lectura NO
// contradiga las cards de abajo (la lección de profile.summary). El backend
// recompute la valuación server-side canónica; el TWR fantasma nunca entra.

import { Sparkles, Loader2, RefreshCw } from 'lucide-react'
import { useAIAnalysis } from '../../hooks/useAIAnalysis'
import { useAuth } from '../../contexts/AuthContext'
import AnalysisCard from '../ai/AnalysisCard'
import UpgradePromoCard from '../ai/UpgradePromoCard'

const VIOLET_BORDER = 'rgba(139,125,255,.32)'
const VIOLET_BG = 'linear-gradient(180deg, rgba(139,125,255,.07), rgba(139,125,255,.025))'

export default function DiagnosticoSummaryBlock({ params = {}, className = '' }) {
  const { user } = useAuth()
  const { result, loading, error, upgrade, usage, tier, analyze, refresh } =
    useAIAnalysis({ screen: 'insights.summary', params, autoload: false })

  const effectiveTier = tier || user?.tier
  const tierLabel =
    effectiveTier === 'pro' || effectiveTier === 'admin'
      ? 'Pro'
      : effectiveTier === 'plus'
        ? 'Plus'
        : 'Free'
  const count = usage?.analyses_count
  const limit = usage?.analyses_limit
  const showUpgradeCard = !!(upgrade && upgrade.available)

  return (
    <section
      className={`border rounded-lg overflow-hidden mb-5 ${className}`}
      style={{ borderColor: VIOLET_BORDER, background: VIOLET_BG }}
    >
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
            <div className="font-mono text-[9.5px] uppercase tracking-caps text-data-violet font-semibold leading-none">
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

      <div className="p-4 space-y-4">
        {showUpgradeCard && !loading && (
          <UpgradePromoCard usage={usage} upgrade={upgrade} source="insights_summary_429" />
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
            <span className="text-sm">Analizando tu cartera…</span>
          </div>
        ) : result ? (
          <AnalysisCard result={result} hideFollowUps />
        ) : showUpgradeCard || error ? null : (
          <div className="text-center py-4">
            <div
              className="w-10 h-10 rounded-xl grid place-items-center mx-auto mb-3"
              style={{ background: 'rgba(139,125,255,.14)' }}
            >
              <Sparkles size={19} strokeWidth={1.7} className="text-data-violet" />
            </div>
            <h4 className="text-sm font-semibold text-ink-0 mb-1">Analizá tu cartera con la IA</h4>
            <p className="text-xs text-ink-2 max-w-md mx-auto mb-4 leading-relaxed">
              El Coach lee tu diagnóstico completo (concentración, riesgo, comportamiento) y
              arma una lectura a medida: qué importa para vos y por qué. Se genera cuando la
              pedís y queda cacheada unas horas.
            </p>
            <button
              onClick={analyze}
              className="inline-flex items-center gap-2 text-sm font-medium bg-data-violet hover:bg-data-violet/90 text-white border border-data-violet rounded-sm px-4 py-2.5 transition-colors press"
            >
              <Sparkles size={14} strokeWidth={1.75} /> Analizar mi cartera
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
