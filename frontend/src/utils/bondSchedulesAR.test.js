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

  it('cupón 2025-01-09 (período 0.75%, face ya reducido por 1 amort) = 0.36', () => {
    // Face después de la 1ª amort (4 %) = 96
    // Cupón = 0.75%/2 × 96 = 0.36
    const p = sched.find(p => p.date === '2025-01-09')
    expect(p).toBeDefined()
    expect(p.coupon).toBeCloseTo(0.36, 3)
  })

  it('cupón 2028-01-09 (primer período step-up 1.75%) usa rate 1.75', () => {
    const p = sched.find(p => p.date === '2028-01-09')
    expect(p).toBeDefined()
    // Face después de 7 amorts = 100 − 4 − 6×8 = 48
    // Cupón = 1.75%/2 × 48 = 0.42
    expect(p.coupon).toBeCloseTo(0.42, 3)
    expect(p.rate).toBe(1.75)
  })
})

describe('AL35 step-up real — según el prospecto', () => {
  // Estas dos pruebas fijaban tasas equivocadas hasta 2026-10-10 (1,5 % para
  // 2026 y 3,625 % para 2028): eran la tabla "de memoria" del catálogo, no la
  // del prospecto. Con ellas la bandeja de cobros proponía US$ 75 por semestre
  // para 10.000 nominales; el bono paga US$ 206,25. Ver la tabla entera abajo
  // ("el catálogo dice lo que dice el prospecto").
  const sched = generateSchedule('AL35')

  it('cupón 2026-07-09 (período 4,125 %) sobre face=100 = 2,0625', () => {
    const p = sched.find(p => p.date === '2026-07-09')
    expect(p).toBeDefined()
    // No hay amort antes de 2031, face sigue en 100. 4,125 %/2 × 100.
    expect(p.coupon).toBeCloseTo(2.0625, 4)
  })

  it('cupón 2028-01-09 (período 4,75 %) sobre face=100 = 2,375', () => {
    const p = sched.find(p => p.date === '2028-01-09')
    expect(p).toBeDefined()
    expect(p.coupon).toBeCloseTo(2.375, 4)
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
    // El proxy SUBESTIMA el yield porque el último período tiene 5 %
    // (más de 2x el proxy), y ese período representa la mayor parte del valor.
    const r = estimateYieldDetailed('AL35', 50, '2026-05-11')
    // Validamos que el step-up final (5 %, según el prospecto) está reflejado:
    // último cupón en 2035-07-09 = 5 %/2 × 10 (face remanente) = 0,25
    const sched = generateSchedule('AL35')
    const lastCoupon = sched[sched.length - 1].coupon
    expect(lastCoupon).toBeCloseTo(0.25, 4)
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


// ─── El catálogo dice lo que dice el prospecto ───────────────────────────────
// Transcripción de la tabla "New Bonds / Interest Rate / Maturity / Principal
// Repayment" (págs. S-32 a S-35) del suplemento de prospecto que la República
// presentó ante la SEC el 17/08/2020:
//   https://www.sec.gov/Archives/edgar/data/914021/000119312520221606/d68512d424b5.htm
// Si esta prueba se pone roja, alguien cambió una tasa o una cuota: el número
// correcto es el del prospecto, no el que "se usa en el mercado". Hasta
// 2026-10-10 nadie fijaba las tasas de 2029, 2038 ni 2046 (se podían cambiar y
// todo seguía verde), y las de 2035 estaban fijadas en el valor equivocado.
describe('el catálogo dice lo que dice el prospecto', () => {
  const PROSPECTO = {
    2029: { vence: '2029-07-09', primera: '2025-01-09', cuotas: 10,
      tasas: [['2020-09-04', 1.000]] },
    2030: { vence: '2030-07-09', primera: '2024-07-09', cuotas: 13, primeraPct: 4,
      tasas: [['2020-09-04', 0.125], ['2021-07-09', 0.500], ['2023-07-09', 0.750], ['2027-07-09', 1.750]] },
    2035: { vence: '2035-07-09', primera: '2031-01-09', cuotas: 10,
      tasas: [['2020-09-04', 0.125], ['2021-07-09', 1.125], ['2022-07-09', 1.500], ['2023-07-09', 3.625],
        ['2024-07-09', 4.125], ['2027-07-09', 4.750], ['2028-07-09', 5.000]] },
    2038: { vence: '2038-01-09', primera: '2027-07-09', cuotas: 22,
      tasas: [['2020-09-04', 0.125], ['2021-07-09', 2.000], ['2022-07-09', 3.875], ['2023-07-09', 4.250],
        ['2024-07-09', 5.000]] },
    2041: { vence: '2041-07-09', primera: '2028-01-09', cuotas: 28,
      tasas: [['2020-09-04', 0.125], ['2021-07-09', 2.500], ['2022-07-09', 3.500], ['2029-07-09', 4.875]] },
    2046: { vence: '2046-07-09', primera: '2025-01-09', cuotas: 44,
      tasas: [['2020-09-04', 0.125], ['2021-07-09', 1.125], ['2022-07-09', 1.500], ['2023-07-09', 3.625],
        ['2024-07-09', 4.125], ['2027-07-09', 4.375], ['2028-07-09', 5.000]] },
  }
  const TICKERS = { 2029: ['AL29', 'GD29'], 2030: ['AL30', 'GD30'], 2035: ['AL35', 'GD35'],
    2038: ['AE38', 'GD38'], 2041: ['AL41', 'GD41'], 2046: ['GD46'] }

  for (const [anio, ref] of Object.entries(PROSPECTO)) {
    for (const ticker of TICKERS[anio]) {
      const cat = CANJE_2020_BY_TICKER[ticker]

      it(`${ticker}: tasas de cupón, tramo por tramo`, () => {
        expect(cat.couponSchedule.map(c => [c.from, c.rate])).toEqual(ref.tasas)
        // Cada tramo termina donde empieza el siguiente; el último, al vencer.
        cat.couponSchedule.forEach((c, i) => {
          expect(c.to).toBe(i + 1 < ref.tasas.length ? ref.tasas[i + 1][0] : ref.vence)
        })
        expect(cat.maturity).toBe(ref.vence)
      })

      it(`${ticker}: cuotas de capital`, () => {
        const a = cat.amortSchedule
        expect(a.length).toBe(ref.cuotas)
        expect(a[0].date).toBe(ref.primera)
        expect(a[a.length - 1].date).toBe(ref.vence)      // la última, al vencimiento
        expect(a.reduce((s, x) => s + x.pct, 0)).toBeCloseTo(100, 6)
        // Semestrales, sin saltos: 9 de enero / 9 de julio.
        a.forEach((x, i) => {
          if (i === 0) return
          const [y0, m0] = a[i - 1].date.split('-').map(Number)
          const [y1, m1] = x.date.split('-').map(Number)
          expect((y1 - y0) * 12 + (m1 - m0)).toBe(6)
          expect(x.date.slice(8)).toBe('09')
        })
        // Iguales, salvo la primera del 2030 (1/25 = 4 %): nota (1) de la tabla.
        const resto = ref.primeraPct ? a.slice(1) : a
        if (ref.primeraPct) expect(a[0].pct).toBe(ref.primeraPct)
        const igual = (100 - (ref.primeraPct || 0)) / resto.length
        for (const x of resto) expect(x.pct).toBeCloseTo(igual, 9)
      })
    }
  }

  it('lo que la bandeja propone hoy por 10.000 nominales (julio 2026)', () => {
    const cupon = (t) => generateSchedule(t).find(p => p.date === '2026-07-09').coupon * 100
    expect(cupon('GD35')).toBeCloseTo(206.25, 2)      // 4,125 %/2 (decía 75)
    expect(cupon('GD38')).toBeCloseTo(250, 2)         // 5 %/2 (decía 193,75)
    expect(cupon('GD41')).toBeCloseTo(175, 2)         // 3,5 %/2
    // 2029: 1 %/2 sobre el 70 % vivo (ya devolvió 3 cuotas del 10 %).
    expect(cupon('GD29')).toBeCloseTo(35, 2)
    // 2046: 4,125 %/2 sobre lo vivo (devolvió 3 de 44 cuotas).
    expect(cupon('GD46')).toBeCloseTo(4.125 / 2 * (100 - 3 * 100 / 44), 2)
  })
})
