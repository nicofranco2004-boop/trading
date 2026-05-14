// demo — modo "probá Rendi sin login" con portfolio simulado.
// ═══════════════════════════════════════════════════════════════════════════
// Cuando la URL tiene `?demo=1`, AuthContext setea un user demo y este módulo
// intercepta las llamadas al backend devolviendo fixtures hardcodeadas.
//
// Cero backend writes. Cero DB. Vive en memoria del browser durante la sesión.
//
// El demo soporta MODIFICACIONES limitadas para que el user pueda probar el
// flow exploratorio:
//   ✓ Agregar / quitar de watchlist          → persiste en overlay localStorage
//   ✓ Agregar posición manual                → persiste en overlay localStorage
//   ✗ Vender / editar / eliminar posición    → bloqueado con mensaje (signup CTA)
//   ✗ Importar CSV / operations manual       → bloqueado con mensaje
//
// El overlay vive en localStorage del browser del visitante demo:
// el user A no ve los cambios del user B (cada device tiene su propio overlay).
// Al hacer "Salir del demo" se limpia el overlay y la próxima vez arranca limpio.

const DEMO_FLAG_KEY = 'rendi_demo_mode'
const DEMO_OVERLAY_KEY = 'rendi_demo_overlay'

// ─── Overlay helpers ─────────────────────────────────────────────────────────
// Estructura del overlay:
//   {
//     watchlist: [{ symbol, asset_type, added_at }],
//     positions: [{ ...positionLike, id: number sintético >= 9000 }],
//   }

const EMPTY_OVERLAY = { watchlist: null, positions: [] }

export function getDemoOverlay() {
  if (typeof window === 'undefined') return EMPTY_OVERLAY
  try {
    const raw = localStorage.getItem(DEMO_OVERLAY_KEY)
    if (!raw) return EMPTY_OVERLAY
    const parsed = JSON.parse(raw)
    return {
      watchlist: Array.isArray(parsed.watchlist) ? parsed.watchlist : null,
      positions: Array.isArray(parsed.positions) ? parsed.positions : [],
    }
  } catch {
    return EMPTY_OVERLAY
  }
}

function saveDemoOverlay(overlay) {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(DEMO_OVERLAY_KEY, JSON.stringify(overlay))
  } catch {
    // Cuota llena o disabled — silencioso
  }
}

function clearDemoOverlay() {
  if (typeof window === 'undefined') return
  localStorage.removeItem(DEMO_OVERLAY_KEY)
}

export function isDemoMode() {
  if (typeof window === 'undefined') return false
  return localStorage.getItem(DEMO_FLAG_KEY) === '1'
}

export function enableDemoMode() {
  if (typeof window === 'undefined') return
  localStorage.setItem(DEMO_FLAG_KEY, '1')
  // Limpiamos cualquier overlay residual al activar — siempre arranca limpio.
  clearDemoOverlay()
}

export function disableDemoMode() {
  if (typeof window === 'undefined') return
  localStorage.removeItem(DEMO_FLAG_KEY)
  localStorage.removeItem('rendi_token')
  localStorage.removeItem('rendi_user')
  clearDemoOverlay()
}

// ─── Error helper para acciones bloqueadas ───────────────────────────────────
// Para que api.js detecte y lance Error con mensaje custom.
const BLOCKED_MSG = 'En modo demo no podés guardar este cambio. Creá una cuenta gratis para usar tu portfolio real.'

function blocked() {
  return { __demoBlocked: true, message: BLOCKED_MSG }
}

// ─── Fixture: portfolio simulado de ~18 meses ────────────────────────────────
// Mix realista AR: Schwab USD (acciones US), Cocos ARS (acciones AR + CEDEARs),
// Binance crypto. Total ≈ US$ 28.000 al blue actual.

const BROKERS = [
  // Schwab e IBKR son brokers de acciones US → USD (no USDT).
  // USDT es exclusivo de exchanges cripto (Binance, etc).
  { id: 1, name: 'Schwab',  currency: 'USD'  },
  { id: 2, name: 'Cocos',   currency: 'ARS'  },
  { id: 3, name: 'Binance', currency: 'USDT' },
]

const POSITIONS = [
  // ── Schwab USD ──
  { id: 101, broker: 'Schwab',  asset: 'NVDA',  is_cash: 0, buy_price: 142.50, quantity: 35,  invested: 4987.50,  tc_compra: null, price_override: null, entry_date: '2024-08-12', commissions: 0 },
  { id: 102, broker: 'Schwab',  asset: 'AAPL',  is_cash: 0, buy_price: 178.20, quantity: 22,  invested: 3920.40,  tc_compra: null, price_override: null, entry_date: '2024-05-30', commissions: 0 },
  { id: 103, broker: 'Schwab',  asset: 'MSFT',  is_cash: 0, buy_price: 410.10, quantity: 8,   invested: 3280.80,  tc_compra: null, price_override: null, entry_date: '2024-11-04', commissions: 0 },
  { id: 104, broker: 'Schwab',  asset: 'TSLA',  is_cash: 0, buy_price: 215.30, quantity: 12,  invested: 2583.60,  tc_compra: null, price_override: null, entry_date: '2024-09-18', commissions: 0 },
  { id: 105, broker: 'Schwab',  asset: 'SPY',   is_cash: 0, buy_price: 528.40, quantity: 6,   invested: 3170.40,  tc_compra: null, price_override: null, entry_date: '2024-06-15', commissions: 0 },
  { id: 199, broker: 'Schwab',  asset: 'USD',   is_cash: 1, buy_price: null,   quantity: 1250, invested: 1250.00, tc_compra: null, price_override: null, entry_date: null,         commissions: 0 },

  // ── Cocos ARS (acciones AR + CEDEARs) ──
  { id: 201, broker: 'Cocos',   asset: 'GGAL',     is_cash: 0, buy_price: 4250,  quantity: 200, invested: 850000,  tc_compra: 1050, price_override: null, entry_date: '2024-04-10', commissions: 0 },
  { id: 202, broker: 'Cocos',   asset: 'YPFD',    is_cash: 0, buy_price: 28500, quantity: 30,  invested: 855000,  tc_compra: 1180, price_override: null, entry_date: '2024-10-22', commissions: 0 },
  { id: 203, broker: 'Cocos',   asset: 'AAPL.BA', is_cash: 0, buy_price: 18800, quantity: 40,  invested: 752000,  tc_compra: 1240, price_override: null, entry_date: '2025-01-15', commissions: 0 },
  { id: 204, broker: 'Cocos',   asset: 'AL30',    is_cash: 0, buy_price: 72500, quantity: 10,  invested: 725000,  tc_compra: 1320, price_override: null, entry_date: '2025-03-08', commissions: 0 },
  { id: 299, broker: 'Cocos',   asset: 'ARS',     is_cash: 1, buy_price: null,  quantity: 180000, invested: 180000, tc_compra: null, price_override: null, entry_date: null,        commissions: 0 },

  // ── Binance crypto ──
  { id: 301, broker: 'Binance', asset: 'BTC',  is_cash: 0, buy_price: 62500,  quantity: 0.085, invested: 5312.50, tc_compra: null, price_override: null, entry_date: '2024-07-22', commissions: 0 },
  { id: 302, broker: 'Binance', asset: 'ETH',  is_cash: 0, buy_price: 3120,   quantity: 1.2,   invested: 3744.00, tc_compra: null, price_override: null, entry_date: '2024-08-30', commissions: 0 },
  { id: 303, broker: 'Binance', asset: 'SOL',  is_cash: 0, buy_price: 165,    quantity: 14,    invested: 2310.00, tc_compra: null, price_override: null, entry_date: '2025-02-04', commissions: 0 },
  { id: 399, broker: 'Binance', asset: 'USDT', is_cash: 1, buy_price: null,   quantity: 820,   invested: 820.00,  tc_compra: null, price_override: null, entry_date: null,         commissions: 0 },
]

// Operaciones cerradas (para Operaciones page + win rate + profit factor)
const OPERATIONS = (() => {
  const ops = [
    { asset: 'NVDA', broker: 'Schwab', entry_price: 120, exit_price: 142, quantity: 10, pnl_usd: 220,  pnl_pct: 18.33, date: '2024-06-12', op_type: 'LONG' },
    { asset: 'MELI', broker: 'Schwab', entry_price: 1820, exit_price: 1740, quantity: 2, pnl_usd: -160, pnl_pct: -4.40, date: '2024-07-04', op_type: 'LONG' },
    { asset: 'GOOGL',broker: 'Schwab', entry_price: 165, exit_price: 182, quantity: 8, pnl_usd: 136,  pnl_pct: 10.30, date: '2024-08-20', op_type: 'LONG' },
    { asset: 'AMD',  broker: 'Schwab', entry_price: 148, exit_price: 132, quantity: 15, pnl_usd: -240, pnl_pct: -10.81,date: '2024-09-15', op_type: 'LONG' },
    { asset: 'BTC',  broker: 'Binance',entry_price: 58000,exit_price: 67500,quantity: 0.04, pnl_usd: 380, pnl_pct: 16.38,date: '2024-10-02', op_type: 'LONG' },
    { asset: 'GGAL', broker: 'Cocos',  entry_price: 3850, exit_price: 4400, quantity: 50, pnl_usd: 195, pnl_pct: 14.28,date: '2024-10-30', op_type: 'LONG' },
    { asset: 'TSLA', broker: 'Schwab', entry_price: 240, exit_price: 218, quantity: 5, pnl_usd: -110, pnl_pct: -9.17, date: '2024-11-08', op_type: 'LONG' },
    { asset: 'ETH',  broker: 'Binance',entry_price: 2850, exit_price: 3320, quantity: 0.5, pnl_usd: 235, pnl_pct: 16.49,date: '2024-12-04', op_type: 'LONG' },
    { asset: 'META', broker: 'Schwab', entry_price: 480, exit_price: 545, quantity: 4, pnl_usd: 260,  pnl_pct: 13.54, date: '2025-01-22', op_type: 'LONG' },
    { asset: 'AAPL', broker: 'Schwab', entry_price: 185, exit_price: 172, quantity: 10, pnl_usd: -130, pnl_pct: -7.03, date: '2025-02-18', op_type: 'LONG' },
    { asset: 'NVDA', broker: 'Schwab', entry_price: 130, exit_price: 156, quantity: 12, pnl_usd: 312,  pnl_pct: 20.00, date: '2025-03-12', op_type: 'LONG' },
    { asset: 'SOL',  broker: 'Binance',entry_price: 180, exit_price: 154, quantity: 8, pnl_usd: -208, pnl_pct: -14.44,date: '2025-03-28', op_type: 'LONG' },
    { asset: 'AVGO', broker: 'Schwab', entry_price: 142, exit_price: 168, quantity: 10, pnl_usd: 260,  pnl_pct: 18.31, date: '2025-04-15', op_type: 'LONG' },
    { asset: 'YPFD', broker: 'Cocos',  entry_price: 24500,exit_price: 27800,quantity: 20, pnl_usd: 280,  pnl_pct: 13.46, date: '2025-05-02', op_type: 'LONG' },
  ]
  return ops.map((o, i) => ({ id: 1000 + i, ...o, commissions: 0 }))
})()

// Cierres mensuales (para Monthly Reports / Reports timeline / Insights chart).
// CRÍTICO: tiene que incluir capital_final para que buildCumulativeReturnSeries
// pueda computar el TWR correctamente. Sin este campo, monthlyReturn = -100% y
// el drawdown queda atascado en -100% propagado por todos los meses.
//
// Modelo consistente entre meses:
//   capital_inicio[t] = capital_final[t-1]
//   pnl_total = pnl_realized + pnl_unrealized  → vuelve al cap_final
//   capital_final[t] = capital_inicio[t] + deposits − withdrawals + pnl_total
// Pesos relativos por broker (suman ~1.0). Determinan cuánto del global
// corresponde a cada broker — el chart ARS de Insights filtra por broker
// específico, así que sin entries por broker el chart ARS queda vacío.
const BROKER_WEIGHTS = { Schwab: 0.51, Cocos: 0.06, Binance: 0.43 }

const MONTHLY = (() => {
  const out = []
  const start = new Date('2024-04-01')
  const today = new Date()
  let valuation = 18500           // valor de mercado al inicio
  while (start < today) {
    const y = start.getFullYear()
    const m = start.getMonth() + 1
    const capInicio = Math.round(valuation)
    // Aporte esporádico: 35% de los meses con $400-800
    const deposit = Math.random() > 0.65 ? Math.round(400 + Math.random() * 400) : 0
    const withdrawal = 0
    // Rendimiento del mes: 1.2% mean ± 3% noise. Realista para retail diversificado.
    const monthReturn = 0.012 + (Math.random() - 0.5) * 0.06
    const pnlTotal = capInicio * monthReturn
    // Split realized / unrealized — la mayoría es unrealized (mark-to-market).
    const pnlRealized = Math.round(pnlTotal * 0.2 + (Math.random() - 0.5) * 200)
    const pnlUnrealized = Math.round(pnlTotal - pnlRealized)
    const capFinal = capInicio + deposit - withdrawal + pnlTotal
    valuation = capFinal

    // Entry global (agregado de todos los brokers)
    out.push({
      broker: 'global',
      year: y,
      month: m,
      capital_inicio: capInicio,
      capital_final: Math.round(capFinal),
      deposits: deposit,
      withdrawals: withdrawal,
      pnl_realized: pnlRealized,
      pnl_unrealized: pnlUnrealized,
    })

    // Entries por broker — proporcionales al peso. Insights los necesita
    // para el chart ARS (filtra por broker.currency === 'ARS').
    for (const [brokerName, weight] of Object.entries(BROKER_WEIGHTS)) {
      out.push({
        broker: brokerName,
        year: y,
        month: m,
        capital_inicio: Math.round(capInicio * weight),
        capital_final: Math.round(capFinal * weight),
        deposits: Math.round(deposit * weight),
        withdrawals: 0,
        pnl_realized: Math.round(pnlRealized * weight),
        pnl_unrealized: Math.round(pnlUnrealized * weight),
      })
    }
    start.setMonth(start.getMonth() + 1)
  }
  return out
})()

const MONTHLY_LAST_VALUATION = MONTHLY.length
  ? MONTHLY[MONTHLY.length - 1].capital_final
  : 18500

// ─── Reports timeline derivada de MONTHLY ───────────────────────────────────
// El backend devuelve PeriodReport por mes con metrics + headline. Acá
// armamos algo equivalente para que /reportes muestre la timeline visual
// (KPI strip, calendar heatmap, monthly table) sin "Not authenticated".

const MONTH_NAMES_ES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

const REPORTS_TIMELINE = (() => {
  // Solo los globals — el frontend agrupa por año
  const globals = MONTHLY.filter(m => m.broker === 'global')
  if (globals.length === 0) return []

  const today = new Date()
  const currentYear = today.getFullYear()
  const currentMonth = today.getMonth() + 1

  return globals.map((m, idx) => {
    const prev = idx > 0 ? globals[idx - 1] : null
    const baseValue = m.capital_inicio || 1
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    const pnlTotal = (m.capital_final || 0) - baseValue - net
    const delta_pct = baseValue > 0 ? (pnlTotal / baseValue) * 100 : 0
    const isCurrent = m.year === currentYear && m.month === currentMonth
    const isRelevant = Math.abs(pnlTotal) > 50 || Math.abs(net) > 50
    // Trades por mes: 2-8 (correlaciona con noise)
    const trades = 2 + Math.floor(Math.random() * 7)
    const winRate = 50 + (delta_pct > 0 ? 15 : -10) + Math.random() * 10
    const vsSp = delta_pct - (1.2 + (Math.random() - 0.5) * 2)  // benchmark ~1.2% mean

    let headline = 'Mes con movimiento moderado.'
    if (delta_pct > 5) headline = 'Mes sólido — rally generalizado del mercado.'
    else if (delta_pct > 2) headline = 'Buen rendimiento, por encima del benchmark.'
    else if (delta_pct < -3) headline = 'Mes difícil — corrección del mercado afectó la cartera.'
    else if (delta_pct < 0) headline = 'Mes ligeramente negativo, sin caídas relevantes.'

    return {
      period_key: `${m.year}-${String(m.month).padStart(2, '0')}`,
      period_label: `${MONTH_NAMES_ES[m.month - 1]} ${m.year}`,
      period_end: new Date(m.year, m.month, 0).toISOString().slice(0, 10),
      is_current: isCurrent,
      is_relevant: isRelevant || isCurrent,
      metrics: {
        start_value: m.capital_inicio,
        end_value: m.capital_final,
        delta_pct: +delta_pct.toFixed(2),
        delta_usd: Math.round(pnlTotal),
        realized_pnl: m.pnl_realized,
        unrealized_pnl: m.pnl_unrealized,
        deposits: m.deposits,
        withdrawals: m.withdrawals,
        trades_count: trades,
        win_rate: +winRate.toFixed(0),
        vs_sp500_pct: +vsSp.toFixed(1),
        vs_inflation_pct: +(delta_pct - 5).toFixed(1),
      },
      headline,
      subheadline: null,
      highlights: [],
      insights: [],
      children: [],
    }
  }).reverse()  // descendente — mes en curso primero
})()

// ─── Behavioral insights mock (Sprint 3-4) ──────────────────────────────────
// Hardcoded para mostrar el flow completo en demo: un sesgo high, otros
// medium/positive/insufficient. Los detectores reales corren contra
// operations en el backend; acá simulamos un payload coherente con OPERATIONS.

const BEHAVIORAL_INSIGHTS = {
  cards: [
    // ── Sprint 3 ──
    {
      code: 'disposition_effect',
      title: 'Vendés ganadoras más rápido que perdedoras',
      severity: 'medium',
      detected: true,
      score: 38,
      value_label: '0.55× (winners/losers)',
      one_liner: 'En promedio aguantás tus perdedoras 1.8× más tiempo que tus ganadoras. Vale la pena revisar criterios de salida.',
      evidence: {
        winners_count: 8, losers_count: 6, winners_avg_days: 32.5, losers_avg_days: 58.7, ratio: 0.55,
        sample_winners: [
          { asset: 'NVDA', days: 18, pnl: 220 },
          { asset: 'GOOGL', days: 24, pnl: 136 },
          { asset: 'AVGO', days: 28, pnl: 260 },
        ],
        sample_losers: [
          { asset: 'AMD', days: 87, pnl: -240 },
          { asset: 'TSLA', days: 72, pnl: -110 },
          { asset: 'SOL', days: 65, pnl: -208 },
        ],
      },
      references: ['Shefrin & Statman (1985) — The disposition to sell winners too early and ride losers too long.'],
    },
    {
      code: 'overtrade',
      title: 'Frecuencia de trades razonable',
      severity: 'positive',
      detected: false,
      score: 28,
      value_label: '1.1× / año',
      one_liner: 'Tu portfolio rota 1.1× por año. Estás en el rango del inversor a mediano plazo.',
      evidence: { total_trades: 14, period_days: 412, period_years: 1.13, annual_ops: 12.4, annual_turnover: 1.1, total_notional: 22500, capital_avg: 19200 },
      references: ['Barber & Odean (2000) — Trading is hazardous to your wealth.'],
    },
    {
      code: 'loss_aversion',
      title: 'Tendencia a aguantar perdedoras grandes',
      severity: 'medium',
      detected: true,
      score: 45,
      value_label: 'losers 1.7× winners',
      one_liner: 'Tus losers tienen tamaño promedio 1.7× tus winners. Vale revisar criterios de salida — un stop loss firme ayudaría.',
      evidence: { winners_count: 8, losers_count: 6, winners_avg_size_usd: 1450, losers_avg_size_usd: 2465, ratio: 1.7 },
      references: ['Kahneman & Tversky (1979) — Prospect theory: an analysis of decision under risk.'],
    },
    {
      code: 'averaging_down',
      title: 'Sin promedios a la baja detectados',
      severity: 'positive',
      detected: false,
      score: 0,
      value_label: '0 instancias',
      one_liner: 'No detectamos compras del mismo ticker a precios decrecientes en ventanas cortas.',
      evidence: { instances: [], total_instances: 0, avg_drop_pct: 0, total_assets_checked: 12 },
      references: ['Odean (1998) — Are investors reluctant to realize their losses?'],
    },
    // ── Sprint 3.1 ──
    {
      code: 'concentration',
      title: 'NVDA pesa fuerte en tu cartera',
      severity: 'medium',
      detected: true,
      score: 56,
      value_label: 'Top 1: 28%',
      one_liner: 'Top 1 = 28%, Top 3 = 62%. El portfolio depende mucho de pocos activos.',
      evidence: {
        top_asset: 'NVDA',
        top1_pct: 28.0,
        top3_pct: 62.0,
        top5_pct: 78.5,
        total_assets: 12,
        total_value_usd: 22300,
        top_5: [
          { asset: 'NVDA', value_usd: 6244, pct: 28.0 },
          { asset: 'BTC',  value_usd: 4079, pct: 18.3 },
          { asset: 'ETH',  value_usd: 3500, pct: 15.7 },
          { asset: 'AAPL', value_usd: 1924, pct: 8.6 },
          { asset: 'SOL',  value_usd: 1750, pct: 7.8 },
        ],
      },
      references: ['Markowitz (1952) — Portfolio selection.'],
    },
    {
      code: 'inflation_loss',
      title: 'Inflación erosionando tu cash ARS',
      severity: 'medium',
      detected: true,
      score: 22,
      value_label: '−US$ 87',
      one_liner: 'Perdiste ~US$ 87 en poder de compra. Considerá MEP, Lecaps en pesos o CEDEARs para hedge.',
      evidence: {
        cash_ars_pesos: 180000,
        inflation_cum_pct: 75.8,
        loss_pesos: 77627,
        loss_usd: 54.86,
      },
      references: ['INDEC — Índice de Precios al Consumidor (IPC).'],
    },
    {
      code: 'counterfactual',
      title: 'Vender temprano te costó algo de upside',
      severity: 'medium',
      detected: true,
      score: 64,
      value_label: '+US$ 642',
      one_liner: 'Hubieras hecho ~US$ 642 más si mantenías. No siempre pasa, pero es interesante mirar el patrón.',
      evidence: {
        realized_total_usd: 1058,
        hypothetical_total_usd: 1700,
        delta_total_usd: 642,
        trades_analyzed: 14,
        top_misses: [
          { asset: 'NVDA',  exit_price: 142, current_price: 178.50, delta_usd: 365, exit_date: '2024-06-12' },
          { asset: 'GOOGL', exit_price: 182, current_price: 195.60, delta_usd: 108, exit_date: '2024-08-20' },
          { asset: 'AVGO',  exit_price: 168, current_price: 198.40, delta_usd: 304, exit_date: '2025-04-15' },
          { asset: 'BTC',   exit_price: 67500, current_price: 81595, delta_usd: 564, exit_date: '2024-10-02' },
          { asset: 'TSLA',  exit_price: 218, current_price: 248.10, delta_usd: 150, exit_date: '2024-11-08' },
        ],
      },
      references: ['Kahneman (2011) — Thinking, Fast and Slow (counterfactual thinking).'],
    },
    // ── Sprint 3.2 ──
    {
      code: 'winrate_payoff',
      title: 'Combinación win rate + payoff sólida',
      severity: 'positive',
      detected: false,
      score: 0,
      value_label: '57% · payoff 1.95×',
      one_liner: 'Win rate 57% con payoff 1.95× = expectancy +49.50 USD por operación. Funciona.',
      evidence: {
        win_rate_pct: 57.1,
        winners_count: 8,
        losers_count: 6,
        total_trades: 14,
        avg_win_usd: 247.50,
        avg_loss_usd: 127.20,
        payoff_ratio: 1.95,
        expectancy_usd: 49.50,
      },
      references: ['Van Tharp (1998) — Trade Your Way to Financial Freedom (expectancy formula).'],
    },
    {
      code: 'home_bias',
      title: 'Balance moderado AR/internacional',
      severity: 'low',
      detected: false,
      score: 28,
      value_label: '6% AR',
      one_liner: '6% AR + 94% internacional. Si tu vida es en pesos (gastos, salario), podés sumar exposición ARS/CEDEARs para hedge natural.',
      evidence: {
        ar_pct: 6.2,
        intl_pct: 93.8,
        ar_value_usd: 1392,
        intl_value_usd: 20908,
        total_value_usd: 22300,
      },
      references: ['French & Poterba (1991) — Investor diversification and international equity markets.'],
    },
    {
      code: 'cash_drag',
      title: 'Nivel de cash equilibrado',
      severity: 'positive',
      detected: false,
      score: 0,
      value_label: '9% en cash',
      one_liner: '9% en cash — cushion razonable para liquidez sin perder oportunidad.',
      evidence: {
        cash_pct: 9.3,
        cash_ars_pct: 0.6,
        cash_usd_amount: 1947,
        cash_ars_usd_equiv: 127,
        invested_usd: 20226,
        total_usd: 22300,
      },
      references: ['Cash drag literature — Vanguard research on optimal cash allocation.'],
    },
    // ── Sprint 3.3 ──
    {
      code: 'recency_bias',
      title: 'Pocas instancias de compras altas',
      severity: 'low',
      detected: false,
      score: 18,
      value_label: '12% del invested',
      one_liner: '12% del invested compró alto. Magnitud baja, no es patrón sistemático.',
      evidence: {
        chase_pct: 12.4,
        chase_pumps_invested_usd: 2780,
        total_invested_usd: 22300,
        flagged_count: 2,
        flagged_assets: [
          { asset: 'TSLA', buy_price: 215.30, current_price: 248.10, drawdown_pct: 13.2, invested_usd: 1290 },
          { asset: 'SOL',  buy_price: 165,    current_price: 198.40, drawdown_pct: 16.8, invested_usd: 1490 },
        ],
      },
      references: ['Barber & Odean (2008) — All that glitters: the effect of attention and news on individual investor behavior.'],
    },
    {
      code: 'sector_concentration',
      title: 'Tech pesa fuerte en tu portfolio',
      severity: 'medium',
      detected: true,
      score: 64,
      value_label: 'Tech: 42%',
      one_liner: 'Tech = 42% · Top 3 sectores = 78%. Diversificar entre sectores reduce el riesgo idiosincrático.',
      evidence: {
        top_sector: 'Tech',
        top1_pct: 42.0,
        top3_pct: 78.0,
        total_sectors: 6,
        total_value_usd: 22300,
        unmapped_count: 0,
        breakdown: [
          { sector: 'Tech',                  value_usd: 9366,  pct: 42.0 },
          { sector: 'Crypto',                value_usd: 6244,  pct: 28.0 },
          { sector: 'ETF / Diversified',     value_usd: 1784,  pct: 8.0 },
          { sector: 'AR · Financials',       value_usd: 1561,  pct: 7.0 },
          { sector: 'AR · Bonos',            value_usd: 1338,  pct: 6.0 },
          { sector: 'AR · CEDEAR (Tech)',    value_usd: 1115,  pct: 5.0 },
          { sector: 'Stablecoin',            value_usd: 892,   pct: 4.0 },
        ],
      },
      references: ['Markowitz (1952) — Portfolio selection. Sector-level diversification literature.'],
    },
  ],
  summary: {
    total_detected: 5,
    total_high: 0,
    total_medium: 5,
    total_positive: 4,
    total_cards: 12,
  },
  generated_at: new Date().toISOString(),
}

// CAGR sintético del demo. Lo computamos sobre los globals usando misma
// fórmula que el backend (TWR mensual + media geométrica anualizada).
const DEMO_CAGR = (() => {
  const globals = MONTHLY.filter(m => m.broker === 'global')
  if (globals.length < 2) return { cagr: null, months: globals.length }
  const factors = globals.map(m => {
    const ci = m.capital_inicio || 0
    const cf = m.capital_final || 0
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    if (ci <= 0) return 1
    return 1 + Math.max(-0.95, (cf - ci - net) / ci)
  })
  const prod = factors.reduce((a, b) => a * b, 1)
  const monthsCount = factors.length
  const cagr = Math.pow(prod, 12 / monthsCount) - 1
  return { cagr: +(cagr * 100).toFixed(2), months: monthsCount }
})()

// Snapshots semanales DERIVADOS del MONTHLY para que ambos cuenten la misma
// historia. Interpolamos linealmente entre capital_inicio y capital_final
// de cada mes para producir snapshots semanales coherentes.
//
// Esto evita la inconsistencia del bug previo donde snapshots y monthly se
// generaban independientes y los flujos del TWR no cerraban.
const SNAPSHOTS = (() => {
  if (MONTHLY.length === 0) return []
  const out = []
  let cumDeposits = MONTHLY[0].capital_inicio
  for (const m of MONTHLY) {
    const capStart = m.capital_inicio
    const capEnd = m.capital_final
    // 4 snapshots por mes (~semanal). Interpolación lineal con noise.
    for (let w = 0; w < 4; w++) {
      const frac = w / 4
      const valueT = capStart + (capEnd - capStart) * frac + (Math.random() - 0.5) * 200
      const d = new Date(m.year, m.month - 1, 1 + w * 7)
      out.push({
        date: d.toISOString().slice(0, 10),
        total_value: Math.round(valueT * 100) / 100,
        total_invested: Math.round(cumDeposits * 0.95 * 100) / 100,
        net_deposited: Math.round(cumDeposits * 100) / 100,
      })
      // Aporte llega aprox la semana 2 del mes
      if (w === 1 && m.deposits) {
        cumDeposits += m.deposits
      }
    }
  }
  // Snapshot del día actual con valuation final
  const today = new Date()
  out.push({
    date: today.toISOString().slice(0, 10),
    total_value: Math.round(MONTHLY_LAST_VALUATION * 100) / 100,
    total_invested: Math.round(cumDeposits * 0.95 * 100) / 100,
    net_deposited: Math.round(cumDeposits * 100) / 100,
  })
  return out.sort((a, b) => b.date.localeCompare(a.date))
})()

// Watchlist demo base (estado inicial — el overlay puede agregar/quitar)
const WATCHLIST_BASE = [
  { symbol: 'AVGO', asset_type: 'stock', added_at: '2025-03-20', price: 168.40, change_pct: 1.2 },
  { symbol: 'PLTR', asset_type: 'stock', added_at: '2025-04-08', price: 24.85,  change_pct: -2.1 },
  { symbol: 'COIN', asset_type: 'stock', added_at: '2025-05-01', price: 215.30, change_pct: 4.5 },
]

// Precios actuales fake (snapshot del momento)
const PRICES = {
  // US stocks
  NVDA: 178.50, AAPL: 192.40, MSFT: 438.20, TSLA: 248.10, AMD: 152.80, SPY: 568.20, GOOGL: 195.60,
  META: 612.40, AVGO: 198.40, MELI: 1985.00,
  // Crypto
  BTC: 81595.00, ETH: 3320.00, SOL: 198.40,
  // BCBA / CEDEARs (en ARS)
  'GGAL.BA': 4820, 'YPFD.BA': 31200, 'AAPL.BA': 22400, 'AL30.BA': 78500,
  // Watchlist
  PLTR: 24.85, COIN: 215.30,
}

// Benchmarks mensuales para Insights chart (S&P / Inflación AR / Dólar Blue)
const BENCHMARKS = (() => {
  const out = { sp500: {}, inflation_ar: {}, dolar_blue: {} }
  const start = new Date('2023-01-01')
  const today = new Date()
  // S&P: arranca en 4700, crece ~10% anual con noise
  let sp = 4700
  // Blue: arranca en 850, sube a 1415 hoy (drift fuerte)
  let blue = 850
  while (start <= today) {
    const key = start.toISOString().slice(0, 7)
    // S&P month-end close: +1% mean, ±2.5% noise
    sp = sp * (1 + 0.009 + (Math.random() - 0.5) * 0.05)
    out.sp500[key] = Math.round(sp * 100) / 100
    // Inflación AR mensual % (alta al inicio, desacelerando — realista AR)
    const monthsSince = (start.getFullYear() - 2023) * 12 + start.getMonth()
    const baseInflation = Math.max(2.5, 12 - monthsSince * 0.25)
    out.inflation_ar[key] = Math.round((baseInflation + (Math.random() - 0.5) * 1.5) * 100) / 100
    // Dólar blue tendencial
    const driftBlue = 0.025 - monthsSince * 0.0008  // se desacelera
    blue = blue * (1 + driftBlue + (Math.random() - 0.5) * 0.04)
    out.dolar_blue[key] = Math.round(blue)
    start.setMonth(start.getMonth() + 1)
  }
  return { ...out, fetched_at: new Date().toISOString() }
})()

const DOLAR = {
  blue:   { compra: 1395, venta: 1415 },
  mep:    { compra: 1420, venta: 1424 },
  ccl:    { compra: 1430, venta: 1432 },
  cripto: { compra: 1421, venta: 1422 },
  fetched_at: new Date().toISOString(),
}

// Strip de índices del Home — shape exacta del backend get_indices_strip()
const INDICES_STRIP = [
  { symbol: 'SPX',  label: 'S&P 500',    kind: 'equity', price: 5840.50, change_pct: 0.42 },
  { symbol: 'IXIC', label: 'NASDAQ 100', kind: 'equity', price: 18925.30, change_pct: 1.28 },
  { symbol: 'MERV', label: 'Merval',     kind: 'equity', price: 2150420, change_pct: -0.85 },
  { symbol: 'BTC',  label: 'Bitcoin',    kind: 'crypto', price: 81595, change_pct: 2.7 },
  { symbol: 'ETH',  label: 'Ethereum',   kind: 'crypto', price: 3320, change_pct: 1.7 },
  { symbol: 'GOLD', label: 'Oro',        kind: 'commodity', price: 2748.20, change_pct: 0.15 },
]

// Movers — top gainers + losers por mercado
const MOVERS = {
  sp500: {
    gainers: [
      { symbol: 'AVGO', label: 'Broadcom',           price: 198.40, change_pct: 5.5 },
      { symbol: 'NVDA', label: 'NVIDIA',             price: 178.50, change_pct: 4.4 },
      { symbol: 'ORCL', label: 'Oracle',             price: 178.40, change_pct: 3.1 },
      { symbol: 'CSCO', label: 'Cisco',              price: 56.40,  change_pct: 13.4 },
      { symbol: 'ACN',  label: 'Accenture',          price: 348.40, change_pct: 2.7 },
    ],
    losers: [
      { symbol: 'QCOM', label: 'Qualcomm',           price: 165.40, change_pct: -6.1 },
      { symbol: 'INTC', label: 'Intel',              price: 32.20,  change_pct: -3.6 },
      { symbol: 'TSLA', label: 'Tesla',              price: 248.10, change_pct: -2.1 },
      { symbol: 'AMZN', label: 'Amazon',             price: 215.30, change_pct: -1.1 },
      { symbol: 'LLY',  label: 'Eli Lilly',          price: 758.20, change_pct: -0.8 },
    ],
  },
  merval: {
    gainers: [
      { symbol: 'BBAR.BA', label: 'BBVA Argentina',  price: 12400, change_pct: 2.2 },
      { symbol: 'SUPV.BA', label: 'Supervielle',     price: 1820,  change_pct: 1.9 },
      { symbol: 'VALO.BA', label: 'Valores',         price: 320,   change_pct: 1.7 },
      { symbol: 'LOMA.BA', label: 'Loma Negra',      price: 4820,  change_pct: 1.6 },
      { symbol: 'YPFD.BA', label: 'YPF',             price: 31200, change_pct: 1.2 },
    ],
    losers: [
      { symbol: 'AGRO.BA', label: 'Agrometal',       price: 1240,  change_pct: -4.0 },
      { symbol: 'HARG.BA', label: 'Holcim Argentina',price: 1820,  change_pct: -2.6 },
      { symbol: 'BYMA.BA', label: 'BYMA',            price: 248,   change_pct: -2.2 },
      { symbol: 'TXAR.BA', label: 'Ternium',         price: 1240,  change_pct: -1.7 },
      { symbol: 'TRAN.BA', label: 'Transener',       price: 1820,  change_pct: -0.7 },
    ],
  },
  crypto: {
    gainers: [
      { symbol: 'XRP-USD',   label: 'XRP',           price: 0.62, change_pct: 5.7 },
      { symbol: 'ADA-USD',   label: 'Cardano',       price: 0.51, change_pct: 3.2 },
      { symbol: 'DOGE-USD',  label: 'Dogecoin',      price: 0.14, change_pct: 2.9 },
      { symbol: 'BTC-USD',   label: 'Bitcoin',       price: 81595, change_pct: 2.7 },
      { symbol: 'AVAX-USD',  label: 'Avalanche',     price: 32.40, change_pct: 2.5 },
    ],
    losers: [
      { symbol: 'MATIC-USD', label: 'Polygon',       price: 0.42, change_pct: -1.5 },
      { symbol: 'BCH-USD',   label: 'Bitcoin Cash',  price: 412,  change_pct: 0.4 },
      { symbol: 'LTC-USD',   label: 'Litecoin',      price: 92.40, change_pct: 0.5 },
      { symbol: 'ATOM-USD',  label: 'Cosmos',        price: 4.80, change_pct: 1.2 },
      { symbol: 'BNB-USD',   label: 'BNB',           price: 615,  change_pct: 1.3 },
    ],
  },
}

// Noticias del mercado — mock con shape del backend
const NEWS_MARKET = [
  {
    title: 'La Reserva Federal mantiene tasas en 4.25-4.50% y modera expectativas de recortes',
    summary: 'Powell confirmó una pausa en el ciclo de baja de tasas y enfatizó que aún no hay evidencia suficiente para una flexibilización rápida.',
    url: 'https://example.com/news/fed-hold',
    published_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    query_source: 'Federal Reserve interest rates',
    category: 'macro',
    source: 'reuters_es',
    tags: ['fed', 'tasas', 'usa', 'macro'],
  },
  {
    title: 'NVIDIA cierra arriba 4.4% en una rotación favorable hacia semiconductores',
    summary: 'El sector tech lideró la jornada con Broadcom +5.5% y NVIDIA +4.4%, impulsado por reporte trimestral de TSMC.',
    url: 'https://example.com/news/nvda-rally',
    published_at: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString(),
    query_source: 'S&P 500 stocks today',
    category: 'market',
    source: 'investing_com',
    tags: ['nvda', 'semiconductores', 'mercado'],
  },
  {
    title: 'Inflación argentina de abril en 2.8%: continúa la desaceleración mensual',
    summary: 'El INDEC reportó que la inflación se desaceleró al 2.8% mensual en abril, marcando la cifra más baja en 14 meses.',
    url: 'https://example.com/news/indec-cpi',
    published_at: new Date(Date.now() - 8 * 60 * 60 * 1000).toISOString(),
    query_source: 'inflación Argentina INDEC',
    category: 'macro',
    source: 'investing_com',
    tags: ['inflacion', 'indec', 'argentina'],
  },
  {
    title: 'El Merval cae 0.85% afectado por toma de ganancias en bancos',
    summary: 'GGAL retrocedió pese al buen reporte mientras los inversores rotan hacia bonos soberanos en USD.',
    url: 'https://example.com/news/merval-bancos',
    published_at: new Date(Date.now() - 12 * 60 * 60 * 1000).toISOString(),
    query_source: 'Merval acciones Argentina',
    category: 'market',
    source: 'investing_com',
    tags: ['merval', 'argentina', 'bancos'],
  },
  {
    title: 'Bitcoin supera los US$81.000 con flujos institucionales fuertes',
    summary: 'El precio del Bitcoin escaló otro 2.7% en las últimas 24h en medio de récord de inflows a ETFs spot.',
    url: 'https://example.com/news/btc-81k',
    published_at: new Date(Date.now() - 14 * 60 * 60 * 1000).toISOString(),
    query_source: 'BTC bitcoin price',
    category: 'market',
    source: 'investing_com',
    tags: ['btc', 'crypto', 'etf'],
  },
]

// Noticias del portfolio — relevantes para tickers del fixture
const NEWS_PORTFOLIO = [
  {
    title: 'NVIDIA: 8 razones detrás del repunte del 4.4% en la última jornada',
    summary: 'Analistas destacan demanda sostenida en data centers y guidance trimestral robusto.',
    url: 'https://example.com/news/nvda-analyst',
    published_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    query_source: 'NVDA acciones',
    category: 'portfolio',
    source: 'reuters_es',
    tags: ['nvda'],
  },
  {
    title: 'GGAL reporta resultados Q1 por encima de lo esperado',
    summary: 'Galicia anunció utilidades por 158 mil millones y mejora la guía para el resto del año.',
    url: 'https://example.com/news/ggal-q1',
    published_at: new Date(Date.now() - 18 * 60 * 60 * 1000).toISOString(),
    query_source: 'GGAL acciones',
    category: 'portfolio',
    source: 'investing_com',
    tags: ['ggal'],
  },
]

// Eventos — earnings + dividendos + macro
const _todayPlus = (days) => {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

const EVENTS_PORTFOLIO = [
  { ticker: 'NVDA', event_type: 'earnings',    event_date: _todayPlus(5),  confirmed: 1, details: { title: 'NVDA · Reporte Q1 2026' } },
  { ticker: 'AAPL', event_type: 'ex_dividend', event_date: _todayPlus(2),  confirmed: 1, details: { amount: 0.25 } },
  { ticker: 'MSFT', event_type: 'earnings',    event_date: _todayPlus(12), confirmed: 1, details: { title: 'MSFT · Reporte Q3 FY26' } },
  { ticker: 'TSLA', event_type: 'earnings',    event_date: _todayPlus(9),  confirmed: 0, details: { title: 'TSLA · Earnings (estimado)' } },
]

const EVENTS_POPULAR = [
  { ticker: '',     event_type: 'macro',       event_date: _todayPlus(3),  confirmed: 1, details: { title: 'FOMC · Decisión de tasas Fed' } },
  { ticker: '',     event_type: 'macro',       event_date: _todayPlus(7),  confirmed: 1, details: { title: 'INDEC · IPC abril Argentina' } },
  { ticker: 'NVDA', event_type: 'earnings',    event_date: _todayPlus(5),  confirmed: 1, details: { title: 'NVDA · Reporte trimestral' } },
  { ticker: 'AAPL', event_type: 'ex_dividend', event_date: _todayPlus(2),  confirmed: 1, details: { amount: 0.25 } },
  { ticker: 'GGAL', event_type: 'earnings',    event_date: _todayPlus(14), confirmed: 0, details: { title: 'GGAL · Resultados Q1 (estimado)' } },
]

// ─── Mock handler para api.js ────────────────────────────────────────────────
// Recibe (method, path) y devuelve la respuesta. null = no hay mock → la
// llamada real se ejecuta (no debería pasar pero por defensa).

export function handleDemoRequest(method, path, body) {
  // Normalizar query string fuera del match base
  const [basePath, query] = path.split('?')
  const overlay = getDemoOverlay()

  // ── GET endpoints ──────────────────────────────────────────────────────────
  if (method === 'GET') {
    if (basePath === '/positions') {
      // Fixture + posiciones agregadas por el user en demo
      return [...POSITIONS, ...overlay.positions]
    }
    if (basePath === '/brokers')     return BROKERS
    if (basePath === '/operations')  return OPERATIONS
    if (basePath === '/monthly')     return MONTHLY
    if (basePath === '/snapshots')   return SNAPSHOTS
    if (basePath === '/watchlist') {
      // Shape: { items: [...] } — coincide con el backend real.
      // Si el user nunca tocó la watchlist, devolvemos la base. Una vez que la
      // tocó (agregó o quitó algo), el overlay reemplaza a la base entera.
      const items = overlay.watchlist != null ? overlay.watchlist : WATCHLIST_BASE
      return { items }
    }
    if (basePath === '/dolar')       return DOLAR
    if (basePath === '/benchmarks')  return BENCHMARKS
    if (basePath === '/imports')     return []
    if (basePath === '/config')      return { tc_mep: 1424, tc_blue: 1415 }
    if (basePath === '/home/personal') {
      return { cards: [
        { kind: 'holding_move', value_tone: 'positive', headline: 'NVDA subió hoy', value: '+4.4%', context: '$178.50', cta_label: 'Ver posición →', cta_href: '/posiciones' },
        { kind: 'holding_move', value_tone: 'negative', headline: 'TSLA bajó hoy', value: '−2.1%', context: '$248.10', cta_label: 'Ver posición →', cta_href: '/posiciones' },
        { kind: 'earnings_soon', value_tone: 'neutral', headline: 'Earnings de NVDA', value: 'en 5 días', context: '2026-05-19', cta_label: 'Ver detalle →', cta_href: '/novedades?tab=eventos' },
      ] }
    }
    if (basePath.startsWith('/home/heatmap')) {
      const market = (query || '').match(/market=([^&]+)/)?.[1] || 'sp500'
      return { blocks: buildHeatmapBlocks(market) }
    }
    if (basePath === '/home/indices') return { items: INDICES_STRIP }
    if (basePath.startsWith('/home/movers')) {
      const market = (query || '').match(/market=([^&]+)/)?.[1] || 'sp500'
      return MOVERS[market] || { gainers: [], losers: [] }
    }
    if (basePath === '/events/portfolio') return { events: EVENTS_PORTFOLIO }
    if (basePath === '/events/popular')   return { events: EVENTS_POPULAR }
    if (basePath === '/news/portfolio')   return { news: NEWS_PORTFOLIO, count: NEWS_PORTFOLIO.length }
    if (basePath === '/news/market')      return { news: NEWS_MARKET, count: NEWS_MARKET.length }
    if (basePath === '/prices') {
      // Devolver subset de PRICES según query symbols=A,B,C
      const symbols = (query || '').match(/symbols=([^&]+)/)?.[1]?.split(',') || []
      const out = {}
      for (const s of symbols) {
        if (PRICES[s] != null) out[s] = PRICES[s]
      }
      return out
    }
    if (basePath === '/prices/history') {
      return buildPriceHistory(query)
    }
    // Reports timeline (Reportes page)
    if (basePath === '/reports/timeline') {
      return { reports: REPORTS_TIMELINE, total: REPORTS_TIMELINE.length }
    }
    // Goals + CAGR (Objetivos page)
    if (basePath === '/goals') return []
    if (basePath === '/goals/cagr') return DEMO_CAGR
    // Behavioral insights — sesgos comportamentales (Sprint 3-4)
    if (basePath === '/behavioral/insights') return BEHAVIORAL_INSIGHTS
    // Insights endpoints opcionales — devuelven shape vacío para no romper
    if (basePath.startsWith('/insights')) return {}
    if (basePath.startsWith('/goals'))    return []
    return null
  }

  // ── POST / PUT / DELETE ────────────────────────────────────────────────────
  // El demo soporta dos acciones con persistencia local (overlay):
  //   - watchlist (agregar/quitar)
  //   - posiciones (agregar manual)
  // El resto devuelve { __demoBlocked: true } para que api.js lance un Error
  // con mensaje claro y el componente lo muestre como toast/error inline.

  // ── Snapshots: silenciar (no falla pero tampoco persistimos)
  if (method === 'POST' && basePath === '/snapshots') return { ok: true }

  // ── Watchlist: agregar / quitar con persistencia
  if (method === 'POST' && basePath === '/watchlist' && body?.symbol) {
    const symbol = String(body.symbol).toUpperCase()
    // Punto de partida: si el user nunca tocó la watchlist, arrancamos del base
    const current = overlay.watchlist ?? [...WATCHLIST_BASE]
    if (!current.some(w => (w.symbol || '').toUpperCase() === symbol)) {
      current.push({
        symbol,
        asset_type: 'stock',
        added_at: new Date().toISOString().slice(0, 10),
        price: PRICES[symbol] || null,
        change_pct: null,
      })
      saveDemoOverlay({ ...overlay, watchlist: current })
    }
    return { ok: true, symbol }
  }
  if (method === 'DELETE' && basePath.startsWith('/watchlist/')) {
    const symbol = decodeURIComponent(basePath.slice('/watchlist/'.length)).toUpperCase()
    const current = overlay.watchlist ?? [...WATCHLIST_BASE]
    const next = current.filter(w => (w.symbol || '').toUpperCase() !== symbol)
    saveDemoOverlay({ ...overlay, watchlist: next })
    return { ok: true }
  }

  // ── Agregar posición manual: persiste
  if (method === 'POST' && basePath === '/positions' && body) {
    // ID sintético >= 9000 para no colisionar con la fixture
    const id = 9000 + overlay.positions.length
    const entry_date = body.entry_date || new Date().toISOString().slice(0, 10)
    const newPosition = {
      id,
      broker: body.broker,
      asset: body.asset,
      is_cash: body.is_cash ? 1 : 0,
      buy_price: body.buy_price != null ? Number(body.buy_price) : null,
      quantity: body.quantity != null ? Number(body.quantity) : null,
      invested: body.invested != null ? Number(body.invested) : null,
      tc_compra: body.tc_compra != null ? Number(body.tc_compra) : null,
      price_override: body.price_override != null ? Number(body.price_override) : null,
      notes: body.notes || null,
      entry_date,
      commissions: body.commissions != null ? Number(body.commissions) : 0,
      __demo: true,
    }
    saveDemoOverlay({
      ...overlay,
      positions: [...overlay.positions, newPosition],
    })
    return newPosition
  }

  // ── Bloqueadas: editar / eliminar / vender posición, op manual, importar
  if (method === 'PUT' && basePath.startsWith('/positions/')) return blocked()
  if (method === 'DELETE' && basePath.startsWith('/positions/')) return blocked()
  if (basePath === '/positions/sell') return blocked()
  if (basePath.startsWith('/operations')) return blocked()
  if (basePath.startsWith('/imports')) return blocked()
  if (basePath.startsWith('/brokers')) return blocked()
  if (basePath.startsWith('/auth/change-password')) return blocked()

  // ── AI chat: respuesta hardcodeada explicando el demo
  if (basePath === '/ai/chat') {
    return {
      reply: 'Estás en modo demo. Para usar el coach con tu portfolio real, creá una cuenta gratis y subí tu CSV.',
    }
  }

  // Default: 200 ok silencioso para no romper handlers no mapeados
  return { ok: true }
}

// ─── Heatmap mock builder ────────────────────────────────────────────────────

function buildHeatmapBlocks(market) {
  const TICKERS = {
    sp500: [
      ['AAPL', 192.40, 1.0, 3600], ['MSFT', 438.20, 1.2, 3250], ['NVDA', 178.50, 4.4, 3100],
      ['GOOGL', 195.60, -0.4, 2400], ['AMZN', 215.30, -1.1, 2200], ['META', 612.40, 0.3, 1550],
      ['TSLA', 248.10, -2.1, 920], ['AVGO', 198.40, 5.5, 920], ['LLY', 758.20, -0.8, 720],
      ['V', 286.40, 0.7, 600], ['WMT', 92.10, 0.8, 740], ['XOM', 118.20, 0.8, 470],
      ['UNH', 542.00, -0.5, 510], ['MA', 488.20, -0.1, 460], ['PG', 168.40, 0.3, 400],
      ['JNJ', 158.20, 0.2, 380], ['COST', 920.40, 0.8, 410], ['BAC', 42.50, 0.0, 330],
      ['ORCL', 178.40, 3.1, 480], ['CRM', 320.10, 1.1, 310], ['CVX', 158.20, 0.3, 295],
      ['KO', 64.30, 0.3, 280], ['ADBE', 540.20, 0.4, 245], ['AMD', 152.80, 0.9, 245],
      ['NFLX', 685.40, -0.7, 290], ['TMO', 580.40, 0.5, 220], ['QCOM', 165.40, -6.1, 185],
      ['LIN', 478.20, -0.3, 230], ['INTC', 32.20, -3.6, 138], ['CSCO', 56.40, 13.4, 230],
      ['ABT', 118.40, 1.3, 205], ['WFC', 64.20, 0.4, 220], ['ACN', 348.40, 2.7, 220],
      ['MCD', 285.40, -0.3, 205], ['PFE', 28.40, -0.8, 160], ['PM', 132.50, 2.1, 205],
      ['IBM', 218.40, 1.8, 200], ['NOW', 950.20, 4.0, 195],
    ],
    merval: [
      ['GGAL.BA', 4820, 0.1, 5500], ['YPFD.BA', 31200, 1.2, 4900], ['PAMP.BA', 2840, -0.5, 4100],
      ['BMA.BA', 8920, 0.7, 3800], ['BBAR.BA', 12400, 2.2, 2200], ['ALUA.BA', 920, -0.1, 1900],
      ['CRES.BA', 1820, 0.8, 1700], ['TXAR.BA', 1240, -1.7, 1400], ['COME.BA', 248, 0.5, 1300],
      ['EDN.BA', 2940, 0.5, 1200], ['TGSU2.BA', 4820, 0.6, 1100], ['TGNO4.BA', 2200, -0.3, 720],
      ['CEPU.BA', 1840, 0.4, 700], ['MIRG.BA', 8420, 0.1, 620], ['VALO.BA', 320, 1.7, 580],
      ['TRAN.BA', 1820, -0.7, 540], ['LOMA.BA', 4820, 1.6, 460], ['AGRO.BA', 1240, -4.0, 410],
      ['SUPV.BA', 1820, 1.9, 380], ['BYMA.BA', 248, -2.2, 350], ['HARG.BA', 1820, -2.6, 320],
      ['CVH.BA', 1240, 2.7, 290],
    ],
    crypto: [
      ['BTC-USD', 81595, 2.7, 1620], ['ETH-USD', 3320, 1.7, 405], ['SOL-USD', 198.40, 1.9, 95],
      ['BNB-USD', 615, 1.3, 89], ['XRP-USD', 0.62, 5.7, 64], ['ADA-USD', 0.51, 3.2, 18],
      ['DOGE-USD', 0.14, 2.9, 21], ['TRX-USD', 0.17, 1.5, 14], ['AVAX-USD', 32.40, 2.5, 13],
      ['DOT-USD', 6.20, 1.4, 9], ['MATIC-USD', 0.42, -1.5, 8], ['LINK-USD', 14.20, 2.1, 8.5],
      ['LTC-USD', 92.40, 0.5, 7], ['BCH-USD', 412, 0.4, 8.2], ['ATOM-USD', 4.80, 1.2, 1.9],
    ],
  }
  const list = TICKERS[market] || []
  return list.map(([symbol, price, change_pct, market_cap]) => ({
    symbol, price, change_pct, market_cap,
  }))
}

// ─── Price history mock (sparkline 30d) ──────────────────────────────────────

function buildPriceHistory(query) {
  const symbol = (query || '').match(/symbol=([^&]+)/)?.[1] || 'UNKNOWN'
  const period = (query || '').match(/period=([^&]+)/)?.[1] || '1m'
  const points = period === '1w' ? 7 : period === '3m' ? 90 : period === '1y' ? 52 : 30
  // Empezamos en un precio base y generamos walk con drift suave
  const base = PRICES[symbol] || PRICES[symbol.replace('-USD', '')] || 100
  const drift = (Math.random() - 0.4) * 0.002
  let v = base * (1 - drift * points)
  const out = []
  const today = new Date()
  for (let i = points - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(today.getDate() - i)
    v = v * (1 + drift + (Math.random() - 0.5) * 0.02)
    out.push({ date: d.toISOString().slice(0, 10), close: Math.round(v * 100) / 100 })
  }
  return { symbol, period, points: out }
}
