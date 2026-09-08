// El resumen mínimo que viaja en el contexto de CADA mensaje del chat de la IA.
//
// ⚠️ `/api/monthly` DEVUELVE LAS FILAS POR-BROKER **Y** LA FILA SINTÉTICA
// `broker='global'`, QUE YA ES SU SUMA. Los escritores del backend estampan las
// dos a la vez (`_update_monthly_pnl_realized(conn, uid, 'global', ...)` corre al
// lado del per-broker), así que sumar todas las filas cuenta cada peso dos veces:
// el P&L de por vida le llegaba al modelo ×2 EXACTO, y con él `deposits_lifetime`
// y `withdrawals_lifetime` — o sea cualquier ratio que el modelo derive de ellos
// sale mal por partida doble.
//
// `Dashboard.jsx` ya filtra `m.broker === 'global'` para el MISMO número que
// muestra en pantalla. El filtro va acá para que el chat y la pantalla no puedan
// volver a divergir: esta función es la única que arma el resumen, y la llaman
// las dos superficies del chat (`RendiAI` y `AICoachDrawer`), que hasta ahora
// tenían una copia idéntica cada una — el bug estaba escrito dos veces.
//
// `months_tracked` cuenta las filas globales, no todas: con 4 brokers y 12 meses
// el modelo leía "48 meses de historia".
export const esFilaGlobal = (m) => m && m.broker === 'global'

export function buildAiSummary(positions, monthly) {
  const pos = positions || []
  const totalInvestedUsd = pos
    .filter(p => !p.is_cash)
    .reduce((acc, p) => acc + (p.invested || 0), 0)
  const totalPositions = pos.filter(p => !p.is_cash).length
  const totalCashPositions = pos.filter(p => p.is_cash).length

  const globales = (monthly || []).filter(esFilaGlobal)
  const monthsCount = globales.length
  const sumPnlRealized = globales.reduce((acc, m) => acc + (m.pnl_realized || 0), 0)
  const sumDeposits = globales.reduce((acc, m) => acc + (m.deposits || 0), 0)
  const sumWithdrawals = globales.reduce((acc, m) => acc + (m.withdrawals || 0), 0)

  return {
    total_invested_usd: +totalInvestedUsd.toFixed(2),
    open_positions_count: totalPositions,
    cash_lines_count: totalCashPositions,
    months_tracked: monthsCount,
    realized_pnl_usd_lifetime: +sumPnlRealized.toFixed(2),
    deposits_lifetime: +sumDeposits.toFixed(2),
    withdrawals_lifetime: +sumWithdrawals.toFixed(2),
  }
}
