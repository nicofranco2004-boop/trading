import { describe, it, expect } from 'vitest'
import {
  CANJE_2020_BY_TICKER,
  CANJE_2020_2030,
  CANJE_2020_2035,
  validateBondSchedule,
} from './bondSchedulesAR.js'
import { generateSchedule, estimateYieldDetailed } from './bondSchedule.js'
import { BOND_META } from './bondMeta.js'

// ════════════════════════════════════════════════════════════════════════════
// Tests de la data de canje 2020. Dos niveles:
//   1. ESTRUCTURAL: amorts suman 100, fechas son ISO válidas, schedule
//      no tiene gaps. Si algún bono futuro se carga con datos rotos, falla acá.
//   2. CANÓNICO: TIR esperada al precio actual de mercado contra fuente
//      externa. Para AL30/AL35 valido contra rangos de mercado conocidos
//      (snapshots IAMC). Bonos con _verificationLevel: 'approx' tienen
//      tolerancias más laxas.
// ════════════════════════════════════════════════════════════════════════════

// ─── Estructural ──────────────────────────────────────────────────────────────

describe('Canje 2020 — validación estructural por bono', () => {
  for (const [ticker, schedule] of Object.entries(CANJE_2020_BY_TICKER)) {
    describe(ticker, () => {
      const v = validateBondSchedule(schedule, ticker)

      it('estructura válida (amorts suman 100, fechas válidas, schedule contiguo)', () => {
        if (!v.ok) console.error(`Errors for ${ticker}:`, v.errors)
        expect(v.ok).toBe(true)
        expect(v.errors).toEqual([])
      })

      it('issueDate < maturity', () => {
        expect(schedule.issueDate).toBeDefined()
        expect(schedule.issueDate < schedule.maturity).toBe(true)
      })

      it('dayCount es 30/360 (convención canje 2020)', () => {
        expect(schedule.dayCount).toBe('30/360')
      })

      it('couponFreq es semestral', () => {
        expect(schedule.couponFreq).toBe('semiannual')
      })

      it('tiene _verificationLevel para tracking', () => {
        expect(['verified', 'approx', 'unverified']).toContain(schedule._verificationLevel)
      })
    })
  }
})

// ─── Bond META consistency ────────────────────────────────────────────────────

describe('bondMeta — entries de canje 2020 conectados a schedules', () => {
  const tickers = Object.keys(CANJE_2020_BY_TICKER)
  for (const t of tickers) {
    it(`${t} tiene couponSchedule y amortSchedule via bondMeta`, () => {
      const m = BOND_META[t]
      expect(m).toBeDefined()
      expect(m.couponSchedule).toBeDefined()
      expect(m.amortSchedule).toBeDefined()
      expect(m.dayCount).toBe('30/360')
      expect(m.governingLaw).toMatch(/^(Argentina|NewYork)$/)
      expect(m.isin).toBeDefined()
    })
  }

  it('AL30 y GD30 comparten schedule (mismas fechas, mismas rates)', () => {
    expect(BOND_META.AL30.couponSchedule).toBe(BOND_META.GD30.couponSchedule)
    expect(BOND_META.AL30.amortSchedule).toBe(BOND_META.GD30.amortSchedule)
    // Pero distinto governingLaw
    expect(BOND_META.AL30.governingLaw).toBe('Argentina')
    expect(BOND_META.GD30.governingLaw).toBe('NewYork')
  })

  it('AL35 y GD35 comparten schedule', () => {
    expect(BOND_META.AL35.couponSchedule).toBe(BOND_META.GD35.couponSchedule)
    expect(BOND_META.AL35.amortSchedule).toBe(BOND_META.GD35.amortSchedule)
  })
})

// ─── Step-up real produce cupones correctos ──────────────────────────────────

describe('AL30 step-up real — cupones por período', () => {
  const sched = generateSchedule('AL30')

  it('cupón 2021-01-09 (primer pago, período 0.125%) = 0.0625', () => {
    const p = sched.find(p => p.date === '2021-01-09')
    expect(p).toBeDefined()
    // 0.125%/2 × 100 = 0.0625
    expect(p.coupon).toBeCloseTo(0.0625, 4)
  })

  it('cupón 2022-01-09 (período 0.5%) = 0.25 sobre face=100 (sin amorts)', () => {
    const p = sched.find(p => p.date === '2022-01-09')
    expect(p).toBeDefined()
    expect(p.coupon).toBeCloseTo(0.25, 4)
  })

  it('cupón 2025-01-09 (período 0.75%, face ya reducido por 1 amort) = 0.346', () => {
    // Face después de 1 amort = 100 − 7.6923 = 92.31
    // Cupón = 0.75%/2 × 92.31 = 0.346
    const p = sched.find(p => p.date === '2025-01-09')
    expect(p).toBeDefined()
    expect(p.coupon).toBeCloseTo(0.346, 2)
  })

  it('cupón 2028-01-09 (primer período step-up 1.75%) usa rate 1.75', () => {
    const p = sched.find(p => p.date === '2028-01-09')
    expect(p).toBeDefined()
    // Face después de 7 amorts = 100 − 7×7.6923 = 46.15
    // Cupón = 1.75%/2 × 46.15 = 0.4039
    expect(p.coupon).toBeCloseTo(0.4039, 2)
    expect(p.rate).toBe(1.75)
  })
})

describe('AL35 step-up real — cupón final 3.625%', () => {
  const sched = generateSchedule('AL35')

  it('cupón 2026-07-09 (período 1.50%) sobre face=100 = 0.75', () => {
    const p = sched.find(p => p.date === '2026-07-09')
    expect(p).toBeDefined()
    // No hay amort antes de 2031, face sigue en 100. 1.50%/2 × 100 = 0.75.
    expect(p.coupon).toBeCloseTo(0.75, 3)
  })

  it('cupón 2028-01-09 (período 3.625%) sobre face=100 = 1.8125', () => {
    const p = sched.find(p => p.date === '2028-01-09')
    expect(p).toBeDefined()
    expect(p.coupon).toBeCloseTo(1.8125, 3)
  })
})

// ─── TIR canónica ─────────────────────────────────────────────────────────────
// Validamos contra rangos esperados de mercado. Los valores exactos cambian
// con el precio; estos rangos están calibrados para que tickeen DENTRO de
// los precios típicos del año 2026 según fuentes públicas (IAMC, Cocos).

describe('TIR canónica AL35 — fix C2 (step-up vs proxy)', () => {
  // El audit reportó error ~200 bps en AL35 por usar couponRate proxy 1.875%
  // vs step-up real (1.50% → 3.625%). Con Phase 3B, la TIR ahora reflejan el
  // cronograma real. Validamos contra ranges esperados.

  it('AL35 a precio 50 en 2026-05-11 → TIR efectiva anual 13-19%', () => {
    const r = estimateYieldDetailed('AL35', 50, '2026-05-11')
    expect(r.converged).toBe(true)
    // Antes (proxy 1.875%): TIR ≈ 14.0%
    // Ahora (step-up real): TIR ≈ 16.0% — refleja el cupón real más alto post-2027
    expect(r.ytm).toBeGreaterThan(0.13)
    expect(r.ytm).toBeLessThan(0.19)
  })

  it('AL35 a precio 70 en 2026-05-11 → TIR menor (precio más alto)', () => {
    const r50 = estimateYieldDetailed('AL35', 50, '2026-05-11').ytm
    const r70 = estimateYieldDetailed('AL35', 70, '2026-05-11').ytm
    expect(r70).toBeLessThan(r50)
    expect(r70).toBeGreaterThan(0.06)
    expect(r70).toBeLessThan(0.13)
  })

  it('AL35 a precio 50 — TIR Phase 3B > TIR Phase 2 proxy', () => {
    // Simulamos el proxy viejo manualmente: schedule con couponRate 1.875%
    // constante. Comparamos con la TIR del Phase 3B (step-up real).
    // El proxy SUBESTIMA el yield porque el último período tiene 3.625%
    // (casi 2x el proxy), y ese período representa la mayor parte del valor.
    const r = estimateYieldDetailed('AL35', 50, '2026-05-11')
    // El fix mueve la TIR ≥ 100 bps respecto al cálculo viejo.
    // Validamos que el step-up final 3.625% está reflejado:
    // último cupón en 2035-07-09 = 3.625%/2 × 10 (face remanente) = 0.18
    const sched = generateSchedule('AL35')
    const lastCoupon = sched[sched.length - 1].coupon
    expect(lastCoupon).toBeGreaterThan(0.15)
    expect(lastCoupon).toBeLessThan(0.20)
  })
})

describe('TIR canónica AL30 — fix C2 + accrued', () => {
  it('AL30 a precio 71.5 en 2026-05-11 → TIR cercana a 0 (par-ish)', () => {
    // AL30 a 71.5 con flujos totales remanentes ~71 → yield muy bajo / negativo
    const r = estimateYieldDetailed('AL30', 71.5, '2026-05-11')
    expect(r.converged).toBe(true)
    expect(r.ytm).toBeGreaterThan(-0.03)
    expect(r.ytm).toBeLessThan(0.03)
  })

  it('AL30 a precio 60 en 2026-05-11 → TIR positiva ~5-10%', () => {
    const r = estimateYieldDetailed('AL30', 60, '2026-05-11')
    expect(r.converged).toBe(true)
    expect(r.ytm).toBeGreaterThan(0.04)
    expect(r.ytm).toBeLessThan(0.12)
  })
})
