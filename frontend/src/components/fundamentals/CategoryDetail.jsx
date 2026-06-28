// CategoryDetail — un panel de "Detalle por categoría" (wave 3).
// ═══════════════════════════════════════════════════════════════════════════
// Renderiza UNA categoría de data.categories_detail: header (icono + label +
// descripción + score /100 coloreado) y una lista de MetricRow.
//
// Cada métrica trae: { key, label, value, value_label, direction, status,
//   status_label, info }. direction: "higher" | "lower" | "info".
//   status: "green" | "amber" | "red" | "na".
//
// Reusa Panel, Pill, InfoTooltip y la lógica de color status→token.
//
// props:
//   icon      — componente lucide (opcional)
//   label     — nombre de la categoría
//   question  — descripción de una línea (opcional)
//   score     — 0-100 | null
//   metrics   — array de filas (ver arriba)

import Panel from '../Panel'
import Pill from '../Pill'
import InfoTooltip from '../InfoTooltip'

// status → { Pill tone, clase de barra, clase de texto del badge ya la da Pill }
const STATUS = {
  green: { tone: 'signal', bar: 'bg-rendi-pos' },
  amber: { tone: 'warn', bar: 'bg-rendi-warn' },
  red: { tone: 'red', bar: 'bg-rendi-neg' },
}

// Color del score grande del header (mismo umbral que CategoryScore).
function scoreColor(score) {
  if (score == null) return 'text-ink-3'
  if (score >= 70) return 'text-rendi-pos'
  if (score >= 40) return 'text-rendi-warn'
  return 'text-rendi-neg'
}

// Hint de dirección bajo el label.
function directionHint(direction) {
  if (direction === 'higher') return '↑ mayor es mejor'
  if (direction === 'lower') return '↓ menor es mejor'
  return null
}

// Ancho de la barra dentro de la categoría: por status (green=100, amber=60,
// red=28). Es un indicador visual del veredicto, no una escala numérica fina —
// evita comparaciones engañosas entre métricas de unidades distintas.
function barWidth(status) {
  if (status === 'green') return 100
  if (status === 'amber') return 60
  if (status === 'red') return 28
  return 0
}

function MetricRow({ metric }) {
  const { label, value_label, direction, status, status_label, info } = metric
  const hint = directionHint(direction)

  const isInfo = direction === 'info'
  const isMissing = value_label == null || value_label === '—'
  const s = STATUS[status]
  const showBadge = !isInfo && !isMissing && !!s && !!status_label
  const showBar = showBadge

  return (
    <div className="py-2.5">
      <div className="flex items-start justify-between gap-3">
        {/* Izquierda: label + tooltip + hint */}
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className={`text-sm leading-tight ${isMissing ? 'text-ink-3' : 'text-ink-1'}`}>
              {label}
            </span>
            {info && (
              <InfoTooltip label={label} size={12} align="left">
                <p>{info}</p>
              </InfoTooltip>
            )}
          </div>
          {hint && !isMissing && (
            <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mt-0.5">
              {hint}
            </p>
          )}
        </div>

        {/* Derecha: valor + badge */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className={`text-sm font-medium tabular ${isMissing ? 'text-ink-3' : 'text-ink-0'}`}>
            {isMissing ? '—' : value_label}
          </span>
          {showBadge && <Pill tone={s.tone}>{status_label}</Pill>}
        </div>
      </div>

      {/* Barra fina coloreada por status */}
      {showBar && (
        <div className="h-1 w-full rounded-full bg-bg-2 overflow-hidden mt-2">
          <div
            className={`h-full rounded-full ${s.bar}`}
            style={{ width: `${barWidth(status)}%`, transition: 'width 600ms ease-out' }}
          />
        </div>
      )}
    </div>
  )
}

export default function CategoryDetail({ icon: Icon, label, question, score, metrics = [], onAsk }) {
  const hasScore = typeof score === 'number' && !Number.isNaN(score)

  return (
    <Panel padding="lg" className="flex flex-col">
      <div className="flex items-start justify-between gap-3 pb-3 mb-1 border-b border-line">
        <div className="flex items-start gap-2 min-w-0">
          {Icon && (
            <span className="mt-0.5 text-ink-3 flex-shrink-0">
              <Icon size={16} strokeWidth={1.75} />
            </span>
          )}
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink-0 leading-tight">{label}</p>
            {question && (
              <p className="text-xs text-ink-3 mt-0.5 leading-snug">{question}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {onAsk && (
            <button
              type="button"
              onClick={onAsk}
              title="Analizar con el Coach IA"
              aria-label="Analizar esta categoría con el Coach IA"
              className="text-xs font-semibold text-data-violet hover:text-data-violet/80 px-2 py-1 rounded-md hover:bg-data-violet/10 transition-colors"
            >
              Analizar
            </button>
          )}
          <div className="flex items-baseline gap-0.5">
            <span className={`text-2xl font-semibold tabular leading-none ${scoreColor(score)}`}>
              {hasScore ? Math.round(score) : '—'}
            </span>
            {hasScore && <span className="text-xs text-ink-3">/100</span>}
          </div>
        </div>
      </div>

      <div className="divide-y divide-line">
        {metrics.map(m => (
          <MetricRow key={m.key} metric={m} />
        ))}
      </div>
    </Panel>
  )
}
