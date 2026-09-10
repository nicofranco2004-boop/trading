// Generates plain-Spanish auto-insights from portfolio data.
// Pure functions — easy to unit-test and extend.

import { fmtUsd } from './format'
import { retornoTotal } from './evolution'

/**
 * Top-of-Dashboard one-liner: explains in plain Spanish what's happening.
 * Returns { tone, text } or null if there's nothing useful to say.
 *
 * @param {object} args
 * @param {number} args.totalValue       — current portfolio value (USD)
 * @param {number} args.netDeposited     — net capital added by the user (USD)
 * @param {number} args.capitalMaximo    — el máximo histórico de capital aportado, que
 *                                          es el denominador estable del %. Lo calcula
 *                                          `capitalMaximoAportado` y lo pasa el
 *                                          Dashboard: esta frase y el chip del hero
 *                                          TIENEN que ser el mismo número.
 * @param {Array}  args.positions        — open positions enriched with { asset, pnl_usd, pnl_pct, value_usd }
 *                                          (pnl_usd / pnl_pct may be null if price not loaded)
 */
export function buildDashboardInsight({ totalValue = 0, netDeposited = 0, capitalMaximo = null, positions = [] } = {}) {
  if (totalValue <= 0 && netDeposited <= 0) return null

  // MISMA regla que el hero, y de la misma función: acá vivía la segunda copia
  // del `netDeposited > 0 ? ... : 0`. `pct` puede venir en null — no hay
  // denominador que lo sostenga — y entonces la frase habla de PLATA y no de
  // porcentaje, en vez de afirmar un 0 % que sería falso.
  const { usd: totalReturn, pct: totalReturnPct } = retornoTotal({ totalValue, netDeposited, capitalMaximo })

  // Find biggest losers / winners with valid pnl
  const withPnl = positions.filter(p => p.pnl_usd != null && p.pnl_pct != null)
  const losers = withPnl.filter(p => p.pnl_usd < 0).sort((a, b) => a.pnl_usd - b.pnl_usd)
  const winners = withPnl.filter(p => p.pnl_usd > 0).sort((a, b) => b.pnl_usd - a.pnl_usd)

  const pctTxt = totalReturnPct != null
    ? `${totalReturnPct >= 0 ? '+' : ''}${(totalReturnPct * 100).toFixed(1)}%`
    : null

  // Sin porcentaje que sostener, la frase se cuenta con la PLATA. Es el mismo
  // criterio que el techo del % realizado: falta el denominador, no el dato.
  if (pctTxt == null) {
    if (totalReturn === 0) {
      return { tone: 'neutral',
               text: 'Cargá tus movimientos y posiciones para ver el rendimiento real de tu cartera.' }
    }
    // ⚠️ La frase dice el HECHO y no la causa. `pct` viene en null por más de
    // un motivo —retiraste más de lo que pusiste, o directamente no cargaste
    // ningún aporte— y nombrar el equivocado le afirma a un usuario nuevo que
    // retiró plata que nunca retiró. Desde acá no se puede distinguir cuál es.
    return {
      tone: totalReturn >= 0 ? 'positive' : 'negative',
      text: `Tu cartera está ${fmtUsd(Math.abs(totalReturn))} ${totalReturn >= 0 ? 'a favor' : 'en contra'} de lo que aportaste. El porcentaje no se puede calcular: no hay un capital aportado contra el cual medirlo.`,
    }
  }

  // Big drawdown narrative — pick top 2 losers
  if (totalReturnPct <= -0.10 && losers.length > 0) {
    const top2 = losers.slice(0, 2).map(p => p.asset).join(' y ')
    return {
      tone: 'negative',
      text: `Tu cartera rinde ${pctTxt} desde el inicio. Las mayores caídas provienen de ${top2}.`,
    }
  }

  // Strong gain narrative
  if (totalReturnPct >= 0.10 && winners.length > 0) {
    const top2 = winners.slice(0, 2).map(p => p.asset).join(' y ')
    return {
      tone: 'positive',
      text: `Tu cartera rinde ${pctTxt} desde el inicio. Las posiciones que más aportan: ${top2}.`,
    }
  }

  // Mild zone — just summarize
  if (totalReturn !== 0) {
    return {
      tone: totalReturn >= 0 ? 'positive' : 'negative',
      text: `Tu cartera rinde ${pctTxt} sobre el capital aportado (${fmtUsd(Math.abs(totalReturn))} ${totalReturn >= 0 ? 'a favor' : 'en contra'}).`,
    }
  }

  return {
    tone: 'neutral',
    text: 'Cargá tus movimientos y posiciones para ver el rendimiento real de tu cartera.',
  }
}
