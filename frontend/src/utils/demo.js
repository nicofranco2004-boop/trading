// demo — modo "probá Rendi sin login" con portfolio simulado.
// ═══════════════════════════════════════════════════════════════════════════
import { isBondTicker } from './tickers'
import { claveSemanaISO } from './semanas'
import { hoyISO, fechaISO } from './fecha'
import { pctTxt } from './format'
import { computeBrokerValue } from './valuation'
import { computeSectorBreakdown } from './assetSector'

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
  // ⚠️ LEER localStorage PUEDE TIRAR EXCEPCIÓN, no sólo venir vacío: pasa en
  // navegación privada vieja, en un iframe con el almacenamiento bloqueado y
  // con la configuración de "no guardar datos de sitios". Chequear `window` no
  // cubre ninguno de esos casos — ahí `window` existe igual.
  //
  // Sin esto, la excepción sube por donde se la haya llamado. Son muchos
  // lugares (la clave del chat guardado, el cliente de la API, el micrófono),
  // y en el peor caso se lleva puesta la pantalla entera. "No es demo" es la
  // respuesta correcta cuando no se puede saber: es lo que pasa siempre salvo
  // que alguien haya entrado por el link de la demo.
  try {
    // La marca guarda CUÁNDO se activó (ver `demoVencido`); el `'1'` viejo también
    // cuenta hasta que `vencerDemoSiCorresponde` lo limpie al abrir la app.
    return !!localStorage.getItem(DEMO_FLAG_KEY)
  } catch {
    return false
  }
}

// ⚠️ EL MODO DEMO VENCE. Antes la marca quedaba para siempre: quien probó el
// demo y volvía otro día a rendi.finance no veía la portada ni podía iniciar
// sesión — veía el demo otra vez, y la única salida era "Crear cuenta"
// (verificado en producción el 2026-09-25). Ahora la marca guarda CUÁNDO se
// activó y se evalúa UNA vez, al abrir la app (`AuthContext`): así nunca se
// corta en medio de una visita.
export const DEMO_DURA_MS = 12 * 60 * 60 * 1000

/** ¿La marca de demo guardada es vieja? `'1'` es el formato anterior, sin fecha. */
export function demoVencido(valor, ahora = Date.now()) {
  if (!valor) return false
  const desde = Number(valor)
  return !(desde > 1) || ahora - desde > DEMO_DURA_MS
}

/** Al abrir la app: si la marca venció, se sale del demo. Devuelve si salió. */
export function vencerDemoSiCorresponde() {
  if (typeof window === 'undefined') return false
  try {
    if (!demoVencido(localStorage.getItem(DEMO_FLAG_KEY))) return false
    localStorage.removeItem(DEMO_FLAG_KEY)
    clearDemoOverlay()
    return true
  } catch {
    return false
  }
}

export function enableDemoMode() {
  if (typeof window === 'undefined') return
  localStorage.setItem(DEMO_FLAG_KEY, String(Date.now()))
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
const BLOCKED_MSG = 'En modo demo no podés guardar este cambio. Creá una cuenta gratis para usar tu cartera real.'

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
  { id: 203, broker: 'Cocos',   asset: 'AAPL',    is_cash: 0, buy_price: 18800, quantity: 40,  invested: 752000,  tc_compra: 1240, price_override: null, entry_date: '2025-01-15', commissions: 0 },
  { id: 204, broker: 'Cocos',   asset: 'AL30',    is_cash: 0, buy_price: 78200, quantity: 60,  invested: 4692000,  tc_compra: 1400, price_override: null, entry_date: '2026-03-15', commissions: 0 },
  { id: 299, broker: 'Cocos',   asset: 'ARS',     is_cash: 1, buy_price: null,  quantity: 180000, invested: 180000, tc_compra: null, price_override: null, entry_date: null,        commissions: 0 },

  // ── Binance crypto ──
  { id: 301, broker: 'Binance', asset: 'BTC',  is_cash: 0, buy_price: 62500,  quantity: 0.085, invested: 5312.50, tc_compra: null, price_override: null, entry_date: '2024-07-22', commissions: 0 },
  { id: 302, broker: 'Binance', asset: 'ETH',  is_cash: 0, buy_price: 3120,   quantity: 1.2,   invested: 3744.00, tc_compra: null, price_override: null, entry_date: '2024-08-30', commissions: 0 },
  { id: 303, broker: 'Binance', asset: 'SOL',  is_cash: 0, buy_price: 165,    quantity: 14,    invested: 2310.00, tc_compra: null, price_override: null, entry_date: '2025-02-04', commissions: 0 },
  { id: 399, broker: 'Binance', asset: 'USDT', is_cash: 1, buy_price: null,   quantity: 820,   invested: 820.00,  tc_compra: null, price_override: null, entry_date: null,         commissions: 0 },
]

// Operaciones cerradas (Movimientos, win rate, profit factor, Reportes).
//
// ⚠️ FECHADAS RELATIVAS A HOY, y con el P&L que da su propia cuenta. Antes eran
// fechas fijas de 2024–2025: ninguna operación en los últimos 12 meses mientras
// Reportes anunciaba "2026: 46 operaciones cerradas" (un número al azar), y las
// dos de Cocos declaraban un P&L en dólares ocho veces el de sus precios. Ahora
// Reportes, Movimientos, el Dashboard y Comportamiento cuentan ESTAS catorce.
// INTC (+148 %) es la mejor operación porque así lo dicen los textos de la IA
// del demo: el fixture tiene que respaldar lo que el demo afirma.
const _TC_OPS_AR = 1300   // dólar de referencia de las ventas en pesos
const OPERATIONS = (() => {
  const hoy = new Date()
  const fecha = (mesesAtras, dia) => {
    const d = new Date(hoy.getFullYear(), hoy.getMonth() - mesesAtras, 1)
    d.setDate(Math.min(dia, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()))
    return fechaISO(d)
  }
  // activo, broker, precio de compra, de venta, cantidad, meses atrás, día
  const ops = [
    ['NVDA', 'Schwab', 120, 142, 10, 17, 12],
    ['MELI', 'Schwab', 1820, 1740, 2, 16, 4],
    ['GOOGL', 'Schwab', 165, 182, 8, 15, 20],
    ['AMD', 'Schwab', 148, 132, 15, 14, 15],
    ['BTC', 'Binance', 58000, 67500, 0.04, 13, 2],
    ['GGAL', 'Cocos', 3850, 4400, 50, 12, 28],
    ['TSLA', 'Schwab', 240, 218, 5, 11, 8],
    ['ETH', 'Binance', 2850, 3320, 0.5, 10, 4],
    ['META', 'Schwab', 480, 545, 4, 9, 22],
    ['AAPL', 'Schwab', 185, 172, 10, 8, 18],
    ['NVDA', 'Schwab', 130, 156, 12, 7, 12],
    ['SOL', 'Binance', 180, 154, 8, 5, 27],
    ['INTC', 'Schwab', 13, 32.2, 60, 4, 9],
    ['AVGO', 'Schwab', 142, 168, 10, 2, 15],
    ['YPFD', 'Cocos', 24500, 27800, 20, 1, 5],
  ]
  return ops.map(([asset, broker, entry_price, exit_price, quantity, meses, dia], i) => {
    const bruto = (exit_price - entry_price) * quantity
    return {
      id: 1000 + i, asset, broker, entry_price, exit_price, quantity,
      pnl_usd: +(broker === 'Cocos' ? bruto / _TC_OPS_AR : bruto).toFixed(2),
      pnl_pct: +(((exit_price / entry_price) - 1) * 100).toFixed(2),
      date: fecha(meses, dia), op_type: 'LONG', commissions: 0,
    }
  })
})()

// Realizado, operaciones y ganadoras POR MES ('YYYY-MM'): lo leen la historia
// mensual y Reportes, así que las tres pantallas cuentan las mismas operaciones.
const _OPS_POR_MES = (() => {
  const out = {}
  for (const o of OPERATIONS) {
    const k = o.date.slice(0, 7)
    if (!out[k]) out[k] = { pnl: 0, trades: 0, wins: 0, activos: [] }
    out[k].pnl += o.pnl_usd
    out[k].trades += 1
    if (o.pnl_usd > 0) out[k].wins += 1
    out[k].activos.push(o)
  }
  return out
})()

// Precios actuales fake (snapshot del momento). Definido ARRIBA de MONTHLY a
// propósito: MONTHLY hace una simulación stochastic desde un valor inicial,
// pero el VALOR FINAL del portfolio (lo que el user ve en el hero del
// Dashboard) sale de POSITIONS × PRICES. Si MONTHLY no termina cerca de
// (POSITIONS × PRICES), la "P&L Últimos N días" se infla por el gap entre
// las dos simulaciones independientes. Necesitamos PRICES acá para
// computar el target y scalear MONTHLY.
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

// Precios "cierre día anterior" derivados de PRICES — necesarios para que
// la columna VAR. DÍA en /posiciones muestre data en modo demo (antes
// devolvía vacío y todas las posiciones quedaban con "—").
//
// Derivamos con un hash determinístico por símbolo (mismo prev_close en
// cada render → no parpadea entre refreshes). Drift -2% a +2.5% con bias
// hacia positivo (más symbols "en verde" hoy = portfolio demo se ve más
// atractivo para marketing).
// ⚠️ UNA SOLA VARIACIÓN DEL DÍA POR ACTIVO. El mapa de calor, los destacados y
// el índice decían "NVDA +4,4 % hoy" mientras la Cartera mostraba NVDA −0,29 %
// en el día (salía de un hash). Ahora los que aparecen en el mercado usan esta
// tabla, que es la del mapa de calor (`buildHeatmapBlocks`); el resto, el hash.
const _CAMBIO_DIA = {
  NVDA: 4.4, AAPL: 1.0, MSFT: 1.2, TSLA: -2.1, AMD: 0.9, SPY: 0.42, GOOGL: -0.4, META: 0.3,
  AVGO: 5.5, BTC: 2.7, ETH: 1.7, SOL: 1.9, 'GGAL.BA': 0.1, 'YPFD.BA': 1.2, 'AAPL.BA': 1.0,
  PLTR: -2.1, COIN: 4.5,
}
const PREV_CLOSE = (() => {
  const out = {}
  for (const [sym, price] of Object.entries(PRICES)) {
    // Hash simple del symbol para drift estable per-render
    let hash = 0
    for (let i = 0; i < sym.length; i++) hash = (hash * 31 + sym.charCodeAt(i)) & 0xffff
    // Distribución: -2% a +2.5% (bias positivo levemente)
    const dailyChange = _CAMBIO_DIA[sym] != null ? _CAMBIO_DIA[sym] / 100 : ((hash % 450) - 200) / 10000
    // prev_close = current / (1 + change) → si change > 0, today subió
    const prev = price / (1 + dailyChange)
    // Redondeo: 4 decimales para crypto chico, 2 para resto
    out[sym] = price < 10 ? +prev.toFixed(4) : +prev.toFixed(2)
  }
  return out
})()

// ─── Números FIJOS, no al azar ───────────────────────────────────────────────
// ⚠️ ANTES TODO SALÍA DE Math.random AL CARGAR: cada recarga era otra cartera
// ("Ganancia total" entre 16 % y 76 %, "P&L realizado" entre US$ 460 y 3.656) y
// lo que el visitante miró hace un minuto ya no existía. Ahora cada serie tiene
// su semilla, y cada MES la suya: sumar el mes nuevo no cambia los anteriores.
function crearAzar(semilla) {
  let a = semilla >>> 0
  return () => {
    a = (a + 0x6D2B79F5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
// La semilla elige UNA historia verosímil entre las posibles: año en curso
// positivo y cerca del S&P, ningún mes peor que −6 %. Cambiarla cambia todos los
// números del demo a la vez (y siguen cerrando entre sí).
const _SEMILLA_DEMO = 'rendi-demo-2'
function azarDe(clave) { return crearAzar(_hashStr(`${_SEMILLA_DEMO}|${clave}`)) }

const _DEMO_TC_BLUE = 1415    // /config del demo
const _DEMO_TC_MEP = 1424     // DOLAR.mep.venta: el dólar con el que valúa la pantalla
const _DEMO_TC_CRIPTO = 1422  // DOLAR.cripto.venta

// ⚠️ LA CARTERA SE VALÚA CON LA MISMA FUNCIÓN QUE LA PANTALLA (computeBrokerValue,
// al MEP, con el costo 'purchase' que ve un visitante). Antes había una copia a
// mano, al blue: el demo decía US$ 41.470 donde el Dashboard mostraba 41.435,82,
// y el costo —del que sale el aportado— no era el de la pantalla.
// La cartera a los precios de AYER: el cierre de ayer de la historia diaria.
// Así "Hoy" es exactamente la suma de la variación del día de cada posición.
const _VALOR_CIERRE_AYER = (() => {
  let v = 0
  for (const b of BROKERS) v += computeBrokerValue(POSITIONS, PREV_CLOSE, b, _DEMO_TC_MEP, _DEMO_TC_MEP, _DEMO_TC_CRIPTO, 'purchase').value
  return v
})()

const _VALUACION = (() => {
  const porBroker = {}
  let valor = 0
  let costo = 0
  for (const b of BROKERS) {
    const r = computeBrokerValue(POSITIONS, PRICES, b, _DEMO_TC_MEP, _DEMO_TC_MEP, _DEMO_TC_CRIPTO, 'purchase')
    porBroker[b.name] = r.value
    valor += r.value
    costo += r.invested
  }
  return { porBroker, valor, costo }
})()

// Peso de cada broker en la cartera de hoy: reparte la historia del total entre
// brokers (el gráfico en pesos de Insights filtra por broker).
const BROKER_WEIGHTS = (() => {
  const w = {}
  for (const b of BROKERS) w[b.name] = (_VALUACION.porBroker[b.name] || 0) / (_VALUACION.valor || 1)
  return w
})()

// Cierres mensuales (Reportes, Insights, /mensual). Cada mes:
//   capital_inicio[t] = capital_final[t-1]
//   capital_final[t] = capital_inicio[t] + aportes + resultado
//
// ⚠️ LA HISTORIA CIERRA CON LA CARTERA DE HOY. El Dashboard verifica
//     aportado + realizado = costo de lo que hay hoy
// y lo que no cierra lo publica como "Dividendos e intereses · no cargados como
// P&L" (o "Diferencia sin explicar"). Con aportes y realizado al azar, el demo
// mostraba en 79 de 80 cargas entre US$ 1.700 y 6.900 de dividendos que no
// existen, sobre NVDA, TSLA y BTC. Ahora:
//   · el realizado de cada mes es el de las OPERATIONS de ese mes;
//   · el capital inicial es lo que falta para que aportado = costo − realizado;
//   · el rendimiento de los meses se ajusta, todos por igual, para que el último
//     cierre sea exactamente el valor que muestra la pantalla.
// El mes en curso rinde sólo lo transcurrido: si no, el día 1 "Hoy" publicaba
// el mes entero (+3,9 % a las 10 de la mañana, antes de que abra el mercado).
const MONTHLY = (() => {
  const hoy = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const plan = []
  for (let d = new Date(2024, 3, 1); d <= hoy; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
    const y = d.getFullYear()
    const m = d.getMonth() + 1
    const key = `${y}-${pad(m)}`
    const r = azarDe('mes-' + key)
    const deposito = r() > 0.65 ? Math.round(400 + r() * 400) : 0
    const retorno = 0.012 + (r() - 0.5) * 0.06
    const enCurso = y === hoy.getFullYear() && m === hoy.getMonth() + 1
    const transcurrido = enCurso ? hoy.getDate() / new Date(y, m, 0).getDate() : 1
    plan.push({ y, m, key, deposito, retorno, transcurrido, realizado: _OPS_POR_MES[key]?.pnl || 0 })
  }
  const realizado = plan.reduce((s, x) => s + x.realizado, 0)
  const aportado = _VALUACION.costo - realizado
  const inicial = aportado - plan.reduce((s, x) => s + x.deposito, 0)
  const recorrer = (ajuste) => {
    let v = inicial
    return plan.map((x) => {
      const ci = v
      const cf = (ci + x.deposito) * (1 + (x.retorno + ajuste) * x.transcurrido)
      v = cf
      return { ci, cf }
    })
  }
  let lo = -0.2
  let hi = 0.2
  for (let i = 0; i < 80; i++) {
    const mid = (lo + hi) / 2
    const t = recorrer(mid)
    if (t[t.length - 1].cf > _VALUACION.valor) hi = mid
    else lo = mid
  }
  const tramos = recorrer((lo + hi) / 2)
  tramos[tramos.length - 1].cf = _VALUACION.valor
  const r2 = (n) => Math.round(n * 100) / 100
  const out = []
  plan.forEach((x, i) => {
    const ci = r2(tramos[i].ci)
    const cf = r2(tramos[i].cf)
    const pnlRealized = r2(x.realizado)
    const pnlUnrealized = r2(cf - ci - x.deposito - pnlRealized)
    out.push({
      broker: 'global', year: x.y, month: x.m,
      capital_inicio: ci, capital_final: cf, deposits: x.deposito, withdrawals: 0,
      pnl_realized: pnlRealized, pnl_unrealized: pnlUnrealized,
    })
    for (const [brokerName, w] of Object.entries(BROKER_WEIGHTS)) {
      out.push({
        broker: brokerName, year: x.y, month: x.m,
        capital_inicio: r2(ci * w), capital_final: r2(cf * w), deposits: r2(x.deposito * w), withdrawals: 0,
        pnl_realized: r2(pnlRealized * w), pnl_unrealized: r2(pnlUnrealized * w),
      })
    }
  })
  return out
})()

// La última fila del TOTAL (no la última fila: detrás de cada mes vienen las de
// cada broker, y leer `MONTHLY[length-1]` —Binance— fue el −64,9 % del chip).
const _ULTIMO_GLOBAL = [...MONTHLY].reverse().find(m => m.broker === 'global')
const MONTHLY_LAST_VALUATION = _ULTIMO_GLOBAL ? _ULTIMO_GLOBAL.capital_final : _VALUACION.valor

// Benchmarks mensuales (Insights y comparaciones). Mismas keys que el backend:
// USD → sp500, shv (T-Bills), gld (Oro). ARS → inflation_ar, merval, uva, dolar_blue.
//
// ⚠️ INFLACIÓN REALISTA. La vieja arrancaba en 12 % MENSUAL y bajaba de a
// 0,25: sumaba +300 % en el período del demo y Diagnóstico publicaba "Le
// perdés a la inflación −43 %". Ahora es la serie mensual argentina de
// referencia (INDEC hasta 2025, aproximada; 2026 supuesta), y el blue sigue un
// camino plausible hasta el blue del demo.
const _INFLACION_REF = {
  2023: [6.0, 6.6, 7.7, 8.4, 7.8, 6.0, 6.3, 12.4, 12.7, 8.3, 12.8, 25.5],
  2024: [20.6, 13.2, 11.0, 8.8, 4.2, 4.6, 4.0, 4.2, 3.5, 2.7, 2.4, 2.7],
  2025: [2.2, 2.4, 3.7, 2.8, 1.5, 1.6, 1.9, 1.9, 2.1, 2.3, 2.5, 2.8],
  2026: [2.3, 2.3, 2.2, 2.1, 2.0, 2.0, 1.9, 1.9, 1.9, 1.9, 1.9, 1.9],
}
const _BLUE_ANCLAS = [['2023-01', 380], ['2023-12', 1000], ['2024-04', 1020], ['2024-07', 1420],
  ['2024-10', 1200], ['2024-12', 1220], ['2025-06', 1290], ['2025-12', 1370]]
const BENCHMARKS = (() => {
  const out = { sp500: {}, inflation_ar: {}, dolar_blue: {}, shv: {}, gld: {}, merval: {}, uva: {} }
  const hoy = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const idxMes = (k) => Number(k.slice(0, 4)) * 12 + Number(k.slice(5, 7)) - 1
  const blueEn = (k) => {
    const i = idxMes(k)
    const anclas = _BLUE_ANCLAS.map(([mk, v]) => [idxMes(mk), v])
    if (i <= anclas[0][0]) return anclas[0][1]
    for (let j = 1; j < anclas.length; j++) {
      const [i0, v0] = anclas[j - 1]
      const [i1, v1] = anclas[j]
      if (i <= i1) return v0 * Math.pow(v1 / v0, (i - i0) / (i1 - i0))
    }
    const [iu, vu] = anclas[anclas.length - 1]
    return vu * Math.pow(1.0035, i - iu)
  }
  let sp = 4700, shv = 110, gld = 185, merv = 400000, uva = 400
  for (let d = new Date(2023, 0, 1); d <= hoy; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
    const y = d.getFullYear()
    const key = `${y}-${pad(d.getMonth() + 1)}`
    const r = azarDe('bench-' + key)
    sp = sp * (1 + 0.009 + (r() - 0.5) * 0.05)
    out.sp500[key] = Math.round(sp * 100) / 100
    const infl = (_INFLACION_REF[y] || _INFLACION_REF[2026])[d.getMonth()]
    out.inflation_ar[key] = infl
    out.dolar_blue[key] = Math.round(blueEn(key) * (1 + (r() - 0.5) * 0.02))
    shv = shv * (1 + 0.0035 + (r() - 0.5) * 0.004)
    out.shv[key] = Math.round(shv * 100) / 100
    gld = gld * (1 + 0.012 + (r() - 0.5) * 0.045)
    out.gld[key] = Math.round(gld * 100) / 100
    merv = merv * (1 + infl / 100 + (r() - 0.5) * 0.07)
    out.merval[key] = Math.round(merv)
    uva = uva * (1 + infl / 100)
    out.uva[key] = Math.round(uva * 100) / 100
  }
  // El último mes del blue = el blue del demo: la vista en pesos valúa "Hoy" al
  // blue actual y el último mes al de la serie; si no coinciden, "Hoy" salta.
  const claves = Object.keys(out.dolar_blue).sort()
  const ultimo = claves.length ? out.dolar_blue[claves[claves.length - 1]] : 0
  if (ultimo > 0) {
    const escala = _DEMO_TC_BLUE / ultimo
    for (const k of claves) out.dolar_blue[k] = Math.round(out.dolar_blue[k] * escala)
  }
  return { ...out, fetched_at: new Date().toISOString() }
})()

const DOLAR = {
  blue:   { compra: 1395, venta: _DEMO_TC_BLUE },
  mep:    { compra: 1420, venta: _DEMO_TC_MEP },
  ccl:    { compra: 1430, venta: 1432 },
  cripto: { compra: 1421, venta: _DEMO_TC_CRIPTO },
  fetched_at: new Date().toISOString(),
}


// Fotos diarias DERIVADAS del MONTHLY para que ambos cuenten la misma historia:
// un cierre por día, como el que escribe el cron en producción, y el último día
// de cada mes ES su capital_final.
//
// ⚠️ UN CIERRE POR DÍA, NO UNO POR SEMANA. Con los 1/8/15/22 de antes el cierre
// anterior al 1° de mes quedaba siempre a 7-10 días, más que los 5 que tolera
// `esBordeFresco`: "Este mes" no tenía número NUNCA en la demo y "Hoy" decía
// "Últimos 3 días". Una demo que no puede mostrar lo que ve un usuario con el
// cron andando no demuestra nada.
//
// Las filas llevan `clase`/`base`/`apto`/`sintetico` con los valores EXACTOS que
// devuelve GET /api/snapshots (twr.clasificar_serie + twr.es_apto), para que la
// pantalla recorra en la demo los mismos guards que en producción.
const SNAPSHOTS = (() => {
  // Solo entries "global" — `MONTHLY` también contiene desagregados por
  // broker (Schwab/Cocos/Binance), iterar sobre todos produce un zigzag
  // brutal en el chart porque los valores parciales (ej. Cocos ~$1k vs
  // global ~$30k) se alternan en la serie temporal.
  const globals = MONTHLY.filter(m => m.broker === 'global')
  if (globals.length === 0) return []
  const hoy = hoyISO()
  const [hoyY, hoyM, hoyD] = hoy.split('-').map(Number)
  const medicion = { clase: 'medicion', base: 'mercado', apto: true, sintetico: false }
  const out = []
  let aportado = globals[0].capital_inicio
  for (const m of globals) {
    const flujo = (m.deposits || 0) - (m.withdrawals || 0)
    // El aporte entra el día 1 y mueve valor y aportado JUNTOS: la ganancia
    // (valor − aportado) no pega un escalón que no existió.
    aportado += flujo
    const resultado = m.capital_final - m.capital_inicio - flujo
    const diasDelMes = new Date(m.year, m.month, 0).getDate()
    // El mes en curso llega a su capital_final HOY (el valor vivo), no a fin de mes.
    const tramo = (m.year === hoyY && m.month === hoyM) ? hoyD : diasDelMes
    for (let dia = 1; dia <= diasDelMes; dia++) {
      const fecha = fechaISO(new Date(m.year, m.month - 1, dia))
      if (fecha >= hoy) break
      // Ruido de ±0,25 % aprox. que se anula en el cierre de mes.
      const ruido = dia === diasDelMes ? 0 : (azarDe('dia-' + fecha)() - 0.5) * 200
      let valor = m.capital_inicio + flujo + resultado * (dia / tramo) + ruido
      // El mes en curso llega AYER a la cartera valuada con los precios de ayer
      // (PREV_CLOSE): "Hoy" = la variación del día de cada posición, sumada.
      if (tramo === hoyD && hoyD > 1) {
        const hastaAyer = (_VALOR_CIERRE_AYER - m.capital_inicio - flujo) * (dia / (hoyD - 1))
        valor = m.capital_inicio + flujo + hastaAyer + (dia === hoyD - 1 ? 0 : ruido)
      }
      out.push({
        date: fecha,
        total_value: Math.round(valor * 100) / 100,
        total_invested: Math.round(aportado * 0.95 * 100) / 100,
        net_deposited: Math.round(aportado * 100) / 100,
        ...medicion,
      })
    }
  }
  // La foto de hoy: la que el Dashboard escribe en la primera visita del día. En
  // producción es INTRADIA (media rueda: sostiene la línea, nunca abre ni cierra
  // un período) y la pantalla la reemplaza por el valor vivo.
  out.push({
    date: hoy,
    total_value: Math.round(MONTHLY_LAST_VALUATION * 100) / 100,
    total_invested: Math.round(aportado * 0.95 * 100) / 100,
    net_deposited: Math.round(aportado * 100) / 100,
    clase: 'intradia', base: 'mercado', apto: false, sintetico: true,
  })
  return out.sort((a, b) => b.date.localeCompare(a.date))
})()


// ─── Reports timeline derivada de MONTHLY ───────────────────────────────────
// El backend devuelve PeriodReport por mes con metrics + headline. Acá
// armamos algo equivalente para que /reportes muestre la timeline visual
// (KPI strip, calendar heatmap, monthly table) sin "Not authenticated".

const MONTH_NAMES_ES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

// ─── Un período medido con las MISMAS fotos que el Dashboard ────────────────
// Mes, semana, día y año de Reportes salen de acá: Δ(valor − aportado) entre el
// último cierre ANTES del período y el último cierre DEL período (el de hoy si
// está en curso), el % con Dietz como en Reportes de producción, y las
// operaciones cerradas en esas fechas.
//
// ⚠️ ANTES CADA PANTALLA INVENTABA SU NÚMERO. La semana repartía el mes con
// pesos fijos (un 16 % del mes caía en una semana que todavía no había
// empezado), el día salía de azar nuevo en cada pedido (el mismo día daba
// −US$ 208 y después +US$ 172) y las operaciones del mes eran 2 a 8 al azar
// aunque Movimientos no tuviera ninguna. En una misma sesión, "Este mes",
// "Septiembre en curso" y Reportes → Mes daban tres números distintos.
const MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
const DIAS_CORTOS = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb']

function _medirPeriodoDemo(inicio, fin) {
  const asc = [...SNAPSHOTS].sort((a, b) => (a.date < b.date ? -1 : 1))
  if (!asc.length) return null
  const base = [...asc].reverse().find(s => s.date < inicio) || asc[0]
  const cierre = [...asc].reverse().find(s => s.date <= fin)
  if (!cierre || cierre.date < inicio || cierre === base) return null
  const r2 = (n) => Math.round(n * 100) / 100
  const aportes = cierre.net_deposited - base.net_deposited
  const deltaUsd = (cierre.total_value - cierre.net_deposited) - (base.total_value - base.net_deposited)
  const denominador = base.total_value + 0.5 * aportes
  const ops = OPERATIONS.filter(o => o.date >= inicio && o.date <= fin)
  const wins = ops.filter(o => o.pnl_usd > 0).length
  const realizado = ops.reduce((s, o) => s + o.pnl_usd, 0)
  return {
    start_value: r2(base.total_value),
    end_value: r2(cierre.total_value),
    delta_usd: r2(deltaUsd),
    delta_pct: denominador > 0 ? +((deltaUsd / denominador) * 100).toFixed(2) : null,
    delta_pct_over_contrib: null,
    realized_pnl: r2(realizado),
    unrealized_pnl: r2(deltaUsd - realizado),
    deposits: r2(Math.max(0, aportes)),
    withdrawals: r2(Math.max(0, -aportes)),
    trades_count: ops.length,
    win_count: wins,
    loss_count: ops.length - wins,
    win_rate: ops.length ? Math.round((wins / ops.length) * 100) : null,
    vs_sp500_pct: null,
    vs_inflation_pct: null,
    basis_incomparable: false,
    _ops: ops,
  }
}

// S&P del período, con la misma serie que dibuja el gráfico del demo.
function _spDelPeriodo(claveMesAnterior, claveMesFinal) {
  const a = BENCHMARKS.sp500[claveMesAnterior]
  const b = BENCHMARKS.sp500[claveMesFinal]
  return a > 0 && b > 0 ? (b / a - 1) * 100 : null
}
const _claveMes = (y, m) => `${y}-${String(m).padStart(2, '0')}`
const _mesAnterior = (y, m) => (m === 1 ? _claveMes(y - 1, 12) : _claveMes(y, m - 1))

function _textoOps(metrics) {
  const ops = metrics._ops || []
  if (!ops.length) return 'Sin operaciones cerradas: el resultado vino de las posiciones abiertas.'
  const mayor = [...ops].sort((a, b) => Math.abs(b.pnl_usd) - Math.abs(a.pnl_usd))[0]
  const signo = mayor.pnl_usd >= 0 ? '+' : '−'
  return `Cerraste ${ops.length} operaci${ops.length === 1 ? 'ón' : 'ones'} (${metrics.win_count} ganadora${metrics.win_count === 1 ? '' : 's'}); la de más peso fue ${mayor.asset}, ${signo}US$ ${Math.abs(mayor.pnl_usd).toLocaleString('es-AR', { maximumFractionDigits: 0 })}.`
}
const _sinInterno = ({ _ops, ...m }) => m

function _semanaDemo(lunesIso) {
  const lunes = new Date(`${lunesIso}T00:00:00Z`)
  const domingo = new Date(lunes.getTime())
  domingo.setUTCDate(domingo.getUTCDate() + 6)
  const finIso = domingo.toISOString().slice(0, 10)
  const hoyIso = hoyISO()
  if (lunesIso > hoyIso) return null
  const m = _medirPeriodoDemo(lunesIso, finIso)
  if (!m) return null
  const clave = claveSemanaISO(lunesIso)
  return {
    period_type: 'week',
    period_key: clave,
    period_label: `Semana ${Number(clave.slice(-2))}`,
    period_start: lunesIso,
    period_end: finIso,
    is_current: lunesIso <= hoyIso && hoyIso <= finIso,
    is_relevant: Math.abs(m.delta_usd) >= 100 || m.trades_count > 0,
    metrics: _sinInterno(m),
    headline: m.delta_usd > 0 ? 'Semana en alza.' : m.delta_usd < 0 ? 'Semana en baja.' : 'Semana sin cambios.',
    subheadline: null,
    insights: [],
    highlights: [],
    children: [],
    _textoOps: _textoOps(m),
  }
}

function semanasDelMesDemo(m) {
  const lunes = []
  const cursor = new Date(Date.UTC(m.year, m.month - 1, 1))
  while (cursor.getUTCMonth() === m.month - 1) {
    if (cursor.getUTCDay() === 1) lunes.push(cursor.toISOString().slice(0, 10))
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return lunes.map(_semanaDemo).filter(Boolean).map(({ _textoOps, ...w }) => w)
}

const REPORTS_TIMELINE = (() => {
  const globals = MONTHLY.filter(m => m.broker === 'global')
  const hoy = new Date()
  return globals.map((m) => {
    const clave = _claveMes(m.year, m.month)
    const ultimoDia = new Date(m.year, m.month, 0).getDate()
    const metrics = _medirPeriodoDemo(`${clave}-01`, `${clave}-${String(ultimoDia).padStart(2, '0')}`)
      || { ...(_medirPeriodoDemo(`${clave}-01`, hoyISO()) || {}) }
    const isCurrent = m.year === hoy.getFullYear() && m.month === hoy.getMonth() + 1
    const pct = metrics.delta_pct ?? 0
    const sp = _spDelPeriodo(_mesAnterior(m.year, m.month), clave)
    const vsSp = sp != null ? +(pct - sp).toFixed(1) : null
    const isRelevant = Math.abs(metrics.delta_usd || 0) > 50 || (metrics.deposits || 0) > 50 || (metrics.trades_count || 0) > 0

    let headline = 'Mes con movimiento moderado.'
    if (pct > 5) headline = 'Mes sólido — rally generalizado del mercado.'
    else if (pct > 2) headline = 'Buen rendimiento del mes.'
    else if (pct < -3) headline = 'Mes difícil — corrección del mercado afectó la cartera.'
    else if (pct < 0) headline = 'Mes ligeramente negativo, sin caídas relevantes.'

    const verbo = (metrics.delta_usd || 0) >= 0 ? 'ganaste' : 'perdiste'
    const vsSpStr = vsSp != null && Math.abs(vsSp) >= 0.5
      ? ` Quedaste ${Math.abs(vsSp).toFixed(1).replace('.', ',')} puntos ${vsSp > 0 ? 'encima' : 'debajo'} del S&P 500.`
      : ''
    const narrative = (isRelevant || isCurrent)
      ? `En ${MONTH_NAMES_ES[m.month - 1].toLowerCase()} ${m.year} ${verbo} US$ ${Math.abs(Math.round(metrics.delta_usd || 0)).toLocaleString('es-AR')} (${pct >= 0 ? '+' : ''}${pct.toFixed(1).replace('.', ',')}%) sobre un capital inicial de US$ ${Math.round(metrics.start_value || 0).toLocaleString('es-AR')}. ${_textoOps(metrics)}${vsSpStr}`
      : null

    return {
      period_type: 'month',
      period_key: clave,
      period_label: `${MONTH_NAMES_ES[m.month - 1]} ${m.year}`,
      period_start: `${clave}-01`,
      period_end: `${clave}-${String(ultimoDia).padStart(2, '0')}`,
      is_current: isCurrent,
      is_relevant: isRelevant || isCurrent,
      metrics: { ..._sinInterno(metrics), vs_sp500_pct: vsSp },
      headline,
      subheadline: null,
      narrative,
      highlights: [],
      insights: [],
      children: semanasDelMesDemo(m),
    }
  }).reverse()  // descendente — mes en curso primero
})()

// ─── Reports period — /reports/period/{day|week|month|year}/{key} ───────────
function buildDemoPeriodReport(periodType, periodKey) {
  if (periodType === 'month') {
    const existing = REPORTS_TIMELINE.find(r => r.period_key === periodKey)
    if (existing) return { ...existing, portfolio_snapshot: _demoPortfolioSnapshot() }
  }

  if (periodType === 'year') {
    const y = parseInt(periodKey, 10)
    const meses = REPORTS_TIMELINE.filter(r => r.period_key.startsWith(`${y}-`))
    if (meses.length === 0) return _emptyDemoPeriod(periodType, periodKey, `Año ${y}`)
    const primero = meses[meses.length - 1]   // la timeline viene descendente
    const ultimo = meses[0]
    const m = _medirPeriodoDemo(primero.period_start, ultimo.period_end)
    if (!m) return _emptyDemoPeriod(periodType, periodKey, `Año ${y}`)
    const sp = _spDelPeriodo(_claveMes(y - 1, 12), ultimo.period_key)
    const vsSp = sp != null && m.delta_pct != null ? +(m.delta_pct - sp).toFixed(1) : null
    const pct = m.delta_pct ?? 0
    const isCurrent = new Date().getFullYear() === y
    const verbo = m.delta_usd >= 0 ? 'ganaste' : 'perdiste'
    const narrative = `En ${y} ${verbo} US$ ${Math.abs(Math.round(m.delta_usd)).toLocaleString('es-AR')} (${pct >= 0 ? '+' : ''}${pct.toFixed(1).replace('.', ',')}%) sobre un capital inicial de US$ ${Math.round(m.start_value).toLocaleString('es-AR')}. Aportaste US$ ${Math.round(m.deposits).toLocaleString('es-AR')} netos en el año. ${_textoOps(m)}`
    return {
      period_type: 'year',
      period_key: periodKey,
      period_label: `Año ${y}`,
      period_start: `${y}-01-01`,
      period_end: `${y}-12-31`,
      is_current: isCurrent,
      is_relevant: Math.abs(m.delta_usd) >= 100 || m.trades_count > 0,
      metrics: { ..._sinInterno(m), vs_sp500_pct: vsSp },
      headline: pct > 10 ? `Año sólido — +${pct.toFixed(1).replace('.', ',')}%.`
        : pct < -3 ? `Año difícil — ${pct.toFixed(1).replace('.', ',')}%.`
        : `Año mixto — ${pct >= 0 ? '+' : ''}${pct.toFixed(1).replace('.', ',')}%.`,
      subheadline: null,
      narrative,
      highlights: [],
      insights: [],
      children: [],
      portfolio_snapshot: _demoPortfolioSnapshot(),
    }
  }

  if (periodType === 'week') {
    // weekKey YYYY-Wnn → lunes ISO
    const [yStr, wStr] = periodKey.split('-W')
    const jan4 = new Date(Date.UTC(parseInt(yStr, 10), 0, 4))
    const lunes = new Date(jan4)
    lunes.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() + 6) % 7) + (parseInt(wStr, 10) - 1) * 7)
    const semana = _semanaDemo(lunes.toISOString().slice(0, 10))
    if (!semana) return _emptyDemoPeriod(periodType, periodKey, `Semana ${parseInt(wStr, 10)}`)
    const d = semana.metrics.delta_usd
    const { _textoOps: texto, ...w } = semana
    return {
      ...w,
      narrative: `En esta semana ${d >= 0 ? 'ganaste' : 'perdiste'} US$ ${Math.abs(Math.round(d)).toLocaleString('es-AR')} (${semana.metrics.delta_pct >= 0 ? '+' : ''}${pctTxt(semana.metrics.delta_pct)}). ${texto}`,
      portfolio_snapshot: _demoPortfolioSnapshot(),
    }
  }

  // 'day' — ese día contra el cierre anterior, con las fotos diarias.
  const dia = periodKey
  const m = _medirPeriodoDemo(dia, dia)
  const f = new Date(`${dia}T00:00:00Z`)
  const label = `${DIAS_CORTOS[f.getUTCDay()]} ${f.getUTCDate()} ${MESES_CORTOS[f.getUTCMonth()]}`
  if (!m) return _emptyDemoPeriod('day', periodKey, label)
  const pct = m.delta_pct ?? 0
  const relevante = Math.abs(m.delta_usd) >= 30 || m.trades_count > 0
  return {
    period_type: 'day',
    period_key: periodKey,
    period_label: label,
    period_start: dia,
    period_end: dia,
    is_current: dia === hoyISO(),
    is_relevant: relevante,
    metrics: _sinInterno(m),
    headline: !relevante ? 'Día sin grandes movimientos.'
      : pct >= 1 ? `Día sólido — +${pct.toFixed(2).replace('.', ',')}%.`
      : pct <= -1 ? `Día difícil — ${pct.toFixed(2).replace('.', ',')}%.`
      : `Día mixto — ${pct >= 0 ? '+' : ''}${pct.toFixed(2).replace('.', ',')}%.`,
    subheadline: null,
    narrative: relevante
      ? `En este día ${m.delta_usd >= 0 ? 'ganaste' : 'perdiste'} US$ ${Math.abs(Math.round(m.delta_usd)).toLocaleString('es-AR')} (${pct >= 0 ? '+' : ''}${pct.toFixed(1).replace('.', ',')}%). ${_textoOps(m)}`
      : null,
    highlights: [],
    insights: [],
    children: [],
    portfolio_snapshot: _demoPortfolioSnapshot(),
  }
}

function _demoPortfolioSnapshot() {
  // Capital aportado: baseline + deposits acumulados, capado a 85% del valor
  // actual para que el ratio "retorno acumulado" sea positivo en demo.
  // Sólo las filas 'global': recorrer MONTHLY entero sumaba los aportes del total
  // Y los de cada broker — el mismo aporte casi dos veces (ver MONTHLY_LAST_VALUATION).
  const globals = MONTHLY.filter(m => m.broker === 'global')
  let deposits = 0
  for (const m of globals) deposits += (m.deposits || 0) - (m.withdrawals || 0)
  const baseline = globals.length ? globals[0].capital_inicio : 0
  const rawCum = baseline + deposits
  // Sin el tope al 85 % del valor que tenía antes: con él, en algunas cargas
  // Reportes mostraba un "Capital aportado" distinto del Dashboard.
  const cumDeposited = rawCum

  // Δ 7d / 30d derivados de SNAPSHOTS (snapshots están sorted DESC en el demo).
  // "now" = el snapshot más reciente del array (no MONTHLY_LAST_VALUATION,
  // que puede divergir por el noise random de interpolación).
  const nowSnap = SNAPSHOTS && SNAPSHOTS.length > 0 ? SNAPSHOTS[0] : null
  const nowVal = nowSnap ? nowSnap.total_value : MONTHLY_LAST_VALUATION
  const delta = (daysAgo) => {
    if (!SNAPSHOTS || SNAPSHOTS.length === 0 || !nowSnap) return null
    // referencia: fecha = nowSnap.date - N días
    const ref = new Date(nowSnap.date + 'T00:00:00Z')
    ref.setUTCDate(ref.getUTCDate() - daysAgo)
    const targetIso = ref.toISOString().slice(0, 10)
    // SNAPSHOTS ordenado DESC — find devuelve el primer (más reciente) ≤ target
    const prev = SNAPSHOTS.find(s => s.date <= targetIso)
    if (!prev || !prev.total_value || prev.total_value <= 0) return null
    // Descontando aportes, como `_snapshot_delta` del backend: la resta de
    // valores a secas contaba el depósito del mes como ganancia de la semana.
    const usd = (nowVal - (nowSnap.net_deposited || 0)) - (prev.total_value - (prev.net_deposited || 0))
    return {
      usd: +usd.toFixed(2),
      pct: +((usd / prev.total_value) * 100).toFixed(2),
    }
  }

  // YTD: desde el primer monthly_entry del año actual, descontando los aportes
  // del año y con el mismo denominador que `_ytd_delta` del backend (Dietz). La
  // resta a secas publicaba "YTD +24,7 %" al lado de "P&L del año +10,9 %" en la
  // misma tarjeta: la diferencia eran los aportes.
  const curYear = new Date().getFullYear()
  const delAnio = globals.filter(m => m.year === curYear)
  const firstOfYear = delAnio[0]
  const flujosDelAnio = delAnio.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)
  // Sin base positiva no hay YTD (Reports.jsx hace `ytd.pct.toFixed`: un pct
  // nulo la rompería; un YTD ausente, no).
  const baseYtd = firstOfYear ? firstOfYear.capital_inicio + 0.5 * flujosDelAnio : 0
  const ytd = (firstOfYear && firstOfYear.capital_inicio > 0 && baseYtd > 0)
    ? (() => {
        const usd = nowVal - firstOfYear.capital_inicio - flujosDelAnio
        return {
          usd: +usd.toFixed(2),
          pct: +((usd / baseYtd) * 100).toFixed(2),
          since_year: curYear,
        }
      })()
    : null

  // Última operación cerrada del demo
  const ops = (typeof OPERATIONS !== 'undefined' && OPERATIONS) ? OPERATIONS : []
  const closed = ops.filter(o => o.pnl_usd != null).sort((a, b) => (b.date || '').localeCompare(a.date || ''))
  const lastOp = closed.length > 0 ? {
    date: closed[0].date,
    asset: closed[0].asset,
    broker: closed[0].broker,
    op_type: closed[0].op_type,
    pnl_usd: closed[0].pnl_usd,
  } : null

  // Top 3 holdings por invested (no-cash)
  const nonCashPositions = (typeof POSITIONS !== 'undefined' && POSITIONS)
    ? POSITIONS.filter(p => !p.is_cash && (p.quantity || 0) > 0)
    : []
  // Ordenadas por VALOR EN DÓLARES con la valuación de la pantalla. Antes se
  // ordenaba por `invested` crudo, que mezcla pesos con dólares: la "posición
  // principal" de Reportes era AL30 (4,7 millones de PESOS) y en el Dashboard BTC.
  const valorUsd = (p) => computeBrokerValue([p], PRICES, BROKERS.find(b => b.name === p.broker),
    _DEMO_TC_MEP, _DEMO_TC_MEP, _DEMO_TC_CRIPTO, 'purchase').value
  const topHoldings = nonCashPositions
    .map(p => ({ asset: p.asset, broker: p.broker, invested: p.invested || 0, valor: valorUsd(p) }))
    .sort((a, b) => b.valor - a.valor)
    .slice(0, 3)
    .map(({ valor, ...h }) => h)

  return {
    latest_value: nowVal,
    latest_date: hoyISO(),
    cum_deposited: cumDeposited,
    positions_count: nonCashPositions.length || 12,
    brokers_count: 3,
    // Las fotos del demo ahora son diarias: el día sale de la serie, igual que
    // la semana y el mes (antes era un número sintético porque eran semanales).
    delta_1d: delta(1),
    delta_7d: delta(7),
    delta_30d: delta(30),
    ytd,
    last_op: lastOp,
    top_holdings: topHoldings,
    cash_value: 0,
  }
}

function _emptyDemoPeriod(periodType, periodKey, label) {
  return {
    period_type: periodType,
    period_key: periodKey,
    period_label: label,
    period_start: periodKey,
    period_end: periodKey,
    is_current: false,
    is_relevant: false,
    metrics: {
      start_value: 0, end_value: 0, delta_usd: 0, delta_pct: 0,
      realized_pnl: 0, unrealized_pnl: 0, deposits: 0, withdrawals: 0,
      trades_count: 0, win_rate: null, vs_sp500_pct: null, vs_inflation_pct: null,
    },
    headline: 'Sin actividad.',
    subheadline: null, narrative: null,
    highlights: [], insights: [], children: [],
  }
}

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
      one_liner: 'Tu cartera rota 1.1× por año. Estás en el rango del inversor a mediano plazo.',
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
      one_liner: 'Top 1 = 28%, Top 3 = 62%. La cartera depende mucho de pocos activos.',
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
      title: 'Tech pesa fuerte en tu cartera',
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
      subtitle: `Tu rendimiento de ${year}`,
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
    tldr: 'El {{ANIO}} del año descansa sobre dos motores asimétricos — NVDA por peso y INTC por un único trade excepcional. La diversificación nominal de la cartera es mayor que su diversificación efectiva de fuentes de rendimiento.',
    sections: [
      { title: 'Dinámica del período', tone: 'neutral', body: 'El valor total se ubica en {{VALOR}} sobre un capital aportado neto de {{APORTADO}}. La diferencia (~{{GANANCIA}}) es ganancia real, no efecto de los aportes. La curva del período no muestra picos extremos: el resultado se construye sobre un puñado de movimientos persistentes más que sobre un evento puntual.' },
      { title: 'Factores que lo explican', tone: 'positive', body: 'NVDA con ~{{NVDA}} de peso y {{NVDA_PNL}} de P&L acumulado es uno de los motores de la cartera, mientras INTC aporta el +148% cerrado más rentable del año. La combinación es típica de portfolios que llegan a outperform sin batir al SPY: una posición core grande y un trade táctico excepcional, con el resto siguiendo de cerca al benchmark.' },
      { title: 'Lectura comparativa', tone: 'neutral', body: 'El TWR queda algunos puntos debajo del S&P 500 acumulado del período. Le gana a la inflación AR con margen, lo cual es coherente con una cartera con exposure mayoritario USD. Sobre el benchmark dominante, el cash drag y la inversión parcial en panel local explican la mayor parte del gap.' },
      { title: 'Riesgo asimétrico actual', tone: 'warning', body: 'Si NVDA corrigiera un 25 %, la cartera perdería alrededor de {{NVDA_25}} puntos. El sesgo de disposition effect (medio) agrega tensión: la tentación a cerrar ganadoras en corrección choca con la lógica del trade core. Tener pre-definido el umbral de rebalance vale más que cualquier decisión en caliente.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La diversificación que el HHI sugiere se diluye cuando uno mira las fuentes del rendimiento, no las del capital. Más del 60% del P&L viene de dos tickers — el resto de la cartera funciona casi como un buy-and-hold con beta menor. La pregunta operativa no es qué comprar, sino bajo qué condición concreta reducir la exposure dominante.' },
    ],
    follow_ups: ['¿Cuánto pierdo si NVDA cae 25%?'],
  },
  'dashboard.composition': {
    tldr: 'El HHI sugiere concentración moderada, pero la lectura por fuente de rendimiento es más concentrada — NVDA pesa {{NVDA}} del capital y explica una porción mayor del P&L del período.',
    sections: [
      { title: 'Reparto del capital', tone: 'neutral', body: 'Los top 5 holdings acumulan aproximadamente 65% del portfolio, con NVDA, AAPL y MSFT al frente. La distribución por moneda queda partida en mayoría USD vía Schwab más una porción material en CEDEARs (Cocos), que económicamente también es exposure US.' },
      { title: 'Concentración real vs nominal', tone: 'warning', body: 'El HHI en zona media-alta capta la dispersión por activo, pero subestima la concentración por factor. Si NVDA, AAPL y MSFT comparten sensibilidad al ciclo tecnológico y a tasas, la diversificación efectiva es menor que la nominal. En una corrección growth, los tres se mueven en la misma dirección.' },
      { title: 'Cash y reserva táctica', tone: 'neutral', body: 'El cash es bajo en el ratio principal del Dashboard pero alto si se suman los USDT/ARS de cuentas de tránsito — esa diferencia importa porque la primera lectura sugiere capital trabajando y la segunda revela parking material. Diferenciar reserva táctica de cash drag estructural cambia la lectura del riesgo.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La regla útil para esta cartera no es bajar concentración por concentración, sino fijar un umbral de rebalance pre-acordado: por ejemplo, recortar si una posición supera el 30% o si los tres tickers tech combinados pasan el 60% del valor. Eso convierte una decisión emocional en una mecánica.' },
    ],
    follow_ups: ['¿A qué umbral conviene rebalancear NVDA?'],
  },
  'dashboard.evolution': {
    tldr: 'La curva del período es sostenida con dispersión mensual baja — sugiere demanda estructural más que un rally puntual. El peor drawdown se ubica dentro del rango histórico previo y se recuperó dentro de las 3-4 semanas habituales para esta cartera.',
    sections: [
      { title: 'Forma de la curva', tone: 'positive', body: 'La progresión es sostenida con pocos quiebres abruptos. Esa forma es típica de portfolios donde el rendimiento viene de varias posiciones aportando en paralelo, más que de un evento concentrado en un trimestre.' },
      { title: 'Drawdown vs histórico', tone: 'neutral', body: 'El peor retroceso del período se mantuvo dentro del rango habitual de esta cartera y duró 2-3 semanas hasta recuperar el peak. El drawdown actual es de magnitud menor — más cerca de "ruido normal" que de un cambio de régimen.' },
      { title: 'Dispersión mensual', tone: 'neutral', body: 'La brecha entre el mejor y peor mes ronda los 10pp — moderada para una cartera con exposure tech alto. Una dispersión más estrecha sugeriría un portfolio más defensivo; una más amplia indicaría dependencia de pocos meses excepcionales.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Curvas sostenidas como ésta son más replicables que las que dependen de uno o dos meses extraordinarios. La métrica útil a monitorear es la varianza mensual, no solo el TWR acumulado — si esa varianza crece sin que cambie la composición, suele anticipar un cambio en el comportamiento del mercado más que del portfolio.' },
    ],
    follow_ups: ['¿Cuánto duraron los drawdowns anteriores hasta recuperar?'],
  },
  'dashboard.top_holdings': {
    tldr: 'Las dos posiciones que dominan el resultado lo hacen por razones distintas — NVDA por peso ({{NVDA}} × {{NVDA_PNL}}) e INTC por un cierre excepcional (+148 %). Sin esos dos vehículos, la cartera se acerca al comportamiento de un buy-and-hold pasivo.',
    sections: [
      { title: 'Ganadoras por peso', tone: 'positive', body: 'NVDA combina weight alto y P&L positivo — esa combinación es la que más mueve el resultado anual. AAPL aporta segundo con +18% pero con weight menor, por lo que su impacto en el TWR es proporcionalmente más chico.' },
      { title: 'Ganadora por trade', tone: 'positive', body: 'INTC cerró +148% — un outlier que infla el P&L realizado del año. Si se excluyera ese trade, la expectancy promedio del sistema cae a un nivel mucho más cercano al break-even.' },
      { title: 'Perdedoras con holding largo', tone: 'warning', body: 'AAVE/USDT (-12%) y NFLX flat acumulan varios meses en la cartera sin que aparezca una tesis explícita de reversión. El patrón de mantener perdedoras chicas con horizonte indefinido es una de las firmas más caras a largo plazo, según los detectores de Comportamiento.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La pregunta útil para revisar este top 8 no es "¿vendo NVDA?" sino "¿qué define que una perdedora siga siendo válida o deba salir?". Las ganadoras grandes se gestionan con criterio de rebalance; las perdedoras chicas, con criterio de salida pre-establecido. Hoy ambos están implícitos — explicitarlos cambia el frame de la decisión.' },
    ],
    follow_ups: ['¿Cuánto tiempo es razonable mantener AAVE/USDT sin revisar la tesis?'],
  },
  'dashboard.brokers': {
    tldr: 'La cartera vive en tres custodios con función distinta — Schwab para US directo, Cocos para CEDEARs y panel AR, Binance para crypto. La asignación parece equilibrada pero esconde una concentración funcional: el alpha del año vive casi entero en uno solo.',
    sections: [
      { title: 'Distribución y función', tone: 'neutral', body: 'Schwab concentra el grueso del valor con acciones US directas, Cocos un tercio entre CEDEARs y panel local, Binance el resto en crypto/USDT. Cada broker cubre una función económica distinta, lo cual reduce solapamiento y simplifica la operación.' },
      { title: 'Performance diferencial', tone: 'positive', body: 'Schwab lidera en P&L absoluto del año, impulsado por NVDA, AAPL e INTC. Cocos aporta sin grandes picos. Binance contribuye principalmente vía BTC, con AAVE/USDT como contrapeso negativo. El alpha del período vive mayoritariamente en Schwab — los otros dos brokers se mueven cerca de un comportamiento pasivo.' },
      { title: 'Riesgo operacional', tone: 'neutral', body: 'Tres custodios reducen el riesgo de plataforma frente a tener todo en una sola cuenta — la continuidad del portfolio no depende de un solo proveedor. Sumar un cuarto broker agregaría complejidad operativa sin reducir materialmente el riesgo por debajo del nivel actual.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Tener brokers segmentados por función ayuda a la operación pero también facilita un sesgo común: medir cada cuenta por separado y perder de vista la consolidación. Una mejora mecánica simple es revisar el TWR conjunto con la misma frecuencia que cada cuenta individual — el portfolio que importa para la decisión es el agregado, no el broker.' },
    ],
    follow_ups: ['¿Qué porción del alpha viene de Schwab vs los demás?'],
  },
  'dashboard.upcoming_events': {
    tldr: 'La ventana próxima concentra eventos sobre las posiciones de mayor peso — el riesgo idiosincrático del portfolio para los siguientes días depende de un puñado de reportes, no del mercado.',
    sections: [
      { title: 'Eventos en la ventana', tone: 'neutral', body: 'Earnings de NVDA y AAPL coinciden en la misma semana; dividendos de KO programados también en el período. Tres eventos materiales en 14 días.' },
      { title: 'Concentración de exposure', tone: 'warning', body: 'El earnings de NVDA toca una posición que pesa cerca del {{NVDA}} de la cartera. Sumado al de AAPL, lo expuesto a un reporte ronda el {{NVDA_AAPL}}. Un movimiento típico post-earnings de ±8 % en NVDA puede mover la cartera {{NVDA_8}} puntos en una sola sesión.' },
      { title: 'Comportamiento típico', tone: 'neutral', body: 'La reacción del precio a un beat o miss de earnings tiene baja correlación con la calidad real del reporte — la sorpresa relativa al consenso pesa más que los números absolutos. No es un evento sobre el cual el inversor individual tenga edge informacional.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La utilidad operativa del calendario de earnings no es decidir qué hacer ese día — es decidir, antes del evento, hasta qué movimiento adverso se está dispuesto a tolerar sin tocar la posición. Definir ese umbral ex-ante evita reacciones post-fact que la literatura muestra como sub-óptimas en promedio.' },
    ],
    follow_ups: ['¿Cuál es el movimiento promedio post-earnings de NVDA?'],
  },
  behavioral: {
    tldr: 'El perfil combina disciplina sistémica (turnover bajo, sin averaging-down) con un sesgo dominante de gestión asimétrica de ganadoras vs perdedoras. Esa combinación protege contra los errores caros pero deja sobre la mesa el upside de cortar perdedoras antes.',
    sections: [
      { title: 'Patrón dominante', tone: 'warning', body: 'Las perdedoras acumulan holding period casi al doble de las ganadoras. El gesto repetido de cerrar verdes rápido (INTC, KO) y mantener rojos esperando recuperación (AAVE/USDT, NFLX) es la firma del disposition effect. En portfolios diversificados ese costo no se ve en una métrica única — aparece como un drag silencioso en la expectancy a largo plazo.' },
      { title: 'Disciplina que se está manteniendo', tone: 'positive', body: 'Turnover anual de 1x ubica al portfolio en territorio de inversor a mediano plazo — fuera de la zona donde fricciones de costo erosionan resultado. Ausencia de averaging-down agresivo sobre activos en caída sugiere que no se rompe la regla de "no doblar la apuesta sin nueva tesis". Esa disciplina es difícil de mantener y vale más que cualquier trade individual del año.' },
      { title: 'Lectura combinada de sesgos', tone: 'neutral', body: 'Concentración media-alta + home_bias moderado + disposition effect arman una asimetría específica: la cartera funciona bien cuando NVDA y el sector tech acompañan, pero el sesgo de gestión amplifica drawdowns porque la tentación de cerrar es mayor en las posiciones grandes. La concentración no es problema aislado — es problema porque interactúa con el sesgo dominante.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El cambio de proceso de mayor leverage no es psicológico sino procedural: definir el criterio de salida ANTES de la entrada, no después. Esa regla aparentemente trivial es la que desarma el disposition effect — saca la decisión del momento de tensión y la convierte en una verificación contra un umbral pre-acordado. No es operativa, es estructural.' },
    ],
    follow_ups: ['¿Cuánto cuesta el disposition effect anualizado en esta cartera?'],
  },
  'profile.summary': {
    tldr: 'Tu perfil declarado (Moderado, con la mira en libertad financiera a largo plazo) y tu conducta real casi coinciden — pero no donde creés. La tensión no es el estilo: es la concentración cruzada con un horizonte declarado en meses.',
    sections: [
      { title: 'Estilo declarado vs. real', tone: 'positive', body: 'Marcaste un perfil "mixto", pero en los hechos operás poco más de una vez por mes: sos buy-and-hold. Para una cartera con 33% en cripto, esa mano quieta es hoy lo que más te ordena — no es un problema, juega a tu favor.' },
      { title: 'Concentración contra horizonte', tone: 'warning', body: 'Tus 3 mayores tenencias son el 44% del total y un tercio está en alternativos (cripto). Contra un horizonte que declaraste en "meses", esa combinación es de cartera de plazo largo. Es tu mayor exposición real, sobre todo si de verdad pensás necesitar esta plata pronto.' },
      { title: 'Lo declarado que sí cierra', tone: 'neutral', body: 'Dijiste que no necesitás esta plata en los próximos 12-24 meses, y eso es coherente con bancarte la volatilidad de cripto. Si el plan es genuinamente largo, la composición está OK. Si el "meses" fue una respuesta por defecto del test, vale la pena revisar esa contradicción antes que cualquier compra nueva.' },
    ],
    follow_ups: [],
  },
  'insights.summary': {
    tldr: 'Le ganás a la inflación (+6%) y al plazo fijo, pero el diagnóstico marca dos cosas que van juntas: NVDA concentra tu resultado y tenés casi la mitad en cash sin desplegar.',
    sections: [
      { title: 'Concentración de resultado', tone: 'warning', body: 'NVDA es tu mayor posición y explica buena parte de lo que ganaste. No es un problema mientras acompañe — pero tu resultado hoy depende más de un solo activo que de la cartera entera. Una corrección del Nasdaq se siente fuerte acá.' },
      { title: 'Cash sin desplegar', tone: 'neutral', body: 'El efectivo es el {{CASH}} de la cartera (dólares, USDT y pesos): un colchón chico que no frena el rendimiento. La pregunta útil no es cuánto cash desplegar, sino qué hacer con la próxima entrada de plata.' },
      { title: 'Lo que sí funciona', tone: 'positive', body: 'Contra las alternativas locales vas bien: le ganás a la inflación y al plazo fijo, y tu operativa es tranquila (pocos trades). Esa mano quieta, con tanta cripto y tech, es hoy lo que más te ordena.' },
    ],
    follow_ups: [],
  },
  insights: {
    tldr: 'El +14% TWR del año descansa sobre dos motores asimétricos (NVDA por peso, INTC por trade único). Le gana a la inflación AR con margen pero queda algunos puntos debajo del SPY — combinación coherente con un portfolio con cash drag y exposure parcial al panel local.',
    sections: [
      { title: 'Performance neta', tone: 'positive', body: 'TWR compoundeado de ~14% sobre los últimos 12 meses con un win rate del 56% en trades cerrados. El payoff 7x sugiere asimetría favorable: pocas ganadoras grandes pagan varias perdedoras chicas. El drawdown máximo del período (~-8%) está dentro del rango habitual para portfolios con exposure tech alto.' },
      { title: 'Origen del resultado', tone: 'neutral', body: 'Del P&L total combinado (realized + unrealized), NVDA aporta más del 55% solo. INTC suma vía el trade cerrado más rentable del año (+148%). Sin esos dos, el rendimiento se acerca al comportamiento de un buy-and-hold del SPY menos el cash drag. Detractores (AAVE/USDT, NFLX) son chicos en magnitud frente a las ganadoras.' },
      { title: 'Lectura comparativa', tone: 'neutral', body: 'vs SPY queda un par de puntos debajo — gap consistente con la combinación de cash material y exposure AR sin alpha relativo del año. vs inflación AR, el margen es claro: el portfolio defendió y aumentó poder de compra en moneda local. vs dólar blue, depende del mix de monedas — para la parte USD del portfolio el blue es referencia tangencial.' },
      { title: 'Riesgo y exposure', tone: 'warning', body: 'La exposición se reparte ~{{SCHWAB}} en acciones y ETFs de EE.UU., ~{{CRIPTO}} en cripto, ~{{AR}} en Argentina y ~{{CASH}} en efectivo. La cripto es la parte más volátil. La concentración en NVDA ({{NVDA}}) amplifica las caídas en correcciones del Nasdaq.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El portfolio supera a la inflación pero queda detrás del SPY — ese resultado es característico de carteras donde el alpha de stock-picking se ve neutralizado por el cash drag. La decisión estratégica relevante no es qué activo agregar sino bajo qué condición el cash actual se convierte en posición — fijar un umbral o calendario de despliegue elimina la fricción mensual de "todavía no".' },
    ],
    follow_ups: ['¿Cuánto cuesta el cash drag anualizado en esta cartera?'],
  },
  'insights.evolution': {
    tldr: 'La trayectoria mensual muestra dispersión moderada con consistencia del 50-65% — el TWR positivo del período viene de varios meses aportando en paralelo, no de uno o dos extraordinarios. La replicabilidad de este resultado es mayor que la de portfolios con curva más volátil.',
    sections: [
      { title: 'Forma de la curva', tone: 'positive', body: 'Progresión sostenida con pocos quiebres. La cantidad de meses positivos sobre el total sugiere disciplina más que suerte: cuando un portfolio gana en más del 60% de los meses, el TWR acumulado tiende a sostenerse incluso si los meses extraordinarios desaparecen.' },
      { title: 'Dispersión interna', tone: 'neutral', body: 'El gap entre el mejor mes (~+6%) y el peor (~-4%) ronda los 10pp — moderado para una cartera con exposure tech material. Una dispersión más estrecha indicaría un portfolio defensivo; una más amplia, dependencia de pocos meses outlier.' },
      { title: 'Lectura comparativa', tone: 'neutral', body: 'El mejor mes coincide con períodos de fuerza relativa del Nasdaq según el contexto del packet. El peor mes está dentro del rango histórico del propio portfolio — no representa un cambio de régimen sino ruido normal. La asimetría entre ambos no sugiere ni euforia ni capitulación.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Lo que sostiene este tipo de curva no es la estrategia del último mes sino la combinación de turnover bajo y disciplina de no mover el portfolio en cada corrección. La métrica que importa monitorear es la varianza mensual, no solo el TWR acumulado: si la varianza crece sin que cambie la composición, suele anticipar un cambio en el comportamiento del mercado más que del portfolio.' },
    ],
    follow_ups: ['¿La dispersión mensual sigue una tendencia creciente?'],
  },
  'insights.drawdown': {
    tldr: 'El peor drawdown del período se mantiene dentro del rango histórico habitual de la cartera. El actual es de magnitud menor — más cerca del ruido normal que de un cambio de régimen.',
    sections: [
      { title: 'Profundidad histórica', tone: 'positive', body: 'El peor retroceso de los últimos 12 meses fue de alrededor de {{DD}}, dentro de lo esperable para una cartera con {{CRIPTO}} en cripto. El S&P 500 mismo tuvo correcciones de magnitud similar en ventanas comparables — el portfolio no exhibió volatilidad excepcional respecto del benchmark relevante.' },
      { title: 'Eventos de DD', tone: 'neutral', body: 'Los dos eventos de drawdown más profundos del período duraron 2-3 semanas hasta recuperar el peak previo. Ninguno se extendió más allá de un mes, lo que sugiere que los gatillos fueron movimientos de mercado de corta duración, no deterioros estructurales del portfolio.' },
      { title: 'Estado actual', tone: 'positive', body: 'El drawdown actual está cerca de cero — el portfolio se mueve en la franja de los máximos históricos. La distancia al peak es pequeña, lo cual no implica que no pueda profundizar; solo describe que hoy no hay daño material acumulado desde el último high.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El patrón "drawdown chico y recuperación rápida" del período no es atributo permanente del portfolio — depende de que la exposure y el comportamiento de los activos sostengan ese ritmo. Una mejora útil al proceso es registrar el time-to-recover de cada DD: cuando ese tiempo se alarga, suele ser una señal anticipada de cambio en el régimen del portfolio, anterior al cambio en el TWR.' },
    ],
    follow_ups: ['¿Cuánto fue el time-to-recover del peor drawdown histórico?'],
  },
  'insights.attribution': {
    tldr: 'Más del 50% del P&L total proviene de una sola posición — la diversificación nominal del portfolio se diluye cuando se mira la fuente real del rendimiento. La concentración de fuente es el factor más asimétrico del año.',
    sections: [
      { title: 'Atribución por posición', tone: 'positive', body: 'NVDA explica más de la mitad del P&L combinado (realized + unrealized). INTC aporta el segundo bloque vía un trade cerrado al +148%. BTC en tercer lugar con magnitud menor. El resto de las posiciones contribuye marginalmente respecto de las top 3.' },
      { title: 'Realized vs unrealized', tone: 'neutral', body: 'El P&L está repartido entre realized (cosecha asegurada) y unrealized (apuesta abierta) en proporciones que merecen atención: la parte unrealized depende íntegramente del comportamiento futuro de las posiciones grandes, mientras la parte realized ya está consolidada. Tratar ambas como equivalentes para tomar decisiones distorsiona el riesgo real.' },
      { title: 'Detractores', tone: 'neutral', body: 'AAVE/USDT y NFLX son los principales lastres del año pero su magnitud no neutraliza materialmente a las ganadoras. La pregunta práctica no es si compensan o no, sino qué patrón de proceso permite que se mantengan tanto tiempo sin reconciliación con la tesis original.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Una posición que aporta más de la mitad del rendimiento anual exige un umbral de rebalance explícito — no para reducirla por reflexivo, sino para evitar que la decisión llegue en el momento de tensión (caída del activo o cambio macro). Pre-definir "qué condición concreta dispara revisar la posición" convierte una decisión emocional en una mecánica medible.' },
    ],
    follow_ups: ['¿Cuánto bajaría el TWR sin la posición top 1?'],
  },
  monthly: {
    tldr: 'El mes cerró con dos motores asimétricos: un trade táctico de tamaño grande explica buena parte del P&L mientras el resto de la cartera siguió cerca del benchmark mensual.',
    sections: [
      { title: 'Resultado del mes', tone: 'positive', body: 'El TWRR del mes fue positivo con varios trades cerrados arriba de promedio. El delta absoluto sobre el capital inicial confirma que el resultado vino de movimientos de mercado, no de flujos.' },
      { title: 'Factores probables', tone: 'neutral', body: 'El mejor trade del mes concentra una porción importante del P&L — sin esa contribución, el portfolio se hubiera movido cerca del benchmark mensual. El resto de las posiciones aportaron de forma pareja.' },
      { title: 'Lectura comparativa', tone: 'neutral', body: 'El delta vs S&P 500 del mes está dentro del rango típico. La cartera mostró menos dispersión que el promedio del año, lo cual es coherente con un mes sin shocks idiosincráticos materiales.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Un mes con resultado positivo concentrado en un solo trade es un patrón a registrar — la pregunta de proceso es si esa contribución refleja una decisión replicable o un timing puntual. Documentar el caso permite reconocer condiciones similares cuando vuelvan.' },
    ],
    follow_ups: ['¿Qué mes histórico se parece más a éste?'],
  },
  'monthly.insight': {
    tldr: 'El insight detectado captura una concentración material del resultado del mes en pocas posiciones — un patrón que distingue meses replicables de meses con dependencia de un trade puntual.',
    sections: [
      { title: 'Dinámica observada', tone: 'neutral', body: 'La señal del chip indica que un activo único explica una porción mayoritaria del P&L del mes. Es una observación descriptiva: no implica habilidad ni suerte por sí sola.' },
      { title: 'Lectura interpretativa', tone: 'warning', body: 'Cuando un mes positivo descansa sobre un solo nombre, la replicabilidad del resultado depende de seguir encontrando situaciones similares. La métrica útil a registrar es si esto se repite a lo largo de varios meses o aparece esporádicamente.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El cambio de proceso de mayor leverage no es rebalancear ahora — es definir un umbral pre-acordado de revisión por concentración del P&L mensual. Eso convierte una observación recurrente en un disparador objetivo, no en una decisión que se toma "cuando se siente".' },
    ],
    follow_ups: ['¿Este patrón se repite en otros meses?'],
  },
  position: {
    tldr: 'La posición concentra una porción significativa del portfolio total con un P&L positivo, pero su peso actual también define una asimetría de riesgo concreta — un movimiento adverso del activo impacta el TWR del agregado más de lo que sugiere su contribución promedio histórica.',
    sections: [
      { title: 'Dinámica de la posición', tone: 'positive', body: 'El P&L actual es positivo en términos absolutos y relativos. El holding period sugiere que la posición es de mediano plazo, no especulativa — la valuación actual incorpora múltiples meses de movimiento.' },
      { title: 'Peso vs portfolio', tone: 'warning', body: 'La posición pesa por encima del 10% del valor total. Esa magnitud convierte un movimiento del 25% en el activo en un movimiento de 2.5pp del TWR del portfolio — material respecto del drawdown histórico habitual.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Lo útil acá no es cerrar la posición sino pre-definir el umbral en que su peso justifica un rebalance. Cuando la decisión se toma con regla objetiva (ej. recortar si supera X% del portfolio) en lugar de en respuesta a un evento adverso, los rendimientos esperados a largo plazo mejoran.' },
    ],
    follow_ups: ['¿Qué umbral de weight conviene para rebalance?'],
  },
  'position.chart': {
    tldr: 'El movimiento reciente del precio sugiere que la posición ya capturó la parte más rápida del recorrido — desde el peak el activo se mueve dentro de un rango más estrecho con dispersión menor que la histórica reciente.',
    sections: [
      { title: 'Trayectoria reciente', tone: 'neutral', body: 'El precio actual se ubica cerca del avg de compra. La serie de 30 días no muestra movimientos extremos en ningún lado — sugiere que la tesis original ya se materializó en parte, ahora la posición vive de optimismo residual o nueva información que aún no aparece en el chart.' },
      { title: 'Volatilidad y drawdown reciente', tone: 'neutral', body: 'El drawdown reciente respecto del peak del período mostrado está controlado. Para un activo con la beta histórica de esta posición, el rango actual es estrecho — período de consolidación más que de tendencia.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El chart no respalda ni invalida la tesis — solo describe que el movimiento esperado ya ocurrió y la información ahora viene por fuera del precio. Para decisiones futuras vale revisar fundamentales (próximos earnings, cambio de momentum sectorial) más que el chart mismo.' },
    ],
    follow_ups: ['¿La volatilidad reciente está dentro del rango histórico?'],
  },
  'position.lots': {
    tldr: 'El historial muestra varias compras a precios crecientes — un patrón de averaging up que es coherente con momentum-following. El avg refleja entradas progresivas, no una compra única dominante.',
    sections: [
      { title: 'Patrón de compras', tone: 'neutral', body: 'La secuencia de operaciones registra varias entradas en momentos distintos, con precios crecientes en mayor proporción. Eso es consistente con un patrón de seguir momentum, no con apostar a reversiones.' },
      { title: 'Estructura del avg', tone: 'neutral', body: 'El precio promedio actual está más cerca de las últimas compras que de la primera — el peso del avg lo definen las entradas tardías. Eso implica que el cushion de tolerancia ante una corrección es menor que el que sugiere el P&L absoluto.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Averaging up funciona en mercados con tendencia clara y se vuelve costoso en mercados laterales o de reversión. La regla útil para este patrón es pre-definir el criterio para dejar de promediar al alza: si el activo cruza X múltiplo del avg, dejar de agregar y considerar el rebalance.' },
    ],
    follow_ups: ['¿Cuál fue el lote más rentable hasta ahora?'],
  },
  operations: {
    tldr: 'El sistema descansa sobre asimetría favorable — pocas ganadoras grandes pagan varias perdedoras chicas. Pero un par de trades excepcionales infla el payoff promedio: si se excluyen, la expectancy se acerca al break-even.',
    sections: [
      { title: 'Estadísticas del sistema', tone: 'positive', body: 'Win rate moderado con payoff ratio elevado configuran un sistema de trend-following clásico — pocos aciertos grandes superan en magnitud a varios fallos chicos. La expectancy es positiva sostenida sobre la muestra histórica.' },
      { title: 'Lo que esconde el promedio', tone: 'warning', body: 'El avg_win está inflado por un par de trades excepcionales. Si se excluye el outlier histórico, el payoff cae a un nivel más cercano a 2-3x — todavía favorable, pero materialmente distinto. La métrica robusta para evaluar el sistema es la mediana del P&L, no el promedio.' },
      { title: 'Concentración por ticker', tone: 'neutral', body: 'Los top 3 tickers más operados acumulan la mayoría de los trades del historial. Esa concentración indica un universo de trading reducido — el sistema vive de operar pocos nombres conocidos en profundidad, no de explorar muchos activos en superficial.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La pregunta útil sobre este sistema no es si va a seguir funcionando, sino qué condiciones del mercado fueron las que posibilitaron los trades excepcionales. Si esas condiciones se repiten poco (ej. correcciones fuertes seguidas de rebotes), el sistema depende de un régimen específico — válido reconocerlo y registrar cuándo se da.' },
    ],
    follow_ups: ['¿Cuál es la expectancy sin los outliers?'],
  },
  'operations.trade': {
    tldr: 'Este trade vale varias veces el avg_win del sistema — fue el aporte más grande del año. Identificar qué condiciones lo posibilitaron es lo más útil del análisis: cómo se construyó el setup, no si va a repetirse.',
    sections: [
      { title: 'Magnitud relativa', tone: 'positive', body: 'El P&L de la operación supera por mucho al avg_win histórico. Esa diferencia ubica al trade como un outlier estadístico del propio sistema — no es una ejecución típica sino una excepción.' },
      { title: 'Ranking en el año', tone: 'neutral', body: 'Es el trade de mayor P&L del año. Una contribución de esta magnitud define la temporada — sin esta operación, el resultado del año se acercaría al benchmark. La replicabilidad de un trade así no se debería asumir.' },
      { title: 'Holding period', tone: 'neutral', body: 'El tiempo de la posición es de mediano plazo — ni intraday ni multi-año. Esa ventana es la típica de las ganadoras grandes en sistemas de trend-following: hay tiempo para que la tesis se desarrolle pero no se mantiene a través de varios ciclos.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Documentar qué fue diferente en este trade (tamaño, timing, conviction, contexto sectorial) es más valioso que el P&L. Sin ese ejercicio, el outlier queda como suerte no transferible. Con el ejercicio, se convierte en una entrada del checklist para reconocer setups similares.' },
    ],
    follow_ups: ['¿Hubo otros trades del mismo ticker?'],
  },
  reports: {
    tldr: 'El año cierra con TWR positivo pero la mayor parte del rendimiento se concentra en uno o dos meses excepcionales — la consistency mensual es media, lo cual hace al resultado menos replicable que un año con curva pareja.',
    sections: [
      { title: 'TWR del año', tone: 'positive', body: 'El portfolio acumula un rendimiento positivo sobre los meses activos del año. Eso describe el resultado bruto, pero no dice cuán pareja fue la curva — la métrica clave para evaluar replicabilidad no es el TWR final sino la dispersión mensual.' },
      { title: 'Win rate mensual', tone: 'neutral', body: 'El % de meses positivos se ubica cerca del 50%. Eso significa que tantos meses negativos como positivos contribuyeron al resultado — el TWR positivo se sostiene porque los meses ganadores fueron de mayor magnitud que los perdedores. Esa asimetría es la firma típica de portfolios con concentración alta en pocos activos volátiles.' },
      { title: 'Mejor vs peor mes', tone: 'neutral', body: 'La brecha entre mejor y peor mes es amplia. Una dispersión así sugiere que el portfolio responde con fuerza al ciclo del activo dominante. Para perfiles que buscan menos volatilidad, suavizar esa brecha requiere bajar concentración o agregar exposure no correlacionada.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La métrica útil a monitorear no es el TWR acumulado del año sino la consistencia de la curva. Un año con TWR del 14% concentrado en dos meses tiene replicabilidad menor que uno con TWR del 10% distribuido en seis meses positivos. Para evaluar el sistema, ignoré el resultado y mirá la varianza mensual.' },
    ],
    follow_ups: ['¿Qué mes contribuyó más al TWR del año?'],
  },
  home: {
    tldr: 'El día abre con mercado mixto y el portfolio se mueve cerca de cero — buena ventana para revisar tesis sin presión de evento. La semana próxima concentra varios reportes sobre posiciones grandes.',
    sections: [
      { title: 'Estado del día', tone: 'neutral', body: 'Los índices abren mixtos: algunos verdes, otros rojos. La sesión no muestra un tema dominante y el portfolio se mueve dentro del rango habitual de un día sin shocks materiales.' },
      { title: 'Vinculación con la cartera', tone: 'neutral', body: 'El portfolio acompaña el rango del mercado del día. Cuando el delta del portfolio se desvía mucho del delta del mercado, esa divergencia suele venir de sectores específicos — hoy no es ese caso.' },
      { title: 'Riesgo de la semana', tone: 'warning', body: 'En los próximos 14 días aparecen earnings sobre posiciones que combinadas representan ~40% del valor del portfolio. La semana del reporte puede mover el TWR diario más de lo usual.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Días sin volatilidad son los más útiles para revisar criterio sin reaccionar al precio. Hoy es ese tipo de día — vale verificar si los umbrales de rebalance están bien calibrados antes de que llegue una sesión con noticias.' },
    ],
    follow_ups: ['¿Qué tan correlacionado está mi portfolio con el SPY?'],
  },
  news: {
    tldr: 'El feed de noticias del período concentra la mayor parte de su volumen en pocos tickers — un patrón que refleja que los temas del momento tocan posiciones específicas de la cartera, no el portfolio entero.',
    sections: [
      { title: 'Distribución de cobertura', tone: 'neutral', body: 'En el período cubierto, una parte significativa de las noticias menciona los mismos 2-3 tickers. Eso significa que las posiciones grandes están en el radar del mercado — el ruido informativo es proporcional al peso, no al diversificado nominal.' },
      { title: 'Temas dominantes', tone: 'neutral', body: 'Los tags más frecuentes apuntan a earnings + movimientos sectoriales. Es un período donde el calendario de reportes domina sobre las noticias macro — eso es normal en semanas de reporting season.' },
      { title: 'Tickers silent', tone: 'neutral', body: 'Varias posiciones del portfolio NO aparecen en las noticias del período. Esa ausencia no es positiva ni negativa por sí sola, pero vale registrar si esas posiciones siguen siendo decisión activa o se volvieron defaults.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Cuando el ruido informativo se concentra en pocas posiciones, las decisiones suelen sesgarse hacia esos tickers — el feed crea agenda. Mantener un registro de "qué decidiste sin noticias" es una métrica simple pero útil para chequear si la toma de decisión responde a la tesis o al volumen de cobertura del día.' },
    ],
    follow_ups: ['¿Qué ticker concentra más cobertura este período?'],
  },
  'news.item': {
    tldr: 'La noticia toca una posición material del portfolio — vale leerla con criterio. Lo importante no es la noticia en sí, sino qué (si es que algo) cambia en la tesis original de la posición.',
    sections: [
      { title: 'Relevancia para tu cartera', tone: 'warning', body: 'El ticker de la noticia está entre las posiciones grandes del portfolio. Una noticia que mueve la valuación del activo se transmite al TWR del portfolio en proporción al peso — vale prestarle atención.' },
      { title: 'Contexto del activo', tone: 'neutral', body: 'La posición viene con P&L positivo acumulado y un holding de varios meses. La noticia llega sobre un activo que ya cargó parte de la tesis — la reacción del precio post-noticia suele ser menor en activos que ya recorrieron camino.' },
      { title: 'Cobertura sostenida', tone: 'neutral', body: 'El ticker registra varias noticias en los últimos 30 días. Esa continuidad indica que el mercado está re-evaluando el activo — la noticia individual es menos importante que la tendencia agregada de cobertura.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Una noticia rara vez justifica cambiar la posición — lo que sí justifica el cambio es si la noticia modifica la TESIS original. La pregunta práctica es "¿lo que dice esto hace que mi razón para tener la posición ya no aplique?". Si la respuesta es no, la noticia es ruido — útil de leer, no de actuar.' },
    ],
    follow_ups: ['¿Cuántas otras noticias hay del mismo ticker?'],
  },
  events: {
    tldr: 'El calendario concentra la mayoría de los eventos sobre un puñado de posiciones grandes — una semana en particular concentra varios reportes que pueden mover el TWR del portfolio más que el rango diario habitual.',
    sections: [
      { title: 'Composición del calendario', tone: 'neutral', body: 'En la ventana cubierta aparecen earnings, dividendos y algunos eventos macro. El mix es típico de una temporada de reportes: el peso recae en earnings, que es lo que más volatilidad introduce en la cartera.' },
      { title: 'Concentración temporal', tone: 'warning', body: 'Hay una semana con varios eventos simultáneos sobre posiciones que combinadas representan una porción material del portfolio. En esos días, el portfolio puede comportarse de forma menos predecible que el promedio.' },
      { title: 'Cash flow vs market movement', tone: 'neutral', body: 'Los dividendos del calendario generan flujos conocidos. Diferenciar ese cash flow del movimiento de mercado ayuda a leer el TWR con criterio — el portfolio puede subir un día solo por dividendos pagados, sin que el activo haya apreciado.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La utilidad del calendario no es decidir qué hacer en cada evento sino fijar el plan ANTES de que llegue. Pre-definir el umbral de tolerancia a movimientos post-earnings ("si X cae más de Y% sin razón fundamental") evita decisiones tomadas en caliente — los datos académicos muestran que decisiones tomadas en frío rinden mejor que las post-evento.' },
    ],
    follow_ups: ['¿Qué semana concentra más eventos?'],
  },
  'events.item': {
    tldr: 'El evento toca una posición de peso material — el día del reporte el portfolio puede moverse más que el promedio diario habitual. Es contexto a tener presente, no señal de acción.',
    sections: [
      { title: 'Magnitud del impacto', tone: 'warning', body: 'El ticker representa una proporción significativa del portfolio. Un movimiento típico post-earnings del orden del ±8% en ese activo se traduce en 2-3 puntos de TWR del portfolio en una sola sesión.' },
      { title: 'Comportamiento típico', tone: 'neutral', body: 'La reacción del precio a un earnings beat/miss tiene baja correlación con la calidad del reporte — la sorpresa relativa al consenso pesa más que los números absolutos. El inversor individual no tiene edge informacional acá.' },
      { title: 'Posición previa al evento', tone: 'neutral', body: 'La posición viene con P&L positivo. Llega al evento con cushion. Eso no garantiza nada del movimiento del precio el día del reporte, pero baja la presión emocional respecto de llegar al evento con la posición en rojo.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La regla útil para earnings de posiciones grandes no es cerrar antes o esperar — es pre-definir el escenario adverso. Por ejemplo: "si el activo cae más de 15% post-earnings sin que cambien los fundamentales explicados en el reporte, mantengo o promedio". Eso convierte una decisión de reacción en una verificación contra criterio.' },
    ],
    follow_ups: ['¿Cuál fue el movimiento promedio de earnings previos de este ticker?'],
  },
  goal: {
    tldr: 'El objetivo es alcanzable si se sostiene la disciplina de aportes y la tasa de retorno esperada se ubica cerca del CAGR histórico del propio portfolio. Depender solo del rendimiento sin aportes adicionales aleja el horizonte estimado en varios meses.',
    sections: [
      { title: 'Estado del progreso', tone: 'positive', body: 'El capital actual cubre una porción razonable del target. El gap restante es alcanzable con el aporte mensual planeado al retorno esperado configurado — el camino es factible, no garantizado.' },
      { title: 'Sensibilidad a variables', tone: 'neutral', body: 'Si el retorno esperado cae al CAGR histórico real del portfolio (más conservador que el target), el ETA se extiende algunos meses. Si los aportes se suspenden, depende íntegramente del rendimiento y el horizonte se aleja sustancialmente. Los aportes constantes son la variable de mayor leverage.' },
      { title: 'Comparación con escenarios', tone: 'neutral', body: 'El escenario "conservador" (rendimiento del SPY histórico) llega al objetivo más tarde que el plan original. La brecha temporal es el costo implícito de asumir un retorno esperado superior al histórico. Esa brecha vale tenerla presente como margen de error razonable.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La métrica útil a monitorear no es el progreso mes a mes (es ruidoso) sino la trayectoria de 6 meses corrida. Si la curva real se desvía consistentemente del escenario base, el ajuste relevante suele ser revisar el aporte, no el target — el plan más robusto suele ser el que asume un retorno menor y un aporte mayor.' },
    ],
    follow_ups: ['¿Qué pasa si suspendo aportes 6 meses?'],
  },
  'insights.benchmarks': {
    tldr: 'Le ganaste a la inflación AR con margen pero quedaste algunos puntos debajo del SPY — esa combinación es característica de portfolios con cash material y exposure mixto, no de un alpha negativo del stock-picking.',
    sections: [
      { title: 'vs Inflación AR', tone: 'positive', body: 'El TWR (~14% en USD equivalent) supera la inflación AR acumulada del período. En una economía con inflación de dos dígitos, defender y aumentar poder de compra real es el primer objetivo material — esa batalla la cartera la gana con margen.' },
      { title: 'vs S&P 500', tone: 'neutral', body: 'En el año la cartera va {{ANIO}} contra {{SP_ANIO}} del S&P 500 ({{GAP_ANIO}}). Con {{CASH}} en efectivo, el cash no explica la diferencia: la explican la cripto ({{CRIPTO}}) y la parte argentina ({{AR}}), que no siguen al índice.' },
      { title: 'vs Dólar Blue', tone: 'neutral', body: 'Para la parte ARS de la cartera, ganarle al blue significa defender poder adquisitivo en pesos. Para la parte USD, el blue es referencia tangencial — esa porción ya está protegida de devaluación gradual. La métrica solo es material para evaluar el costo de quedarse en pesos vs dolarizar.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La métrica útil acá no es "¿cómo le gano al SPY?" sino "¿qué porción del cash debería estar invertida si quiero achicar el gap?". El gap vs SPY es esencialmente cash drag — desplegarlo de forma escalonada y pre-pactada (no en función del precio diario) suele cerrar la diferencia sin agregar riesgo material.' },
    ],
    follow_ups: ['¿Qué TWR tendría la cartera con 0% de cash drag?'],
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
      { title: 'Interacción con concentración', tone: 'neutral', body: 'El sesgo se vuelve más caro cuando hay una posición core grande: la tentación a cerrar la ganadora en corrección amplifica el efecto. NVDA con {{NVDA}} de peso y el disposition effect activo arman exactamente esa tensión latente.' },
      { title: 'Insight clave', tone: 'neutral', body: 'El cambio de leverage más alto no es psicológico — es procedural. Definir el criterio de salida ANTES de la entrada (stop por precio, por % de portfolio o por cambio en la tesis) saca la decisión del momento de tensión y la convierte en una verificación contra un umbral pre-acordado. Eso desarma el sesgo sin pelearlo en cada operación.' },
    ],
    follow_ups: ['¿Cuántos puntos por año estimás que cuesta este sesgo en mi caso?'],
  },
  overtrade: {
    tldr: 'Turnover anual de 1x ubica al portfolio en territorio de inversor a mediano plazo — fuera de la zona donde fricciones de costo erosionan el resultado. Esa disciplina es difícil de mantener y suele subestimarse como factor de performance.',
    sections: [
      { title: 'Qué dice el dato', tone: 'positive', body: 'Rotás aproximadamente una vez al año el capital. Los detectores académicos identifican overtrading desde 3x anual hacia arriba — niveles donde la suma de comisiones, impuestos sobre realizados y bid-ask spread empieza a comerse un porcentaje material del retorno.' },
      { title: 'Por qué importa', tone: 'neutral', body: 'Cada operación tiene un costo silencioso. Barber & Odean documentaron que portfolios de inversores individuales subperformaban el mercado en proporción directa a su nivel de actividad. El portfolio menos activo tiende a estar más cerca del benchmark — y para la mayoría eso ya es resultado.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Mantener turnover bajo es contraintuitivo porque la operatoria se confunde con "estar trabajando la cartera". El research muestra lo opuesto: el portfolio se beneficia más de la decisión inicial bien tomada que de las decisiones intermedias. La regla útil acá es operar solo cuando hay tesis clara que justifica costo — no cuando "no pasa nada".' },
    ],
    follow_ups: ['¿Qué pasa con la expectancy si subiera el turnover a 3x?'],
  },
  concentration: {
    tldr: 'La concentración nominal (top1 ~18%, top3 ~46%) está en zona moderada — pero la concentración por fuente de rendimiento es mayor. La diversificación de capital no se traduce automáticamente en diversificación de riesgo.',
    sections: [
      { title: 'Lectura del HHI', tone: 'neutral', body: 'El reparto por activo no muestra una posición que domine en términos de capital. Esa lectura aislada sugiere portfolio diversificado. Pero el HHI mide concentración por nombre, no por factor — y el factor importa más cuando las posiciones grandes comparten exposure al mismo ciclo.' },
      { title: 'Concentración encubierta', tone: 'warning', body: 'Si los top 3 holdings son del mismo sector (tech US) o del mismo factor (growth), la diversificación efectiva es menor que la nominal. En una corrección del Nasdaq, los tres se mueven en la misma dirección y la cartera se comporta como si tuviera una sola posición agregada.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La regla útil no es bajar concentración por concentración — es definir un umbral pre-acordado que dispare revisión. Por ejemplo: rebalancear si un activo cruza el 25% del portfolio, o si dos del mismo sector combinados superan el 40%. Eso convierte la decisión emocional ("me siento expuesto") en una mecánica medible.' },
    ],
    follow_ups: ['¿Qué % del riesgo de mercado explica el sector tech?'],
  },
  inflation_loss: {
    tldr: 'Los ~US$ 272 de erosión por inflación AR son una pérdida real que no aparece en el P&L — el cash ARS no se queda quieto en términos de poder adquisitivo. Tratar esa porción como neutral en lugar de inversión inflación-pasiva subestima el costo.',
    sections: [
      { title: 'Qué pasó', tone: 'warning', body: 'Mantener cash en pesos en una economía con inflación de dos dígitos transforma el ARS en una posición default con retorno negativo conocido. La métrica del detector aproxima la pérdida acumulada del período en USD-equivalent: ~US$ 272 que no se ven en una métrica visible pero erosionan capital real.' },
      { title: 'Por qué importa específicamente', tone: 'neutral', body: 'El cash ARS funciona como reserva táctica solo si se usa en un horizonte cercano — para operaciones, gastos o deploy a corto plazo. Si lleva más de algunas semanas quieto, deja de ser reserva y se convierte en costo. Distinguir uno del otro cambia la decisión.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La mejora de mayor leverage no es elegir el mejor instrumento alternativo (Lecaps, MEP, CEDEARs) sino fijar una regla de no-permanencia: cash ARS que no se mueve en X semanas se rota automáticamente al instrumento default elegido. Eso convierte una pérdida pasiva en una decisión estructural única, no una decisión recurrente.' },
    ],
    follow_ups: ['¿Cuánto cuesta anualizado mantener cash ARS sin instrumentar?'],
  },
  winrate_payoff: {
    tldr: 'El win rate del 56% con payoff 7x sugiere un sistema asimétrico saludable, pero la lectura honesta es que el payoff promedio está inflado por un o dos trades excepcionales. Sin esos outliers, la expectancy cae al territorio de break-even.',
    sections: [
      { title: 'Qué dice el dato', tone: 'positive', body: 'Win rate 56% + payoff 7x = expectancy aproximada de +US$ 81 por operación. La asimetría favorable (ganadoras grandes vs perdedoras chicas) es exactamente el patrón que la literatura asocia con disciplina de stop loss y let-winners-run.' },
      { title: 'Lo que esconde el promedio', tone: 'warning', body: 'INTC +148% como trade único distorsiona el avg_win. Si se excluye, el payoff promedio cae sustancialmente y la expectancy se acerca al break-even. La métrica robusta es la mediana, no el promedio — pero el packet trae promedio, lo cual hay que tener en cuenta al interpretar.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Sistemas asimétricos como éste tienen un riesgo específico: confundir suerte sostenida con habilidad sistemática. La validación útil no es si el payoff sigue alto el próximo trade, sino si se mantiene cuando se excluye el outlier histórico. Si la respuesta es no, el "sistema" depende de seguir encontrando outliers — lo cual no es predecible.' },
    ],
    follow_ups: ['¿Cuál sería la expectancy excluyendo el trade INTC?'],
  },
  loss_aversion: {
    tldr: 'El patrón de ganadoras > perdedoras en magnitud es uno de los más difíciles de mantener — es el opuesto a la tendencia instintiva. Lo que está funcionando hoy no es una decisión puntual sino un proceso silencioso que vale más que cualquier trade individual del año.',
    sections: [
      { title: 'Patrón saludable', tone: 'positive', body: 'En promedio, tus ganadoras superan en magnitud a tus perdedoras — eso significa que cuando una tesis falla la cortás temprano (stops respetados) y cuando funciona la dejás correr (no toma de ganancia prematura). El comportamiento opuesto es lo que la mayoría de inversores individuales hace por default.' },
      { title: 'Por qué es frágil', tone: 'neutral', body: 'Mantener este patrón es difícil porque pelea contra dos sesgos al mismo tiempo: el deseo de "asegurar" ganancias cuando una posición sube fuerte (anchoring al precio de compra), y la tendencia a mantener perdedoras esperando recuperación. El proceso se rompe en momentos de tensión, no en operatoria normal.' },
      { title: 'Insight clave', tone: 'neutral', body: 'Lo importante no es el patrón actual — es identificar cuál es el momento típico donde se rompe. Suele ser cuando una ganadora pasa de +30% a +80%: la tentación a cerrar para "asegurar" es máxima ahí. Pre-definir qué se hace en ese escenario (ej. rebalancear al 50% solo si supera X% del portfolio) protege el patrón sin requerir disciplina momentánea.' },
    ],
    follow_ups: ['¿En qué momentos típicamente se rompe este patrón?'],
  },
  cash_drag: {
    tldr: 'El efectivo es el {{CASH}} de la cartera: funciona como colchón de liquidez y no como freno. Con ese tamaño, el costo de oportunidad es chico frente al resto de las decisiones.',
    sections: [
      { title: 'Magnitud del drag', tone: 'warning', body: 'Cash material de esa proporción contra un benchmark como el SPY representa un gap de retorno estructural — no porque el cash sea malo, sino porque no participa del rendimiento del mercado. Sobre 12 meses, esa porción "sin trabajar" puede explicar buena parte del gap vs benchmark.' },
      { title: 'Reserva táctica vs cash drag', tone: 'neutral', body: 'El cash con función específica (deploy planificado, gasto cercano, reserva por evento) tiene sentido. El cash sin función específica acumulado por inacción no — es la posición default cuando no se decide. Diferenciar ambos casos cambia totalmente la lectura del riesgo.' },
      { title: 'Insight clave', tone: 'neutral', body: 'La mejora útil no es invertir el cash en bloque, sino pre-acordar una regla de despliegue escalonado. Por ejemplo: deploy mensual del X% durante Y meses, independiente del precio. Esa mecánica saca al inversor del dilema "todavía no" sin requerir convicción en un timing — y el research muestra que el promedio del DCA suele estar dentro del 1% del óptimo retrospectivo.' },
    ],
    follow_ups: ['¿Cuánto del gap vs SPY se explica por cash drag?'],
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
  follow_ups: ['¿Cómo se calculan los sesgos?'],
})

// Mock de follow-up: el LLM real responde la pregunta puntual con el packet.
// Acá armamos una respuesta interpretativa coherente con la cartera demo
// (NVDA top, INTC trade excepcional, mix Schwab/Cocos/Binance, etc.).
function buildDemoFollowup(topic, question) {
  const q = (question || '').toLowerCase()
  let tldr, sections

  if (q.includes('nvda') && (q.includes('cae') || q.includes('cay') || q.includes('baja'))) {
    tldr = 'Con NVDA pesando ~{{NVDA}} de la cartera, una caída del 25 % se traduce en aproximadamente {{NVDA_25}} puntos de la cartera total.'
    sections = [
      { title: 'Cálculo aproximado', tone: 'warning', body: 'El impacto sería del orden de 25 % × {{NVDA}} = {{NVDA_25}} puntos. Sobre una cartera de {{VALOR}}, eso son ~{{NVDA_25_USD}} de pérdida no realizada.' },
      { title: 'Contexto histórico', tone: 'neutral', body: 'Movimientos de NVDA del orden -20%/-30% no son inusuales en corrections del Nasdaq — el activo ha tenido al menos dos drawdowns intra-año de esa magnitud en los últimos ciclos. La pregunta práctica no es si puede pasar, sino cuándo y bajo qué criterio reacciones.' },
    ]
  } else if (q.includes('cash') || q.includes('drag') || q.includes('liquidez')) {
    tldr = 'Tu efectivo es el {{CASH}} de la cartera. Con el S&P rindiendo históricamente ~10 % anual, ese cash te cuesta del orden de {{CASH_COSTO}} puntos anuales: poco.'
    sections = [
      { title: 'Magnitud del costo', tone: 'warning', body: 'Sobre tu valor del portfolio, ~US$ 3.7K en cash a un costo de oportunidad del 10% anual = ~US$ 370/año que dejás arriba de la mesa por no estar invertido. Eso es un drag real, no contable.' },
      { title: 'Mejora estructural', tone: 'neutral', body: 'El despliegue escalonado (DCA mensual) suele cerrar la mayor parte de ese gap sin requerir convicción sobre timing. La pregunta es si tu cash actual es reserva táctica activa o cash drag por inacción.' },
    ]
  } else if (q.includes('s&p') || q.includes('spy') || q.includes('benchmark')) {
    tldr = 'En el año la cartera va {{ANIO}} y el S&P 500 {{SP_ANIO}} ({{GAP_ANIO}}). La diferencia la explican sobre todo la cripto ({{CRIPTO}}) y la parte argentina ({{AR}}), que no siguen al índice.'
    sections = [
      { title: 'Descomposición del gap', tone: 'neutral', body: 'Con {{CASH}} en efectivo rindiendo 0, el cash explica apenas {{CASH_GAP}} puntos de la diferencia con el S&P. El resto sale de lo que no es S&P: cripto ({{CRIPTO}}) y Argentina ({{AR}}).' },
      { title: 'Lectura útil', tone: 'neutral', body: 'Para cerrar el gap vs SPY, la palanca dominante NO es elegir mejor stocks — es decidir cuándo desplegar el cash. Un schedule de DCA pre-pactado normalmente cierra la diferencia sin agregar riesgo material.' },
    ]
  } else if (q.includes('intc') || q.includes('148') || q.includes('mejor trade')) {
    tldr = 'INTC +148% representa más de la mitad del P&L realizado del año. Sin ese trade, la expectancy del sistema se acerca al break-even — el resto de las operaciones rindió cerca del promedio del mercado.'
    sections = [
      { title: 'Contribución asimétrica', tone: 'positive', body: 'Sobre 9 trades cerrados del año, INTC explica una fracción material del avg_win. Ese tipo de outlier es lo que hace que el payoff ratio del sistema sea alto, pero también lo que hace difícil pronosticar replicabilidad.' },
      { title: 'Validación de sistema', tone: 'neutral', body: 'La pregunta clave: ¿qué condiciones permitieron el setup de ese trade? Si son condiciones que se repiten (corrección sectorial + entrada a múltiplos bajos + paciencia hasta inflexión), es reproducible. Si fue un evento idiosincrático, fue suerte capturada bien.' },
    ]
  } else if (q.includes('concentr') || q.includes('rebalanc')) {
    tldr = 'Tu concentración nominal (top1 ~{{TOP1_PCT}}) está en zona moderada, pero la concentración por fuente de rendimiento es claramente más alta. Esa asimetría es lo que justifica un rebalance pre-acordado.'
    sections = [
      { title: 'Regla útil', tone: 'neutral', body: 'Un umbral mecánico simple: recortar si una posición cruza el 30% del portfolio O si el top 3 combinado pasa el 60%. Eso convierte la decisión emocional (\\"me siento expuesto\\") en una regla objetiva que aplica solo cuando los datos lo justifican.' },
      { title: 'Frecuencia', tone: 'neutral', body: 'Rebalancear con criterio (umbral cruzado) es más eficiente que rebalancear calendario (mensual/trimestral). El primero solo actúa cuando hay desviación real; el segundo paga fricciones constantes incluso sin cambio material.' },
    ]
  } else {
    // Generic fallback — respuesta corta y honesta
    tldr = `Sobre "${question}": la data del packet permite responder solo parcialmente. Te paso lo que sí se puede afirmar y dónde quedan los huecos.`
    sections = [
      { title: 'Lo que el packet permite', tone: 'neutral', body: 'Tengo los números agregados del portfolio (TWR, drawdown, top holdings, exposure). Eso me deja contestar preguntas estructurales sobre composición, riesgo, y attribution.' },
      { title: 'Lo que no tengo', tone: 'neutral', body: 'Para precisión sobre activos puntuales, momentum sectorial o eventos macro específicos, necesitaría un análisis sobre el ticker o sección específica. El botón ✦ en cada componente te da ese zoom-in.' },
    ]
  }

  return {
    tldr,
    sections,
    follow_ups: [],  // los follow-ups internos no traen más follow_ups (cap)
  }
}


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
      comparison: 'Sobre una cartera de {{VALOR}}, un movimiento adverso del 25 % en la posición más grande ({{TOP1}}, {{TOP1_PCT}}) implica un impacto del orden de {{TOP1_25}} puntos. El peor retroceso de los últimos 12 meses fue de {{DD}}.',
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
      comparison: 'Sobre la cartera actual, el efectivo es el {{CASH}}: casi todo el capital participó del mercado. Contra el S&P, el cash explica apenas {{CASH_GAP}} puntos de la diferencia del año.',
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

// Watchlist demo base (estado inicial — el overlay puede agregar/quitar)
const WATCHLIST_BASE = [
  // Precio y variación de la MISMA fuente que el mapa de calor (antes AVGO
  // figuraba a US$ 168,40 debajo de un mapa que lo mostraba a 198,40).
  { symbol: 'AVGO', asset_type: 'stock', added_at: '2025-03-20', price: PRICES.AVGO, change_pct: _CAMBIO_DIA.AVGO },
  { symbol: 'PLTR', asset_type: 'stock', added_at: '2025-04-08', price: PRICES.PLTR, change_pct: _CAMBIO_DIA.PLTR },
  { symbol: 'COIN', asset_type: 'stock', added_at: '2025-05-01', price: PRICES.COIN, change_pct: _CAMBIO_DIA.COIN },
]

// PRICES + PREV_CLOSE: ver arriba (movidos antes de MONTHLY para que el
// scaling de MONTHLY pueda computar el target POSITIONS × PRICES).

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

const _MES_ACTUAL_NOMBRE = MONTH_NAMES_ES[new Date().getMonth()].toLowerCase()
const _MES_ANTERIOR_NOMBRE = MONTH_NAMES_ES[(new Date().getMonth() + 11) % 12].toLowerCase()
const _INFLACION_MES_ANTERIOR = (() => {
  const d = new Date()
  d.setDate(1)
  d.setMonth(d.getMonth() - 1)
  const v = (_INFLACION_REF[d.getFullYear()] || _INFLACION_REF[2026])[d.getMonth()]
  return `${String(v).replace('.', ',')} %`
})()

// Noticias del mercado — mock con shape del backend
const NEWS_MARKET = [
  {
    // Antes de la reunión, no después: la agenda del demo tiene la decisión de
    // la Fed dentro de 3 días y esta noticia decía que ya la había tomado.
    title: 'El mercado anticipa que la Fed mantendría las tasas en su próxima reunión',
    summary: 'Los futuros descuentan una pausa en el ciclo de baja de tasas; la atención está en el tono de Powell sobre los próximos recortes.',
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
    // El mes que ya se publicó (el anterior) y con el dato de la serie del demo;
    // antes era "abril" todo el año y la agenda tenía el IPC de abril por venir.
    title: `Inflación de ${_MES_ANTERIOR_NOMBRE} en ${_INFLACION_MES_ANTERIOR}: continúa la desaceleración`,
    summary: `El INDEC informó que la inflación de ${_MES_ANTERIOR_NOMBRE} fue de ${_INFLACION_MES_ANTERIOR} mensual.`,
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
    title: 'GGAL reporta resultados trimestrales por encima de lo esperado',
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
  return fechaISO(d)
}

const EVENTS_PORTFOLIO = [
  { ticker: 'NVDA', event_type: 'earnings',    event_date: _todayPlus(5),  confirmed: 1, details: { title: 'NVDA · Reporte Q1 2026' } },
  { ticker: 'AAPL', event_type: 'ex_dividend', event_date: _todayPlus(2),  confirmed: 1, details: { amount: 0.25 } },
  { ticker: 'MSFT', event_type: 'earnings',    event_date: _todayPlus(12), confirmed: 1, details: { title: 'MSFT · Reporte Q3 FY26' } },
  { ticker: 'TSLA', event_type: 'earnings',    event_date: _todayPlus(9),  confirmed: 0, details: { title: 'TSLA · Earnings (estimado)' } },
]

const EVENTS_POPULAR = [
  { ticker: '',     event_type: 'macro',       event_date: _todayPlus(3),  confirmed: 1, details: { title: 'FOMC · Decisión de tasas Fed' } },
  { ticker: '',     event_type: 'macro',       event_date: _todayPlus(7),  confirmed: 1, details: { title: `INDEC · IPC de ${_MES_ACTUAL_NOMBRE}` } },
  { ticker: 'NVDA', event_type: 'earnings',    event_date: _todayPlus(5),  confirmed: 1, details: { title: 'NVDA · Reporte trimestral' } },
  { ticker: 'AAPL', event_type: 'ex_dividend', event_date: _todayPlus(2),  confirmed: 1, details: { amount: 0.25 } },
  { ticker: 'GGAL', event_type: 'earnings',    event_date: _todayPlus(14), confirmed: 0, details: { title: 'GGAL · Próximos resultados (estimado)' } },
]

// ─── Fundamentals (Rendi Score) ──────────────────────────────────────────────
// Fixtures que matchean EXACTAMENTE el shape del contrato
// (GET /fundamentals/{ticker} + POST /fundamentals/ai-summary). Permiten que la
// página /fundamentals funcione end-to-end en demo, sin backend.
//
// overall.label: >=80 Excelente, >=65 Bueno, >=45 Mixto, else Débil.
// category color (front): >=70 verde, >=40 ámbar, <40 rojo.

// Tickers que NO tienen fundamentales (cripto + bonos). Se responden con
// available:false replicando la lógica del backend.
const _FUND_CRYPTO = new Set([
  'BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'ADA', 'DOGE', 'AVAX', 'DOT', 'MATIC',
  'LINK', 'USDT', 'USDC', 'BTC-USD', 'ETH-USD',
])

function _fundLabel(overall) {
  if (overall == null) return 'Sin datos'
  if (overall >= 80) return 'Excelente'
  if (overall >= 65) return 'Bueno'
  if (overall >= 45) return 'Mixto'
  return 'Débil'
}

function _fundCategories({ valuation, growth, profitability, health, valMetrics }) {
  return [
    {
      key: 'valuation', label: 'Valuación', question: '¿Está a buen precio hoy?',
      score: valuation,
      metrics: valMetrics || [],
    },
    {
      key: 'growth', label: 'Crecimiento', question: '¿Está creciendo?',
      score: growth, metrics: [],
    },
    {
      key: 'profitability', label: 'Rentabilidad', question: '¿Genera ganancias de forma eficiente?',
      score: profitability, metrics: [],
    },
    {
      key: 'health', label: 'Salud Financiera', question: '¿Es financieramente sólida?',
      score: health, metrics: [],
    },
  ]
}

// ── metrics_detail (wave 2) ──────────────────────────────────────────────
// Las 20 keys del contrato, con value (magnitud comparable) + value_label
// (display) + direction. _md() arma una fila; _metricsDetail() arma el array
// completo a partir de un objeto parcial {key: value} (los faltantes → null/"—").
const _MD_SPEC = [
  ['pe',             'P/E',                'valuation',     'lower',  'x'],
  ['pe_fwd',         'P/E fwd',            'valuation',     'lower',  'x'],
  ['pb',             'P/B',                'valuation',     'lower',  'x'],
  ['ev_ebitda',      'EV/EBITDA',          'valuation',     'lower',  'x'],
  ['peg',            'PEG',                'valuation',     'lower',  'x'],
  ['rev_growth_3y',  'Ingresos 3Y',        'growth',        'higher', '%'],
  ['rev_growth_5y',  'Ingresos 5Y',        'growth',        'higher', '%'],
  ['eps_growth_3y',  'EPS 3Y',             'growth',        'higher', '%'],
  ['rev_growth_yoy', 'Ingresos YoY',       'growth',        'higher', '%'],
  ['earnings_yoy',   'Ganancias YoY',      'growth',        'higher', '%'],
  ['roe',            'ROE',                'profitability', 'higher', '%'],
  ['roa',            'ROA',                'profitability', 'higher', '%'],
  ['net_margin',     'Margen neto',        'profitability', 'higher', '%'],
  ['oper_margin',    'Margen operativo',   'profitability', 'higher', '%'],
  ['gross_margin',   'Margen bruto',       'profitability', 'higher', '%'],
  ['debt_equity',    'Deuda/Capital',      'health',        'lower',  'x'],
  ['current_ratio',  'Liquidez corriente', 'health',        'higher', 'x'],
  ['quick_ratio',    'Liquidez ácida',     'health',        'higher', 'x'],
  ['payout',         'Payout',             'health',        'lower',  '%'],
  ['fcf_margin',     'Margen FCF',         'health',        'higher', '%'],
]

function _mdLabel(value, unit) {
  if (value == null || Number.isNaN(value)) return '—'
  return unit === '%' ? `${value.toFixed(2).replace('.', ',')}%` : `${value.toFixed(2).replace('.', ',')}x`
}

// vals: { key: number } — claves ausentes salen null/"—".
function _metricsDetail(vals = {}) {
  return _MD_SPEC.map(([key, label, category, direction, unit]) => {
    const v = vals[key]
    const value = typeof v === 'number' && !Number.isNaN(v) ? v : null
    return { key, label, category, value, value_label: _mdLabel(value, unit), direction }
  })
}

// ── categories_detail (wave 3) ───────────────────────────────────────────
// Desglose métrica por métrica de las 5 categorías (incl. Dividendos). Las
// shapes matchean el contrato exacto para que demo == real:
//   category: { key, label, question, score (0-100|null), metrics[] }
//   metric:   { key, label, value, value_label, direction, status,
//               status_label, info }
//   direction: "higher"|"lower"|"info"; status: "green"|"amber"|"red"|"na".
//
// Spec por categoría: [key, label, direction, unit, info, threshold(value)→status]
// La función de threshold devuelve "green"|"amber"|"red"; "info" no la usa.
const _STATUS_LABEL = { green: 'Excelente', amber: 'Aceptable', red: 'Bajo', na: '' }
// Para valuación el label "rojo" es "Muy caro" y el ámbar "Aceptable".
const _VAL_STATUS_LABEL = { green: 'Excelente', amber: 'Aceptable', red: 'Muy caro', na: '' }

// Umbrales (replican el contrato backend).
const _thHigher = (g, a) => (v) => (v >= g ? 'green' : v >= a ? 'amber' : 'red')
const _thLower = (g, a) => (v) => (v < 0 ? 'red' : v <= g ? 'green' : v <= a ? 'amber' : 'red')

const _CD_SPEC = [
  {
    key: 'valuation', label: 'Valuación', question: '¿Qué tan cara está respecto a sus fundamentos?',
    labels: _VAL_STATUS_LABEL,
    metrics: [
      ['pe', 'P/E', 'lower', 'x', 'Precio / ganancias por acción. Menor = más barato.', _thLower(15, 30)],
      ['pe_fwd', 'P/E Forward', 'lower', 'x', 'P/E usando ganancias estimadas a futuro.', _thLower(15, 25)],
      ['pb', 'P/B', 'lower', 'x', 'Precio / valor libro. Menor = más barato vs activos.', _thLower(3, 8)],
      ['ev_ebitda', 'EV/EBITDA', 'lower', 'x', 'Valor empresa / EBITDA. Menor = más barato.', _thLower(10, 18)],
      ['peg', 'PEG', 'lower', 'x', 'P/E ajustado por crecimiento. <1 suele ser barato.', _thLower(1, 2)],
    ],
  },
  {
    key: 'growth', label: 'Crecimiento', question: '¿Está creciendo sus ventas y ganancias?',
    labels: _STATUS_LABEL,
    metrics: [
      ['rev_growth_3y', 'CAGR Ingresos 3A', 'higher', '%', 'Crecimiento anual de ingresos en 3 años.', _thHigher(15, 5)],
      ['rev_growth_5y', 'CAGR Ingresos 5A', 'higher', '%', 'Crecimiento anual de ingresos en 5 años.', _thHigher(15, 5)],
      ['eps_growth_3y', 'Crecimiento EPS 3A', 'higher', '%', 'Crecimiento anual de ganancias por acción en 3 años.', _thHigher(15, 5)],
      ['rev_growth_yoy', 'Ingresos vs año anterior', 'higher', '%', 'Variación de ingresos contra el año pasado.', _thHigher(15, 5)],
      ['earnings_yoy', 'Ganancias vs año anterior', 'higher', '%', 'Variación de ganancias contra el año pasado.', _thHigher(15, 5)],
    ],
  },
  {
    key: 'profitability', label: 'Rentabilidad', question: '¿Genera ganancias de forma eficiente?',
    labels: _STATUS_LABEL,
    metrics: [
      ['roe', 'ROE', 'higher', '%', 'Retorno sobre el patrimonio de los accionistas.', _thHigher(15, 8)],
      ['roa', 'ROA', 'higher', '%', 'Retorno sobre los activos totales.', _thHigher(8, 3)],
      ['net_margin', 'Margen Neto', 'higher', '%', 'Ganancia neta como % de los ingresos.', _thHigher(15, 5)],
      ['oper_margin', 'Margen Operativo', 'higher', '%', 'Ganancia operativa como % de los ingresos.', _thHigher(15, 5)],
      ['gross_margin', 'Margen Bruto', 'higher', '%', 'Ingresos menos costo de ventas, como %.', _thHigher(40, 20)],
    ],
  },
  {
    key: 'health', label: 'Salud Financiera', question: '¿Es financieramente sólida?',
    labels: _STATUS_LABEL,
    metrics: [
      ['debt_equity', 'Deuda/Patrimonio', 'lower', 'x', 'Deuda total vs patrimonio. Menor = menos apalancada.', _thLower(0.5, 1.5)],
      ['current_ratio', 'Liquidez Corriente', 'higher', 'x', 'Activos corrientes / pasivos corrientes.', _thHigher(2, 1)],
      ['quick_ratio', 'Prueba Ácida', 'higher', 'x', 'Liquidez sin inventarios.', _thHigher(1, 0.7)],
      ['interest_coverage', 'Cobertura de Intereses', 'higher', 'x', 'EBIT / intereses. Cuántas veces cubre su deuda.', _thHigher(5, 2)],
      ['total_cash', 'Caja Total', 'info', '$', 'Efectivo y equivalentes disponibles.', null],
      ['total_debt', 'Deuda Total', 'info', '$', 'Deuda total de la empresa.', null],
    ],
  },
  {
    key: 'dividends', label: 'Dividendos', question: '¿Reparte dividendos sostenibles?',
    labels: _STATUS_LABEL,
    metrics: [
      ['dividend_yield', 'Dividend Yield', 'higher', '%', 'Dividendo anual como % del precio.', _thHigher(3, 1)],
      ['payout', 'Payout Ratio', 'lower', '%', 'Qué % de las ganancias reparte como dividendos.', _thLower(60, 90)],
      ['avg_yield_5y', 'Yield Promedio 5A', 'info', '%', 'Dividend yield promedio de los últimos 5 años.', null],
    ],
  },
]

function _cdValueLabel(value, unit) {
  if (value == null || Number.isNaN(value)) return '—'
  if (unit === '%') return `${value.toFixed(2).replace('.', ',')}%`
  if (unit === '$') return _fundUsdCompact(value)
  return `${value.toFixed(2).replace('.', ',')}x`
}

function _fundUsdCompact(n) {
  if (n == null || Number.isNaN(n)) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '−' : ''
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2).replace('.', ',')}T`
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2).replace('.', ',')}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2).replace('.', ',')}M`
  return `${sign}$${abs.toFixed(0)}`
}

// status → points para derivar el score de categoría (igual que backend).
const _CD_POINTS = { green: 90, amber: 55, red: 18 }

// vals: { key: number } — arma las 5 categorías. Las claves ausentes salen
// null/"—" (sin badge/barra). Dividendos: score null (no entra al overall).
function _categoriesDetail(vals = {}) {
  return _CD_SPEC.map(spec => {
    const points = []
    const metrics = spec.metrics.map(([key, label, direction, unit, info, th]) => {
      const v = vals[key]
      const value = typeof v === 'number' && !Number.isNaN(v) ? v : null
      let status = 'na'
      if (direction !== 'info' && value != null && th) {
        status = th(value)
        points.push(_CD_POINTS[status])
      }
      const status_label = direction === 'info' ? '' : (spec.labels[status] || '')
      return {
        key, label, value,
        value_label: _cdValueLabel(value, unit),
        direction, status, status_label, info,
      }
    })
    const score =
      spec.key === 'dividends'
        ? null
        : (points.length ? Math.round(points.reduce((a, b) => a + b, 0) / points.length) : null)
    return { key: spec.key, label: spec.label, question: spec.question, score, metrics }
  })
}

// Deriva el score HEADLINE (4 cards + overall) desde categories_detail, igual
// que el backend _score_categories(). Garantiza demo == real y que las cards y
// el detalle NUNCA se contradigan. Reusa _fundCategories (preguntas cortas, como
// _FUND_CATEGORY_META del backend). Dividendos NO entra al overall.
const _CORE_WEIGHTS = { valuation: 0.30, profitability: 0.25, health: 0.25, growth: 0.20 }
function _deriveScoreFromCategoriesDetail(cd) {
  const byKey = {}
  for (const c of (cd || [])) byKey[c.key] = c
  const sc = (k) => (byKey[k] && typeof byKey[k].score === 'number' ? byKey[k].score : null)
  const valuation = sc('valuation'), growth = sc('growth')
  const profitability = sc('profitability'), health = sc('health')
  let acc = 0, wsum = 0
  for (const [k, v] of [['valuation', valuation], ['growth', growth], ['profitability', profitability], ['health', health]]) {
    if (typeof v === 'number') { acc += v * _CORE_WEIGHTS[k]; wsum += _CORE_WEIGHTS[k] }
  }
  const overall = wsum > 0 ? Math.round(acc / wsum) : null
  return { overall, label: _fundLabel(overall), categories: _fundCategories({ valuation, growth, profitability, health }) }
}

// Fichas explícitas para los holdings demo principales.
const _FUND_FIXTURES = {
  NVDA: {
    ticker: 'NVDA', company_name: 'NVIDIA Corporation', sector: 'Technology',
    currency: 'USD', as_of: '2026-05-20', stale: false,
    score: {
      overall: 85, label: 'Excelente',
      categories: _fundCategories({
        valuation: 44, growth: 100, profitability: 100, health: 93,
        valMetrics: [
          { name: 'P/E (precio/ganancias)', value_label: '32.88', status: 'amber', reference: 'vs forward 28.1' },
        ],
      }),
    },
    opportunity: {
      available: true, kind: 'analyst', value_pct: 50.0, label: 'Oportunidad',
      position_pct: 18.0, caption: '50% de upside vs el precio objetivo de los analistas',
    },
    analysts: {
      available: true, recommendation_key: 'strong_buy', recommendation_label: 'Compra fuerte',
      n_analysts: 58, target_mean_usd: 298.0, current_price_usd: 198.7, upside_pct: 50.0,
    },
    metrics: {
      trailing_pe: 32.88, forward_pe: 28.1, peg_ratio: 1.2,
      dividend_yield_pct: 0.47, payout_ratio_pct: 1.9,
      roe_pct: 114.28, profit_margin_pct: 62.96, revenue_growth_pct: 100.04,
      debt_to_equity: 0.41, market_cap_usd: 3.2e12, beta: 1.7,
      week_52_high_usd: 153.0, week_52_low_usd: 86.0,
    },
    metrics_detail: _metricsDetail({
      pe: 32.88, pe_fwd: 28.06, pb: 14.59, ev_ebitda: 32.07, peg: 2.17,
      rev_growth_3y: 100.04, eps_growth_3y: 120.5, earnings_yoy: 168.0,
      roe: 114.28, net_margin: 62.96, oper_margin: 64.1, gross_margin: 75.0,
      debt_equity: 0.41, payout: 1.9, fcf_margin: 47.0,
    }),
    categories_detail: _categoriesDetail({
      pe: 32.88, pe_fwd: 28.06, pb: 14.59, ev_ebitda: 32.07, peg: 2.17,
      rev_growth_3y: 100.04, rev_growth_5y: 72.4, eps_growth_3y: 120.5,
      rev_growth_yoy: 94.0, earnings_yoy: 168.0,
      roe: 114.28, roa: 65.2, net_margin: 62.96, oper_margin: 64.1, gross_margin: 75.0,
      debt_equity: 0.41, current_ratio: 4.10, quick_ratio: 3.62, interest_coverage: 45.0,
      total_cash: 4.34e10, total_debt: 1.0e10,
      dividend_yield: 0.47, payout: 1.9, avg_yield_5y: 0.10,
    }),
  },
  MSFT: {
    ticker: 'MSFT', company_name: 'Microsoft Corporation', sector: 'Technology',
    currency: 'USD', as_of: '2026-04-30', stale: false,
    score: {
      overall: 82, label: 'Excelente',
      categories: _fundCategories({
        valuation: 55, growth: 78, profitability: 100, health: 90,
        valMetrics: [
          { name: 'P/E (precio/ganancias)', value_label: '35.10', status: 'amber', reference: 'vs forward 30.4' },
        ],
      }),
    },
    opportunity: {
      available: true, kind: 'analyst', value_pct: 14.0, label: 'Oportunidad',
      position_pct: 33.0, caption: '14% de upside vs el precio objetivo de los analistas',
    },
    analysts: {
      available: true, recommendation_key: 'buy', recommendation_label: 'Compra',
      n_analysts: 51, target_mean_usd: 510.0, current_price_usd: 447.0, upside_pct: 14.0,
    },
    metrics: {
      trailing_pe: 35.1, forward_pe: 30.4, peg_ratio: 2.1,
      dividend_yield_pct: 0.72, payout_ratio_pct: 25.0,
      roe_pct: 38.5, profit_margin_pct: 36.4, revenue_growth_pct: 17.0,
      debt_to_equity: 0.33, market_cap_usd: 3.3e12, beta: 0.9,
      week_52_high_usd: 468.0, week_52_low_usd: 362.0,
    },
    metrics_detail: _metricsDetail({
      pe: 35.10, pe_fwd: 30.40, pb: 11.20, ev_ebitda: 24.50, peg: 2.10,
      rev_growth_3y: 16.80, eps_growth_3y: 22.40, earnings_yoy: 18.20,
      roe: 38.50, roa: 18.10, net_margin: 36.40, oper_margin: 44.6, gross_margin: 69.4,
      debt_equity: 0.33, current_ratio: 1.30, quick_ratio: 1.27, payout: 25.0, fcf_margin: 30.1,
    }),
    categories_detail: _categoriesDetail({
      pe: 35.10, pe_fwd: 30.40, pb: 11.20, ev_ebitda: 24.50, peg: 2.10,
      rev_growth_3y: 16.80, rev_growth_5y: 15.4, eps_growth_3y: 22.40,
      rev_growth_yoy: 17.0, earnings_yoy: 18.20,
      roe: 38.50, roa: 18.10, net_margin: 36.40, oper_margin: 44.6, gross_margin: 69.4,
      debt_equity: 0.33, current_ratio: 1.30, quick_ratio: 1.27, interest_coverage: 38.0,
      total_cash: 7.5e10, total_debt: 4.7e10,
      dividend_yield: 0.72, payout: 25.0, avg_yield_5y: 0.85,
    }),
  },
  MELI: {
    ticker: 'MELI', company_name: 'MercadoLibre, Inc.', sector: 'Consumer Cyclical',
    currency: 'USD', as_of: '2026-03-31', stale: false,
    score: {
      overall: 50, label: 'Mixto',
      categories: _fundCategories({
        valuation: 30, growth: 88, profitability: 60, health: 45,
        valMetrics: [
          { name: 'P/E (precio/ganancias)', value_label: '43.29', status: 'red', reference: 'vs forward 33.0' },
        ],
      }),
    },
    opportunity: {
      available: true, kind: 'analyst', value_pct: 22.0, label: 'Oportunidad',
      position_pct: 28.0, caption: '22% de upside vs el precio objetivo de los analistas',
    },
    analysts: {
      available: true, recommendation_key: 'buy', recommendation_label: 'Compra',
      n_analysts: 24, target_mean_usd: 2450.0, current_price_usd: 2008.0, upside_pct: 22.0,
    },
    metrics: {
      trailing_pe: 43.29, forward_pe: 33.0, peg_ratio: 1.03,
      dividend_yield_pct: null, payout_ratio_pct: 0.0,
      roe_pct: 31.26, profit_margin_pct: 9.3, revenue_growth_pct: 37.0,
      debt_to_equity: 1.1, market_cap_usd: 1.0e11, beta: 1.6,
      week_52_high_usd: 2120.0, week_52_low_usd: 1300.0,
    },
    metrics_detail: _metricsDetail({
      pe: 43.29, pe_fwd: 33.00, pb: 18.40, ev_ebitda: 28.90, peg: 1.03,
      rev_growth_3y: 38.91, eps_growth_3y: 54.20, earnings_yoy: 41.0,
      roe: 31.26, net_margin: 9.30, oper_margin: 11.8, gross_margin: 49.5,
      debt_equity: 1.10, payout: 0.0,
    }),
    categories_detail: _categoriesDetail({
      pe: 43.29, pe_fwd: 33.00, pb: 18.40, ev_ebitda: 28.90, peg: 1.03,
      rev_growth_3y: 38.91, rev_growth_5y: 42.0, eps_growth_3y: 54.20,
      rev_growth_yoy: 37.0, earnings_yoy: 41.0,
      roe: 31.26, roa: 8.4, net_margin: 9.30, oper_margin: 11.8, gross_margin: 49.5,
      debt_equity: 1.10, current_ratio: 1.30, quick_ratio: 1.18, interest_coverage: 6.2,
      total_cash: 2.1e9, total_debt: 3.4e9,
      // MELI no paga dividendos → yield 0/na, payout 0 (na), avg null.
    }),
  },
  GOOGL: {
    ticker: 'GOOGL', company_name: 'Alphabet Inc.', sector: 'Communication Services',
    currency: 'USD', as_of: '2026-03-31', stale: false,
    score: {
      overall: 81, label: 'Excelente',
      categories: _fundCategories({
        valuation: 66, growth: 72, profitability: 100, health: 95,
        valMetrics: [
          { name: 'P/E (precio/ganancias)', value_label: '24.10', status: 'green', reference: 'vs forward 21.3' },
        ],
      }),
    },
    opportunity: {
      available: true, kind: 'analyst', value_pct: 12.0, label: 'Oportunidad',
      position_pct: 35.0, caption: '12% de upside vs el precio objetivo de los analistas',
    },
    analysts: {
      available: true, recommendation_key: 'strong_buy', recommendation_label: 'Compra fuerte',
      n_analysts: 47, target_mean_usd: 205.0, current_price_usd: 183.0, upside_pct: 12.0,
    },
    metrics: {
      trailing_pe: 24.1, forward_pe: 21.3, peg_ratio: 1.3,
      dividend_yield_pct: 0.45, payout_ratio_pct: 8.0,
      roe_pct: 30.8, profit_margin_pct: 27.7, revenue_growth_pct: 15.0,
      debt_to_equity: 0.1, market_cap_usd: 2.2e12, beta: 1.0,
      week_52_high_usd: 191.0, week_52_low_usd: 130.0,
    },
    metrics_detail: _metricsDetail({
      pe: 24.10, pe_fwd: 21.30, pb: 6.80, ev_ebitda: 17.40, peg: 1.30,
      rev_growth_3y: 14.20, rev_growth_5y: 18.6, eps_growth_3y: 21.10, earnings_yoy: 28.6,
      roe: 30.80, roa: 19.4, net_margin: 27.70, oper_margin: 32.0, gross_margin: 57.5,
      debt_equity: 0.10, current_ratio: 1.95, quick_ratio: 1.90, payout: 8.0, fcf_margin: 25.3,
    }),
    categories_detail: _categoriesDetail({
      pe: 24.10, pe_fwd: 21.30, pb: 6.80, ev_ebitda: 17.40, peg: 1.30,
      rev_growth_3y: 14.20, rev_growth_5y: 18.6, eps_growth_3y: 21.10,
      rev_growth_yoy: 15.0, earnings_yoy: 28.6,
      roe: 30.80, roa: 19.4, net_margin: 27.70, oper_margin: 32.0, gross_margin: 57.5,
      debt_equity: 0.10, current_ratio: 1.95, quick_ratio: 1.90, interest_coverage: 28.0,
      total_cash: 1.1e11, total_debt: 1.3e10,
      dividend_yield: 0.45, payout: 8.0, avg_yield_5y: 0.52,
    }),
  },
  AAPL: {
    ticker: 'AAPL', company_name: 'Apple Inc.', sector: 'Technology',
    currency: 'USD', as_of: '2026-03-29', stale: false,
    score: {
      overall: 73, label: 'Bueno',
      categories: _fundCategories({
        valuation: 48, growth: 55, profitability: 100, health: 78,
        valMetrics: [
          { name: 'P/E (precio/ganancias)', value_label: '29.40', status: 'amber', reference: 'vs forward 27.0' },
        ],
      }),
    },
    opportunity: {
      available: true, kind: 'analyst', value_pct: 8.0, label: 'En precio',
      position_pct: 52.0, caption: '8% de upside vs el precio objetivo de los analistas',
    },
    analysts: {
      available: true, recommendation_key: 'hold', recommendation_label: 'Mantener',
      n_analysts: 40, target_mean_usd: 235.0, current_price_usd: 218.0, upside_pct: 8.0,
    },
    metrics: {
      trailing_pe: 29.4, forward_pe: 27.0, peg_ratio: 2.9,
      dividend_yield_pct: 0.55, payout_ratio_pct: 15.0,
      roe_pct: 147.0, profit_margin_pct: 26.3, revenue_growth_pct: 5.0,
      debt_to_equity: 1.5, market_cap_usd: 3.3e12, beta: 1.2,
      week_52_high_usd: 237.0, week_52_low_usd: 164.0,
    },
    metrics_detail: _metricsDetail({
      pe: 29.40, pe_fwd: 27.00, pb: 48.20, ev_ebitda: 22.10, peg: 2.90,
      rev_growth_3y: 6.80, eps_growth_3y: 9.40, earnings_yoy: 5.2,
      roe: 147.00, roa: 28.6, net_margin: 26.30, oper_margin: 30.7, gross_margin: 46.2,
      debt_equity: 1.50, current_ratio: 0.99, quick_ratio: 0.95, payout: 15.0, fcf_margin: 28.4,
    }),
    categories_detail: _categoriesDetail({
      pe: 29.40, pe_fwd: 27.00, pb: 48.20, ev_ebitda: 22.10, peg: 2.90,
      rev_growth_3y: 6.80, rev_growth_5y: 7.9, eps_growth_3y: 9.40,
      rev_growth_yoy: 5.0, earnings_yoy: 5.2,
      roe: 147.00, roa: 28.6, net_margin: 26.30, oper_margin: 30.7, gross_margin: 46.2,
      debt_equity: 1.50, current_ratio: 0.99, quick_ratio: 0.95, interest_coverage: 32.0,
      total_cash: 2.95e10, total_debt: 1.04e11,
      dividend_yield: 0.55, payout: 15.0, avg_yield_5y: 0.62,
    }),
  },
  NFLX: {
    ticker: 'NFLX', company_name: 'Netflix, Inc.', sector: 'Communication Services',
    currency: 'USD', as_of: '2026-03-31', stale: false,
    score: {
      overall: 75, label: 'Bueno',
      categories: _fundCategories({
        valuation: 52, growth: 92, profitability: 88, health: 80,
        valMetrics: [
          { name: 'P/E (precio/ganancias)', value_label: '34.77', status: 'amber', reference: 'vs forward 29.0' },
        ],
      }),
    },
    opportunity: {
      available: true, kind: 'analyst', value_pct: 16.0, label: 'Oportunidad',
      position_pct: 30.0, caption: '16% de upside vs el precio objetivo de los analistas',
    },
    analysts: {
      available: true, recommendation_key: 'buy', recommendation_label: 'Compra',
      n_analysts: 39, target_mean_usd: 780.0, current_price_usd: 672.0, upside_pct: 16.0,
    },
    metrics: {
      trailing_pe: 34.77, forward_pe: 29.0, peg_ratio: 0.95,
      dividend_yield_pct: null, payout_ratio_pct: 0.0,
      roe_pct: 48.49, profit_margin_pct: 22.30, revenue_growth_pct: 15.0,
      debt_to_equity: 0.54, market_cap_usd: 2.9e11, beta: 1.3,
      week_52_high_usd: 700.0, week_52_low_usd: 420.0,
    },
    metrics_detail: _metricsDetail({
      pe: 34.77, pe_fwd: 29.00, pb: 14.20, ev_ebitda: 26.40, peg: 0.95,
      rev_growth_3y: 14.30, eps_growth_3y: 86.40, earnings_yoy: 82.80,
      roe: 48.49, net_margin: 22.30, oper_margin: 26.7, gross_margin: 46.0,
      debt_equity: 0.54, payout: 0.0, fcf_margin: 18.4,
    }),
    categories_detail: _categoriesDetail({
      pe: 34.77, pe_fwd: 29.00, pb: 14.20, ev_ebitda: 26.40, peg: 0.95,
      rev_growth_3y: 14.30, rev_growth_5y: 16.8, eps_growth_3y: 86.40,
      rev_growth_yoy: 15.0, earnings_yoy: 82.80,
      roe: 48.49, roa: 14.2, net_margin: 22.30, oper_margin: 26.7, gross_margin: 46.0,
      debt_equity: 0.54, current_ratio: 1.12, quick_ratio: 1.12, interest_coverage: 12.0,
      total_cash: 7.8e9, total_debt: 1.6e10,
      // NFLX no paga dividendos → categoría Dividendos en na/"—".
    }),
  },
}

// Fallback determinístico para cualquier otra acción (no listada arriba).
// Genera scores estables a partir del hash del símbolo → la misma acción
// siempre devuelve el mismo scorecard.
function _hashStr(s) {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) >>> 0
  }
  return h
}

function _genericFundamentals(ticker) {
  const h = _hashStr(ticker)
  const span = (seed, min, max) => min + (seed % (max - min + 1))
  const valuation = span(h, 35, 75)
  const growth = span(h >> 3, 40, 95)
  const profitability = span(h >> 6, 45, 95)
  const health = span(h >> 9, 50, 95)
  // weighted mean (val .30, prof .25, health .25, growth .20)
  const overall = Math.round(
    valuation * 0.30 + profitability * 0.25 + health * 0.25 + growth * 0.20
  )
  const upside = span(h >> 12, -12, 35)
  const recKey = upside > 18 ? 'buy' : upside > 5 ? 'hold' : 'underperform'
  const recLabel = upside > 18 ? 'Compra' : upside > 5 ? 'Mantener' : 'Vender'
  const price = 50 + (h % 400)
  const target = +(price * (1 + upside / 100)).toFixed(2)
  return {
    available: true, ticker, company_name: ticker, sector: 'Equity',
    currency: 'USD', as_of: null, stale: false,
    score: {
      overall, label: _fundLabel(overall),
      categories: _fundCategories({ valuation, growth, profitability, health }),
    },
    opportunity: {
      available: true, kind: 'analyst', value_pct: upside,
      label: upside > 15 ? 'Oportunidad' : upside > 0 ? 'En precio' : 'Flojo',
      position_pct: Math.max(0, Math.min(100, 50 - upside)),
      caption: `${upside >= 0 ? '+' : ''}${pctTxt(upside)} vs el precio objetivo de los analistas`,
    },
    analysts: {
      available: true, recommendation_key: recKey, recommendation_label: recLabel,
      n_analysts: span(h >> 15, 6, 45), target_mean_usd: target,
      current_price_usd: price, upside_pct: upside,
    },
    metrics: {
      trailing_pe: +(12 + (h % 30)).toFixed(2), forward_pe: null, peg_ratio: null,
      dividend_yield_pct: +((h % 400) / 100).toFixed(2), payout_ratio_pct: null,
      roe_pct: +(8 + (h % 40)).toFixed(2), profit_margin_pct: +(5 + (h % 35)).toFixed(2),
      revenue_growth_pct: +((h % 60) - 10).toFixed(2),
      debt_to_equity: +((h % 200) / 100).toFixed(2), market_cap_usd: null, beta: null,
      week_52_high_usd: null, week_52_low_usd: null,
    },
    // metrics_detail determinístico: derivamos las magnitudes del hash. Dejamos
    // algunas keys en null/"—" para que se vea realista (datos parciales).
    metrics_detail: _metricsDetail({
      pe: +(12 + (h % 30)).toFixed(2),
      pe_fwd: +(10 + (h % 26)).toFixed(2),
      pb: +(1 + (h % 800) / 100).toFixed(2),
      ev_ebitda: +(8 + (h % 22)).toFixed(2),
      peg: +(0.6 + (h % 250) / 100).toFixed(2),
      rev_growth_3y: +((h % 45) - 5).toFixed(2),
      eps_growth_3y: +((h % 60) - 8).toFixed(2),
      earnings_yoy: +((h % 50) - 6).toFixed(2),
      roe: +(8 + (h % 40)).toFixed(2),
      net_margin: +(5 + (h % 35)).toFixed(2),
      gross_margin: +(30 + (h % 45)).toFixed(2),
      debt_equity: +((h % 200) / 100).toFixed(2),
      payout: +((h % 60)).toFixed(2),
      // rev_growth_5y / roa / oper_margin / liquidez / fcf_margin → null ("—")
    }),
    // categories_detail determinístico — deja algunas keys en null ("—") para
    // un look de datos parciales realista (igual que metrics_detail).
    categories_detail: _categoriesDetail({
      pe: +(12 + (h % 30)).toFixed(2),
      pe_fwd: +(10 + (h % 26)).toFixed(2),
      pb: +(1 + (h % 800) / 100).toFixed(2),
      ev_ebitda: +(8 + (h % 22)).toFixed(2),
      peg: +(0.6 + (h % 250) / 100).toFixed(2),
      rev_growth_3y: +((h % 45) - 5).toFixed(2),
      eps_growth_3y: +((h % 60) - 8).toFixed(2),
      rev_growth_yoy: +((h % 50) - 6).toFixed(2),
      earnings_yoy: +((h % 50) - 6).toFixed(2),
      roe: +(8 + (h % 40)).toFixed(2),
      net_margin: +(5 + (h % 35)).toFixed(2),
      gross_margin: +(30 + (h % 45)).toFixed(2),
      debt_equity: +((h % 200) / 100).toFixed(2),
      current_ratio: +(0.8 + (h % 250) / 100).toFixed(2),
      total_debt: 1e8 + (h % 900) * 1e7,
      dividend_yield: +((h % 400) / 100).toFixed(2),
      payout: +((h % 60)).toFixed(2),
      // rev_growth_5y / roa / oper_margin / quick / interest_cov / total_cash
      // / avg_yield_5y → null ("—")
    }),
  }
}

function _buildDemoFundamentals(rawTicker) {
  const ticker = (rawTicker || '').toUpperCase()
  if (!ticker) {
    return { available: false, ticker, reason: 'Ticker vacío.' }
  }
  // Cripto → sin fundamentales
  if (_FUND_CRYPTO.has(ticker)) {
    return {
      available: false, ticker,
      reason: `yfinance no tiene fundamentales para ${ticker} (cripto, bono o ticker inválido)`,
    }
  }
  // Bonos AR / .BA (CEDEAR en ARS)
  if (isBondTicker(ticker)) {
    return {
      available: false, ticker,
      reason: `yfinance no tiene fundamentales para ${ticker} (cripto, bono o ticker inválido)`,
    }
  }
  if (ticker.endsWith('.BA')) {
    const us = ticker.slice(0, -3)
    return {
      available: false, ticker,
      reason: `Usá el ticker en USD: ${us} en vez de ${ticker}`,
    }
  }
  const fixture = _FUND_FIXTURES[ticker]
  const result = fixture ? { available: true, ...fixture } : _genericFundamentals(ticker)
  // Single source of truth (igual que el backend): el score headline se DERIVA
  // de categories_detail, así las cards y el detalle nunca se contradicen.
  if (result.available && Array.isArray(result.categories_detail)) {
    result.score = _deriveScoreFromCategoriesDetail(result.categories_detail)
  }
  return result
}

// Resúmenes IA por ticker (matchean el contrato: {summary:{intro,pros,cons}}).
const _FUND_AI_SUMMARIES = {
  NVDA: {
    intro: 'NVIDIA se volvió el motor de la IA, fabricando los chips que alimentan los modelos más avanzados.',
    pros: [
      'Sus ingresos crecieron a una tasa anual del 100% en tres años.',
      'De cada 100 dólares que factura, se queda con 63 de ganancia neta.',
      'ROE de 114%: exprime al máximo el capital de los accionistas.',
    ],
    cons: [
      'Está cara: un P/E de 32.9 implica pagar caro cada dólar de ganancia; si decepciona, puede corregir fuerte.',
      'No es para vivir de dividendos: rinde 0.47%, casi nada.',
    ],
  },
  MSFT: {
    intro: 'Microsoft es una máquina de generar caja con nube (Azure), software y, cada vez más, IA integrada.',
    pros: [
      'Rentabilidad altísima y constante: márgenes del 36% año tras año.',
      'Balance muy sólido, poca deuda y caja de sobra para invertir.',
      'Negocio diversificado: nube, Office, gaming y publicidad.',
    ],
    cons: [
      'No está barata: el mercado ya le paga el optimismo de la IA.',
      'El dividendo es chico (0.7%): no es una acción para renta.',
    ],
  },
  MELI: {
    intro: 'MercadoLibre es el Amazon + PayPal de Latinoamérica: e-commerce y fintech creciendo a toda velocidad.',
    pros: [
      'Crece muy rápido: ventas +37% anual aprovechando la digitalización de la región.',
      'Domina el e-commerce y los pagos en sus mercados clave.',
      'El negocio de crédito (Mercado Pago) suma una palanca de ganancias enorme.',
    ],
    cons: [
      'Carísima: un P/E de 43 deja poco margen de error si frena el crecimiento.',
      'Expuesta a la volatilidad de monedas latinoamericanas y al riesgo regulatorio.',
    ],
  },
  GOOGL: {
    intro: 'Alphabet (Google) domina la búsqueda y la publicidad online, con YouTube y la nube como motores extra.',
    pros: [
      'Rentabilidad excelente con márgenes cercanos al 28%.',
      'Balance impecable: prácticamente sin deuda y montañas de caja.',
      'Valuación razonable para la calidad: P/E de 24, más barata que sus pares.',
    ],
    cons: [
      'Depende mucho de la publicidad: una recesión le pega directo a los ingresos.',
      'La IA generativa amenaza el corazón de su negocio de búsqueda.',
    ],
  },
  AAPL: {
    intro: 'Apple vende un ecosistema, no solo productos: iPhone, servicios y una base de usuarios ultra leal.',
    pros: [
      'Rentabilidad extraordinaria: ROE de 147%, de las mejores del mercado.',
      'El negocio de servicios crece y suaviza la dependencia del iPhone.',
      'Marca y fidelidad que le dan poder de fijar precios.',
    ],
    cons: [
      'El crecimiento se desaceleró: ventas casi planas (+5%).',
      'Está algo cara para lo poco que crece hoy; los analistas la ven "en precio".',
    ],
  },
  NFLX: {
    intro: 'Netflix dominó el streaming y ahora exprime ese liderazgo con publicidad, planes con anuncios y un control de costos mucho más fino.',
    pros: [
      'Las ganancias por acción crecieron 86% anual en los últimos 3 años.',
      'ROE de 48%: usa el capital de los accionistas de forma muy eficiente.',
      'Márgenes en expansión y generación de caja libre creciente.',
    ],
    cons: [
      'No es barata: un P/E de 35 ya descuenta varios años de buen crecimiento.',
      'Competencia feroz (Disney, Amazon, YouTube) presiona precios y contenido.',
    ],
  },
}

function _genericAISummary(ticker, fund) {
  const m = fund?.metrics || {}
  const pros = []
  const cons = []
  if ((m.revenue_growth_pct ?? 0) > 12) {
    pros.push(`Está creciendo: las ventas suben ${pctTxt(m.revenue_growth_pct)} al año.`)
  } else {
    cons.push('El crecimiento es flojo: las ventas casi no se mueven.')
  }
  if ((m.profit_margin_pct ?? 0) > 15) {
    pros.push(`Buena rentabilidad: se queda con ${m.profit_margin_pct} de cada 100 que factura.`)
  } else {
    cons.push('Márgenes ajustados: gana poco por cada dólar que vende.')
  }
  if ((m.roe_pct ?? 0) > 15) {
    pros.push(`Usa bien el capital: ROE de ${pctTxt(m.roe_pct)}.`)
  }
  if ((m.trailing_pe ?? 0) > 30) {
    cons.push(`Está cara: un P/E de ${m.trailing_pe} deja poco margen de error.`)
  } else if ((m.trailing_pe ?? 0) > 0) {
    pros.push(`Valuación razonable: P/E de ${m.trailing_pe}.`)
  }
  if (pros.length === 0) pros.push('Tiene fundamentales decentes en algunas métricas clave.')
  if (cons.length === 0) cons.push('Revisá la valuación antes de entrar: el precio ya descuenta lo bueno.')
  return {
    intro: `${ticker} es una empresa cotizante. Acá va lo bueno y lo malo de sus números, en criollo.`,
    pros: pros.slice(0, 3),
    cons: cons.slice(0, 2),
  }
}

function _buildDemoAISummary(rawTicker) {
  const ticker = (rawTicker || '').toUpperCase()
  const fund = _buildDemoFundamentals(ticker)
  if (!fund.available) {
    // El backend devolvería 422/available:false — replicamos available:false.
    return { available: false, ticker, reason: fund.reason }
  }
  const summary = _FUND_AI_SUMMARIES[ticker] || _genericAISummary(ticker, fund)
  // Incluimos `usage` para igualar el shape del backend real (el frontend lo
  // lee para mostrar la cuota). En demo simulamos Pro con cupo amplio.
  return {
    summary,
    cached: true,
    tier: 'pro',
    usage: { analyses_count: 1, analyses_limit: 60, analyses_remaining: 59, resets_on: null },
  }
}

// ─── Mock handler para api.js ────────────────────────────────────────────────
// Recibe (method, path) y devuelve la respuesta. null = no hay mock → la
// llamada real se ejecuta (no debería pasar pero por defensa).

// Contador de "No me interesa" del demo (cuota Free 2/sem). El frontend solo
// pega al endpoint para Free; este contador simula el server. Se resetea al
// recargar la página.
let _demoDiagDismissCount = 0

// Estado del badge de alertas en el demo: arranca con 1 evento SIN VER (para
// mostrar el puntito violeta del sidebar); al entrar a /alertas se marca visto.
let _demoAlertsSeen = false

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
    if (basePath === '/monthly')     return _monthlyConAgregadas(overlay)
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
    if (basePath === '/auth/investor-profile') {
      // Demo user es un Moderado típico — horizonte medio, hold ante drawdown,
      // objetivo libertad financiera, estilo mixto. Sirve para mostrar las
      // cards de perfil del inversor con datos reales en lugar del empty CTA.
      return {
        horizon: 'medium',
        drawdown: 'hold',
        goal: 'freedom',
        style: 'mixed',
        net_worth: '10_to_30',
        liquidity: 'no',
        experience: '2_to_5',
        return_expectation: 'grow',
      }
    }
    if (basePath === '/imports')     return []
    // Parsers agrupados — alimentan el grid de brokers del Paso 0 del wizard.
    // Mismo shape que parser_options_grouped() del backend. Sin esto, en demo
    // el grid de "elegí tu broker" quedaría vacío.
    if (basePath === '/imports/parsers/grouped') {
      return [
        { platform: 'generic', platform_label: 'Genérico (cualquier broker)', tenencia_format: null, tenencia_label: null, exports: [
          { id: 'rendi_generic', label: 'Template Rendi', supported: true },
        ] },
        { platform: 'binance', platform_label: 'Binance', tenencia_format: null, tenencia_label: null, exports: [
          { id: 'binance', label: 'Spot → Trade History', supported: true },
          { id: 'binance_transaction_history', label: 'Asset History → Transaction History (completo)', supported: true },
        ] },
        { platform: 'balanz', platform_label: 'Balanz', tenencia_format: 'balanz_tenencia', tenencia_label: 'Mi cuenta → Resumen de cuenta (PDF)', exports: [
          { id: 'balanz_movimientos', label: 'Actividad → Movimientos (recomendado)', supported: true },
          { id: 'balanz', label: 'Operaciones → Órdenes → Exportar', supported: true },
          { id: 'balanz_resultados', label: 'Actividad → Resultados', supported: true },
        ] },
        { platform: 'cocos', platform_label: 'Cocos Capital', tenencia_format: 'cocos_tenencia', tenencia_label: 'Inversiones → Estado de cuenta → Exportar', exports: [
          { id: 'cocos', label: 'Actividad → Movimientos', supported: true },
        ] },
        { platform: 'ppi', platform_label: 'PPI (Portafolio Personal)', tenencia_format: 'ppi_tenencia', tenencia_label: 'Mi cuenta → Estado de cuenta (Excel)', exports: [
          { id: 'ppi', label: 'Movimientos (Excel)', supported: true },
        ] },
        { platform: 'iol', platform_label: 'IOL (InvertirOnline)', tenencia_format: 'iol_tenencia', tenencia_label: 'Mi cuenta → Estado de cuenta (PDF)', exports: [
          { id: 'iol', label: 'Mi Cuenta → Movimientos → Detalle de Movimientos', supported: true },
        ] },
        { platform: 'schwab', platform_label: 'Charles Schwab', tenencia_format: null, tenencia_label: null, exports: [
          { id: 'schwab', label: 'History → Export CSV', supported: true },
        ] },
        { platform: 'bullmarket', platform_label: 'Bull Market', tenencia_format: 'bullmarket_tenencia', tenencia_label: 'Mi cuenta → Otras consultas → Tenencia valorizada (PDF)', exports: [
          { id: 'bullmarket', label: 'Cuenta Corriente (Excel) o Movimientos (CSV)', supported: true },
        ] },
        { platform: 'ieb', platform_label: 'IEB · Invertir en Bolsa', tenencia_format: 'ieb_tenencia', tenencia_label: 'Portafolio → Exportar (Excel)', exports: [
          { id: 'ieb', label: 'Movimientos', supported: true },
        ] },
        { platform: 'inviu', platform_label: 'inviu', tenencia_format: 'inviu_tenencia', tenencia_label: 'Tenencias → Exportar (Excel)', exports: [
          { id: 'inviu', label: 'Reporte de cuenta corriente (Excel)', supported: true },
        ] },
      ]
    }
    if (basePath === '/imports/mappings') return []
    if (basePath === '/config')      return { tc_mep: 1424, tc_blue: 1415 }
    if (basePath === '/home/personal') {
      return { cards: [
        { kind: 'holding_move', value_tone: 'positive', headline: 'NVDA subió hoy', value: '+4,4 %', context: 'US$ 178,50', cta_label: 'Ver posición →', cta_href: '/posiciones' },
        { kind: 'holding_move', value_tone: 'negative', headline: 'TSLA bajó hoy', value: '−2,1 %', context: 'US$ 248,10', cta_label: 'Ver posición →', cta_href: '/posiciones' },
        { kind: 'earnings_soon', value_tone: 'neutral', headline: 'Earnings de NVDA', value: 'en 5 días', context: _todayPlus(5), cta_label: 'Ver detalle →', cta_href: '/novedades?tab=eventos' },
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
    // Expectativas de earnings (panel expandible de la agenda de Eventos)
    if (basePath === '/events/earnings-expectations') {
      return {
        available: true,
        ticker: 'DEMO',
        // La fecha del evento de ese activo en la agenda del demo (antes: una
        // fecha fija ya pasada para todos).
        next_earnings_date: (() => {
          const t = decodeURIComponent((query || '').match(/ticker=([^&]+)/)?.[1] || '').toUpperCase()
          const ev = [...EVENTS_PORTFOLIO, ...EVENTS_POPULAR].find(e => e.ticker === t && e.event_type === 'earnings')
          return ev ? ev.event_date : _todayPlus(20 + (_hashStr(t) % 40))
        })(),
        next_earnings_estimates: { eps_average: 0.93, eps_low: 0.85, eps_high: 1.02 },
        last_quarters: [
          { date: '2026-04', eps_estimate: 0.85, eps_actual: 0.9, surprise_pct: 6.1 },
          { date: '2026-01', eps_estimate: 0.78, eps_actual: 0.85, surprise_pct: 9.2 },
          { date: '2025-10', eps_estimate: 0.71, eps_actual: 0.74, surprise_pct: 4.0 },
          { date: '2025-07', eps_estimate: 0.68, eps_actual: 0.67, surprise_pct: -1.8 },
        ],
        surprise_avg_last_4q_pct: 4.4,
      }
    }
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
    if (basePath === '/prices/prev-close') {
      // Mismo shape que /prices pero con PREV_CLOSE (cierre del día anterior).
      // Positions/PositionsMobile lo usan para calcular la VAR. DÍA por fila.
      // Sin este intercept en demo la columna queda en "—" para todo el book.
      const symbols = (query || '').match(/symbols=([^&]+)/)?.[1]?.split(',') || []
      const out = {}
      for (const s of symbols) {
        if (PREV_CLOSE[s] != null) out[s] = PREV_CLOSE[s]
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

    // Reports period — day / week / month / year (página Reportes tabs)
    const periodMatch = basePath.match(/^\/reports\/period\/(day|week|month|year)\/(.+)$/)
    if (periodMatch) {
      const [, periodType, periodKey] = periodMatch
      return buildDemoPeriodReport(periodType, periodKey)
    }
    // Goals + CAGR (Objetivos page) — demo siempre muestra una meta de ejemplo
    // para que el user vea el diagnostic (Sprint 7) sin tener que crear una.
    // ⚠️ EL OBJETIVO SE CALCULA CON LA CARTERA DEL DEMO. Estaba escrito a mano y
    // se contradecía solo: 36 meses en el encabezado y "38 meses (14 más que tu
    // objetivo)" en el diagnóstico, "el plan está alineado" arriba de
    // "Atrasado", y "38 operaciones en 12 meses" donde Movimientos tiene 15.
    if (basePath === '/goals') {
      const o = _objetivoDemo()
      return [{ id: 1, target_usd: o.meta, target_date: o.fecha, expected_return_pct: o.rendimientoAsumido, label: 'Comprar mi primer auto' }]
    }
    if (basePath === '/goals/cagr') return DEMO_CAGR
    if (/^\/goals\/\d+\/diagnostic$/.test(basePath)) return _objetivoDemo().diagnostico
    // Behavioral insights — sesgos comportamentales (Sprint 3-4)
    if (basePath === '/behavioral/insights') return _comportamientoDemo()
    // Wrapped anual — reseña del año (Sprint 6)
    if (basePath.startsWith('/wrapped/')) {
      const yearStr = basePath.slice('/wrapped/'.length).split('?')[0]
      const year = parseInt(yearStr, 10) || new Date().getFullYear()
      return WRAPPED(year)
    }
    // ── Alertas — una alerta de precio + un evento disparado (sin ver hasta
    //    que el user entra a /alertas) para showcasear el badge del sidebar.
    if (basePath === '/alerts') {
      const firedAt = new Date(Date.now() - 90 * 60 * 1000)  // hace ~1.5h
        .toISOString().slice(0, 19).replace('T', ' ')
      return {
        items: [
          { id: 1, kind: 'price_target', symbol: 'AAPL', direction: 'above',
            threshold: 180, currency: 'USD', active: 1, armed: 0,
            last_fired_at: firedAt, last_fired_price: 182.5 },
        ],
        events: [
          { id: 1, alert_id: 1, symbol: 'AAPL', fired_at: firedAt, price: 182.5,
            message: 'AAPL superó tu objetivo de US$180 (llegó a US$182,5)',
            seen: _demoAlertsSeen ? 1 : 0 },
        ],
      }
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
        return fechaISO(d)
      })()
      return {
        tier: 'pro',
        period: 'week',
        analyses_count: 3,
        analyses_limit: 60,
        analyses_remaining: 57,
        hub_queries_count: 0,
        hub_queries_limit: 60,
        hub_queries_remaining: 60,
        // Pro → "No me interesa" ilimitado (limit/remaining null).
        diag_dismiss_count: 0,
        diag_dismiss_limit: null,
        diag_dismiss_remaining: null,
        resets_on: nextMonday,
        week_starts_on: nextMonday,
      }
    }
    if (basePath === '/plan/features') {
      // Demo siempre simula Pro para mostrar todas las features sin paywall
      return {
        tier: 'pro',
        limits: {
          brokers_max: null,
          brokers_current: 3,
          brokers_can_create: true,
          brokers_grandfather: false,
          insights_diagnostic_visible: null,
          behavioral_tags_visible: null,
        },
        access: {
          'ai.followup': true,
          'ai.hub': false,
          'comportamiento.full': true,
          'insights.distribucion_activo': true,
          'reportes.historicos': true,
          'export.csv': true,
          'tax.helper': false,
        },
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
          'operations',
          'operations.trade',
        ],
      }
    }
    // Insights endpoints opcionales — devuelven shape vacío para no romper
    // Fundamentals — ficha de scorecard por ticker.
    if (basePath.startsWith('/fundamentals/')) {
      const t = decodeURIComponent(basePath.slice('/fundamentals/'.length)).split('?')[0]
      return _buildDemoFundamentals(t)
    }
    // Diagnóstico → Performance. Antes `{}`: la tarjeta decía "Sin mediciones
    // todavía" y "TWRR · Acumulado 1A —" al lado de 30 meses de curva.
    if (basePath === '/insights/performance') return _demoPerformance(query)
    if (basePath.startsWith('/insights')) return {}
    if (basePath.startsWith('/goals'))    return []

    // ⚠️ SIN ESTO EL DEMO DECÍA "SIN MEDIR" EN TODOS LOS AÑOS. La ruta no estaba
    // interceptada, así que caía en el `return null` de abajo y la pantalla leía
    // "no hay años" — mientras las barras de los meses SÍ se dibujaban, porque
    // `/reports/timeline` sí está cubierta. Visto en pantalla: los tres años con
    // "Sin medir · sin fotos a precio de mercado" al lado de sus doce barras.
    // Es la peor superficie donde podía pasar: el demo es lo único que ve alguien
    // que todavía no tiene cuenta, y le estábamos diciendo que no podemos medir.
    // El año se arma con `buildDemoPeriodReport`, que ya existía para la pestaña
    // Año — no hay un segundo generador.
    // ⚠️ ESTOS ONCE SE ESCAPABAN AL BACKEND REAL (medido 2026-09-25 recorriendo
    // todas las pantallas del demo). A un visitante sin sesión le volvía un 401:
    // Movimientos mostraba "Unauthorized" y Alertas "No pudimos leer tu
    // configuración". A uno CON sesión real le volvían SUS datos: sus
    // movimientos y sus plazos fijos sumados al total del demo. Ahora el demo
    // contesta todo y `api.js` no deja salir nada que no conozca.
    if (basePath === '/movements')              return _demoMovimientos()
    if (basePath === '/plazos-fijos')           return []
    if (basePath === '/futures')                return []
    if (basePath === '/bonds/cashflow/skips')   return []
    if (basePath === '/positions/split-check')  return { suggestions: [] }
    if (basePath === '/sections/archived')      return { archived: [] }
    if (basePath === '/market-brief/prefs')     return { enabled: false }
    if (basePath === '/me/advisor')             return { advisors: [], requests: [] }
    if (basePath === '/wallbit/status')         return { connected: false }
    if (basePath === '/advisor/alerts')         return { history: [] }
    if (basePath === '/fx-rates')               return _demoFxRates()

    if (basePath === '/reports/years') {
      const años = [...new Set(REPORTS_TIMELINE.map(r => parseInt(r.period_key.slice(0, 4), 10)))]
        .sort((a, b) => b - a)
      const hoy = new Date()
      return {
        broker: 'global',
        modo: 'certero',
        moneda: 'usd',
        historicos: true,
        years: años.map(y => {
          const r = buildDemoPeriodReport('year', String(y))
          const m = r.metrics || {}
          const finVentana = r.is_current
            ? hoyISO()
            : `${y}-12-31`
          return {
            year: y,
            is_current: !!r.is_current,
            pct: m.delta_pct ?? null,
            usd: m.delta_usd ?? null,
            start_value: m.start_value ?? null,
            end_value: m.end_value ?? null,
            basis: 'mercado',
            basis_incomparable: false,
            motivo: null,
            motivo_texto: null,
            medido_desde: `${y - 1}-12-31`,
            medido_hasta: finVentana,
            bench_desde: `${y - 1}-12-31`,
            bench_hasta: finVentana,
            // El demo no simula el índice ni el INDEC: publica el EXCESO contra el
            // S&P que ya traía y deja el retorno propio del benchmark en null, que
            // es como la pantalla distingue "no lo tengo" de "dio cero".
            sp500_return_pct: null,
            vs_sp500_pct: m.vs_sp500_pct ?? null,
            // ⚠️ EL VEREDICTO CONTRA LA INFLACIÓN NO SE PUBLICA EN DEMO. Se mide
            // SIEMPRE en pesos (`twr.vs_inflacion_ar`) y para eso hace falta la serie
            // de dólar por fecha, que el demo no tiene. El fixture traía un
            // `vs_inflation_pct` viejo calculado como `retorno − 80`, o sea la resta
            // en unidades distintas que el producto acaba de dejar de hacer: se veía
            // "vs inflación −76,1 pp" en la pantalla que existe para convencer a
            // alguien de abrir la cuenta.
            inflation_pct: null,
            vs_inflation_pct: null,
            retorno_ars_pct: null,
            deposits: m.deposits ?? 0,
            withdrawals: m.withdrawals ?? 0,
            realized_pnl: m.realized_pnl ?? 0,
            trades_count: m.trades_count ?? 0,
            win_rate: m.win_rate ?? null,
            meses_del_anio: r.is_current ? hoy.getMonth() + 1 : 12,
          }
        }),
      }
    }
    return null
  }

  // ── POST / PUT / DELETE ────────────────────────────────────────────────────
  // El demo soporta dos acciones con persistencia local (overlay):
  //   - watchlist (agregar/quitar)
  //   - posiciones (agregar manual)
  // El resto devuelve { __demoBlocked: true } para que api.js lance un Error
  // con mensaje claro y el componente lo muestre como toast/error inline.

  // ⚠️ LO QUE EL VISITANTE GUARDA A MANO SE BLOQUEA, NO SE "APRUEBA" EN SILENCIO.
  // El `{ ok: true }` del final contestaba "listo" a 95 escrituras: registrar un
  // depósito, crear una alerta, un objetivo o un plazo fijo, conectar Wallbit…
  // La pantalla decía "Listo" y al recargar no había nada. Y "Suscribirme" en
  // Planes terminaba en "No pudimos generar el checkout". Se bloquea con el
  // mismo mensaje que ya usan vender o importar: "creá una cuenta".
  // Quedan en silencio sólo las escrituras de FONDO, que nadie pidió a mano
  // (la foto del día, el no realizado, la telemetría, "marcar visto").
  if (_esEscrituraDelVisitante(method, basePath)) return blocked()

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
        added_at: hoyISO(),
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
    const entry_date = body.entry_date || hoyISO()
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

  // ── Fundamentals AI summary: resumen canned por ticker
  if (method === 'POST' && basePath === '/fundamentals/ai-summary') {
    return _buildDemoAISummary(body?.ticker)
  }

  // ── AI chat: respuestas canned ESTRUCTURADAS (bloque ---RENDI---) para que
  //    el demo muestre el diseño nuevo (veredicto + tarjetas + repreguntas).
  if (basePath === '/ai/chat') {
    const _q = ((body?.messages || []).filter(m => m.role === 'user').pop()?.content || '').toLowerCase()
    // ── Registro por chat v2 (demo del form/confirm, stateless por matching) ──
    // "compré ..." → form de faltantes; "broker: ..." (submit del form) →
    // confirmación con botones; "sí, confirmá" → registrado (demo no escribe).
    if (/\bcompr[eé](?=\s|$)/.test(_q) && !_q.includes('broker:')) {
      return {
        tier: 'pro',
        reply: 'Anotado: compra de TSLA por ARS 300.000. Me faltan dos datos:\n---RENDI---{"blocks":[{"type":"form","title":"Completá el registro","subtitle":"TSLA · compra · ARS 300.000","fields":[{"k":"broker","label":"¿En qué broker?","kind":"select","options":["Cocos","Balanz","Binance"]},{"k":"precio","label":"Precio de compra","kind":"number","unit":"ARS","hint":"El precio al que operaste, por unidad"}],"submitLabel":"Completar registro"}]}',
      }
    }
    if (_q.includes('broker:')) {
      return {
        tier: 'pro',
        reply: 'Listo, quedaría así:\n---RENDI---{"blocks":[{"type":"confirm","title":"Compra de TSLA","rows":[["Operación","Compra"],["Activo","TSLA"],["Broker","Cocos"],["Cantidad","16,08 CEDEARs"],["Precio","ARS 18.650"],["Total","ARS 300.000"]],"yes":"Confirmar compra","no":"Corregir"}]}',
      }
    }
    if (/^s[ií](?=[\s,.!]|$)/.test(_q.trim())) {
      return {
        tier: 'pro',
        reply: '✅ (Demo) Compra registrada: 16,08 TSLA en Cocos. En tu cuenta real, la Cartera se actualiza al instante.',
        portfolio_changed: false,
      }
    }
    if (_q.includes('riesgo') || _q.includes('concentr') || _q.includes('sesgo')) {
      return { tier: 'pro', reply: _respuestaRiesgoDemo() }
    }
    // ⚠️ CALCULADA CON EL DEMO, NO ESCRITA A MANO. La respuesta fija decía "vale
    // US$ 41.416", "NVDA pesa el 28 %", "~45 % en efectivo" y un YTD inventado:
    // en la pantalla de al lado NVDA era el 15 % y el efectivo el 5 %. Todos los
    // botones "Analizar" del demo terminan acá.
    return { tier: 'pro', reply: _respuestaChatDemo() }
  }

  // ── AI v2 analyze: mocks por topic (datos consistentes con la fixture demo)
  if (method === 'POST' && basePath === '/ai/analyze') {
    const topic = (body?.screen || '').toLowerCase()
    const followupQ = (body?.followup_question || '').trim()
    let result
    if (followupQ) {
      // Mock de follow-up: armamos respuesta corta interpretativa
      result = buildDemoFollowup(topic, followupQ)
    } else if (topic === 'behavioral.card') {
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
      return fechaISO(d)
    })()
    return {
      result: _rellenarTextosDemo(result),
      cached: false,
      tier: 'pro',
      usage: {
        tier: 'pro',
        period: 'week',
        analyses_count: 3,
        analyses_limit: 60,
        analyses_remaining: 57,
        hub_queries_count: 0,
        hub_queries_limit: 60,
        hub_queries_remaining: 60,
        resets_on: nextMonday,
      },
    }
  }
  // Invalidar cache → no-op (los mocks son determinísticos, no hay cache)
  if (method === 'DELETE' && basePath.startsWith('/ai/cache/')) {
    return { deleted: 0 }
  }

  // Marcar alertas como vistas → apaga el badge del sidebar en el demo.
  if (method === 'POST' && basePath === '/alerts/events/seen') {
    _demoAlertsSeen = true
    return { ok: true }
  }

  // "No me interesa" del diagnóstico (cuota Free 2/sem). El frontend solo pega
  // acá para Free (paid rota local). El demo actual es tier 'pro' → NO se llama
  // (queda dormido). Si algún día se hace un demo Free, este mock simula la
  // cuota: 2 OK, la 3ª → 429 con upgrade payload. Contador se resetea al recargar.
  if (method === 'POST' && basePath === '/diagnostics/dismiss') {
    _demoDiagDismissCount += 1
    const limit = 2
    if (_demoDiagDismissCount > limit) {
      return { __demoHttpError: { status: 429, payload: { detail: {
        error: 'diag_dismiss_quota_exceeded',
        message: `Usaste tus ${limit} personalizaciones del diagnóstico de esta semana. Con Plus las descartás sin límite.`,
        usage: { tier: 'free', diag_dismiss_count: limit, diag_dismiss_limit: limit, diag_dismiss_remaining: 0 },
        upgrade: { available: true, current_tier: 'free', target_tier: 'plus', resets_on: null, benefits: [
          'Personalizá tu diagnóstico sin límite (descartá lo que no te sirve)',
          'Hasta 3 brokers (vs 1 en Free)',
          'Reportes históricos + Export CSV',
          '9× más Chat con Rendi AI',
        ] },
      } } } }
    }
    return { ok: true, usage: { tier: 'free', diag_dismiss_count: _demoDiagDismissCount, diag_dismiss_limit: limit, diag_dismiss_remaining: limit - _demoDiagDismissCount } }
  }

  // Default: 200 ok silencioso para no romper handlers no mapeados
  return { ok: true }
}

// ─── Comportamiento con los números del demo ────────────────────────────────
// ⚠️ LAS TARJETAS ESTABAN ESCRITAS PARA OTRA CARTERA (US$ 22.300, 14
// operaciones con 8 ganadoras, "9 % en efectivo", "6 % AR") y la pantalla de
// al lado mostraba otra: 5 % de efectivo, 13 % argentino, 64 % de acierto. Se
// conservan los textos y la bibliografía; los datos se recalculan acá.
function _comportamientoDemo() {
  const out = JSON.parse(JSON.stringify(BEHAVIORAL_INSIGHTS))
  const broker = (n) => BROKERS.find(b => b.name === n)
  const valorDe = (p) => computeBrokerValue([p], PRICES, broker(p.broker), _DEMO_TC_MEP, _DEMO_TC_MEP, _DEMO_TC_CRIPTO, 'purchase').value
  const filas = POSITIONS.map(p => ({ ...p, value_usd: valorDe(p) }))
  const total = _VALUACION.valor
  const r1 = (n) => Math.round(n * 10) / 10
  const r2 = (n) => Math.round(n * 100) / 100
  const pct = (v) => r1((v / total) * 100)
  const usdOp = (o, precio) => (o.broker === 'Cocos' ? precio * o.quantity / _TC_OPS_AR : precio * o.quantity)
  const ganadoras = OPERATIONS.filter(o => o.pnl_usd > 0)
  const perdedoras = OPERATIONS.filter(o => o.pnl_usd <= 0)
  const prom = (xs, f) => (xs.length ? xs.reduce((s, x) => s + f(x), 0) / xs.length : 0)
  const card = (code) => out.cards.find(c => c.code === code)

  const disp = card('disposition_effect')
  if (disp) { disp.evidence.winners_count = ganadoras.length; disp.evidence.losers_count = perdedoras.length }

  const over = card('overtrade')
  if (over) {
    const primera = [...OPERATIONS].map(o => o.date).sort()[0]
    const dias = Math.max(1, Math.round((Date.parse(hoyISO()) - Date.parse(primera)) / 86_400_000))
    const anios = dias / 365
    const nocional = OPERATIONS.reduce((s, o) => s + usdOp(o, o.exit_price), 0)
    const capitalProm = MONTHLY.filter(m => m.broker === 'global').slice(-12).reduce((s, m, _i, a) => s + m.capital_final / a.length, 0)
    const rotacion = nocional / (capitalProm || 1) / anios
    Object.assign(over.evidence, { total_trades: OPERATIONS.length, period_days: dias, period_years: r2(anios),
      annual_ops: r1(OPERATIONS.length / anios), annual_turnover: r2(rotacion), total_notional: Math.round(nocional), capital_avg: Math.round(capitalProm) })
    over.value_label = `${rotacion.toFixed(2).replace('.', ',')}× / año`
    over.one_liner = `Tu cartera rota ${rotacion.toFixed(2).replace('.', ',')}× por año (${OPERATIONS.length} operaciones en ${Math.round(dias / 30)} meses). Estás en el rango del inversor de mediano plazo.`
  }

  const loss = card('loss_aversion')
  if (loss) {
    const tamGan = prom(ganadoras, o => usdOp(o, o.entry_price))
    const tamPer = prom(perdedoras, o => usdOp(o, o.entry_price))
    const ratio = tamPer / (tamGan || 1)
    Object.assign(loss.evidence, { winners_count: ganadoras.length, losers_count: perdedoras.length,
      winners_avg_size_usd: Math.round(tamGan), losers_avg_size_usd: Math.round(tamPer), ratio: r1(ratio) })
    loss.value_label = `losers ${ratio.toFixed(1).replace('.', ',')}× winners`
    loss.one_liner = `El tamaño promedio de tus perdedoras es ${ratio.toFixed(1).replace('.', ',')}× el de tus ganadoras.${ratio > 1.2 ? ' Vale revisar criterios de salida.' : ' No hay señal de aguantar perdedoras grandes.'}`
    loss.detected = ratio > 1.2
    loss.severity = ratio > 1.2 ? 'medium' : 'positive'
  }

  const conc = card('concentration')
  if (conc) {
    const inv = filas.filter(p => !p.is_cash).sort((a, b) => b.value_usd - a.value_usd)
    const suma = (xs) => xs.reduce((s, p) => s + p.value_usd, 0)
    const top1 = pct(suma(inv.slice(0, 1)))
    const top3 = pct(suma(inv.slice(0, 3)))
    conc.title = `${inv[0].asset} es tu posición más grande`
    conc.value_label = `Top 1: ${top1.toFixed(0)} %`
    conc.one_liner = `Top 1 = ${top1.toFixed(0)} %, Top 3 = ${top3.toFixed(0)} %.${top3 > 50 ? ' La cartera depende mucho de pocos activos.' : ''}`
    Object.assign(conc.evidence, { top_asset: inv[0].asset, top1_pct: top1, top3_pct: top3, top5_pct: pct(suma(inv.slice(0, 5))),
      total_assets: inv.length, total_value_usd: Math.round(total),
      top_5: inv.slice(0, 5).map(p => ({ asset: p.asset, value_usd: Math.round(p.value_usd), pct: pct(p.value_usd) })) })
  }

  const infl = card('inflation_loss')
  if (infl) {
    const cash = POSITIONS.find(p => p.is_cash && p.broker === 'Cocos')
    const claves = Object.keys(BENCHMARKS.inflation_ar).sort().slice(-12)
    const acum = claves.reduce((f, k) => f * (1 + BENCHMARKS.inflation_ar[k] / 100), 1) - 1
    const pesos = cash ? cash.quantity : 0
    const perdida = pesos * (1 - 1 / (1 + acum))
    const usd = perdida / _DEMO_TC_MEP
    Object.assign(infl.evidence, { cash_ars_pesos: pesos, inflation_cum_pct: r1(acum * 100), loss_pesos: Math.round(perdida), loss_usd: r2(usd) })
    infl.value_label = `−US$ ${Math.round(usd)}`
    infl.one_liner = `En 12 meses, la inflación le sacó ~US$ ${Math.round(usd)} de poder de compra a tus pesos quietos. Considerá MEP, Lecaps en pesos o CEDEARs para cubrirte.`
  }

  const cf = card('counterfactual')
  if (cf) {
    const precioHoy = (o) => (o.broker === 'Cocos' ? PRICES[`${o.asset}.BA`] : PRICES[o.asset])
    const analizadas = OPERATIONS.filter(o => precioHoy(o) != null)
    const deltas = analizadas.map(o => ({ o, delta: usdOp(o, precioHoy(o)) - usdOp(o, o.exit_price) }))
    const deltaTotal = deltas.reduce((s, d) => s + d.delta, 0)
    const realizado = analizadas.reduce((s, o) => s + o.pnl_usd, 0)
    Object.assign(cf.evidence, { realized_total_usd: Math.round(realizado), hypothetical_total_usd: Math.round(realizado + deltaTotal),
      delta_total_usd: Math.round(deltaTotal), trades_analyzed: analizadas.length,
      top_misses: deltas.filter(d => d.delta > 0).sort((a, b) => b.delta - a.delta).slice(0, 5).map(({ o, delta }) => ({
        asset: o.asset, exit_price: o.exit_price, current_price: precioHoy(o), delta_usd: Math.round(delta), exit_date: o.date })) })
    cf.value_label = `${deltaTotal >= 0 ? '+' : '−'}US$ ${Math.abs(Math.round(deltaTotal))}`
    cf.one_liner = deltaTotal >= 0
      ? `Sumando todas tus ventas, hubieras hecho ~US$ ${Math.round(deltaTotal)} más si mantenías (algunas bajaron después, otras subieron).`
      : `Sumando todas tus ventas, vender te ahorró ~US$ ${Math.abs(Math.round(deltaTotal))}: en conjunto, lo vendido bajó después.`
  }

  const wr = card('winrate_payoff')
  if (wr) {
    const tasa = (ganadoras.length / OPERATIONS.length) * 100
    const promGan = prom(ganadoras, o => o.pnl_usd)
    const promPer = Math.abs(prom(perdedoras, o => o.pnl_usd))
    const payoff = promGan / (promPer || 1)
    const esperanza = prom(OPERATIONS, o => o.pnl_usd)
    Object.assign(wr.evidence, { win_rate_pct: r1(tasa), winners_count: ganadoras.length, losers_count: perdedoras.length,
      total_trades: OPERATIONS.length, avg_win_usd: r2(promGan), avg_loss_usd: r2(promPer), payoff_ratio: r2(payoff), expectancy_usd: r2(esperanza) })
    wr.value_label = `${tasa.toFixed(0)} % · payoff ${payoff.toFixed(2).replace('.', ',')}×`
    wr.one_liner = `Win rate ${tasa.toFixed(0)} % con payoff ${payoff.toFixed(2).replace('.', ',')}× = esperanza de ${esperanza >= 0 ? '+' : '−'}US$ ${Math.abs(esperanza).toFixed(2).replace('.', ',')} por operación.`
  }

  const home = card('home_bias')
  if (home) {
    const ar = _VALUACION.porBroker.Cocos || 0
    home.value_label = `${pct(ar).toFixed(0)} % AR`
    home.one_liner = `${pct(ar).toFixed(0)} % en Argentina y ${(100 - pct(ar)).toFixed(0)} % afuera. Si tu vida es en pesos (gastos, salario), podés sumar exposición local como cobertura natural.`
    Object.assign(home.evidence, { ar_pct: pct(ar), intl_pct: r1(100 - pct(ar)), ar_value_usd: Math.round(ar), intl_value_usd: Math.round(total - ar), total_value_usd: Math.round(total) })
  }

  const cash = card('cash_drag')
  if (cash) {
    const enCaja = filas.filter(p => p.is_cash)
    const cajaUsd = enCaja.reduce((s, p) => s + p.value_usd, 0)
    const cajaArs = enCaja.filter(p => p.broker === 'Cocos').reduce((s, p) => s + p.value_usd, 0)
    cash.value_label = `${pct(cajaUsd).toFixed(0)} % en cash`
    cash.one_liner = `${pct(cajaUsd).toFixed(0)} % en cash — colchón razonable para liquidez sin perder oportunidades.`
    Object.assign(cash.evidence, { cash_pct: pct(cajaUsd), cash_ars_pct: pct(cajaArs), cash_usd_amount: Math.round(cajaUsd - cajaArs),
      cash_ars_usd_equiv: Math.round(cajaArs), invested_usd: Math.round(total - cajaUsd), total_usd: Math.round(total) })
  }

  const rec = card('recency_bias')
  if (rec) {
    rec.evidence.total_invested_usd = Math.round(_VALUACION.costo)
    rec.evidence.chase_pct = r1((rec.evidence.chase_pumps_invested_usd / _VALUACION.costo) * 100)
    rec.value_label = `${rec.evidence.chase_pct.toFixed(0)} % del invertido`
    rec.one_liner = `${rec.evidence.chase_pct.toFixed(0)} % de lo invertido se compró alto. Magnitud baja, no es un patrón sistemático.`
  }

  const sec = card('sector_concentration')
  if (sec) {
    const b = computeSectorBreakdown(filas.map(p => ({ ...p, value_usd: p.value_usd })), BROKERS)
    const it = b.items || []
    if (it.length) {
      const top3 = it.slice(0, 3).reduce((s, x) => s + x.pct, 0)
      sec.title = `${it[0].label} pesa fuerte en tu cartera`
      sec.value_label = `${it[0].label}: ${it[0].pct.toFixed(0)} %`
      sec.one_liner = `${it[0].label} = ${it[0].pct.toFixed(0)} % · Top 3 sectores = ${top3.toFixed(0)} %. Diversificar entre sectores reduce el riesgo idiosincrático.`
      Object.assign(sec.evidence, { top_sector: it[0].label, top1_pct: r1(it[0].pct), top3_pct: r1(top3), total_sectors: it.length,
        total_value_usd: Math.round(b.total), unmapped_count: (b.unclassified?.assets || []).length,
        breakdown: it.map(x => ({ sector: x.label, value_usd: Math.round(x.value), pct: r1(x.pct) })) })
    }
  }

  const detectadas = out.cards.filter(c => c.detected)
  out.summary = {
    total_detected: detectadas.length,
    total_high: out.cards.filter(c => c.severity === 'high').length,
    total_medium: out.cards.filter(c => c.severity === 'medium').length,
    total_positive: out.cards.filter(c => c.severity === 'positive').length,
    total_cards: out.cards.length,
  }
  out.generated_at = new Date().toISOString()
  return out
}

// ─── Hechos del demo para los textos de la IA ────────────────────────────────
// Un solo lugar: los textos enlatados leen estos números en vez de afirmar
// los suyos. Todo sale de la misma valuación que la pantalla (`_VALUACION`).
function _hechosDelDemo() {
  const broker = (n) => BROKERS.find(b => b.name === n)
  const valorDe = (p) => computeBrokerValue([p], PRICES, broker(p.broker), _DEMO_TC_MEP, _DEMO_TC_MEP, _DEMO_TC_CRIPTO, 'purchase').value
  const filas = POSITIONS.map(p => ({ ...p, valor: valorDe(p) }))
  const total = _VALUACION.valor || 1
  const invertidas = filas.filter(p => !p.is_cash).sort((a, b) => b.valor - a.valor)
  const pesoDe = (xs) => (xs.reduce((s, p) => s + p.valor, 0) / total) * 100
  const cripto = new Set(['BTC', 'ETH', 'SOL'])
  const mejor = [...OPERATIONS].sort((a, b) => b.pnl_pct - a.pnl_pct)[0]
  const g = MONTHLY.filter(m => m.broker === 'global')
  const aportado = (g[0]?.capital_inicio || 0) + g.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)
  const anio = buildDemoPeriodReport('year', String(new Date().getFullYear()))?.metrics || {}
  return {
    valor: _VALUACION.valor,
    noRealizadoPct: ((_VALUACION.valor - _VALUACION.costo) / (_VALUACION.costo || 1)) * 100,
    gananciaTotal: _VALUACION.valor - aportado,
    top: { asset: invertidas[0]?.asset, peso: pesoDe(invertidas.slice(0, 1)) },
    top3: pesoDe(invertidas.slice(0, 3)),
    top3Activos: invertidas.slice(0, 3).map(p => ({ asset: p.asset, peso: pesoDe([p]) })),
    efectivo: pesoDe(filas.filter(p => p.is_cash)),
    cripto: pesoDe(filas.filter(p => cripto.has(p.asset))),
    mejor,
    anioPct: anio.delta_pct,
    anioVsSp: anio.vs_sp500_pct,
    operaciones: OPERATIONS.length,
    ganadoras: OPERATIONS.filter(o => o.pnl_usd > 0).length,
  }
}
const _pctDemo = (x, dec = 1) => (x == null ? '—' : `${x >= 0 ? '+' : ''}${x.toFixed(dec).replace('.', ',')}%`)
const _usdDemo = (n) => `US$ ${Math.round(n).toLocaleString('es-AR')}`

function _respuestaChatDemo() {
  const h = _hechosDelDemo()
  const texto = `La cartera demo vale ${_usdDemo(h.valor)} y lleva ${_pctDemo(h.noRealizadoPct)} de ganancia no realizada sobre lo invertido. `
    + `La posición más grande es ${h.top.asset} (${h.top.peso.toFixed(0)} % de la cartera) y las tres principales suman ${h.top3.toFixed(0)} %. `
    + `La mejor operación cerrada fue ${h.mejor.asset} (${_pctDemo(h.mejor.pnl_pct, 0)}). El efectivo es el ${h.efectivo.toFixed(0)} % y la cripto el ${h.cripto.toFixed(0)} %.`
    + '\n\n(Modo demo: creá una cuenta para usar Rendi AI con tu cartera real.)'
  const bloques = [{ type: 'alloc', title: 'Composición de tu cartera', items: [
    ...h.top3Activos.map(a => ({ l: a.asset, pct: Math.round(a.peso) })),
    { l: 'Otros', pct: Math.max(0, Math.round(100 - h.top3 - h.efectivo)) },
    { l: 'Efectivo', pct: Math.round(h.efectivo) },
  ] }]
  if (h.anioPct != null && h.anioVsSp != null) {
    const sp = h.anioPct - h.anioVsSp
    const escala = Math.max(Math.abs(h.anioPct), Math.abs(sp), 1)
    bloques.unshift({ type: 'compare', title: `Tu cartera vs S&P 500 · ${new Date().getFullYear()}`, items: [
      { l: 'Tu cartera', v: _pctDemo(h.anioPct), pct: Math.round((Math.abs(h.anioPct) / escala) * 90) },
      { l: 'S&P 500', v: _pctDemo(sp), pct: Math.round((Math.abs(sp) / escala) * 90) },
    ] })
  }
  const rendi = {
    verdict: h.gananciaTotal >= 0 ? 'Buen momento' : 'A revisar',
    tone: h.gananciaTotal >= 0 ? 'pos' : 'neg',
    headline: `La cartera vale ${_usdDemo(h.valor)}, ${_pctDemo(h.noRealizadoPct)} no realizado, con ${h.top.asset} como posición más grande.`,
    stats: [
      { l: 'Valor hoy', v: _usdDemo(h.valor), t: 'neutral' },
      { l: 'P&L no realizado', v: _pctDemo(h.noRealizadoPct), t: h.noRealizadoPct >= 0 ? 'pos' : 'neg' },
      { l: 'Mayor posición', v: `${h.top.asset} · ${h.top.peso.toFixed(0)} %`, t: h.top.peso > 25 ? 'warn' : 'neutral' },
    ],
    blocks: bloques,
    followups: ['¿Qué riesgos detectás en mi cartera?', '¿Cómo evalúo mi win rate?', '¿Cómo vengo contra el S&P 500?'],
    sources: [`${POSITIONS.filter(p => !p.is_cash).length} posiciones`, `${BROKERS.length} brokers`, 'datos de la demo'],
  }
  return `${texto}\n---RENDI---${JSON.stringify(rendi)}`
}

function _respuestaRiesgoDemo() {
  const h = _hechosDelDemo()
  const golpe = (h.top.peso * 0.15).toFixed(1).replace('.', ',')
  const texto = `Tu mayor riesgo hoy es la concentración: ${h.top.asset} pesa el ${h.top.peso.toFixed(0)} % de la cartera y las tres principales, el ${h.top3.toFixed(0)} %. `
    + `Si ${h.top.asset} corrige 15 %, el golpe directo a la cartera es de ~${golpe} puntos. `
    + `La cripto suma el ${h.cripto.toFixed(0)} %: es la parte más volátil. El efectivo (${h.efectivo.toFixed(0)} %) amortigua poco.`
    + '\n\n(Modo demo: creá una cuenta para usar Rendi AI con tu cartera real.)'
  const rendi = {
    verdict: h.top3 > 50 ? 'Concentrada' : 'Diversificada', tone: h.top3 > 50 ? 'warn' : 'neutral',
    headline: `${h.top.asset} es el ${h.top.peso.toFixed(0)} % de la cartera; las tres principales, el ${h.top3.toFixed(0)} %.`,
    stats: [
      { l: 'Mayor posición', v: `${h.top.asset} · ${h.top.peso.toFixed(0)} %`, t: 'warn' },
      { l: 'Top 3', v: `${h.top3.toFixed(0)} %`, t: h.top3 > 50 ? 'warn' : 'neutral' },
      { l: 'Cripto', v: `${h.cripto.toFixed(0)} %`, t: 'neutral' },
    ],
    blocks: [],
    followups: ['¿Cómo evalúo mi win rate?', '¿Cómo vengo contra el S&P 500?'],
    sources: ['datos de la demo'],
  }
  return `${texto}\n---RENDI---${JSON.stringify(rendi)}`
}

// ─── Textos enlatados con los números del demo ───────────────────────────────
// ⚠️ LOS TEXTOS ESTABAN ESCRITOS PARA OTRA CARTERA ("US$ 8.3K", "NVDA pesa el
// 28 %", "45 % en cash"): en la pantalla de al lado la cartera valía US$ 41.500,
// NVDA el 15 % y el efectivo el 5 %, y los análisis concluían que "casi la mitad
// del capital no participó del rally". Los números van como {{MARCA}} y se
// completan acá, con la misma valuación que la pantalla.
function _marcasDemo() {
  const h = _hechosDelDemo()
  const broker = (n) => BROKERS.find(b => b.name === n)
  const valorDe = (p) => computeBrokerValue([p], PRICES, broker(p.broker), _DEMO_TC_MEP, _DEMO_TC_MEP, _DEMO_TC_CRIPTO, 'purchase').value
  const pesoDe = (asset) => POSITIONS.filter(p => p.asset === asset && !p.is_cash && p.broker !== 'Cocos').reduce((s, p) => s + valorDe(p), 0) / (h.valor || 1) * 100
  const nvda = POSITIONS.find(p => p.asset === 'NVDA')
  const nvdaPnl = nvda ? ((PRICES.NVDA * nvda.quantity) / nvda.invested - 1) * 100 : 0
  const nvdaPeso = pesoDe('NVDA')
  const k = (n) => `US$ ${(n / 1000).toFixed(1).replace('.', ',')}K`
  const pts = (n) => n.toFixed(1).replace('.', ',')
  const pctTxtDemo = (n) => `${Math.round(n)} %`
  // Peor retroceso de los últimos 12 meses, con las fotos diarias.
  const desde = (() => { const d = new Date(); d.setFullYear(d.getFullYear() - 1); return fechaISO(d) })()
  const serie = [...SNAPSHOTS].filter(x => x.date >= desde).sort((a, b) => (a.date < b.date ? -1 : 1))
  let pico = 0, peor = 0
  for (const x of serie) { pico = Math.max(pico, x.total_value); peor = Math.min(peor, x.total_value / pico - 1) }
  const g = MONTHLY.filter(m => m.broker === 'global')
  const aportado = (g[0]?.capital_inicio || 0) + g.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)
  const spAnio = h.anioPct != null && h.anioVsSp != null ? h.anioPct - h.anioVsSp : null
  return {
    ANIO: _pctDemo(h.anioPct),
    SP_ANIO: _pctDemo(spAnio),
    GAP_ANIO: h.anioVsSp == null ? '—' : `${h.anioVsSp >= 0 ? '+' : '−'}${pts(Math.abs(h.anioVsSp))} puntos`,
    VALOR: k(h.valor),
    APORTADO: k(aportado),
    GANANCIA: k(h.valor - aportado),
    NVDA: pctTxtDemo(nvdaPeso),
    NVDA_PNL: _pctDemo(nvdaPnl, 0),
    NVDA_25: pts(nvdaPeso * 0.25),
    NVDA_25_USD: _usdDemo(h.valor * nvdaPeso / 100 * 0.25),
    NVDA_8: pts(nvdaPeso * 0.08),
    NVDA_AAPL: pctTxtDemo(nvdaPeso + pesoDe('AAPL')),
    CASH: pctTxtDemo(h.efectivo),
    CASH_COSTO: pts(h.efectivo * 0.10),
    CASH_GAP: pts(spAnio != null ? Math.abs(spAnio) * h.efectivo / 100 : 0),
    CRIPTO: pctTxtDemo(h.cripto),
    AR: pctTxtDemo(((_VALUACION.porBroker.Cocos || 0) / (h.valor || 1)) * 100),
    SCHWAB: pctTxtDemo(((_VALUACION.porBroker.Schwab || 0) / (h.valor || 1)) * 100),
    TOP1: h.top.asset,
    TOP1_PCT: pctTxtDemo(h.top.peso),
    TOP1_25: pts(h.top.peso * 0.25),
    DD: `${(peor * 100).toFixed(1).replace('.', ',')} %`,
  }
}

function _rellenarTextosDemo(obj) {
  const marcas = _marcasDemo()
  const rellenar = (v) => {
    if (typeof v === 'string') return v.replace(/\{\{([A-Z0-9_]+)\}\}/g, (m, key) => (key in marcas ? String(marcas[key]) : m))
    if (Array.isArray(v)) return v.map(rellenar)
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([kk, vv]) => [kk, rellenar(vv)]))
    return v
  }
  return rellenar(obj)
}

// ─── /insights/performance del demo ──────────────────────────────────────────
// La misma forma que `performance.performance` del backend, armada con las
// fotos diarias: índice encadenado con Dietz tramo a tramo, el punto "hoy" con
// el valor vivo, el benchmark indexado a 1 en la misma fecha y las caídas.
function _demoPerformance(query) {
  const q = new URLSearchParams(query || '')
  const benchKey = q.get('bench') || 'sp500'
  const moneda = String(q.get('moneda') || 'usd').toLowerCase() === 'ars' ? 'ars' : 'usd'
  const desde = q.get('desde') || null
  const hasta = q.get('hasta') || null
  const vivo = q.get('valor_live') != null && q.get('valor_live') !== '' ? Number(q.get('valor_live')) : null
  const hoy = hoyISO()
  const fx = (fecha) => (moneda === 'ars' ? (BENCHMARKS.dolar_blue[String(fecha).slice(0, 7)] || _DEMO_TC_BLUE) : 1)
  const filas = [...SNAPSHOTS]
    .filter(x => x.apto && x.date < hoy && (!desde || x.date >= desde) && (!hasta || x.date <= hasta))
    .sort((a, b) => (a.date < b.date ? -1 : 1))
  if (filas.length < 2) {
    return { curva: [], benchmark: [], benchmark_key: benchKey, moneda, twr: null, cagr: null,
      motivo: 'sin_mediciones', motivo_texto: 'Todavía no hay dos cierres medidos.' }
  }
  const curva = []
  let idx = 1
  let pico = 1
  let ddMax = 0
  let ddFecha = null
  let ddPico = null
  let fechaPico = filas[0].date
  const empujar = (fecha, valor, aportado, previo) => {
    let ret = null
    if (previo) {
      const flujo = aportado - previo.aportado
      const den = previo.valor + 0.5 * flujo
      ret = den > 0 ? (valor - previo.valor - flujo) / den : 0
      idx *= 1 + ret
    }
    if (idx > pico) { pico = idx; fechaPico = fecha }
    const dd = idx / pico - 1
    if (dd < ddMax) { ddMax = dd; ddFecha = fecha; ddPico = fechaPico }
    curva.push({ date: fecha, index: +idx.toFixed(6), index_publicado: +idx.toFixed(6), valor_foto: null,
      fx: moneda === 'ars' ? fx(fecha === 'hoy' ? hoy : fecha) : null, value: +valor.toFixed(2), clase: 'medicion',
      apto: true, ret, estimado: false, base: 'mercado', segmento: 0, drawdown: +dd.toFixed(6) })
    return { valor, aportado }
  }
  let previo = null
  for (const x of filas) previo = empujar(x.date, x.total_value * fx(x.date), x.net_deposited * fx(x.date), previo)
  const ultimoAportado = MONTHLY.filter(m => m.broker === 'global')
    .reduce((s, m, i) => s + (i === 0 ? m.capital_inicio : 0) + (m.deposits || 0) - (m.withdrawals || 0), 0)
  if (vivo != null && !hasta) empujar('hoy', vivo * fx(hoy), ultimoAportado * fx(hoy), previo)
  // Benchmark indexado a 1 en la primera fecha de la curva (mensual, con arrastre).
  const serie = BENCHMARKS[benchKey] || {}
  const esPorcentual = benchKey === 'inflation_ar'
  const meses = Object.keys(serie).sort()
  const nivelEn = (ym) => {
    if (esPorcentual) {
      let f = 1
      for (const m of meses) { if (m > curva[0].date.slice(0, 7) && m <= ym) f *= 1 + serie[m] / 100 }
      return f
    }
    let v = null
    for (const m of meses) { if (m <= ym) v = serie[m]; else break }
    return v
  }
  const base = nivelEn(curva[0].date.slice(0, 7))
  const benchmark = curva.map(pt => {
    const n = nivelEn((pt.date === 'hoy' ? hoy : pt.date).slice(0, 7))
    return { date: pt.date, index: base && n != null ? +(n / base).toFixed(6) : null }
  })
  const desdeF = filas[0].date
  const hastaF = filas[filas.length - 1].date
  const dias = Math.max(1, Math.round((Date.parse(hoy) - Date.parse(desdeF)) / 86_400_000))
  const twr = idx - 1
  return {
    curva, benchmark, benchmark_key: benchKey, benchmark_resolucion: 'mensual',
    moneda, riel_fx: moneda === 'ars' ? 'blue' : null, contable: [],
    medido_desde: desdeF, medido_hasta: hastaF, cobertura: 1, cobertura_reconstruccion: null,
    instrumentos_al_costo: [], modo: q.get('modo') || 'certero', por_clase: { medicion: filas.length },
    tramos: 1, tramos_medidos: curva.length - 1, serie_partida: false, tramos_detalle: [],
    twr, cagr: dias >= 365 ? Math.pow(1 + twr, 365 / dias) - 1 : null,
    base_del_twr: 'mercado', excluye_no_realizado: false,
    ventana_desde: desdeF, ventana_hasta: vivo != null && !hasta ? hoy : hastaF,
    drawdown_actual: curva[curva.length - 1].drawdown, drawdown_maximo: +ddMax.toFixed(6),
    drawdown_maximo_fecha: ddFecha, drawdown_maximo_pico: ddPico,
    motivo: null, motivo_texto: null, cortes_dudosos: [], contable_superado: 0, contable_realineado: 0,
  }
}

// ─── Objetivo del demo ───────────────────────────────────────────────────────
// La meta es lo que la cartera del demo alcanza en 3 años con SU rendimiento
// histórico y SUS aportes promedio, redondeado para abajo: así el diagnóstico,
// el estado y los meses cuentan la misma historia.
function _objetivoDemo() {
  const meses = 36
  const valor = _VALUACION.valor
  const g = MONTHLY.filter(m => m.broker === 'global').slice(-12)
  const aporteMes = g.reduce((s, m) => s + (m.deposits || 0), 0) / (g.length || 1)
  const tasa = (DEMO_CAGR.cagr ?? 8) / 100
  const proyectar = (r, n, aporte) => {
    const rm = Math.pow(1 + r, 1 / 12) - 1
    let v = valor
    for (let i = 0; i < n; i++) v = v * (1 + rm) + aporte
    return v
  }
  const proyectado = proyectar(tasa, meses, aporteMes)
  const meta = Math.max(5000, Math.floor(proyectado / 5000) * 5000)
  let eta = 0
  while (proyectar(tasa, eta, aporteMes) < meta && eta < 600) eta++
  let lo = -0.5
  let hi = 2
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2
    if (proyectar(mid, meses, aporteMes) >= meta) hi = mid
    else lo = mid
  }
  const requerido = hi
  const f = new Date()
  f.setMonth(f.getMonth() + meses)
  const pct = (x) => `${(x * 100).toFixed(1).replace('.', ',')} %`
  const usd = (n) => `US$ ${Math.round(n).toLocaleString('es-AR')}`
  return {
    meta,
    fecha: fechaISO(f),
    rendimientoAsumido: Math.round(tasa * 100),
    diagnostico: {
      status: 'on_track',
      projected_value_at_target_date: Math.round(proyectado),
      eta_months_at_current_rate: eta,
      delta_pct_required: +((requerido - tasa) * 100).toFixed(1),
      months_left: meses,
      required_annual_pct: +(requerido * 100).toFixed(1),
      diagnostic: `A tu ritmo actual (${pct(tasa)} anual y ${usd(aporteMes)} de aporte por mes) llegás en ~${eta} meses: en fecha.`,
      suggestion: {
        code: 'aportes',
        title: 'Sostené los aportes',
        action: `La meta depende tanto del rendimiento como de aportar: con ${usd(aporteMes)} por mes llegás en fecha sin tener que buscar más rendimiento.`,
        evidence: `En los últimos 12 meses aportaste ${usd(aporteMes)} por mes en promedio y la cartera rindió ${pct(tasa)} anual.`,
      },
    },
  }
}

// ─── Escrituras del visitante (se bloquean) ──────────────────────────────────
// Las de FONDO siguen en silencio: nadie las pidió a mano y un error ahí sólo
// sería ruido (la foto diaria, el no realizado del mes, telemetría, "visto").
const _ESCRITURAS_DE_FONDO = new Set([
  'POST /snapshots',
  'POST /monthly/sync-unrealized',
  'POST /plan/track',
  'POST /alerts/events/seen',
  'POST /advisor/alerts/events/seen',
  'POST /auth/logout',
  'POST /feedback/recommendation',
])
const _BASES_DEL_VISITANTE = [
  '/cash', '/monthly', '/positions/group', '/conversions', '/bonds/cashflow',
  '/goals', '/wallbit', '/plazos-fijos', '/futures', '/alerts', '/movements',
  '/me', '/market-brief', '/assets', '/sections', '/billing', '/iol',
  '/advisor', '/admin', '/push', '/auth/investor-profile', '/ai/voz',
]
function _esEscrituraDelVisitante(method, path) {
  if (method === 'GET') return false
  if (_ESCRITURAS_DE_FONDO.has(`${method} ${path}`)) return false
  if (/^\/positions\/[^/]+\/adjust-ratio$/.test(path)) return true
  return _BASES_DEL_VISITANTE.some(b => path === b || path.startsWith(b + '/'))
}

// ─── /monthly con las posiciones que agregó el visitante ────────────────────
// ⚠️ LO QUE EL VISITANTE AGREGA ES PLATA QUE PUSO, NO GANANCIA. La posición
// agregada sumaba su valor a la cartera sin sumar aporte: 10 META a US$ 600
// pasaban "Hoy" a +14,8 % y "Ganancia total" de +51 % a +75 %, y quedaba así
// entre recargas. Su costo entra como aporte del mes en curso.
function _monthlyConAgregadas(overlay) {
  const agregadas = overlay?.positions || []
  const costo = agregadas.reduce((s, p) => {
    const broker = BROKERS.find(b => b.name === p.broker)
    if (!broker) return s
    return s + (computeBrokerValue([p], PRICES, broker, _DEMO_TC_MEP, _DEMO_TC_MEP, _DEMO_TC_CRIPTO, 'purchase').invested || 0)
  }, 0)
  if (!(costo > 0)) return MONTHLY
  return MONTHLY.map(m => (m === _ULTIMO_GLOBAL
    ? { ...m, deposits: m.deposits + costo, capital_final: m.capital_final + costo }
    : m))
}

// ─── /movements del demo ─────────────────────────────────────────────────────
// Misma forma que `_build_movements` del backend (main.py): aportes, compras de
// las posiciones abiertas y ventas cerradas con su P&L. Sale de los MISMOS
// fixtures que el resto de las pantallas, así que Movimientos cuenta la misma
// historia que el Dashboard.
function _demoMovimientos() {
  const pad = (n) => String(n).padStart(2, '0')
  const blueEn = (fecha) => BENCHMARKS.dolar_blue?.[String(fecha).slice(0, 7)] || _DEMO_TC_BLUE
  const base = { kind: 'movement', fees_usd: 0, notes: '', source: 'manual' }
  const filas = []
  const globals = MONTHLY.filter(m => m.broker === 'global')
  globals.forEach((m, i) => {
    const fecha = `${m.year}-${pad(m.month)}-01`
    if (i === 0 && m.capital_inicio > 0) {
      filas.push({ ...base, id: 'demo-dep-inicial', date: fecha, type: 'DEPOSIT', broker: 'Schwab', asset: '',
        quantity: null, unit_price: null, amount_usd: m.capital_inicio, currency: 'USD', notes: 'Capital inicial' })
    }
    if ((m.deposits || 0) > 0) {
      filas.push({ ...base, id: `demo-dep-${m.year}-${m.month}`, date: fecha, type: 'DEPOSIT', broker: 'Schwab', asset: '',
        quantity: null, unit_price: null, amount_usd: m.deposits, currency: 'USD', notes: 'Aporte' })
    }
  })
  for (const p of POSITIONS) {
    if (p.is_cash || !p.entry_date) continue
    const enPesos = p.broker === 'Cocos'
    filas.push({ ...base, id: `demo-pos-${p.id}`, date: p.entry_date, type: 'BUY', broker: p.broker, asset: p.asset,
      quantity: p.quantity, unit_price: p.buy_price, currency: enPesos ? 'ARS' : 'USD',
      amount_usd: enPesos ? p.invested / (p.tc_compra || blueEn(p.entry_date)) : p.invested })
  }
  for (const o of OPERATIONS) {
    const enPesos = o.broker === 'Cocos'
    const bruto = o.exit_price * o.quantity
    filas.push({ ...base, id: `demo-op-${o.id}`, date: o.date, type: 'SELL', broker: o.broker, asset: o.asset,
      quantity: o.quantity, unit_price: o.exit_price, currency: enPesos ? 'ARS' : 'USD',
      amount_usd: enPesos ? bruto / blueEn(o.date) : bruto, pnl_usd: o.pnl_usd })
  }
  return filas.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0))
}

// ─── /fx-rates del demo ──────────────────────────────────────────────────────
// La historia del dólar que usa la vista en pesos para convertir cada fecha con
// SU cotización. Sale de la misma serie blue de los benchmarks del demo.
function _demoFxRates() {
  const mepSobreBlue = (DOLAR.mep.venta || 1424) / (DOLAR.blue.venta || 1415)
  const filas = Object.entries(BENCHMARKS.dolar_blue || {})
    .map(([mes, blue]) => ({ date: `${mes}-01`, blue, mep: Math.round(blue * mepSobreBlue) }))
  filas.push({ date: hoyISO(), blue: DOLAR.blue.venta, mep: DOLAR.mep.venta })
  return filas.sort((a, b) => (a.date < b.date ? -1 : 1))
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
  // ⚠️ FIJA POR ACTIVO Y TERMINA EN EL PRECIO DE HOY. Antes era azar nuevo en
  // cada pedido y el último cierre no era el precio de la Cartera (NVDA cerraba
  // entre 167,84 y 178,48 contra un precio de 178,50). Se camina hacia ATRÁS
  // desde el precio actual con una semilla por activo y período.
  const actual = PRICES[symbol] || PRICES[symbol.replace('-USD', '')] || 100
  const r = azarDe(`precio-${symbol}-${period}`)
  const drift = (r() - 0.4) * 0.002
  const valores = [actual]
  for (let i = 1; i < points; i++) valores.push(valores[i - 1] / (1 + drift + (r() - 0.5) * 0.02))
  valores.reverse()
  const hoy = new Date()
  const out = valores.map((v, i) => {
    const d = new Date(hoy)
    d.setDate(hoy.getDate() - (points - 1 - i))
    return { date: fechaISO(d), close: Math.round(v * 100) / 100 }
  })
  return { symbol, period, points: out }
}
