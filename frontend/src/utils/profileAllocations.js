// profileAllocations — tablas de referencia perfil → asignación sugerida.
// ═══════════════════════════════════════════════════════════════════════════
// Source of truth de la INDUSTRIA ARGENTINA (Balanz, IOL, Cocos Capital,
// BBVA, Santander, Galicia, ICBC). Las asignaciones publicadas por estos
// brokers/bancos para los 3 perfiles canónicos son razonablemente
// homogéneas — los rangos abajo son la mediana razonable.
//
// IMPORTANTE: estas son ASIGNACIONES SUGERIDAS, no recomendaciones de
// inversión. Son orientativas, no normativas. El frontend muestra "asignación
// de referencia para perfil X" — nunca "deberías tener X%".

// ─── Derivación: 7 respuestas → categoría ──────────────────────────────────
//
// Scoring multi-dimensional con peso mayor a horizonte + drawdown (los dos
// drivers más relevantes para perfil de riesgo según literatura financiera).
//
// Rango total posible: 0 a ~18. Cortes calibrados para que el "perfil
// arquetípico" Moderado (horizonte medio + hold + libertad financiera +
// experiencia 2-5y + mixto + sin urgencia de liquidez = score 13) caiga
// en Moderado, no en Agresivo.
//    0-6   → Conservador
//    7-13  → Moderado
//    14+   → Agresivo
//
// Devuelve null si el profile no tiene horizon Y drawdown (datos mínimos
// para clasificar de forma honesta — sin esos dos campos el resultado sería
// adivinanza).

const SCORE_MAP = {
  horizon: {
    short: 0,
    medium: 2,
    long: 4,
  },
  drawdown: {
    sell_all: 0,
    sell_some: 1,
    hold: 3,
    buy_more: 4,
  },
  liquidity: {
    yes: 0,           // necesita plata pronto → más conservador
    partial: 1,
    no: 2,
  },
  goal: {
    specific_purchase: 0,
    retirement: 1,
    hobby: 2,
    freedom: 2,
    learn: 2,
  },
  experience: {
    first_time: 0,
    under_2: 1,
    '2_to_5': 2,
    over_5: 3,
  },
  style: {
    passive: 2,
    mixed: 2,
    active: 3,
  },
}

/**
 * deriveProfileCategory
 *
 * Convierte el JSON del investor profile en una categoría canónica:
 * 'conservador' | 'moderado' | 'agresivo'.
 *
 * Devuelve null si faltan los campos primarios (horizon + drawdown) —
 * no clasificamos sin esa data mínima porque sería adivinanza.
 *
 * @param {Object} profile  { horizon, drawdown, goal, ... }
 * @returns {'conservador' | 'moderado' | 'agresivo' | null}
 */
export function deriveProfileCategory(profile) {
  if (!profile || typeof profile !== 'object') return null
  if (!profile.horizon || !profile.drawdown) return null

  let score = 0
  for (const key of Object.keys(SCORE_MAP)) {
    const val = profile[key]
    if (val && SCORE_MAP[key][val] != null) {
      score += SCORE_MAP[key][val]
    }
  }

  if (score <= 6) return 'conservador'
  if (score <= 13) return 'moderado'
  return 'agresivo'
}


// ─── Asignaciones sugeridas por categoría (industria AR) ────────────────────
//
// Basado en publicaciones de Balanz, IOL, Cocos, BBVA Argentina, Santander
// Argentina (sección "Perfil del Inversor" / "Tu cartera ideal"). Los valores
// son mediana razonable de lo que estos players sugieren — no son normativos
// ni vinculantes.
//
// Buckets (alineados con classifyAssetType + nueva detección de bonos):
//   cash         — cuentas remuneradas, dólar cash, USDT/USDC
//   fixed_income — bonos soberanos AR (AL/GD), corporativos, LECAPs, LEDES
//   equity       — acciones (CEDEARs + AR + ETFs como SPY/QQQ)
//   alternative  — crypto (BTC/ETH/altcoins), commodities

export const SUGGESTED_ALLOCATIONS = {
  conservador: {
    cash: 30,
    fixed_income: 60,
    equity: 10,
    alternative: 0,
  },
  moderado: {
    cash: 15,
    fixed_income: 40,
    equity: 40,
    alternative: 5,
  },
  agresivo: {
    cash: 5,
    fixed_income: 20,
    equity: 65,
    alternative: 10,
  },
}

// Label en español para cada categoría — usado en UI cards.
export const PROFILE_LABELS = {
  conservador: 'Conservador',
  moderado: 'Moderado',
  agresivo: 'Agresivo',
}

// Concentración típica por perfil — "tus top 3 activos representan X%".
// Más concentración tolerada en perfiles agresivos (que asumen más riesgo
// idiosincrásico). Los rangos son orientativos.
export const TYPICAL_CONCENTRATION_TOP3 = {
  conservador: { min: 20, max: 35 },
  moderado:    { min: 30, max: 50 },
  agresivo:    { min: 40, max: 65 },
}


// ─── Drawdown: behavior declarada → tolerancia implícita ───────────────────
//
// El test no captura un % numérico de tolerancia — captura una intención
// de comportamiento ("¿qué harías si tu portfolio cayera 30%?"). Para
// cruzar con el drawdown histórico real necesitamos un mapeo cualitativo
// del behavior a un rango aproximado de tolerancia en %.
//
// Estos rangos son heurísticos basados en literatura de behavioral finance
// (Kahneman & Tversky, prospect theory) — usuarios que dicen "vendería
// todo" típicamente tienen sensibilidad a la pérdida que se dispara entre
// 5-12% de drawdown realizado. "Buy more" implica mucha más tolerancia,
// usualmente arriba del 30%.
//
// Devolvemos un OBJETO con range (para inequalities) y midpoint (para
// comparaciones single-value en el UI).

export const DRAWDOWN_TOLERANCE_BY_BEHAVIOR = {
  sell_all:  { min: 5,  max: 12, mid: 8,  label: 'vendería toda la cartera' },
  sell_some: { min: 12, max: 20, mid: 15, label: 'vendería una parte' },
  hold:      { min: 20, max: 30, mid: 25, label: 'mantendría la posición' },
  buy_more:  { min: 30, max: 60, mid: 40, label: 'compraría más para promediar abajo' },
}


// ─── Horizonte declarado → tipo de cartera esperada ────────────────────────
//
// Para Card 2 (horizonte vs composición). Mapeo qué tipo de cartera "se
// espera" según el horizonte declarado — orientativo, no normativo.

export const HORIZON_EXPECTATION = {
  short: {
    label: 'corto plazo (días/semanas)',
    expectedBuckets: ['cash', 'fixed_income'],
    expectedLabel: 'cash y renta fija',
    riskBuckets: ['equity', 'alternative'],
    riskLabel: 'renta variable y alternativos',
  },
  medium: {
    label: 'mediano plazo (meses)',
    expectedBuckets: ['cash', 'fixed_income', 'equity'],
    expectedLabel: 'mix de cash, renta fija y renta variable',
    riskBuckets: ['alternative'],
    riskLabel: 'alternativos (crypto)',
  },
  long: {
    label: 'largo plazo (años)',
    expectedBuckets: ['equity', 'alternative'],
    expectedLabel: 'renta variable y alternativos',
    riskBuckets: ['cash', 'fixed_income'],
    riskLabel: 'cash y renta fija',
  },
}


// ─── Clasificación de activos extendida (con bonos AR) ──────────────────────
//
// La clasificación que ya existe en insightsModel.js tiene 4 buckets:
//   Cash · Cripto · CEDEAR/AR · Acción/ETF
//
// Para el modelo de allocation necesitamos separar bonos (renta fija) de
// acciones argentinas. Lo hacemos por pattern matching del ticker —
// los bonos AR tienen prefijos canónicos.

const BOND_PREFIXES_AR = [
  // Bonos soberanos en USD
  'AL',   // AL29, AL30, AL35, AL38, AL41
  'GD',   // GD29, GD30, GD35, GD38, GD41
  'AE',   // AE38
  'AY',   // AY24 (legacy)
  // Bonos en pesos / CER
  'TX',   // TX24, TX26, TX28 (CER)
  'TY',   // TY28 (CER)
  'TC',   // TC25 (CER)
  'TG',   // TG23 (USD link)
  'TZ',   // TZX25 (CER)
  // BONAR / BPO
  'BONAR',
  'BPO',
  'BP',   // BPC28, BPO27
  // LECAP / LEDES / LELIQ
  'LECAP',
  'LEDES',
  'LELIQ',
  'S',    // S31E5, S30J5 (LECAPs short tickers — heurística por longitud abajo)
]

// Tickers exactos que son LECAPs/LEDES — pattern de 4-5 chars con prefijo S/T
// y formato fecha (S31E5 = vence 31 enero 2025). Detectamos por regex.
const LECAP_REGEX = /^[ST]\d{1,2}[A-Z]\d{1,2}$/

/**
 * isBondTicker
 *
 * Detecta si un ticker es un bono argentino por pattern del símbolo.
 * No es exhaustivo — cubre los más comunes (soberanos, CER, LECAPs).
 *
 * @param {string} ticker
 * @returns {boolean}
 */
export function isBondTicker(ticker) {
  if (!ticker) return false
  const t = String(ticker).toUpperCase().trim()
  // Detectar LECAP/LEDES por formato fecha (S31E5, T30D5, etc.)
  if (LECAP_REGEX.test(t)) return true
  // Detectar por prefijo conocido — pero excluir false-positives
  // (ej: "AAPL" empieza con A pero no es bono — el regex de longitud ayuda)
  for (const prefix of BOND_PREFIXES_AR) {
    if (t.startsWith(prefix)) {
      // Heurística: bonos AR tienen al menos un dígito en el ticker
      if (/\d/.test(t)) return true
    }
  }
  return false
}


/**
 * classifyAssetBucket
 *
 * Versión ampliada de classifyAssetType (de insightsModel.js) que incluye
 * el bucket fixed_income (renta fija) detectado por ticker.
 *
 * Buckets devueltos: 'cash' | 'fixed_income' | 'equity' | 'alternative'
 * — alineados con SUGGESTED_ALLOCATIONS.
 *
 * @param {Object} position  { asset, broker, is_cash }
 * @param {Array}  brokers   [{ name, currency }]
 * @returns {'cash' | 'fixed_income' | 'equity' | 'alternative'}
 */
export function classifyAssetBucket(position, brokers = []) {
  if (!position) return 'equity'  // fallback razonable
  if (position.is_cash) return 'cash'

  const ticker = String(position.asset || '').toUpperCase().trim()

  // 1. Crypto (alternative)
  // Reutilizamos la lista de insightsModel.js — repetida acá para no
  // crear dependencia circular. Si el set cambia, mantener sincronizado.
  const CRYPTO_TICKERS = new Set([
    'BTC','ETH','SOL','BNB','ADA','XRP','MATIC','DOT','AVAX','LINK','LTC','BCH',
    'ATOM','UNI','USDT','USDC','DAI','DOGE','SHIB','TRX','XLM','VET','FIL','ICP',
    'APT','NEAR','ARB','OP','SUI','TON','PEPE','WBTC','STETH','HYPE','BONK','WLD',
  ])
  if (CRYPTO_TICKERS.has(ticker)) {
    // Stablecoins se tratan como cash si la posición no se marca is_cash —
    // muchos brokers crypto no marcan stables como cash explícitamente.
    if (['USDT', 'USDC', 'DAI'].includes(ticker)) return 'cash'
    return 'alternative'
  }

  // 2. Bonos AR (fixed_income)
  if (isBondTicker(ticker)) return 'fixed_income'

  // 3. Acciones (equity) — CEDEARs, ETFs, AR shares
  return 'equity'
}


/**
 * computeAllocationBuckets
 *
 * Calcula el % del portfolio en cada bucket (cash / fixed_income / equity /
 * alternative) a partir de las posiciones.
 *
 * @param {Array} positions  con value_usd pre-resuelto
 * @param {Array} brokers
 * @returns {{ cash, fixed_income, equity, alternative, totalUsd }}  pcts 0-100
 */
export function computeAllocationBuckets(positions = [], brokers = []) {
  const buckets = { cash: 0, fixed_income: 0, equity: 0, alternative: 0 }
  let total = 0
  for (const p of positions) {
    if (p.value_usd == null || p.value_usd <= 0) continue
    const bucket = classifyAssetBucket(p, brokers)
    buckets[bucket] += p.value_usd
    total += p.value_usd
  }
  if (total === 0) {
    return { cash: 0, fixed_income: 0, equity: 0, alternative: 0, totalUsd: 0 }
  }
  return {
    cash:         (buckets.cash         / total) * 100,
    fixed_income: (buckets.fixed_income / total) * 100,
    equity:       (buckets.equity       / total) * 100,
    alternative:  (buckets.alternative  / total) * 100,
    totalUsd:     total,
  }
}
