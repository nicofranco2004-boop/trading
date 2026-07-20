// InsightDelDiaHero — card protagonista del sesgo más severo del día.
// ═══════════════════════════════════════════════════════════════════════════
// Se renderiza al top de /insights solo en mobile. Compactá la información de
// /api/behavioral/insights en una sola card "full-bleed-ish": indicador
// destacado, severity pill, one_liner, value_label, CTAs (ver detalle /
// compartir).
//
// Si no hay flagged cards (todos insufficient_data) → mensaje empty state.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Brain, AlertTriangle, CheckCircle2, Info, ArrowRight, ChevronRight,
} from 'lucide-react'
import Pill from '../Pill'
import ShareCardModal from '../ShareCardModal'
import { specFromInsight } from '../../utils/shareCard'
import { api } from '../../utils/api'

const SEVERITY_RANK = { high: 4, medium: 3, low: 2, positive: 1, neutral: 0 }
const SEVERITY_TONE = {
  high:     { pill: 'red',    accent: 'text-rendi-neg',  bg: 'bg-rendi-neg/[0.04]',  border: 'border-rendi-neg/25',  Icon: AlertTriangle, label: 'Severidad alta' },
  medium:   { pill: 'warn',   accent: 'text-rendi-warn', bg: 'bg-rendi-warn/[0.04]', border: 'border-rendi-warn/25', Icon: AlertTriangle, label: 'Severidad media' },
  low:      { pill: 'info',   accent: 'text-data-blue',  bg: 'bg-data-blue/[0.03]',  border: 'border-data-blue/25',  Icon: Info,          label: 'Severidad baja' },
  positive: { pill: 'signal', accent: 'text-rendi-pos',  bg: 'bg-rendi-pos/[0.04]',  border: 'border-rendi-pos/25',  Icon: CheckCircle2,  label: 'Patrón saludable' },
  neutral:  { pill: 'off',    accent: 'text-ink-2',      bg: 'bg-bg-2/40',            border: 'border-line',         Icon: Info,          label: 'Sin datos' },
}

export default function InsightDelDiaHero() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [shareCard, setShareCard] = useState(null)

  useEffect(() => {
    api.get('/behavioral/insights')
      .then(setData)
      .catch(() => { /* silent — si falla, no rompemos toda la pantalla */ })
      .finally(() => setLoading(false))
  }, [])

  if (loading || !data) return null

  const flagged = (data.cards || []).filter(c => !c.insufficient_data)
  if (flagged.length === 0) {
    return (
      <div className="bg-bg-1 border border-line/60 rounded-lg p-4 mb-5">
        <div className="flex items-center gap-2 mb-1.5">
          <Brain size={14} strokeWidth={1.75} className="text-ink-3" />
          <span className="text-[12.5px] text-ink-2 font-medium">Insight del día</span>
        </div>
        <p className="text-xs text-ink-2 leading-relaxed">
          Necesitamos más historial para detectar patrones. Cargá al menos 5 operaciones cerradas.
        </p>
      </div>
    )
  }

  const sorted = [...flagged].sort(
    (a, b) => (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0)
  )
  const card = sorted[0]
  const tone = SEVERITY_TONE[card.severity] || SEVERITY_TONE.neutral
  const { Icon } = tone

  return (
    <>
      <article className={`${tone.bg} border ${tone.border} rounded-lg p-4 mb-5`}>
        <div className="flex items-center justify-between gap-2 mb-2.5">
          <div className="flex items-center gap-2 min-w-0">
            <Icon size={13} strokeWidth={1.75} className={`${tone.accent} flex-shrink-0`} />
            <span className="text-[12.5px] text-ink-2 truncate font-medium">
              Insight del día · {card.code.replace(/_/g, ' ')}
            </span>
          </div>
          <Pill tone={tone.pill} dot>{tone.label}</Pill>
        </div>

        <h2 className="text-lg font-medium text-ink-0 leading-snug mb-1.5">
          {card.title}
        </h2>
        <p className="text-xs text-ink-2 leading-relaxed mb-3">
          {card.one_liner}
        </p>

        {card.value_label && (
          <div className="bg-bg-1 border border-line/40 rounded-sm p-2.5 mb-3">
            <div className="text-[12.5px] text-ink-2 leading-none mb-1 font-medium">
              Indicador
            </div>
            <div className={`text-sm font-medium tabular leading-none ${tone.accent}`}>
              {card.value_label}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-2 pt-2 border-t border-line/30">
          <Link
            to="/comportamiento"
            className="text-[12px] text-ink-2 hover:text-ink-0 inline-flex items-center gap-1 font-medium"
          >
            Ver los 12 detectores <ChevronRight size={10} strokeWidth={1.75} />
          </Link>
          <button
            onClick={() => setShareCard(card)}
            className="text-[12px] text-rendi-pos hover:text-rendi-pos/80 font-medium"
          >
            Compartir
          </button>
        </div>
      </article>

      {shareCard && (
        <ShareCardModal
          spec={specFromInsight(shareCard)}
          filename={`rendi-${shareCard.code}.png`}
          source="insight_del_dia"
          onClose={() => setShareCard(null)}
        />
      )}
    </>
  )
}
