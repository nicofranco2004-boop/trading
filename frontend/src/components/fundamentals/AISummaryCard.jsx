// AISummaryCard — resumen IA "Lo mejor / Ojo con esto" (acento violeta).
// ═══════════════════════════════════════════════════════════════════════════
// Carga POST /api/fundamentals/ai-summary on-demand (auto al montar/cambiar
// ticker). NUNCA bloquea el scorecard — vive en su propia card.
//
// Estados:
//   - loading → Skeleton
//   - ok      → intro + LO MEJOR (pros) + OJO CON ESTO (cons) + disclaimer
//   - 429     → UpgradePromoCard (reusa el patrón del Coach IA)
//   - 503     → soft "Resumen IA no disponible por ahora"
//   - 422/available:false → mensaje "sin fundamentales para resumir"
//
// El backend devuelve el 429 con el MISMO shape que /api/ai/analyze:
//   detail = { error, message, usage?, upgrade? }  (ver AICoach.jsx).

import { useState, useEffect } from 'react'
import { Sparkles, CheckCircle, AlertTriangle } from 'lucide-react'
import { api } from '../../utils/api'
import Skeleton from '../Skeleton'
import UpgradePromoCard from '../ai/UpgradePromoCard'
import { track } from '../../utils/track'

export default function AISummaryCard({ ticker }) {
  const [summary, setSummary] = useState(null)
  const [usage, setUsage] = useState(null)
  const [upgradeInfo, setUpgradeInfo] = useState(null)
  const [loading, setLoading] = useState(true)
  const [softError, setSoftError] = useState(null)

  useEffect(() => {
    if (!ticker) return
    let cancelled = false

    setLoading(true)
    setSummary(null)
    setUpgradeInfo(null)
    setSoftError(null)

    api.post('/fundamentals/ai-summary', { ticker })
      .then(res => {
        if (cancelled) return
        // available:false (200) → no hay fundamentales para resumir
        if (res && res.available === false) {
          setSoftError('Esta acción no tiene fundamentales para resumir.')
          return
        }
        setSummary(res?.summary || null)
        if (res?.usage) setUsage(res.usage)
        track('fundamentals_ai_summary_loaded', { ticker })
      })
      .catch(e => {
        if (cancelled) return
        const status = e?.status
        const detail = e?.payload?.detail ?? e?.detail

        if (status === 429 && detail && typeof detail === 'object') {
          // Cuota agotada — reusar el patrón del Coach: UpgradePromoCard.
          if (detail.usage) setUsage(detail.usage)
          if (detail.upgrade && detail.upgrade.available) {
            setUpgradeInfo(detail.upgrade)
          } else {
            // El backend manda el texto en detail.error (igual que /api/ai/analyze);
            // soportamos .message por las dudas.
            setSoftError(detail.error || detail.message || 'Llegaste al límite de análisis IA de esta semana.')
          }
        } else if (status === 503) {
          setSoftError('Resumen IA no disponible por ahora. Volvé a intentar en un rato.')
        } else if (status === 422) {
          setSoftError('Esta acción no tiene fundamentales para resumir.')
        } else {
          setSoftError('No pudimos generar el resumen IA. Intentá de nuevo más tarde.')
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [ticker])

  return (
    <div className="border border-data-violet/30 bg-data-violet/[0.05] rounded-lg p-5">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <div className="p-1.5 rounded-sm bg-data-violet/10 border border-data-violet/30">
          <Sparkles size={15} strokeWidth={1.75} className="text-data-violet" />
        </div>
        <div>
          <h3 className="text-sm font-medium text-ink-0 leading-tight">Resumen IA</h3>
          <p className="text-[11px] text-ink-3">Lo bueno y lo malo, en criollo</p>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="space-y-3" aria-busy="true">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-3 w-24 mt-4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/6" />
          <Skeleton className="h-3 w-24 mt-4" />
          <Skeleton className="h-4 w-3/4" />
        </div>
      )}

      {/* Upgrade (429 con upgrade disponible) */}
      {!loading && upgradeInfo && (
        <UpgradePromoCard
          usage={usage}
          upgrade={upgradeInfo}
          kind="analyses"
          source="fundamentals_ai_429"
        />
      )}

      {/* Soft error (503 / 422 / sin upgrade / genérico) */}
      {!loading && !upgradeInfo && softError && (
        <p className="text-xs text-ink-2 leading-relaxed py-1">{softError}</p>
      )}

      {/* Contenido */}
      {!loading && !upgradeInfo && !softError && summary && (
        <div className="space-y-4">
          {summary.intro && (
            <p className="text-sm text-ink-1 leading-relaxed">{summary.intro}</p>
          )}

          {Array.isArray(summary.pros) && summary.pros.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-caps text-rendi-pos mb-2">
                Lo mejor
              </p>
              <ul className="space-y-1.5">
                {summary.pros.map((p, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-ink-1">
                    <CheckCircle size={14} strokeWidth={2} className="text-rendi-pos mt-0.5 flex-shrink-0" />
                    <span className="leading-snug">{p}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {Array.isArray(summary.cons) && summary.cons.length > 0 && (
            <div>
              <p className="text-[10px] font-mono uppercase tracking-caps text-rendi-warn mb-2">
                Ojo con esto
              </p>
              <ul className="space-y-1.5">
                {summary.cons.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-ink-1">
                    <AlertTriangle size={14} strokeWidth={2} className="text-rendi-warn mt-0.5 flex-shrink-0" />
                    <span className="leading-snug">{c}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-[10px] text-ink-3 leading-relaxed pt-2 border-t border-line/40">
            Resumen generado por IA en base a los fundamentales. No constituye recomendación de inversión.
          </p>
        </div>
      )}
    </div>
  )
}
