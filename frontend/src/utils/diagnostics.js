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
      return `**${brokerConcentration.top.sharePct.toFixed(0)}%** de tu capital está en **${brokerConcentration.top.name}**. Considerá diversificar custodia para reducir riesgo de contraparte.`
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
      return `Tu portfolio supera al **S&P 500** por **+${vsSp500.pct.toFixed(1)}%**. Estás generando alpha sobre el índice de referencia.`
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
      return `**${sharePct.toFixed(0)}%** del portfolio está en cash. Aporta liquidez para oportunidades, pero también genera drag de rendimiento si el mercado sube.`
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
    severity: 'positive',
    generate: ({ openExtremes }) => {
      if (!openExtremes || !openExtremes.best || openExtremes.best.pnl_usd <= 0) return null
      if (openExtremes.best.pnl_pct == null || openExtremes.best.pnl_pct < 30) return null
      return `**${openExtremes.best.asset}** acumula **${fmtPct(openExtremes.best.pnl_pct)}** de ganancia no realizada. Definí un plan de toma de utilidades para no exponer la ganancia a una reversión.`
    },
  },

  // ─── Currency ───────────────────────────────────────────────────────────
  {
    id: 'high_ars_exposure',
    category: 'Moneda',
    severity: 'warn',
    generate: ({ pieData, totalPortfolio, brokers }) => {
      if (!pieData || !brokers || !totalPortfolio) return null
      const arsBrokerSet = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
      const arsValue = pieData.filter(p => arsBrokerSet.has(p.name)).reduce((s, p) => s + p.value, 0)
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
