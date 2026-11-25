// hallazgosDeLaBienvenida — el resumen corto que Mervall-E da al terminar de
// cargar el historial («tu cartera»): 3 o 4 cosas que Rendi detectó, para que
// la primera pantalla con plata sea algo más que el total.
//
// De dónde sale cada uno:
//   · «resultado», «mejor activo» y «el que más te pesa»: del cálculo de «tu
//     cartera» (hooks/useCarteraRecienCargada), el MISMO que da el total que se
//     ve arriba en la misma pantalla. Así los números no se contradicen.
//   · el resto: del motor de Diagnóstico (utils/diagnostics.js), con SUS textos y
//     SUS umbrales — no se reescriben acá. Sólo los generadores de la lista de
//     abajo: los que describen la cartera de hoy y no necesitan meses de
//     historia (rendimientos, rachas, benchmarks), ni dan consejos impositivos.
//
// Función pura: la pantalla la llama con lo que ya calculó; las pruebas, con
// datos armados.

import { selectDiagnostics } from './diagnostics'
import { fmtUsd, pctSigned } from './format'
import { OCULTO } from './ocultarSaldos'

/** Los generadores de utils/diagnostics.js que entran en la bienvenida. */
export const HALLAZGOS_DEL_MOTOR = [
  'concentration_extreme',
  'concentration_high',
  'few_assets',
  'cash_heavy',
  'fees_drag',
  'broker_idle_cash',
  'stale_positions',
]

export const MAX_HALLAZGOS = 4

/**
 * @param {object} p
 * @param {object} p.stats        — de useCarteraRecienCargada (value, invested,
 *                                  pnl, pnlPct, best, worst, pieData)
 * @param {Array}  p.positions    — las posiciones con las que se valuó
 * @param {Array}  p.brokers
 * @param {number} p.tcValuacion
 * @param {boolean} p.oculto      — «Ocultar saldos»: los montos salen tapados
 * @param {Date}   p.hoy          — inyectable (el motor rota por día)
 * @returns {Array<{id, tono: 'pos'|'neg'|'atencion'|'info', texto}>}
 */
export function hallazgosDeLaBienvenida({ stats, positions = [], brokers = [], tcValuacion = null, oculto = false, hoy = new Date() } = {}) {
  if (!stats || !(stats.value > 0)) return []
  const plata = (v) => (oculto ? OCULTO : fmtUsd(Math.abs(v), 0))
  const out = []

  // 1. Cómo viene lo que tiene hoy contra lo que pagó.
  if (stats.invested > 0 && Math.abs(stats.pnl) >= 1) {
    const arriba = stats.pnl >= 0
    out.push({
      id: 'resultado',
      tono: arriba ? 'pos' : 'neg',
      texto: arriba
        ? `Lo que tenés hoy vale **${plata(stats.pnl)} más** de lo que pagaste (**${pctSigned(stats.pnlPct)}**).`
        : `Lo que tenés hoy vale **${plata(stats.pnl)} menos** de lo que pagaste (**${pctSigned(stats.pnlPct)}**).`,
    })
  }

  // 2. El activo que más le dio.
  const best = stats.best
  if (best && best.pnl_usd >= 1) {
    out.push({ id: 'mejor_activo', tono: 'pos', texto: `Tu mejor activo es **${best.asset}**: vale **${plata(best.pnl_usd)}** más de lo que pagaste.` })
  }

  // 3-4. Lo más importante que ve el motor de Diagnóstico (ya viene ordenado:
  // lo urgente primero).
  const delMotor = selectDiagnostics({
    oculto,
    pieData: stats.pieData || [],
    totalPortfolio: stats.value,
    positions,
    brokers,
    tcValuacion,
  }, 999, hoy).filter(d => HALLAZGOS_DEL_MOTOR.includes(d.id) && !d.locked)
  for (const d of delMotor) {
    if (out.length >= MAX_HALLAZGOS) break
    out.push({ id: d.id, tono: d.severity === 'urgent' || d.severity === 'warn' ? 'atencion' : 'info', texto: d.text })
  }

  // Si el motor no vio nada que decir, el activo que más le pesa completa el
  // resumen (siempre que no sea el mismo que el mejor).
  const worst = stats.worst
  if (out.length < 3 && worst && worst.pnl_usd <= -1 && worst.asset !== best?.asset) {
    out.push({ id: 'peor_activo', tono: 'neg', texto: `El que más te pesa es **${worst.asset}**: vale **${plata(worst.pnl_usd)}** menos de lo que pagaste.` })
  }

  return out.slice(0, MAX_HALLAZGOS)
}
