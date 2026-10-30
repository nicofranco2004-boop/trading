// Las copias que dejó la versión anterior a la regla de dueño, al abrir la app:
// las que dicen de quién son (iban a nombre del email) pasan a su dueño; las
// demás se borran; las que ya tienen dueño (y las del demo) quedan. Acá
// plantarlas a mano ES el caso: son las que dejó una versión vieja de la app.
import { describe, it, expect, beforeAll, afterEach } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'
import { ordenarCopiasSinDueno, esCopiaSinDueno } from './copiasSinDueno'

beforeAll(() => { instalarNavegadorMinimo() })
afterEach(() => { localStorage.clear(); sessionStorage.clear() })

const claves = (s) => Array.from({ length: s.length }, (_, i) => s.key(i)).sort()

describe('las copias sin dueño de la versión anterior', () => {
  it('«desde tu última visita» y las tarjetas descartadas pasan a la persona, en su cuenta propia (re-test 2)', () => {
    // Lo que guarda hoy producción: a nombre del email (el de la última visita,
    // tal cual vino; el de las tarjetas, en minúsculas).
    localStorage.setItem('rendi_lastvisit_diagnostico:Ana@Prueba.test', '{"valueUsd":41536.95,"findingIds":["a"]}')
    localStorage.setItem('rendi_diag_dismissed_diag:ana@prueba.test', '{"dismissed":["concentracion"],"slots":{}}')
    expect(ordenarCopiasSinDueno()).toEqual({ pasadas: 2, borradas: 0 })
    expect(claves(localStorage)).toEqual([
      'rendi_diag_dismissed_diag:ana@prueba.test|propia',
      'rendi_lastvisit_diagnostico:ana@prueba.test|propia',
    ])
    expect(JSON.parse(localStorage.getItem('rendi_lastvisit_diagnostico:ana@prueba.test|propia')).valueUsd).toBe(41536.95)
    expect(JSON.parse(localStorage.getItem('rendi_diag_dismissed_diag:ana@prueba.test|propia')).dismissed).toEqual(['concentracion'])
  })

  it('si ya hay una con dueño, gana la nueva y la vieja se va', () => {
    localStorage.setItem('rendi_lastvisit_diagnostico:ana@prueba.test', '{"valueUsd":1}')
    localStorage.setItem('rendi_lastvisit_diagnostico:ana@prueba.test|propia', '{"valueUsd":2}')
    ordenarCopiasSinDueno()
    expect(claves(localStorage)).toEqual(['rendi_lastvisit_diagnostico:ana@prueba.test|propia'])
    expect(JSON.parse(localStorage.getItem('rendi_lastvisit_diagnostico:ana@prueba.test|propia')).valueUsd).toBe(2)
  })

  it('las que no dicen de quién son se borran; las de una persona y una cuenta, y las del demo, quedan', () => {
    localStorage.setItem('rendi_snapshot_date', '2026-10-29')
    localStorage.setItem('rendi_lastvisit_diagnostico:anon', '{"valueUsd":1}')      // sin sesión: de nadie
    localStorage.setItem('rendi_dibujos:AAPL:usd', '{"pendiente":true,"dibujos":[]}')
    sessionStorage.setItem('rendi_tanda_ultima', '{"filas":[{"nombre":"Juan Pérez"}]}')
    sessionStorage.setItem('rendi_valor_visto:cliente-2:a', '{"valor":1}')
    sessionStorage.setItem('rendi_ultimo_total:propia:cartera', '{"total":1}')
    localStorage.setItem('rendi_snapshot_date:ana@prueba.test|propia', '2026-10-30')
    localStorage.setItem('rendi_lastvisit_diagnostico:ana@prueba.test|cliente-2', '{}')
    localStorage.setItem('rendi_dibujos:demo:AAPL:usd', '{}')
    localStorage.setItem('rendi_theme', 'dark')
    sessionStorage.setItem('rendi_tanda_ultima:ana@prueba.test|propia', '{}')

    expect(ordenarCopiasSinDueno()).toEqual({ pasadas: 0, borradas: 6 })
    expect(claves(localStorage)).toEqual([
      'rendi_dibujos:demo:AAPL:usd',
      'rendi_lastvisit_diagnostico:ana@prueba.test|cliente-2',
      'rendi_snapshot_date:ana@prueba.test|propia',
      'rendi_theme',
    ])
    expect(claves(sessionStorage)).toEqual(['rendi_tanda_ultima:ana@prueba.test|propia'])
    expect(ordenarCopiasSinDueno()).toEqual({ pasadas: 0, borradas: 0 })   // la segunda vez no hay nada
  })

  it('una clave de otra familia, aunque no tenga «|», no es suya', () => {
    expect(esCopiaSinDueno('rendi_user')).toBe(false)
    expect(esCopiaSinDueno('rendi_cuentas_separadas')).toBe(false)
    expect(esCopiaSinDueno('rendi_version_cartera:demo')).toBe(false)
    expect(esCopiaSinDueno('rendi_version_cartera:propia')).toBe(true)
  })
})
