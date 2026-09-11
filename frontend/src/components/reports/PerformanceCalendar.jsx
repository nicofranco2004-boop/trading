// PerformanceCalendar — overview visual fuerte de Reportes (V2).
// ═══════════════════════════════════════════════════════════════════════════
// Dos piezas:
//   1) KPI strip 12M (acumulado realizado, meses positivos, mejor/peor, trades)
//   2) Calendario heatmap por año — bandas con 12 cuadrados (ENE-DIC)
//      coloreados según delta_pct mensual. Escala 7 pasos + neutro + sin datos.
//
// Visual: tipografía mono operativa, celdas con altura generosa, colores
// con buen contraste sobre bg-bg-1.

import { Link } from 'react-router-dom'
import { Lock } from 'lucide-react'
import { useMoneyFormat } from '../../contexts/CurrencyContext'

const MONTH_SHORT = ['ENE', 'FEB', 'MAR', 'ABR', 'MAY', 'JUN', 'JUL', 'AGO', 'SEP', 'OCT', 'NOV', 'DIC']

function monthNum(period_key) {
  if (!period_key) return null
  const m = period_key.match(/-(\d{1,2})/)
  return m ? parseInt(m[1], 10) : null
}

// ─── Color bins (7 niveles + neutro + sin datos) ─────────────────────────────
// Colores con buen contraste sobre bg-bg-1. Texto adapta al fondo.
function colorForCell(pct, hasData) {
  if (!hasData) {
    return {
      bg: 'transparent',
      border: '1px dashed rgba(255,255,255,0.06)',
      label: '#5A6478',
      value: '#5A6478',
    }
  }
  if (pct == null || Math.abs(pct) < 0.5) {
    return { bg: '#1B2230', border: 'none', label: '#9CA3B5', value: '#C3CAD8' }
  }
  if (pct >= 5)    return { bg: '#21D07A', border: 'none', label: '#06160E', value: '#06160E' }
  if (pct >= 2)    return { bg: '#14A560', border: 'none', label: '#E6EAF2', value: '#E6EAF2' }
  if (pct > 0)     return { bg: '#0F5C36', border: 'none', label: '#C3CAD8', value: '#5FE19D' }
  if (pct <= -5)   return { bg: '#FF5360', border: 'none', label: '#1F0A0C', value: '#1F0A0C' }
  if (pct <= -2)   return { bg: '#C8333E', border: 'none', label: '#E6EAF2', value: '#E6EAF2' }
  return            { bg: '#8E2B33', border: 'none', label: '#C3CAD8', value: '#FFB1B7' }
}

function fmtPctValue(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  // Compacto: enteros para >=10, 1 decimal para <10
  const abs = Math.abs(p)
  return `${sign}${abs >= 10 ? p.toFixed(0) : p.toFixed(2)}`
}

// fmtUsdSigned reemplazado por money.fmtMoney(v, { signed: true }) en el
// componente — respeta el toggle global ARS/USD (Fase B).

// ─── KPI strip data ──────────────────────────────────────────────────────────
function computeKpis(yearGroups) {
  const allMonths = yearGroups
    .flatMap(g => g.months)
    .filter(m => m.is_relevant && m.metrics)
  const sorted = [...allMonths].sort((a, b) => (a.period_key < b.period_key ? 1 : -1))
  const last12 = sorted.slice(0, 12)
  if (last12.length === 0) return null

  const realizedSum = last12.reduce((s, m) => s + (m.metrics.realized_pnl || 0), 0)
  const trades = last12.reduce((s, m) => s + (m.metrics.trades_count || 0), 0)
  const positiveCount = last12.filter(m => (m.metrics.delta_pct || 0) > 0).length

  let best = null, worst = null
  for (const m of last12) {
    if (m.metrics.delta_pct == null) continue
    if (!best  || m.metrics.delta_pct > best.metrics.delta_pct)  best  = m
    if (!worst || m.metrics.delta_pct < worst.metrics.delta_pct) worst = m
  }
  return { realizedSum, trades, positiveCount, totalCount: last12.length, best, worst }
}

function KpiCell({ label, value, sub, tone, first }) {
  const valueColor =
    tone === 'pos' ? 'text-rendi-pos' :
    tone === 'neg' ? 'text-rendi-neg' :
    'text-ink-0'
  return (
    <div className={`px-4 py-3 flex-1 min-w-[140px] ${first ? '' : 'border-l border-line/50'}`}>
      <div className="text-[12.5px] text-ink-2 leading-none font-medium">
        {label}
      </div>
      <div className={`mt-2 font-medium tabular num leading-none text-2xl tracking-tight ${valueColor}`}>
        {value}
      </div>
      <div className="text-[12.5px] text-ink-2 mt-1.5 leading-none truncate font-medium">
        {sub}
      </div>
    </div>
  )
}

// ─── Veredicto contra un benchmark ───────────────────────────────────────────
// `pp` es el EXCESO en puntos porcentuales (cartera − benchmark), no el retorno
// del índice. Sin dato no se dibuja nada: un "—" por año ocupa lugar y no dice
// más que el vacío.
function Veredicto({ nombre, articulo, pp }) {
  if (pp == null) return null
  const gana = pp >= 0
  const de = articulo === 'el' ? 'del' : 'de la'
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] text-ink-2 bg-bg-2 border border-line-2 rounded-full px-2.5 py-1 tabular whitespace-nowrap"
      title={`${gana ? 'Por encima' : 'Por debajo'} ${de} ${nombre} por ${Math.abs(pp).toFixed(1)} puntos porcentuales`}
    >
      vs {nombre}
      <b className={`font-semibold ${gana ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
        {gana ? '+' : '−'}{Math.abs(pp).toFixed(1)} pp
      </b>
    </span>
  )
}

// dd/mm/aa — corto pero sin perder el año, que es lo que distingue las dos
// puntas de una ventana anual.
function fmtFechaCorta(iso) {
  if (!iso || iso.length < 10) return iso || ''
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(2, 4)}`
}

// ─── La fila de métricas del año ─────────────────────────────────────────────
// Lo que Reportes ya calculaba para el año en curso y sólo mostraba ahí. Los
// meses en verde y el mejor/peor salen de las celdas que ya están dibujadas
// arriba, así que describen exactamente lo que el usuario tiene delante.
function Dato({ label, valor, tono }) {
  const color = tono === 'pos' ? 'text-rendi-pos' : tono === 'neg' ? 'text-rendi-neg' : 'text-ink-1'
  return (
    <div className="flex flex-col gap-0.5 min-w-[92px]">
      <span className="text-[10.5px] text-ink-3 font-medium leading-none">{label}</span>
      <span className={`text-[13px] font-semibold tabular leading-none ${color}`}>{valor}</span>
    </div>
  )
}

function MetricasDelAno({ resumen, months, money }) {
  if (!resumen) return null
  const conDato = months.filter(m => m.is_relevant && m.metrics?.delta_pct != null)
  const pcts = conDato.map(m => m.metrics.delta_pct)
  const verdes = pcts.filter(p => p > 0).length
  const datos = []
  if (resumen.sp500_return_pct != null) {
    datos.push({ label: 'S&P 500 ese año',
                 valor: `${resumen.sp500_return_pct >= 0 ? '+' : '−'}${Math.abs(resumen.sp500_return_pct).toFixed(1)}%` })
  }
  if (resumen.inflation_pct != null) {
    datos.push({ label: 'Inflación AR', valor: `+${resumen.inflation_pct.toFixed(1)}%` })
  }
  if (resumen.deposits > 0) {
    datos.push({ label: 'Aportaste', valor: money.fmtMoney(resumen.deposits) })
  }
  if (resumen.withdrawals > 0) {
    datos.push({ label: 'Retiraste', valor: money.fmtMoney(resumen.withdrawals) })
  }
  if (resumen.realized_pnl) {
    datos.push({ label: 'P&L realizado', valor: money.fmtMoney(resumen.realized_pnl, { signed: true }),
                 tono: resumen.realized_pnl >= 0 ? 'pos' : 'neg' })
  }
  if (resumen.trades_count > 0) {
    datos.push({ label: 'Operaciones', valor: `${resumen.trades_count} cerradas` })
    if (resumen.win_rate != null) {
      datos.push({ label: 'Win rate', valor: `${resumen.win_rate.toFixed(0)}%` })
    }
  }
  if (pcts.length > 0) {
    datos.push({ label: 'Meses en verde', valor: `${verdes} de ${pcts.length}` })
    const mejor = Math.max(...pcts), peor = Math.min(...pcts)
    datos.push({ label: 'Mejor mes', valor: `+${mejor.toFixed(1)}%`, tono: 'pos' })
    if (peor < 0) datos.push({ label: 'Peor mes', valor: `−${Math.abs(peor).toFixed(1)}%`, tono: 'neg' })
  }
  // Sin un solo dato la fila no se dibuja: un separador vacío bajo cada año es
  // ruido que el ojo tiene que descartar en cada pasada.
  if (datos.length === 0) return null
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-2.5 pl-[120px] pt-2.5 border-t border-line/50">
      {datos.map((d, i) => <Dato key={i} {...d} />)}
      {resumen.bench_desde && resumen.bench_hasta && (
        // ⚠️ CON AÑO. Sin él, un año cerrado se leía "comparado del 31/12 al
        // 31/12" — dos fechas idénticas que sugieren un solo día, cuando son los
        // dos extremos del año. La ventana existe justamente para poder leerla.
        <span className="text-[10.5px] text-ink-3 self-end leading-none">
          comparado del {fmtFechaCorta(resumen.bench_desde)} al {fmtFechaCorta(resumen.bench_hasta)}
        </span>
      )}
    </div>
  )
}

export default function PerformanceCalendar({ yearGroups, years = [], yearsLoading = false,
                                             historicos = true }) {
  const kpis = computeKpis(yearGroups)
  // Fase B: el P&L Realizado 12M respeta el toggle global ARS/USD.
  // Los % no cambian (son ratios) — solo el valor monetario se convierte.
  const money = useMoneyFormat()
  if (!kpis) return null

  return (
    <section className="mb-6 space-y-3">
      {/* ── KPI strip ── */}
      <div className="border border-line rounded-xl bg-bg-1 flex flex-wrap">
        <KpiCell
          first
          label="P&L Realizado · 12M"
          value={money.fmtMoney(kpis.realizedSum, { signed: true })}
          tone={kpis.realizedSum >= 0 ? 'pos' : 'neg'}
          sub={`${kpis.totalCount} ${kpis.totalCount === 1 ? 'mes activo' : 'meses activos'}`}
        />
        <KpiCell
          label="Meses positivos"
          value={`${kpis.positiveCount}/${kpis.totalCount}`}
          sub={
            kpis.totalCount > 0
              ? `${Math.round((kpis.positiveCount / kpis.totalCount) * 100)}% en verde`
              : '—'
          }
        />
        <KpiCell
          label="Trades · 12M"
          value={kpis.trades.toLocaleString('es-AR')}
          sub="operaciones cerradas"
        />
      </div>

      {/* ── Calendar heatmap ── */}
      <div className="border border-line rounded-xl bg-bg-1 overflow-hidden">
        <header className="flex items-center justify-between px-4 py-2.5 border-b border-line">
          <div className="flex items-center gap-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-rendi-pos" aria-hidden="true" />
            <span className="text-[12.5px] text-ink-0 font-medium">
              Calendario de performance
            </span>
            <span className="text-[12.5px] text-ink-2 ml-1 font-medium">
              / TWR mensual
            </span>
          </div>
          <span className="text-[12.5px] text-ink-2 font-medium">
            {yearGroups.length} {yearGroups.length === 1 ? 'año' : 'años'} cargados
          </span>
        </header>

        {/* ⚠️ SCROLL, NO RECORTE. La card de afuera lleva `overflow-hidden`, así que
            sin esto las bandas angostas se CORTABAN: en 554px de ancho, noviembre,
            diciembre y los chips de veredicto desaparecían sin ninguna señal. Doce
            meses más el cierre no entran en un teléfono, y el contrato del repo ya
            marca este archivo como sitio de riesgo por sus anchos fijos. */}
        <div className="px-4 py-5 space-y-5 overflow-x-auto">
          {yearGroups.map(({ year, months }) => {
            const cells = Array.from({ length: 12 }, (_, idx) => {
              const m = months.find(mm => monthNum(mm.period_key) === idx + 1)
              return { idx, month: m }
            })
            // ⚠️ ACÁ VIVÍA UN SEGUNDO MOTOR DEL RENDIMIENTO ANUAL, Y CONTRADECÍA AL
            // PRIMERO. Componía los meses que la timeline hubiera traído y contaba
            // los ausentes como +0% (factor 1). Con la timeline en 12 meses, el año
            // anterior sólo tenía sus últimos meses cargados: medido en la cuenta de
            // prueba, 2025 publicaba "+6,50%" acá mientras el motor canónico mide
            // +32,95% — 26 puntos de diferencia para el mismo año, y el rótulo de
            // arriba diciendo "TWR mensual" como si fuera lo mismo.
            // Ahora el número viene de `/api/reports/years` (`twr.curva_indexada`),
            // que es el mismo que publica la pestaña Año y el inicio.
            const resumen = years.find(a => a.year === year) || null
            const pct = resumen?.pct
            // ⚠️ "BLOQUEADO" NO ES "SIN MEDIR". Sin el resumen —porque el plan no
            // lo incluye— la fila diría "sin fotos a precio de mercado", que es
            // falso: el número existe y está del otro lado del muro. Decirle al
            // usuario que le faltan datos cuando lo que le falta es el plan es la
            // peor de las dos mentiras posibles.
            const bloqueado = !historicos && !resumen
            return (
              <div key={year} className="space-y-2.5 min-w-[880px]">
              <div className="flex items-center gap-4">
                <div className="min-w-[104px] flex flex-col gap-1">
                  <span className="font-mono text-[12px] tracking-label text-ink-3 tabular">
                    {year}{resumen?.is_current ? ' · hasta hoy' : ''}
                  </span>
                  {pct != null ? (
                    <span className={`text-[22px] font-semibold tracking-tight leading-none tabular ${
                      resumen.basis === 'contable' ? 'text-ink-1'
                        : pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                      {pct >= 0 ? '+' : '−'}{Math.abs(pct).toFixed(2)}%
                    </span>
                  ) : bloqueado ? (
                    <Link to="/planes" className="inline-flex items-center gap-1.5 text-[13px] text-rendi-accent hover:text-rendi-accent/80 font-medium leading-none">
                      <Lock size={12} strokeWidth={2} /> Ver {year}
                    </Link>
                  ) : (
                    <span className="text-[13px] text-ink-3 font-medium leading-none">
                      {yearsLoading ? '…' : 'Sin medir'}
                    </span>
                  )}
                  <span className="text-[10.5px] text-ink-3 leading-tight">
                    {bloqueado
                      ? 'los años anteriores están en el plan pago'
                      : pct == null
                        ? (resumen?.motivo_texto ? 'el motor no publica este año' : 'sin fotos a precio de mercado')
                        : resumen.basis === 'contable'
                          ? 'de tu historia importada'
                          : 'medido a precio de mercado'}
                  </span>
                </div>
                <div className="grid grid-cols-12 gap-1.5 flex-1">
                  {cells.map(({ idx, month }) => {
                    const pct = month?.metrics?.delta_pct
                    const hasData = !!month && month.is_relevant && pct != null
                    const c = colorForCell(pct, hasData)
                    const isCurrent = month?.is_current
                    return (
                      <div
                        key={idx}
                        title={month ? `${month.period_label}: ${fmtPctValue(pct)}%` : `${MONTH_SHORT[idx]}: sin datos`}
                        // ⚠️ SIN PROPORCIÓN FIJA. Con `aspect-[1.4/1]` + `min-h-[56px]`
                        // la celda EXIGE 78px de ancho: cuando su columna daba menos
                        // —doce columnas más el cierre del año no entran en una
                        // laptop— el cuadrado se salía de su lugar y pisaba al de al
                        // lado. El alto ahora lo fija `min-h` y el ancho lo pone la
                        // columna, que es quien sabe cuánto hay.
                        className="min-h-[52px] px-1.5 py-2 flex flex-col justify-between"
                        style={{
                          background: c.bg,
                          border: c.border,
                          outline: isCurrent ? '1.5px solid #21D07A' : undefined,
                          outlineOffset: isCurrent ? '-2px' : undefined,
                          borderRadius: '3px',
                        }}
                      >
                        <span
                          className="font-mono text-[10px] tracking-label leading-none"
                          style={{ color: c.label }}
                        >
                          {MONTH_SHORT[idx]}
                        </span>
                        <span
                          className="font-mono text-[12px] font-semibold leading-none tabular"
                          style={{ color: c.value }}
                        >
                          {hasData ? fmtPctValue(pct) : '—'}
                        </span>
                      </div>
                    )
                  })}
                </div>
                <div className="flex flex-col gap-1.5 items-end min-w-[132px]">
                  <Veredicto nombre="S&P 500" articulo="el" pp={resumen?.vs_sp500_pct} />
                  <Veredicto nombre="inflación" articulo="la" pp={resumen?.vs_inflation_pct} />
                </div>
              </div>
              <MetricasDelAno resumen={resumen} months={months} money={money} />
              </div>
            )
          })}

          {/* Legend */}
          <div className="flex items-center gap-1 pt-3 border-t border-line/50 text-[10px] font-mono text-ink-3">
            <span className="mr-2 font-medium">−5%</span>
            <span className="inline-block w-5 h-2.5" style={{ background: '#FF5360' }} />
            <span className="inline-block w-5 h-2.5" style={{ background: '#C8333E' }} />
            <span className="inline-block w-5 h-2.5" style={{ background: '#8E2B33' }} />
            <span className="inline-block w-5 h-2.5 mx-1" style={{ background: '#1B2230' }} />
            <span className="inline-block w-5 h-2.5" style={{ background: '#0F5C36' }} />
            <span className="inline-block w-5 h-2.5" style={{ background: '#14A560' }} />
            <span className="inline-block w-5 h-2.5" style={{ background: '#21D07A' }} />
            <span className="ml-2 font-medium">+5%</span>
            <span className="ml-auto font-medium">Rendimiento mensual</span>
          </div>
        </div>
      </div>
    </section>
  )
}
