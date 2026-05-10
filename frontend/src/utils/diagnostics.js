// diagnostics.js
// ──────────────
// Motor de diagnóstico del portfolio. La idea es que existan MUCHOS
// generadores y que cada visita el usuario vea solo los más relevantes para
// su situación actual + algo de variedad día a día.
//
// Cómo funciona:
//  1. Cada generador es una función pura (data) => null | { id, severity, category, text }
//     Devuelve null si no aplica → no se muestra.
//  2. selectDiagnostics() agarra todos, ordena por severidad, y dentro de la
//     misma severidad rota por día calendario. Eso da variedad sin perder lo
//     importante: lo urgente siempre está arriba; lo informativo va rotando.
//
// Severidad:
//  • urgent   → rojo. Riesgo concreto y elevado.
//  • warn     → ámbar. Cosa a mirar.
//  • info     → slate. Observación neutra / educativa.
//  • positive → emerald. Hábito o métrica buena.
//
// Convención: para resaltar números/nombres en el bullet, envolverlos en
// **dobles asteriscos**. La UI los renderiza en negrita.

// ─── Helpers ────────────────────────────────────────────────────────────────

const fmtUsd = (n) => {
  if (n == null || !isFinite(n)) return '—'
  return `${n >= 0 ? '+' : '−'}USD ${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
}

const fmtPct = (n, decimals = 1) => {
  if (n == null || !isFinite(n)) return '—'
  return `${n >= 0 ? '+' : ''}${n.toFixed(decimals)}%`
}

// Hash determinístico de un string → entero. Usado para tie-break diario
// estable: el mismo día se ve la misma rotación, pero entre días varía.
function hashString(s) {
  let h = 5381
  for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0
  return h
}

function dayOfYearKey(date = new Date()) {
  // YYYY-DDD donde DDD = día del año. Cambia cada día calendario.
  const start = Date.UTC(date.getUTCFullYear(), 0, 0)
  const diff = date.getTime() - start
  const dayOfYear = Math.floor(diff / 86_400_000)
  return `${date.getUTCFullYear()}-${dayOfYear}`
}

// ─── Generadores ────────────────────────────────────────────────────────────
// Cada uno se centra en UN aspecto del portfolio. Convención: si la condición
// no aplica, devolver null. No emitir bullets vagos: si no hay un dato concreto
// para citar, no es útil mostrar la observación.

export const DIAGNOSTIC_GENERATORS = [
  // ─── Riesgo / concentración ─────────────────────────────────────────────
  {
    id: 'concentration_extreme',
    category: 'Riesgo',
    severity: 'urgent',
    generate: ({ pieData, totalPortfolio }) => {
      if (!pieData || !pieData.length || !totalPortfolio) return null
      const top = [...pieData].sort((a, b) => b.value - a.value)[0]
      const sharePct = (top.value / totalPortfolio) * 100
      if (sharePct < 50) return null
      const impact = sharePct * 0.2
      return `**${top.name}** representa el **${sharePct.toFixed(0)}%** de tu cartera. Una caída del 20% en ese activo se traduce en **−${impact.toFixed(1)}%** sobre el total.`
    },
  },
  {
    id: 'concentration_high',
    category: 'Riesgo',
    severity: 'warn',
    generate: ({ pieData, totalPortfolio }) => {
      if (!pieData || !pieData.length || !totalPortfolio) return null
      const top = [...pieData].sort((a, b) => b.value - a.value)[0]
      const sharePct = (top.value / totalPortfolio) * 100
      if (sharePct < 35 || sharePct >= 50) return null
      return `**${top.name}** pesa **${sharePct.toFixed(0)}%** del portfolio. Concentración elevada en un único activo.`
    },
  },
  {
    id: 'concentration_top3',
    category: 'Riesgo',
    severity: 'warn',
    generate: ({ concentration }) => {
      if (!concentration || concentration.sharePct < 80) return null
      const names = concentration.top3.map(t => t.asset).join(', ')
      return `El **${concentration.sharePct.toFixed(0)}%** de la cartera está concentrado en 3 activos: **${names}**.`
    },
  },
  {
    id: 'broker_concentration',
    category: 'Riesgo',
    severity: 'warn',
    generate: ({ brokerConcentration }) => {
      if (!brokerConcentration || brokerConcentration.top.sharePct < 70) return null
      return `**${brokerConcentration.top.sharePct.toFixed(0)}%** de tu capital está custodiado en **${brokerConcentration.top.name}**. Si ese broker tuviera un problema operativo o regulatorio, todo tu capital quedaría expuesto. Diversificar entre brokers reduce ese riesgo.`
    },
  },
  {
    id: 'asset_class_concentration',
    category: 'Riesgo',
    severity: 'warn',
    generate: ({ assetTypeBreakdown }) => {
      if (!assetTypeBreakdown || !assetTypeBreakdown.length) return null
      const top = [...assetTypeBreakdown].sort((a, b) => b.sharePct - a.sharePct)[0]
      if (top.sharePct < 70) return null
      return `**${top.sharePct.toFixed(0)}%** de la cartera está en una sola clase de activo (**${top.type}**). Diversificar entre instrumentos reduce la sensibilidad a un mismo factor.`
    },
  },
  {
    id: 'few_assets',
    category: 'Riesgo',
    severity: 'info',
    generate: ({ pieData }) => {
      if (!pieData) return null
      const n = pieData.length
      if (n === 0 || n >= 4) return null
      return `Tenés **${n} ${n === 1 ? 'activo' : 'activos'}** en cartera. Diversificación limitada: cada movimiento individual impacta de forma desproporcionada en el total.`
    },
  },

  // ─── Performance / atribución ──────────────────────────────────────────
  {
    id: 'growth_from_deposits',
    category: 'Performance',
    severity: 'warn',
    generate: ({ discipline }) => {
      if (!discipline || !discipline.deposits || !discipline.pnl) return null
      // crecimiento total = depósitos + pnl. Si los depósitos explican >70%, advertir.
      const total = Math.abs(discipline.total)
      if (total <= 0) return null
      const depositShare = (Math.abs(discipline.deposits) / total) * 100
      if (depositShare < 70) return null
      return `El **${depositShare.toFixed(0)}%** del crecimiento de tu portfolio proviene de aportes, no del rendimiento del mercado. La performance real es la que genera tu capital existente.`
    },
  },
  {
    id: 'growth_from_market',
    category: 'Performance',
    severity: 'positive',
    generate: ({ discipline }) => {
      if (!discipline || !discipline.deposits || !discipline.pnl) return null
      const total = Math.abs(discipline.total)
      if (total <= 0 || discipline.pnl <= 0) return null
      const pnlShare = (discipline.pnl / total) * 100
      if (pnlShare < 60) return null
      return `El **${pnlShare.toFixed(0)}%** del crecimiento proviene del rendimiento del mercado, no de aportes nuevos. Indicador positivo de gestión.`
    },
  },
  {
    id: 'gain_concentration',
    category: 'Performance',
    severity: 'warn',
    generate: ({ assetContribFull, totalResult }) => {
      if (!assetContribFull || !assetContribFull.length || !totalResult || totalResult <= 0) return null
      const positive = assetContribFull.filter(x => x.pnl > 0)
      if (!positive.length) return null
      const totalGains = positive.reduce((s, x) => s + x.pnl, 0)
      const top = positive.sort((a, b) => b.pnl - a.pnl)[0]
      const share = (top.pnl / totalGains) * 100
      if (share < 50) return null
      return `El **${share.toFixed(0)}%** de tus ganancias proviene de **${top.asset}**. Sin esa posición, el rendimiento se reduce significativamente.`
    },
  },
  {
    id: 'underperform_benchmark',
    category: 'Performance',
    severity: 'warn',
    generate: ({ vsSp500, currency }) => {
      if (currency !== 'USD' || !vsSp500 || vsSp500.pct == null) return null
      if (vsSp500.pct >= -5) return null
      return `Tu portfolio rinde **${Math.abs(vsSp500.pct).toFixed(1)}%** por debajo del **S&P 500**. Si la brecha persiste, conviene evaluar si la gestión activa justifica el costo frente a un índice.`
    },
  },
  {
    id: 'outperform_benchmark',
    category: 'Performance',
    severity: 'positive',
    generate: ({ vsSp500, currency }) => {
      if (currency !== 'USD' || !vsSp500 || vsSp500.pct == null) return null
      if (vsSp500.pct < 5) return null
      return `Tu portfolio rinde **+${vsSp500.pct.toFixed(1)}%** por encima del **S&P 500**, el índice de referencia del mercado de acciones de EEUU.`
    },
  },
  {
    id: 'beat_inflation_ars',
    category: 'Performance',
    severity: 'positive',
    generate: ({ vsArs, inflationCum, currency }) => {
      if (currency !== 'ARS' || !inflationCum) return null
      if (!vsArs || vsArs.pct == null) return null
      if (vsArs.pct < 0) return null
      return `Tu cartera en pesos supera a la inflación INDEC con un retorno real de **+${vsArs.pct.toFixed(1)}%**.`
    },
  },
  {
    id: 'lose_to_inflation_ars',
    category: 'Performance',
    severity: 'warn',
    generate: ({ vsArs, inflationCum, currency }) => {
      if (currency !== 'ARS' || !inflationCum) return null
      if (!vsArs || vsArs.pct == null || vsArs.pct >= 0) return null
      return `Tu cartera en pesos rinde **${Math.abs(vsArs.pct).toFixed(1)}%** por debajo de la inflación INDEC. Hay pérdida de poder adquisitivo en términos reales.`
    },
  },

  // ─── Drawdown ───────────────────────────────────────────────────────────
  {
    id: 'drawdown_severe',
    category: 'Riesgo',
    severity: 'urgent',
    generate: ({ drawdown }) => {
      if (!drawdown || drawdown.current >= -20) return null
      return `Drawdown profundo: **${drawdown.current.toFixed(1)}%** desde el máximo histórico. Mantené tu plan — las decisiones impulsivas en esta zona suelen consolidar pérdidas.`
    },
  },
  {
    id: 'drawdown_moderate',
    category: 'Riesgo',
    severity: 'warn',
    generate: ({ drawdown }) => {
      if (!drawdown || drawdown.current >= -10 || drawdown.current < -20) return null
      return `Drawdown del **${drawdown.current.toFixed(1)}%** desde el máximo histórico. Caída habitual del mercado — revisá si tu tesis de inversión sigue intacta.`
    },
  },
  {
    id: 'at_highs',
    category: 'Performance',
    severity: 'positive',
    generate: ({ drawdown }) => {
      if (!drawdown || drawdown.current < -1 || drawdown.maxPct == null) return null
      if (drawdown.maxPct > -3) return null  // sin drawdown histórico relevante, no es noticia
      return `Tu portfolio está en máximos históricos. Recuperado de un drawdown previo del **${Math.abs(drawdown.maxPct).toFixed(1)}%**.`
    },
  },

  // ─── Comportamiento (operaciones cerradas) ──────────────────────────────
  {
    id: 'profit_factor_low_winrate_high',
    category: 'Comportamiento',
    severity: 'warn',
    generate: ({ winRate, profitFactor }) => {
      if (!winRate || !profitFactor || winRate.wins + winRate.losses < 5) return null
      if (winRate.pct < 60 || profitFactor.profitFactor >= 1) return null
      return `Win rate alto (**${winRate.pct.toFixed(0)}%**) pero profit factor de **${profitFactor.profitFactor.toFixed(2)}**: las pérdidas individuales superan a las ganancias. El sistema acierta más de lo que falla, pero pierde dinero neto.`
    },
  },
  {
    id: 'profit_factor_strong',
    category: 'Comportamiento',
    severity: 'positive',
    generate: ({ profitFactor }) => {
      if (!profitFactor || profitFactor.profitFactor === Infinity) return null
      if (profitFactor.profitFactor < 2) return null
      return `Profit factor de **${profitFactor.profitFactor.toFixed(1)}**: por cada dólar perdido, generás ${profitFactor.profitFactor.toFixed(1)}. Sistema con expectativa positiva sólida.`
    },
  },
  {
    id: 'disposition_effect',
    category: 'Comportamiento',
    severity: 'warn',
    generate: ({ holdTime }) => {
      if (!holdTime || holdTime.avgWin == null || holdTime.avgLoss == null) return null
      // Disposition effect = cortás ganadoras rápido, aguantás perdedoras
      if (holdTime.avgLoss <= holdTime.avgWin * 1.4) return null
      return `Sostenés perdedoras durante **${holdTime.avgLoss.toFixed(0)}d** en promedio frente a **${holdTime.avgWin.toFixed(0)}d** en las ganadoras. Patrón consistente con el "disposition effect", un sesgo conductual que erosiona retornos a largo plazo.`
    },
  },
  {
    id: 'cuts_losses_early',
    category: 'Comportamiento',
    severity: 'positive',
    generate: ({ holdTime }) => {
      if (!holdTime || holdTime.avgWin == null || holdTime.avgLoss == null) return null
      if (holdTime.avgWin <= holdTime.avgLoss * 1.4) return null
      return `Dejás correr ganadoras (**${holdTime.avgWin.toFixed(0)}d**) y cortás perdedoras temprano (**${holdTime.avgLoss.toFixed(0)}d**). Disciplina opuesta al disposition effect.`
    },
  },
  {
    id: 'low_sample_size',
    category: 'Comportamiento',
    severity: 'info',
    generate: ({ winRate }) => {
      if (!winRate) return null
      const total = winRate.wins + winRate.losses
      if (total === 0 || total >= 10) return null
      return `Muestra de **${total} ${total === 1 ? 'operación cerrada' : 'operaciones cerradas'}**. Métricas como win rate y profit factor requieren más historial para ser estadísticamente significativas.`
    },
  },

  // ─── Cash / asignación ──────────────────────────────────────────────────
  {
    id: 'cash_heavy',
    category: 'Asignación',
    severity: 'warn',
    generate: ({ positions, totalPortfolio, brokers }) => {
      if (!positions || !totalPortfolio || !brokers) return null
      const arsBrokers = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
      const tcBlue = 1 // valor irrelevante — solo necesitamos la proporción y los cash están en su moneda
      const cashUsd = positions
        .filter(p => p.is_cash)
        .reduce((s, p) => {
          if (arsBrokers.has(p.broker)) return s // ARS cash se ignora aquí (estimación gruesa)
          return s + (p.invested || 0)
        }, 0)
      const sharePct = (cashUsd / totalPortfolio) * 100
      if (sharePct < 30) return null
      return `**${sharePct.toFixed(0)}%** del portfolio está en cash. Aporta liquidez para aprovechar correcciones del mercado, pero también limita el rendimiento si el mercado tiene una tendencia alcista sostenida.`
    },
  },
  {
    id: 'cash_low',
    category: 'Asignación',
    severity: 'info',
    generate: ({ positions, totalPortfolio }) => {
      if (!positions || !totalPortfolio) return null
      const cash = positions
        .filter(p => p.is_cash)
        .reduce((s, p) => s + (p.invested || 0), 0)
      const sharePct = (cash / totalPortfolio) * 100
      if (sharePct >= 5 || sharePct < 0.5) return null
      return `Solo **${sharePct.toFixed(1)}%** del portfolio en cash. Una reserva mayor te permitiría aprovechar correcciones del mercado.`
    },
  },

  // ─── Posiciones abiertas ────────────────────────────────────────────────
  {
    id: 'open_loss_significant',
    category: 'Posiciones abiertas',
    severity: 'warn',
    generate: ({ openExtremes, totalPortfolio }) => {
      if (!openExtremes || !openExtremes.worst || openExtremes.worst.pnl_usd >= 0) return null
      const lossPct = (Math.abs(openExtremes.worst.pnl_usd) / (totalPortfolio || 1)) * 100
      if (lossPct < 3) return null
      const pctTxt = openExtremes.worst.pnl_pct != null ? ` (${openExtremes.worst.pnl_pct.toFixed(1)}%)` : ''
      return `**${openExtremes.worst.asset}** acumula la mayor pérdida no realizada: **${fmtUsd(openExtremes.worst.pnl_usd)}**${pctTxt}. Revisá si la tesis original sigue vigente o si conviene reasignar capital.`
    },
  },
  {
    id: 'open_winner_strong',
    category: 'Posiciones abiertas',
    // Una ganancia no realizada concentrada NO es un insight positivo:
    // es una alerta — el texto mismo dice 'una corrección podría reducir
    // o eliminar esta ganancia'. Es un riesgo de paper gains que conviene
    // realizar parcialmente. Por eso va en severity='warn', no 'positive'.
    severity: 'warn',
    generate: ({ openExtremes }) => {
      if (!openExtremes || !openExtremes.best || openExtremes.best.pnl_usd <= 0) return null
      if (openExtremes.best.pnl_pct == null || openExtremes.best.pnl_pct < 30) return null
      return `**${openExtremes.best.asset}** acumula **${fmtPct(openExtremes.best.pnl_pct)}** de ganancia no realizada. Una corrección del mercado podría reducir o eliminar esta ganancia hasta que la posición se cierre — las ganancias no realizadas se materializan solo al vender.`
    },
  },

  // ─── Currency ───────────────────────────────────────────────────────────
  {
    id: 'high_ars_exposure',
    category: 'Moneda',
    severity: 'warn',
    // NOTA: usa `brokerPieData` (por broker), no `pieData` (que está por activo).
    // Filtra por nombre de broker → solo tiene sentido sobre el agregado por broker.
    generate: ({ brokerPieData, totalPortfolio, brokers }) => {
      if (!brokerPieData || !brokers || !totalPortfolio) return null
      const arsBrokerSet = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
      const arsValue = brokerPieData.filter(p => arsBrokerSet.has(p.name)).reduce((s, p) => s + p.value, 0)
      const sharePct = (arsValue / totalPortfolio) * 100
      if (sharePct < 60) return null
      return `**${sharePct.toFixed(0)}%** de la cartera está custodiada en brokers ARS. Tu rendimiento medido en USD depende de la evolución del dólar blue.`
    },
  },
  {
    // Cash ARS específicamente: el USD-equivalente fluctúa con el blue sin que
    // hagas trades. Esa "ganancia/pérdida" cambia el Dashboard pero queda
    // invisible en el Resumen Mensual (que se cerró al blue del momento).
    // Esta es la razón principal por la que Dashboard ≠ Monthly capital_final.
    id: 'fx_cash_ars_exposure',
    category: 'Moneda',
    severity: 'info',
    generate: ({ positions, totalPortfolio, brokers, tcBlue }) => {
      if (!positions || !brokers || !totalPortfolio || !tcBlue) return null
      const arsBrokerSet = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
      const cashArs = positions
        .filter(p => p.is_cash && arsBrokerSet.has(p.broker))
        .reduce((s, p) => s + (p.invested || 0), 0)
      if (cashArs <= 0) return null
      const cashUsd = cashArs / tcBlue
      const sharePct = (cashUsd / totalPortfolio) * 100
      if (sharePct < 5) return null
      // Sensibilidad a un movimiento del 10% del blue
      const sensUsd = cashUsd * 0.1
      return `**${sharePct.toFixed(0)}%** del portfolio (≈ **${fmtUsd(cashUsd)}**) está en cash ARS. Una variación del 10% en el dólar blue mueve tu valor en USD aproximadamente ±**${fmtUsd(sensUsd)}** sin operaciones — esto explica buena parte de la diferencia entre Dashboard y Resumen Mensual.`
    },
  },

  // ═════════════════════════════════════════════════════════════════════════
  // BLOQUE 2 — Reglas de comportamiento, costos, consistencia y oportunidad.
  // ═════════════════════════════════════════════════════════════════════════

  // ─── Actividad operativa ────────────────────────────────────────────────
  {
    id: 'inactivity_long',
    category: 'Comportamiento',
    severity: 'info',
    generate: ({ tradeOps }) => {
      if (!tradeOps || tradeOps.length === 0) return null
      const lastDate = tradeOps
        .map(o => o.date)
        .filter(Boolean)
        .sort()
        .pop()
      if (!lastDate) return null
      const days = Math.floor((Date.now() - new Date(lastDate).getTime()) / 86_400_000)
      if (days < 90) return null
      const months = Math.round(days / 30)
      return `Hace **${months} ${months === 1 ? 'mes' : 'meses'}** que no realizás operaciones. Si cambiaron tus circunstancias o las tesis originales, conviene revisar la cartera.`
    },
  },
  {
    id: 'overtrading',
    category: 'Comportamiento',
    severity: 'warn',
    generate: ({ tradeOps }) => {
      if (!tradeOps || tradeOps.length === 0) return null
      const cutoff = Date.now() - 30 * 86_400_000
      const recent = tradeOps.filter(o => o.date && new Date(o.date).getTime() >= cutoff)
      if (recent.length < 12) return null
      return `Realizaste **${recent.length} operaciones** en los últimos 30 días. Operar muy seguido suele erosionar el rendimiento por costos, spreads y ruido — los mejores resultados suelen venir de menos decisiones, mejor pensadas.`
    },
  },

  // ─── Mejor / peor operación cerrada ─────────────────────────────────────
  {
    id: 'best_realized_op',
    category: 'Comportamiento',
    severity: 'positive',
    generate: ({ bestWorstOp }) => {
      if (!bestWorstOp || !bestWorstOp.best || !bestWorstOp.best.asset) return null
      if ((bestWorstOp.best.pnl_usd || 0) <= 50) return null  // umbral mínimo para evitar ruido
      return `Tu mejor operación cerrada fue **${bestWorstOp.best.asset}** con **${fmtUsd(bestWorstOp.best.pnl_usd)}**. Vale la pena identificar qué características compartió esa tesis para repetir el patrón.`
    },
  },
  {
    id: 'worst_realized_op',
    category: 'Comportamiento',
    severity: 'warn',
    generate: ({ bestWorstOp }) => {
      if (!bestWorstOp || !bestWorstOp.worst || !bestWorstOp.worst.asset) return null
      if ((bestWorstOp.worst.pnl_usd || 0) >= -50) return null
      return `Tu peor operación cerrada fue **${bestWorstOp.worst.asset}** con **${fmtUsd(bestWorstOp.worst.pnl_usd)}**. Identificar qué falló — tesis equivocada, timing, tamaño excesivo — es la forma más barata de no repetir el error.`
    },
  },

  // ─── Rachas de operaciones cerradas ─────────────────────────────────────
  {
    id: 'losing_streak',
    category: 'Comportamiento',
    severity: 'urgent',
    generate: ({ tradeOps }) => {
      if (!tradeOps || tradeOps.length < 4) return null
      // Ordenar por fecha descendente y contar racha de pérdidas consecutivas
      const sorted = [...tradeOps]
        .filter(o => o.date && o.pnl_usd != null)
        .sort((a, b) => new Date(b.date) - new Date(a.date))
      let streak = 0
      for (const op of sorted) {
        if (op.pnl_usd < 0) streak++
        else break
      }
      if (streak < 4) return null
      return `Acumulás **${streak} operaciones perdedoras consecutivas**. Es el momento de pausar y revisar el sistema antes de que el sesgo emocional empuje a sobre-operar para "recuperar".`
    },
  },
  {
    id: 'winning_streak',
    category: 'Comportamiento',
    severity: 'warn',
    generate: ({ tradeOps }) => {
      if (!tradeOps || tradeOps.length < 5) return null
      const sorted = [...tradeOps]
        .filter(o => o.date && o.pnl_usd != null)
        .sort((a, b) => new Date(b.date) - new Date(a.date))
      let streak = 0
      for (const op of sorted) {
        if (op.pnl_usd > 0) streak++
        else break
      }
      if (streak < 5) return null
      return `Llevás **${streak} operaciones ganadoras seguidas**. Cuidado con la trampa más común: agrandar el tamaño de posición creyendo que la racha continuará. Mantené el sizing disciplinado.`
    },
  },

  // ─── Hold time / estilo del inversor ────────────────────────────────────
  {
    id: 'avg_hold_time_classifier',
    category: 'Comportamiento',
    severity: 'info',
    generate: ({ holdTime }) => {
      if (!holdTime || holdTime.avg == null || holdTime.avg <= 0) return null
      const d = holdTime.avg
      let style
      if (d < 7)        style = 'scalper / day-trader'
      else if (d < 30)  style = 'swing trader corto'
      else if (d < 90)  style = 'swing trader / posición corta'
      else if (d < 365) style = 'inversor de posición'
      else              style = 'inversor de largo plazo'
      return `Tu hold time promedio en operaciones cerradas es de **${d.toFixed(0)} días**. Tu perfil operativo se asemeja al de un **${style}** — útil para evaluar si tu estrategia y costos están alineados a ese horizonte.`
    },
  },

  // ─── Realizadas vs no realizadas ────────────────────────────────────────
  {
    id: 'unrealized_dominates',
    category: 'Performance',
    severity: 'warn',
    generate: ({ realizedPnl, unrealizedPnl }) => {
      if (realizedPnl == null || unrealizedPnl == null) return null
      const totalPnl = realizedPnl + unrealizedPnl
      if (totalPnl <= 0) return null  // si el total es pérdida, no aplica
      if (unrealizedPnl <= 0) return null
      const share = (unrealizedPnl / totalPnl) * 100
      if (share < 75) return null
      return `El **${share.toFixed(0)}%** de tu P&L total está sin realizar (${fmtUsd(unrealizedPnl)}). Es ganancia "en papel" que puede esfumarse con una corrección — considerá realizar parcialmente las posiciones más concentradas.`
    },
  },

  // ─── Comisiones y costos ────────────────────────────────────────────────
  {
    id: 'fees_drag',
    category: 'Performance',
    severity: 'warn',
    generate: ({ positions, totalPortfolio }) => {
      if (!positions || !totalPortfolio) return null
      const totalCommissions = positions.reduce((s, p) => s + (p.commissions || 0), 0)
      if (totalCommissions <= 0) return null
      const share = (totalCommissions / totalPortfolio) * 100
      if (share < 0.5) return null
      return `Las comisiones acumuladas suman **${fmtUsd(totalCommissions)}** (**${share.toFixed(1)}%** del portfolio). Cada operación adicional come tu rendimiento — vale la pena chequear si el broker está cobrando comisiones competitivas.`
    },
  },

  // ─── Tax-loss harvesting ────────────────────────────────────────────────
  {
    id: 'tax_loss_opportunity',
    category: 'Performance',
    severity: 'info',
    generate: ({ pieData }) => {
      if (!pieData || pieData.length === 0) return null
      const losers = pieData.filter(p => (p.pnl != null) && p.pnl < -50)
      if (losers.length === 0) return null
      const totalLoss = losers.reduce((s, p) => s + p.pnl, 0)
      if (totalLoss > -100) return null
      return `Tenés **${losers.length} ${losers.length === 1 ? 'posición' : 'posiciones'}** con pérdida no realizada por **${fmtUsd(totalLoss)}**. Si tributás ganancias del año, realizar pérdidas (tax-loss harvesting) puede compensar parte de esa carga impositiva.`
    },
  },

  // ─── Posiciones pequeñas — drag de complejidad ──────────────────────────
  {
    id: 'tiny_positions_drag',
    category: 'Posiciones abiertas',
    severity: 'info',
    generate: ({ pieData, totalPortfolio }) => {
      if (!pieData || pieData.length < 5 || !totalPortfolio) return null
      const tinies = pieData.filter(p => (p.value / totalPortfolio) * 100 < 2)
      if (tinies.length < 3) return null
      const totalShare = tinies.reduce((s, p) => s + (p.value / totalPortfolio) * 100, 0)
      if (totalShare > 8) return null  // si la suma es >8%, no son tan menores
      return `Tenés **${tinies.length} posiciones** que pesan menos del 2% cada una y representan apenas el **${totalShare.toFixed(1)}%** del total. Posiciones tan chicas no mueven la aguja pero suman complejidad operativa — considerá consolidar o salir.`
    },
  },

  // ─── Posiciones estancadas (sin movimiento) ─────────────────────────────
  {
    id: 'stale_positions',
    category: 'Posiciones abiertas',
    severity: 'info',
    generate: ({ positions }) => {
      if (!positions || positions.length === 0) return null
      const cutoff = Date.now() - 365 * 86_400_000
      const stale = positions.filter(p =>
        !p.is_cash && p.entry_date && new Date(p.entry_date).getTime() < cutoff
      )
      if (stale.length < 2) return null
      return `**${stale.length} posiciones** llevan más de un año sin movimiento. Pueden ser convicciones de largo plazo o posiciones olvidadas — conviene revisar si la tesis original sigue vigente.`
    },
  },

  // ─── Concentración geográfica ───────────────────────────────────────────
  {
    id: 'geographic_concentration_ar',
    category: 'Moneda',
    severity: 'warn',
    generate: ({ positions, totalPortfolio, brokers, prices, tcBlue }) => {
      // Posiciones argentinas = activos en brokers ARS (cotizan en BCBA con sufijo .BA)
      if (!positions || !brokers || !totalPortfolio || !tcBlue) return null
      const arsBrokers = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
      const arValue = positions
        .filter(p => arsBrokers.has(p.broker) && !p.is_cash)
        .reduce((s, p) => {
          // Aproximación: usamos invested ARS / tcBlue. Si hay precio, igual sirve
          // para estimar exposición geográfica (no es valor live exacto).
          const arsAmt = (p.invested || 0) + (p.commissions || 0)
          return s + arsAmt / tcBlue
        }, 0)
      const sharePct = (arValue / totalPortfolio) * 100
      if (sharePct < 50) return null
      return `**${sharePct.toFixed(0)}%** del portfolio está en activos argentinos (acciones BCBA, CEDEARs locales). Concentración geográfica alta — para diversificar considerá cuentas USD con ETFs internacionales (SPY, EEM, VEA).`
    },
  },

  // ─── Recuperación de drawdown ───────────────────────────────────────────
  {
    id: 'drawdown_recovery',
    category: 'Performance',
    severity: 'positive',
    generate: ({ drawdown }) => {
      if (!drawdown || drawdown.maxPct == null || drawdown.current == null) return null
      // Si tuvo un drawdown profundo (≤ -10%) y se recuperó (current > -3%)
      if (drawdown.maxPct > -10) return null
      if (drawdown.current < -3) return null
      const recovered = Math.abs(drawdown.maxPct) - Math.abs(drawdown.current)
      if (recovered < 5) return null
      return `Recuperaste **${recovered.toFixed(1)}** puntos de un drawdown que llegó a **${drawdown.maxPct.toFixed(1)}%**. Tu portfolio mostró resiliencia — el peor momento ya pasó y se sostuvo la disciplina.`
    },
  },

  // ─── Profit factor excepcional ──────────────────────────────────────────
  {
    id: 'profit_factor_excellent',
    category: 'Comportamiento',
    severity: 'positive',
    generate: ({ profitFactor }) => {
      if (!profitFactor || profitFactor.profitFactor === Infinity) return null
      if (profitFactor.profitFactor < 3) return null
      return `Profit factor de **${profitFactor.profitFactor.toFixed(1)}**: por cada dólar perdido, generás ${profitFactor.profitFactor.toFixed(1)}. Performance excepcional — el desafío ahora es mantener disciplina y no agrandar el sizing por sobre-confianza.`
    },
  },

  // ─── Consistencia mensual ───────────────────────────────────────────────
  {
    id: 'monthly_pnl_streak',
    category: 'Performance',
    severity: 'positive',
    generate: ({ globalMonthly }) => {
      if (!globalMonthly || globalMonthly.length < 3) return null
      // Ordenar de más reciente a más viejo y contar racha de meses positivos
      const sorted = [...globalMonthly].sort((a, b) =>
        b.year !== a.year ? b.year - a.year : b.month - a.month
      )
      let streak = 0
      for (const m of sorted) {
        const totalPnl = (m.pnl_realized || 0) + (m.pnl_unrealized || 0)
        if (totalPnl > 0) streak++
        else break
      }
      if (streak < 3) return null
      return `Llevás **${streak} meses consecutivos** en ganancia. Consistencia es la métrica más difícil de sostener — mantené el plan y evitá decisiones impulsivas en máximos.`
    },
  },
  {
    id: 'monthly_pnl_negative_streak',
    category: 'Performance',
    severity: 'warn',
    generate: ({ globalMonthly }) => {
      if (!globalMonthly || globalMonthly.length < 3) return null
      const sorted = [...globalMonthly].sort((a, b) =>
        b.year !== a.year ? b.year - a.year : b.month - a.month
      )
      let streak = 0
      for (const m of sorted) {
        const totalPnl = (m.pnl_realized || 0) + (m.pnl_unrealized || 0)
        if (totalPnl < 0) streak++
        else break
      }
      if (streak < 3) return null
      return `Llevás **${streak} meses consecutivos** en pérdida. Conviene revisar si la tesis macro sigue vigente, si el sizing es adecuado, o si vale pausar para no operar contra el viento.`
    },
  },

  // ─── Aniversario de portfolio ───────────────────────────────────────────
  {
    id: 'first_purchase_anniversary',
    category: 'Comportamiento',
    severity: 'info',
    generate: ({ positions, operations }) => {
      // Tomamos la fecha más antigua entre positions.entry_date y operations.date
      const dates = []
      if (positions) {
        for (const p of positions) {
          if (!p.is_cash && p.entry_date) dates.push(p.entry_date)
        }
      }
      if (operations) {
        for (const o of operations) {
          if (o.date) dates.push(o.date)
        }
      }
      if (dates.length === 0) return null
      const earliest = dates.sort()[0]
      const days = Math.floor((Date.now() - new Date(earliest).getTime()) / 86_400_000)
      const years = days / 365
      if (years < 1) return null
      const yLabel = years >= 2 ? `${Math.floor(years)} años` : '1 año'
      return `Llevás **${yLabel}** invirtiendo de forma trackeada (desde **${earliest}**). El tiempo en el mercado, no el timing del mercado, es lo que históricamente compone los retornos.`
    },
  },

  // ─── Cash vs invertido en broker idle ───────────────────────────────────
  {
    id: 'broker_idle_cash',
    category: 'Liquidez',
    severity: 'info',
    generate: ({ positions, brokers, tcBlue, totalPortfolio }) => {
      if (!positions || !brokers || !tcBlue || !totalPortfolio) return null
      // Detectamos brokers donde TODO el saldo está en cash (sin posiciones invertidas)
      const idleBrokers = []
      for (const b of brokers) {
        const bpos = positions.filter(p => p.broker === b.name)
        if (bpos.length === 0) continue
        const cashPos = bpos.filter(p => p.is_cash)
        const investPos = bpos.filter(p => !p.is_cash)
        if (cashPos.length === 0) continue
        if (investPos.length > 0) continue  // tiene inversiones, no es idle
        const cashUsd = cashPos.reduce((s, p) => {
          const amt = p.invested || 0
          return s + (b.currency === 'ARS' ? amt / tcBlue : amt)
        }, 0)
        if (cashUsd < 100) continue  // umbral mínimo
        idleBrokers.push({ name: b.name, cashUsd, currency: b.currency })
      }
      if (idleBrokers.length === 0) return null
      const total = idleBrokers.reduce((s, b) => s + b.cashUsd, 0)
      const list = idleBrokers.map(b => `**${b.name}** (≈ ${fmtUsd(b.cashUsd).replace('+', '')})`).join(', ')
      return `${idleBrokers.length === 1 ? 'Tu broker' : 'Tus brokers'} ${list} ${idleBrokers.length === 1 ? 'tiene' : 'tienen'} cash sin invertir por **${fmtUsd(total)}** total. Si la tesis era esperar oportunidad, considerá si el costo de oportunidad lo justifica.`
    },
  },
]

// ─── Selector ───────────────────────────────────────────────────────────────

const SEVERITY_RANK = { urgent: 0, warn: 1, positive: 2, info: 3 }

/**
 * selectDiagnostics
 *
 * @param {object}  data       — datos del portfolio (las claves que cada
 *                              generador necesite). Pasar todo lo que se
 *                              tenga — los generadores ignoran lo que no usan.
 * @param {number}  maxBullets — cuántos bullets mostrar (default 5)
 * @param {Date}    today      — fecha (inyectable para tests)
 * @returns {Array} bullets ordenados por (severidad, rotación diaria)
 */
export function selectDiagnostics(data, maxBullets = 5, today = new Date()) {
  const fired = []
  for (const gen of DIAGNOSTIC_GENERATORS) {
    let text
    try { text = gen.generate(data) } catch (_) { text = null }
    if (!text) continue
    fired.push({ id: gen.id, category: gen.category, severity: gen.severity, text })
  }

  if (fired.length === 0) return []

  // Tie-break determinístico por día. Mismo día = mismo orden; cambia a las
  // 00:00 UTC. Eso da variedad entre días sin romper la coherencia dentro del
  // mismo día (no se reordena en cada render).
  const seed = hashString(dayOfYearKey(today))
  fired.sort((a, b) => {
    const sevDiff = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]
    if (sevDiff !== 0) return sevDiff
    // Dentro de la misma severidad: tie-break por hash(id ⊕ seed)
    const ha = hashString(a.id) ^ seed
    const hb = hashString(b.id) ^ seed
    return ha - hb
  })

  return fired.slice(0, maxBullets)
}

// Para testing
export { hashString, dayOfYearKey }
