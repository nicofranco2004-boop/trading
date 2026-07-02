import { describe, it, expect } from 'vitest'
import { positionPct, checkPositionRow, auditPositions } from './valuationGuards.js'

describe('positionPct — % siempre derivado de valor y P&L', () => {
  it('deriva el % agregado (caso GOOGL: valor 2117.89, P&L 466.81 → ~28%)', () => {
    const pct = positionPct(2117.89, 466.81)
    expect(pct).toBeCloseTo(0.2827, 3)   // NO 1.573 (el % del primer lote)
  })
  it('posición sin ganancia → 0%', () => {
    expect(positionPct(1000, 0)).toBe(0)
  })
  it('costo cero o negativo (value ≤ pnl) → null (no se puede dividir)', () => {
    expect(positionPct(500, 500)).toBeNull()
    expect(positionPct(500, 600)).toBeNull()
  })
  it('valores no finitos → null', () => {
    expect(positionPct(null, 10)).toBeNull()
    expect(positionPct(100, undefined)).toBeNull()
  })
})

describe('checkPositionRow — detecta filas que no cierran', () => {
  it('fila consistente (value = invested + pnl, % derivado) → ok', () => {
    const r = checkPositionRow({ asset: 'MELI', value_usd: 1679.78, pnl_usd: 33.55, pnl_pct: positionPct(1679.78, 33.55) })
    expect(r.ok).toBe(true)
    expect(r.issues).toHaveLength(0)
  })
  it('bug GOOGL: % del primer lote (1.573) NO cierra con value/pnl → falla', () => {
    const r = checkPositionRow({ asset: 'GOOGL', value_usd: 2117.89, pnl_usd: 466.81, pnl_pct: 1.573 })
    expect(r.ok).toBe(false)
    expect(r.issues.join(' ')).toMatch(/no cierra/)
  })
  it('bono ×100: valor ~100× el costo → olor a inflado', () => {
    // value 173168.86, cost 1737.58 → pnl 171431.28; el % SÍ cierra (98.7×) pero
    // la magnitud dispara la alarma de inflado.
    const r = checkPositionRow({ asset: 'TXMJ0', value_usd: 173168.86, pnl_usd: 171431.28, pnl_pct: 98.66 })
    expect(r.ok).toBe(false)
    expect(r.issues.join(' ')).toMatch(/inflado/)
  })
  it('sin pnl_pct reportado → no inventa falla (solo chequea lo que hay)', () => {
    const r = checkPositionRow({ asset: 'AAPL', value_usd: 100, pnl_usd: 10, pnl_pct: null })
    expect(r.ok).toBe(true)
  })
  it('drift chico por redondeo (2 decimales) → tolerado, no falla', () => {
    // % reportado con leve diferencia de redondeo respecto al derivado exacto
    const r = checkPositionRow({ asset: 'KO', value_usd: 1000, pnl_usd: 200, pnl_pct: 0.2503 })
    expect(r.ok).toBe(true)
  })
})

describe('auditPositions — corre sobre un array y devuelve las fallas', () => {
  it('devuelve solo las filas problemáticas', () => {
    const rows = [
      { asset: 'MELI', value_usd: 1679.78, pnl_usd: 33.55, pnl_pct: positionPct(1679.78, 33.55) },  // ok
      { asset: 'GOOGL', value_usd: 2117.89, pnl_usd: 466.81, pnl_pct: 1.573 },                       // bug %
      { asset: 'TXMJ0', value_usd: 173168.86, pnl_usd: 171431.28, pnl_pct: 98.66 },                  // inflado
    ]
    const problems = auditPositions(rows, 'test')
    expect(problems).toHaveLength(2)
    expect(problems.map((p) => p.asset).sort()).toEqual(['GOOGL', 'TXMJ0'])
  })
  it('array vacío o inválido → sin fallas, no rompe', () => {
    expect(auditPositions([], 'test')).toHaveLength(0)
    expect(auditPositions(null, 'test')).toHaveLength(0)
    expect(auditPositions(undefined)).toHaveLength(0)
  })
})
