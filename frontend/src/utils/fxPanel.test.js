import { describe, it, expect } from 'vitest'
import { filtrarFilas, deltaRendimiento, contarCaen, contarFrenadas } from './fxPanel'

// Números reales del dry-run del 2026-07-30 sobre 497 cuentas.
const sim = (antes, despues, ok = true) => ({
  ok, verificacion: { rendimiento_antes_pct: antes, rendimiento_despues_pct: despues },
})

const CUENTAS = [
  { user_id: 595, fx_version: 'v1' },   // +11,3 → −89,9  (cae 101 pts)
  { user_id: 814, fx_version: 'v1' },   // +39,7 → −92,3  (cae 132 pts)
  { user_id: 476, fx_version: 'v1' },   // +2,2 → +3,5    (no cambia nada)
  { user_id: 826, fx_version: 'v1' },   // frenada
  { user_id: 999, fx_version: 'v1' },   // sin simular
  { user_id: 111, fx_version: 'v1', bloqueada_por_escala: true },
]
const SIMS = {
  595: sim(11.3, -89.9),
  814: sim(39.7, -92.3),
  476: sim(2.2, 3.5),
  826: { ok: false, motivo: 'el aportado queda en US$ -1477983.75' },
}

describe('deltaRendimiento', () => {
  it('mide en puntos porcentuales', () => {
    expect(deltaRendimiento(SIMS[595])).toBeCloseTo(-101.2, 1)
  })
  it('devuelve null sin simulación o sin rendimiento', () => {
    expect(deltaRendimiento(undefined)).toBeNull()
    expect(deltaRendimiento({ ok: true, verificacion: {} })).toBeNull()
    // Una cuenta frenada no trae verificacion: no puede romper.
    expect(deltaRendimiento(SIMS[826])).toBeNull()
  })
})

describe('buscar', () => {
  it('encuentra por id exacto', () => {
    expect(filtrarFilas(CUENTAS, SIMS, { buscar: '595' }).map(c => c.user_id)).toEqual([595])
  })
  it('tolera el # que uno escribe sin pensar', () => {
    expect(filtrarFilas(CUENTAS, SIMS, { buscar: '#814' }).map(c => c.user_id)).toEqual([814])
  })
  it('busca por coincidencia parcial', () => {
    expect(filtrarFilas(CUENTAS, SIMS, { buscar: '11' }).map(c => c.user_id)).toEqual([111])
  })
  it('el string vacío no filtra', () => {
    expect(filtrarFilas(CUENTAS, SIMS, { buscar: '   ' })).toHaveLength(6)
  })
})

describe('filtro', () => {
  it('"caen" deja solo las que se mueven 50 puntos o más', () => {
    expect(filtrarFilas(CUENTAS, SIMS, { filtro: 'caen' }).map(c => c.user_id).sort())
      .toEqual([595, 814])
  })
  it('"caen" toma el valor absoluto: una SUBIDA grande también hay que mirarla', () => {
    const s = { 1: sim(-50, 120) }   // sube 170 puntos
    expect(filtrarFilas([{ user_id: 1 }], s, { filtro: 'caen' })).toHaveLength(1)
  })
  it('"frenadas" deja las que el gate paró', () => {
    expect(filtrarFilas(CUENTAS, SIMS, { filtro: 'frenadas' }).map(c => c.user_id)).toEqual([826])
  })
  it('"sinsim" excluye las bloqueadas por escala', () => {
    expect(filtrarFilas(CUENTAS, SIMS, { filtro: 'sinsim' }).map(c => c.user_id)).toEqual([999])
  })
})

describe('orden por caída', () => {
  it('la caída más fuerte va primero', () => {
    const r = filtrarFilas(CUENTAS, SIMS, { orden: 'caida' }).map(c => c.user_id)
    expect(r.slice(0, 3)).toEqual([814, 595, 476])
  })
  it('las que no tienen simulación quedan al final', () => {
    const r = filtrarFilas(CUENTAS, SIMS, { orden: 'caida' }).map(c => c.user_id)
    expect(r.slice(-3).sort()).toEqual([111, 826, 999])
  })
  it('no muta el array original', () => {
    const orig = [...CUENTAS]
    filtrarFilas(CUENTAS, SIMS, { orden: 'caida' })
    expect(CUENTAS).toEqual(orig)
  })
})

describe('combinaciones y bordes', () => {
  it('filtro + orden se aplican juntos', () => {
    expect(filtrarFilas(CUENTAS, SIMS, { filtro: 'caen', orden: 'caida' }).map(c => c.user_id))
      .toEqual([814, 595])
  })
  it('sin cuentas ni sims no explota', () => {
    expect(filtrarFilas(null, null, { filtro: 'caen', orden: 'caida', buscar: '5' })).toEqual([])
    expect(contarCaen(null, null)).toBe(0)
    expect(contarFrenadas(null, null)).toBe(0)
  })
  it('los contadores del encabezado', () => {
    expect(contarCaen(CUENTAS, SIMS)).toBe(2)
    expect(contarFrenadas(CUENTAS, SIMS)).toBe(1)
  })
})
