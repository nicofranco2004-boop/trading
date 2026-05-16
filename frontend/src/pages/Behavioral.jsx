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
  CheckCircle2, ChevronRight, ArrowRight, X, BookOpen, Share2,
  PieChart, Globe2, Wallet, Flame, Rewind, Target, Zap, Layers,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import Pill from '../components/Pill'
import ShareCardModal from '../components/ShareCardModal'
import { specFromInsight } from '../utils/shareCard'
import { api } from '../utils/api'
import { track } from '../utils/track'
import AnalyzeButton from '../components/ai/AnalyzeButton'
import AskAIAbout from '../components/ai/AskAIAbout'

// Mapeo code → icono + tono visual.
const CARD_META = {
  // Sprint 3
  disposition_effect: { Icon: TrendingDown, label: 'Disposition effect' },
  overtrade:          { Icon: Repeat,        label: 'Frecuencia de trades' },
  loss_aversion:      { Icon: Activity,      label: 'Loss aversion' },
  averaging_down:     { Icon: RefreshCw,     label: 'Promedio a la baja' },
  // Sprint 3.1
  concentration:      { Icon: PieChart,      label: 'Concentración' },
  inflation_loss:     { Icon: Flame,         label: 'Pérdida por inflación' },
  counterfactual:     { Icon: Rewind,        label: 'Tu yo de hace meses' },
  // Sprint 3.2
  winrate_payoff:     { Icon: Target,        label: 'Win rate · Payoff' },
  home_bias:          { Icon: Globe2,        label: 'Home bias' },
  cash_drag:          { Icon: Wallet,        label: 'Cash drag' },
  // Sprint 3.3
  recency_bias:       { Icon: Zap,           label: 'Chase the pump' },
  sector_concentration: { Icon: Layers,      label: 'Concentración sectorial' },
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
        action={
          <AnalyzeButton
            screen="behavioral"
            subtitle="Tus patrones de comportamiento"
          />
        }
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

      {/* Grid de cards — cada card wrappeada con AskAIAbout para análisis
          individual del sesgo. Click normal sigue abriendo el modal de
          detalle existente; ✦ (hover) o double-click abren el drawer IA. */}
      {!allInsufficient && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {cards.map(card => (
            <AskAIAbout
              key={card.code}
              topic="behavioral.card"
              params={{ code: card.code }}
              subtitle={card.title || card.code}
              className="h-full"
            >
              <BehavioralCard
                card={card}
                onClick={() => {
                  track('behavioral_card_opened', { code: card.code })
                  setSelectedCard(card)
                }}
              />
            </AskAIAbout>
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
      <div className="border border-line rounded bg-bg-1 p-4 opacity-70 h-full">
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
      className={`w-full h-full text-left border ${tone.border} rounded bg-bg-1 p-4 hover:bg-bg-2/40 transition-colors group flex flex-col`}
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

      <div className="flex items-center justify-between text-xs mt-auto">
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
  const [shareOpen, setShareOpen] = useState(false)

  // ESC para cerrar (no cierra el padre si el share está abierto)
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !shareOpen) onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, shareOpen])

  const meta = CARD_META[card.code] || { Icon: Info, label: card.code }
  const tone = SEVERITY_TONE[card.severity] || SEVERITY_TONE.neutral
  const { Icon } = meta

  const canShare = !card.insufficient_data && !!card.title

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
          <div className="flex items-center gap-1 flex-shrink-0">
            {canShare && (
              <button
                onClick={() => {
                  track('share_card_opened', { source: 'behavioral', code: card.code })
                  setShareOpen(true)
                }}
                className="inline-flex items-center gap-1 text-[11px] font-mono uppercase tracking-caps text-ink-2 hover:text-ink-0 hover:bg-bg-2/60 transition-colors px-2 py-1 rounded-sm border border-line/60"
                aria-label="Compartir esta tarjeta"
                title="Compartir"
              >
                <Share2 size={12} strokeWidth={1.75} />
                Compartir
              </button>
            )}
            <button
              onClick={onClose}
              className="text-ink-3 hover:text-ink-0 transition-colors p-1"
              aria-label="Cerrar"
            >
              <X size={16} strokeWidth={1.75} />
            </button>
          </div>
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

      {shareOpen && (
        <ShareCardModal
          spec={specFromInsight(card)}
          filename={`rendi-${card.code}.png`}
          source="behavioral"
          onClose={() => setShareOpen(false)}
        />
      )}
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

    // ── Sprint 3.1 ──
    case 'concentration':
      return (
        <div className="space-y-3">
          <EvidenceRow label="Activo más grande" value={ev.top_asset} />
          <EvidenceRow label="Top 1" value={`${ev.top1_pct?.toFixed(1)}%`} mono />
          <EvidenceRow label="Top 3" value={`${ev.top3_pct?.toFixed(1)}%`} mono />
          <EvidenceRow label="Top 5" value={`${ev.top5_pct?.toFixed(1)}%`} mono />
          <EvidenceRow label="Activos totales" value={ev.total_assets} mono />
          {ev.top_5?.length > 0 && (
            <div className="border-t border-line/40 pt-2 space-y-1">
              <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1">Composición</div>
              {ev.top_5.map((a, i) => (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className="text-ink-1 font-mono">{a.asset}</span>
                  <div className="flex items-baseline gap-2">
                    <span className="text-ink-3 tabular text-[11px]">US$ {a.value_usd.toLocaleString('es-AR', { maximumFractionDigits: 0 })}</span>
                    <span className="text-ink-0 tabular font-medium min-w-[42px] text-right">{a.pct}%</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )

    case 'inflation_loss':
      return (
        <div className="space-y-2">
          <EvidenceRow label="Cash en pesos" value={`ARS ${ev.cash_ars_pesos?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
          <EvidenceRow label="Inflación 12M acumulada" value={`${ev.inflation_cum_pct?.toFixed(1)}%`} mono />
          <EvidenceRow label="Pérdida en pesos" value={`ARS ${ev.loss_pesos?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
          <EvidenceRow label="Pérdida en USD (al blue)" value={`US$ ${ev.loss_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
        </div>
      )

    case 'counterfactual':
      return (
        <div className="space-y-3">
          <EvidenceRow label="P&L realizado" value={`US$ ${ev.realized_total_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
          <EvidenceRow label="P&L si no hubieras vendido" value={`US$ ${ev.hypothetical_total_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
          <EvidenceRow label="Diferencia" value={`${ev.delta_total_usd >= 0 ? '+' : '−'}US$ ${Math.abs(ev.delta_total_usd).toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
          <EvidenceRow label="Trades analizados" value={ev.trades_analyzed} mono />
          {ev.top_misses?.length > 0 && (
            <div className="border-t border-line/40 pt-2 space-y-1">
              <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1">Top diferencias</div>
              {ev.top_misses.map((m, i) => (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className="text-ink-1 font-mono">{m.asset}</span>
                  <span className="text-[11px] text-ink-3 tabular">
                    US$ {m.exit_price} → {m.current_price}
                  </span>
                  <span className={`font-mono tabular ${m.delta_usd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                    {m.delta_usd >= 0 ? '+' : '−'}${Math.abs(m.delta_usd).toLocaleString('es-AR', { maximumFractionDigits: 0 })}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )

    // ── Sprint 3.2 ──
    case 'winrate_payoff':
      return (
        <div className="space-y-2">
          <EvidenceRow label="Win rate" value={`${ev.win_rate_pct?.toFixed(1)}%`} mono />
          <EvidenceRow label="Ganadoras" value={ev.winners_count} count={`avg US$ ${ev.avg_win_usd?.toFixed(0)}`} />
          <EvidenceRow label="Perdedoras" value={ev.losers_count} count={`avg US$ ${ev.avg_loss_usd?.toFixed(0)}`} />
          <EvidenceRow label="Payoff ratio" value={ev.payoff_ratio != null ? `${ev.payoff_ratio.toFixed(2)}×` : '∞'} mono />
          <EvidenceRow label="Expectancy" value={`${ev.expectancy_usd >= 0 ? '+' : ''}US$ ${ev.expectancy_usd?.toFixed(2)} por op`} mono />
        </div>
      )

    case 'home_bias':
      return (
        <div className="space-y-3">
          <EvidenceRow label="Argentina" value={`${ev.ar_pct?.toFixed(1)}%`} count={`US$ ${ev.ar_value_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} />
          <EvidenceRow label="Internacional" value={`${ev.intl_pct?.toFixed(1)}%`} count={`US$ ${ev.intl_value_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} />
          <EvidenceRow label="Total portfolio" value={`US$ ${ev.total_value_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
          {/* Barra visual de mix AR / INTL */}
          <div className="pt-1">
            <div className="flex h-2 rounded-sm overflow-hidden bg-bg-2">
              <div className="bg-data-cyan" style={{ width: `${ev.ar_pct}%` }} title={`AR ${ev.ar_pct}%`} />
              <div className="bg-data-blue" style={{ width: `${ev.intl_pct}%` }} title={`INTL ${ev.intl_pct}%`} />
            </div>
            <div className="flex justify-between text-[10px] font-mono text-ink-3 mt-1">
              <span>🇦🇷 AR</span>
              <span>🌎 Internacional</span>
            </div>
          </div>
        </div>
      )

    case 'cash_drag':
      return (
        <div className="space-y-2">
          <EvidenceRow label="Cash total" value={`${ev.cash_pct?.toFixed(1)}%`} mono />
          <EvidenceRow label="Cash USD" value={`US$ ${ev.cash_usd_amount?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
          <EvidenceRow label="Cash ARS (en USD)" value={`US$ ${ev.cash_ars_usd_equiv?.toLocaleString('es-AR', { maximumFractionDigits: 0 })} (${ev.cash_ars_pct?.toFixed(1)}%)`} mono />
          <EvidenceRow label="Invertido" value={`US$ ${ev.invested_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
          <EvidenceRow label="Total portfolio" value={`US$ ${ev.total_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
        </div>
      )

    // ── Sprint 3.3 ──
    case 'recency_bias':
      return (
        <div className="space-y-3">
          <EvidenceRow label="Invested afectado" value={`${ev.chase_pct?.toFixed(1)}%`} mono />
          <EvidenceRow label="Monto chase pumps" value={`US$ ${ev.chase_pumps_invested_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`} mono />
          <EvidenceRow label="Activos flagged" value={ev.flagged_count} count={`de ${ev.flagged_count > 0 ? ev.flagged_count : 0}`} />
          {ev.flagged_assets?.length > 0 && (
            <div className="border-t border-line/40 pt-2 space-y-2">
              <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3">Top compras altas</div>
              {ev.flagged_assets.map((a, i) => (
                <div key={i} className="text-xs border border-line/40 rounded-sm p-2 bg-bg-2/40">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium text-ink-0">{a.asset}</span>
                    <span className="font-mono tabular text-rendi-neg">{a.drawdown_pct}%</span>
                  </div>
                  <div className="text-[11px] text-ink-3 tabular">
                    Compraste a US$ {a.buy_price?.toLocaleString('es-AR', { maximumFractionDigits: 2 })} · hoy US$ {a.current_price?.toLocaleString('es-AR', { maximumFractionDigits: 2 })} · invested US$ {a.invested_usd?.toLocaleString('es-AR', { maximumFractionDigits: 0 })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )

    case 'sector_concentration':
      return (
        <div className="space-y-3">
          <EvidenceRow label="Sector más grande" value={ev.top_sector} />
          <EvidenceRow label="Top sector" value={`${ev.top1_pct?.toFixed(1)}%`} mono />
          <EvidenceRow label="Top 3 sectores" value={`${ev.top3_pct?.toFixed(1)}%`} mono />
          <EvidenceRow label="Sectores distintos" value={ev.total_sectors} mono />
          {ev.breakdown?.length > 0 && (
            <div className="border-t border-line/40 pt-2 space-y-1">
              <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1">Distribución</div>
              {/* Barra stacked */}
              <div className="flex h-2 rounded-sm overflow-hidden bg-bg-2 mb-2">
                {ev.breakdown.slice(0, 6).map((b, i) => {
                  const COLORS = ['#21D07A', '#46C6E0', '#4E83FF', '#E8B14A', '#8B7DFF', '#5A6478']
                  return (
                    <div
                      key={i}
                      style={{ width: `${b.pct}%`, background: COLORS[i % COLORS.length] }}
                      title={`${b.sector}: ${b.pct}%`}
                    />
                  )
                })}
              </div>
              {ev.breakdown.slice(0, 8).map((b, i) => (
                <div key={i} className="flex items-center justify-between text-xs">
                  <span className="text-ink-1 truncate flex-1">{b.sector}</span>
                  <div className="flex items-baseline gap-2 flex-shrink-0">
                    <span className="text-ink-3 tabular text-[11px]">US$ {b.value_usd.toLocaleString('es-AR', { maximumFractionDigits: 0 })}</span>
                    <span className="text-ink-0 tabular font-medium min-w-[42px] text-right">{b.pct}%</span>
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
