// InsightsKpiStrip — KPI strip denso al tope de /insights (V2).
// ═══════════════════════════════════════════════════════════════════════════
// Cinco celdas tabular, estilo audit:
//   1) Findings detectados  → bucket HI / MED / LO
//   2) Concentración top    → activo con mayor share
//   3) Drawdown actual      → TWRR
//   4) Rendimiento acum.    → TWRR vs benchmark si está
//   5) Win rate · trades    → ratio de operaciones cerradas
//
// Al verse (useAlVerse), los cinco números cuentan hasta su valor y los
// hallazgos por gravedad aterrizan de a uno (el total se arma con ellos). Si un
// número cambia después (1A → 2A, otro comparativo), va del viejo al nuevo.

import { labelVentanaMeses, pctTxt, pctVar, pctVarSign } from '../utils/format'
import AnimatedNumber from './AnimatedNumber'
import { useAlVerse } from '../hooks/useAlVerse'

const SEV_LABEL = { urgent: 'HI', warn: 'MED', positive: 'POS', info: 'LO' }
const SEV_TONE = {
  urgent:   'text-rendi-neg',
  warn:     'text-rendi-warn',
  positive: 'text-rendi-pos',
  info:     'text-ink-3',
}

function fmtFechaCorta(iso) {
  const s = String(iso || '')
  return /^\d{4}-\d{2}-\d{2}/.test(s) ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : s
}

/**
 * Qué es el número del modo Estimado, en una línea. Desde el 2026-10-27 (decisión
 * del dueño) el estimado es una RECONSTRUCCIÓN: precio real de lo que se pudo
 * valuar, costo de lo que no (bonos o FCI sin precio histórico), y la pantalla dice
 * cuánto quedó a precio real. "Sólo se mueve cuando vendés" queda únicamente para
 * cuando parte del número es la contabilidad pura (`excluyeNoRealizado`).
 */
export function textoReconstruido({ cobertura, excluyeNoRealizado } = {}) {
  const partes = ['reconstruido']
  if (typeof cobertura === 'number' && cobertura >= 0) {
    const pct = Math.round(cobertura * 100)
    partes.push(pct >= 100 ? 'todo a precio real' : `${pct} % a precio real, el resto al costo`)
  }
  if (excluyeNoRealizado) partes.push('lo contable sólo se mueve cuando vendés')
  return partes.join(' · ')
}

export default function InsightsKpiStrip({
  diagnosis = [],
  assetPieData = [],
  drawdownTwrr,
  winRate,
  cumulativeReturnPct,
  acumuladoEstimado = null,
  benchmarkReturnPct,
  benchmarkLabel,
  ventanaMeses,
  currency = 'USD',
}) {
  const [ref, visto] = useAlVerse()
  const ventanaLabel = labelVentanaMeses(ventanaMeses)

  // ── 1) Findings buckets ────────────────────────────────────────────────────
  const buckets = { urgent: 0, warn: 0, positive: 0, info: 0 }
  for (const d of diagnosis) {
    if (buckets[d.severity] != null) buckets[d.severity]++
  }
  const totalFindings = diagnosis.length

  // ── 2) Concentración top ───────────────────────────────────────────────────
  const totalAssetValue = assetPieData.reduce((s, x) => s + (x.value || 0), 0)
  let topAsset = null
  if (totalAssetValue > 0) {
    const top = [...assetPieData].sort((a, b) => (b.value || 0) - (a.value || 0))[0]
    if (top) {
      topAsset = { name: top.name, pct: (top.value / totalAssetValue) * 100 }
    }
  }
  const concentrationTone =
    !topAsset ? null :
    topAsset.pct >= 50 ? 'neg' :
    topAsset.pct >= 30 ? 'warn' :
    null

  // ── 3) Drawdown ────────────────────────────────────────────────────────────
  const ddCurrent = drawdownTwrr?.currentPct
  const ddMax = drawdownTwrr?.maxPct
  const ddTone = ddCurrent == null ? null : (ddCurrent < -5 ? 'neg' : (ddCurrent < -1 ? 'warn' : null))

  // ── 4) Rendimiento acumulado vs benchmark ──────────────────────────────────
  // El tono es el del número que se ve (1 decimal): un −0,03 se escribe "0,0%" y va neutro.
  const rendSign = pctVarSign(cumulativeReturnPct, 1)
  const rendTone = rendSign > 0 ? 'pos' : rendSign < 0 ? 'neg' : null

  // ── 5) Win rate ────────────────────────────────────────────────────────────
  const wr = winRate?.pct ?? null
  const wrTotal = winRate?.total ?? 0

  // Un número que cuenta hasta su valor cuando la fila se ve; "—" si no hay.
  const cuenta = (v, formato) =>
    v == null ? '—' : <AnimatedNumber value={v} visto={visto} format={formato} />
  const gravedades = ['urgent', 'warn', 'positive', 'info'].filter(k => buckets[k] > 0)

  return (
    <div ref={ref} className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      <KpiCell
        label="Findings detectados"
        value={cuenta(totalFindings, n => Math.round(n))}
        hero
        sub={
          totalFindings > 0 ? (
            <span className="flex items-center gap-1.5">
              {gravedades.map((k, i) => (
                <span key={k} className={`${SEV_TONE[k]} ${visto ? 'tilde-entra' : 'por-entrar'}`} style={{ '--i': i }}>
                  {buckets[k]} {SEV_LABEL[k]}
                </span>
              ))}
            </span>
          ) : 'sin observaciones'
        }
      />
      <KpiCell
        label={topAsset ? `Concentración · ${topAsset.name}` : 'Concentración'}
        value={cuenta(topAsset?.pct ?? null, n => pctTxt(n, 0))}
        tone={concentrationTone}
        sub={topAsset ? 'de la cartera total' : 'sin posiciones'}
      />
      <KpiCell
        label="Drawdown actual"
        value={cuenta(ddCurrent, n => pctTxt(n, 1))}
        tone={ddTone}
        sub={ddMax != null ? `peak histórico ${pctTxt(ddMax, 1)}` : 'TWRR'}
      />
      {/* La ventana va EN EL TÍTULO, no en el subtítulo: "Acumulado" a secas se
          lee como "desde siempre" y en realidad es el rango visible del gráfico
          (12 meses por defecto), que cambia en silencio con los tabs 1A/2A/5A/MAX.
          Sin el rótulo, este número se compara mentalmente contra el "Rendimiento
          anual" del Dashboard —que sí es toda la historia, y anualizado— y no hay
          forma de darse cuenta de que miden cosas distintas. */}
      {/* ⚠️ FASE 2 · UN NÚMERO RECONSTRUIDO NO PUEDE VERSE IGUAL QUE UNO MEDIDO.
          En modo Estimado este acumulado sale de la reconstrucción: llega más
          atrás y a cambio lo que no tuvo precio histórico queda al costo. El chip
          del gráfico lo dice con el % a precio real; si el KPI queda mudo, el usuario se lleva el número
          sin el asterisco. Y cuando la ventana tiene un corte de regla en el
          medio, el número es de la última corrida homogénea —encadenar por encima
          del corte sería la Fase 1 otra vez—, así que se declara desde cuándo. */}
      <KpiCell
        label={`Acumulado ${ventanaLabel} · ${currency}${acumuladoEstimado ? ' · reconstruido' : ''}`}
        value={cuenta(cumulativeReturnPct, n => pctVar(n, 1))}
        tone={rendTone}
        sub={
          acumuladoEstimado
            ? (acumuladoEstimado.parcial
                /* No decimos "desde <fecha>": con el resampleo mensual la fila que
                   abre la corrida puede no ser el arranque real del segmento, así
                   que la fecha sería inventada. Lo que SÍ sabemos es que hay un
                   corte de regla antes y que el número es de después de ese corte. */
                ? 'reconstruido · desde el último corte de la serie'
                : (acumuladoEstimado.medidoDesde
                    /* La línea es reconstruida hasta la primera medición y medida
                       después; el número es el producto de las dos partes. */
                    ? `reconstruido hasta ${fmtFechaCorta(acumuladoEstimado.medidoDesde)} · medido después`
                    : textoReconstruido(acumuladoEstimado)))
            : benchmarkReturnPct != null
            ? `vs ${benchmarkLabel}: ${pctVar(benchmarkReturnPct, 1)} · mismo período`
            : 'TWRR ajustado · sin anualizar'
        }
      />
      <KpiCell
        label="Win rate"
        value={cuenta(wr, n => pctTxt(n, 0))}
        sub={wrTotal > 0 ? `${wrTotal} ${wrTotal === 1 ? 'op cerrada' : 'ops cerradas'}` : 'sin operaciones'}
      />
    </div>
  )
}

function KpiCell({ label, value, sub, tone, hero }) {
  const valueColor =
    tone === 'pos'  ? 'text-rendi-pos' :
    tone === 'neg'  ? 'text-rendi-neg' :
    tone === 'warn' ? 'text-rendi-warn' :
    'text-ink-0'
  return (
    <div className="rounded-xl border border-line bg-bg-1 px-4 py-4">
      <div className="text-[12.5px] text-ink-2 font-medium leading-tight">{label}</div>
      <div className={`mt-3 font-semibold tabular num leading-none ${hero ? 'text-[30px] tracking-tight' : 'text-[26px]'} ${valueColor}`}>
        {value}
      </div>
      <div className="text-[12px] text-ink-3 mt-2.5 leading-snug">{sub}</div>
    </div>
  )
}
