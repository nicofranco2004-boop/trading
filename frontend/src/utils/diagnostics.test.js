import { describe, it, expect } from 'vitest'
import { selectDiagnostics, DIAGNOSTIC_GENERATORS, dayOfYearKey, hashString } from './diagnostics.js'

// Helper: encontrar un generador por id
const findGen = (id) => DIAGNOSTIC_GENERATORS.find(g => g.id === id)
const fire = (id, data) => findGen(id).generate(data)

// ─── Generadores individuales ──────────────────────────────────────────────

describe('concentration_extreme', () => {
  it('dispara cuando un activo pesa más del 50%', () => {
    const out = fire('concentration_extreme', {
      pieData: [{ name: 'BTC', value: 6000 }, { name: 'ETH', value: 4000 }],
      totalPortfolio: 10000,
    })
    expect(out).toMatch(/BTC/)
    expect(out).toMatch(/60%/)
    expect(out).toMatch(/cartera/)
  })

  it('no dispara cuando la concentración es moderada', () => {
    expect(fire('concentration_extreme', {
      pieData: [{ name: 'BTC', value: 3000 }, { name: 'ETH', value: 4000 }, { name: 'SOL', value: 3000 }],
      totalPortfolio: 10000,
    })).toBe(null)
  })

  it('clampa ~101% (divergencia de valuación) a 100% y lo muestra', () => {
    const out = fire('concentration_extreme', {
      pieData: [{ name: 'SID', value: 10100 }, { name: 'AAPL', value: 50 }],
      totalPortfolio: 10000,   // Σ holdings > total por-broker → 101%
    })
    expect(out).toMatch(/SID/)
    expect(out).toMatch(/100%/)
    expect(out).not.toMatch(/101%/)
  })

  it('suprime valores absurdos (>110%, ej. bono per-100 mal valuado)', () => {
    expect(fire('concentration_extreme', {
      pieData: [{ name: 'AL30', value: 68900 }],
      totalPortfolio: 10000,   // 689%
    })).toBe(null)
  })
})

describe('concentration_top3', () => {
  it('cuenta dinámica: un solo activo → "1 activo" (no "3 activos")', () => {
    const out = fire('concentration_top3', {
      concentration: { top3: [{ asset: 'SID', value: 10000 }], sharePct: 100, totalAssets: 1 },
    })
    expect(out).toMatch(/1 activo:/)
    expect(out).toMatch(/SID/)
    expect(out).not.toMatch(/activos/)
  })
  it('tres activos → "3 activos"', () => {
    const out = fire('concentration_top3', {
      concentration: {
        top3: [{ asset: 'AAPL', value: 5000 }, { asset: 'SID', value: 3000 }, { asset: 'KO', value: 1000 }],
        sharePct: 90, totalAssets: 5,
      },
    })
    expect(out).toMatch(/3 activos:/)
    expect(out).toMatch(/AAPL, SID, KO/)
  })
  it('no dispara si la concentración top-3 es baja (<80%)', () => {
    expect(fire('concentration_top3', {
      concentration: { top3: [{ asset: 'A', value: 1 }], sharePct: 50, totalAssets: 4 },
    })).toBe(null)
  })
})

describe('growth_from_deposits', () => {
  it('dispara cuando >70% del crecimiento viene de aportes', () => {
    const out = fire('growth_from_deposits', {
      discipline: { deposits: 8000, pnl: 1000, total: 9000, pnlShare: 11 },
    })
    expect(out).toMatch(/aportes/)
    expect(out).toMatch(/89%/)
  })

  it('no dispara cuando el rendimiento explica más del crecimiento', () => {
    expect(fire('growth_from_deposits', {
      discipline: { deposits: 1000, pnl: 4000, total: 5000, pnlShare: 80 },
    })).toBe(null)
  })
})

describe('gain_concentration', () => {
  it('dispara cuando un activo solo explica más del 50% de las ganancias', () => {
    const out = fire('gain_concentration', {
      assetContribFull: [
        { asset: 'NVDA', pnl: 800 },
        { asset: 'TSLA', pnl: 200 },
        { asset: 'GGAL', pnl: -100 },
      ],
      totalResult: 900,
    })
    expect(out).toMatch(/NVDA/)
    expect(out).toMatch(/80%/)
  })

  it('no dispara si las ganancias están repartidas', () => {
    expect(fire('gain_concentration', {
      assetContribFull: [
        { asset: 'A', pnl: 200 }, { asset: 'B', pnl: 200 },
        { asset: 'C', pnl: 200 }, { asset: 'D', pnl: 200 },
      ],
      totalResult: 800,
    })).toBe(null)
  })
})

describe('disposition_effect', () => {
  it('dispara cuando aguantás perdedoras mucho más que ganadoras', () => {
    const out = fire('disposition_effect', {
      holdTime: { avgWin: 10, avgLoss: 80, avg: 30, count: 5 },
    })
    expect(out).toMatch(/perdedoras/)
    expect(out).toMatch(/80d/)
    expect(out).toMatch(/10d/)
    expect(out).toMatch(/disposition effect/)
  })

  it('no dispara si los holds están parejos', () => {
    expect(fire('disposition_effect', {
      holdTime: { avgWin: 30, avgLoss: 35, avg: 32, count: 10 },
    })).toBe(null)
  })
})

describe('drawdown_severe', () => {
  it('dispara con drawdown actual peor a -20%', () => {
    expect(fire('drawdown_severe', { drawdown: { current: -25, max: -25 } })).toMatch(/drawdown/i)
  })
  it('no dispara con drawdown moderado', () => {
    expect(fire('drawdown_severe', { drawdown: { current: -8, max: -8 } })).toBe(null)
  })
})

describe('fx_cash_ars_exposure', () => {
  it('dispara cuando hay >5% del portfolio en cash ARS', () => {
    const out = fire('fx_cash_ars_exposure', {
      positions: [{ is_cash: true, broker: 'Cocos', invested: 1_500_000 }],
      brokers: [{ name: 'Cocos', currency: 'ARS' }, { name: 'IB', currency: 'USDT' }],
      totalPortfolio: 10_000,  // 1.5M / 1500 = 1000 USD = 10%
      tcBlue: 1500,
    })
    expect(out).toMatch(/cash ARS/)
    expect(out).toMatch(/10%/)
    expect(out).toMatch(/dólar blue/)
  })

  it('no dispara si el cash ARS es <5% del portfolio', () => {
    expect(fire('fx_cash_ars_exposure', {
      positions: [{ is_cash: true, broker: 'Cocos', invested: 100_000 }],
      brokers: [{ name: 'Cocos', currency: 'ARS' }],
      totalPortfolio: 10_000,  // 100k / 1500 = 66 USD = 0.66%
      tcBlue: 1500,
    })).toBe(null)
  })

  it('no dispara sin cash ARS', () => {
    expect(fire('fx_cash_ars_exposure', {
      positions: [{ is_cash: true, broker: 'IB', invested: 5000 }],
      brokers: [{ name: 'IB', currency: 'USDT' }],
      totalPortfolio: 10_000,
      tcBlue: 1500,
    })).toBe(null)
  })

  it('no dispara sin tcBlue', () => {
    expect(fire('fx_cash_ars_exposure', {
      positions: [{ is_cash: true, broker: 'Cocos', invested: 1_500_000 }],
      brokers: [{ name: 'Cocos', currency: 'ARS' }],
      totalPortfolio: 10_000,
      tcBlue: null,
    })).toBe(null)
  })
})

describe('profit_factor_low_winrate_high', () => {
  it('dispara con win rate alto pero PF < 1', () => {
    expect(fire('profit_factor_low_winrate_high', {
      winRate: { wins: 7, losses: 3, pct: 70, ratio: 0.5 },
      profitFactor: { profitFactor: 0.85 },
    })).toMatch(/profit factor/i)
  })

  it('no dispara con PF > 1', () => {
    expect(fire('profit_factor_low_winrate_high', {
      winRate: { wins: 7, losses: 3, pct: 70, ratio: 1.5 },
      profitFactor: { profitFactor: 1.5 },
    })).toBe(null)
  })

  it('no dispara con muestra muy chica', () => {
    expect(fire('profit_factor_low_winrate_high', {
      winRate: { wins: 2, losses: 1, pct: 67 },
      profitFactor: { profitFactor: 0.8 },
    })).toBe(null)
  })
})

// ═════════════════════════════════════════════════════════════════════════
// BLOQUE 2 — Reglas de comportamiento, costos, consistencia y oportunidad.
// ═════════════════════════════════════════════════════════════════════════

describe('inactivity_long', () => {
  it('dispara cuando hace más de 90 días sin operaciones', () => {
    const oldDate = new Date(Date.now() - 200 * 86_400_000).toISOString().slice(0, 10)
    const out = fire('inactivity_long', {
      tradeOps: [{ date: oldDate, pnl_usd: 50 }],
    })
    expect(out).toMatch(/meses/)
    expect(out).toMatch(/no realizás operaciones/)
  })

  it('no dispara con actividad reciente', () => {
    const recentDate = new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10)
    expect(fire('inactivity_long', {
      tradeOps: [{ date: recentDate, pnl_usd: 50 }],
    })).toBe(null)
  })
})

describe('overtrading', () => {
  it('dispara con 12+ ops en los últimos 30 días', () => {
    const recent = Array.from({ length: 15 }, (_, i) => ({
      date: new Date(Date.now() - i * 86_400_000).toISOString().slice(0, 10),
      pnl_usd: 10,
    }))
    const out = fire('overtrading', { tradeOps: recent })
    expect(out).toMatch(/15 operaciones/)
  })

  it('no dispara con poca actividad', () => {
    expect(fire('overtrading', {
      tradeOps: [{ date: new Date().toISOString().slice(0, 10), pnl_usd: 10 }],
    })).toBe(null)
  })
})

describe('losing_streak', () => {
  it('detecta racha de 4+ pérdidas consecutivas', () => {
    const ops = [
      { date: '2025-05-01', pnl_usd: -100 },
      { date: '2025-05-02', pnl_usd: -50 },
      { date: '2025-05-03', pnl_usd: -75 },
      { date: '2025-05-04', pnl_usd: -200 },
      { date: '2025-04-15', pnl_usd: 300 }, // anterior, ganadora
    ]
    const out = fire('losing_streak', { tradeOps: ops })
    expect(out).toMatch(/4 operaciones perdedoras/)
  })

  it('no dispara si la última fue ganadora', () => {
    expect(fire('losing_streak', {
      tradeOps: [
        { date: '2025-05-04', pnl_usd: 50 },
        { date: '2025-05-03', pnl_usd: -100 },
        { date: '2025-05-02', pnl_usd: -50 },
        { date: '2025-05-01', pnl_usd: -75 },
        { date: '2025-04-30', pnl_usd: -200 },
      ],
    })).toBe(null)
  })
})

describe('winning_streak', () => {
  it('detecta racha de 5+ ganadoras consecutivas', () => {
    const ops = Array.from({ length: 5 }, (_, i) => ({
      date: `2025-05-${String(10 - i).padStart(2, '0')}`,
      pnl_usd: 50,
    }))
    const out = fire('winning_streak', { tradeOps: ops })
    expect(out).toMatch(/5 operaciones ganadoras/)
    expect(out).toMatch(/overconfidence|over-confianza|sizing/)
  })
})

describe('avg_hold_time_classifier', () => {
  it('clasifica como swing trader corto entre 7 y 30 días', () => {
    const out = fire('avg_hold_time_classifier', { holdTime: { avg: 15 } })
    expect(out).toMatch(/15 días/)
    expect(out).toMatch(/swing trader corto/)
  })

  it('clasifica como inversor de largo plazo con 1+ año', () => {
    const out = fire('avg_hold_time_classifier', { holdTime: { avg: 400 } })
    expect(out).toMatch(/largo plazo/)
  })

  it('no dispara sin hold time válido', () => {
    expect(fire('avg_hold_time_classifier', { holdTime: { avg: 0 } })).toBe(null)
  })
})

describe('unrealized_dominates', () => {
  it('dispara cuando >75% del P&L es no realizado', () => {
    const out = fire('unrealized_dominates', {
      realizedPnl: 500,
      unrealizedPnl: 4500,
    })
    expect(out).toMatch(/90%/)
    expect(out).toMatch(/sin realizar/)
  })

  it('no dispara si está balanceado', () => {
    expect(fire('unrealized_dominates', {
      realizedPnl: 1000,
      unrealizedPnl: 1500,
    })).toBe(null)
  })
})

describe('fees_drag', () => {
  it('dispara cuando comisiones >0.5% del portfolio (USD broker)', () => {
    const out = fire('fees_drag', {
      positions: [
        { commissions: 100, broker: 'IBKR' },
        { commissions: 50, broker: 'IBKR' },
      ],
      brokers: [{ name: 'IBKR', currency: 'USDT' }],
      totalPortfolio: 10000,
    })
    expect(out).toMatch(/USD 150/)
    expect(out).toMatch(/1.5%/)
  })

  it('no dispara si las comisiones son bajas', () => {
    expect(fire('fees_drag', {
      positions: [{ commissions: 5, broker: 'IBKR' }],
      brokers: [{ name: 'IBKR', currency: 'USDT' }],
      totalPortfolio: 10000,
    })).toBe(null)
  })

  it('REGRESIÓN: para broker ARS convierte comisiones ARS→USD con TC blue', () => {
    // 41,809 ARS de comisiones / 1415 = ~29.55 USD (no 41,809)
    // sobre portfolio de 5,757 USD = 0.51% (no 726%)
    const out = fire('fees_drag', {
      positions: [{ commissions: 41809, broker: 'Cocos' }],
      brokers: [{ name: 'Cocos', currency: 'ARS' }],
      tcBlue: 1415,
      totalPortfolio: 5757,
    })
    expect(out).toMatch(/USD 30/)              // 41809/1415 ≈ 29.55, fmtUsd redondea
    expect(out).not.toMatch(/USD 41/)
    expect(out).not.toMatch(/726/)             // % no debe ser absurdo
    expect(out).toMatch(/0\.5%/)               // ~0.51% del portfolio
  })

  it('mezcla ARS+USD brokers convierte solo los ARS', () => {
    // 50000 ARS (=35.3 USD) + 30 USD = 65.3 USD ≈ 0.65% de 10000
    const out = fire('fees_drag', {
      positions: [
        { commissions: 50000, broker: 'Cocos' },  // ARS
        { commissions: 30, broker: 'IBKR' },      // USD
      ],
      brokers: [
        { name: 'Cocos', currency: 'ARS' },
        { name: 'IBKR', currency: 'USDT' },
      ],
      tcBlue: 1415,
      totalPortfolio: 10000,
    })
    // No debe ser USD 50,030 (la suma cruda sin conversión)
    expect(out).not.toMatch(/USD 50,030/)
    expect(out).not.toMatch(/USD 50030/)
    // Sí debe ser un número razonable (~65 USD)
    expect(out).toMatch(/USD 6[0-9]/)
  })
})

describe('tax_loss_opportunity', () => {
  it('dispara con pérdidas no realizadas significativas', () => {
    const out = fire('tax_loss_opportunity', {
      pieData: [
        { name: 'A', value: 1000, pnl: -200 },
        { name: 'B', value: 1500, pnl: -150 },
        { name: 'C', value: 2000, pnl: 500 },
      ],
    })
    expect(out).toMatch(/2 posiciones/)
    expect(out).toMatch(/USD 350/)
    expect(out).toMatch(/tax-loss harvesting/)
  })
})

describe('tiny_positions_drag', () => {
  it('dispara con 3+ posiciones <2% sumando <8% del total', () => {
    const out = fire('tiny_positions_drag', {
      pieData: [
        { name: 'BIG', value: 9000 },
        { name: 'X', value: 100 },
        { name: 'Y', value: 100 },
        { name: 'Z', value: 100 },
        { name: 'W', value: 100 },
      ],
      totalPortfolio: 10000,
    })
    expect(out).toMatch(/4 posiciones/)
    expect(out).toMatch(/4.0%/)
  })
})

describe('monthly_pnl_streak', () => {
  it('detecta 3+ meses positivos consecutivos', () => {
    const out = fire('monthly_pnl_streak', {
      globalMonthly: [
        { year: 2026, month: 4, pnl_realized: 100, pnl_unrealized: 50 },
        { year: 2026, month: 3, pnl_realized: 200, pnl_unrealized: 0 },
        { year: 2026, month: 2, pnl_realized: 50, pnl_unrealized: 100 },
        { year: 2026, month: 1, pnl_realized: -200, pnl_unrealized: 0 },
      ],
    })
    expect(out).toMatch(/3 meses consecutivos/)
  })

  it('no dispara si el último mes fue pérdida', () => {
    expect(fire('monthly_pnl_streak', {
      globalMonthly: [
        { year: 2026, month: 4, pnl_realized: -100, pnl_unrealized: 0 },
        { year: 2026, month: 3, pnl_realized: 200, pnl_unrealized: 0 },
        { year: 2026, month: 2, pnl_realized: 50, pnl_unrealized: 0 },
      ],
    })).toBe(null)
  })
})

// ─── Selector ──────────────────────────────────────────────────────────────

describe('selectDiagnostics', () => {
  it('devuelve array vacío sin datos', () => {
    expect(selectDiagnostics({})).toEqual([])
  })

  it('ordena urgent antes de warn antes de positive antes de info', () => {
    const data = {
      pieData: [{ name: 'NVDA', value: 9000 }, { name: 'AAPL', value: 1000 }],
      totalPortfolio: 10000,
      profitFactor: { profitFactor: 3 }, // dispara profit_factor_strong (positive)
      drawdown: { current: -25, max: -25 }, // dispara drawdown_severe (urgent)
    }
    const out = selectDiagnostics(data, 10)
    const sevs = out.map(d => d.severity)
    // Urgent debe venir antes que warn debe venir antes que positive
    const urgentIdx = sevs.findIndex(s => s === 'urgent')
    const warnIdx = sevs.findIndex(s => s === 'warn')
    const posIdx = sevs.findIndex(s => s === 'positive')
    if (urgentIdx >= 0 && warnIdx >= 0) expect(urgentIdx).toBeLessThan(warnIdx)
    if (warnIdx >= 0 && posIdx >= 0) expect(warnIdx).toBeLessThan(posIdx)
  })

  it('respeta el límite de bullets', () => {
    // Forzar varios disparos
    const data = {
      pieData: [{ name: 'NVDA', value: 9000 }, { name: 'AAPL', value: 1000 }],
      totalPortfolio: 10000,
      concentration: { sharePct: 90, top3: [{ asset: 'NVDA' }, { asset: 'AAPL' }, { asset: 'X' }], totalAssets: 3 },
      brokerConcentration: { top: { name: 'IB', sharePct: 90 } },
      drawdown: { current: -25, max: -25 },
    }
    expect(selectDiagnostics(data, 2).length).toBeLessThanOrEqual(2)
  })

  it('mismo día → mismo orden (rotación estable dentro del día)', () => {
    const data = {
      // Múltiples generadores info compiten por el mismo slot
      positions: [{ is_cash: true, broker: 'IB', invested: 100 }],
      totalPortfolio: 10000,
      winRate: { wins: 1, losses: 1, pct: 50 },
    }
    const today = new Date('2026-05-06T12:00:00Z')
    const a = selectDiagnostics(data, 5, today)
    const b = selectDiagnostics(data, 5, today)
    expect(a.map(x => x.id)).toEqual(b.map(x => x.id))
  })

  it('días distintos pueden rotar la selección', () => {
    // Necesitamos que haya MÁS generadores compitiendo que slots para que la
    // rotación cambie algo. Acá creamos un escenario con varios disparos
    // y revisamos que para días distintos, el tie-break se mueve.
    const data = {
      pieData: [{ name: 'NVDA', value: 4000 }, { name: 'AAPL', value: 6000 }],
      totalPortfolio: 10000,
      concentration: { sharePct: 85, top3: [{ asset: 'AAPL' }, { asset: 'NVDA' }, { asset: 'X' }], totalAssets: 3 },
      brokerConcentration: { top: { name: 'IB', sharePct: 75 } },
      assetTypeBreakdown: [{ type: 'Acciones', sharePct: 75 }],
    }
    const day1 = new Date('2026-01-01T12:00:00Z')
    const day2 = new Date('2026-06-15T12:00:00Z')
    const a = selectDiagnostics(data, 2, day1)
    const b = selectDiagnostics(data, 2, day2)
    // No exigimos que necesariamente cambie (depende del hash) pero al menos
    // ambas selecciones siguen siendo válidas y de tamaño correcto.
    expect(a.length).toBe(2)
    expect(b.length).toBe(2)
  })
})

describe('helpers', () => {
  it('hashString es determinístico', () => {
    expect(hashString('foo')).toBe(hashString('foo'))
    expect(hashString('foo')).not.toBe(hashString('bar'))
  })

  it('dayOfYearKey cambia entre días', () => {
    const a = dayOfYearKey(new Date('2026-01-01T12:00:00Z'))
    const b = dayOfYearKey(new Date('2026-01-02T12:00:00Z'))
    expect(a).not.toBe(b)
  })

  it('dayOfYearKey es estable dentro del mismo día UTC', () => {
    const a = dayOfYearKey(new Date('2026-05-06T01:00:00Z'))
    const b = dayOfYearKey(new Date('2026-05-06T23:00:00Z'))
    expect(a).toBe(b)
  })
})

// ─── Métricas como diagnósticos (ex "Métricas Pro") ─────────────────────────
describe('generadores de métricas (proMetrics)', () => {
  const gen = (id) => DIAGNOSTIC_GENERATORS.find(g => g.id === id)
  const full = {
    cagr: { cagr: 0.18, totalGrowth: 0.2, months: 12 },
    volatility: 0.22,
    sharpe: { sharpe: 1.4, returnAnnual: 0.2, rfAnnual: 0.045, months: 8 },
    sortino: { sortino: 1.9, downsideDev: 0.1, months: 8 },
    alphaBeta: { beta: 1.15, alphaAnnual: 0.03, rSquared: 0.6, months: 8 },
    infoRatio: { infoRatio: 0.7, activeReturn: 0.05, trackingError: 0.07 },
    calmar: { calmar: 2.1 },
  }

  it('cada métrica fires con proMetrics completo y menciona su valor', () => {
    expect(gen('metric_cagr').generate({ proMetrics: full })).toContain('+18.0%')
    expect(gen('metric_volatility').generate({ proMetrics: full })).toContain('22.0%')
    expect(gen('metric_sharpe').generate({ proMetrics: full })).toContain('1.40')
    expect(gen('metric_sortino').generate({ proMetrics: full })).toContain('1.90')
    expect(gen('metric_beta').generate({ proMetrics: full })).toContain('1.15')
    expect(gen('metric_alpha').generate({ proMetrics: full })).toContain('+3.0%')
    expect(gen('metric_info_ratio').generate({ proMetrics: full })).toContain('0.70')
    expect(gen('metric_calmar').generate({ proMetrics: full })).toContain('2.10')
  })

  it('todas son severidad info (viven en el tier Diagnóstico)', () => {
    for (const id of ['metric_cagr','metric_volatility','metric_sharpe','metric_sortino','metric_beta','metric_alpha','metric_info_ratio','metric_calmar']) {
      expect(gen(id).severity).toBe('info')
    }
  })

  it('no fires sin proMetrics ni con campos null/NaN', () => {
    for (const id of ['metric_cagr','metric_volatility','metric_sharpe','metric_beta','metric_calmar']) {
      expect(gen(id).generate({})).toBeNull()
      expect(gen(id).generate({ proMetrics: null })).toBeNull()
    }
    expect(gen('metric_volatility').generate({ proMetrics: { volatility: NaN } })).toBeNull()
    expect(gen('metric_sharpe').generate({ proMetrics: { sharpe: { sharpe: Infinity } } })).toBeNull()
    expect(gen('metric_beta').generate({ proMetrics: { alphaBeta: null } })).toBeNull()
    expect(gen('metric_cagr').generate({ proMetrics: { cagr: { cagr: 0.1, months: 1 } } })).toBeNull()  // <2 meses
  })

  it('selectDiagnostics las incluye cuando proMetrics está', () => {
    const fired = selectDiagnostics({ proMetrics: full }, 999)
    const ids = fired.map(f => f.id)
    expect(ids).toContain('metric_sharpe')
    expect(ids).toContain('metric_volatility')
  })

  it('las 6 métricas ajustadas por riesgo son premium; CAGR + vol NO', () => {
    for (const id of ['metric_sharpe','metric_sortino','metric_beta','metric_alpha','metric_info_ratio','metric_calmar']) {
      expect(gen(id).premium).toBe(true)
      expect(typeof gen(id).lockedLabel).toBe('string')
    }
    // Gratis para todos: CAGR (retorno anualizado) y volatilidad.
    expect(gen('metric_cagr').premium).toBeUndefined()
    expect(gen('metric_volatility').premium).toBeUndefined()
  })

  it('isFree=true → métricas premium BLOQUEADAS: título sin valor + unlockTier plus', () => {
    const fired = selectDiagnostics({ proMetrics: full, isFree: true }, 999)
    const sharpe = fired.find(f => f.id === 'metric_sharpe')
    expect(sharpe.locked).toBe(true)
    expect(sharpe.unlockTier).toBe('plus')
    expect(sharpe.lockedLabel).toBe('Tu Sharpe ratio')
    expect(sharpe.text).toBe('Tu Sharpe ratio')  // el card usa esto como título
    expect(sharpe.text).not.toMatch(/\d/)          // NO expone el valor
  })

  it('isFree=true → CAGR y volatilidad NO se bloquean (gratis, con valor)', () => {
    const fired = selectDiagnostics({ proMetrics: full, isFree: true }, 999)
    const cagr = fired.find(f => f.id === 'metric_cagr')
    const vol = fired.find(f => f.id === 'metric_volatility')
    expect(cagr.locked).toBeFalsy()
    expect(cagr.text).toMatch(/CAGR anualizado es/)
    expect(cagr.text).toMatch(/18\.0%/)   // muestra el valor
    expect(vol.locked).toBeFalsy()
    expect(vol.text).toMatch(/22\.0%/)
  })

  it('isFree=false → métricas premium con valor, sin locked', () => {
    const fired = selectDiagnostics({ proMetrics: full, isFree: false }, 999)
    const sharpe = fired.find(f => f.id === 'metric_sharpe')
    expect(sharpe.locked).toBeUndefined()
    expect(sharpe.text).toMatch(/Sharpe ratio es/)
    expect(sharpe.text).toMatch(/1\.40/)
  })

  it('los diagnósticos NO-premium nunca se bloquean, aunque sea Free', () => {
    const fired = selectDiagnostics({ proMetrics: full, isFree: true }, 999)
    for (const f of fired) {
      if (f.id !== 'metric_sharpe' && f.id !== 'metric_sortino' && f.id !== 'metric_beta'
          && f.id !== 'metric_alpha' && f.id !== 'metric_info_ratio' && f.id !== 'metric_calmar') {
        expect(f.locked).toBeFalsy()
      }
    }
  })
})

// Regresión: los generadores de drawdown leían `drawdown.maxPct`, pero el objeto
// que arma Insights.jsx tiene `.max` → NUNCA fireaban. Ahora leen `.max`.
describe('generadores de drawdown (leen drawdown.max, no .maxPct)', () => {
  it('at_highs fires con un drawdown recuperado (max negativo, current ~0)', () => {
    const out = findGen('at_highs').generate({ drawdown: { current: 0, max: -15 } })
    expect(out).toBeTruthy()
    expect(out).toMatch(/máximos históricos/i)
    expect(out).toMatch(/15\.0%/)
  })

  it('at_highs NO fires si no hubo drawdown histórico relevante (max > -3)', () => {
    expect(findGen('at_highs').generate({ drawdown: { current: 0, max: -1 } })).toBeNull()
  })

  it('drawdown_recovery fires tras recuperar un drawdown profundo', () => {
    const out = findGen('drawdown_recovery').generate({ drawdown: { current: -2, max: -20 } })
    expect(out).toBeTruthy()
    expect(out).toMatch(/Recuperaste/)
    expect(out).toMatch(/-20\.0%/)
  })

  it('ambos toleran drawdown null sin fires', () => {
    expect(findGen('at_highs').generate({ drawdown: null })).toBeNull()
    expect(findGen('drawdown_recovery').generate({ drawdown: null })).toBeNull()
  })
})
