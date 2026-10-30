// Las copias que dejó la versión anterior a la regla de dueño se borran al
// abrir la app; las que tienen dueño (y las del demo) quedan. Acá plantarlas a
// mano ES el caso: son las que dejó una versión vieja de la app.
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'
import { borrarCopiasSinDueno, esCopiaSinDueno } from './copiasSinDueno'

beforeAll(() => { instalarNavegadorMinimo() })
afterEach(() => { localStorage.clear(); sessionStorage.clear() })

const claves = (s) => Array.from({ length: s.length }, (_, i) => s.key(i)).sort()

describe('las copias sin dueño de la versión anterior', () => {
  it('se borran al abrir la app; las de una persona y una cuenta quedan', () => {
    // Lo que dejaba la versión publicada hasta el 30/10.
    localStorage.setItem('rendi_snapshot_date', '2026-10-29')
    localStorage.setItem('rendi_lastvisit_diagnostico:ana@prueba.test', '{"valueUsd":41536.95}')
    localStorage.setItem('rendi_diag_dismissed_diag:ana@prueba.test', '[]')
    localStorage.setItem('rendi_dibujos:AAPL:usd', '{"pendiente":true,"dibujos":[]}')
    sessionStorage.setItem('rendi_tanda_ultima', '{"filas":[{"nombre":"Juan Pérez"}]}')
    sessionStorage.setItem('rendi_valor_visto:cliente-2:a', '{"valor":1}')
    sessionStorage.setItem('rendi_ultimo_total:propia:cartera', '{"total":1}')
    // Las de ahora, con dueño, y las que no son de esta familia.
    localStorage.setItem('rendi_snapshot_date:ana@prueba.test|propia', '2026-10-30')
    localStorage.setItem('rendi_lastvisit_diagnostico:ana@prueba.test|cliente-2', '{}')
    localStorage.setItem('rendi_dibujos:demo:AAPL:usd', '{}')
    localStorage.setItem('rendi_theme', 'dark')
    sessionStorage.setItem('rendi_tanda_ultima:ana@prueba.test|propia', '{}')

    expect(borrarCopiasSinDueno()).toBe(7)
    expect(claves(localStorage)).toEqual([
      'rendi_dibujos:demo:AAPL:usd',
      'rendi_lastvisit_diagnostico:ana@prueba.test|cliente-2',
      'rendi_snapshot_date:ana@prueba.test|propia',
      'rendi_theme',
    ])
    expect(claves(sessionStorage)).toEqual(['rendi_tanda_ultima:ana@prueba.test|propia'])
    expect(borrarCopiasSinDueno()).toBe(0)       // la segunda vez no hay nada
  })

  it('una clave de otra familia, aunque no tenga «|», no es suya', () => {
    expect(esCopiaSinDueno('rendi_user')).toBe(false)
    expect(esCopiaSinDueno('rendi_cuentas_separadas')).toBe(false)
    expect(esCopiaSinDueno('rendi_version_cartera:demo')).toBe(false)
    expect(esCopiaSinDueno('rendi_version_cartera:propia')).toBe(true)
  })
})
