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
import { ArrowRight } from 'lucide-react'
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

  // Chips: uno por benchmark, con tono propio. El monto va en el title
  // (hover) para no saturar la línea.
  function fmtSegment(d, name) {
    const sign = d.delta >= 0 ? '+' : '−'
    return {
      ref: name,
      pct: `${sign}${Math.abs(d.pct).toFixed(1)}%`,
      pos: d.delta >= 0,
      amount: `${sign}USD ${usd(Math.abs(d.delta), 0)} vs ${name}`,
    }
  }

  const segments = []
  if (vsSp) segments.push(fmtSegment(vsSp, 'el S&P 500'))
  if (vsDolar) segments.push(fmtSegment(vsDolar, 'el dólar quieto'))

  return (
    <div className={`flex items-center gap-2 flex-wrap ${className}`}>
      {segments.map((s, i) => (
        <span
          key={i}
          className="inline-flex items-center gap-1.5 text-[12px] text-ink-2 bg-bg-1 border border-line rounded-full px-2.5 py-1 tabular"
          title={s.amount}
        >
          vs {s.ref}
          <b className={`font-semibold ${s.pos ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{s.pct}</b>
        </span>
      ))}
      <Link
        to="/insights"
        className="text-[12.5px] text-rendi-accent hover:text-rendi-accent/80 inline-flex items-center gap-0.5 transition-colors font-medium"
      >
        Ver comparativa <ArrowRight size={11} strokeWidth={1.75} />
      </Link>
    </div>
  )
}
