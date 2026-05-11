import { describe, it, expect } from 'vitest'
import {
  dayCountFraction,
  computeAccrued,
  yieldToMaturity,
  cleanToDirty,
  dirtyToClean,
  semiAnnualToEffectiveAnnual,
  effectiveAnnualToSemiAnnual,
} from './bondPricing.js'

// ════════════════════════════════════════════════════════════════════════════
// Cada test compara contra un valor canónico de la literatura de bond pricing
// (Fabozzi, Hull, Bloomberg DCC reference). NO son tests "compará-con-tu-propio-
// output"; son tests "el resultado es lo que dice la industria que tiene que
// ser". Si fallan, el bug está en NUESTRO código (o en cómo interpretamos la
// convención), no en la convención.
// ════════════════════════════════════════════════════════════════════════════

// ─── dayCountFraction ─────────────────────────────────────────────────────────

describe('dayCountFraction — 30/360 US (BMA/SIA)', () => {
  it('un mes "normal" (día 1 al día 1) = 30 días = 30/360 año', () => {
    expect(dayCountFraction('2025-01-01', '2025-02-01', '30/360')).toBeCloseTo(30 / 360, 6)
  })
  it('un semestre (días iguales) = 180 días = 0.5 año', () => {
    expect(dayCountFraction('2025-01-09', '2025-07-09', '30/360')).toBeCloseTo(0.5, 6)
  })
  it('un año completo (mismo día/mes, año siguiente) = 1.0', () => {
    expect(dayCountFraction('2025-01-09', '2026-01-09', '30/360')).toBeCloseTo(1.0, 6)
  })
  it('regla de ajuste 31→30: 31 enero a 1 marzo = 30+1 = 31/360', () => {
    // d1 = min(31, 30) = 30
    // d2 = 1  (no aplica regla de "30 cuando d1=30 y d2=31")
    // days = 360×0 + 30×(3-1) + (1-30) = 60 - 29 = 31
    expect(dayCountFraction('2025-01-31', '2025-03-01', '30/360')).toBeCloseTo(31 / 360, 6)
  })
  it('regla d1=30, d2=31: el 31 se baja a 30', () => {
    // from 2025-03-30, to 2025-07-31: d1=30, d2=31 → d2'=30
    // days = 0 + 30×(7-3) + (30-30) = 120
    expect(dayCountFraction('2025-03-30', '2025-07-31', '30/360')).toBeCloseTo(120 / 360, 6)
  })
})

describe('dayCountFraction — ACT/365 Fixed', () => {
  it('un año NO bisiesto cuenta 365 días', () => {
    expect(dayCountFraction('2025-01-01', '2026-01-01', 'ACT/365')).toBeCloseTo(365 / 365, 6)
  })
  it('un año BISIESTO cuenta 366 días (sobre 365 fijo → >1 año)', () => {
    expect(dayCountFraction('2024-01-01', '2025-01-01', 'ACT/365')).toBeCloseTo(366 / 365, 6)
  })
  it('febrero NO bisiesto (28 días)', () => {
    expect(dayCountFraction('2025-02-01', '2025-03-01', 'ACT/365')).toBeCloseTo(28 / 365, 6)
  })
})

describe('dayCountFraction — ACT/ACT-ISDA', () => {
  it('mismo año NO bisiesto: días reales / 365', () => {
    expect(dayCountFraction('2025-02-01', '2025-03-01', 'ACT/ACT-ISDA')).toBeCloseTo(28 / 365, 6)
  })
  it('mismo año BISIESTO: días reales / 366', () => {
    expect(dayCountFraction('2024-02-01', '2024-03-01', 'ACT/ACT-ISDA')).toBeCloseTo(29 / 366, 4)
  })
  it('período cruzando bisiesto → contribución mixta', () => {
    // 2024-07-01 a 2025-07-01: cruza año bisiesto 2024 y arranca 2025 no-bisiesto
    // Contribución 2024: 184 días (jul-dec) / 366 ≈ 0.5027
    // Contribución 2025: 181 días (ene-jun) / 365 ≈ 0.4959
    // Total ≈ 0.9986 (un poco menor que 1.0 porque hay un día menos en 2025)
    const r = dayCountFraction('2024-07-01', '2025-07-01', 'ACT/ACT-ISDA')
    expect(r).toBeGreaterThan(0.99)
    expect(r).toBeLessThan(1.01)
  })
})

describe('dayCountFraction — comparativa entre convenciones', () => {
  it('30/360 ≠ ACT/365 en meses no-30 (febrero)', () => {
    const f30 = dayCountFraction('2025-02-01', '2025-03-01', '30/360')
    const f365 = dayCountFraction('2025-02-01', '2025-03-01', 'ACT/365')
    expect(f30).toBeCloseTo(30 / 360, 6)
    expect(f365).toBeCloseTo(28 / 365, 6)
    expect(f30).toBeGreaterThan(f365)
  })
  it('ACT/360 > ACT/365 para el mismo período (denominador más chico)', () => {
    expect(dayCountFraction('2025-01-01', '2026-01-01', 'ACT/360'))
      .toBeGreaterThan(dayCountFraction('2025-01-01', '2026-01-01', 'ACT/365'))
  })
})

describe('dayCountFraction — edge cases', () => {
  it('mismas fechas → 0', () => {
    expect(dayCountFraction('2025-01-01', '2025-01-01', '30/360')).toBe(0)
  })
  it('input inválido → 0', () => {
    expect(dayCountFraction('not-a-date', '2025-01-01', '30/360')).toBe(0)
    expect(dayCountFraction(null, '2025-01-01', '30/360')).toBe(0)
  })
})

// ─── yieldToMaturity — casos canónicos de bond pricing ───────────────────────

describe('yieldToMaturity — casos canónicos', () => {
  it('bullet anual 5%, par 100, 5 años → TIR = 5% efectivo anual', () => {
    // cf = [5, 5, 5, 5, 105]. Verificación inversa:
    // NPV @ 5% = 5/1.05 + 5/1.1025 + 5/1.157625 + 5/1.21550625 + 105/1.2762815625
    //        = 4.7619 + 4.5351 + 4.3192 + 4.1135 + 82.2702 = 99.9999 ≈ 100 ✓
    const cf = []
    for (let i = 1; i <= 5; i++) cf.push({ t: i, amount: i === 5 ? 105 : 5 })
    const r = yieldToMaturity({ dirtyPrice: 100, cashflows: cf })
    expect(r.converged).toBe(true)
    expect(r.ytm).toBeCloseTo(0.05, 5)
  })

  it('zero-cupón 5 años descontado a 78.3526 → TIR = 5%', () => {
    // PV = 100 / (1.05)^5 = 78.35262 → si pagás 78.3526, yield = 5%
    const r = yieldToMaturity({ dirtyPrice: 78.3526, cashflows: [{ t: 5, amount: 100 }] })
    expect(r.converged).toBe(true)
    expect(r.ytm).toBeCloseTo(0.05, 4)
  })

  it('zero-cupón 5 años a precio par 100 → TIR = 0%', () => {
    const r = yieldToMaturity({ dirtyPrice: 100, cashflows: [{ t: 5, amount: 100 }] })
    expect(r.converged).toBe(true)
    expect(r.ytm).toBeCloseTo(0, 6)
  })

  it('bullet semestral 4% TNA, par 100, 5 años → TIR semestral ≈ 2%', () => {
    // 10 cupones de 2 + face 100 al final. Si par, yield semestral = 2%.
    // Efectivo anual = (1.02)^2 - 1 = 4.04%.
    const cf = []
    for (let i = 1; i <= 10; i++) cf.push({ t: i / 2, amount: i === 10 ? 102 : 2 })
    const r = yieldToMaturity({ dirtyPrice: 100, cashflows: cf })
    expect(r.converged).toBe(true)
    // Convertimos para verificar: TIR efectiva anual obtenida ≈ 4.04%
    // Pero el output de yieldToMaturity está expresado en la fracción de año
    // del t input. Acá t está en años → output es efectivo anual.
    expect(r.ytm).toBeCloseTo(0.0404, 4)
  })

  it('bono con prima (precio > flujos) → TIR negativa', () => {
    // 1 flujo de 105 en 1 año, pagado 110 → yield = 105/110 − 1 = -4.55%
    const r = yieldToMaturity({ dirtyPrice: 110, cashflows: [{ t: 1, amount: 105 }] })
    expect(r.converged).toBe(true)
    expect(r.ytm).toBeCloseTo(-0.04545, 4)
  })

  it('distressed: zero a 1 año cotizando 50 → TIR = 100%', () => {
    // 100 / (1+r) = 50 → r = 1
    const r = yieldToMaturity({ dirtyPrice: 50, cashflows: [{ t: 1, amount: 100 }] })
    expect(r.converged).toBe(true)
    expect(r.ytm).toBeCloseTo(1.0, 4)
  })

  it('hyper-distressed: zero a 5 años cotizando 5 → TIR > 80% (bracket auto-expand)', () => {
    // 100 / (1+r)^5 = 5 → (1+r)^5 = 20 → r = 20^(1/5) - 1 = 0.8206
    const r = yieldToMaturity({ dirtyPrice: 5, cashflows: [{ t: 5, amount: 100 }] })
    expect(r.converged).toBe(true)
    expect(r.ytm).toBeCloseTo(0.8206, 3)
  })

  it('precio absurdamente alto vs flujos → bracket_failed graceful', () => {
    // 1 USD de flujo, pagado 100 → yield = -99%, fuera del bracket razonable
    const r = yieldToMaturity({ dirtyPrice: 100, cashflows: [{ t: 1, amount: 1 }] })
    // Después de auto-expansión, debe converger a algo cerca de -0.99 o
    // devolver bracket_failed. Cualquiera de las dos es aceptable.
    expect(r.ytm === null || r.ytm < -0.95).toBe(true)
  })

  it('precio = 0 → invalid_price', () => {
    const r = yieldToMaturity({ dirtyPrice: 0, cashflows: [{ t: 1, amount: 100 }] })
    expect(r.converged).toBe(false)
    expect(r.method).toBe('invalid_price')
  })

  it('cashflows vacíos → no_cashflows', () => {
    const r = yieldToMaturity({ dirtyPrice: 100, cashflows: [] })
    expect(r.converged).toBe(false)
    expect(r.method).toBe('no_cashflows')
  })

  it('output incluye método e iteraciones para diagnóstico', () => {
    const cf = [{ t: 1, amount: 105 }]
    const r = yieldToMaturity({ dirtyPrice: 100, cashflows: cf })
    expect(r.method).toBeDefined()
    expect(typeof r.iterations).toBe('number')
  })

  it('amortizing bond (cashflows decrecientes) converge igual', () => {
    // AL30-like: amorts iguales + cupones decrecientes. Sum flows = 70.20.
    // A precio 65 (descuento sobre flows) → yield positivo.
    const cf = [
      { t: 0.5, amount: 8.0 },
      { t: 1.0, amount: 7.95 },
      { t: 1.5, amount: 7.90 },
      { t: 2.0, amount: 7.85 },
      { t: 2.5, amount: 7.80 },
      { t: 3.0, amount: 7.75 },
      { t: 3.5, amount: 7.70 },
      { t: 4.0, amount: 7.65 },
      { t: 4.5, amount: 7.60 },
    ]
    const totalFlows = cf.reduce((s, x) => s + x.amount, 0)  // 70.20
    // Comprado a 65 (debajo de flows) → TIR positiva ~5%
    const rPos = yieldToMaturity({ dirtyPrice: 65, cashflows: cf })
    expect(rPos.converged).toBe(true)
    expect(rPos.ytm).toBeGreaterThan(0.02)
    expect(rPos.ytm).toBeLessThan(0.10)
    // Comprado a 71.5 (arriba de flows sin descontar) → TIR ligeramente negativa
    const rNeg = yieldToMaturity({ dirtyPrice: 71.5, cashflows: cf })
    expect(rNeg.converged).toBe(true)
    expect(rNeg.ytm).toBeLessThan(0)
    expect(rNeg.ytm).toBeGreaterThan(-0.05)
  })
})

// ─── computeAccrued ──────────────────────────────────────────────────────────

describe('computeAccrued', () => {
  // Schedule canónico: bono bullet semestral 4% TNA con face 100 al maturity.
  // Cupones de 2 por período.
  const sched = [
    { date: '2025-01-09', coupon: 2, amort: 0, total: 2 },
    { date: '2025-07-09', coupon: 2, amort: 0, total: 2 },
    { date: '2026-01-09', coupon: 2, amort: 100, total: 102 },
  ]

  it('día después de cupón → accrued ≈ 0', () => {
    const a = computeAccrued(sched, '2025-01-10', '30/360')
    expect(a).toBeGreaterThanOrEqual(0)
    expect(a).toBeLessThan(0.05)
  })

  it('mid-period exacto → accrued = cupón × 50%', () => {
    // 2025-04-09 = 3 meses después de 2025-01-09 (semestre)
    const a = computeAccrued(sched, '2025-04-09', '30/360')
    expect(a).toBeCloseTo(1.0, 2)
  })

  it('día antes del próximo cupón → accrued ≈ cupón completo', () => {
    const a = computeAccrued(sched, '2025-07-08', '30/360')
    expect(a).toBeGreaterThan(1.95)
    expect(a).toBeLessThan(2.0)
  })

  it('en la fecha de pago → accrued = 0 (post-cupón)', () => {
    // 2025-07-09: el cupón se acaba de pagar, accrued resetea.
    // El "next payment" pasa a ser 2026-01-09; el "prev" es 2025-07-09;
    // elapsed = 0 día → accrued = 0.
    const a = computeAccrued(sched, '2025-07-09', '30/360')
    expect(a).toBeCloseTo(0, 4)
  })

  it('schedule vacío → 0', () => {
    expect(computeAccrued([], '2025-04-09', '30/360')).toBe(0)
    expect(computeAccrued(null, '2025-04-09', '30/360')).toBe(0)
  })

  it('asOfDate después de maturity → 0 (no hay next)', () => {
    expect(computeAccrued(sched, '2030-01-01', '30/360')).toBe(0)
  })

  it('sin prev en schedule, con issueDate explícito → usa issueDate', () => {
    // Schedule "futuro puro" (asOf antes del primer pago), debe usar issueDate.
    const a = computeAccrued(sched, '2024-10-09', '30/360', '2024-07-09')
    // Período: 2024-07-09 a 2025-01-09 = 6 meses (0.5 año)
    // Elapsed: 2024-07-09 a 2024-10-09 = 3 meses (0.25 año)
    // accrued = 2 × 0.25/0.5 = 1.0
    expect(a).toBeCloseTo(1.0, 2)
  })
})

// ─── cleanToDirty / dirtyToClean ─────────────────────────────────────────────

describe('cleanToDirty / dirtyToClean', () => {
  it('cleanToDirty suma accrued', () => {
    expect(cleanToDirty(71.5, 1.23)).toBeCloseTo(72.73, 4)
  })
  it('dirtyToClean resta accrued', () => {
    expect(dirtyToClean(72.73, 1.23)).toBeCloseTo(71.5, 4)
  })
  it('round-trip preserva el precio', () => {
    const clean = 88.75
    const accrued = 2.15
    expect(dirtyToClean(cleanToDirty(clean, accrued), accrued)).toBeCloseTo(clean, 6)
  })
  it('accrued null o undefined → returns clean', () => {
    expect(cleanToDirty(100, null)).toBe(100)
    expect(cleanToDirty(100, undefined)).toBe(100)
  })
  it('clean null → returns null', () => {
    expect(cleanToDirty(null, 1.23)).toBeNull()
  })
})

// ─── Conversiones de yield ───────────────────────────────────────────────────

describe('semiAnnualToEffectiveAnnual / inverse', () => {
  it('TIR semestral 2% → EAR 4.04%', () => {
    expect(semiAnnualToEffectiveAnnual(0.02)).toBeCloseTo(0.0404, 4)
  })
  it('TIR semestral 5% → EAR 10.25%', () => {
    expect(semiAnnualToEffectiveAnnual(0.05)).toBeCloseTo(0.1025, 4)
  })
  it('round-trip preserva el valor', () => {
    const sem = 0.0234
    expect(effectiveAnnualToSemiAnnual(semiAnnualToEffectiveAnnual(sem))).toBeCloseTo(sem, 8)
  })
  it('null in → null out', () => {
    expect(semiAnnualToEffectiveAnnual(null)).toBeNull()
    expect(effectiveAnnualToSemiAnnual(null)).toBeNull()
  })
})
