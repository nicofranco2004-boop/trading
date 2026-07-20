// WeekCard — child de MonthCard. Compacto, behavioral.
//
// Default: colapsado a 1 línea (week label + delta + headline).
// Expandido: muestra insights + drivers.
//
// Si is_relevant=false (sin movimientos), se renderiza minimal y deshabilitado.

import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import InsightChip from './InsightChip'
import { useMoneyFormat } from '../../contexts/CurrencyContext'

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : '−'
  return `${sign}${Math.abs(p).toFixed(2)}%`
}

export default function WeekCard({ week }) {
  const [open, setOpen] = useState(false)
  // Con % None (semana per-broker) la polaridad sale del SIGNO del USD — antes
  // `undefined >= 0` era false pero `null >= 0` es TRUE en JS → verde en pérdidas.
  const positive = week.metrics.delta_pct != null
    ? week.metrics.delta_pct >= 0
    : (week.metrics.delta_usd ?? 0) >= 0
  // Fase B: delta_usd y realized_pnl respetan el toggle global ARS/USD.
  const money = useMoneyFormat()
  const fmtUsd = (v) => money.fmtMoney(v, { signed: true })

  // Sin actividad: chip minimal, no expandible
  if (!week.is_relevant) {
    return (
      <div className="px-3 py-2 rounded-sm border border-line/50 bg-bg-2/20 flex items-center gap-3 text-xs text-ink-3">
        <span className="font-mono">{week.period_label}</span>
        <span className="flex-1">Sin movimientos</span>
      </div>
    )
  }

  return (
    <div className="rounded-sm border border-line bg-bg-2/40">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-3 py-2 hover:bg-bg-3/40 transition-colors text-left"
        aria-expanded={open}
      >
        <span className="text-xs font-mono text-ink-2 min-w-[80px]">{week.period_label}</span>
        <span className={`text-xs font-semibold tabular min-w-[64px] ${positive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
          {fmtPct(week.metrics.delta_pct)}
        </span>
        <span className="text-xs text-ink-2 flex-1 truncate" title={week.headline}>
          {week.headline}
        </span>
        <span className="text-[10px] text-ink-3 font-mono tabular">
          {fmtUsd(week.metrics.delta_usd)}
        </span>
        {open
          ? <ChevronUp size={14} className="text-ink-3" strokeWidth={1.75} aria-hidden="true" />
          : <ChevronDown size={14} className="text-ink-3" strokeWidth={1.75} aria-hidden="true" />}
      </button>

      {open && (
        <div className="border-t border-line/50 px-3 py-3 space-y-2.5">
          {week.subheadline && (
            <p className="text-xs text-ink-2 leading-relaxed">{week.subheadline}</p>
          )}
          {week.insights && week.insights.length > 0 && (
            <div className="space-y-1.5">
              {week.insights.map((ins, i) => (
                <InsightChip key={ins.code + i} insight={ins} />
              ))}
            </div>
          )}
          <div className="grid grid-cols-3 gap-2 text-[10px]">
            <Stat label="Trades" value={week.metrics.trades_count} />
            <Stat label="Win rate" value={week.metrics.win_rate != null ? `${week.metrics.win_rate.toFixed(0)}%` : '—'} />
            <Stat label="Realizado" value={fmtUsd(week.metrics.realized_pnl)} />
          </div>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="rounded-sm bg-bg-3/40 px-2 py-1.5">
      <div className="text-ink-3 text-[12.5px] font-medium">{label}</div>
      <div className="text-ink-1 font-mono tabular text-[11px]">{value}</div>
    </div>
  )
}
