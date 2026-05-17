import { describe, it, expect } from 'vitest'
import {
  netCapitalContributed,
  buildCumulativeReturnSeries,
  computeDrawdownOnReturns,
  computeBestWorstMonth,
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
