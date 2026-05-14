// Behavioral — sesgos comportamentales detectados sobre tus operaciones.
// ════════════════════════════════════════════════════════════════════════════
// Sprint 3-4 del plan post-auditoría. Lo que diferencia Rendi de cualquier
// broker AR: te decimos "vendiste tus winners 3.5x más rápido que tus losers".
//
// Cards: disposition effect, overtrade, loss aversion, averaging down.
// Click en una card → modal con explicación detallada, evidencia y citas
// académicas.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Brain, Activity, TrendingDown, RefreshCw, Repeat, Info, AlertTriangle,
  CheckCircle2, ChevronRight, ArrowRight, X, BookOpen,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import Pill from '../components/Pill'
import { api } from '../utils/api'
import { track } from '../utils/track'

// Mapeo code → icono + tono visual.
const CARD_META = {
  disposition_effect: { Icon: TrendingDown, label: 'Disposition effect' },
  overtrade:          { Icon: Repeat,        label: 'Frecuencia de trades' },
  loss_aversion:      { Icon: Activity,      label: 'Loss aversion' },
  averaging_down:     { Icon: RefreshCw,     label: 'Promedio a la baja' },
}

const SEVERITY_TONE = {
  high:     { pill: 'red',     accent: 'text-rendi-neg',  border: 'border-rendi-neg/30',  Icon: AlertTriangle },
  medium:   { pill: 'warn',    accent: 'text-rendi-warn', border: 'border-rendi-warn/30', Icon: AlertTriangle },
  low:      { pill: 'info',    accent: 'text-data-blue',  border: 'border-data-blue/30',  Icon: Info },
  positive: { pill: 'signal',  accent: 'text-rendi-pos',  border: 'border-rendi-pos/30',  Icon: CheckCircle2 },
  neutral:  { pill: 'off',     accent: 'text-ink-3',      border: 'border-line',          Icon: Info },
}

const SEVERITY_LABEL = {
  high: 'Alta',
  medium: 'Media',
  low: 'Baja',
  positive: 'Saludable',
  neutral: 'Sin datos',
}

export default function Behavioral() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedCard, setSelectedCard] = useState(null)

  useEffect(() => {
    track('behavioral_viewed')
    api.get('/behavioral/insights')
      .then(d => setData(d))
      .catch(ex => setError(ex.message || 'No pudimos cargar los insights.'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="page-shell text-center py-20 text-ink-3 text-sm" aria-live="polite">
        Analizando tu historial…
      </div>
    )
  }

  if (error) {
    return (
      <div className="page-shell">
        <PageHeader
          eyebrow="Análisis"
          title="Comportamiento"
          subtitle="Sesgos comportamentales detectados sobre tu historial de operaciones."
        />
        <div className="border border-rendi-neg/30 bg-rendi-neg/[0.06] rounded p-4 text-sm text-rendi-neg">
          {error}
        </div>
      </div>
    )
  }

  const cards = data?.cards || []
  const allInsufficient = cards.every(c => c.insufficient_data)

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        eyebrow="Análisis"
        title="Comportamiento"
        subtitle="Sesgos comportamentales detectados sobre tu historial de operaciones. Lo que tu broker no te dice."
      />

      {/* KPI strip de resumen */}
      <div className="border border-line rounded bg-bg-1 flex flex-wrap">
        <SummaryCell first label="Sesgos detectados" value={data?.summary?.total_detected ?? 0} tone={data?.summary?.total_detected > 0 ? 'warn' : 'pos'} />
        <SummaryCell label="Severidad alta"  value={data?.summary?.total_high ?? 0}    tone={data?.summary?.total_high > 0 ? 'neg' : null} />
        <SummaryCell label="Severidad media" value={data?.summary?.total_medium ?? 0}  tone={data?.summary?.total_medium > 0 ? 'warn' : null} />
        <SummaryCell label="Patrones sanos"  value={data?.summary?.total_positive ?? 0} tone="pos" />
        <SummaryCell label="Detectores"      value={data?.summary?.total_cards ?? 0} />
      </div>

      {/* Empty state si no hay data */}
      {allInsufficient && (
        <div className="border border-line rounded bg-bg-1 px-6 py-12 text-center max-w-2xl mx-auto">
          <Brain size={28} strokeWidth={1.5} className="mx-auto mb-3 text-ink-3" />
          <h2 className="text-base font-medium text-ink-0 mb-1.5">Necesitamos más historial</h2>
          <p className="text-sm text-ink-2 leading-relaxed mb-4 max-w-md mx-auto">
            Los detectores de sesgos comparan tus operaciones cerradas. Importá tu CSV
            o cargá al menos 5 ventas para empezar a ver patrones.
          </p>
          <Link
            to="/config"
            className="inline-flex items-center gap-1.5 text-sm bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-4 py-2 rounded-sm transition-colors"
          >
            Importar mi historial
            <ArrowRight size={13} strokeWidth={1.75} />
          </Link>
        </div>
      )}

      {/* Grid de cards */}
      {!allInsufficient && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {cards.map(card => (
            <BehavioralCard
              key={card.code}
              card={card}
              onClick={() => {
                track('behavioral_card_opened', { code: card.code })
                setSelectedCard(card)
              }}
            />
          ))}
        </div>
      )}

      {/* Footer educational */}
      <p className="text-xs text-ink-3 max-w-2xl pt-2">
        Los detectores se basan en literatura académica de behavioral finance
        (Kahneman, Shefrin, Odean). Son señales orientativas, no recomendaciones
        de operación.
      </p>

      {/* Modal de detalle */}
      {selectedCard && (
        <BehavioralModal
          card={selectedCard}
          onClose={() => setSelectedCard(null)}
        />
      )}
    </div>
  )
}

// ─── Summary cell ───────────────────────────────────────────────────────────

function SummaryCell({ label, value, sub, tone, first }) {
  const color = tone === 'pos' ? 'text-rendi-pos'
              : tone === 'neg' ? 'text-rendi-neg'
              : tone === 'warn' ? 'text-rendi-warn'
              : 'text-ink-0'
  return (
    <div className={`px-4 py-3 flex-1 min-w-[120px] ${first ? '' : 'border-l border-line/50'}`}>
      <div className="text-[10px] font-mono uppercase tracking-label text-ink-3 leading-none">{label}</div>
      <div className={`mt-2 font-medium tabular num leading-none text-2xl tracking-tight ${color}`}>{value}</div>
      {sub && <div className="text-[10px] font-mono text-ink-3 mt-1.5 leading-none">{sub}</div>}
    </div>
  )
}

// ─── Card ───────────────────────────────────────────────────────────────────

function BehavioralCard({ card, onClick }) {
  const meta = CARD_META[card.code] || { Icon: Info, label: card.code }
  const tone = SEVERITY_TONE[card.severity] || SEVERITY_TONE.neutral
  const { Icon } = meta
  const { Icon: SevIcon } = tone

  if (card.insufficient_data) {
    return (
      <div className="border border-line rounded bg-bg-1 p-4 opacity-70">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Icon size={14} strokeWidth={1.75} className="text-ink-3" />
            <span className="text-xs font-mono uppercase tracking-caps text-ink-3">{meta.label}</span>
          </div>
          <Pill tone="off">Sin datos</Pill>
        </div>
        <h3 className="text-sm font-medium text-ink-1 mb-1">Necesitamos más operaciones</h3>
        <p className="text-xs text-ink-3 leading-relaxed">{card.one_liner}</p>
      </div>
    )
  }

  return (
    <button
      onClick={onClick}
      className={`text-left border ${tone.border} rounded bg-bg-1 p-4 hover:bg-bg-2/40 transition-colors group`}
    >
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2 min-w-0">
          <Icon size={14} strokeWidth={1.75} className={tone.accent} />
          <span className="text-xs font-mono uppercase tracking-caps text-ink-3">{meta.label}</span>
        </div>
        <Pill tone={tone.pill} dot={card.severity !== 'neutral' && card.severity !== 'off'}>
          {SEVERITY_LABEL[card.severity] || card.severity}
        </Pill>
      </div>

      <h3 className="text-base font-medium text-ink-0 mb-1.5 leading-snug">{card.title}</h3>
      <p className="text-sm text-ink-2 leading-relaxed mb-3">{card.one_liner}</p>

      <div className="flex items-center justify-between text-xs">
        <span className="font-mono tabular text-ink-1">{card.value_label}</span>
        <span className="text-ink-3 inline-flex items-center gap-0.5 group-hover:text-ink-0 transition-colors">
          Ver detalle <ChevronRight size={11} strokeWidth={1.75} />
        </span>
      </div>
    </button>
  )
}

// ─── Modal de detalle ───────────────────────────────────────────────────────

function BehavioralModal({ card, onClose }) {
  // ESC para cerrar
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const meta = CARD_META[card.code] || { Icon: Info, label: card.code }
  const tone = SEVERITY_TONE[card.severity] || SEVERITY_TONE.neutral
  const { Icon } = meta

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-3 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        className={`bg-bg-1 border ${tone.border} rounded-lg shadow-2xl w-full max-w-xl max-h-[90vh] overflow-y-auto`}
      >
        <header className="flex items-start justify-between gap-3 px-5 py-4 border-b border-line/40">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <Icon size={14} strokeWidth={1.75} className={tone.accent} />
              <span className="text-xs font-mono uppercase tracking-caps text-ink-3">{meta.label}</span>
              <Pill tone={tone.pill} dot>{SEVERITY_LABEL[card.severity] || card.severity}</Pill>
            </div>
            <h2 className="text-lg font-medium text-ink-0 leading-tight">{card.title}</h2>
          </div>
          <button
            onClick={onClose}
            className="text-ink-3 hover:text-ink-0 transition-colors p-1 flex-shrink-0"
            aria-label="Cerrar"
          >
            <X size={16} strokeWidth={1.75} />
          </button>
        </header>

        <div className="px-5 py-4 space-y-4">
          <p className="text-sm text-ink-1 leading-relaxed">{card.one_liner}</p>

          <ModalEvidence card={card} />

          {/* Referencias académicas */}
          {card.references?.length > 0 && (
            <div className="border-t border-line/40 pt-3">
              <div className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1.5">
                <BookOpen size={11} strokeWidth={1.75} />
                Referencia académica
              </div>
              <ul className="space-y-1 text-xs text-ink-2 leading-relaxed">
                {card.references.map((r, i) => (
                  <li key={i}>· {r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Evidencia por detector ─────────────────────────────────────────────────

function ModalEvidence({ card }) {
  const ev = card.evidence || {}
  switch (card.code) {
    case 'disposition_effect':
      return (
        <div className="space-y-3">
          <EvidenceRow label="Ganadoras (avg holding)" value={`${ev.winners_avg_days?.toFixed(1)} días`} count={ev.winners_count} />
          <EvidenceRow label="Perdedoras (avg holding)" value={`${ev.losers_avg_days?.toFixed(1)} días`} count={ev.losers_count} />
          <EvidenceRow label="Ratio" value={`${ev.ratio?.toFixed(2)}× (winners/losers)`} mono />
          {(ev.sample_winners?.length > 0 || ev.sample_losers?.length > 0) && (
            <div className="grid grid-cols-2 gap-3 pt-2">
              {ev.sample_winners?.length > 0 && (
                <SamplesPanel title="Top winners más rápidos" tone="pos" items={ev.sample_winners} />
              )}
              {ev.sample_losers?.length > 0 && (
                <SamplesPanel title="Top losers más aguantados" tone="neg" items={ev.sample_losers} />
              )}
            </div>
          )}
        </div>
      )
    case 'overtrade':
      return (
        <div className="space-y-2">
          <EvidenceRow label="Trades cerrados" value={ev.total_trades} mono />
          <EvidenceRow label="Período analizado" value={`${ev.period_years?.toFixed(1)} años (${ev.period_days} días)`} />
          <EvidenceRow label="Ops por año" value={ev.annual_ops?.toFixed(1)} mono />
          <EvidenceRow label="Turnover anualizado" value={`${ev.annual_turnover?.toFixed(2)}×`} mono />
          <EvidenceRow label="Notional total" value={`US$ ${ev.total_notional?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} />
          <EvidenceRow label="Capital promedio" value={`US$ ${ev.capital_avg?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} />
        </div>
      )
    case 'loss_aversion':
      return (
        <div className="space-y-2">
          <EvidenceRow label="Ganadoras" value={ev.winners_count} count={`avg US$ ${ev.winners_avg_size_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} />
          <EvidenceRow label="Perdedoras" value={ev.losers_count} count={`avg US$ ${ev.losers_avg_size_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} />
          <EvidenceRow label="Ratio losers/winners" value={`${ev.ratio?.toFixed(2)}×`} mono />
        </div>
      )
    case 'averaging_down':
      return (
        <div className="space-y-3">
          <EvidenceRow label="Instancias detectadas" value={ev.total_instances} mono />
          <EvidenceRow label="Caída promedio entre compras" value={`${ev.avg_drop_pct?.toFixed(1)}%`} mono />
          {ev.instances?.length > 0 && (
            <div className="border-t border-line/40 pt-2 space-y-2">
              <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3">Ejemplos</div>
              {ev.instances.slice(0, 5).map((inst, i) => (
                <div key={i} className="text-xs border border-line/40 rounded-sm p-2 bg-bg-2/40">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium text-ink-0">{inst.asset}</span>
                    <span className="font-mono tabular text-rendi-neg">{inst.price_drop_pct}%</span>
                  </div>
                  <div className="text-[11px] text-ink-3 tabular">
                    {inst.first_buy.date}: US$ {inst.first_buy.price} → {inst.second_buy.date}: US$ {inst.second_buy.price}
                    <span className="ml-1">· {inst.gap_days} días</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )
    default:
      return null
  }
}

function EvidenceRow({ label, value, count, mono }) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-sm">
      <span className="text-ink-3 text-xs">{label}</span>
      <span className={`text-ink-0 ${mono ? 'font-mono tabular' : ''}`}>
        {value}
        {count != null && <span className="text-ink-3 ml-1.5 text-xs">· {count}</span>}
      </span>
    </div>
  )
}

function SamplesPanel({ title, tone, items }) {
  const color = tone === 'pos' ? 'text-rendi-pos' : 'text-rendi-neg'
  return (
    <div className="border border-line/40 rounded-sm p-2 bg-bg-2/40">
      <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1.5">{title}</div>
      <ul className="space-y-1 text-xs">
        {items.map((s, i) => (
          <li key={i} className="flex items-center justify-between gap-2">
            <span className="text-ink-1 font-mono">{s.asset}</span>
            <span className="text-ink-3 tabular">{s.days}d</span>
            <span className={`font-mono tabular ${color}`}>
              {s.pnl >= 0 ? '+' : '−'}${Math.abs(s.pnl).toLocaleString('es-AR', { maximumFractionDigits: 0 })}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
