// MonthlyTeaser — banner compacto del mes en curso para embeber en Dashboard.
// ════════════════════════════════════════════════════════════════════════════
// Reemplaza al `<MonthlySummary>` que vivía embebido en el Dashboard (700+
// líneas de tabla editable, mezclando admin + visualización). En su lugar
// mostramos 1 strip horizontal con la métrica clave del mes en curso y un
// CTA "Ver reporte completo →" que linkea a /reportes.
//
// Patrón visual: hereda del banner de delta diario de Posiciones — icono
// direccional + amount + porcentaje + CTA. Cero scroll, alta info density.
//
// Comportamiento:
//   • Si hay data del mes actual         → muestra delta + %
//   • Si no hay data del mes              → no se renderiza (no agrega ruido)
//   • Color condicional verde / rojo según signo del delta

import { Link } from 'react-router-dom'
import { TrendingUp, TrendingDown, ArrowRight, Calendar } from 'lucide-react'
import useMonthlyData from '../hooks/useMonthlyData'
import { usd, pctSigned } from '../utils/format'

// Días restantes en el mes en curso (Date local del usuario).
// Devuelve number >= 0. Si el mes ya pasó (raro), devuelve 0.
function daysLeftInMonth(year, month) {
  const today = new Date()
  const isCurrentMonth = today.getFullYear() === year && (today.getMonth() + 1) === month
  if (!isCurrentMonth) return 0
  const lastDay = new Date(year, month, 0).getDate()
  return Math.max(0, lastDay - today.getDate())
}

export default function MonthlyTeaser() {
  // Reusamos el mismo hook de /reportes — con 'global' como default.
  // Esto incluye un re-fetch en cada mount del Dashboard, pero el costo es
  // bajo (los endpoints son cacheables del lado del browser).
  const { loading, years, hasAnyData } = useMonthlyData({ broker: 'global' })

  if (loading || !hasAnyData) return null

  // Mes en curso = primer mes del año actual con mayor `month` que también
  // sea el mes calendario de hoy. Si el último mes guardado NO es el mes
  // actual, igual mostramos lo último que tengamos (con copy ajustado).
  const todayY = new Date().getFullYear()
  const todayM = new Date().getMonth() + 1
  const yr = years.find(y => y.year === todayY)
  if (!yr || yr.months.length === 0) return null

  // Los meses vienen ordenados ascendentes (Enero → Diciembre). Tomamos el último.
  const lastMonth = yr.months[yr.months.length - 1]
  const isLive = lastMonth.month === todayM
  const daysLeft = isLive ? daysLeftInMonth(lastMonth.year, lastMonth.month) : null
  const isPositive = lastMonth.deltaUsd >= 0

  return (
    <Link
      to="/reportes"
      className={`group flex items-center gap-3 px-4 py-3 rounded border transition-colors mb-8 ${
        isPositive
          ? 'bg-rendi-pos/[0.04] border-rendi-pos/20 hover:border-rendi-pos/40'
          : 'bg-rendi-neg/[0.04] border-rendi-neg/20 hover:border-rendi-neg/40'
      }`}
    >
      <div className={`flex items-center justify-center w-8 h-8 rounded-sm flex-shrink-0 ${
        isPositive ? 'bg-rendi-pos/15 text-rendi-pos' : 'bg-rendi-neg/15 text-rendi-neg'
      }`}>
        {isPositive ? <TrendingUp size={16} strokeWidth={1.75} aria-hidden="true" /> : <TrendingDown size={16} strokeWidth={1.75} aria-hidden="true" />}
      </div>

      <div className="flex-1 min-w-0 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="label-mono inline-flex items-center gap-1.5">
          <Calendar size={11} strokeWidth={1.75} aria-hidden="true" />
          {lastMonth.name}{isLive ? ' en curso' : ' (último cierre)'}
        </span>
        <span className={`text-base font-semibold tabular ${
          isPositive ? 'text-rendi-pos' : 'text-rendi-neg'
        }`}>
          {isPositive ? '+' : '−'}USD {usd(Math.abs(lastMonth.deltaUsd))}
        </span>
        {lastMonth.source !== 'derived' && (
          <span className={`text-sm tabular ${
            isPositive ? 'text-rendi-pos/80' : 'text-rendi-neg/80'
          }`}>
            ({pctSigned(lastMonth.deltaPct / 100)})
          </span>
        )}
        {daysLeft != null && daysLeft > 0 && (
          <span className="text-xs text-ink-2 font-mono">
            {daysLeft} {daysLeft === 1 ? 'día' : 'días'} para cerrar
          </span>
        )}
      </div>

      <span className="flex-shrink-0 inline-flex items-center gap-1 text-xs text-ink-2 group-hover:text-rendi-accent transition-colors">
        Ver reporte
        <ArrowRight size={11} strokeWidth={1.75} className="group-hover:translate-x-0.5 transition-transform" aria-hidden="true" />
      </span>
    </Link>
  )
}
