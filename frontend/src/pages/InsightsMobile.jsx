// InsightsMobile — "Insight del día" (Sprint M1, item 03 del audit).
// ═══════════════════════════════════════════════════════════════════════════
// Audit: "El desktop tiene 14 findings simultáneos. El mobile entrega uno
// protagonista por día — el de mayor impacto — como pantalla casi full-bleed.
// Lista de findings secundarios debajo, en filas densas."
//
// Source: /api/behavioral/insights (los 12 detectores). El de severidad más
// alta + más reciente = protagonista. El resto = lista secundaria.
//
// Tap protagonista → expande explicación + evidencia.
// Tap fila secundaria → reusa el modal del BehavioralModal (lo importamos
// directo desde Behavioral.jsx).

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Brain, AlertTriangle, CheckCircle2, Info, ArrowRight, ChevronRight,
} from 'lucide-react'
import Pill from '../components/Pill'
import ShareCardModal from '../components/ShareCardModal'
import { specFromInsight } from '../utils/shareCard'
import { api } from '../utils/api'
import { track } from '../utils/track'

const SEVERITY_RANK = { high: 4, medium: 3, low: 2, positive: 1, neutral: 0 }
const SEVERITY_TONE = {
  high:     { pill: 'red',    accent: 'text-rendi-neg',  bg: 'bg-rendi-neg/[0.04]',  border: 'border-rendi-neg/25',  Icon: AlertTriangle, label: 'Severidad alta' },
  medium:   { pill: 'warn',   accent: 'text-rendi-warn', bg: 'bg-rendi-warn/[0.04]', border: 'border-rendi-warn/25', Icon: AlertTriangle, label: 'Severidad media' },
  low:      { pill: 'info',   accent: 'text-data-blue',  bg: 'bg-data-blue/[0.03]',  border: 'border-data-blue/25',  Icon: Info,          label: 'Severidad baja' },
  positive: { pill: 'signal', accent: 'text-rendi-pos',  bg: 'bg-rendi-pos/[0.04]',  border: 'border-rendi-pos/25',  Icon: CheckCircle2,  label: 'Patrón saludable' },
  neutral:  { pill: 'off',    accent: 'text-ink-2',      bg: 'bg-bg-2/40',            border: 'border-line',         Icon: Info,          label: 'Sin datos' },
}

export default function InsightsMobile() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [shareCard, setShareCard] = useState(null)

  useEffect(() => {
    track('insight_del_dia_viewed')
    api.get('/behavioral/insights')
      .then(setData)
      .catch(ex => setError(ex?.message || 'No pudimos cargar tus insights.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="px-4 py-10 text-center text-ink-3 text-sm" aria-live="polite">
        Analizando tu historial…
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-4 py-6">
        <div className="border border-rendi-neg/30 bg-rendi-neg/[0.06] rounded p-4 text-sm text-rendi-neg">
          {error}
        </div>
      </div>
    )
  }

  const allCards = data?.cards || []
  const flaggedCards = allCards.filter(c => !c.insufficient_data)

  if (flaggedCards.length === 0) {
    return (
      <div className="px-4 pt-6 pb-10">
        <div className="bg-bg-1 border border-line/60 rounded-lg p-6 text-center">
          <Brain size={24} strokeWidth={1.5} className="mx-auto mb-3 text-ink-3" />
          <h2 className="text-sm font-medium text-ink-0 mb-1.5">
            Necesitamos más historial
          </h2>
          <p className="text-xs text-ink-2 leading-relaxed mb-4">
            Cargá al menos 5 operaciones cerradas para que detectemos patrones
            comportamentales en tu trading.
          </p>
          <Link
            to="/config"
            className="inline-flex items-center gap-1.5 text-xs bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-3 py-1.5 rounded-sm"
          >
            Importar historial <ArrowRight size={11} strokeWidth={1.75} />
          </Link>
        </div>
      </div>
    )
  }

  // Protagonista: el de severidad más alta
  const sorted = [...flaggedCards].sort(
    (a, b) => (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0)
  )
  const protagonist = sorted[0]
  const others = sorted.slice(1)

  return (
    <div className="pb-8">
      {/* Header chiquito */}
      <header className="px-4 pt-4 pb-2">
        <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none mb-1">
          Insight del día
        </div>
        <h1 className="text-lg font-medium text-ink-0 leading-tight">
          Lo que tus operaciones cuentan hoy
        </h1>
      </header>

      {/* ── Protagonista — full-bleed-ish ─────────────────────────────── */}
      <ProtagonistCard card={protagonist} onShare={(c) => setShareCard(c)} />

      {/* ── Lista secundaria densa ──────────────────────────────────── */}
      {others.length > 0 && (
        <section className="mt-6 px-4">
          <h2 className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2">
            También detectamos
          </h2>
          <ul className="bg-bg-1 border border-line/60 rounded-lg overflow-hidden">
            {others.map((c, i) => (
              <SecondaryRow key={c.code} card={c} first={i === 0} />
            ))}
          </ul>
        </section>
      )}

      {/* Footer informativo */}
      <p className="px-4 mt-6 text-[11px] text-ink-3 leading-relaxed">
        Los detectores se basan en literatura de behavioral finance
        (Kahneman, Shefrin, Odean). Son señales, no recomendaciones.
        <br />
        <Link
          to="/comportamiento"
          className="inline-flex items-center gap-1 text-data-blue mt-1.5 font-mono uppercase tracking-caps text-[10px]"
        >
          Ver los 12 detectores <ArrowRight size={11} strokeWidth={1.75} />
        </Link>
      </p>

      {/* Share card */}
      {shareCard && (
        <ShareCardModal
          spec={specFromInsight(shareCard)}
          filename={`rendi-${shareCard.code}.png`}
          source="insight_del_dia"
          onClose={() => setShareCard(null)}
        />
      )}
    </div>
  )
}

// ─── Protagonista ────────────────────────────────────────────────────────

function ProtagonistCard({ card, onShare }) {
  const tone = SEVERITY_TONE[card.severity] || SEVERITY_TONE.neutral
  const { Icon } = tone
  return (
    <article
      className={`mx-4 ${tone.bg} border ${tone.border} rounded-lg p-5`}
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <Icon size={14} strokeWidth={1.75} className={tone.accent} />
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
            {card.code.replace(/_/g, ' ')}
          </span>
        </div>
        <Pill tone={tone.pill} dot>{tone.label}</Pill>
      </div>

      <h2 className="text-xl font-medium text-ink-0 leading-snug mb-2">
        {card.title}
      </h2>

      <p className="text-sm text-ink-2 leading-relaxed mb-4">
        {card.one_liner}
      </p>

      {card.value_label && (
        <div className="bg-bg-1 border border-line/40 rounded-sm p-3 mb-4">
          <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none mb-1.5">
            Indicador
          </div>
          <div className={`text-base font-medium tabular leading-none ${tone.accent}`}>
            {card.value_label}
          </div>
        </div>
      )}

      <div className="flex items-center justify-between gap-2 pt-2 border-t border-line/30">
        <Link
          to="/comportamiento"
          className="text-[11px] font-mono uppercase tracking-caps text-ink-2 hover:text-ink-0 inline-flex items-center gap-1"
        >
          Ver detalle <ChevronRight size={11} strokeWidth={1.75} />
        </Link>
        <button
          onClick={() => onShare(card)}
          className="text-[11px] font-mono uppercase tracking-caps text-rendi-pos hover:text-rendi-pos/80"
        >
          Compartir
        </button>
      </div>
    </article>
  )
}

// ─── Fila secundaria densa ───────────────────────────────────────────────

function SecondaryRow({ card, first }) {
  const tone = SEVERITY_TONE[card.severity] || SEVERITY_TONE.neutral
  const { Icon } = tone
  return (
    <li>
      <Link
        to="/comportamiento"
        className={`flex items-center gap-3 px-3 py-3 hover:bg-bg-2/40 active:bg-bg-3 transition-colors ${
          first ? '' : 'border-t border-line/30'
        }`}
      >
        <Icon size={13} strokeWidth={1.75} className={`${tone.accent} flex-shrink-0`} />
        <div className="flex-1 min-w-0">
          <div className="text-sm text-ink-0 leading-tight truncate">
            {card.title}
          </div>
          {card.value_label && (
            <div className="text-[11px] font-mono text-ink-3 leading-none mt-1 truncate">
              {card.value_label}
            </div>
          )}
        </div>
        <ChevronRight size={13} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
      </Link>
    </li>
  )
}
