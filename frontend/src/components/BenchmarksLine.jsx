// BenchmarksLine.jsx
// ──────────────────
// Versión liviana de "Cómo voy vs el mundo" para el Dashboard / Home mobile.
// Una sola línea con los 2 benchmarks más relevantes (S&P 500 + dólar quieto),
// con monto absoluto entre paréntesis, y link a /insights para el detalle.
//
// Por qué esta versión y no la card completa de BenchmarksCard:
// la card completa duplicaba la "Comparativa con benchmarks" que ya existe
// en /insights (cards grandes con valor del benchmark, contexto, etc.). Esto
// es solo el headline — el detalle vive en /insights.
//
// Edge cases:
//   • Sin monthly global entries → no renderiza.
//   • Sin bench data (cache miss) → renderiza solo "vs dólar quieto" (no necesita bench).
//   • Outliers del cálculo (pct > 500% o bench ≤ $1) → ese benchmark se omite.

import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { TrendingUp, TrendingDown, ArrowRight } from 'lucide-react'
import { simulateSp500, simulateDolarCash } from '../utils/benchmarkSim'
import { usd } from '../utils/format'

const MIN_SIGNIFICANT_BENCH_USD = 1
const MAX_DISPLAY_PCT = 500

export default function BenchmarksLine({ monthly, bench, totalPortfolio, className = '' }) {
  const globalMonthly = useMemo(
    () => (monthly || []).filter(m => m.broker === 'global'),
    [monthly]
  )

  const sp500Sim = useMemo(
    () => simulateSp500(globalMonthly, bench?.sp500),
    [globalMonthly, bench]
  )
  const dolarSim = useMemo(
    () => simulateDolarCash(globalMonthly),
    [globalMonthly]
  )

  // Computa delta vs benchmark. Retorna null si no hay data significativa.
  function deltaVs(benchFinal) {
    if (benchFinal == null || !(totalPortfolio > 0)) return null
    if (benchFinal <= MIN_SIGNIFICANT_BENCH_USD) return null
    const delta = totalPortfolio - benchFinal
    const pct = (delta / benchFinal) * 100
    if (Math.abs(pct) > MAX_DISPLAY_PCT) return null
    return { delta, pct }
  }

  const vsSp = sp500Sim ? deltaVs(sp500Sim.finalValue) : null
  const vsDolar = dolarSim ? deltaVs(dolarSim.finalValue) : null

  // Si no hay nada para mostrar, no renderizar.
  if (globalMonthly.length === 0) return null
  if (!vsSp && !vsDolar) return null

  // Tono general: positivo si ganó a TODOS los benchmarks disponibles.
  // Negativo si perdió a todos. Neutral si es mixto.
  const both = [vsSp, vsDolar].filter(Boolean)
  const allPositive = both.every(d => d.delta >= 0)
  const allNegative = both.every(d => d.delta < 0)
  const tone = allPositive ? 'positive' : allNegative ? 'negative' : 'neutral'

  // Build segments
  function fmtSegment(d, name) {
    const word = d.delta >= 0 ? 'más' : 'menos'
    const sign = d.delta >= 0 ? '+' : '−'
    return {
      pct: `${Math.abs(d.pct).toFixed(1)}% ${word}`,
      ref: name,
      amount: `${sign}USD ${usd(Math.abs(d.delta), 0)}`,
    }
  }

  const segments = []
  if (vsSp) segments.push(fmtSegment(vsSp, 'el S&P 500'))
  if (vsDolar) segments.push(fmtSegment(vsDolar, 'el dólar quieto'))

  const toneClass = {
    positive: 'text-rendi-pos border-rendi-pos/30 bg-rendi-pos/[0.05]',
    negative: 'text-rendi-neg border-rendi-neg/30 bg-rendi-neg/[0.05]',
    neutral:  'text-ink-1 border-line bg-bg-1',
  }[tone]

  const icon = allPositive ? <TrendingUp size={14} strokeWidth={1.75} /> :
               allNegative ? <TrendingDown size={14} strokeWidth={1.75} /> :
               null

  return (
    <div className={`flex items-start gap-2 px-3 py-2 rounded-lg border text-sm leading-snug ${toneClass} ${className}`}>
      {icon && <span className="flex-shrink-0 mt-0.5">{icon}</span>}
      <span className="flex-1 min-w-0">
        Tu cartera rindió{' '}
        {segments.map((s, i) => (
          <span key={i}>
            <strong className="font-semibold">{s.pct}</strong> que {s.ref}{' '}
            <span className="text-ink-3 font-mono text-[12px]">({s.amount})</span>
            {i < segments.length - 1 && <span> y </span>}
          </span>
        ))}
        .{' '}
        <Link
          to="/insights"
          className="text-[12.5px] text-ink-2 hover:text-ink-0 inline-flex items-center gap-0.5 ml-1 transition-colors font-medium"
        >
          Ver detalle <ArrowRight size={11} strokeWidth={1.75} />
        </Link>
      </span>
    </div>
  )
}
