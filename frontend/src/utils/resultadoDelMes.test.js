// El resultado del mes sin el puente de un pase entre brokers (spec E.7 / E.10).
import { describe, it, expect } from 'vitest'
import { resultadoSinPuente, puenteDelMes, lineasDelPuente, resultadoParaElPorcentaje } from './resultadoDelMes'
import { fmtUsd } from './format'

describe('resultadoSinPuente', () => {
  it('broker de origen: el realizado trae +V−C del pase y el rendimiento no', () => {
    // Vendió algo por +10 y pasó títulos que valían 178,57 y costaron 92,30.
    const a = { pnl_realized: 10 + 86.27, puente_salida_usd: 86.27 }
    expect(resultadoSinPuente(a)).toBeCloseTo(10, 6)
    expect(puenteDelMes(a)).toBeCloseTo(86.27, 6)
  })

  it('broker de destino: el realizado trae −(V−C) y el rendimiento no', () => {
    const b = { pnl_realized: -86.27, puente_entrada_usd: 86.27 }
    expect(resultadoSinPuente(b)).toBeCloseTo(0, 6)
  })

  it('el gasto del trámite queda: es una pérdida de verdad', () => {
    const a = { pnl_realized: 86.27 - 3.57, puente_salida_usd: 86.27, gasto_pase_usd: 3.57 }
    expect(resultadoSinPuente(a)).toBeCloseTo(-3.57, 6)
  })

  it('una fila sin pase (o la global con las dos patas vivas) queda igual', () => {
    expect(resultadoSinPuente({ pnl_realized: 42 })).toBe(42)
    expect(resultadoSinPuente({})).toBe(0)
  })
})

// Revisión E12, problema 2: en el mes en curso el % suma el no realizado, que en B
// trae la ganancia vieja (los títulos llegan con su costo original C). Sacar ahí
// el puente hacía que el % contradijera el monto de la misma fila.
describe('resultadoParaElPorcentaje: el % del mes en curso cuenta lo mismo que el monto', () => {
  // B arranca el mes con 1.000; recibe títulos con C = 100 que valían V = 300 el
  // día del pase; hoy valen 310. El realizado de B trae −(V − C) = −200.
  const B = { capital_inicio: 1000, pnl_realized: -200, puente_entrada_usd: 200, pnl_unrealized: 310 - 100 }
  // A tenía esos títulos (C = 100) y los pasó cuando valían 300: el realizado
  // trae +(V − C) = +200 y en su no realizado ya no están.
  const A = { capital_inicio: 5000, pnl_realized: 200, puente_salida_usd: 200, pnl_unrealized: 0 }

  it('B en el mes en curso: +10 (lo que ganó desde que llegaron), no +210', () => {
    const monto = B.pnl_realized + B.pnl_unrealized
    expect(monto).toBe(10)
    expect(resultadoParaElPorcentaje(B, true)).toBe(monto)
    expect(resultadoParaElPorcentaje(B, true) / B.capital_inicio).toBeCloseTo(0.01, 9)   // +1 %, no +21 %
  })

  it('A en el mes en curso: el pase no le cambia el % (antes esos 200 estaban en su no realizado)', () => {
    const antesDelPase = { capital_inicio: 5000, pnl_realized: 0, pnl_unrealized: 200 }
    expect(resultadoParaElPorcentaje(A, true)).toBe(resultadoParaElPorcentaje(antesDelPase, true))
  })

  it('en un mes cerrado sí se saca el puente: no se vendió nada', () => {
    expect(resultadoParaElPorcentaje({ ...A, pnl_unrealized: 0 }, false)).toBe(0)
    expect(resultadoParaElPorcentaje({ ...B, pnl_unrealized: 0 }, false)).toBe(0)
    // El gasto del trámite queda en los dos casos.
    expect(resultadoParaElPorcentaje({ pnl_realized: 196.5, puente_salida_usd: 200, gasto_pase_usd: 3.5 }, false)).toBeCloseTo(-3.5, 9)
  })

  it('una fila sin pase da lo mismo que antes del cambio (realizado + no realizado si es el mes en curso)', () => {
    const m = { pnl_realized: 42, pnl_unrealized: 8 }
    expect(resultadoParaElPorcentaje(m, true)).toBe(50)
    expect(resultadoParaElPorcentaje(m, false)).toBe(42)
  })
})

describe('lineasDelPuente', () => {
  it('un renglón por concepto distinto de 0', () => {
    expect(lineasDelPuente({ puente_salida_usd: 86.27, gasto_pase_usd: 3.5 }, fmtUsd)).toEqual([
      'Incluye una ganancia de USD 86,27 de los títulos que pasaste a otro broker (no es una venta).',
      'Incluye USD 3,50 del costo del pase.',
    ])
    expect(lineasDelPuente({ puente_entrada_usd: 86.27 }, fmtUsd)).toEqual([
      'Descuenta USD 86,27: los títulos que llegaron desde otro broker ya traían esa ganancia (no es una pérdida).',
    ])
    expect(lineasDelPuente({ puente_entrada_usd: -12 }, fmtUsd)).toEqual([
      'Suma USD 12,00: los títulos que llegaron desde otro broker ya traían esa pérdida.',
    ])
    expect(lineasDelPuente({ puente_salida_usd: -5 }, fmtUsd)[0]).toMatch(/^Incluye una pérdida de USD 5,00/)
    expect(lineasDelPuente({ pnl_realized: 10 }, fmtUsd)).toEqual([])
  })
})
