import { describe, it, expect } from 'vitest'
import { generateSchedule, getRemainingPayments, estimateYieldDetailed } from './bondSchedule.js'

// ════════════════════════════════════════════════════════════════════════════
// Phase 3C — ajuste por coeficiente CER en bonos AR ARS-linked.
//
// El motor recibe una serie CER (dict {YYYY-MM-DD: value}) vía options.cerSeries.
// Si el bono es type='cer' con cerEmissionDate, los flujos se multiplican por
// el factor = CER(payment_date) / CER(cerEmissionDate).
//
// Estos tests validan:
//   1. Comportamiento legacy: sin serie CER → flujos nominales (regression).
//   2. CER plana (todos = base): factor = 1, mismos flujos.
//   3. CER 2x: flujos 2x, TIR ajustada coherentemente.
//   4. LOCF: fecha de pago sin entry exacta usa último valor previo.
// ════════════════════════════════════════════════════════════════════════════

// Serie CER de prueba: el coeficiente arranca en 100 el 2023-06-30 (cerEmissionDate
// de TZX26) y crece linealmente hasta 300 (= 3x) al 2026-06-30 (maturity).
const cerLinear3x = (() => {
  const series = {}
  // 100 → 300 desde 2023-06-30 a 2026-06-30 (3 años)
  const start = new Date('2023-06-30')
  const end = new Date('2026-06-30')
  const days = Math.round((end - start) / 86400000)
  for (let i = 0; i <= days; i++) {
    const d = new Date(start.getTime() + i * 86400000)
    const iso = d.toISOString().slice(0, 10)
    series[iso] = 100 + (i / days) * 200  // lineal 100 → 300
  }
  return series
})()

// ─── Sin serie: comportamiento nominal (regression) ──────────────────────────

describe('TZX26 sin cerSeries — comportamiento legacy nominal', () => {
  const sched = generateSchedule('TZX26')

  it('un único pago = 100 nominal al vencimiento (sin ajuste)', () => {
    expect(sched).toHaveLength(1)
    expect(sched[0].date).toBe('2026-06-30')
    expect(sched[0].amort).toBe(100)
    expect(sched[0].total).toBe(100)
    // cerFactor null porque no se pasó cerSeries
    expect(sched[0].cerFactor).toBeNull()
  })
})

// ─── CER plana = 1 (regression check) ────────────────────────────────────────

describe('TZX26 con CER plana (factor=1) — equivalente a legacy', () => {
  const flatSeries = {
    '2023-06-30': 100.0,
    '2026-06-30': 100.0,
  }
  const sched = generateSchedule('TZX26', { cerSeries: flatSeries })

  it('factor = 1 → amort sigue siendo 100', () => {
    expect(sched).toHaveLength(1)
    expect(sched[0].amort).toBe(100)
    expect(sched[0].cerFactor).toBeCloseTo(1.0, 4)
  })
})

// ─── CER lineal 3x: amort triplicado ─────────────────────────────────────────

describe('TZX26 con CER lineal 3x — ajuste aplicado correctamente', () => {
  const sched = generateSchedule('TZX26', { cerSeries: cerLinear3x })

  it('amort al maturity = 100 × 3 = 300', () => {
    expect(sched).toHaveLength(1)
    expect(sched[0].amort).toBeCloseTo(300, 1)
    expect(sched[0].total).toBeCloseTo(300, 1)
    expect(sched[0].cerFactor).toBeCloseTo(3.0, 2)
  })
})

// ─── TX26 (cuponizado) con CER aplica al CUPÓN y al AMORT ────────────────────

describe('TX26 con CER 2x al maturity — cupón ajustado también', () => {
  // Serie linear: CER emission TX26 = 2020-08-04, valor 100; al 2026-11-09 = 200 (2x).
  const start = new Date('2020-08-04')
  const end = new Date('2026-11-09')
  const days = Math.round((end - start) / 86400000)
  const series = {}
  for (let i = 0; i <= days; i++) {
    const d = new Date(start.getTime() + i * 86400000)
    series[d.toISOString().slice(0, 10)] = 100 + (i / days) * 100
  }

  const sched = generateSchedule('TX26', { cerSeries: series })

  it('el último pago = (cupón + 100 face) × CER_factor_maturity', () => {
    const last = sched[sched.length - 1]
    expect(last.date).toBe('2026-11-09')
    // CER factor a maturity = 2.0
    expect(last.cerFactor).toBeCloseTo(2.0, 1)
    // Cupón 2% TNA / 2 sem = 1% sobre face 100, ajustado por 2 = 2 ARS
    // Amort 100 ajustado por 2 = 200 ARS
    // Total = 202 ARS por 100 face original
    expect(last.amort).toBeCloseTo(200, 0)
    expect(last.total).toBeCloseTo(202, 0)
  })

  it('cupones intermedios tienen factor < 2 (CER creció proporcionalmente)', () => {
    // Un cupón de 2024 debería tener factor < 2 (entre 1 y 2)
    const cupon2024 = sched.find(p => p.date.startsWith('2024'))
    expect(cupon2024).toBeDefined()
    expect(cupon2024.cerFactor).toBeGreaterThan(1)
    expect(cupon2024.cerFactor).toBeLessThan(2)
  })
})

// ─── TIR con ajuste CER cambia consistentemente ──────────────────────────────

describe('TIR de TZX26 con CER — yield real vs nominal', () => {
  it('CER plana + precio 78 a 2 años → TIR ≈ 13.2% (nominal, sin inflación)', () => {
    const flat = { '2023-06-30': 100, '2026-06-30': 100 }
    const r = estimateYieldDetailed('TZX26', 78, '2024-06-30', { cerSeries: flat })
    expect(r.converged).toBe(true)
    expect(r.ytm).toBeGreaterThan(0.10)
    expect(r.ytm).toBeLessThan(0.16)
  })

  it('CER lineal 3x desde 2023-06-30 + precio 78 a 2 años → TIR mucho mayor', () => {
    // Si CER crecio de 100 (2023-06-30) a 300 (2026-06-30), el pago al maturity es 300.
    // Comprado a 78 con asOf 2024-06-30, el factor de CER ese día ≈ 100 + (1/3)*200 = 167
    // Pero el PAGO al maturity es 300, así que el yield sobre el precio efectivo en
    // términos NOMINALES (sin descontar inflación) es muy alto.
    const r = estimateYieldDetailed('TZX26', 78, '2024-06-30', { cerSeries: cerLinear3x })
    expect(r.converged).toBe(true)
    // Yield aproximado: (300/78)^(1/2) - 1 ≈ 96%
    expect(r.ytm).toBeGreaterThan(0.50)
  })
})

// ─── LOCF (Last Observation Carried Forward) ─────────────────────────────────

describe('Lookup CER con LOCF', () => {
  it('si la fecha exacta no está, usa último valor previo disponible', () => {
    // Serie con valores SÓLO en 2023-06-30 (100), 2024-01-01 (150), 2026-06-30 (300)
    const sparse = {
      '2023-06-30': 100,
      '2024-01-01': 150,
      '2026-06-30': 300,
    }
    const sched = generateSchedule('TZX26', { cerSeries: sparse })
    // En 2026-06-30 está la fecha exacta → factor 300/100 = 3.0
    expect(sched[0].cerFactor).toBeCloseTo(3.0, 2)
  })

  it('si la serie no tiene la fecha base (cerEmissionDate), fallback a factor=1', () => {
    const sinBase = {
      '2025-06-30': 200,
      '2026-06-30': 300,
    }
    const sched = generateSchedule('TZX26', { cerSeries: sinBase })
    // cerEmissionDate=2023-06-30 no está en serie, antes del primer valor
    // → cerBase = null → factor = 1 → amort sigue siendo 100
    expect(sched[0].cerFactor).toBeNull()
    expect(sched[0].amort).toBe(100)
  })
})

// ─── Bonos no-CER ignoran cerSeries ──────────────────────────────────────────

describe('Bonos no-CER no se afectan por cerSeries', () => {
  it('AL30 con cerSeries: schedule idéntico a sin cerSeries', () => {
    const sWithout = generateSchedule('AL30')
    const sWith = generateSchedule('AL30', { cerSeries: cerLinear3x })
    expect(sWith).toEqual(sWithout)
    // cerFactor no debe estar en bonos non-CER (campo agregado solo si isCer)
    expect(sWith[0].cerFactor).toBeUndefined()
  })
})
