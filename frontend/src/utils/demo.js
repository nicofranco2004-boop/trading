// demo — modo "probá Rendi sin login" con portfolio simulado.
// ═══════════════════════════════════════════════════════════════════════════
// Cuando la URL tiene `?demo=1`, AuthContext setea un user demo y este módulo
// intercepta las llamadas al backend devolviendo fixtures hardcodeadas.
//
// Cero backend writes. Cero DB. Vive en memoria del browser durante la sesión.
// Al hacer "Salir del demo" se limpia el localStorage y vuelve al login.
//
// Lo que está stubbeado:
//   /positions /brokers /operations /monthly /snapshots /watchlist
//   /dolar /imports /home/personal /home/heatmap?market=...
//   /events/portfolio /events/popular /news/portfolio /news/market
//   /prices /prices/history (sparkline mock)
//
// Lo que NO está stubbeado (devuelve 200 con array vacío para no romper):
//   AI chat, admin endpoints.

const DEMO_FLAG_KEY = 'rendi_demo_mode'

export function isDemoMode() {
  if (typeof window === 'undefined') return false
  return localStorage.getItem(DEMO_FLAG_KEY) === '1'
}

export function enableDemoMode() {
  if (typeof window === 'undefined') return
  localStorage.setItem(DEMO_FLAG_KEY, '1')
}

export function disableDemoMode() {
  if (typeof window === 'undefined') return
  localStorage.removeItem(DEMO_FLAG_KEY)
  localStorage.removeItem('rendi_token')
  localStorage.removeItem('rendi_user')
}

// ─── Fixture: portfolio simulado de ~18 meses ────────────────────────────────
// Mix realista AR: Schwab USD (acciones US), Cocos ARS (acciones AR + CEDEARs),
// Binance crypto. Total ≈ US$ 28.000 al blue actual.

const BROKERS = [
  { id: 1, name: 'Schwab',  currency: 'USDT' },  // tratamos USD nativo como USDT acá
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
  { id: 199, broker: 'Schwab',  asset: 'USDT',  is_cash: 1, buy_price: null,   quantity: 1250, invested: 1250.00, tc_compra: null, price_override: null, entry_date: null,         commissions: 0 },

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

// Snapshots mensuales (para chart de evolución del Dashboard)
const SNAPSHOTS = (() => {
  // Generamos snapshots desde abr 2024 hasta hoy con tendencia alcista + ruido.
  const out = []
  const startValue = 18000
  const startCapital = 17500
  let value = startValue
  let capital = startCapital
  const start = new Date('2024-04-01')
  const today = new Date()
  while (start <= today) {
    // Evolución mensual: +1.5% mean, ±3% noise
    const driftMonthly = 0.015
    const noise = (Math.random() - 0.5) * 0.06
    value = value * (1 + driftMonthly + noise)
    // Aporta US$ 400 cada 2 meses
    if (start.getMonth() % 2 === 0) capital += 400
    out.push({
      date: start.toISOString().slice(0, 10),
      total_value: Math.round(value * 100) / 100,
      total_invested: Math.round((capital * 0.95) * 100) / 100,
      net_deposited: Math.round(capital * 100) / 100,
    })
    start.setDate(start.getDate() + 7) // semana a semana
  }
  return out.sort((a, b) => b.date.localeCompare(a.date))
})()

// Cierres mensuales (para Monthly Reports / Reports timeline)
const MONTHLY = (() => {
  const out = []
  const start = new Date('2024-04-01')
  const today = new Date()
  while (start < today) {
    const y = start.getFullYear()
    const m = start.getMonth() + 1
    out.push({
      broker: 'global',
      year: y,
      month: m,
      capital_inicio: 17500 + (y - 2024) * 4800 + (m - 1) * 400,
      deposits: Math.random() > 0.7 ? 400 : 0,
      withdrawals: 0,
      pnl_realized: Math.round((Math.random() - 0.3) * 1200),
      pnl_unrealized: Math.round((Math.random() - 0.2) * 2400),
    })
    start.setMonth(start.getMonth() + 1)
  }
  return out
})()

// Watchlist demo
const WATCHLIST = [
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

const DOLAR = {
  blue:   { compra: 1395, venta: 1415 },
  mep:    { compra: 1420, venta: 1424 },
  ccl:    { compra: 1430, venta: 1432 },
  cripto: { compra: 1421, venta: 1422 },
  fetched_at: new Date().toISOString(),
}

const NEWS_MARKET = []  // dejamos vacío — la página se renderiza ok
const NEWS_PORTFOLIO = []
const EVENTS_PORTFOLIO = []
const EVENTS_POPULAR = []

// ─── Mock handler para api.js ────────────────────────────────────────────────
// Recibe (method, path) y devuelve la respuesta. null = no hay mock → la
// llamada real se ejecuta (no debería pasar pero por defensa).

export function handleDemoRequest(method, path, body) {
  // Normalizar query string fuera del match base
  const [basePath, query] = path.split('?')

  // ── GET endpoints ──────────────────────────────────────────────────────────
  if (method === 'GET') {
    if (basePath === '/positions')   return POSITIONS
    if (basePath === '/brokers')     return BROKERS
    if (basePath === '/operations')  return OPERATIONS
    if (basePath === '/monthly')     return MONTHLY
    if (basePath === '/snapshots')   return SNAPSHOTS
    if (basePath === '/watchlist')   return WATCHLIST
    if (basePath === '/dolar')       return DOLAR
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
    if (basePath === '/events/portfolio') return EVENTS_PORTFOLIO
    if (basePath === '/events/popular')   return { events: EVENTS_POPULAR }
    if (basePath === '/news/portfolio')   return { news: NEWS_PORTFOLIO, count: 0 }
    if (basePath === '/news/market')      return { news: NEWS_MARKET, count: 0 }
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
    // Endpoints menos críticos — array vacío para no romper
    if (basePath.startsWith('/insights')) return {}
    if (basePath.startsWith('/goals'))    return []
    return null
  }

  // ── POST / PUT / DELETE ────────────────────────────────────────────────────
  // En demo mode no persistimos. Devolvemos 200 con echo del body si aplica.
  if (method === 'POST' || method === 'PUT' || method === 'DELETE') {
    if (basePath === '/watchlist' || basePath.startsWith('/watchlist/')) return { ok: true }
    if (basePath === '/snapshots') return { ok: true }
    if (basePath.startsWith('/positions')) return body || { ok: true }
    if (basePath.startsWith('/operations')) return body || { ok: true }
    if (basePath === '/ai/chat') {
      return {
        reply: 'Estás en modo demo. Para usar el coach con tu data real, creá una cuenta y subí tu CSV.',
      }
    }
    return { ok: true }
  }

  return null
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
