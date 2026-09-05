import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import {
  buildEvolutionFromSnapshots,
  buildPortfolioValueSeries,
  convertSeriesToArs,
  computeDailyPnl,
  computeReturnDelta,
  diagnosticoSinMedicion,
  textoSinMedicion,
} from './evolution.js'

const TCB = 1500

const BENCH = {
  dolar_blue: {
    '2025-01': 1000,
    '2025-02': 1100,
    '2025-03': 1200,
    '2026-04': 1400,
  },
}

// ── Guards ────────────────────────────────────────────────────────────────────

describe('Returns null when there are <2 snapshots', () => {
  it('null snapshots', () => {
    expect(buildEvolutionFromSnapshots(null, [], BENCH, TCB)).toBe(null)
  })
  it('undefined snapshots', () => {
    expect(buildEvolutionFromSnapshots(undefined, [], BENCH, TCB)).toBe(null)
  })
  it('empty array', () => {
    expect(buildEvolutionFromSnapshots([], [], BENCH, TCB)).toBe(null)
  })
  it('single snapshot', () => {
    const snaps = [{ date: '2025-02-01', total_value: 100, total_invested: 100, net_deposited: 100 }]
    expect(buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)).toBe(null)
  })
})

// ── USD core math ─────────────────────────────────────────────────────────────

describe('USD: 2 snapshots, simple growth', () => {
  const snaps = [
    { date: '2025-02-01', total_value: 1000, total_invested: 800, net_deposited: 1000 },
    { date: '2025-02-15', total_value: 1100, total_invested: 800, net_deposited: 1000 },
  ]
  const result = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)

  it('produces 2 USD points', () => expect(result.seriesUsd.length).toBe(2))
  it('first point: 0% (value == baseline)', () => expect(result.seriesUsd[0].total).toBe(0))
  it('second point: 10% gain', () => expect(result.seriesUsd[1].total).toBe(10))
  it('label is MM-DD', () => {
    expect(result.seriesUsd[0].label).toBe('02-01')
    expect(result.seriesUsd[1].label).toBe('02-15')
  })
  it('key is full ISO date', () => {
    expect(result.seriesUsd[0].key).toBe('2025-02-01')
    expect(result.seriesUsd[1].key).toBe('2025-02-15')
  })
  it('realized = 0 with no monthly entries', () => {
    expect(result.seriesUsd[0].realized).toBe(0)
    expect(result.seriesUsd[1].realized).toBe(0)
  })
})

describe('USD: snapshots are sorted ascending regardless of input order', () => {
  const snaps = [
    { date: '2025-03-15', total_value: 1200, total_invested: 800, net_deposited: 1000 },  // later
    { date: '2025-02-01', total_value: 1000, total_invested: 800, net_deposited: 1000 },  // earlier
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
  it('first point is the earlier date', () => expect(r.seriesUsd[0].key).toBe('2025-02-01'))
  it('second point is the later date', () => expect(r.seriesUsd[1].key).toBe('2025-03-15'))
  it('% growth applied to correct point', () => {
    expect(r.seriesUsd[0].total).toBe(0)
    expect(r.seriesUsd[1].total).toBe(20)
  })
})

describe('USD: TWRR — primer snapshot es baseline (0%), siguientes son chain-link', () => {
  // Migración a TWRR: cada snapshot ya NO se computa independientemente como
  // MWR (value-baseline)/baseline. El primero es 0% (referencia) y los
  // siguientes son chain-link de period_returns (Modified Dietz).
  const snaps = [
    { date: '2025-01-01', total_value: 1000, total_invested: 800, net_deposited: 0 },
    { date: '2025-01-15', total_value: 880,  total_invested: 800, net_deposited: 0 },
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
  it('first point: 0% baseline (TWRR)', () => expect(r.seriesUsd[0].total).toBe(0))
  it('second point: (880-1000)/1000 = -12% (period return sin flujos)', () => {
    expect(r.seriesUsd[1].total).toBe(-12)
  })
})

describe('USD: zero baseline → 0% (no division by zero)', () => {
  const snaps = [
    { date: '2025-02-01', total_value: 0, total_invested: 0, net_deposited: 0 },
    { date: '2025-02-02', total_value: 100, total_invested: 0, net_deposited: 0 },
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
  it('first total = 0', () => expect(r.seriesUsd[0].total).toBe(0))
  it('second total = 0 (baseline still 0)', () => expect(r.seriesUsd[1].total).toBe(0))
})

// ── Realized line from monthly_entries ────────────────────────────────────────

describe('Realized line: cumulative from monthly_entries, step-matched by month', () => {
  const monthly = [
    { broker: 'global', year: 2025, month: 1, pnl_realized: 50 },   // Jan: cum=50
    { broker: 'global', year: 2025, month: 2, pnl_realized: 30 },   // Feb: cum=80
    { broker: 'global', year: 2025, month: 3, pnl_realized: -10 },  // Mar: cum=70
  ]
  const snaps = [
    { date: '2025-01-15', total_value: 1000, net_deposited: 1000 },  // baseline=1000, cumR=50 → 5%
    { date: '2025-02-15', total_value: 1100, net_deposited: 1000 },  // baseline=1000, cumR=80 → 8%
    { date: '2025-03-15', total_value: 1200, net_deposited: 1000 },  // baseline=1000, cumR=70 → 7%
  ]
  const r = buildEvolutionFromSnapshots(snaps, monthly, BENCH, TCB)
  it('Jan snap: realized = 5%', () => expect(r.seriesUsd[0].realized).toBe(5))
  it('Feb snap: realized = 8%', () => expect(r.seriesUsd[1].realized).toBe(8))
  it('Mar snap: realized = 7% (negative March cancels)', () => expect(r.seriesUsd[2].realized).toBe(7))
})

describe('Realized line: snapshot before any monthly entry → 0%', () => {
  const monthly = [{ broker: 'global', year: 2025, month: 5, pnl_realized: 100 }]
  const snaps = [
    { date: '2025-01-01', total_value: 1000, net_deposited: 1000 },  // before May entry
    { date: '2025-02-01', total_value: 1100, net_deposited: 1000 },
  ]
  const r = buildEvolutionFromSnapshots(snaps, monthly, BENCH, TCB)
  it('all pre-monthly snaps have realized=0', () => {
    expect(r.seriesUsd[0].realized).toBe(0)
    expect(r.seriesUsd[1].realized).toBe(0)
  })
})

describe('Realized line: snapshot after gap month uses last known cumulative', () => {
  const monthly = [
    { broker: 'global', year: 2025, month: 1, pnl_realized: 100 },   // Jan: cum=100
    // Feb missing
    { broker: 'global', year: 2025, month: 3, pnl_realized: 50 },    // Mar: cum=150
  ]
  const snaps = [
    { date: '2025-02-15', total_value: 1100, net_deposited: 1000 },  // Feb gap → falls back to Jan cum=100 → 10%
    { date: '2025-03-15', total_value: 1150, net_deposited: 1000 },  // Mar exists → 15%
  ]
  const r = buildEvolutionFromSnapshots(snaps, monthly, BENCH, TCB)
  it('Feb snap (gap month) → uses Jan cum', () => expect(r.seriesUsd[0].realized).toBe(10))
  it('Mar snap → uses Mar cum', () => expect(r.seriesUsd[1].realized).toBe(15))
})

// ── ARS series uses historical FX of snapshot's month ─────────────────────────

describe('ARS: TWRR period return entre snapshots con FX por mes', () => {
  const snaps = [
    { date: '2025-01-15', total_value: 1000, net_deposited: 1000 },  // FX=1000 (Jan)
    { date: '2025-02-15', total_value: 1100, net_deposited: 1000 },  // FX=1100 (Feb)
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
  // Jan: baseline TWRR = 0%
  // Feb (Modified Dietz):
  //   prevValueArs=1000*1000=1M, prevBaselineArs=1000*1000=1M
  //   valueArs=1100*1100=1.21M, baselineArs=1000*1100=1.1M
  //   flowsArs=1.1M-1M=100k (sintético por el FX que sube — el cash subyacente
  //                          no cambió, pero la base ARS sí)
  //   pnlArs=(1.21M-1M)-100k=110k
  //   avgArs=1M+50k=1.05M
  //   r=110k/1.05M=10.48%
  it('Jan ARS: 0%', () => expect(r.seriesArs[0].total).toBe(0))
  it('Feb ARS: ~10.5% (Modified Dietz absorbe el flujo por FX)', () => {
    expect(r.seriesArs[1].total).toBeCloseTo(10.48, 1)
  })
})

describe('ARS realized: cumRealized × fx_at_snap / baselineArs', () => {
  const monthly = [
    { broker: 'global', year: 2025, month: 1, pnl_realized: 100 },  // cum=100
  ]
  const snaps = [
    { date: '2025-01-15', total_value: 1000, net_deposited: 1000 },
  ]
  const snaps2 = [
    snaps[0],
    { date: '2025-02-15', total_value: 1000, net_deposited: 1000 },
  ]
  const r = buildEvolutionFromSnapshots(snaps2, monthly, BENCH, TCB)
  // Jan: cumR=100, fx=1000 → realArs = 100*1000 / (1000*1000) * 100 = 10%
  // Feb: cumR=100 (Feb missing → falls back to Jan), fx=1100 → realArs = 100*1100 / (1000*1100) * 100 = 10%
  it('Jan ARS realized = 10%', () => expect(r.seriesArs[0].realized).toBe(10))
  it('Feb ARS realized = 10% (still 10% since fx cancels)', () => expect(r.seriesArs[1].realized).toBe(10))
})

// ── Robustness ────────────────────────────────────────────────────────────────

describe('Robustness — bench null', () => {
  const snaps = [
    { date: '2025-02-01', total_value: 1000, net_deposited: 1000 },
    { date: '2025-02-15', total_value: 1100, net_deposited: 1000 },
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], null, TCB)
  it('still produces both series', () => {
    expect(r.seriesUsd.length).toBe(2)
    expect(r.seriesArs.length).toBe(2)
  })
  it('USD math unaffected by missing bench', () => {
    expect(r.seriesUsd[1].total).toBe(10)
  })
  it('ARS uses tcValuacion fallback (FX cancels in % anyway)', () => {
    expect(r.seriesArs[1].total).toBe(10)
  })
})

describe('Robustness — globalMonthly empty', () => {
  const snaps = [
    { date: '2025-02-01', total_value: 1000, net_deposited: 1000 },
    { date: '2025-02-15', total_value: 1100, net_deposited: 1000 },
  ]
  const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
  it('realized line = 0 throughout', () => {
    expect(r.seriesUsd[0].realized).toBe(0)
    expect(r.seriesUsd[1].realized).toBe(0)
  })
})

// ── computeDailyPnl: P&L del día EXCLUYE cashflows ──────────────────────────────
// Regresión del bug "P&L Día −$110": el cálculo viejo usaba Δtotal_value, que
// suma depósitos/retiros a la ganancia. Acá fijamos "hoy" = 2026-05-29 para que
// la lógica `date < today` y dayDiff sea determinística.

describe('computeDailyPnl', () => {
  beforeAll(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-05-29T12:00:00Z')) })
  afterAll(() => { vi.useRealTimers() })

  it('returns null without snapshots', () => {
    expect(computeDailyPnl(null)).toBe(null)
    expect(computeDailyPnl([])).toBe(null)
  })

  it('returns null when there is no prior close (only a snapshot dated today)', () => {
    const snaps = [{ date: '2026-05-29', total_value: 100, total_invested: 100, net_deposited: 100 }]
    expect(computeDailyPnl(snaps, { liveValue: 120, liveNetDeposited: 100 })).toBe(null)
  })

  it('REGRESSION: a withdrawal must NOT show as a daily loss', () => {
    // Cierre de ayer: value 10000, aportado 8000 → ganancia acumulada 2000.
    const snaps = [{ date: '2026-05-28', total_value: 10000, total_invested: 8000, net_deposited: 8000 }]
    // Hoy: retiró $160 y las tenencias subieron $50 → value 9890, aportado 7840.
    const r = computeDailyPnl(snaps, { liveValue: 9890, liveNetDeposited: 7840 })
    // El cálculo VIEJO (Δtotal_value) daría 9890 − 10000 = −110 (falso negativo).
    expect(9890 - 10000).toBe(-110)
    // El correcto: +50 reales de ganancia.
    expect(r.usd).toBeCloseTo(50, 6)
    expect(r.pct).toBeCloseTo(50 / 10000, 6)
    expect(r.prevDate).toBe('2026-05-28')
    expect(r.dayDiff).toBe(1)
  })

  it('pure gain with no cashflow equals Δvalue', () => {
    const snaps = [{ date: '2026-05-28', total_value: 10000, total_invested: 8000, net_deposited: 8000 }]
    const r = computeDailyPnl(snaps, { liveValue: 10120, liveNetDeposited: 8000 })
    expect(r.usd).toBeCloseTo(120, 6)
  })

  it('a deposit must NOT inflate the daily P&L', () => {
    const snaps = [{ date: '2026-05-28', total_value: 10000, total_invested: 8000, net_deposited: 8000 }]
    // Depositó $500 hoy, mercado plano → value 10500, aportado 8500. Viejo: +500. Correcto: 0.
    const r = computeDailyPnl(snaps, { liveValue: 10500, liveNetDeposited: 8500 })
    expect(r.usd).toBeCloseTo(0, 6)
  })

  it('snapshot-only path (no live) compares the two most recent snapshots', () => {
    const snaps = [
      { date: '2026-05-27', total_value: 10000, total_invested: 8000, net_deposited: 8000 },
      { date: '2026-05-28', total_value: 10080, total_invested: 8000, net_deposited: 8000 },
    ]
    const r = computeDailyPnl(snaps)
    expect(r.usd).toBeCloseTo(80, 6)
    expect(r.prevDate).toBe('2026-05-27')
  })

  it('legacy snapshots (net_deposited=0) fall back to total_invested', () => {
    const snaps = [{ date: '2026-05-28', total_value: 10000, total_invested: 8000, net_deposited: 0 }]
    // prevTR = 10000 − 8000 (fallback); todayTR = 10100 − 8000 → +100
    const r = computeDailyPnl(snaps, { liveValue: 10100, liveNetDeposited: 8000 })
    expect(r.usd).toBeCloseTo(100, 6)
  })

  it('reports dayDiff > 1 across a snapshot gap', () => {
    const snaps = [{ date: '2026-05-25', total_value: 10000, total_invested: 8000, net_deposited: 8000 }]
    const r = computeDailyPnl(snaps, { liveValue: 10000, liveNetDeposited: 8000 })
    expect(r.dayDiff).toBe(4) // 05-25 → 05-29
  })
})

// ── computeReturnDelta con sinceDate (variación mensual / MTD) ──────────────────

describe('computeReturnDelta — variación mensual (sinceDate)', () => {
  beforeAll(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-05-29T12:00:00Z')) })
  afterAll(() => { vi.useRealTimers() })

  const MONTH_START = '2026-05-01'

  it('mide desde el cierre del mes anterior (último snap antes del 1°)', () => {
    const snaps = [
      { date: '2026-04-30', total_value: 10000, total_invested: 8000, net_deposited: 8000 },
      { date: '2026-05-10', total_value: 10200, total_invested: 8000, net_deposited: 8000 },
    ]
    const r = computeReturnDelta(snaps, { liveValue: 10300, liveNetDeposited: 8000, sinceDate: MONTH_START })
    expect(r.usd).toBeCloseTo(300, 6)        // 10300 − 10000
    expect(r.pct).toBeCloseTo(300 / 10000, 6)
    expect(r.prevDate).toBe('2026-04-30')
  })

  it('un depósito en el mes NO infla la variación mensual', () => {
    const snaps = [{ date: '2026-04-30', total_value: 10000, total_invested: 8000, net_deposited: 8000 }]
    // Depositó $500 en mayo y el mercado subió $300 → value 10800, aportado 8500.
    const r = computeReturnDelta(snaps, { liveValue: 10800, liveNetDeposited: 8500, sinceDate: MONTH_START })
    expect(10800 - 10000).toBe(800)          // el viejo Δvalue daría +800 (falso)
    expect(r.usd).toBeCloseTo(300, 6)         // el correcto: +300
  })

  it('si empezaste DENTRO del mes (sin cierre previo) cae al snapshot más antiguo', () => {
    const snaps = [{ date: '2026-05-03', total_value: 5000, total_invested: 5000, net_deposited: 5000 }]
    const r = computeReturnDelta(snaps, { liveValue: 5100, liveNetDeposited: 5000, sinceDate: MONTH_START })
    expect(r.usd).toBeCloseTo(100, 6)
    expect(r.prevDate).toBe('2026-05-03')
  })
})


// ─── Phase C audit fix C1: convertSeriesToArs + fxToUsdBlue propagation ─────
// Verifica:
//   • buildPortfolioValueSeries propaga fx_to_usd_blue del snapshot al output
//   • convertSeriesToArs aplica el FX correcto por punto (stamped > lookup)
//   • _fxUsed se expone en cada punto para que el chart pueda mostrarlo

describe("buildPortfolioValueSeries propaga fx_to_usd_blue (Phase C)", () => {
  it("snapshot con fx_to_usd_blue lo expone como fxToUsdBlue en el output", () => {
    const snaps = [
      { date: "2025-06-01", total_value: 1000, total_invested: 800, net_deposited: 800, fx_to_usd_blue: 1200 },
      { date: "2025-06-02", total_value: 1050, total_invested: 800, net_deposited: 800, fx_to_usd_blue: 1210 },
    ]
    const series = buildPortfolioValueSeries(snaps)
    expect(series).toHaveLength(2)
    expect(series[0].fxToUsdBlue).toBe(1200)
    expect(series[1].fxToUsdBlue).toBe(1210)
  })

  it("snapshot sin fx_to_usd_blue → fxToUsdBlue=null en el output", () => {
    const snaps = [
      { date: "2025-06-01", total_value: 1000, total_invested: 800, net_deposited: 800 },
      { date: "2025-06-02", total_value: 1050, total_invested: 800, net_deposited: 800, fx_to_usd_blue: null },
    ]
    const series = buildPortfolioValueSeries(snaps)
    expect(series[0].fxToUsdBlue).toBe(null)
    expect(series[1].fxToUsdBlue).toBe(null)
  })

  it("liveFx se aplica al punto today appended", () => {
    const snaps = [
      { date: "2025-06-01", total_value: 1000, total_invested: 800, net_deposited: 800, fx_to_usd_blue: 1200 },
    ]
    const series = buildPortfolioValueSeries(snaps, null, 1100, 850, 1466)
    expect(series).toHaveLength(2)
    expect(series[1].fxToUsdBlue).toBe(1466)
  })
})

describe("convertSeriesToArs (Phase C audit fix C1)", () => {
  const getFx = (date) => {
    const m = { "2025-06-01": 1200, "2025-06-02": 1210, "2025-06-03": 1220 }
    return m[date] || null
  }

  it("usa fxToUsdBlue stampeado cuando está presente (prioridad 1)", () => {
    const series = [
      { date: "2025-06-01", valueUsd: 1000, netDeposited: 800, fxToUsdBlue: 1234 },
    ]
    const out = convertSeriesToArs(series, getFx)
    // 1000 * 1234 = 1234000 (stamped gana sobre el lookup de 1200)
    expect(out[0].valueUsd).toBe(1234000)
    expect(out[0].netDeposited).toBe(800 * 1234)
    expect(out[0]._fxUsed).toBe(1234)
  })

  it("hace fallback a getFxForDate si no hay stamped (prioridad 2)", () => {
    const series = [
      { date: "2025-06-02", valueUsd: 500, netDeposited: 400, fxToUsdBlue: null },
    ]
    const out = convertSeriesToArs(series, getFx)
    expect(out[0].valueUsd).toBe(500 * 1210)
    expect(out[0]._fxUsed).toBe(1210)
  })

  it("último fallback es 1 (no convierte) cuando getFx devuelve null", () => {
    const series = [
      { date: "2030-12-25", valueUsd: 1000, netDeposited: 800, fxToUsdBlue: null },
    ]
    const out = convertSeriesToArs(series, () => null)
    expect(out[0].valueUsd).toBe(1000)
    expect(out[0]._fxUsed).toBe(1)
  })

  it("preserva otras keys del punto", () => {
    const series = [
      { date: "2025-06-01", label: "06-01", valueUsd: 1000, netDeposited: 800, fxToUsdBlue: 1200 },
    ]
    const out = convertSeriesToArs(series, getFx)
    expect(out[0].date).toBe("2025-06-01")
    expect(out[0].label).toBe("06-01")
  })

  it("input vacío / inválido devuelve []", () => {
    expect(convertSeriesToArs([], getFx)).toEqual([])
    expect(convertSeriesToArs(null, getFx)).toEqual([])
    expect(convertSeriesToArs(undefined, getFx)).toEqual([])
  })

  it("getFxForDate no-function: no rompe, usa fallback=1", () => {
    const series = [{ date: "2025-06-01", valueUsd: 100, netDeposited: 80, fxToUsdBlue: null }]
    expect(() => convertSeriesToArs(series, null)).not.toThrow()
    const out = convertSeriesToArs(series, null)
    expect(out[0].valueUsd).toBe(100)
  })
})


// ── El clamp asimétrico eliminado ─────────────────────────────────────────────
// `Math.min(Math.max(rRaw, -0.99), 0.5)` limitaba las subidas de la CARTERA a
// +50% por mes y NO le aplicaba nada al BENCHMARK: el sesgo iba sistemáticamente
// en contra del usuario y se componía mes a mes.
describe('sin techo asimétrico', () => {
  it('un tramo de +80% NO se trunca a +50%', () => {
    const snaps = [
      { date: '2025-01-31', total_value: 100, total_invested: 100, net_deposited: 100 },
      { date: '2025-02-28', total_value: 180, total_invested: 100, net_deposited: 100 },
    ]
    const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
    expect(r.seriesUsd[1].total).toBeCloseTo(80, 1)
  })

  it('el piso de −99% sigue vigente', () => {
    const snaps = [
      { date: '2025-01-31', total_value: 100, total_invested: 100, net_deposited: 100 },
      { date: '2025-02-28', total_value: -500, total_invested: 100, net_deposited: 100 },
    ]
    const r = buildEvolutionFromSnapshots(snaps, [], BENCH, TCB)
    expect(r.seriesUsd[1].total).toBeGreaterThanOrEqual(-99)
  })
})

// ── Sólo base de mercado ──────────────────────────────────────────────────────
// `snapshots` mezcla mediciones del cron con fotos que el import FABRICA copiando
// la cadena contable: encadenarlas fabrica un desplome que nadie vivió.
describe('descarta los puntos que no son base de mercado', () => {
  const medido = (date, v) => ({ date, total_value: v, total_invested: 100, net_deposited: 100, apto: true })
  const fabricado = (date, v) => ({ date, total_value: v, total_invested: 100, net_deposited: 100, apto: false })

  it('una foto fabricada altísima no fabrica un desplome', () => {
    const r = buildEvolutionFromSnapshots(
      [fabricado('2025-01-31', 999999), medido('2025-02-28', 100), medido('2025-03-31', 110)],
      [], BENCH, TCB)
    expect(r.seriesUsd).toHaveLength(2)
    expect(r.seriesUsd[1].total).toBeCloseTo(10, 1)   // +10%, no −99,99%
  })

  it('acepta el nombre viejo `sintetico` (backend anterior al cambio)', () => {
    const r = buildEvolutionFromSnapshots(
      [{ date: '2025-01-31', total_value: 999999, total_invested: 100, net_deposited: 100, sintetico: true },
       { date: '2025-02-28', total_value: 100, total_invested: 100, net_deposited: 100, sintetico: false },
       { date: '2025-03-31', total_value: 110, total_invested: 100, net_deposited: 100, sintetico: false }],
      [], BENCH, TCB)
    expect(r.seriesUsd).toHaveLength(2)
  })

  it('sin la marca (fixture viejo) no se descarta nada', () => {
    const r = buildEvolutionFromSnapshots(
      [{ date: '2025-01-31', total_value: 100, total_invested: 100, net_deposited: 100 },
       { date: '2025-02-28', total_value: 110, total_invested: 100, net_deposited: 100 }],
      [], BENCH, TCB)
    expect(r.seriesUsd).toHaveLength(2)
  })

  it('si queda menos de 2 puntos medidos devuelve null (el caller cae a monthly)', () => {
    const r = buildEvolutionFromSnapshots(
      [fabricado('2025-01-31', 100), medido('2025-02-28', 110)], [], BENCH, TCB)
    expect(r).toBe(null)
  })
})

// ═══════════════════════════════════════════════════════════════════════════
// RONDA 2 — lo que la pasada adversarial encontró abierto.
// ═══════════════════════════════════════════════════════════════════════════
describe('ronda 2 — la función que MIDE aunque se llame build...Evolution', () => {
  const TCB2 = 1500
  const med = (date, v, nd = 100) => ({ date, total_value: v, total_invested: 100, net_deposited: nd, apto: true, clase: 'medicion' })
  const intra = (date, v, nd = 100) => ({ date, total_value: v, total_invested: 100, net_deposited: nd, apto: false, clase: 'intradia' })

  it('una foto INTRADIA no entra al chain-link ni fija el pico', () => {
    // ⚠️ EL FIXTURE TIENE QUE PODER FALLAR: la intradía va con un valor MUY por
    // encima de los cierres. Si vuelve a entrar, es denominador de un período y
    // pico de la serie, y el acumulado se mueve. Es la forma del uid 93, que con
    // UNA sola intradía pasaba de +7,82% a −33,44%.
    const conIntra = [med('2026-01-31', 100), intra('2026-02-10', 400), med('2026-02-28', 110)]
    const sinIntra = [med('2026-01-31', 100), med('2026-02-28', 110)]
    const a = buildEvolutionFromSnapshots(conIntra, [], BENCH, TCB2)
    const b = buildEvolutionFromSnapshots(sinIntra, [], BENCH, TCB2)
    expect(a.seriesUsd.at(-1).total).toBeCloseTo(b.seriesUsd.at(-1).total, 6)
    // y la intradía tampoco aporta un punto a la serie medida
    expect(a.seriesUsd).toHaveLength(2)
  })

  it('§4.4 adentro del chain-link: net_deposited NEGATIVO no cae al cost basis', () => {
    // ⚠️ CON `net_deposited` POSITIVO ESTE BUG ES INEXHIBIBLE. Los dos cierres
    // tienen el MISMO nd negativo → flujos 0 → el retorno es el movimiento puro.
    // Con el `> 0` viejo, ambos caían a `total_invested` (100 y 100) y daba lo
    // mismo por casualidad; acá `total_invested` DIFIERE entre las dos filas, que
    // es lo que destapa la contaminación.
    const s = [
      { date: '2026-01-31', total_value: 1000, total_invested: 800, net_deposited: -500, apto: true, clase: 'medicion' },
      { date: '2026-02-28', total_value: 1100, total_invested: 900, net_deposited: -500, apto: true, clase: 'medicion' },
    ]
    const r = buildEvolutionFromSnapshots(s, [], BENCH, TCB2)
    // flujos = (−500) − (−500) = 0 → retorno = (1100 − 1000) / 1000 = +10%
    expect(r.seriesUsd.at(-1).total).toBeCloseTo(10, 6)
  })

  it('el 0 SIGUE significando "no lo tengo" (fallback legacy vivo)', () => {
    const s = [
      { date: '2026-01-31', total_value: 1000, total_invested: 900, net_deposited: 0, apto: true, clase: 'medicion' },
      { date: '2026-02-28', total_value: 1100, total_invested: 900, net_deposited: 0, apto: true, clase: 'medicion' },
    ]
    const r = buildEvolutionFromSnapshots(s, [], BENCH, TCB2)
    expect(r.seriesUsd.at(-1).total).toBeCloseTo(10, 6)
  })
})

describe('ronda 2 — un cero falso es peor que un vacío', () => {
  it('base negativa no publica "0,00%" con un monto al lado', () => {
    // uid 1 en producción: +US$2.026,35 contra 0,00%, con base −11,92.
    const s = [
      { date: '2026-06-04', total_value: -11.92, total_invested: 10, net_deposited: 10, apto: true, clase: 'medicion' },
      { date: '2026-08-16', total_value: 2000, total_invested: 10, net_deposited: 10, apto: true, clase: 'medicion' },
    ]
    expect(computeReturnDelta(s, { sinceDate: '2026-07-01' })).toBe(null)
  })

  it('base positiva sigue publicando normal', () => {
    const s = [
      { date: '2026-06-30', total_value: 1000, total_invested: 900, net_deposited: 900, apto: true, clase: 'medicion' },
      { date: '2026-08-16', total_value: 1100, total_invested: 900, net_deposited: 900, apto: true, clase: 'medicion' },
    ]
    const d = computeReturnDelta(s, { sinceDate: '2026-07-01' })
    expect(d).not.toBe(null)
    expect(d.pct).toBeCloseTo(0.1, 6)
  })
})

describe('ronda 2 — el vacío tiene que hablar', () => {
  it('cuenta vacía → null (el vacío de siempre, no un sermón)', () => {
    expect(diagnosticoSinMedicion([])).toBe(null)
    expect(diagnosticoSinMedicion(null)).toBe(null)
  })

  it('57 filas y ninguna medida → dice cuántas hay y que son del import', () => {
    // El uid 107 real: 57 snapshots, 0 medibles. El mensaje viejo le pedía
    // "cargá tus snapshots diarios" — o sea lo que ya hizo.
    const s = Array.from({ length: 57 }, (_, i) => ({
      date: `2026-0${1 + (i % 6)}-1${i % 9}`, total_value: 100, apto: false, clase: 'sintetico_costo',
    }))
    const d = diagnosticoSinMedicion(s)
    expect(d).not.toBe(null)
    expect(d.filas).toBe(57)
    expect(d.medidas).toBe(0)
    const txt = textoSinMedicion(d)
    expect(txt).toContain('57')
    expect(txt).not.toMatch(/carg[áa] tus snapshots/i)
  })

  it('con 2 mediciones no dice nada (hay número)', () => {
    const s = [
      { date: '2026-08-15', total_value: 100, apto: true, clase: 'medicion' },
      { date: '2026-08-16', total_value: 110, apto: true, clase: 'medicion' },
    ]
    expect(diagnosticoSinMedicion(s)).toBe(null)
  })
})
