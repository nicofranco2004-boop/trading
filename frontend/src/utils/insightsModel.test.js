import { describe, it, expect } from 'vitest'
import {
  partirMedidoYEstimado,
  resolucionDeSerie,
  totalDePunto,
  cortarPorTramo,
  tsDeClave,
  rellenarTimestamps,
  drawdownFromPerf,
  netCapitalContributed,
  buildCumulativeReturnSeries,
  computeDrawdownOnReturns,
  computeBestWorstMonth,
  acumuladoDeVentana,
  computeAssetContribution,
  computeBestWorstClosedOp,
  computeProfitFactor,
  computeMonthlyConsistency,
  buildDrawdownTimeSeries,
  computeOpenPositionExtremes,
  computeBrokerConcentration,
  classifyAssetType,
  computeAssetTypeBreakdown,
} from './insightsModel.js'

// ── Helpers ───────────────────────────────────────────────────────────────────
const month = (y, m, capInicio, capFinal, deposits = 0, withdrawals = 0, pnl_realized = 0) => ({
  year: y, month: m, capital_inicio: capInicio, capital_final: capFinal,
  deposits, withdrawals, pnl_realized, pnl_unrealized: 0,
})

// ── netCapitalContributed ─────────────────────────────────────────────────────

describe('netCapitalContributed', () => {
  it('returns 0 with no entries', () => {
    expect(netCapitalContributed([])).toBe(0)
  })

  it('includes baseline of first month + cumulative net flows', () => {
    const m = [
      month(2025, 1, 10000, 11000, 500, 0),  // baseline 10k + 500 dep
      month(2025, 2, 11000, 12000, 0, 200),  // 200 wd
    ]
    expect(netCapitalContributed(m)).toBe(10300) // 10000 + 500 - 200
  })

  it('respects sort order (handles unsorted input)', () => {
    const m = [
      month(2025, 3, 0, 0, 100, 0),
      month(2025, 1, 5000, 0, 0, 0),         // baseline only on first
      month(2025, 2, 0, 0, 200, 0),
    ]
    expect(netCapitalContributed(m)).toBe(5300)
  })
})

// ── buildCumulativeReturnSeries ───────────────────────────────────────────────

describe('buildCumulativeReturnSeries', () => {
  it('returns null with no entries', () => {
    expect(buildCumulativeReturnSeries([])).toBe(null)
  })

  it('a 10% gain month gives index 1.10', () => {
    const m = [month(2025, 1, 1000, 1100)]
    const s = buildCumulativeReturnSeries(m)
    expect(s).toHaveLength(1)
    expect(s[0].monthlyReturn).toBeCloseTo(0.10, 5)
    expect(s[0].index).toBeCloseTo(1.10, 5)
  })

  it('compounds returns across months', () => {
    const m = [
      month(2025, 1, 1000, 1100),                 // +10%
      month(2025, 2, 1100, 1210),                 // +10%
    ]
    const s = buildCumulativeReturnSeries(m)
    expect(s[1].index).toBeCloseTo(1.21, 5)        // 1.1 × 1.1
  })

  it('neutralizes a deposit (no fake gain)', () => {
    // Capital final sube de 1000 a 5000 PERO 4000 vino de un depósito —
    // el rendimiento del mes debe ser 0%.
    const m = [month(2025, 1, 1000, 5000, 4000, 0)]
    const s = buildCumulativeReturnSeries(m)
    expect(s[0].monthlyReturn).toBeCloseTo(0, 5)
    expect(s[0].index).toBeCloseTo(1, 5)
  })

  it('neutralizes a withdrawal (no fake drawdown)', () => {
    // El user retira 500 — no es una pérdida.
    const m = [month(2025, 1, 1000, 500, 0, 500)]
    const s = buildCumulativeReturnSeries(m)
    expect(s[0].monthlyReturn).toBeCloseTo(0, 5)
  })

  it('uses liveValue para el último mes (en curso)', () => {
    const m = [
      month(2025, 1, 1000, 1100),
      month(2025, 2, 1100, 1100),  // capital_final stale
    ]
    const s = buildCumulativeReturnSeries(m, 1320)  // live = 1320 → +20% el mes 2
    expect(s[1].capFinal).toBe(1320)
    expect(s[1].monthlyReturn).toBeCloseTo(0.20, 5)
    expect(s[1].index).toBeCloseTo(1.10 * 1.20, 5)
  })

  it('ignora liveValue si vale 0 (precios no cargados)', () => {
    const m = [month(2025, 1, 1000, 1100)]
    const s = buildCumulativeReturnSeries(m, 0)
    expect(s[0].capFinal).toBe(1100)  // usa el del entry
  })

  it('capInicio = 0 → monthlyReturn = 0 (no divide por cero)', () => {
    const m = [month(2025, 1, 0, 100, 100, 0)]   // primer mes con depósito puro
    const s = buildCumulativeReturnSeries(m)
    expect(s[0].monthlyReturn).toBe(0)
    expect(s[0].index).toBe(1)
  })

  // REGRESIÓN: primer mes con cap_inicio=0 y depósito grande (typical import
  // inicial) debe usar el depósito como base, NO como flow mid-month. Sin
  // este caso, Modified Dietz infla 2x la pérdida/ganancia del primer mes.
  it('primer mes con cap_inicio=0 y depósito grande usa deposit como base', () => {
    // User importa histórico: el primer mes tuvo $123k de depósito y cerró
    // en $111k (perdió 9.4% real, no 19% como diría Modified Dietz estándar).
    const m = [month(2025, 1, 0, 111429, 123000, 0)]
    const s = buildCumulativeReturnSeries(m)
    // (111429 - 0 - 123000) / 123000 = -0.0941
    expect(s[0].monthlyReturn).toBeCloseTo(-0.0941, 3)
    // NO debería estar cerca de -0.19 (el resultado buggy anterior)
    expect(s[0].monthlyReturn).toBeGreaterThan(-0.12)
  })

  it('primer mes con ganancia sobre depósito inicial también se ajusta', () => {
    // $10k iniciales → $11k cierre = +10% real (no +20% del cálculo viejo)
    const m = [month(2025, 1, 0, 11000, 10000, 0)]
    const s = buildCumulativeReturnSeries(m)
    expect(s[0].monthlyReturn).toBeCloseTo(0.10, 3)
  })

  it('NO afecta segundo mes — solo el primer mes con cap_inicio=0', () => {
    // Segundo mes con cap_inicio > 0 usa Modified Dietz normal aunque
    // haya depósito grande.
    const m = [
      month(2025, 1, 0, 10000, 10000, 0),       // import inicial, ret=0%
      month(2025, 2, 10000, 11500, 1000, 0),    // +500 ganancia + $1k aporte
    ]
    const s = buildCumulativeReturnSeries(m)
    // Segundo mes: avg = 10000 + 0.5*1000 = 10500, ret = (11500-10000-1000)/10500 = 4.76%
    expect(s[1].monthlyReturn).toBeCloseTo(0.0476, 3)
  })
})

// ── computeDrawdownOnReturns ──────────────────────────────────────────────────

describe('computeDrawdownOnReturns', () => {
  it('null si serie tiene <2 puntos', () => {
    expect(computeDrawdownOnReturns(null)).toBe(null)
    expect(computeDrawdownOnReturns([{ index: 1 }])).toBe(null)
  })

  it('drawdown = 0 si la serie es estrictamente creciente', () => {
    const s = [{ index: 1 }, { index: 1.1 }, { index: 1.2 }]
    const dd = computeDrawdownOnReturns(s)
    expect(dd.maxPct).toBe(0)
    expect(dd.currentPct).toBe(0)
  })

  it('captura caída desde un peak', () => {
    // 1.0 → 1.5 → 1.0 = -33.3% de drawdown
    const s = [{ index: 1.0, key: 'a' }, { index: 1.5, key: 'b' }, { index: 1.0, key: 'c' }]
    const dd = computeDrawdownOnReturns(s)
    expect(dd.maxPct).toBeCloseTo(-33.33, 1)
    expect(dd.peakKey).toBe('b')
    expect(dd.troughKey).toBe('c')
  })

  it('drawdown actual reflects vs HWM histórico, no vs último peak', () => {
    // 1.0 → 1.5 (peak) → 1.2 → 1.4 (no nuevo HWM)
    // Drawdown actual = (1.4 - 1.5) / 1.5 = -6.67%
    const s = [{ index: 1.0 }, { index: 1.5 }, { index: 1.2 }, { index: 1.4 }]
    const dd = computeDrawdownOnReturns(s)
    expect(dd.currentPct).toBeCloseTo(-6.67, 1)
  })

  it('un retiro grande NO inflar el drawdown (vs cálculo viejo sobre valor absoluto)', () => {
    // Si el user retira plata, el rendimiento no cambia → drawdown = 0
    const m = [
      month(2025, 1, 10000, 11000),               // +10%
      month(2025, 2, 11000, 6000, 0, 5000),       // retira 5k → return 0%
    ]
    const series = buildCumulativeReturnSeries(m)
    const dd = computeDrawdownOnReturns(series)
    expect(dd.maxPct).toBe(0)  // el "cálculo viejo" daría ~-45%
  })
})

// ── computeBestWorstMonth ─────────────────────────────────────────────────────

describe('computeBestWorstMonth', () => {
  it('null si no hay data', () => {
    expect(computeBestWorstMonth([])).toBe(null)
  })

  it('detecta mejor y peor mes', () => {
    const m = [
      month(2025, 1, 1000, 1100),   // +10%
      month(2025, 2, 1100, 990),    // -10%
      month(2025, 3, 990, 1080),    // +9.09%
    ]
    const r = computeBestWorstMonth(m, new Date(2025, 5, 1))  // jun → ya cerraron
    expect(r.best.month).toBe(1)
    expect(r.best.pct).toBeCloseTo(10, 1)
    expect(r.worst.month).toBe(2)
    expect(r.worst.pct).toBeCloseTo(-10, 1)
    expect(r.count).toBe(3)
  })

  it('excluye el mes calendario actual', () => {
    const m = [
      month(2025, 1, 1000, 1100),         // +10%
      month(2025, 5, 1100, 2000),         // +81.8% pero es el mes en curso
    ]
    const r = computeBestWorstMonth(m, new Date(2025, 4, 15))  // mayo en curso
    expect(r.best.month).toBe(1)         // mayo no entra
    expect(r.count).toBe(1)
  })

  it('null si solo hay mes en curso', () => {
    const m = [month(2025, 5, 1000, 1100)]
    const r = computeBestWorstMonth(m, new Date(2025, 4, 1))
    expect(r).toBe(null)
  })
})

// ── computeAssetContribution ──────────────────────────────────────────────────

describe('computeAssetContribution', () => {
  it('combina realized + unrealized por asset', () => {
    const ops = [
      { asset: 'BTC', pnl_usd: 500 },
      { asset: 'BTC', pnl_usd: 200 },
      { asset: 'ETH', pnl_usd: -100 },
    ]
    const open = [
      { asset: 'BTC', pnl_usd: 300 },
      { asset: 'SOL', pnl_usd: -50 },
    ]
    const r = computeAssetContribution(ops, open)
    const btc = r.find(x => x.asset === 'BTC')
    expect(btc.realized).toBe(700)
    expect(btc.unrealized).toBe(300)
    expect(btc.pnl).toBe(1000)
    expect(btc.hasOpen).toBe(true)
    expect(btc.hasClosed).toBe(true)
    // Ordering desc by pnl
    expect(r[0].asset).toBe('BTC')
  })

  it('ignora positions sin pnl_usd (sin precio)', () => {
    const open = [{ asset: 'BTC', pnl_usd: null }]
    const r = computeAssetContribution([], open)
    expect(r).toHaveLength(0)
  })

  it('case-insensitive asset matching', () => {
    const ops = [{ asset: 'btc', pnl_usd: 100 }]
    const open = [{ asset: 'BTC', pnl_usd: 50 }]
    const r = computeAssetContribution(ops, open)
    expect(r).toHaveLength(1)
    expect(r[0].pnl).toBe(150)
  })
})

// ── computeBestWorstClosedOp ──────────────────────────────────────────────────

describe('computeBestWorstClosedOp', () => {
  it('null si no hay ops', () => {
    expect(computeBestWorstClosedOp([])).toBe(null)
  })

  it('encuentra mejor y peor', () => {
    const ops = [
      { id: 1, asset: 'BTC', pnl_usd: 500 },
      { id: 2, asset: 'SOL', pnl_usd: -200 },
      { id: 3, asset: 'ETH', pnl_usd: 100 },
    ]
    const r = computeBestWorstClosedOp(ops)
    expect(r.best.id).toBe(1)
    expect(r.worst.id).toBe(2)
  })
})

// ── computeProfitFactor ───────────────────────────────────────────────────────

describe('computeProfitFactor', () => {
  it('null si no hay ops', () => {
    expect(computeProfitFactor([])).toBe(null)
  })

  it('PF = 2 con $1000 ganados y $500 perdidos', () => {
    const ops = [
      { pnl_usd: 600 }, { pnl_usd: 400 },        // gross win 1000
      { pnl_usd: -300 }, { pnl_usd: -200 },      // gross loss 500
    ]
    const r = computeProfitFactor(ops)
    expect(r.profitFactor).toBe(2)
    expect(r.grossWin).toBe(1000)
    expect(r.grossLoss).toBe(500)
  })

  it('Infinity si no hay pérdidas (todas ganadoras)', () => {
    const ops = [{ pnl_usd: 100 }, { pnl_usd: 50 }]
    const r = computeProfitFactor(ops)
    expect(r.profitFactor).toBe(Infinity)
  })

  it('PF = 0 si no hay ganadoras (solo pérdidas)', () => {
    const ops = [{ pnl_usd: -50 }, { pnl_usd: -30 }]
    const r = computeProfitFactor(ops)
    expect(r.profitFactor).toBe(0)
  })

  it('captura asimetría que win rate solo no captura', () => {
    // 4 ganadoras chicas + 1 perdedora grande → WR 80% pero PF < 1
    const ops = [
      { pnl_usd: 50 }, { pnl_usd: 50 }, { pnl_usd: 50 }, { pnl_usd: 50 },  // +200
      { pnl_usd: -300 },                                                    // -300
    ]
    const r = computeProfitFactor(ops)
    expect(r.profitFactor).toBeLessThan(1)
  })
})

// ── computeMonthlyConsistency ─────────────────────────────────────────────────

describe('computeMonthlyConsistency', () => {
  it('null si no hay serie', () => {
    expect(computeMonthlyConsistency(null)).toBe(null)
    expect(computeMonthlyConsistency([])).toBe(null)
  })

  it('cuenta meses positivos vs negativos', () => {
    const series = [
      { year: 2025, month: 1, monthlyReturn: 0.10 },
      { year: 2025, month: 2, monthlyReturn: -0.05 },
      { year: 2025, month: 3, monthlyReturn: 0.03 },
      { year: 2025, month: 4, monthlyReturn: -0.02 },
    ]
    const r = computeMonthlyConsistency(series, new Date(2025, 5, 1))
    expect(r.positiveCount).toBe(2)
    expect(r.negativeCount).toBe(2)
    expect(r.positivePct).toBe(50)
    expect(r.total).toBe(4)
  })

  it('std dev de retornos constantes = 0', () => {
    const series = [
      { year: 2025, month: 1, monthlyReturn: 0.05 },
      { year: 2025, month: 2, monthlyReturn: 0.05 },
    ]
    const r = computeMonthlyConsistency(series, new Date(2025, 5, 1))
    expect(r.stdDev).toBeCloseTo(0, 5)
  })

  it('excluye mes en curso', () => {
    const series = [
      { year: 2025, month: 1, monthlyReturn: 0.10 },
      { year: 2025, month: 5, monthlyReturn: -0.50 },  // en curso
    ]
    const r = computeMonthlyConsistency(series, new Date(2025, 4, 15))
    expect(r.total).toBe(1)
    expect(r.positivePct).toBe(100)
  })
})

// ── buildDrawdownTimeSeries ───────────────────────────────────────────────────

describe('buildDrawdownTimeSeries', () => {
  it('serie vacía', () => {
    expect(buildDrawdownTimeSeries([])).toEqual([])
  })

  it('drawdown en cada punto (underwater curve)', () => {
    const series = [
      { key: '2025-01', index: 1.0 },
      { key: '2025-02', index: 1.2 },   // peak
      { key: '2025-03', index: 0.9 },   // -25% del peak
      { key: '2025-04', index: 1.1 },   // recuperando, aún -8.33% del peak
    ]
    const dd = buildDrawdownTimeSeries(series)
    expect(dd[0].ddPct).toBe(0)
    expect(dd[1].ddPct).toBe(0)              // nuevo HWM, ddpct = 0
    expect(dd[2].ddPct).toBeCloseTo(-25, 0)
    expect(dd[3].ddPct).toBeCloseTo(-8.33, 1)
  })
})

// ── computeOpenPositionExtremes ──────────────────────────────────────────────

describe('computeOpenPositionExtremes', () => {
  it('null si vacío', () => {
    expect(computeOpenPositionExtremes([])).toBe(null)
  })

  it('encuentra mejor y peor por pnl_usd', () => {
    const pos = [
      { asset: 'BTC', pnl_usd: 1000 },
      { asset: 'ETH', pnl_usd: -500 },
      { asset: 'SOL', pnl_usd: 200 },
    ]
    const r = computeOpenPositionExtremes(pos)
    expect(r.best.asset).toBe('BTC')
    expect(r.worst.asset).toBe('ETH')
    expect(r.count).toBe(3)
  })

  it('ignora posiciones sin precio (pnl_usd null)', () => {
    const pos = [
      { asset: 'BTC', pnl_usd: 100 },
      { asset: 'ETH', pnl_usd: null },
    ]
    const r = computeOpenPositionExtremes(pos)
    expect(r.count).toBe(1)
  })
})

// ── computeBrokerConcentration ────────────────────────────────────────────────

describe('computeBrokerConcentration', () => {
  it('null si no hay brokers con valor', () => {
    expect(computeBrokerConcentration([])).toBe(null)
    expect(computeBrokerConcentration([{ name: 'X', value: 0 }])).toBe(null)
  })

  it('calcula sharePct y top correctamente', () => {
    const r = computeBrokerConcentration([
      { name: 'A', value: 7000 },
      { name: 'B', value: 3000 },
    ])
    expect(r.top.name).toBe('A')
    expect(r.top.sharePct).toBe(70)
    expect(r.brokers).toHaveLength(2)
    expect(r.total).toBe(10000)
  })
})

// ── classifyAssetType ─────────────────────────────────────────────────────────

describe('classifyAssetType', () => {
  const brokers = [
    { name: 'Binance', currency: 'USDT' },
    { name: 'Cocos', currency: 'ARS' },
  ]

  it('cash detection takes priority', () => {
    expect(classifyAssetType({ asset: 'USDT', is_cash: true }, brokers)).toBe('Cash')
  })

  it('crypto tickers', () => {
    expect(classifyAssetType({ asset: 'BTC', broker: 'Binance' }, brokers)).toBe('Cripto')
    expect(classifyAssetType({ asset: 'eth', broker: 'Binance' }, brokers)).toBe('Cripto')
  })

  it('ARS broker → CEDEAR/AR', () => {
    expect(classifyAssetType({ asset: 'GGAL', broker: 'Cocos' }, brokers)).toBe('CEDEAR/AR')
  })

  it('USD broker no-crypto → Acción/ETF', () => {
    expect(classifyAssetType({ asset: 'AAPL', broker: 'Binance' }, brokers)).toBe('Acción/ETF')
  })

  it('CEDEAR en broker USD → CEDEAR/AR (por asset_type)', () => {
    const bk = [{ name: 'Cocos · USD', currency: 'USDT' }]
    expect(classifyAssetType({ asset: 'MELI', asset_type: 'CEDEAR', broker: 'Cocos · USD' }, bk)).toBe('CEDEAR/AR')
  })

  it('instrumento en sub-broker AR "· USD" → CEDEAR/AR (por nombre)', () => {
    const bk = [{ name: 'Cocos · USD', currency: 'USDT' }]
    expect(classifyAssetType({ asset: 'PAMP', broker: 'Cocos · USD' }, bk)).toBe('CEDEAR/AR')
  })
})

// ── computeAssetTypeBreakdown ─────────────────────────────────────────────────

describe('computeAssetTypeBreakdown', () => {
  const brokers = [
    { name: 'Binance', currency: 'USDT' },
    { name: 'Cocos', currency: 'ARS' },
  ]

  it('agrupa y calcula sharePct', () => {
    const positions = [
      { asset: 'BTC', broker: 'Binance', value_usd: 5000 },
      { asset: 'ETH', broker: 'Binance', value_usd: 3000 },
      { asset: 'GGAL', broker: 'Cocos', value_usd: 2000 },
    ]
    const r = computeAssetTypeBreakdown(positions, brokers)
    expect(r[0].type).toBe('Cripto')
    expect(r[0].value).toBe(8000)
    expect(r[0].sharePct).toBe(80)
    expect(r[1].type).toBe('CEDEAR/AR')
    expect(r[1].sharePct).toBe(20)
  })

  it('ignora posiciones sin value_usd', () => {
    const positions = [
      { asset: 'BTC', broker: 'Binance', value_usd: 1000 },
      { asset: 'ETH', broker: 'Binance', value_usd: null },
    ]
    const r = computeAssetTypeBreakdown(positions, brokers)
    expect(r).toHaveLength(1)
    expect(r[0].value).toBe(1000)
  })
})


// ── El gate del drawdown ──────────────────────────────────────────────────────
// "No se pudo medir" NO puede convertirse en "0,0%". El backend devuelve null
// cuando no hay tramo medible; el `|| 0` que había acá lo re-fabricaba del lado
// del cliente y el usuario del caso 452 iba a leer "Drawdown actual 0,0% · peak
// histórico 0,0%" exactamente donde antes leía −45%.
describe('drawdownFromPerf', () => {
  it('null cuando no hay ninguna medición (una sola foto)', () => {
    expect(drawdownFromPerf({ drawdown_maximo: null, drawdown_actual: null })).toBe(null)
  })

  it('null si falta cualquiera de los dos campos', () => {
    expect(drawdownFromPerf({ drawdown_maximo: -0.2, drawdown_actual: null })).toBe(null)
    expect(drawdownFromPerf({ drawdown_maximo: null, drawdown_actual: -0.2 })).toBe(null)
  })

  it('null con perf ausente (el endpoint todavía no volvió)', () => {
    expect(drawdownFromPerf(null)).toBe(null)
    expect(drawdownFromPerf(undefined)).toBe(null)
  })

  it('un drawdown REAL de 0% sí se publica (no es lo mismo que no medido)', () => {
    const d = drawdownFromPerf({ drawdown_maximo: 0, drawdown_actual: 0 })
    expect(d).not.toBe(null)
    expect(d.maxPct).toBe(0)
  })

  it('convierte a puntos porcentuales', () => {
    const d = drawdownFromPerf({ drawdown_maximo: -0.45, drawdown_actual: -0.12 })
    expect(d.maxPct).toBeCloseTo(-45, 6)
    expect(d.currentPct).toBeCloseTo(-12, 6)
  })
})


// ── El corte entre tramos ─────────────────────────────────────────────────────
// El índice y el pico se reinician en cada tramo, así que el primer punto del
// tramo 2 vale 0% — dibujado pegado al tramo 1 se lee como "recuperé todo" con la
// cartera 60% abajo. En la curva de drawdown es peor: el encabezado está gateado
// y muestra "—", así que el gráfico queda solo, sin nada que lo contradiga.
describe('cortarPorTramo', () => {
  const serie = [
    { key: '2026-01-31', tramo: 0, total: 0 },
    { key: '2026-02-28', tramo: 0, total: 50 },
    { key: '2026-03-31', tramo: 0, total: 40 },
    { key: '2026-08-18', tramo: 1, total: 0 },
    { key: '2026-08-19', tramo: 1, total: 3 },
  ]

  it('corta EN LA FRONTERA, no al final', () => {
    const r = cortarPorTramo(serie)
    const i = r.findIndex(p => String(p.key).startsWith('corte-'))
    expect(i).toBe(3)                                   // entre 03-31 y 08-18
    expect(r[i - 1].key).toBe('2026-03-31')
    expect(r[i + 1].key).toBe('2026-08-18')
    expect(r[r.length - 1].key).toBe('2026-08-19')      // NO al final
  })

  it('el punto de corte va en null para que Recharts deje el hueco', () => {
    const r = cortarPorTramo(serie)
    const corte = r.find(p => String(p.key).startsWith('corte-'))
    expect(corte.total).toBe(null)
    expect(corte.realized).toBe(null)
    expect(corte.label).toBe('')
  })

  it('con tres tramos hay DOS cortes, no uno', () => {
    const tres = [...serie, { key: '2027-02-01', tramo: 2, total: 0 }]
    const r = cortarPorTramo(tres)
    expect(r.filter(p => String(p.key).startsWith('corte-'))).toHaveLength(2)
  })

  it('una serie de un solo tramo no se toca', () => {
    const uno = serie.filter(p => p.tramo === 0)
    expect(cortarPorTramo(uno)).toHaveLength(uno.length)
  })

  it('sin `tramo` (backend viejo) no corta nada', () => {
    const sinTramo = serie.map(({ tramo, ...r }) => r)
    expect(cortarPorTramo(sinTramo)).toHaveLength(serie.length)
  })

  // ── RONDA 9 · el corte por CAMBIO DE BASE ────────────────────────────────
  // La línea principal no se parte sólo donde hay un hueco: también donde cambia
  // la BASE de valuación. Un segmento que une una foto al costo con una medición a
  // mercado dibuja el escalón entre dos reglas — medido, −47,26% en el caso 452,
  // con el header diciendo "—" justo al lado.
  it('corta por `segmento` cuando se lo pide, no por `tramo`', () => {
    const conBase = [
      { key: '2026-04-30', tramo: 0, segmento: 0, total: 0 },   // costo
      { key: '2026-07-31', tramo: 0, segmento: 0, total: 0 },   // costo
      { key: '2026-08-24', tramo: 0, segmento: 1, total: 0 },   // mercado
    ]
    // Por `tramo` los tres son uno solo: el corte no existiría.
    expect(cortarPorTramo(conBase)).toHaveLength(3)
    const r = cortarPorTramo(conBase, undefined, 'segmento')
    const i = r.findIndex(p => String(p.key).startsWith('corte-'))
    expect(i).toBe(2)
    expect(r[i - 1].key).toBe('2026-07-31')
    expect(r[i + 1].key).toBe('2026-08-24')
  })

  it('una serie sin `segmento` (la de ARS) no corta nunca', () => {
    const ars = [{ key: '2026-01', total: 0 }, { key: '2026-02', total: 5 }]
    expect(cortarPorTramo(ars, undefined, 'segmento')).toHaveLength(2)
  })

  it('acepta campos vacíos propios (la curva de drawdown usa ddPct)', () => {
    const r = cortarPorTramo(serie, { ddPct: null })
    const corte = r.find(p => String(p.key).startsWith('corte-'))
    expect(corte.ddPct).toBe(null)
  })

  it('vacío y null no rompen', () => {
    expect(cortarPorTramo([])).toEqual([])
    expect(cortarPorTramo(null)).toEqual([])
  })
})


// ── Un punto no-apto no se dibuja ─────────────────────────────────────────────
// En los no-aptos el índice NO avanzó: el `index` que traen es el arrastrado del
// último punto medido. Dibujarlos los muestra en 0,00% — el bug original con el
// signo dado vuelta, y encima se lee tranquilizador.
describe('totalDePunto', () => {
  it('un punto apto se dibuja', () => {
    expect(totalDePunto({ apto: true, index: 1.2 })).toBeCloseTo(20, 6)
  })

  it('una foto no apta SÍ se dibuja — con su posición real', () => {
    // El backend le calcula un índice propio (no el arrastrado), así que
    // esconderla le borraba la curva al que tiene la cartera al costo.
    expect(totalDePunto({ apto: false, index: 1.15 })).toBeCloseTo(15, 6)
  })

  it('la parte no medida va en su propia clave, para dibujarla punteada', () => {
    const filas = [
      { k: 'a', estimado: true, T: 0 },
      { k: 'b', estimado: true, T: 10 },
      { k: 'c', estimado: false, T: 12 },
      { k: 'd', estimado: false, T: 15 },
    ]
    const r = partirMedidoYEstimado(filas, 'T', 'E')
    // El punto frontera aparece en las DOS, para que las líneas se toquen.
    expect(r.map(x => x.T)).toEqual([null, 10, 12, 15])
    expect(r.map(x => x.E)).toEqual([0, 10, 12, null])
  })

  it('null/undefined no rompen', () => {
    expect(totalDePunto(null)).toBe(null)
    expect(totalDePunto({ apto: true })).toBe(null)
  })
})


// ── La resolución sigue a lo MEDIDO ───────────────────────────────────────────
// Con 46 mediciones diarias repartidas en dos meses, el resampleo mensual dibuja
// DOS PUNTOS —una recta— y se come una caída real del 8,31%. En la misma pantalla
// la curva de drawdown dice «Máx histórico −8,3%».
describe('resolucionDeSerie', () => {
  const dias = (desde, n) => {
    const out = []
    const d = new Date(desde)
    for (let i = 0; i < n; i++) {
      out.push(new Date(d.getTime() + i * 86400000).toISOString().slice(0, 10))
    }
    return out
  }

  it('46 días medidos → diaria (si no, es una recta)', () => {
    expect(resolucionDeSerie(dias('2026-07-11', 46))).toBe('diaria')
  })

  it('dos años medidos → mensual', () => {
    expect(resolucionDeSerie(['2024-01-01', '2026-01-01'])).toBe('mensual')
  })

  it('el umbral está en ~3 meses', () => {
    expect(resolucionDeSerie(['2026-01-01', '2026-03-15'])).toBe('diaria')   // 73 d
    expect(resolucionDeSerie(['2026-01-01', '2026-06-01'])).toBe('mensual')  // 151 d
  })

  it('ignora "today", que no es una fecha', () => {
    expect(resolucionDeSerie(['2026-07-11', '2026-07-20', 'today'])).toBe('diaria')
  })

  it('con menos de dos puntos no agrupa', () => {
    expect(resolucionDeSerie([])).toBe('diaria')
    expect(resolucionDeSerie(['2026-07-11'])).toBe('diaria')
    expect(resolucionDeSerie(null)).toBe('diaria')
  })

  it('el resampleo mensual perdería la caída; el diario no', () => {
    // 2 meses de datos con una caída dentro de agosto.
    const puntos = [
      { key: '2026-07-15', total: 0 },
      { key: '2026-07-31', total: 2 },
      { key: '2026-08-10', total: 3 },
      { key: '2026-08-14', total: -5.4 },   // la caída del 8,3%
      { key: '2026-08-29', total: 1 },
    ]
    expect(resolucionDeSerie(puntos.map(p => p.key))).toBe('diaria')
    // Lo que hacía el resampleo mensual: un punto por mes → la caída desaparece.
    const porMes = {}
    for (const p of puntos) porMes[p.key.slice(0, 7)] = p
    expect(Object.values(porMes).map(p => p.total)).toEqual([2, 1])
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// FASE 2 · RONDA 2 — el KPI que decía "—" al lado de su propia curva.
// ═══════════════════════════════════════════════════════════════════════════
describe('acumuladoDeVentana', () => {
  const KM = 'Demo P/L total'
  const KE = 'Demo estimado'
  // Filas con la forma que deja `partirMedidoYEstimado`: el valor vive en UNA de
  // las dos claves (o en las dos, si es punto frontera).
  // ⚠️ CON `total`: es el camino real. `total` es el acumulado crudo del punto,
  // ya relativo al arranque de SU segmento — que es de donde sale el número.
  const med = (label, v) => ({ label, estimado: false, total: v, [KM]: v, [KE]: null })
  const est = (label, v) => ({ label, estimado: true, total: v, [KM]: null, [KE]: v })
  const corte = () => ({ label: '', total: null, [KM]: null, [KE]: null })

  it('usuario 100% contable: publica el acumulado en vez de "—"', () => {
    // ⚠️ EL CASO QUE DA NOMBRE A LA RONDA. Todos los puntos caen en la clave
    // ESTIMADA, así que la regla vieja (`ultimaFila[claveMedida]`) devolvía null y
    // el KPI mostraba "—" con la curva dibujada al lado. Son los 331 usuarios que
    // el modo Estimado vino a servir.
    const f = [est('Sep', 0), est('Oct', 5), est('Nov', 10)]
    expect(f[f.length - 1][KM]).toBeNull()      // el fixture exhibe el bug
    const r = acumuladoDeVentana(f, KM, KE)
    expect(r).not.toBeNull()
    // (100+10)/(100+0) − 1 = +10%
    expect(r.pct).toBeCloseTo(10, 6)
    expect(r.estimado).toBe(true)
    expect(r.parcial).toBe(false)
  })

  it('NO encadena a través de un corte de regla: usa la última corrida', () => {
    // ⚠️ ES LA REGLA DE LA FASE 1 APLICADA ACÁ. El índice del backend se REINICIA
    // en cada cambio de base, así que dividir el último punto (mercado) por el
    // primero (contable) mezcla dos reglas. El fixture lo hace imposible de no
    // ver: la corrida contable va +50% y la de mercado +2%.
    const f = [est('Ene', 0), est('Feb', 50), corte(), med('Mar', 0), med('Abr', 2)]
    const r = acumuladoDeVentana(f, KM, KE)
    expect(r.pct).toBeCloseTo(2, 6)     // el +2% del segmento medido, NO 2-vs-50
    expect(r.parcial).toBe(true)        // empieza después del borde de la ventana
    expect(r.estimado).toBe(false)      // la última corrida es medida
  })

  it('una sola punta después de un corte NO es un acumulado', () => {
    // Los 25 usuarios reales: el último segmento tiene UN punto, cuyo valor
    // rebaseado es 0 porque el índice acaba de reiniciarse. La regla vieja
    // publicaba "0,0%" — que se lee "tu cartera no se movió" — sobre un artefacto
    // del reinicio. No hay número: hay una punta.
    const f = [est('Ene', 0), est('Feb', 150), corte(), med('Ago', 0)]
    expect(f[f.length - 1][KM]).toBe(0)  // el fixture exhibe el "0,0%" viejo
    expect(acumuladoDeVentana(f, KM, KE)).toBeNull()
  })

  it('el número NO depende de la resolución del gráfico', () => {
    // ⚠️ LO ENCONTRÉ MIDIENDO, NO LEYENDO. El resampleo mensual colapsa un
    // segmento entero en UNA fila; con el cociente primera-vs-última el mismo
    // usuario daba −0,52% en resolución diaria y "—" en mensual. Como `total` ya
    // es el acumulado del segmento, la fila sola alcanza.
    const diaria  = [est('E', 0), est('F', 50), corte(), med('M1', 0), med('M2', -0.3), med('M3', -0.52)]
    const mensual = [est('E', 0), est('F', 50), corte(), med('M3', -0.52)]
    expect(acumuladoDeVentana(diaria, KM, KE).pct).toBeCloseTo(-0.52, 6)
    expect(acumuladoDeVentana(mensual, KM, KE).pct).toBeCloseTo(-0.52, 6)
  })

  it('una cartera de verdad PLANA sí publica 0,0%', () => {
    // ⚠️ EL ERROR OPUESTO, y hay que no cometerlo: suprimir todo `total === 0`
    // le borraría el número a quien estuvo genuinamente plano. Lo que distingue al
    // artefacto es que sea UNA sola fila (el arranque del segmento, sin nada
    // después); varias filas en 0 son una cartera que no se movió.
    const f = [med('Ene', 0), med('Feb', 0), med('Mar', 0)]
    const r = acumuladoDeVentana(f, KM, KE)
    expect(r).not.toBeNull()
    expect(r.pct).toBe(0)
  })

  it('ventana sin ningún punto → null (ahí el "—" es lo correcto)', () => {
    expect(acumuladoDeVentana([], KM, KE)).toBeNull()
    expect(acumuladoDeVentana([corte(), corte()], KM, KE)).toBeNull()
    expect(acumuladoDeVentana(null, KM, KE)).toBeNull()
  })

  it('la corrida con un punto estimado en el medio queda marcada estimada', () => {
    // Un tramo con UN punto reconstruido ya no es una medición limpia, y el KPI
    // tiene que decirlo aunque las puntas sean medidas.
    const f = [med('Ene', 0), { label: 'Feb', estimado: true, total: 4, [KM]: 4, [KE]: 4 }, med('Mar', 8)]
    const r = acumuladoDeVentana(f, KM, KE)
    expect(r.pct).toBeCloseTo(8, 6)
    expect(r.estimado).toBe(true)
  })
})

// ─── El eje X tiene que medir tiempo ────────────────────────────────────────
describe('tsDeClave / rellenarTimestamps', () => {
  const dia = (y, m, d) => new Date(y, m - 1, d).getTime()
  const KM = 'Demo P/L total'

  it('una fecha cae en su día, a medianoche LOCAL', () => {
    // Local y no UTC: las marcas de una escala de tiempo caen en límites de día
    // locales. Con medianoche UTC, en Argentina cada punto quedaría 3 h corrido
    // respecto de su propia marca.
    expect(tsDeClave('2026-08-25')).toBe(dia(2026, 8, 25))
    expect(new Date(tsDeClave('2026-08-25')).getDate()).toBe(25)
  })

  it('una clave mensual cae en el ÚLTIMO día del mes, no en el primero', () => {
    // Las series contables son CIERRES de mes. Ponerlas el día 1 las adelantaría
    // un mes entero sobre el eje.
    expect(tsDeClave('2026-02')).toBe(dia(2026, 2, 28))
    expect(tsDeClave('2024-02')).toBe(dia(2024, 2, 29)) // bisiesto
    expect(tsDeClave('2026-12')).toBe(dia(2026, 12, 31))
  })

  it("'today' es ahora, y se puede inyectar para testear", () => {
    expect(tsDeClave('today', 12345)).toBe(12345)
  })

  it('lo que no es fecha no inventa un instante', () => {
    expect(tsDeClave('corte-2026-08-01')).toBeNull()
    expect(tsDeClave('')).toBeNull()
    expect(tsDeClave(null)).toBeNull()
  })

  it('el CORTE va al punto medio de sus vecinos', () => {
    // El corte marca dónde cambia la regla de valuación. El punto medio es el
    // único lugar que no estira ni el tramo que termina ni el que empieza.
    const filas = [
      { key: '2026-07-30' },
      { key: 'corte-2026-08-01' },
      { key: '2026-08-01' },
    ]
    const r = rellenarTimestamps(filas)
    expect(r[0].ts).toBe(dia(2026, 7, 30))
    expect(r[2].ts).toBe(dia(2026, 8, 1))
    expect(r[1].ts).toBe((r[0].ts + r[2].ts) / 2)
    expect(r[1].ts).toBeGreaterThan(r[0].ts)
    expect(r[1].ts).toBeLessThan(r[2].ts)
  })

  it('dos cortes seguidos que aíslan un punto siguen ordenados', () => {
    // El caso real de la cuenta demo: el 31/07 es una foto contable en medio del
    // tramo medido, y queda encerrado entre dos cortes.
    const filas = [
      { key: '2026-07-30' }, { key: 'corte-2026-07-31' }, { key: '2026-07-31' },
      { key: 'corte-2026-08-01' }, { key: '2026-08-01' },
    ]
    const ts = rellenarTimestamps(filas).map(r => r.ts)
    for (let i = 1; i < ts.length; i++) expect(ts[i]).toBeGreaterThan(ts[i - 1])
  })

  it('siempre devuelve números: un eje numérico no ubica un null', () => {
    const r = rellenarTimestamps([{ key: 'raro' }, { key: '2026-08-01' }, { key: 'otro' }])
    r.forEach(x => expect(typeof x.ts).toBe('number'))
    expect(Number.isNaN(r[0].ts)).toBe(false)
  })

  it('sin una sola clave legible quedan equiespaciadas — el eje viejo', () => {
    const r = rellenarTimestamps([{ key: 'a' }, { key: 'b' }, { key: 'c' }])
    expect(r[1].ts - r[0].ts).toBe(r[2].ts - r[1].ts)
  })

  it('es aditivo: no toca ningún otro campo', () => {
    const filas = [{ key: '2026-08-01', label: 'Ago', total: 3, [KM]: 1 }]
    const r = rellenarTimestamps(filas)
    expect(r[0].label).toBe('Ago')
    expect(r[0].total).toBe(3)
    expect(r[0][KM]).toBe(1)
    expect(filas[0].ts).toBeUndefined() // no muta la entrada
  })

  it('la serie mixta reparte el ancho por TIEMPO, no por posición', () => {
    // El bug de esta ronda en una línea: 10 meses contables + unos días medidos.
    // Con posiciones, los 10 meses ocupaban 10/13 del ancho; con tiempo, lo suyo.
    const filas = [
      { key: '2025-09' }, { key: '2025-10' }, { key: '2025-11' },
      { key: '2026-07-11' }, { key: '2026-07-12' }, { key: '2026-07-13' },
    ]
    const ts = rellenarTimestamps(filas).map(r => r.ts)
    const dias = (a, b) => (b - a) / 86400000
    expect(dias(ts[0], ts[2])).toBeCloseTo(61, 0)   // sep→nov: dos meses
    expect(dias(ts[3], ts[5])).toBeCloseTo(2, 6)    // tres días medidos: dos días
  })
})
