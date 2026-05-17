// AnalysisDrawer — drawer derecho (desktop) / bottom sheet (mobile) con análisis.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint AI v2. Container reutilizable. Cada screen del producto monta uno
// con su `screen` y `params` — el hook + card hacen el resto.
//
// UX:
//   - Desktop: panel fixed derecha, 420px ancho, full-height
//   - Mobile: bottom sheet via componente BottomSheet existente
//   - ESC cierra; backdrop click cierra; cuerpo locked
//   - Botón "Refrescar" arriba (DELETE cache + reanalyze)

import { useEffect, useState } from 'react'
import { X, RefreshCw, Sparkles } from 'lucide-react'
import { useAIAnalysis } from '../../hooks/useAIAnalysis'
import { useIsMobile } from '../../hooks/useIsMobile'
import BottomSheet from '../mobile/BottomSheet'
import AnalysisCard from './AnalysisCard'
import AISkeleton from './AISkeleton'
import UpgradePromoCard from './UpgradePromoCard'

export default function AnalysisDrawer({
  open,
  onClose,
  screen,
  params,
  title = 'Análisis',
  subtitle,
}) {
  const isMobile = useIsMobile()
  const {
    result, usage, tier, cached, loading, error, upgrade,
    followups, followupLoading, followupsExhausted,
    refresh, askFollowUp,
  } = useAIAnalysis({
    screen,
    params,
    autoload: open,
  })
  // 429 con upgrade payload → mostramos UpgradePromoCard en lugar de banner rojo.
  const showUpgradeCard = !!(upgrade && upgrade.available)
  const [refreshing, setRefreshing] = useState(false)

  // ESC cierra
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Body scroll lock (desktop drawer)
  useEffect(() => {
    if (!open || isMobile) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [open, isMobile])

  if (!open) return null

  async function handleRefresh() {
    setRefreshing(true)
    try { await refresh() } finally { setRefreshing(false) }
  }

  // Badge weekly: free=X/10 esta semana, pro=X/200 esta semana, admin=sin tope.
  function renderUsageBadge() {
    if (!usage) return null
    if (usage.tier === 'admin') return 'Admin · sin tope'
    if (usage.tier === 'pro') return `${usage.analyses_count}/${usage.analyses_limit} · Pro`
    // Free
    return `${usage.analyses_count}/${usage.analyses_limit} esta semana`
  }

  const body = (
    <div className="space-y-5">
      {/* 429 con upgrade payload → card promocional; otros errores → banner */}
      {showUpgradeCard && !loading && (
        <UpgradePromoCard usage={usage} upgrade={upgrade} source={`drawer_429_${screen}`} />
      )}
      {error && !loading && !showUpgradeCard && (
        <div className="text-xs text-rendi-neg bg-rendi-neg/[0.06] border border-rendi-neg/25 rounded-sm px-3 py-2">
          {typeof error === 'string' ? error : 'No pudimos generar el análisis.'}
        </div>
      )}

      {loading && !result && <AISkeleton />}

      {result && (
        <AnalysisCard
          result={result}
          onFollowUp={askFollowUp}
          followUpsDisabled={followupLoading || followupsExhausted}
        />
      )}

      {/* Follow-ups acumulados — cada uno con su pregunta + respuesta */}
      {followups.map((fu, i) => (
        <FollowUpBlock key={i} followup={fu} />
      ))}

      {/* Loading del follow-up activo */}
      {followupLoading && (
        <div className="pt-3 border-t border-line/40">
          <div className="text-[10px] font-mono uppercase tracking-caps text-data-violet mb-2">
            Profundizando…
          </div>
          <AISkeleton />
        </div>
      )}

      {/* Cap alcanzado */}
      {followupsExhausted && !followupLoading && (
        <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 text-center pt-2">
          Llegaste al máximo de 2 preguntas por análisis. Refrescá para empezar de nuevo.
        </div>
      )}

      {/* Footer meta — cached + usage badge (weekly) */}
      <div className="pt-3 border-t border-line/40 flex items-center justify-between text-[10px] font-mono uppercase tracking-caps text-ink-3">
        <span>
          {loading ? 'Generando…' : cached ? 'Análisis cacheado · ≤24h' : 'Generado ahora'}
        </span>
        {usage && (
          <span>{renderUsageBadge()}</span>
        )}
      </div>
    </div>
  )

  // ── Mobile: BottomSheet ────────────────────────────────────────────────
  if (isMobile) {
    return (
      <BottomSheet
        open
        onClose={onClose}
        eyebrow={
          <span className="inline-flex items-center gap-1">
            <Sparkles size={11} strokeWidth={1.75} className="text-data-violet" />
            {title}
          </span>
        }
        title={subtitle || 'Análisis del portfolio'}
        ariaLabel="Análisis IA"
        footer={
          <button
            onClick={handleRefresh}
            disabled={loading || refreshing}
            className="w-full inline-flex items-center justify-center gap-1.5 text-xs bg-bg-2 hover:bg-bg-3 disabled:opacity-50 text-ink-1 border border-line/60 rounded-sm py-2 transition-colors"
          >
            <RefreshCw size={12} strokeWidth={1.75} className={refreshing ? 'animate-spin' : ''} />
            Refrescar
          </button>
        }
      >
        <div className="p-4">{body}</div>
      </BottomSheet>
    )
  }

  // ── Desktop: drawer derecho ────────────────────────────────────────────
  return (
    <div
      className="fixed inset-0 z-[60] flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="Análisis IA"
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.() }}
    >
      {/* Backdrop */}
      <div
        aria-hidden
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <aside
        onClick={(e) => e.stopPropagation()}
        className="relative w-full max-w-[420px] bg-bg-1 border-l border-data-violet/30 shadow-2xl flex flex-col"
        style={{
          animation: 'ai-drawer-in 220ms cubic-bezier(0.32, 0.72, 0, 1)',
        }}
      >
        {/* Header */}
        <header className="flex items-start justify-between gap-2 px-5 py-4 border-b border-line/40 flex-shrink-0">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5 mb-1.5">
              <Sparkles size={12} strokeWidth={1.75} className="text-data-violet" />
              <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
                {title}
              </span>
            </div>
            <h2 className="text-base font-medium text-ink-0 leading-tight">
              {subtitle || 'Análisis del portfolio'}
            </h2>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            <button
              onClick={handleRefresh}
              disabled={loading || refreshing}
              aria-label="Refrescar análisis"
              className="text-ink-3 hover:text-ink-0 disabled:opacity-40 transition-colors p-1.5"
              title="Refrescar"
            >
              <RefreshCw size={14} strokeWidth={1.75} className={refreshing ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={onClose}
              aria-label="Cerrar"
              className="text-ink-3 hover:text-ink-0 transition-colors p-1.5"
            >
              <X size={16} strokeWidth={1.75} />
            </button>
          </div>
        </header>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {body}
        </div>
      </aside>

      <style>{`
        @keyframes ai-drawer-in {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
      `}</style>
    </div>
  )
}


// FollowUpBlock — render de un follow-up ejecutado (pregunta + respuesta o
// error). Visualmente diferenciado del análisis principal con borde violeta
// sutil para que el user vea claro que es una capa adicional.
function FollowUpBlock({ followup }) {
  return (
    <div className="pt-4 border-t border-data-violet/20 space-y-3">
      <div className="flex items-start gap-2">
        <div className="flex-shrink-0 w-1 h-4 bg-data-violet/40 rounded-full mt-1" />
        <p className="text-xs font-medium text-data-violet leading-snug">
          {followup.question}
        </p>
      </div>
      {followup.error ? (
        <p className="text-xs text-rendi-neg bg-rendi-neg/[0.06] border border-rendi-neg/25 rounded-sm px-3 py-2">
          {followup.error}
        </p>
      ) : (
        <AnalysisCard result={followup.result} hideFollowUps />
      )}
    </div>
  )
}
