// La cadena mensual de Insights medía solo lo REALIZADO: el backend fuerza
// pnl_unrealized = 0 en los meses cerrados, así que (cf−ci−net) ≡ pnl_realized y
// el movimiento de mercado desaparecía. Comparado contra el S&P —que es 100%
// mark-to-market— la cartera quedaba sistemáticamente subestimada.
//
// Lo que estos tests fijan, además del reemplazo:
//   · un mes cerrado NUNCA queda con ci a costo y cf a mercado (eso fabrica el
//     "-64,9% fantasma", que es el bug que estamos evitando, no el que arreglamos)
//   · el mes EN CURSO sí se corrige con un solo snapshot, porque su cf ya es live
//   · sin snapshots no hay regresión: todo queda como está
import { describe, it, expect } from 'vitest'
import { applyMtmToMonthly, netCapitalContributed } from './insightsModel'

const HOY = new Date('2026-08-15T12:00:00Z')

// Mes cerrado típico: entró 1000, se realizaron 50, el backend cierra a 1050.
// El mercado en realidad lo dejó en 1200 — esos 150 no aparecían en ningún lado.
const mes = (year, month, over = {}) => ({
  year, month, broker: 'global',
  capital_inicio: 1000, capital_final: 1050,
  deposits: 0, withdrawals: 0, pnl_realized: 50, ...over,
})
const snap = (date, total_value) => ({ date, total_value, net_deposited: 0 })

const rDietz = (m) => {
  const net = (m.deposits || 0) - (m.withdrawals || 0)
  return (m.capital_final - m.capital_inicio - net) / (m.capital_inicio + 0.5 * net)
}

describe('applyMtmToMonthly — mes cerrado', () => {
  it('con los DOS snapshots reemplaza inicio y final', () => {
    const out = applyMtmToMonthly(
      [mes(2026, 5)],
      [snap('2026-04-30', 1000), snap('2026-05-31', 1200)],
      HOY)
    expect(out[0].capital_inicio).toBe(1000)
    expect(out[0].capital_final).toBe(1200)
    expect(out[0].mtm).toBe('ambos')
  })

  it('EL PUNTO: el retorno pasa de contar solo lo realizado a contar el mercado', () => {
    const antes = mes(2026, 5)
    const [despues] = applyMtmToMonthly(
      [antes], [snap('2026-04-30', 1000), snap('2026-05-31', 1200)], HOY)
    expect(rDietz(antes)).toBeCloseTo(0.05, 10)      // 50/1000 = solo lo realizado
    expect(rDietz(despues)).toBeCloseTo(0.20, 10)    // 200/1000 = lo que hizo el mercado
  })

  it('con UN solo snapshot NO toca nada (ci a costo + cf a mercado = el fantasma)', () => {
    // Este es el guard que importa. Reemplazar solo el inicio dejaría el mes con
    // arranque a mercado y cierre a costo → una pérdida inventada del tamaño de
    // todo el no realizado acumulado.
    const soloPrev = applyMtmToMonthly([mes(2026, 5)], [snap('2026-04-30', 1000)], HOY)
    expect(soloPrev[0].mtm).toBeUndefined()
    expect(soloPrev[0].capital_final).toBe(1050)

    const soloCur = applyMtmToMonthly([mes(2026, 5)], [snap('2026-05-31', 1200)], HOY)
    expect(soloCur[0].mtm).toBeUndefined()
    expect(soloCur[0].capital_inicio).toBe(1000)
  })

  it('un hueco de snapshots deja ESE mes a costo sin contaminar a los vecinos', () => {
    const out = applyMtmToMonthly(
      [mes(2026, 4), mes(2026, 5), mes(2026, 6)],
      // falta todo mayo → mayo y junio se quedan a costo, abril se convierte
      [snap('2026-03-31', 900), snap('2026-04-30', 1100), snap('2026-06-30', 1400)],
      HOY)
    expect(out[0].mtm).toBe('ambos')      // abril: tiene marzo y abril
    expect(out[1].mtm).toBeUndefined()    // mayo: no tiene snapshot propio
    expect(out[2].mtm).toBeUndefined()    // junio: le falta el de mayo
  })

  it('toma el ÚLTIMO snapshot de cada mes, no el primero', () => {
    const out = applyMtmToMonthly(
      [mes(2026, 5)],
      [snap('2026-04-01', 500), snap('2026-04-30', 1000),
       snap('2026-05-02', 1111), snap('2026-05-31', 1200)],
      HOY)
    expect(out[0].capital_inicio).toBe(1000)
    expect(out[0].capital_final).toBe(1200)
  })

  it('no depende de que los snapshots vengan ordenados', () => {
    const out = applyMtmToMonthly(
      [mes(2026, 5)],
      [snap('2026-05-31', 1200), snap('2026-04-01', 500),
       snap('2026-04-30', 1000), snap('2026-05-02', 1111)],
      HOY)
    expect(out[0].capital_inicio).toBe(1000)
    expect(out[0].capital_final).toBe(1200)
  })

  it('cruza el año correctamente (enero busca diciembre anterior)', () => {
    const out = applyMtmToMonthly(
      [mes(2026, 1)], [snap('2025-12-31', 800), snap('2026-01-31', 950)], HOY)
    expect(out[0].capital_inicio).toBe(800)
    expect(out[0].capital_final).toBe(950)
  })
})

describe('applyMtmToMonthly — mes EN CURSO', () => {
  it('le alcanza el snapshot del mes anterior: su cierre ya es live', () => {
    // El mes en curso es el que HOY absorbe todo el no realizado histórico,
    // porque su cf viene del sync live y su ci de la cadena a costo.
    const out = applyMtmToMonthly(
      [mes(2026, 8, { capital_inicio: 1050, capital_final: 1300 })],
      [snap('2026-07-31', 1200)], HOY)
    expect(out[0].capital_inicio).toBe(1200)
    expect(out[0].capital_final).toBe(1300)   // intacto
    expect(out[0].mtm).toBe('inicio')
  })

  it('mata el salto fantasma: 23,8% inventado pasa a 8,3% real', () => {
    const antes = mes(2026, 8, { capital_inicio: 1050, capital_final: 1300 })
    const [despues] = applyMtmToMonthly([antes], [snap('2026-07-31', 1200)], HOY)
    expect(rDietz(antes)).toBeCloseTo(250 / 1050, 6)    // +23,8% de un mes
    expect(rDietz(despues)).toBeCloseTo(100 / 1200, 6)  // +8,3%, lo que pasó de verdad
  })

  it('sin snapshot del mes anterior queda como está', () => {
    const out = applyMtmToMonthly([mes(2026, 8)], [snap('2026-08-14', 1300)], HOY)
    expect(out[0].mtm).toBeUndefined()
  })
})

describe('applyMtmToMonthly — sin datos no hay regresión', () => {
  it('sin snapshots devuelve la entrada tal cual', () => {
    const filas = [mes(2026, 5)]
    expect(applyMtmToMonthly(filas, [], HOY)).toBe(filas)
    expect(applyMtmToMonthly(filas, null, HOY)).toBe(filas)
  })

  it('sin filas mensuales no explota', () => {
    expect(applyMtmToMonthly([], [snap('2026-05-31', 1200)], HOY)).toEqual([])
    expect(applyMtmToMonthly(null, [snap('2026-05-31', 1200)], HOY)).toEqual([])
  })

  it('ignora snapshots con total_value nulo, 0 o negativo', () => {
    const out = applyMtmToMonthly(
      [mes(2026, 5)],
      [snap('2026-04-30', 0), snap('2026-04-29', 1000), snap('2026-05-31', null),
       snap('2026-05-30', 1200)],
      HOY)
    expect(out[0].capital_inicio).toBe(1000)
    expect(out[0].capital_final).toBe(1200)
  })

  it('NO muta la entrada', () => {
    const filas = [mes(2026, 5)]
    const copia = JSON.parse(JSON.stringify(filas))
    applyMtmToMonthly(filas, [snap('2026-04-30', 1000), snap('2026-05-31', 1200)], HOY)
    expect(filas).toEqual(copia)
  })

  it('los flujos NUNCA se tocan: son el registro contable', () => {
    const out = applyMtmToMonthly(
      [mes(2026, 5, { deposits: 300, withdrawals: 40, pnl_realized: 50 })],
      [snap('2026-04-30', 1000), snap('2026-05-31', 1500)], HOY)
    expect(out[0].deposits).toBe(300)
    expect(out[0].withdrawals).toBe(40)
    expect(out[0].pnl_realized).toBe(50)
    // Y el retorno descuenta el aporte: (1500−1000−260)/(1000+130) = 21,2%
    expect(rDietz(out[0])).toBeCloseTo(240 / 1130, 10)
  })
})

describe('el aportado NO se contamina con valor de mercado', () => {
  it('preserva el baseline de costo cuando pisa capital_inicio', () => {
    const out = applyMtmToMonthly(
      [mes(2026, 5, { capital_inicio: 1000 })],
      [snap('2026-04-30', 1800), snap('2026-05-31', 1900)], HOY)
    expect(out[0].capital_inicio).toBe(1800)        // la serie ve mercado
    expect(out[0].capital_inicio_costo).toBe(1000)  // el aportado ve costo
  })

  it('netCapitalContributed sigue dando lo APORTADO, no lo que vale', () => {
    // Sin el guard, el hero sumaría los 800 de ganancia latente al "capital
    // aportado" — y "Resultado total = valor − aportado" se comería la ganancia.
    const filas = applyMtmToMonthly(
      [mes(2026, 5, { capital_inicio: 1000, deposits: 200, withdrawals: 50 })],
      [snap('2026-04-30', 1800), snap('2026-05-31', 1900)], HOY)
    expect(netCapitalContributed(filas)).toBe(1000 + 200 - 50)
  })

  it('sin snapshots el aportado es idéntico al de antes', () => {
    const filas = [mes(2026, 5, { capital_inicio: 1000, deposits: 200 })]
    expect(netCapitalContributed(applyMtmToMonthly(filas, [], HOY)))
      .toBe(netCapitalContributed(filas))
  })
})
