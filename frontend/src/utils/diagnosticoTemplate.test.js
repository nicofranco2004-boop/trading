// Tests del motor de la plantilla del Diagnóstico.
// Fijan: clasificación de arquetipo, supresión por falta de data, y
// re-priorización (veredicto arriba para conservador/cripto).
import { describe, it, expect } from 'vitest'
import { buildDiagnosticoLayout, classifyArchetype } from './diagnosticoTemplate'

const FULL = {
  nonCashPositions: 8, monthsTracked: 12, snapshotsCount: 30,
  cryptoSharePct: 20, rentaFijaSharePct: 10,
  hasMissingPrices: false, diagnosisCount: 12, hasFeatured: true,
  hasVerdicts: true, hasContributors: true, hasComposition: true,
  hasDrawdown: true, isFirstVisit: false,
}

describe('classifyArchetype', () => {
  it('empty sin posiciones', () => {
    expect(classifyArchetype({ nonCashPositions: 0, monthsTracked: 5 })).toBe('empty')
  })
  it('new con poca historia', () => {
    expect(classifyArchetype({ nonCashPositions: 3, monthsTracked: 1, snapshotsCount: 5 })).toBe('new')
    expect(classifyArchetype({ nonCashPositions: 3, monthsTracked: 5, snapshotsCount: 1 })).toBe('new')
  })
  it('crypto con ≥60% en exchange', () => {
    expect(classifyArchetype({ ...FULL, cryptoSharePct: 70 })).toBe('crypto')
  })
  it('conservador_ar con ≥60% renta fija', () => {
    expect(classifyArchetype({ ...FULL, cryptoSharePct: 5, rentaFijaSharePct: 65 })).toBe('conservador_ar')
  })
  it('completo por defecto', () => {
    expect(classifyArchetype(FULL)).toBe('completo')
  })
  it('prioridad: empty > new > crypto > conservador', () => {
    // sin historial pero cripto-pesado → new gana (no hay data para performance)
    expect(classifyArchetype({ nonCashPositions: 5, monthsTracked: 1, cryptoSharePct: 90 })).toBe('new')
  })
})

describe('buildDiagnosticoLayout — usuario completo', () => {
  const { archetype, slots } = buildDiagnosticoLayout(FULL)
  it('archetype completo, todos los slots relevantes', () => {
    expect(archetype).toBe('completo')
    expect(slots).toContain('ai_reading')
    expect(slots).toContain('benchmark')
    expect(slots).toContain('drawdown')
    expect(slots).not.toContain('checklist')       // no es nuevo
    expect(slots).not.toContain('data_integrity')  // sin missing prices
  })
  it('orden: delta antes que lectura antes que featured antes que kpi', () => {
    const i = (id) => slots.indexOf(id)
    expect(i('delta')).toBeLessThan(i('ai_reading'))
    expect(i('ai_reading')).toBeLessThan(i('featured'))
    expect(i('featured')).toBeLessThan(i('kpi'))
    expect(i('kpi')).toBeLessThan(i('verdict'))
  })
})

describe('buildDiagnosticoLayout — supresión por falta de data', () => {
  it('sin verdicts / sin historial → sin veredicto ni drawdown', () => {
    const { slots } = buildDiagnosticoLayout({
      ...FULL, monthsTracked: 1, snapshotsCount: 1, hasVerdicts: false, hasDrawdown: false,
    })
    // (queda como 'new')
    expect(slots).not.toContain('verdict')
    expect(slots).not.toContain('drawdown')
    expect(slots).toContain('checklist')  // sí, es nuevo
  })
  it('primera visita → sin delta', () => {
    const { slots } = buildDiagnosticoLayout({ ...FULL, isFirstVisit: true })
    expect(slots).not.toContain('delta')
  })
  it('missing prices → aparece data_integrity primero', () => {
    const { slots } = buildDiagnosticoLayout({ ...FULL, hasMissingPrices: true })
    expect(slots[0]).toBe('data_integrity')
  })
  it('empty → solo lo mínimo + checklist', () => {
    const { slots, isEmpty } = buildDiagnosticoLayout({ nonCashPositions: 0, monthsTracked: 0 })
    expect(isEmpty).toBe(true)
    expect(slots).toContain('ai_reading')
    expect(slots).toContain('checklist')
    expect(slots).not.toContain('kpi')       // no hay cartera
    expect(slots).not.toContain('benchmark')
  })
})

describe('buildDiagnosticoLayout — re-priorización por arquetipo', () => {
  it('conservador_ar: veredicto arriba de featured', () => {
    const { slots, archetype } = buildDiagnosticoLayout({ ...FULL, cryptoSharePct: 5, rentaFijaSharePct: 70 })
    expect(archetype).toBe('conservador_ar')
    expect(slots.indexOf('verdict')).toBeLessThan(slots.indexOf('featured'))
  })
  it('crypto: veredicto sube (arriba de kpi)', () => {
    const { slots, archetype } = buildDiagnosticoLayout({ ...FULL, cryptoSharePct: 75 })
    expect(archetype).toBe('crypto')
    expect(slots.indexOf('verdict')).toBeLessThan(slots.indexOf('kpi'))
  })
  it('completo: veredicto en su lugar (después de kpi)', () => {
    const { slots } = buildDiagnosticoLayout(FULL)
    expect(slots.indexOf('verdict')).toBeGreaterThan(slots.indexOf('kpi'))
  })
  it('determinístico: misma entrada → mismo orden', () => {
    const a = buildDiagnosticoLayout(FULL).slots
    const b = buildDiagnosticoLayout(FULL).slots
    expect(a).toEqual(b)
  })
})
