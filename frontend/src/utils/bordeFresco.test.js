/**
 * "Este mes" tiene que significar este mes.
 *
 * EL BUG (auditoría 1B, H-3). `computeReturnDelta` tomaba como base el cierre más
 * reciente anterior al mes, POR VIEJO QUE FUERA. Medido sobre un usuario cuyo
 * cron se cortó el 20 de junio y que volvió a abrir la app el 10 de septiembre:
 *
 *     Dashboard / home mobile   →  +35,24 %  ·  US$ 3.700  ·  midiendo 79 días
 *     /mensual y /reportes      →  sin base para medir
 *     el mes real               →  +2,90 %   ·  US$ 400
 *
 * El propio helper devolvía `dayDiff: 79`. El dato para no publicarlo estaba
 * calculado y nadie lo miraba.
 *
 * POR QUÉ ERA UN BUG DE PROPAGACIÓN Y NO DE ARITMÉTICA. El piso de antigüedad ya
 * existía en el repo, escrito tres veces: `_border_is_fresh` en el backend y a
 * mano en una de las dos ramas de `useMonthlyData`. Faltaba justo en el motor que
 * alimenta el número titular del Dashboard. Y el comentario que acompañaba a la
 * copia del frontend decía, textual, "mismo número a propósito: si se separan,
 * uno de los dos está mal". Se habían separado, y nada lo verificaba.
 *
 * Por eso el último test de este archivo LEE el archivo de Python: la única forma
 * de que "mismo número a propósito" sea una afirmación y no un deseo.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { BORDE_MAX_LAG_DIAS, computeReturnDelta, esBordeFresco } from './evolution.js'

const AQUI = dirname(fileURLToPath(import.meta.url))
const MES = '2026-09-01'

const snap = (date, total_value, net_deposited = 0) => ({
  date, total_value, total_invested: total_value, net_deposited, apto: 1,
})

describe('esBordeFresco — el espejo del guard del backend', () => {
  it('el cierre del último día del mes anterior abre el mes', () => {
    expect(esBordeFresco('2026-08-31', MES)).toBe(true)
  })

  it('un finde largo entra: hasta 5 días de atraso', () => {
    expect(esBordeFresco('2026-08-27', MES)).toBe(true)   // lag = 5
    expect(esBordeFresco('2026-08-26', MES)).toBe(false)  // lag = 6
  })

  it('un cierre DENTRO del período no abre nada: lo parte', () => {
    expect(esBordeFresco('2026-09-10', MES)).toBe(false)
  })

  it('una fecha ausente o ilegible no es un borde', () => {
    expect(esBordeFresco(null, MES)).toBe(false)
    expect(esBordeFresco('ayer', MES)).toBe(false)
    expect(esBordeFresco('2026-08-31', null)).toBe(false)
  })
})

describe('computeReturnDelta — el KPI "Este mes" del Dashboard', () => {
  it('EL CASO MEDIDO: se ausentó en junio, volvió en septiembre → no hay número', () => {
    // Serie del cron hasta el 20 de junio; el usuario vuelve el 10 de septiembre.
    const snaps = [snap('2026-06-20', 10500, 10000)]
    const r = computeReturnDelta(snaps, {
      liveValue: 14200, liveNetDeposited: 10000, sinceDate: MES,
    })
    // Antes: { usd: 3700, pct: 0.3523…, prevDate: '2026-06-20', dayDiff: 79 }
    expect(r).toBeNull()
  })

  it('con el cierre del 31 de agosto sí mide, y mide el mes', () => {
    const snaps = [
      snap('2026-06-20', 10500, 10000),
      snap('2026-08-31', 13800, 10000),
    ]
    const r = computeReturnDelta(snaps, {
      liveValue: 14200, liveNetDeposited: 10000, sinceDate: MES,
    })
    expect(r.prevDate).toBe('2026-08-31')
    expect(r.usd).toBeCloseTo(400, 6)
  })

  it('un cierre viejo NO se degrada al más antiguo, que sería todavía peor', () => {
    // La trampa del fix: rechazar el borde viejo y caer al fallback publica una
    // ventana aún más larga. El guard tiene que cortar, no reintentar.
    const snaps = [
      snap('2026-01-15', 8000, 10000),
      snap('2026-06-20', 10500, 10000),
    ]
    const r = computeReturnDelta(snaps, {
      liveValue: 14200, liveNetDeposited: 10000, sinceDate: MES,
    })
    expect(r).toBeNull()
  })

  it('ASIMETRÍA DELIBERADA: el que empezó este mes sí ve su número', () => {
    // Toda la serie cae dentro del período → esta persona empezó en septiembre.
    // El backend rechazaría este borde (lag < 0) porque le queda la cadena
    // contable; acá no hay segunda vía y rechazarlo apagaría el KPI a todo
    // usuario nuevo durante su primer mes.
    //
    // Si algún día se decide unificarlo con el backend, este test tiene que
    // fallar primero: es una decisión de producto, no un descuido.
    const snaps = [snap('2026-09-03', 5000, 5000)]
    const r = computeReturnDelta(snaps, {
      liveValue: 5100, liveNetDeposited: 5000, sinceDate: MES,
    })
    expect(r.usd).toBeCloseTo(100, 6)
    expect(r.prevDate).toBe('2026-09-03')
  })

  it('el modo diario (sin sinceDate) no se toca', () => {
    const snaps = [snap('2026-06-19', 10000, 10000), snap('2026-06-20', 10500, 10000)]
    const r = computeReturnDelta(snaps, { liveValue: 10600, liveNetDeposited: 10000 })
    expect(r).not.toBeNull()
  })
})

describe('el número es UNO SOLO en los dos lados de la app', () => {
  it('BORDE_MAX_LAG_DIAS coincide con _BORDER_MAX_LAG_DAYS del backend', () => {
    const py = readFileSync(
      resolve(AQUI, '../../../backend/reporting/builder.py'), 'utf-8')
    const m = py.match(/^_BORDER_MAX_LAG_DAYS\s*=\s*(\d+)/m)
    expect(m, 'no encontré _BORDER_MAX_LAG_DAYS en reporting/builder.py').not.toBeNull()
    expect(BORDE_MAX_LAG_DIAS).toBe(Number(m[1]))
  })

  it('el frontend no vuelve a escribir el número a mano', () => {
    // El bug era una copia. Este guard lee CÓDIGO: si alguien reintroduce el
    // `- 5 * 86400000` que había en useMonthlyData, se pone en rojo.
    const hook = readFileSync(resolve(AQUI, '../hooks/useMonthlyData.js'), 'utf-8')
    expect(hook).not.toMatch(/5\s*\*\s*86400000/)
    expect(hook).toContain('esBordeFresco')
  })
})
