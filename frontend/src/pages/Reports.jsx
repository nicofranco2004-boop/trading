// Reports — timeline financiera narrativa (Phase 1).
//
// Reemplaza la pantalla vieja MonthlyReports.jsx. Diseño:
//   - Header: PageHeader + BrokerSelector
//   - Para cada año: banda con label "2026" / "2025" + lista de meses
//   - Cada mes es un MonthCard premium (hero + insights + highlights + weeks colapsadas)
//
// Reglas de default expansion:
//   - Mes en curso: expandido + chips visibles
//   - Meses del año actual (cerrados): visibles, semanas colapsadas
//   - Años pasados: la banda muestra el delta resumen del año; los meses se
//     pueden expandir individualmente

import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import { Loader2, FileText, AlertTriangle } from 'lucide-react'
import useReportsTimeline from '../hooks/useReportsTimeline'
import BrokerSelector from '../components/reports/BrokerSelector'
import MonthCard from '../components/reports/MonthCard'

export default function Reports() {
  const [broker, setBroker] = useState('global')
  const { loading, error, yearGroups, hasAnyData } = useReportsTimeline(broker, 12)
  const todayYear = new Date().getFullYear()

  return (
    <div className="page-shell">
      <PageHeader
        title="Reportes"
        subtitle="Tu historia financiera, contada como timeline. Lo reciente con detalle, lo histórico condensado."
        action={<BrokerSelector value={broker} onChange={setBroker} />}
      />

      {error && (
        <div className="mb-4 flex items-start gap-2 px-3 py-2 rounded-sm bg-rendi-neg/10 border border-rendi-neg/20 text-rendi-neg text-sm">
          <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      {loading && (
        <div className="p-10 text-center text-ink-3">
          <Loader2 size={20} className="animate-spin mx-auto mb-2" aria-hidden="true" />
          <p className="text-sm">Armando tu timeline…</p>
        </div>
      )}

      {!loading && !error && !hasAnyData && (
        <EmptyState
          icon={<FileText size={20} />}
          title="Todavía no hay reportes"
          description="Importá un CSV o cargá un cierre mensual para que tu historia financiera empiece a poblarse acá."
        />
      )}

      {!loading && !error && hasAnyData && (
        <div className="space-y-8">
          {yearGroups.map(({ year, months }) => (
            <YearGroup
              key={year}
              year={year}
              months={months}
              isCurrentYear={year === todayYear}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ─── YearGroup ───────────────────────────────────────────────────────────────
// Banda con label del año + lista de meses.
// Año actual: meses con contenido expandido.
// Años pasados: meses minimal hasta que el user expanda.

function YearGroup({ year, months, isCurrentYear }) {
  // Calcular un resumen anual a partir de los meses (delta acumulado + flows)
  const summary = (() => {
    const sumDelta = months.reduce((s, m) => s + (m.metrics.delta_usd || 0), 0)
    const sumRealized = months.reduce((s, m) => s + (m.metrics.realized_pnl || 0), 0)
    const trades = months.reduce((s, m) => s + (m.metrics.trades_count || 0), 0)
    return { sumDelta, sumRealized, trades }
  })()

  return (
    <section>
      <header className="flex items-baseline justify-between gap-4 pb-3 mb-3 border-b border-line/40">
        <h2 className="font-display text-3xl text-ink-0 tracking-tight">{year}</h2>
        <div className="flex items-baseline gap-3 text-xs text-ink-3 font-mono tabular">
          <span>{months.length} {months.length === 1 ? 'mes' : 'meses'}</span>
          <span>·</span>
          <span>{summary.trades} trades</span>
          <span>·</span>
          <span className={summary.sumRealized >= 0 ? 'text-rendi-pos/80' : 'text-rendi-neg/80'}>
            {summary.sumRealized >= 0 ? '+' : '−'}US${Math.abs(summary.sumRealized).toLocaleString('es-AR', { maximumFractionDigits: 0 })} realizado
          </span>
        </div>
      </header>

      <div className="space-y-3">
        {months.map(m => (
          <MonthCard
            key={m.period_key}
            month={m}
            defaultExpanded={isCurrentYear}
          />
        ))}
      </div>
    </section>
  )
}
