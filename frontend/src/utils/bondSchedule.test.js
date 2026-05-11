import { describe, it, expect } from 'vitest'
import {
  generateSchedule,
  getRemainingPayments,
  getNextPayment,
  totalRemainingPayout,
  estimateYield,
  estimateYieldDetailed,
  nextPaymentForPosition,
  addMonths,
  getAccruedInterest,
} from './bondSchedule.js'

// ─── addMonths (helper interno expuesto para test) ────────────────────────────

describe('addMonths', () => {
  it('suma meses preservando el día', () => {
    expect(addMonths('2024-01-15', 6)).toBe('2024-07-15')
    expect(addMonths('2024-07-15', 6)).toBe('2025-01-15')
  })
  it('resta meses con argumentos negativos', () => {
    expect(addMonths('2024-07-09', -6)).toBe('2024-01-09')
    expect(addMonths('2025-01-01', -1)).toBe('2024-12-01')
  })
  it('si el día no existe en el mes destino, cae al último día', () => {
    // 31 enero + 1 mes → febrero 28/29
    const r = addMonths('2025-01-31', 1)
    expect(r === '2025-02-28' || r === '2025-02-29').toBe(true)
  })
  it('devuelve null para inputs malformados', () => {
    expect(addMonths('not-a-date', 1)).toBeNull()
    expect(addMonths('', 1)).toBeNull()
  })
})

// ─── generateSchedule ─────────────────────────────────────────────────────────

describe('generateSchedule — amortizing sovereign (AL30)', () => {
  const sched = generateSchedule('AL30')

  it('genera un schedule no vacío', () => {
    expect(sched).not.toBeNull()
    expect(sched.length).toBeGreaterThan(0)
  })

  it('la última fecha es la maturity', () => {
    expect(sched[sched.length - 1].date).toBe('2030-07-09')
  })

  it('incluye la fecha de amortStart', () => {
    const found = sched.find(p => p.date === '2024-07-09')
    expect(found).toBeDefined()
    expect(found.amort).toBeGreaterThan(0)
  })

  it('amort total = ~100 (toda la face se devuelve)', () => {
    const totalAmort = sched.reduce((s, p) => s + p.amort, 0)
    expect(totalAmort).toBeCloseTo(100, 1)
  })

  it('el primer cupón se calcula sobre face=100 al step-up rate inicial', () => {
    // Phase 3B: AL30 step-up real = 0.125% TNA en período 2020-2021.
    // Primer cupón = 0.125%/2 × 100 = 0.0625 (no 0.375 del proxy 0.75%).
    // Esto corrige hallazgo C2 del audit (step-up promedio mata la TIR real).
    const first = sched[0]
    expect(first.coupon).toBeCloseTo(0.0625, 4)
  })

  it('cupones decrecen después de cada amortización', () => {
    // Localizo la primera amortización en el schedule
    const amortIdx = sched.findIndex(p => p.amort > 0)
    expect(amortIdx).toBeGreaterThanOrEqual(0)
    // Cupón antes y después de la amort
    if (amortIdx + 1 < sched.length) {
      const before = sched[amortIdx].coupon
      const after = sched[amortIdx + 1].coupon
      // El cupón inmediatamente después es sobre face MENOR
      expect(after).toBeLessThan(before)
    }
  })

  it('el último pago lleva face a 0 (suma todo lo que falte)', () => {
    // Después de aplicar todos los amorts, no debe sobrar face.
    let face = 100
    for (const p of sched) face -= p.amort
    expect(Math.abs(face)).toBeLessThan(0.01)
  })
})

describe('generateSchedule — bullet ON corporativa (YCA0O — YPF 2026)', () => {
  const sched = generateSchedule('YCA0O')

  it('genera schedule', () => {
    expect(sched).not.toBeNull()
    expect(sched.length).toBeGreaterThan(0)
  })

  it('la última fecha incluye face=100 + cupón final', () => {
    const last = sched[sched.length - 1]
    expect(last.date).toBe('2026-02-12')
    // YPF YCA0O cupón 8.5% anual → 4.25% semestral → 4.25 por 100
    expect(last.amort).toBeCloseTo(100, 1)
    expect(last.coupon).toBeCloseTo(4.25, 1)
  })

  it('todos los pagos intermedios son sólo cupón (sin amort)', () => {
    for (let i = 0; i < sched.length - 1; i++) {
      expect(sched[i].amort).toBe(0)
      expect(sched[i].coupon).toBeGreaterThan(0)
    }
  })

  it('cupón constante en todos los pagos (face no cambia hasta maturity)', () => {
    const couponAmounts = sched.map(p => p.coupon)
    const uniques = [...new Set(couponAmounts.map(x => x.toFixed(4)))]
    expect(uniques.length).toBe(1)
  })
})

describe('generateSchedule — zero-cupón CER (TZX26)', () => {
  const sched = generateSchedule('TZX26')

  it('un único pago al vencimiento = 100', () => {
    expect(sched).toHaveLength(1)
    expect(sched[0].date).toBe('2026-06-30')
    expect(sched[0].coupon).toBe(0)
    expect(sched[0].amort).toBe(100)
    expect(sched[0].total).toBe(100)
  })
})

describe('generateSchedule — ETF sin maturity (TLT)', () => {
  it('devuelve null porque no aplica un schedule discreto', () => {
    expect(generateSchedule('TLT')).toBeNull()
  })
})

describe('generateSchedule — ticker desconocido', () => {
  it('devuelve null', () => {
    expect(generateSchedule('NOEXISTE')).toBeNull()
    expect(generateSchedule('')).toBeNull()
  })
})

// ─── Filtros con fecha base ──────────────────────────────────────────────────

describe('getRemainingPayments', () => {
  it('filtra los pagos pasados con la fecha dada', () => {
    const future = getRemainingPayments('AL30', '2026-05-11')
    expect(future).not.toBeNull()
    // Todos los pagos están a partir de 2026-07-09 (el siguiente semestre)
    for (const p of future) {
      expect(p.date > '2026-05-11').toBe(true)
    }
  })

  it('devuelve array vacío si el bono ya venció', () => {
    const past = getRemainingPayments('AL30', '2099-01-01')
    expect(past).toEqual([])
  })

  it('devuelve null para tickers sin schedule', () => {
    expect(getRemainingPayments('NOEXISTE', '2026-01-01')).toBeNull()
  })
})

describe('getNextPayment', () => {
  it('devuelve el primer pago futuro', () => {
    const next = getNextPayment('AL30', '2026-05-11')
    expect(next).not.toBeNull()
    expect(next.date).toBe('2026-07-09')
  })

  it('null si no quedan pagos', () => {
    expect(getNextPayment('AL30', '2099-01-01')).toBeNull()
  })
})

describe('totalRemainingPayout', () => {
  it('suma todos los flujos futuros', () => {
    const t = totalRemainingPayout('AL30', '2024-01-01')  // antes de cualquier amort
    // Total esperado: ~100 face + algún cupón remanente. Cupón total
    // acumulado de AL30 ≈ pocos USD por 100 face dado el rate bajo.
    expect(t).toBeGreaterThan(100)
    expect(t).toBeLessThan(115)
  })
})

// ─── estimateYield (TIR Newton-Raphson) ──────────────────────────────────────

describe('estimateYield', () => {
  it('bullet a la par → TIR ≈ couponRate', () => {
    // YCA0O 8.5% anual semestral. Para test usamos una fecha varios cupones
    // antes de maturity. Precio = 100 (par) → TIR debería ser ≈ 8.5% anual.
    const r = estimateYield('YCA0O', 100, '2025-02-12')
    expect(r).not.toBeNull()
    // Tolerancia 50bp por la convención simple (semestral compounding ≠ anual)
    expect(r).toBeGreaterThan(0.075)
    expect(r).toBeLessThan(0.095)
  })

  it('zero-cupón con descuento → TIR > 0', () => {
    // TZX26 vence 2026-06-30. Si compramos a 78 el 2024-06-30 (2 años antes,
    // precio 78), TIR ≈ (100/78)^(1/2) - 1 ≈ 13.2%
    const r = estimateYield('TZX26', 78, '2024-06-30')
    expect(r).not.toBeNull()
    expect(r).toBeGreaterThan(0.10)
    expect(r).toBeLessThan(0.16)
  })

  it('precio = total flujos (precio efectivo) → TIR ≈ 0', () => {
    // Bono pagando flujos por valor total ~108 (100 face + cupones). Si compro
    // a ese mismo valor, el yield es ~0%.
    const flujos = totalRemainingPayout('YCA0O', '2025-02-12')
    expect(flujos).toBeGreaterThan(100)
    const r = estimateYield('YCA0O', flujos, '2025-02-12')
    expect(r).not.toBeNull()
    expect(Math.abs(r)).toBeLessThan(0.02)  // < 2% absoluto
  })

  it('precio = 0 o negativo → null', () => {
    expect(estimateYield('AL30', 0, '2026-05-11')).toBeNull()
    expect(estimateYield('AL30', -10, '2026-05-11')).toBeNull()
  })

  it('bono ya vencido → null (no quedan flujos)', () => {
    expect(estimateYield('AL30', 90, '2099-01-01')).toBeNull()
  })

  it('ticker desconocido → null', () => {
    expect(estimateYield('NOEXISTE', 100, '2026-01-01')).toBeNull()
  })
})

// ─── nextPaymentForPosition ──────────────────────────────────────────────────

describe('nextPaymentForPosition', () => {
  it('escala el próximo pago por la quantity del user', () => {
    const r = nextPaymentForPosition('AL30', 1000, '2026-05-11')
    expect(r).not.toBeNull()
    expect(r.date).toBe('2026-07-09')
    // AL30 amort 7.69 por 100 face, cupón ~0.346 por 100 (face decreciente)
    // qty=1000 nominales → recibe (cupón + amort) × 1000 / 100
    expect(r.amort).toBeGreaterThan(70)  // ~76.92 (1000 × 7.692/100)
    expect(r.amort).toBeLessThan(80)
    expect(r.total).toBeGreaterThan(r.amort)  // cupón > 0
  })

  it('null si quantity = 0 o no hay próximo pago', () => {
    expect(nextPaymentForPosition('AL30', 0, '2026-05-11')).toBeNull()
    expect(nextPaymentForPosition('AL30', 1000, '2099-01-01')).toBeNull()
  })
})

// ════════════════════════════════════════════════════════════════════════════
// PR #8 / Fase 3A — tests de la API rica (estimateYieldDetailed + accrued)
// ════════════════════════════════════════════════════════════════════════════

describe('estimateYieldDetailed — API rica con metadata', () => {
  it('devuelve estructura con ytm, converged, method, accrued, dirty, clean, dayCount', () => {
    const r = estimateYieldDetailed('YCA0O', 100, '2025-02-12')
    expect(r).toHaveProperty('ytm')
    expect(r).toHaveProperty('converged')
    expect(r).toHaveProperty('method')
    expect(r).toHaveProperty('accrued')
    expect(r).toHaveProperty('dirty')
    expect(r).toHaveProperty('clean')
    expect(r).toHaveProperty('dayCount')
    expect(r.converged).toBe(true)
    expect(r.ytm).toBeCloseTo(0.085, 2)  // bullet par → TIR ≈ coupón anual
  })

  it('expone el accrued cuando el asOfDate está mid-period', () => {
    // YCA0O cupones cada 6 meses. 2025-02-12 = fecha de pago (accrued = 0)
    // 2025-05-12 = ~3 meses después = ~50% del semestre → accrued ≈ cupón/2 = 2.13
    const r = estimateYieldDetailed('YCA0O', 100, '2025-05-12')
    expect(r.accrued).toBeGreaterThan(1.5)
    expect(r.accrued).toBeLessThan(2.5)
    // Con accrued positivo, dirty > clean
    expect(r.dirty).toBeGreaterThan(r.clean)
    expect(r.dirty - r.clean).toBeCloseTo(r.accrued, 4)
  })

  it('priceIsDirty=true: no agrega accrued', () => {
    // Si el caller dice "ya te paso dirty", el sistema no debería sumar accrued.
    const r = estimateYieldDetailed('YCA0O', 102.13, '2025-05-12', { priceIsDirty: true })
    expect(r.dirty).toBeCloseTo(102.13, 4)
    expect(r.clean).toBeCloseTo(102.13 - r.accrued, 4)
  })

  it('ticker desconocido → method=no_meta', () => {
    const r = estimateYieldDetailed('NOEXISTE', 100, '2026-01-01')
    expect(r.ytm).toBeNull()
    expect(r.method).toBe('no_meta')
  })

  it('bono vencido → method=matured', () => {
    const r = estimateYieldDetailed('AL30', 90, '2099-01-01')
    expect(r.ytm).toBeNull()
    expect(r.method).toBe('matured')
  })
})

describe('getAccruedInterest', () => {
  it('día de pago exacto → accrued ≈ 0', () => {
    // YCA0O paga 2025-02-12 (es fecha de cupón) → accrued = 0 después del pago
    expect(getAccruedInterest('YCA0O', '2025-02-12')).toBeLessThan(0.05)
  })

  it('mid-period → accrued positivo proporcional', () => {
    // 2025-05-12 está ~3 meses del último cupón en YCA0O semestral
    const a = getAccruedInterest('YCA0O', '2025-05-12')
    expect(a).toBeGreaterThan(1.5)
    expect(a).toBeLessThan(2.5)
  })

  it('ticker desconocido → 0', () => {
    expect(getAccruedInterest('NOEXISTE', '2026-01-01')).toBe(0)
  })

  it('bono vencido → 0', () => {
    expect(getAccruedInterest('AL30', '2099-01-01')).toBe(0)
  })
})

// ════════════════════════════════════════════════════════════════════════════
// PR #8 — Forma rica: bondMeta con couponSchedule (step-up) + amortSchedule
// ════════════════════════════════════════════════════════════════════════════
// Estos tests usan un bono ficticio "para test" — los bonos reales con
// couponSchedule llegan en Phase 3B. Acá validamos que el motor soporta
// ambas formas.

describe('generateSchedule — forma rica (couponSchedule step-up)', () => {
  // Mock simple: simulamos un step-up similar a AL30 inyectando el meta
  // directamente vía un re-export. Como no tenemos un bono real con
  // couponSchedule en bondMeta todavía, validamos que el código respeta el
  // shape si llega — usando mock.
  // (Fase 3B reemplazará los soberanos con couponSchedule real.)
  it.todo('AL30 con couponSchedule step-up real produce cupones decrecientes en último período')
  it.todo('amortSchedule explícito con fechas no-regulares (modified following)')
})

// ════════════════════════════════════════════════════════════════════════════
// PR #8 — Regression: la TIR vieja "clean=dirty" subestimaba mid-period
// ════════════════════════════════════════════════════════════════════════════

describe('estimateYield (legacy API) — comportamiento de fecha de pago vs mid-period', () => {
  it('día de pago → TIR no cambia vs implementación previa (preserva tests)', () => {
    // YCA0O bullet 8.5% a la par el 2025-02-12 (fecha de pago) → TIR ≈ 8.5%
    const r = estimateYield('YCA0O', 100, '2025-02-12')
    expect(r).toBeGreaterThan(0.075)
    expect(r).toBeLessThan(0.095)
  })

  it('mid-period: TIR del corregido < TIR del legacy buggy', () => {
    // Con la corrección C4, mid-period la TIR baja porque dirty > clean →
    // mayor "pago" → yield menor. Verificamos que el cambio se manifiesta.
    const ytmAtPaymentDate = estimateYield('YCA0O', 100, '2025-02-12')  // accrued ≈ 0
    const ytmMidPeriod = estimateYield('YCA0O', 100, '2025-05-12')      // accrued ≈ 2
    // Comprar a 100 mid-period es comprar a 100 clean = ~102 dirty → yield menor
    expect(ytmMidPeriod).toBeLessThan(ytmAtPaymentDate)
  })
})
