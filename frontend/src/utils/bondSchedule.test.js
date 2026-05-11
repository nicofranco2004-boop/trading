import { describe, it, expect } from 'vitest'
import {
  generateSchedule,
  getRemainingPayments,
  getNextPayment,
  totalRemainingPayout,
  estimateYield,
  nextPaymentForPosition,
  addMonths,
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

  it('el primer cupón se calcula sobre face=100', () => {
    // AL30 couponRate=0.75% anual → 0.375% semestral
    // Primer cupón: 0.375% × 100 = 0.375
    const first = sched[0]
    expect(first.coupon).toBeCloseTo(0.375, 3)
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
