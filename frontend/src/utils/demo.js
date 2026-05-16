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

// Wrapped anual — mock para demo. Estructura debe matchear el shape de
// backend/wrapped.py: { year, slides[], summary }.
const WRAPPED = (year) => ({
  year,
  slides: [
    {
      code: 'intro', kind: 'intro',
      title: `Tu ${year} en Rendi`,
      subtitle: 'Un repaso a tus inversiones del año.',
      metric: { value: String(year), label: 'AÑO' },
      stats: [
        { label: 'Rendimiento', value: '+14.32%' },
        { label: 'P&L total',   value: '+$4,287' },
        { label: 'Operaciones', value: '14' },
        { label: 'Mejor mes',   value: 'Marzo' },
      ],
      tone: 'neutral',
    },
    {
      code: 'pnl', kind: 'pnl',
      title: '+14.32%',
      subtitle: `Tu rendimiento TWR de ${year}`,
      metric: { value: '+$4,287', label: 'P&L TOTAL' },
      stats: [
        { label: 'Capital inicio',  value: '$30,000' },
        { label: 'Capital final',   value: '$34,287' },
        { label: 'Meses operados',  value: '12' },
      ],
      tone: 'positive',
    },
    {
      code: 'best_month', kind: 'best_month',
      title: 'Marzo fue tu mejor mes',
      subtitle: '+6.21% — $31,250 → $33,191',
      metric: { value: '+6.21%', label: 'MARZO' },
      stats: [],
      tone: 'positive',
    },
    {
      code: 'worst_month', kind: 'worst_month',
      title: 'Junio fue el más duro',
      subtitle: '−3.84% — todos tenemos meses así.',
      metric: { value: '−3.84%', label: 'JUNIO' },
      stats: [],
      tone: 'negative',
    },
    {
      code: 'best_trade', kind: 'best_trade',
      title: 'NVDA fue tu mejor trade',
      subtitle: '+$680 (+22.4%)',
      metric: { value: '+$680', label: 'NVDA' },
      stats: [
        { label: 'Activo', value: 'NVDA' },
        { label: 'Fecha',  value: `${year}-03-14` },
      ],
      tone: 'positive',
    },
    {
      code: 'activity', kind: 'stats',
      title: '14 operaciones cerradas',
      subtitle: 'Tu activo más operado fue AAPL.',
      metric: { value: '14', label: 'TRADES' },
      stats: [
        { label: 'AAPL', value: '3×' },
        { label: 'NVDA', value: '2×' },
        { label: 'TSLA', value: '2×' },
        { label: 'Distintos activos', value: '9' },
      ],
      bars: [
        { label: 'AAPL', value: 3 },
        { label: 'NVDA', value: 2 },
        { label: 'TSLA', value: 2 },
      ],
      tone: 'neutral',
    },
    {
      code: 'vs_benchmark', kind: 'vs_benchmark',
      title: 'Le ganaste a los índices',
      subtitle: `Tu rendimiento estuvo por encima del promedio de benchmarks (${year}).`,
      metric: { value: '+14.32%', label: 'TU RENDIMIENTO' },
      stats: [{ label: 'vs S&P 500', value: '+4.32pp' }],
      bars: [
        { label: 'Tu cartera', value: 0.1432, highlight: true },
        { label: 'S&P 500',    value: 0.10 },
        { label: 'MERVAL',     value: 0.08 },
      ],
      tone: 'positive',
    },
    {
      code: 'vs_inflation', kind: 'vs_inflation',
      title: 'La inflación AR te ganó',
      subtitle: 'Tu rendimiento quedó 15.68pp por debajo de la inflación AR.',
      metric: { value: '−15.68pp', label: 'VS INFLACIÓN AR' },
      stats: [
        { label: 'Tu rendimiento',    value: '+14.32%' },
        { label: `Inflación ${year}`, value: '30.00%' },
      ],
      bars: [
        { label: 'Tu cartera',         value: 0.1432, highlight: true },
        { label: `Inflación AR ${year}`, value: 0.30 },
      ],
      tone: 'negative',
    },
    {
      code: 'dominant_bias', kind: 'dominant_bias',
      title: 'Vendés ganadoras más rápido que perdedoras',
      subtitle: 'En promedio aguantás tus perdedoras 1.8× más tiempo que tus ganadoras. Vale la pena revisar criterios de salida.',
      metric: { value: 'MEDIUM', label: 'SEVERIDAD' },
      stats: [
        { label: 'Tipo',      value: 'disposition_effect' },
        { label: 'Indicador', value: '0.55× (winners/losers)' },
      ],
      tone: 'neutral',
    },
    {
      code: 'outro', kind: 'outro',
      title: `Gracias por usar Rendi en ${year}`,
      subtitle: 'Compartí tu Wrapped y ayudanos a hacer crecer la comunidad de inversores Latam.',
      metric: { value: 'RENDI', label: 'COMPARTILO' },
      stats: [],
      tone: 'neutral',
    },
  ],
  summary: { has_data: true, twr: 0.1432, months_count: 12, operations_count: 14, slide_count: 10 },
})

// AI v2 — análisis pre-redactados por topic.
// Coherentes con la fixture demo (portfolio ~$8K, NVDA top, AAVE/USDT en
// rojo, mix Schwab USD + Cocos ARS + Binance USDT, sesgo dominante
// disposition_effect medio).
// Mocks coherentes con el manifiesto editorial de prompts.py: interpretativos,
// densos, lenguaje probabilístico, un insight memorable por respuesta, sin
// frases vacías ni adjetivos infantiles. Cartera demo: ~US$ 8.3K, NVDA top,
// INTC +148% como mejor trade cerrado, mix Schwab + Cocos + Binance.
const DEMO_AI_RESULTS = {
  dashboard: {
    tldr: 'El +14% del período descansa sobre dos motores asimétricos — NVDA por peso y INTC por un único trade excepcional. La diversificación nominal de la cartera es mayor que su diversificación efectiva de fuentes de rendimiento.',
    sections: [
      { title: 'Dinámica del período', tone: 'neutral', body: 'El valor total se ubica en US$ 8.3K sobre un capital aportado neto de US$ 7.1K. El delta absoluto (~US$ 1.2K) es ganancia real, no efecto flujos. La curva del período no muestra picos extremos: el resultado se construye sobre un puñado de movimientos persistentes más que sobre un evento puntual.' },
      { title: 'Factores que lo explican', tone: 'positive', body: 'NVDA con ~28% de weight y +29% de P&L acumulado actúa como motor principal por peso, mientras INTC aporta el +148% cerrado más rentable del año. La combinación es típica de portfolios que llegan a outperform sin batir al SPY: una posición core grande y un trade táctico excepcional, con el resto siguiendo de cerca al benchmark.' },
      { title: 'Lectura comparativa', tone: 'neutral', body: 'El TWR queda algunos puntos debajo del S&P 500 acumulado del período. Le gana a la inflación AR con margen, lo cual es coherente con una cartera con exposure mayoritario USD. Sobre el benchmark dominante, el cash drag y la inversión parcial en panel local explican la mayor parte del gap.' },
      { title: 'Riesgo asimétrico actual', tone: 'warning', body: 'Si NVDA corrigiera un 25%, el portfolio perdería alrededor de 7 puntos de TWR — más de la mitad del rendimiento anual. El sesgo de disposition effect (medio) agrega tensión: la tentación a cerrar ganadoras en corrección choca con la lógica del trade core. Tener pre-definido el umbral de rebalance vale más que cualquier decisión en caliente.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La diversificación que el HHI sugiere se diluye cuando uno mira las fuentes del rendimiento, no las del capital. Más del 60% del P&L viene de dos tickers — el resto de la cartera funciona casi como un buy-and-hold con beta menor. La pregunta operativa no es qué comprar, sino bajo qué condición concreta reducir la exposure dominante.' },
    ],
    follow_ups: ['¿Cuánto pierdo si NVDA cae 25%?', '¿Cómo se compara mi TWR con el SPY del período exacto?', '¿Cuál es el cash drag estimado anualizado?'],
  },
  'dashboard.composition': {
    tldr: 'El HHI sugiere concentración moderada, pero la lectura por fuente de rendimiento es más concentrada — NVDA pesa 28% del capital y explica una porción mucho mayor del P&L del período.',
    sections: [
      { title: 'Reparto del capital', tone: 'neutral', body: 'Los top 5 holdings acumulan aproximadamente 65% del portfolio, con NVDA, AAPL y MSFT al frente. La distribución por moneda queda partida en mayoría USD vía Schwab más una porción material en CEDEARs (Cocos), que económicamente también es exposure US.' },
      { title: 'Concentración real vs nominal', tone: 'warning', body: 'El HHI en zona media-alta capta la dispersión por activo, pero subestima la concentración por factor. Si NVDA, AAPL y MSFT comparten sensibilidad al ciclo tecnológico y a tasas, la diversificación efectiva es menor que la nominal. En una corrección growth, los tres se mueven en la misma dirección.' },
      { title: 'Cash y reserva táctica', tone: 'neutral', body: 'El cash es bajo en el ratio principal del Dashboard pero alto si se suman los USDT/ARS de cuentas de tránsito — esa diferencia importa porque la primera lectura sugiere capital trabajando y la segunda revela parking material. Diferenciar reserva táctica de cash drag estructural cambia la lectura del riesgo.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La regla útil para esta cartera no es bajar concentración por concentración, sino fijar un umbral de rebalance pre-acordado: por ejemplo, recortar si una posición supera el 30% o si los tres tickers tech combinados pasan el 60% del valor. Eso convierte una decisión emocional en una mecánica.' },
    ],
    follow_ups: ['¿A qué umbral conviene rebalancear NVDA?', '¿Qué % de la beta del portfolio explica el sector tech?'],
  },
  'dashboard.evolution': {
    tldr: 'La curva del período es sostenida con dispersión mensual baja — sugiere demanda estructural más que un rally puntual. El peor drawdown se ubica dentro del rango histórico previo y se recuperó dentro de las 3-4 semanas habituales para esta cartera.',
    sections: [
      { title: 'Forma de la curva', tone: 'positive', body: 'La progresión es sostenida con pocos quiebres abruptos. Esa forma es típica de portfolios donde el rendimiento viene de varias posiciones aportando en paralelo, más que de un evento concentrado en un trimestre.' },
      { title: 'Drawdown vs histórico', tone: 'neutral', body: 'El peor retroceso del período se mantuvo dentro del rango habitual de esta cartera y duró 2-3 semanas hasta recuperar el peak. El drawdown actual es de magnitud menor — más cerca de "ruido normal" que de un cambio de régimen.' },
      { title: 'Dispersión mensual', tone: 'neutral', body: 'La brecha entre el mejor y peor mes ronda los 10pp — moderada para una cartera con exposure tech alto. Una dispersión más estrecha sugeriría un portfolio más defensivo; una más amplia indicaría dependencia de pocos meses excepcionales.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Curvas sostenidas como ésta son más replicables que las que dependen de uno o dos meses extraordinarios. La métrica útil a monitorear es la varianza mensual, no solo el TWR acumulado — si esa varianza crece sin que cambie la composición, suele anticipar un cambio en el comportamiento del mercado más que del portfolio.' },
    ],
    follow_ups: ['¿Cuánto duraron los drawdowns anteriores hasta recuperar?', '¿La dispersión mensual de este año vs el anterior?'],
  },
  'dashboard.top_holdings': {
    tldr: 'Las dos posiciones que dominan el resultado lo hacen por razones distintas — NVDA por peso (28% × +29%) e INTC por un cierre excepcional (+148%). Sin esos dos vehículos, la cartera se acerca al comportamiento de un buy-and-hold pasivo.',
    sections: [
      { title: 'Ganadoras por peso', tone: 'positive', body: 'NVDA combina weight alto y P&L positivo — esa combinación es la que más mueve el resultado anual. AAPL aporta segundo con +18% pero con weight menor, por lo que su impacto en el TWR es proporcionalmente más chico.' },
      { title: 'Ganadora por trade', tone: 'positive', body: 'INTC cerró +148% — un outlier que infla el P&L realizado del año. Si se excluyera ese trade, la expectancy promedio del sistema cae a un nivel mucho más cercano al break-even.' },
      { title: 'Perdedoras con holding largo', tone: 'warning', body: 'AAVE/USDT (-12%) y NFLX flat acumulan varios meses en la cartera sin que aparezca una tesis explícita de reversión. El patrón de mantener perdedoras chicas con horizonte indefinido es una de las firmas más caras a largo plazo, según los detectores de Comportamiento.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La pregunta útil para revisar este top 8 no es "¿vendo NVDA?" sino "¿qué define que una perdedora siga siendo válida o deba salir?". Las ganadoras grandes se gestionan con criterio de rebalance; las perdedoras chicas, con criterio de salida pre-establecido. Hoy ambos están implícitos — explicitarlos cambia el frame de la decisión.' },
    ],
    follow_ups: ['¿Cuánto tiempo es razonable mantener AAVE/USDT sin revisar la tesis?', '¿La expectancy del sistema sin INTC es positiva?'],
  },
  'dashboard.brokers': {
    tldr: 'La cartera vive en tres custodios con función distinta — Schwab para US directo, Cocos para CEDEARs y panel AR, Binance para crypto. La asignación parece equilibrada pero esconde una concentración funcional: el alpha del año vive casi entero en uno solo.',
    sections: [
      { title: 'Distribución y función', tone: 'neutral', body: 'Schwab concentra el grueso del valor con acciones US directas, Cocos un tercio entre CEDEARs y panel local, Binance el resto en crypto/USDT. Cada broker cubre una función económica distinta, lo cual reduce solapamiento y simplifica la operación.' },
      { title: 'Performance diferencial', tone: 'positive', body: 'Schwab lidera en P&L absoluto del año, impulsado por NVDA, AAPL e INTC. Cocos aporta sin grandes picos. Binance contribuye principalmente vía BTC, con AAVE/USDT como contrapeso negativo. El alpha del período vive mayoritariamente en Schwab — los otros dos brokers se mueven cerca de un comportamiento pasivo.' },
      { title: 'Riesgo operacional', tone: 'neutral', body: 'Tres custodios reducen el riesgo de plataforma frente a tener todo en una sola cuenta — la continuidad del portfolio no depende de un solo proveedor. Sumar un cuarto broker agregaría complejidad operativa sin reducir materialmente el riesgo por debajo del nivel actual.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Tener brokers segmentados por función ayuda a la operación pero también facilita un sesgo común: medir cada cuenta por separado y perder de vista la consolidación. Una mejora mecánica simple es revisar el TWR conjunto con la misma frecuencia que cada cuenta individual — el portfolio que importa para la decisión es el agregado, no el broker.' },
    ],
    follow_ups: ['¿Qué porción del alpha viene de Schwab vs los demás?', '¿Hay solapamiento entre los CEDEARs de Cocos y las acciones US directas?'],
  },
  'dashboard.upcoming_events': {
    tldr: 'La ventana próxima concentra eventos sobre las posiciones de mayor peso — el riesgo idiosincrático del portfolio para los siguientes días depende de un puñado de reportes, no del mercado.',
    sections: [
      { title: 'Eventos en la ventana', tone: 'neutral', body: 'Earnings de NVDA y AAPL coinciden en la misma semana; dividendos de KO programados también en el período. Tres eventos materiales en 14 días.' },
      { title: 'Concentración de exposure', tone: 'warning', body: 'El earnings de NVDA solo toca una posición que pesa cerca del 28% del portfolio. Sumado al earnings de AAPL, la exposure combinada del weight con reporte ronda el 40% de la cartera. Un movimiento típico post-earnings de ±8% en NVDA puede mover el TWR del portfolio 2-3 puntos en una sola sesión.' },
      { title: 'Comportamiento típico', tone: 'neutral', body: 'La reacción del precio a un beat o miss de earnings tiene baja correlación con la calidad real del reporte — la sorpresa relativa al consenso pesa más que los números absolutos. No es un evento sobre el cual el inversor individual tenga edge informacional.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La utilidad operativa del calendario de earnings no es decidir qué hacer ese día — es decidir, antes del evento, hasta qué movimiento adverso se está dispuesto a tolerar sin tocar la posición. Definir ese umbral ex-ante evita reacciones post-fact que la literatura muestra como sub-óptimas en promedio.' },
    ],
    follow_ups: ['¿Cuál es el movimiento promedio post-earnings de NVDA?', '¿Qué % del portfolio queda expuesta esa semana?'],
  },
  behavioral: {
    tldr: 'El perfil combina disciplina sistémica (turnover bajo, sin averaging-down) con un sesgo dominante de gestión asimétrica de ganadoras vs perdedoras. Esa combinación protege contra los errores caros pero deja sobre la mesa el upside de cortar perdedoras antes.',
    sections: [
      { title: 'Patrón dominante', tone: 'warning', body: 'Las perdedoras acumulan holding period casi al doble de las ganadoras. El gesto repetido de cerrar verdes rápido (INTC, KO) y mantener rojos esperando recuperación (AAVE/USDT, NFLX) es la firma del disposition effect. En portfolios diversificados ese costo no se ve en una métrica única — aparece como un drag silencioso en la expectancy a largo plazo.' },
      { title: 'Disciplina que se está manteniendo', tone: 'positive', body: 'Turnover anual de 1x ubica al portfolio en territorio de inversor a mediano plazo — fuera de la zona donde fricciones de costo erosionan resultado. Ausencia de averaging-down agresivo sobre activos en caída sugiere que no se rompe la regla de "no doblar la apuesta sin nueva tesis". Esa disciplina es difícil de mantener y vale más que cualquier trade individual del año.' },
      { title: 'Lectura combinada de sesgos', tone: 'neutral', body: 'Concentración media-alta + home_bias moderado + disposition effect arman una asimetría específica: la cartera funciona bien cuando NVDA y el sector tech acompañan, pero el sesgo de gestión amplifica drawdowns porque la tentación de cerrar es mayor en las posiciones grandes. La concentración no es problema aislado — es problema porque interactúa con el sesgo dominante.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El cambio de proceso de mayor leverage no es psicológico sino procedural: definir el criterio de salida ANTES de la entrada, no después. Esa regla aparentemente trivial es la que desarma el disposition effect — saca la decisión del momento de tensión y la convierte en una verificación contra un umbral pre-acordado. No es operativa, es estructural.' },
    ],
    follow_ups: ['¿Cuánto cuesta el disposition effect anualizado en esta cartera?', '¿Qué interacción tiene la concentración con el sesgo dominante?', '¿Cómo se ve un criterio de salida bien definido en la práctica?'],
  },
  insights: {
    tldr: 'El +14% TWR del año descansa sobre dos motores asimétricos (NVDA por peso, INTC por trade único). Le gana a la inflación AR con margen pero queda algunos puntos debajo del SPY — combinación coherente con un portfolio con cash drag y exposure parcial al panel local.',
    sections: [
      { title: 'Performance neta', tone: 'positive', body: 'TWR compoundeado de ~14% sobre los últimos 12 meses con un win rate del 56% en trades cerrados. El payoff 7x sugiere asimetría favorable: pocas ganadoras grandes pagan varias perdedoras chicas. El drawdown máximo del período (~-8%) está dentro del rango habitual para portfolios con exposure tech alto.' },
      { title: 'Origen del resultado', tone: 'neutral', body: 'Del P&L total combinado (realized + unrealized), NVDA aporta más del 55% solo. INTC suma vía el trade cerrado más rentable del año (+148%). Sin esos dos, el rendimiento se acerca al comportamiento de un buy-and-hold del SPY menos el cash drag. Detractores (AAVE/USDT, NFLX) son chicos en magnitud frente a las ganadoras.' },
      { title: 'Lectura comparativa', tone: 'neutral', body: 'vs SPY queda un par de puntos debajo — gap consistente con la combinación de cash material y exposure AR sin alpha relativo del año. vs inflación AR, el margen es claro: el portfolio defendió y aumentó poder de compra en moneda local. vs dólar blue, depende del mix de monedas — para la parte USD del portfolio el blue es referencia tangencial.' },
      { title: 'Riesgo y exposure', tone: 'warning', body: 'La exposición se reparte ~47% US (Schwab + CEDEARs), ~8% panel AR, ~45% en cash distribuido entre USDT y ARS. El cash de esa magnitud, si no es reserva táctica activa, representa un costo de oportunidad anualizado material. La concentración en NVDA (28% weight) amplifica drawdowns en correcciones del Nasdaq.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El portfolio supera a la inflación pero queda detrás del SPY — ese resultado es característico de carteras donde el alpha de stock-picking se ve neutralizado por el cash drag. La decisión estratégica relevante no es qué activo agregar sino bajo qué condición el cash actual se convierte en posición — fijar un umbral o calendario de despliegue elimina la fricción mensual de "todavía no".' },
    ],
    follow_ups: ['¿Cuánto cuesta el cash drag anualizado en esta cartera?', '¿Cuál sería el TWR sin la posición NVDA?', '¿El payoff 7x es replicable o un outlier histórico?'],
  },
  'insights.evolution': {
    tldr: 'La trayectoria mensual muestra dispersión moderada con consistencia del 50-65% — el TWR positivo del período viene de varios meses aportando en paralelo, no de uno o dos extraordinarios. La replicabilidad de este resultado es mayor que la de portfolios con curva más volátil.',
    sections: [
      { title: 'Forma de la curva', tone: 'positive', body: 'Progresión sostenida con pocos quiebres. La cantidad de meses positivos sobre el total sugiere disciplina más que suerte: cuando un portfolio gana en más del 60% de los meses, el TWR acumulado tiende a sostenerse incluso si los meses extraordinarios desaparecen.' },
      { title: 'Dispersión interna', tone: 'neutral', body: 'El gap entre el mejor mes (~+6%) y el peor (~-4%) ronda los 10pp — moderado para una cartera con exposure tech material. Una dispersión más estrecha indicaría un portfolio defensivo; una más amplia, dependencia de pocos meses outlier.' },
      { title: 'Lectura comparativa', tone: 'neutral', body: 'El mejor mes coincide con períodos de fuerza relativa del Nasdaq según el contexto del packet. El peor mes está dentro del rango histórico del propio portfolio — no representa un cambio de régimen sino ruido normal. La asimetría entre ambos no sugiere ni euforia ni capitulación.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Lo que sostiene este tipo de curva no es la estrategia del último mes sino la combinación de turnover bajo y disciplina de no mover el portfolio en cada corrección. La métrica que importa monitorear es la varianza mensual, no solo el TWR acumulado: si la varianza crece sin que cambie la composición, suele anticipar un cambio en el comportamiento del mercado más que del portfolio.' },
    ],
    follow_ups: ['¿La dispersión mensual sigue una tendencia creciente?', '¿Qué meses del año concentran la mayor parte del TWR?'],
  },
  'insights.drawdown': {
    tldr: 'El peor drawdown del período se mantiene dentro del rango histórico habitual de la cartera. El actual es de magnitud menor — más cerca del ruido normal que de un cambio de régimen.',
    sections: [
      { title: 'Profundidad histórica', tone: 'positive', body: 'El max drawdown del período se ubica alrededor del -8%, dentro de lo esperable para un portfolio con ~47% de exposure US tech. El S&P 500 mismo tuvo correcciones de magnitud similar en ventanas comparables — el portfolio no exhibió volatilidad excepcional respecto del benchmark relevante.' },
      { title: 'Eventos de DD', tone: 'neutral', body: 'Los dos eventos de drawdown más profundos del período duraron 2-3 semanas hasta recuperar el peak previo. Ninguno se extendió más allá de un mes, lo que sugiere que los gatillos fueron movimientos de mercado de corta duración, no deterioros estructurales del portfolio.' },
      { title: 'Estado actual', tone: 'positive', body: 'El drawdown actual está cerca de cero — el portfolio se mueve en la franja de los máximos históricos. La distancia al peak es pequeña, lo cual no implica que no pueda profundizar; solo describe que hoy no hay daño material acumulado desde el último high.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El patrón "drawdown chico y recuperación rápida" del período no es atributo permanente del portfolio — depende de que la exposure y el comportamiento de los activos sostengan ese ritmo. Una mejora útil al proceso es registrar el time-to-recover de cada DD: cuando ese tiempo se alarga, suele ser una señal anticipada de cambio en el régimen del portfolio, anterior al cambio en el TWR.' },
    ],
    follow_ups: ['¿Cuánto fue el time-to-recover del peor drawdown histórico?', '¿Hay correlación entre la profundidad del DD y el sector más afectado?'],
  },
  'insights.attribution': {
    tldr: 'Más del 50% del P&L total proviene de una sola posición — la diversificación nominal del portfolio se diluye cuando se mira la fuente real del rendimiento. La concentración de fuente es el factor más asimétrico del año.',
    sections: [
      { title: 'Atribución por posición', tone: 'positive', body: 'NVDA explica más de la mitad del P&L combinado (realized + unrealized). INTC aporta el segundo bloque vía un trade cerrado al +148%. BTC en tercer lugar con magnitud menor. El resto de las posiciones contribuye marginalmente respecto de las top 3.' },
      { title: 'Realized vs unrealized', tone: 'neutral', body: 'El P&L está repartido entre realized (cosecha asegurada) y unrealized (apuesta abierta) en proporciones que merecen atención: la parte unrealized depende íntegramente del comportamiento futuro de las posiciones grandes, mientras la parte realized ya está consolidada. Tratar ambas como equivalentes para tomar decisiones distorsiona el riesgo real.' },
      { title: 'Detractores', tone: 'neutral', body: 'AAVE/USDT y NFLX son los principales lastres del año pero su magnitud no neutraliza materialmente a las ganadoras. La pregunta práctica no es si compensan o no, sino qué patrón de proceso permite que se mantengan tanto tiempo sin reconciliación con la tesis original.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Una posición que aporta más de la mitad del rendimiento anual exige un umbral de rebalance explícito — no para reducirla por reflexivo, sino para evitar que la decisión llegue en el momento de tensión (caída del activo o cambio macro). Pre-definir "qué condición concreta dispara revisar la posición" convierte una decisión emocional en una mecánica medible.' },
    ],
    follow_ups: ['¿Cuánto bajaría el TWR sin la posición top 1?', '¿Qué umbral de weight conviene para gatillar revisión?'],
  },
  monthly: {
    tldr: 'El mes cerró con dos motores asimétricos: un trade táctico de tamaño grande explica buena parte del P&L mientras el resto de la cartera siguió cerca del benchmark mensual.',
    sections: [
      { title: 'Resultado del mes', tone: 'positive', body: 'El TWRR del mes fue positivo con varios trades cerrados arriba de promedio. El delta absoluto sobre el capital inicial confirma que el resultado vino de movimientos de mercado, no de flujos.' },
      { title: 'Factores probables', tone: 'neutral', body: 'El mejor trade del mes concentra una porción importante del P&L — sin esa contribución, el portfolio se hubiera movido cerca del benchmark mensual. El resto de las posiciones aportaron de forma pareja.' },
      { title: 'Lectura comparativa', tone: 'neutral', body: 'El delta vs S&P 500 del mes está dentro del rango típico. La cartera mostró menos dispersión que el promedio del año, lo cual es coherente con un mes sin shocks idiosincráticos materiales.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Un mes con resultado positivo concentrado en un solo trade es un patrón a registrar — la pregunta de proceso es si esa contribución refleja una decisión replicable o un timing puntual. Documentar el caso permite reconocer condiciones similares cuando vuelvan.' },
    ],
    follow_ups: ['¿Qué mes histórico se parece más a éste?', '¿Sin el top trade, cuánto hubiera rendido?'],
  },
  'monthly.insight': {
    tldr: 'El insight detectado captura una concentración material del resultado del mes en pocas posiciones — un patrón que distingue meses replicables de meses con dependencia de un trade puntual.',
    sections: [
      { title: 'Dinámica observada', tone: 'neutral', body: 'La señal del chip indica que un activo único explica una porción mayoritaria del P&L del mes. Es una observación descriptiva: no implica habilidad ni suerte por sí sola.' },
      { title: 'Lectura interpretativa', tone: 'warning', body: 'Cuando un mes positivo descansa sobre un solo nombre, la replicabilidad del resultado depende de seguir encontrando situaciones similares. La métrica útil a registrar es si esto se repite a lo largo de varios meses o aparece esporádicamente.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El cambio de proceso de mayor leverage no es rebalancear ahora — es definir un umbral pre-acordado de revisión por concentración del P&L mensual. Eso convierte una observación recurrente en un disparador objetivo, no en una decisión que se toma "cuando se siente".' },
    ],
    follow_ups: ['¿Este patrón se repite en otros meses?', '¿Cuál sería un umbral razonable para gatillar revisión?'],
  },
  position: {
    tldr: 'La posición concentra una porción significativa del portfolio total con un P&L positivo, pero su peso actual también define una asimetría de riesgo concreta — un movimiento adverso del activo impacta el TWR del agregado más de lo que sugiere su contribución promedio histórica.',
    sections: [
      { title: 'Dinámica de la posición', tone: 'positive', body: 'El P&L actual es positivo en términos absolutos y relativos. El holding period sugiere que la posición es de mediano plazo, no especulativa — la valuación actual incorpora múltiples meses de movimiento.' },
      { title: 'Peso vs portfolio', tone: 'warning', body: 'La posición pesa por encima del 10% del valor total. Esa magnitud convierte un movimiento del 25% en el activo en un movimiento de 2.5pp del TWR del portfolio — material respecto del drawdown histórico habitual.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Lo útil acá no es cerrar la posición sino pre-definir el umbral en que su peso justifica un rebalance. Cuando la decisión se toma con regla objetiva (ej. recortar si supera X% del portfolio) en lugar de en respuesta a un evento adverso, los rendimientos esperados a largo plazo mejoran.' },
    ],
    follow_ups: ['¿Qué umbral de weight conviene para rebalance?', '¿Cuánto pierde el portfolio si cae 25%?'],
  },
  'position.chart': {
    tldr: 'El movimiento reciente del precio sugiere que la posición ya capturó la parte más rápida del recorrido — desde el peak el activo se mueve dentro de un rango más estrecho con dispersión menor que la histórica reciente.',
    sections: [
      { title: 'Trayectoria reciente', tone: 'neutral', body: 'El precio actual se ubica cerca del avg de compra. La serie de 30 días no muestra movimientos extremos en ningún lado — sugiere que la tesis original ya se materializó en parte, ahora la posición vive de optimismo residual o nueva información que aún no aparece en el chart.' },
      { title: 'Volatilidad y drawdown reciente', tone: 'neutral', body: 'El drawdown reciente respecto del peak del período mostrado está controlado. Para un activo con la beta histórica de esta posición, el rango actual es estrecho — período de consolidación más que de tendencia.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El chart no respalda ni invalida la tesis — solo describe que el movimiento esperado ya ocurrió y la información ahora viene por fuera del precio. Para decisiones futuras vale revisar fundamentales (próximos earnings, cambio de momentum sectorial) más que el chart mismo.' },
    ],
    follow_ups: ['¿La volatilidad reciente está dentro del rango histórico?', '¿Qué tan lejos está del próximo peak?'],
  },
  'position.lots': {
    tldr: 'El historial muestra varias compras a precios crecientes — un patrón de averaging up que es coherente con momentum-following. El avg refleja entradas progresivas, no una compra única dominante.',
    sections: [
      { title: 'Patrón de compras', tone: 'neutral', body: 'La secuencia de operaciones registra varias entradas en momentos distintos, con precios crecientes en mayor proporción. Eso es consistente con un patrón de seguir momentum, no con apostar a reversiones.' },
      { title: 'Estructura del avg', tone: 'neutral', body: 'El precio promedio actual está más cerca de las últimas compras que de la primera — el peso del avg lo definen las entradas tardías. Eso implica que el cushion de tolerancia ante una corrección es menor que el que sugiere el P&L absoluto.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Averaging up funciona en mercados con tendencia clara y se vuelve costoso en mercados laterales o de reversión. La regla útil para este patrón es pre-definir el criterio para dejar de promediar al alza: si el activo cruza X múltiplo del avg, dejar de agregar y considerar el rebalance.' },
    ],
    follow_ups: ['¿Cuál fue el lote más rentable hasta ahora?', '¿Qué pasa con el avg si agrego un lote más al precio actual?'],
  },
  reports: {
    tldr: 'El año cierra con TWR positivo pero la mayor parte del rendimiento se concentra en uno o dos meses excepcionales — la consistency mensual es media, lo cual hace al resultado menos replicable que un año con curva pareja.',
    sections: [
      { title: 'TWR del año', tone: 'positive', body: 'El portfolio acumula un rendimiento positivo sobre los meses activos del año. Eso describe el resultado bruto, pero no dice cuán pareja fue la curva — la métrica clave para evaluar replicabilidad no es el TWR final sino la dispersión mensual.' },
      { title: 'Win rate mensual', tone: 'neutral', body: 'El % de meses positivos se ubica cerca del 50%. Eso significa que tantos meses negativos como positivos contribuyeron al resultado — el TWR positivo se sostiene porque los meses ganadores fueron de mayor magnitud que los perdedores. Esa asimetría es la firma típica de portfolios con concentración alta en pocos activos volátiles.' },
      { title: 'Mejor vs peor mes', tone: 'neutral', body: 'La brecha entre mejor y peor mes es amplia. Una dispersión así sugiere que el portfolio responde con fuerza al ciclo del activo dominante. Para perfiles que buscan menos volatilidad, suavizar esa brecha requiere bajar concentración o agregar exposure no correlacionada.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La métrica útil a monitorear no es el TWR acumulado del año sino la consistencia de la curva. Un año con TWR del 14% concentrado en dos meses tiene replicabilidad menor que uno con TWR del 10% distribuido en seis meses positivos. Para evaluar el sistema, ignoré el resultado y mirá la varianza mensual.' },
    ],
    follow_ups: ['¿Qué mes contribuyó más al TWR del año?', '¿Cómo se ve la dispersión vs el año anterior?'],
  },
  home: {
    tldr: 'El día abre con mercado mixto y el portfolio se mueve cerca de cero — buena ventana para revisar tesis sin presión de evento. La semana próxima concentra varios reportes sobre posiciones grandes.',
    sections: [
      { title: 'Estado del día', tone: 'neutral', body: 'Los índices abren mixtos: algunos verdes, otros rojos. La sesión no muestra un tema dominante y el portfolio se mueve dentro del rango habitual de un día sin shocks materiales.' },
      { title: 'Vinculación con la cartera', tone: 'neutral', body: 'El portfolio acompaña el rango del mercado del día. Cuando el delta del portfolio se desvía mucho del delta del mercado, esa divergencia suele venir de sectores específicos — hoy no es ese caso.' },
      { title: 'Riesgo de la semana', tone: 'warning', body: 'En los próximos 14 días aparecen earnings sobre posiciones que combinadas representan ~40% del valor del portfolio. La semana del reporte puede mover el TWR diario más de lo usual.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Días sin volatilidad son los más útiles para revisar criterio sin reaccionar al precio. Hoy es ese tipo de día — vale verificar si los umbrales de rebalance están bien calibrados antes de que llegue una sesión con noticias.' },
    ],
    follow_ups: ['¿Qué tan correlacionado está mi portfolio con el SPY?', '¿Cuál es el peso combinado con earnings esta semana?'],
  },
  news: {
    tldr: 'El feed de noticias del período concentra la mayor parte de su volumen en pocos tickers — un patrón que refleja que los temas del momento tocan posiciones específicas de la cartera, no el portfolio entero.',
    sections: [
      { title: 'Distribución de cobertura', tone: 'neutral', body: 'En el período cubierto, una parte significativa de las noticias menciona los mismos 2-3 tickers. Eso significa que las posiciones grandes están en el radar del mercado — el ruido informativo es proporcional al peso, no al diversificado nominal.' },
      { title: 'Temas dominantes', tone: 'neutral', body: 'Los tags más frecuentes apuntan a earnings + movimientos sectoriales. Es un período donde el calendario de reportes domina sobre las noticias macro — eso es normal en semanas de reporting season.' },
      { title: 'Tickers silent', tone: 'neutral', body: 'Varias posiciones del portfolio NO aparecen en las noticias del período. Esa ausencia no es positiva ni negativa por sí sola, pero vale registrar si esas posiciones siguen siendo decisión activa o se volvieron defaults.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Cuando el ruido informativo se concentra en pocas posiciones, las decisiones suelen sesgarse hacia esos tickers — el feed crea agenda. Mantener un registro de "qué decidiste sin noticias" es una métrica simple pero útil para chequear si la toma de decisión responde a la tesis o al volumen de cobertura del día.' },
    ],
    follow_ups: ['¿Qué ticker concentra más cobertura este período?', '¿Cuáles son los tags dominantes?'],
  },
  'news.item': {
    tldr: 'La noticia toca una posición material del portfolio — vale leerla con criterio. Lo importante no es la noticia en sí, sino qué (si es que algo) cambia en la tesis original de la posición.',
    sections: [
      { title: 'Relevancia para tu cartera', tone: 'warning', body: 'El ticker de la noticia está entre las posiciones grandes del portfolio. Una noticia que mueve la valuación del activo se transmite al TWR del portfolio en proporción al peso — vale prestarle atención.' },
      { title: 'Contexto del activo', tone: 'neutral', body: 'La posición viene con P&L positivo acumulado y un holding de varios meses. La noticia llega sobre un activo que ya cargó parte de la tesis — la reacción del precio post-noticia suele ser menor en activos que ya recorrieron camino.' },
      { title: 'Cobertura sostenida', tone: 'neutral', body: 'El ticker registra varias noticias en los últimos 30 días. Esa continuidad indica que el mercado está re-evaluando el activo — la noticia individual es menos importante que la tendencia agregada de cobertura.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Una noticia rara vez justifica cambiar la posición — lo que sí justifica el cambio es si la noticia modifica la TESIS original. La pregunta práctica es "¿lo que dice esto hace que mi razón para tener la posición ya no aplique?". Si la respuesta es no, la noticia es ruido — útil de leer, no de actuar.' },
    ],
    follow_ups: ['¿Cuántas otras noticias hay del mismo ticker?', '¿Qué % del portfolio depende de esta posición?'],
  },
  events: {
    tldr: 'El calendario concentra la mayoría de los eventos sobre un puñado de posiciones grandes — una semana en particular concentra varios reportes que pueden mover el TWR del portfolio más que el rango diario habitual.',
    sections: [
      { title: 'Composición del calendario', tone: 'neutral', body: 'En la ventana cubierta aparecen earnings, dividendos y algunos eventos macro. El mix es típico de una temporada de reportes: el peso recae en earnings, que es lo que más volatilidad introduce en la cartera.' },
      { title: 'Concentración temporal', tone: 'warning', body: 'Hay una semana con varios eventos simultáneos sobre posiciones que combinadas representan una porción material del portfolio. En esos días, el portfolio puede comportarse de forma menos predecible que el promedio.' },
      { title: 'Cash flow vs market movement', tone: 'neutral', body: 'Los dividendos del calendario generan flujos conocidos. Diferenciar ese cash flow del movimiento de mercado ayuda a leer el TWR con criterio — el portfolio puede subir un día solo por dividendos pagados, sin que el activo haya apreciado.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La utilidad del calendario no es decidir qué hacer en cada evento sino fijar el plan ANTES de que llegue. Pre-definir el umbral de tolerancia a movimientos post-earnings ("si X cae más de Y% sin razón fundamental") evita decisiones tomadas en caliente — los datos académicos muestran que decisiones tomadas en frío rinden mejor que las post-evento.' },
    ],
    follow_ups: ['¿Qué semana concentra más eventos?', '¿Qué porcentaje del portfolio está expuesto a earnings esta temporada?'],
  },
  'events.item': {
    tldr: 'El evento toca una posición de peso material — el día del reporte el portfolio puede moverse más que el promedio diario habitual. Es contexto a tener presente, no señal de acción.',
    sections: [
      { title: 'Magnitud del impacto', tone: 'warning', body: 'El ticker representa una proporción significativa del portfolio. Un movimiento típico post-earnings del orden del ±8% en ese activo se traduce en 2-3 puntos de TWR del portfolio en una sola sesión.' },
      { title: 'Comportamiento típico', tone: 'neutral', body: 'La reacción del precio a un earnings beat/miss tiene baja correlación con la calidad del reporte — la sorpresa relativa al consenso pesa más que los números absolutos. El inversor individual no tiene edge informacional acá.' },
      { title: 'Posición previa al evento', tone: 'neutral', body: 'La posición viene con P&L positivo. Llega al evento con cushion. Eso no garantiza nada del movimiento del precio el día del reporte, pero baja la presión emocional respecto de llegar al evento con la posición en rojo.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La regla útil para earnings de posiciones grandes no es cerrar antes o esperar — es pre-definir el escenario adverso. Por ejemplo: "si el activo cae más de 15% post-earnings sin que cambien los fundamentales explicados en el reporte, mantengo o promedio". Eso convierte una decisión de reacción en una verificación contra criterio.' },
    ],
    follow_ups: ['¿Cuál fue el movimiento promedio de earnings previos de este ticker?', '¿Cuánto cae el portfolio si el activo retrocede 15%?'],
  },
  goal: {
    tldr: 'El objetivo es alcanzable si se sostiene la disciplina de aportes y la tasa de retorno esperada se ubica cerca del CAGR histórico del propio portfolio. Depender solo del rendimiento sin aportes adicionales aleja el horizonte estimado en varios meses.',
    sections: [
      { title: 'Estado del progreso', tone: 'positive', body: 'El capital actual cubre una porción razonable del target. El gap restante es alcanzable con el aporte mensual planeado al retorno esperado configurado — el camino es factible, no garantizado.' },
      { title: 'Sensibilidad a variables', tone: 'neutral', body: 'Si el retorno esperado cae al CAGR histórico real del portfolio (más conservador que el target), el ETA se extiende algunos meses. Si los aportes se suspenden, depende íntegramente del rendimiento y el horizonte se aleja sustancialmente. Los aportes constantes son la variable de mayor leverage.' },
      { title: 'Comparación con escenarios', tone: 'neutral', body: 'El escenario "conservador" (rendimiento del SPY histórico) llega al objetivo más tarde que el plan original. La brecha temporal es el costo implícito de asumir un retorno esperado superior al histórico. Esa brecha vale tenerla presente como margen de error razonable.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La métrica útil a monitorear no es el progreso mes a mes (es ruidoso) sino la trayectoria de 6 meses corrida. Si la curva real se desvía consistentemente del escenario base, el ajuste relevante suele ser revisar el aporte, no el target — el plan más robusto suele ser el que asume un retorno menor y un aporte mayor.' },
    ],
    follow_ups: ['¿Qué pasa si suspendo aportes 6 meses?', '¿Cuál es el CAGR histórico real del portfolio?'],
  },
  'insights.benchmarks': {
    tldr: 'Le ganaste a la inflación AR con margen pero quedaste algunos puntos debajo del SPY — esa combinación es característica de portfolios con cash material y exposure mixto, no de un alpha negativo del stock-picking.',
    sections: [
      { title: 'vs Inflación AR', tone: 'positive', body: 'El TWR (~14% en USD equivalent) supera la inflación AR acumulada del período. En una economía con inflación de dos dígitos, defender y aumentar poder de compra real es el primer objetivo material — esa batalla la cartera la gana con margen.' },
      { title: 'vs S&P 500', tone: 'neutral', body: 'Queda un par de puntos por debajo del SPY. El gap es consistente con dos factores estructurales del portfolio: cash del orden del 45% que no participó del rally, y exposure AR sin alpha relativo del año. No sugiere un déficit del stock-picking — sugiere un déficit de despliegue de capital.' },
      { title: 'vs Dólar Blue', tone: 'neutral', body: 'Para la parte ARS de la cartera, ganarle al blue significa defender poder adquisitivo en pesos. Para la parte USD, el blue es referencia tangencial — esa porción ya está protegida de devaluación gradual. La métrica solo es material para evaluar el costo de quedarse en pesos vs dolarizar.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La métrica útil acá no es "¿cómo le gano al SPY?" sino "¿qué porción del cash debería estar invertida si quiero achicar el gap?". El gap vs SPY es esencialmente cash drag — desplegarlo de forma escalonada y pre-pactada (no en función del precio diario) suele cerrar la diferencia sin agregar riesgo material.' },
    ],
    follow_ups: ['¿Qué TWR tendría la cartera con 0% de cash drag?', '¿Hay períodos donde el portfolio sí superó al SPY?'],
  },
}

// Mocks por código de sesgo individual (topic 'behavioral.card'). Coherentes
// con el manifiesto editorial — interpretativos, no descriptivos, con un
// insight memorable por respuesta y lenguaje probabilístico.
const DEMO_BEHAVIORAL_CARDS = {
  disposition_effect: {
    tldr: 'El holding period invertido (perdedoras al doble del tiempo que ganadoras) es la firma estructural del disposition effect — un patrón que no aparece en el P&L mensual pero erosiona la expectancy a largo plazo.',
    sections: [
      { title: 'Qué muestra el dato', tone: 'warning', body: 'El ratio winners/losers de days held se ubica alrededor de 0.55x: las ganadoras se cierran rápido, las perdedoras quedan en cartera esperando recuperación. INTC, KO y otras ganadoras del año se cerraron temprano; AAVE/USDT y NFLX llevan meses con tesis implícita de mean reversion sin gatillo definido.' },
      { title: 'Por qué importa', tone: 'neutral', body: 'La literatura de Shefrin & Statman estima que invertir el patrón (mantener ganadoras, cortar perdedoras) suma 2-4 puntos por año en expectancy, dependiendo de la cantidad de operaciones. El costo no se ve en una métrica única — aparece como un drag silencioso en el resultado anualizado.' },
      { title: 'Interacción con concentración', tone: 'neutral', body: 'El sesgo se vuelve más caro cuando hay una posición core grande: la tentación a cerrar la ganadora en corrección amplifica el efecto. NVDA con 28% de weight y el disposition effect activo arman exactamente esa tensión latente.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El cambio de leverage más alto no es psicológico — es procedural. Definir el criterio de salida ANTES de la entrada (stop por precio, por % de portfolio o por cambio en la tesis) saca la decisión del momento de tensión y la convierte en una verificación contra un umbral pre-acordado. Eso desarma el sesgo sin pelearlo en cada operación.' },
    ],
    follow_ups: ['¿Cuántos puntos por año estimás que cuesta este sesgo en mi caso?', '¿Cómo se ve en la práctica un criterio de salida pre-definido?'],
  },
  overtrade: {
    tldr: 'Turnover anual de 1x ubica al portfolio en territorio de inversor a mediano plazo — fuera de la zona donde fricciones de costo erosionan el resultado. Esa disciplina es difícil de mantener y suele subestimarse como factor de performance.',
    sections: [
      { title: 'Qué dice el dato', tone: 'positive', body: 'Rotás aproximadamente una vez al año el capital. Los detectores académicos identifican overtrading desde 3x anual hacia arriba — niveles donde la suma de comisiones, impuestos sobre realizados y bid-ask spread empieza a comerse un porcentaje material del retorno.' },
      { title: 'Por qué importa', tone: 'neutral', body: 'Cada operación tiene un costo silencioso. Barber & Odean documentaron que portfolios de inversores individuales subperformaban el mercado en proporción directa a su nivel de actividad. El portfolio menos activo tiende a estar más cerca del benchmark — y para la mayoría eso ya es resultado.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Mantener turnover bajo es contraintuitivo porque la operatoria se confunde con "estar trabajando la cartera". El research muestra lo opuesto: el portfolio se beneficia más de la decisión inicial bien tomada que de las decisiones intermedias. La regla útil acá es operar solo cuando hay tesis clara que justifica costo — no cuando "no pasa nada".' },
    ],
    follow_ups: ['¿Qué pasa con la expectancy si subiera el turnover a 3x?', '¿El bid-ask spread es material en mis brokers actuales?'],
  },
  concentration: {
    tldr: 'La concentración nominal (top1 ~18%, top3 ~46%) está en zona moderada — pero la concentración por fuente de rendimiento es mayor. La diversificación de capital no se traduce automáticamente en diversificación de riesgo.',
    sections: [
      { title: 'Lectura del HHI', tone: 'neutral', body: 'El reparto por activo no muestra una posición que domine en términos de capital. Esa lectura aislada sugiere portfolio diversificado. Pero el HHI mide concentración por nombre, no por factor — y el factor importa más cuando las posiciones grandes comparten exposure al mismo ciclo.' },
      { title: 'Concentración encubierta', tone: 'warning', body: 'Si los top 3 holdings son del mismo sector (tech US) o del mismo factor (growth), la diversificación efectiva es menor que la nominal. En una corrección del Nasdaq, los tres se mueven en la misma dirección y la cartera se comporta como si tuviera una sola posición agregada.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La regla útil no es bajar concentración por concentración — es definir un umbral pre-acordado que dispare revisión. Por ejemplo: rebalancear si un activo cruza el 25% del portfolio, o si dos del mismo sector combinados superan el 40%. Eso convierte la decisión emocional ("me siento expuesto") en una mecánica medible.' },
    ],
    follow_ups: ['¿Qué % del riesgo de mercado explica el sector tech?', '¿A qué umbral conviene gatillar rebalance?'],
  },
  inflation_loss: {
    tldr: 'Los ~US$ 272 de erosión por inflación AR son una pérdida real que no aparece en el P&L — el cash ARS no se queda quieto en términos de poder adquisitivo. Tratar esa porción como neutral en lugar de inversión inflación-pasiva subestima el costo.',
    sections: [
      { title: 'Qué pasó', tone: 'warning', body: 'Mantener cash en pesos en una economía con inflación de dos dígitos transforma el ARS en una posición default con retorno negativo conocido. La métrica del detector aproxima la pérdida acumulada del período en USD-equivalent: ~US$ 272 que no se ven en una métrica visible pero erosionan capital real.' },
      { title: 'Por qué importa específicamente', tone: 'neutral', body: 'El cash ARS funciona como reserva táctica solo si se usa en un horizonte cercano — para operaciones, gastos o deploy a corto plazo. Si lleva más de algunas semanas quieto, deja de ser reserva y se convierte en costo. Distinguir uno del otro cambia la decisión.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La mejora de mayor leverage no es elegir el mejor instrumento alternativo (Lecaps, MEP, CEDEARs) sino fijar una regla de no-permanencia: cash ARS que no se mueve en X semanas se rota automáticamente al instrumento default elegido. Eso convierte una pérdida pasiva en una decisión estructural única, no una decisión recurrente.' },
    ],
    follow_ups: ['¿Cuánto cuesta anualizado mantener cash ARS sin instrumentar?', '¿Cuál es la frontera práctica entre reserva táctica y cash drag?'],
  },
  winrate_payoff: {
    tldr: 'El win rate del 56% con payoff 7x sugiere un sistema asimétrico saludable, pero la lectura honesta es que el payoff promedio está inflado por un o dos trades excepcionales. Sin esos outliers, la expectancy cae al territorio de break-even.',
    sections: [
      { title: 'Qué dice el dato', tone: 'positive', body: 'Win rate 56% + payoff 7x = expectancy aproximada de +US$ 81 por operación. La asimetría favorable (ganadoras grandes vs perdedoras chicas) es exactamente el patrón que la literatura asocia con disciplina de stop loss y let-winners-run.' },
      { title: 'Lo que esconde el promedio', tone: 'warning', body: 'INTC +148% como trade único distorsiona el avg_win. Si se excluye, el payoff promedio cae sustancialmente y la expectancy se acerca al break-even. La métrica robusta es la mediana, no el promedio — pero el packet trae promedio, lo cual hay que tener en cuenta al interpretar.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Sistemas asimétricos como éste tienen un riesgo específico: confundir suerte sostenida con habilidad sistemática. La validación útil no es si el payoff sigue alto el próximo trade, sino si se mantiene cuando se excluye el outlier histórico. Si la respuesta es no, el "sistema" depende de seguir encontrando outliers — lo cual no es predecible.' },
    ],
    follow_ups: ['¿Cuál sería la expectancy excluyendo el trade INTC?', '¿Cómo se ve la mediana del payoff vs el promedio?'],
  },
  loss_aversion: {
    tldr: 'El patrón de ganadoras > perdedoras en magnitud es uno de los más difíciles de mantener — es el opuesto a la tendencia instintiva. Lo que está funcionando hoy no es una decisión puntual sino un proceso silencioso que vale más que cualquier trade individual del año.',
    sections: [
      { title: 'Patrón saludable', tone: 'positive', body: 'En promedio, tus ganadoras superan en magnitud a tus perdedoras — eso significa que cuando una tesis falla la cortás temprano (stops respetados) y cuando funciona la dejás correr (no toma de ganancia prematura). El comportamiento opuesto es lo que la mayoría de inversores individuales hace por default.' },
      { title: 'Por qué es frágil', tone: 'neutral', body: 'Mantener este patrón es difícil porque pelea contra dos sesgos al mismo tiempo: el deseo de "asegurar" ganancias cuando una posición sube fuerte (anchoring al precio de compra), y la tendencia a mantener perdedoras esperando recuperación. El proceso se rompe en momentos de tensión, no en operatoria normal.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Lo importante no es el patrón actual — es identificar cuál es el momento típico donde se rompe. Suele ser cuando una ganadora pasa de +30% a +80%: la tentación a cerrar para "asegurar" es máxima ahí. Pre-definir qué se hace en ese escenario (ej. rebalancear al 50% solo si supera X% del portfolio) protege el patrón sin requerir disciplina momentánea.' },
    ],
    follow_ups: ['¿En qué momentos típicamente se rompe este patrón?', '¿Cómo proteger el patrón sin pelearlo en cada decisión?'],
  },
  cash_drag: {
    tldr: 'El 45% en cash combinado (USDT + ARS) no es inversión defensiva — es capital sin desplegar. Si esa decisión no es activa (esperando un nivel concreto), el costo de oportunidad anualizado supera a cualquier alpha potencial del stock-picking del año.',
    sections: [
      { title: 'Magnitud del drag', tone: 'warning', body: 'Cash material de esa proporción contra un benchmark como el SPY representa un gap de retorno estructural — no porque el cash sea malo, sino porque no participa del rendimiento del mercado. Sobre 12 meses, esa porción "sin trabajar" puede explicar buena parte del gap vs benchmark.' },
      { title: 'Reserva táctica vs cash drag', tone: 'neutral', body: 'El cash con función específica (deploy planificado, gasto cercano, reserva por evento) tiene sentido. El cash sin función específica acumulado por inacción no — es la posición default cuando no se decide. Diferenciar ambos casos cambia totalmente la lectura del riesgo.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La mejora útil no es invertir el cash en bloque, sino pre-acordar una regla de despliegue escalonado. Por ejemplo: deploy mensual del X% durante Y meses, independiente del precio. Esa mecánica saca al inversor del dilema "todavía no" sin requerir convicción en un timing — y el research muestra que el promedio del DCA suele estar dentro del 1% del óptimo retrospectivo.' },
    ],
    follow_ups: ['¿Cuánto del gap vs SPY se explica por cash drag?', '¿Qué cantidad de cash es razonable como reserva táctica vs operativa?'],
  },
}

// Fallback genérico para códigos sin mock específico — útil para no romper
// el demo cuando se agreguen detectores nuevos.
const DEMO_BEHAVIORAL_CARD_GENERIC = (code) => ({
  tldr: `Análisis del sesgo "${code}" — el detector encontró un patrón en tu historial que vale la pena revisar.`,
  sections: [
    { title: 'Patrón detectado', tone: 'neutral', body: 'En modo demo este sesgo específico todavía no tiene una narrativa pre-redactada. La versión real con tus datos te daría una explicación detallada del patrón y por qué importa.' },
    { title: 'Cómo funciona', tone: 'neutral', body: 'Cada sesgo se calcula sobre tu historial real de operaciones, comparando con benchmarks académicos. La severidad (alta/media/baja/positiva) te orienta sobre dónde poner atención.' },
    { title: 'Probalo logueado', tone: 'positive', body: 'Si querés ver el análisis personalizado, creá una cuenta gratis y subí tu CSV o cargá algunas operaciones para que los detectores tengan datos para trabajar.' },
  ],
  follow_ups: ['¿Cómo se calculan los sesgos?', '¿Qué referencias usan los detectores?'],
})

// Builder dinámico para 'insights.observation'. Usa keywords del title/text
// para activar una de varias narrativas interpretativas. Mantiene el estilo
// research-note del manifiesto editorial: interpretación + comparación +
// insight memorable, no descripción superficial.
function buildDemoObservation(params = {}) {
  const { title = 'Observación', text = '', category = '', level = 'info' } = params
  const toneByLevel = {
    urgent: 'negative',
    danger: 'negative',
    warn: 'warning',
    warning: 'warning',
    positive: 'positive',
    info: 'neutral',
    diagnostic: 'neutral',
  }
  const baseTone = toneByLevel[(level || '').toLowerCase()] || 'neutral'
  const lower = (title + ' ' + text).toLowerCase()

  // Cada bloque devuelve {interpretation, comparison, insight} — el armado
  // final usa esas tres piezas + dinámica + tldr para construir la respuesta.
  let bloc
  if (lower.includes('concentración') || (lower.includes('represent') && lower.includes('%'))) {
    bloc = {
      interpretation: 'El peso señalado por la observación capta concentración nominal, pero la dimensión que más importa es la concentración por fuente del rendimiento. En esta cartera, una posición con weight cercano al 30% suele explicar una porción aún mayor del P&L acumulado — la diversificación de capital no se traduce automáticamente en diversificación de riesgo.',
      comparison: 'Sobre el portfolio agregado (~US$ 8.3K), un movimiento adverso del 25% en la posición señalada implica un impacto del orden de 7 puntos en el TWR del período. Comparado con el peor drawdown histórico de la cartera (~-8%), un escenario así sería el más profundo del año.',
      insight: 'La utilidad operativa de esta observación no es bajar la posición de manera reactiva, sino pre-definir un umbral de revisión: por ejemplo, recortar si el activo cruza X% del portfolio o si la combinación con otros del mismo sector excede Y%. Eso convierte una decisión emocional en una mecánica medible — el research muestra que decisiones tomadas en frío suelen ser superiores a las tomadas durante el evento.',
    }
  } else if (lower.includes('drawdown') || lower.includes('máximo histórico') || lower.includes('peak')) {
    bloc = {
      interpretation: 'La observación sobre el drawdown vale más como contexto que como alarma. La profundidad relevante no es absoluta — depende del rango histórico que tolera el propio portfolio antes de mostrar deterioro estructural. Un retroceso dentro del rango previo es ruido normal; uno que lo excede sí merece atención específica.',
      comparison: 'En esta cartera, los eventos de drawdown del período se recuperaron en aproximadamente 3 semanas en promedio. El actual está dentro de ese rango temporal. Sobre un benchmark como el SPY, correcciones de magnitud similar son frecuentes en ventanas comparables — la lectura aislada de la profundidad subestima el contexto.',
      insight: 'La métrica más útil a monitorear no es la profundidad del drawdown sino el time-to-recover. Cuando ese tiempo se alarga sin que cambie la composición de la cartera, suele anticipar un cambio en el régimen del mercado antes que aparezca en el TWR acumulado. Registrarlo por evento da una señal anticipada que el drawdown crudo no captura.',
    }
  } else if (lower.includes('cash') || lower.includes('liquidez') || lower.includes('sin invertir')) {
    bloc = {
      interpretation: 'Cash material acumulado por inacción funciona como una apuesta implícita: "el mercado va a estar más barato pronto". Cuando esa apuesta no se materializa, el costo de oportunidad anualizado supera al alpha potencial del stock-picking del resto del portfolio. Diferenciar cash con función específica (deploy planificado) de cash drag estructural cambia totalmente la lectura.',
      comparison: 'Sobre el portfolio actual, una porción cercana al 45% en cash combinado (USDT + ARS) significa que casi la mitad del capital no participó del rally del año. Contra un benchmark como el SPY, esa porción sola explica buena parte del gap del TWR — no es un déficit del stock-picking sino del despliegue.',
      insight: 'La mejora de mayor leverage no es invertir el cash en bloque, sino pre-acordar una regla de despliegue escalonado. Deploy del X% mensual durante Y meses, independiente del precio del día, saca la decisión del territorio emocional y la convierte en mecánica. El research sobre DCA muestra que el promedio histórico queda dentro del 1% del óptimo retrospectivo — un costo muy bajo por eliminar la fricción del "todavía no".',
    }
  } else if (lower.includes('argentin') || lower.includes('bcba') || lower.includes('cedear') || lower.includes('blue') || (lower.includes('broker') && lower.includes('ar'))) {
    bloc = {
      interpretation: 'La exposure a activos AR (panel local o CEDEARs) introduce un factor adicional al rendimiento medido en USD: la evolución del dólar blue. Para CEDEARs el wrapper es local pero el subyacente es US — esa porción tiene riesgo de mercado idéntico al activo original más una capa de riesgo cambiario peso-dólar.',
      comparison: 'Sobre la cartera, la mitad-y-más del valor vive en USD directo (Schwab + USDT en Binance). La porción restante en panel local + CEDEARs vía Cocos representa exposure mixta — protegida contra devaluación gradual del peso pero no contra un salto donde el blue se mueve más rápido que el subyacente local.',
      insight: 'La pregunta operativa relevante no es si reducir la exposure AR sino bajo qué escenario macro específico se evalúa el cambio. Pre-definir el disparador ("si el spread CCL-blue supera X%", "si la macro AR cambia de régimen") permite reaccionar a un cambio real en lugar de a la narrativa diaria — el costo de cambiar la exposure en frío suele ser menor al de cambiarla durante el evento.',
    }
  } else if (lower.includes('s&p') || lower.includes('spy') || lower.includes('benchmark') || lower.includes('por encima')) {
    bloc = {
      interpretation: 'El gap vs benchmark vale más por su origen que por su signo. Outperformar puede ser stock-picking real o beta accidental al sector dominante; underperformar puede ser cash drag, exposure descalzada o decisiones de market timing — cada una tiene implicancia de proceso distinta.',
      comparison: 'El portfolio supera al SPY en algunos meses específicos y queda detrás en otros — la consistencia del outperform es más informativa que el dato puntual del período. Sobre el SPY el gap acumulado del año está dentro del rango típico de portfolios concentrados en pocos nombres tech, con cash material y exposure AR sin alpha relativo.',
      insight: 'Comparar contra el SPY tiene sentido si el SPY es benchmark económico real del inversor — para alguien con cash drag estructural y exposure mixta, el bench técnicamente más justo es un blend (ej. 60% SPY + 40% cash + ARS). Comparar contra el blend, no contra el SPY puro, da una lectura más precisa de si el alpha del stock-picking existe o se confunde con la asignación.',
    }
  } else if (lower.includes('profit factor') || lower.includes('expectancy') || lower.includes('win rate') || lower.includes('ganás')) {
    bloc = {
      interpretation: 'El profit factor y la expectancy capturan asimetría del sistema, no su robustez. Un sistema con expectancy positiva sostenida por uno o dos trades outlier no es equivalente a uno con expectancy similar distribuida entre muchas operaciones — el primero depende de seguir encontrando outliers, el segundo no.',
      comparison: 'En la muestra actual, INTC +148% como trade único representa una porción enorme del avg_win. Si se excluye, el payoff promedio cae sustancialmente y la expectancy se acerca al territorio de break-even. La métrica robusta acá no es el promedio sino la mediana — el packet trae promedio, lo cual hay que tener en cuenta al leer.',
      insight: 'La validación útil del sistema no es si el próximo trade sigue siendo asimétrico, sino si la expectancy se sostiene cuando se excluye el outlier histórico. Si la respuesta es no, el sistema vive de seguir encontrando outliers — algo que la literatura describe como muy difícil de mantener sin un edge específico documentable.',
    }
  } else if (lower.includes('intc') || lower.includes('mejor operación') || lower.includes('cerrada fue')) {
    bloc = {
      interpretation: 'Un trade único de magnitud excepcional como INTC +148% es señal poco frecuente — antes que celebrarlo, vale aislar qué condiciones lo posibilitaron para evaluar replicabilidad. Tamaño de la posición, momento de entrada relativo al ciclo del sector, criterio de salida: esas tres dimensiones suelen explicar si fue un acierto sistemático o una coincidencia favorable.',
      comparison: 'El P&L cerrado de INTC representa más del 50% del realized del año. Sin ese trade, la expectancy promedio del sistema cae fuerte. El resto de las operaciones cerradas exhibe un payoff mucho más cercano al break-even — la asimetría del año descansa en una sola operación.',
      insight: 'La utilidad operativa de un outlier histórico no es replicarlo sino entender en qué se diferenció. Si el tamaño de la posición fue mayor de lo habitual, eso vale documentarlo como regla; si el timing coincidió con un evento sectorial específico, vale registrarlo para reconocer condiciones similares en el futuro. Sin ese ejercicio, el outlier queda como suerte no transferible.',
    }
  } else if (lower.includes('muestra de') || lower.includes('operaciones cerradas') || lower.includes('historial') || lower.includes('estadísticamente')) {
    bloc = {
      interpretation: 'Una muestra estadísticamente significativa requiere típicamente más de 30 trades cerrados para que las métricas de win rate, payoff y expectancy se estabilicen. Con menos, los valores oscilan según el último trade — son indicativos, no concluyentes.',
      comparison: 'En la muestra actual los detectores marcan el límite — las métricas tienen señal pero su robustez es menor que con un historial más profundo. La interpretación debería ponderar eso: una tendencia clara con muestra chica es señal débil; una tendencia ambigua con muestra chica directamente no es informativa.',
      insight: 'La utilidad práctica acá es no sobre-actuar sobre métricas con muestra insuficiente. Las decisiones de proceso (definir criterios de salida, umbrales de rebalance) son más valiosas que las basadas en estadísticas que aún no son estables. Cuando la muestra crezca, las métricas dirán más — hasta entonces, mejor confiar en la lógica del sistema que en los números.',
    }
  } else {
    bloc = {
      interpretation: 'La observación capta un patrón concreto en los datos pero su interpretación correcta depende del contexto completo del portfolio — peso, exposure, momento del ciclo. Tomarla aislada suele llevar a sobre-reacciones; combinarla con el resto del diagnóstico da una lectura más útil.',
      comparison: 'Sobre el conjunto de observaciones priorizadas del período, ésta se ubica dentro del subconjunto que merece registro y monitoreo, no acción inmediata. La frontera entre "vale la pena revisar el proceso" y "vale la pena cambiar la cartera" suele estar marcada por la persistencia del patrón en varios períodos, no por la aparición puntual en uno.',
      insight: 'La regla útil para observaciones de este tipo es no decidir en el momento de la lectura. Pasarla por un filtro de tiempo (esperar X días, revisarla nuevamente, ver si persiste) elimina decisiones tomadas en respuesta inmediata al diagnóstico — que suelen ser sub-óptimas comparadas con decisiones tomadas en frío sobre patrones confirmados.',
    }
  }

  const sections = [
    { title: 'Dinámica observada', tone: baseTone, body: text || 'El detector marcó esta observación porque cruza un umbral pre-definido en los datos del portfolio.' },
    { title: 'Lectura interpretativa', tone: 'neutral', body: bloc.interpretation },
    { title: 'Contexto comparativo', tone: 'neutral', body: bloc.comparison },
    { title: 'Insight clave', tone: 'neutral', body: bloc.insight },
  ]

  // TLDR interpretativo — arranca con la observación, no con "tu portfolio"
  const tldr = bloc.interpretation.split('. ')[0] + '. ' + bloc.insight.split('. ')[0] + '.'

  return {
    tldr: tldr.length > 350 ? bloc.interpretation.split('. ')[0] + '.' : tldr,
    sections,
    follow_ups: [
      '¿Cómo se compara esta observación con períodos anteriores?',
      '¿Qué umbral concreto disparaba una acción distinta?',
    ],
  }
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
    if (basePath === '/snapshots') {
      // Respetar el param ?days=N filtrando por ventana. Si no viene, devolver
      // toda la serie. Backend ordena DESC por date — replicamos.
      const daysMatch = (query || '').match(/days=(\d+)/)
      const cutoff = daysMatch ? Date.now() - parseInt(daysMatch[1], 10) * 86400000 : 0
      const filtered = cutoff
        ? SNAPSHOTS.filter(s => new Date(s.date).getTime() >= cutoff)
        : SNAPSHOTS
      return [...filtered].sort((a, b) => (a.date < b.date ? 1 : -1))
    }
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
    // Goals + CAGR (Objetivos page) — demo siempre muestra una meta de ejemplo
    // para que el user vea el diagnostic (Sprint 7) sin tener que crear una.
    if (basePath === '/goals') {
      return [{
        id: 1,
        target_usd: 25000,
        target_date: (() => {
          const d = new Date()
          d.setFullYear(d.getFullYear() + 2)
          return d.toISOString().slice(0, 10)
        })(),
        expected_return_pct: 12,
        label: 'Comprar mi primer auto',
      }]
    }
    if (basePath === '/goals/cagr') return DEMO_CAGR
    // Goal diagnostic (Sprint 7) — devuelve mock determinístico
    if (/^\/goals\/\d+\/diagnostic$/.test(basePath)) {
      return {
        status: 'behind',
        projected_value_at_target_date: 28400,
        eta_months_at_current_rate: 38,
        delta_pct_required: 6.5,
        months_left: 24,
        required_annual_pct: 18.4,
        diagnostic: 'A este ritmo llegás en ~38 meses (14 más que tu objetivo). Necesitás acelerar o aumentar aportes.',
        suggestion: {
          code: 'overtrade',
          title: 'Operás demasiado',
          action: 'Cada operación restá comisiones y spread. Reducí frecuencia y vas a ver más capital trabajando para tu meta.',
          evidence: 'Hicieron 38 operaciones cerradas en 12 meses — por encima del promedio Latam (≈18).',
        },
      }
    }
    // Behavioral insights — sesgos comportamentales (Sprint 3-4)
    if (basePath === '/behavioral/insights') return BEHAVIORAL_INSIGHTS
    // Wrapped anual — reseña del año (Sprint 6)
    if (basePath.startsWith('/wrapped/')) {
      const yearStr = basePath.slice('/wrapped/'.length).split('?')[0]
      const year = parseInt(yearStr, 10) || new Date().getFullYear()
      return WRAPPED(year)
    }
    // ── AI v2 endpoints — usage + topics ────────────────────────────────
    if (basePath === '/ai/usage') {
      // En demo simulamos un user "Pro" para que vea respuestas premium
      // sin contadores agresivos. La idea del demo es mostrar el mejor
      // caso del producto.
      const nextMonday = (() => {
        const today = new Date()
        const daysToMon = (8 - today.getDay()) % 7 || 7
        const d = new Date(today)
        d.setDate(d.getDate() + daysToMon)
        return d.toISOString().slice(0, 10)
      })()
      return {
        tier: 'pro',
        period: 'week',
        analyses_count: 3,
        analyses_limit: 200,
        analyses_remaining: 197,
        hub_queries_count: 0,
        hub_queries_limit: 200,
        hub_queries_remaining: 200,
        resets_on: nextMonday,
        week_starts_on: nextMonday,
      }
    }
    if (basePath === '/ai/topics') {
      return {
        topics: [
          'behavioral',
          'behavioral.card',
          'dashboard',
          'dashboard.brokers',
          'dashboard.composition',
          'dashboard.evolution',
          'dashboard.top_holdings',
          'dashboard.upcoming_events',
          'insights',
          'insights.attribution',
          'insights.benchmarks',
          'insights.drawdown',
          'insights.evolution',
          'insights.observation',
          'monthly',
          'monthly.insight',
          'position',
          'position.chart',
          'position.lots',
          'goal',
          'home',
          'news',
          'news.item',
          'events',
          'events.item',
          'reports',
        ],
      }
    }
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

  // ── AI v2 analyze: mocks por topic (datos consistentes con la fixture demo)
  if (method === 'POST' && basePath === '/ai/analyze') {
    const topic = (body?.screen || '').toLowerCase()
    let result
    if (topic === 'behavioral.card') {
      const code = (body?.params?.code || '').toLowerCase()
      result = DEMO_BEHAVIORAL_CARDS[code] || DEMO_BEHAVIORAL_CARD_GENERIC(code || 'unknown')
    } else if (topic === 'insights.observation') {
      // Dinámico — el LLM real recibiría la observación; acá la mockeamos
      // armando un análisis razonable según level / categoría / keywords.
      result = buildDemoObservation(body?.params || {})
    } else {
      result = DEMO_AI_RESULTS[topic] || DEMO_AI_RESULTS.dashboard
    }
    // En demo simulamos al user como Pro — respuestas premium + contador
    // generoso. Cuando exista el real signup, el usuario nuevo entra como
    // Free y ve los mocks descriptivos correspondientes.
    const nextMonday = (() => {
      const today = new Date()
      const daysToMon = (8 - today.getDay()) % 7 || 7
      const d = new Date(today)
      d.setDate(d.getDate() + daysToMon)
      return d.toISOString().slice(0, 10)
    })()
    return {
      result,
      cached: false,
      tier: 'pro',
      usage: {
        tier: 'pro',
        period: 'week',
        analyses_count: 3,
        analyses_limit: 200,
        analyses_remaining: 197,
        hub_queries_count: 0,
        hub_queries_limit: 200,
        hub_queries_remaining: 200,
        resets_on: nextMonday,
      },
    }
  }
  // Invalidar cache → no-op (los mocks son determinísticos, no hay cache)
  if (method === 'DELETE' && basePath.startsWith('/ai/cache/')) {
    return { deleted: 0 }
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
