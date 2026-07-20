import { describe, it, expect } from 'vitest'
import { resolveTierShown, computeDismiss } from './diagnosticsRotation'

// Helpers
const mk = (...ids) => ids.map(id => ({ id }))       // pool de {id}
const ids = pool => pool.map(d => d.id)
const S = (...xs) => new Set(xs)

describe('resolveTierShown', () => {
  it('sin slots guardados → primeros min(3,N) del pool en orden', () => {
    const pool = mk('a', 'b', 'c', 'd', 'e')
    expect(resolveTierShown(pool, ids(pool), undefined, S())).toEqual(['a', 'b', 'c'])
  })

  it('pool ≤3 → muestra todos (identidad exacta)', () => {
    const pool = mk('a', 'b')
    expect(resolveTierShown(pool, ids(pool), undefined, S())).toEqual(['a', 'b'])
  })

  it('respeta las slots guardadas (identidad estable, no re-ordena)', () => {
    const pool = mk('a', 'b', 'c', 'd', 'e')
    // guardadas fuera del orden natural
    expect(resolveTierShown(pool, ids(pool), ['d', 'b', 'e'], S())).toEqual(['d', 'b', 'e'])
  })

  it('completa slots faltantes con candidatos NO descartados', () => {
    const pool = mk('a', 'b', 'c', 'd')
    // sólo 1 guardada válida → completa con a, b (saltea la guardada 'c')
    expect(resolveTierShown(pool, ids(pool), ['c'], S())).toEqual(['c', 'a', 'b'])
  })

  it('descarta ids guardadas que ya no están en el pool (self-heal)', () => {
    const pool = mk('a', 'b', 'c', 'd')
    expect(resolveTierShown(pool, ids(pool), ['zzz', 'b'], S())).toEqual(['b', 'a', 'c'])
  })

  it('cicla: si todo el resto está descartado, rellena igual hasta min(3,N)', () => {
    const pool = mk('a', 'b', 'c', 'd')
    // dismissed a,b,c,d → no quedan no-descartados, pero la fila igual muestra 3
    const out = resolveTierShown(pool, ids(pool), undefined, S('a', 'b', 'c', 'd'))
    expect(out).toHaveLength(3)
    expect(new Set(out).size).toBe(3)  // sin duplicados
  })

  it('tolera savedIds NO-array (storage corrupto/manual) sin crashear → default', () => {
    const pool = mk('a', 'b', 'c', 'd')
    expect(() => resolveTierShown(pool, ids(pool), 'C1', S())).not.toThrow()
    expect(resolveTierShown(pool, ids(pool), 'C1', S())).toEqual(['a', 'b', 'c'])
    expect(resolveTierShown(pool, ids(pool), { 0: 'a' }, S())).toEqual(['a', 'b', 'c'])
  })
})

describe('computeDismiss — reemplazo por-slot estable', () => {
  const pool = mk('a', 'b', 'c', 'd', 'e')
  const poolIds = ids(pool)

  it('descartar el slot 0 SOLO cambia el slot 0 (el bug reportado)', () => {
    const current = ['a', 'b', 'c']
    const { nextShown } = computeDismiss(pool, poolIds, current, 'a', S())
    expect(nextShown).toEqual(['d', 'b', 'c'])   // a→d, b y c intactos
  })

  it('descartar el slot del medio SOLO cambia ese slot', () => {
    const current = ['a', 'b', 'c']
    const { nextShown } = computeDismiss(pool, poolIds, current, 'b', S())
    expect(nextShown).toEqual(['a', 'd', 'c'])
  })

  it('descartar el último slot SOLO cambia ese slot', () => {
    const current = ['a', 'b', 'c']
    const { nextShown } = computeDismiss(pool, poolIds, current, 'c', S())
    expect(nextShown).toEqual(['a', 'b', 'd'])
  })

  it('agrega la id descartada al skip-list', () => {
    const { nextDismissed } = computeDismiss(pool, poolIds, ['a', 'b', 'c'], 'a', S())
    expect(nextDismissed.has('a')).toBe(true)
  })

  it('no-op si la id ya no está visible (mismas referencias)', () => {
    const current = ['a', 'b', 'c']
    const dismissed = S('x')
    const res = computeDismiss(pool, poolIds, current, 'e', dismissed)
    expect(res.nextShown).toBe(current)
    expect(res.nextDismissed).toBe(dismissed)
  })

  it('dismisses sucesivos del MISMO slot no tocan los otros dos', () => {
    let current = ['a', 'b', 'c']
    let dismissed = S()
    const fixed0 = current[0], fixed2 = current[2]
    for (let k = 0; k < 5; k++) {
      const r = computeDismiss(pool, poolIds, current, current[1], dismissed)
      current = r.nextShown; dismissed = r.nextDismissed
      expect(current[0]).toBe(fixed0)   // slot 0 nunca se mueve
      expect(current[2]).toBe(fixed2)   // slot 2 nunca se mueve
    }
  })

  it('cicla al agotar el tier: vuelve a un candidato previo sin tocar los otros slots', () => {
    // pool de 4 → slot 1 puede rotar entre b(inicial), d, ... y luego ciclar
    const p4 = mk('a', 'b', 'c', 'd')
    const p4ids = ids(p4)
    let current = ['a', 'b', 'c']
    let dismissed = S()
    const seen = new Set([current[1]])
    // Descarto slot 1 hasta forzar el ciclo (b→d→ciclo→b)
    let cycled = false
    for (let k = 0; k < 4; k++) {
      const r = computeDismiss(p4, p4ids, current, current[1], dismissed)
      current = r.nextShown; dismissed = r.nextDismissed
      expect(current[0]).toBe('a')       // otros slots intactos durante el ciclo
      expect(current[2]).toBe('c')
      if (seen.has(current[1])) cycled = true
      seen.add(current[1])
    }
    expect(cycled).toBe(true)             // en algún momento repitió → cicló
    // Tras ciclar, el skip-list del tier se limpió (no quedó todo descartado)
    expect([...dismissed].filter(id => p4ids.includes(id)).length).toBeLessThan(p4ids.length)
  })
})
