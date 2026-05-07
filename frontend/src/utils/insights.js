// Generates plain-Spanish auto-insights from portfolio data.
// Pure functions — easy to unit-test and extend.

import { fmtUsd } from './format'

/**
 * Top-of-Dashboard one-liner: explains in plain Spanish what's happening.
 * Returns { tone, text } or null if there's nothing useful to say.
 *
 * @param {object} args
 * @param {number} args.totalValue       — current portfolio value (USD)
 * @param {number} args.netDeposited     — net capital added by the user (USD)
 * @param {Array}  args.positions        — open positions enriched with { asset, pnl_usd, pnl_pct, value_usd }
 *                                          (pnl_usd / pnl_pct may be null if price not loaded)
 */
export function buildDashboardInsight({ totalValue = 0, netDeposited = 0, positions = [] } = {}) {
  if (totalValue <= 0 && netDeposited <= 0) return null

  const totalReturn = totalValue - netDeposited
  const totalReturnPct = netDeposited > 0 ? totalReturn / netDeposited : 0

  // Find biggest losers / winners with valid pnl
  const withPnl = positions.filter(p => p.pnl_usd != null && p.pnl_pct != null)
  const losers = withPnl.filter(p => p.pnl_usd < 0).sort((a, b) => a.pnl_usd - b.pnl_usd)
  const winners = withPnl.filter(p => p.pnl_usd > 0).sort((a, b) => b.pnl_usd - a.pnl_usd)

  const pctTxt = `${totalReturnPct >= 0 ? '+' : ''}${(totalReturnPct * 100).toFixed(1)}%`

  // Big drawdown narrative — pick top 2 losers
  if (totalReturnPct <= -0.10 && losers.length > 0) {
    const top2 = losers.slice(0, 2).map(p => p.asset).join(' y ')
    return {
      tone: 'negative',
      text: `Tu portfolio rinde ${pctTxt} desde el inicio. Las mayores caídas provienen de ${top2}.`,
    }
  }

  // Strong gain narrative
  if (totalReturnPct >= 0.10 && winners.length > 0) {
    const top2 = winners.slice(0, 2).map(p => p.asset).join(' y ')
    return {
      tone: 'positive',
      text: `Tu portfolio rinde ${pctTxt} desde el inicio. Las posiciones que más aportan: ${top2}.`,
    }
  }

  // Mild zone — just summarize
  if (totalReturn !== 0) {
    return {
      tone: totalReturn >= 0 ? 'positive' : 'negative',
      text: `Tu portfolio rinde ${pctTxt} sobre el capital aportado (${fmtUsd(Math.abs(totalReturn))} ${totalReturn >= 0 ? 'a favor' : 'en contra'}).`,
    }
  }

  return {
    tone: 'neutral',
    text: 'Cargá tus movimientos y posiciones para ver el rendimiento real de tu portfolio.',
  }
}
