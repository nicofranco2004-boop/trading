// MonthlyReportsPreview — prototipo NO funcional para validar dirección.
// ════════════════════════════════════════════════════════════════════════════
// Este archivo es DESCARTABLE. La data está hardcoded — cuando aprobemos
// el look, se reemplaza por las llamadas reales a /api/monthly + ops + sims.
//
// Ruta: /reportes-preview
//
// Lo que valida este prototipo:
//   • Cards por año expandibles (en vez de tabla)
//   • Cards de mes con jerarquía: delta grande + label-mono de status
//   • Modal de detalle con drivers + benchmarks + insights
//   • Que la separación 'reportes' vs 'cierre' tenga sentido visual
//
// Lo que NO valida (porque es mock):
//   • Performance con muchos años / meses (acá hay 3 años, 24 meses totales)
//   • Cálculos reales (drivers, benchmarks, insights data-driven)
//   • Edición / cierre de mes (eso vive en /mensual actual)

import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  TrendingUp, TrendingDown, ArrowRight, ChevronDown, ChevronUp,
  X, Calendar, Sparkles, BarChart3, Settings,
} from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import { usd, fmtUsd, pctSigned } from '../utils/format'

// ════════════════════════════════════════════════════════════════════════════
// MOCK DATA — borrar al implementar versión real.
// ════════════════════════════════════════════════════════════════════════════

const MOCK_YEARS = [
  {
    year: 2026,
    ytdPct: 16.3,
    ytdUsd: 1154,
    startUsd: 7144,
    endUsd: 8299,
    bestMonth: { name: 'Mayo', pct: 17.0 },
    worstMonth: { name: 'Febrero', pct: -3.4 },
    months: [
      mockMonth('2026-05', 'Mayo',     1189,  17.0,  6998, 8299, 112,  13.2, 'excellent', [
        { asset: 'BTC',  pnl: 540 },
        { asset: 'NVDA', pnl: 320 },
        { asset: 'SPY',  pnl: 180 },
      ], [{ asset: 'TSLA', pnl: -41 }], [
        'Tu cartera superó al S&P 500 por +13.2 puntos en el mes.',
        'BTC explica el 45% del rendimiento mensual — concentración alta de la ganancia.',
        'Sin las posiciones cripto, el mes habría cerrado en +5.5%.',
      ]),
      mockMonth('2026-04', 'Abril',       7,   0.1,  6991, 6998,  50,  -1.8, 'neutral', [
        { asset: 'NVDA', pnl: 210 },
      ], [{ asset: 'BTC', pnl: -85 }, { asset: 'TSLA', pnl: -120 }], [
        'Mes plano: el portfolio se sostuvo pese a corrección crypto.',
        'Aportes netos ($50) sostuvieron el resultado.',
      ]),
      mockMonth('2026-03', 'Marzo',     352,   5.3,  6639, 6991, 100,   2.1, 'positive', [
        { asset: 'SPY',  pnl: 220 },
        { asset: 'NVDA', pnl: 140 },
      ], [{ asset: 'GGAL', pnl: -25 }], [
        'Mes sólido apoyado en posiciones USA defensivas.',
        'Rendimiento alineado con el mercado en general.',
      ]),
      mockMonth('2026-02', 'Febrero',  -228,  -3.4,  6867, 6639,  20,  -0.9, 'difficult', [
        { asset: 'GGAL', pnl: 45 },
      ], [{ asset: 'BTC', pnl: -180 }, { asset: 'TSLA', pnl: -95 }], [
        'Drawdown moderado por exposición a mega-caps tech.',
        'BTC retrocedió 12% — fue el principal detractor.',
      ]),
      mockMonth('2026-01', 'Enero',     -166, -2.3,  7144, 6867,   0,   0.5, 'difficult', [
        { asset: 'NVDA', pnl: 80 },
      ], [{ asset: 'SPY', pnl: -120 }, { asset: 'BTC', pnl: -130 }], [
        'Arranque débil del año en línea con corrección global.',
      ]),
    ],
  },
  {
    year: 2025,
    ytdPct: 28.7,
    ytdUsd: 1597,
    startUsd: 5557,
    endUsd: 7144,
    bestMonth: { name: 'Noviembre', pct: 9.4 },
    worstMonth: { name: 'Marzo', pct: -5.1 },
    months: [
      mockMonth('2025-12', 'Diciembre', 380, 5.6, 6764, 7144, 0, 2.1, 'positive'),
      mockMonth('2025-11', 'Noviembre', 580, 9.4, 6184, 6764, 100, 6.2, 'excellent'),
      mockMonth('2025-10', 'Octubre',   -84, -1.4, 6268, 6184, 50, -2.0, 'difficult'),
      mockMonth('2025-09', 'Septiembre', 220, 3.6, 6048, 6268, 100, 1.5, 'positive'),
      mockMonth('2025-08', 'Agosto',    140, 2.4, 5908, 6048, 50, 0.8, 'positive'),
      mockMonth('2025-07', 'Julio',      80, 1.4, 5828, 5908, 0, -0.4, 'positive'),
      mockMonth('2025-06', 'Junio',     310, 5.6, 5518, 5828, 100, 3.2, 'positive'),
      mockMonth('2025-05', 'Mayo',      200, 3.7, 5318, 5518, 50, 1.1, 'positive'),
      mockMonth('2025-04', 'Abril',     -90, -1.7, 5408, 5318, 0, -2.5, 'difficult'),
      mockMonth('2025-03', 'Marzo',    -290, -5.1, 5698, 5408, 0, -4.8, 'difficult'),
      mockMonth('2025-02', 'Febrero',   180, 3.3, 5518, 5698, 50, 1.0, 'positive'),
      mockMonth('2025-01', 'Enero',     -39, -0.7, 5557, 5518, 0, -2.1, 'difficult'),
    ],
  },
  {
    year: 2024,
    ytdPct: 11.1,
    ytdUsd: 555,
    startUsd: 5002,
    endUsd: 5557,
    bestMonth: { name: 'Diciembre', pct: 6.8 },
    worstMonth: { name: 'Mayo', pct: -3.9 },
    months: [
      mockMonth('2024-12', 'Diciembre', 354, 6.8, 5203, 5557, 0, 2.0, 'positive'),
      mockMonth('2024-11', 'Noviembre', 110, 2.2, 5093, 5203, 50, 0.4, 'positive'),
      mockMonth('2024-10', 'Octubre',    91, 1.8, 5002, 5093, 0, -0.6, 'positive'),
    ],
  },
]

function mockMonth(period, name, deltaUsd, deltaPct, startUsd, endUsd, deposits, vsBenchmark, status, top, worst, insights) {
  return {
    period, name, deltaUsd, deltaPct, startUsd, endUsd, deposits, vsBenchmark, status,
    topContributors: top || [{ asset: 'NVDA', pnl: Math.round(deltaUsd * 0.5) }, { asset: 'BTC', pnl: Math.round(deltaUsd * 0.3) }],
    worstPositions: worst || [{ asset: 'TSLA', pnl: -Math.abs(Math.round(deltaUsd * 0.1)) }],
    insights: insights || [
      `Mes ${deltaPct >= 0 ? 'positivo' : 'difícil'} con cartera ${deltaPct >= 0 ? 'creciendo' : 'corrigiendo'} ${Math.abs(deltaPct).toFixed(1)}%.`,
    ],
  }
}

// ════════════════════════════════════════════════════════════════════════════
// Status config — el badge label-mono cambia según el delta del mes
// ════════════════════════════════════════════════════════════════════════════
const STATUS = {
  excellent: { label: 'Excelente',  badge: 'bg-rendi-pos/15 text-rendi-pos border-rendi-pos/30' },
  positive:  { label: 'Positivo',   badge: 'bg-rendi-pos/10 text-rendi-pos/80 border-rendi-pos/20' },
  neutral:   { label: 'Neutro',     badge: 'bg-bg-3 text-ink-2 border-line' },
  difficult: { label: 'Negativo',   badge: 'bg-rendi-neg/10 text-rendi-neg border-rendi-neg/30' },
}

// Color para la cifra principal
function deltaColor(deltaUsd) {
  if (deltaUsd > 50) return 'text-rendi-pos'
  if (deltaUsd < -50) return 'text-rendi-neg'
  return 'text-ink-1'
}

// ════════════════════════════════════════════════════════════════════════════
// Componente principal
// ════════════════════════════════════════════════════════════════════════════
export default function MonthlyReportsPreview() {
  // El año actual arranca expandido. Resto colapsados.
  const [expandedYear, setExpandedYear] = useState(2026)
  const [selectedMonth, setSelectedMonth] = useState(null)

  // Hero global = primer año (más reciente)
  const currentYear = MOCK_YEARS[0]

  return (
    <div className="page-shell">
      {/* Banner amarillo: queda claro que es preview */}
      <div className="mb-6 px-3 py-2 rounded-sm bg-rendi-warn/10 border border-rendi-warn/30 text-xs text-rendi-warn flex items-center gap-2">
        <Sparkles size={13} strokeWidth={1.75} />
        <span><b>Prototipo — data de ejemplo.</b> Validamos look antes de implementar con tu data real.</span>
      </div>

      <PageHeader
        title="Reportes mensuales"
        subtitle="Cómo se comportó tu portfolio mes a mes — narrativa, drivers e insights, sin tablas administrativas."
        action={
          <Link
            to="/mensual"
            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-sm bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 transition"
          >
            <Settings size={12} strokeWidth={1.75} />
            Cerrar mes en curso
          </Link>
        }
      />

      {/* ─── HERO YTD ───────────────────────────────────────────────── */}
      <div className="mb-8">
        <StatCard
          tone="hero"
          label={`Rendimiento ${currentYear.year}`}
          value={fmtUsd(currentYear.endUsd)}
          sub={
            <span className="inline-flex items-center gap-3 flex-wrap">
              <span className="text-ink-2">YTD</span>
              <span className={`inline-flex items-center gap-1 font-semibold ${currentYear.ytdUsd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                {currentYear.ytdUsd >= 0 ? <TrendingUp size={14} strokeWidth={1.5} aria-hidden="true" /> : <TrendingDown size={14} strokeWidth={1.5} aria-hidden="true" />}
                +USD {usd(currentYear.ytdUsd)}
              </span>
              <span className={`tabular ${currentYear.ytdUsd >= 0 ? 'text-rendi-pos/80' : 'text-rendi-neg/80'}`}>
                ({pctSigned(currentYear.ytdPct / 100)})
              </span>
            </span>
          }
          hint={`De ${fmtUsd(currentYear.startUsd)} a ${fmtUsd(currentYear.endUsd)} · Mejor mes: ${currentYear.bestMonth.name} (${pctSigned(currentYear.bestMonth.pct / 100)})`}
        />
      </div>

      {/* ─── LISTA DE AÑOS ──────────────────────────────────────────── */}
      <div className="space-y-4">
        {MOCK_YEARS.map(yr => (
          <YearCard
            key={yr.year}
            year={yr}
            isExpanded={expandedYear === yr.year}
            onToggle={() => setExpandedYear(expandedYear === yr.year ? null : yr.year)}
            onMonthClick={setSelectedMonth}
          />
        ))}
      </div>

      {/* ─── MODAL DETALLE MENSUAL ──────────────────────────────────── */}
      {selectedMonth && (
        <MonthDetailModal month={selectedMonth} onClose={() => setSelectedMonth(null)} />
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// YearCard — header del año (clickable) + grid de meses cuando expandido
// ════════════════════════════════════════════════════════════════════════════
function YearCard({ year, isExpanded, onToggle, onMonthClick }) {
  return (
    <section className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded overflow-hidden">
      {/* Header: año + summary del año */}
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-4 px-5 py-4 hover:bg-slate-50 dark:hover:bg-bg-2/50 transition-colors"
        aria-expanded={isExpanded}
      >
        <div className="flex items-baseline gap-4 min-w-0">
          <span className="font-display text-3xl text-ink-0 tracking-tight">{year.year}</span>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 min-w-0">
            <span className={`text-base font-semibold tabular ${year.ytdUsd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {pctSigned(year.ytdPct / 100)}
            </span>
            <span className={`text-sm tabular ${year.ytdUsd >= 0 ? 'text-rendi-pos/70' : 'text-rendi-neg/70'}`}>
              {year.ytdUsd >= 0 ? '+' : '−'}USD {usd(Math.abs(year.ytdUsd))}
            </span>
            <span className="text-xs text-ink-2 font-mono">
              {year.months.length} {year.months.length === 1 ? 'mes' : 'meses'} · mejor: {year.bestMonth.name}
            </span>
          </div>
        </div>
        <div className="flex-shrink-0 text-ink-3">
          {isExpanded ? <ChevronUp size={16} strokeWidth={1.75} /> : <ChevronDown size={16} strokeWidth={1.75} />}
        </div>
      </button>

      {/* Grid de meses */}
      {isExpanded && (
        <div className="border-t border-slate-200 dark:border-line p-4 sm:p-5 bg-slate-50/40 dark:bg-bg-2/30">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {year.months.map(m => (
              <MonthCard key={m.period} month={m} onClick={() => onMonthClick(m)} />
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// MonthCard — card chica de cada mes con delta + status badge
// ════════════════════════════════════════════════════════════════════════════
function MonthCard({ month, onClick }) {
  const status = STATUS[month.status] || STATUS.neutral
  const isPositive = month.deltaUsd >= 0
  return (
    <button
      onClick={onClick}
      className="text-left bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded p-4 hover:border-rendi-accent/40 dark:hover:border-rendi-accent/40 transition-colors group"
      aria-label={`Ver reporte de ${month.name}`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="label-mono">{month.name}</span>
        <span className={`text-[9px] font-mono uppercase tracking-[0.12em] px-1.5 py-0.5 rounded-sm border ${status.badge}`}>
          {status.label}
        </span>
      </div>
      <div className="flex items-baseline gap-2 mb-1">
        <span className={`text-xl font-medium num tabular tracking-tight ${deltaColor(month.deltaUsd)}`}>
          {isPositive ? '+' : '−'}USD {usd(Math.abs(month.deltaUsd))}
        </span>
      </div>
      <div className={`text-xs font-mono ${isPositive ? 'text-rendi-pos/80' : 'text-rendi-neg/80'}`}>
        {pctSigned(month.deltaPct / 100)}
      </div>
      <div className="mt-3 pt-3 border-t border-slate-100 dark:border-line/50 flex items-center justify-between text-[10px] font-mono text-ink-3">
        <span>{fmtUsd(month.startUsd).replace('+', '')} → {fmtUsd(month.endUsd).replace('+', '')}</span>
        <ArrowRight size={11} strokeWidth={1.75} className="text-ink-3 group-hover:text-rendi-accent transition-colors" />
      </div>
    </button>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// MonthDetailModal — la pantalla "real" del reporte mensual
// ════════════════════════════════════════════════════════════════════════════
function MonthDetailModal({ month, onClose }) {
  const isPositive = month.deltaUsd >= 0

  // Mock chart de evolución del mes (simula valor diario)
  const chartData = generateMonthChart(month.startUsd, month.endUsd)

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded-t-2xl sm:rounded w-full max-w-3xl shadow-2xl max-h-[95vh] sm:max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-slate-200 dark:border-line flex-shrink-0">
          <div className="min-w-0">
            <p className="eyebrow mb-1">Reporte mensual</p>
            <h2 className="text-xl font-semibold text-ink-0">{month.name} {month.period.slice(0, 4)}</h2>
          </div>
          <button onClick={onClose} className="text-ink-3 hover:text-ink-0 -mt-1 -mr-1 p-1" aria-label="Cerrar reporte">
            <X size={18} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>

        {/* Contenido scrolleable */}
        <div className="overflow-y-auto flex-1 p-5 space-y-6">

          {/* Hero del mes */}
          <div className="flex items-start gap-4">
            <div className={`flex-shrink-0 w-10 h-10 rounded-sm flex items-center justify-center ${
              isPositive ? 'bg-rendi-pos/15 text-rendi-pos' : 'bg-rendi-neg/15 text-rendi-neg'
            }`}>
              {isPositive ? <TrendingUp size={20} strokeWidth={1.75} /> : <TrendingDown size={20} strokeWidth={1.75} />}
            </div>
            <div className="flex-1 min-w-0">
              <p className={`text-2xl font-medium num tabular tracking-tight ${deltaColor(month.deltaUsd)}`}>
                {isPositive ? '+' : '−'}USD {usd(Math.abs(month.deltaUsd))}
                <span className={`ml-3 text-base ${isPositive ? 'text-rendi-pos/80' : 'text-rendi-neg/80'}`}>
                  ({pctSigned(month.deltaPct / 100)})
                </span>
              </p>
              <p className="text-xs text-ink-2 mt-1 font-mono">
                {fmtUsd(month.startUsd).replace('+', '')} → {fmtUsd(month.endUsd).replace('+', '')} · aportes netos {fmtUsd(month.deposits)}
              </p>
            </div>
          </div>

          {/* Chart 1 solo */}
          <section>
            <p className="eyebrow mb-2">Evolución</p>
            <div className="bg-slate-50/40 dark:bg-bg-2/40 rounded p-3" style={{ height: 180 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="#222636" strokeOpacity={0.5} strokeDasharray="2 4" vertical={false} />
                  <XAxis dataKey="day" tick={{ fill: '#8B8D8A', fontSize: 10, fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
                  <YAxis hide domain={['dataMin - 100', 'dataMax + 100']} />
                  <Tooltip
                    cursor={{ stroke: '#5A5C5B', strokeWidth: 1, strokeDasharray: '3 3' }}
                    contentStyle={{ background: '#101218', border: '1px solid #2C3142', borderRadius: 6, padding: '6px 10px', fontFamily: 'JetBrains Mono', fontSize: 11 }}
                    formatter={(v) => [fmtUsd(v), 'Valor']}
                    labelFormatter={l => `Día ${l}`}
                  />
                  <Line type="monotone" dataKey="value" stroke={isPositive ? '#6FE3A3' : '#F17A7A'} strokeWidth={1.75} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          {/* Drivers */}
          <section>
            <p className="eyebrow mb-3">Qué explicó el resultado</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <h4 className="text-xs font-semibold text-ink-2 mb-2 uppercase tracking-wider">A favor</h4>
                <ul className="space-y-1.5">
                  {month.topContributors.map(c => (
                    <li key={c.asset} className="flex items-center justify-between text-sm">
                      <span className="font-medium text-ink-1">{c.asset}</span>
                      <span className="font-mono tabular text-rendi-pos font-semibold">+USD {usd(c.pnl)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h4 className="text-xs font-semibold text-ink-2 mb-2 uppercase tracking-wider">En contra</h4>
                <ul className="space-y-1.5">
                  {month.worstPositions.map(c => (
                    <li key={c.asset} className="flex items-center justify-between text-sm">
                      <span className="font-medium text-ink-1">{c.asset}</span>
                      <span className="font-mono tabular text-rendi-neg font-semibold">−USD {usd(Math.abs(c.pnl))}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </section>

          {/* Benchmarks */}
          <section>
            <p className="eyebrow mb-3">Versus benchmarks</p>
            <div className="bg-slate-50/40 dark:bg-bg-2/40 rounded border border-slate-200 dark:border-line overflow-hidden">
              <div className="grid grid-cols-3 divide-x divide-slate-200 dark:divide-line">
                <div className="p-3">
                  <p className="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-2">Tu portfolio</p>
                  <p className={`text-base font-semibold tabular mt-1 ${isPositive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                    {pctSigned(month.deltaPct / 100)}
                  </p>
                </div>
                <div className="p-3">
                  <p className="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-2">S&amp;P 500</p>
                  <p className="text-base font-semibold tabular mt-1 text-ink-1">
                    {pctSigned((month.deltaPct - month.vsBenchmark) / 100)}
                  </p>
                </div>
                <div className="p-3">
                  <p className="text-[10px] font-mono uppercase tracking-[0.12em] text-ink-2">Diferencia</p>
                  <p className={`text-base font-semibold tabular mt-1 ${month.vsBenchmark >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                    {pctSigned(month.vsBenchmark / 100)}
                  </p>
                </div>
              </div>
              <div className={`px-3 py-2 text-xs ${month.vsBenchmark >= 0 ? 'text-rendi-pos bg-rendi-pos/[0.04]' : 'text-rendi-neg bg-rendi-neg/[0.04]'} border-t border-slate-200 dark:border-line`}>
                {month.vsBenchmark >= 5 ? 'Superaste ampliamente al mercado.' :
                 month.vsBenchmark >= 0 ? 'Superaste al mercado.' :
                 month.vsBenchmark >= -5 ? 'Rendiste por debajo del mercado.' :
                 'Rendiste sustancialmente por debajo del mercado.'}
              </div>
            </div>
          </section>

          {/* Insights */}
          {month.insights.length > 0 && (
            <section>
              <p className="eyebrow mb-3">Insights</p>
              <ul className="space-y-2">
                {month.insights.map((ins, i) => (
                  <li key={i} className="flex items-start gap-2.5 text-sm text-ink-1 leading-snug">
                    <Sparkles size={12} strokeWidth={1.75} className="flex-shrink-0 mt-1 text-rendi-accent" />
                    <span>{ins}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

        </div>
      </div>
    </div>
  )
}

// Genera serie de chart simulada (lineal con ruido) entre startUsd y endUsd
function generateMonthChart(startUsd, endUsd) {
  const days = 22  // ~días hábiles del mes
  const data = []
  const totalChange = endUsd - startUsd
  for (let i = 0; i <= days; i++) {
    const linearProgress = i / days
    const noise = (Math.sin(i * 0.7) * 0.5 + Math.cos(i * 1.3) * 0.3) * (Math.abs(totalChange) * 0.15)
    data.push({
      day: i + 1,
      value: Math.round(startUsd + (totalChange * linearProgress) + noise),
    })
  }
  return data
}
