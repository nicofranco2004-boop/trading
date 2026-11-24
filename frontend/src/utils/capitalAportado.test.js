// «Capital aportado» en pesos con un pase de títulos entre brokers (spec E.7 / E.10).
//
// El pase escribe una pata de salida en A (un retiro de V) y una de entrada en B
// (un depósito de V). En la cuenta entera se anulan: el aportado total no cambia.
// El servidor manda las patas APARTE de lo importado (`traspaso_pesos_*`,
// `traspaso_usd_con_dia`) y, para la fila global, sólo el neto de las patas vivas
// (`traspaso_neto_pesos` / `traspaso_neto_usd`, 0 con las dos vivas).
import { describe, it, expect } from 'vitest'
import { capitalAportado } from './capitalAportado'

const BROKERS = [
  { id: 1, name: 'Cocos', currency: 'ARS' },
  { id: 2, name: 'Balanz', currency: 'ARS' },
  { id: 3, name: 'Balanz · USD', currency: 'USDT', parent_broker_id: 2 },
  { id: 4, name: 'Schwab', currency: 'USD' },
]
const DOLAR_MES = { '2026-10': 1300, '2026-11': 1400 }
const DIAS = { '2026-11-05': 1350, '2026-11-20': 1420 }
const tcEnFecha = (iso) => DIAS[iso] ?? null
const fila = (broker, o = {}) => ({ broker, year: 2026, month: 11, capital_inicio: 0, deposits: 0, withdrawals: 0, ...o })

// Un aporte de US$ 1.000 en Schwab el 05/11 (importado, con su día).
const APORTE = fila('Schwab', { deposits: 1000, usd_con_dia: { importado: { dep: [['2026-11-05', 1000]] } } })
// El pase: 10 títulos que valían $250.000 (US$ 172,41 al dólar del pase, 1.450) de Cocos a Balanz.
const V_ARS = 250000
const V_USD = 250000 / 1450
const SALIDA = fila('Cocos', { withdrawals: V_USD, traspaso_pesos_ret: V_ARS, traspaso_pesos_ret_usd: V_USD })
const ENTRADA = fila('Balanz', { deposits: V_USD, traspaso_pesos_dep: V_ARS, traspaso_pesos_dep_usd: V_USD })

const calcular = (monthly, broker = 'global') =>
  capitalAportado({ monthly, brokers: BROKERS, dolarMes: DOLAR_MES, tcEnFecha, tcHoy: 1500, broker })

describe('capitalAportado con un pase entre brokers', () => {
  it('pase + aporte en dólares con día en el mismo mes: el global en pesos da lo mismo que sin el pase', () => {
    const sinPase = calcular([fila('global', { deposits: 1000 }), APORTE])
    const conPase = calcular([fila('global', { deposits: 1000, traspaso_neto_pesos: 0, traspaso_neto_usd: 0 }), APORTE, SALIDA, ENTRADA])
    expect(sinPase.ars).toBeCloseTo(1000 * 1350, 6)
    expect(conPase.ars).toBeCloseTo(sinPase.ars, 6)
    expect(conPase.usd).toBeCloseTo(sinPase.usd, 6)
  })

  it('en la tabla del broker que recibió, la pata en pesos cuenta con SUS pesos (no al dólar del mes)', () => {
    const b = calcular([fila('global', { deposits: 1000 }), APORTE, SALIDA, ENTRADA], 'Balanz')
    expect(b.ars).toBeCloseTo(V_ARS, 6)                 // y no V_USD × 1.400 = 241.379
    const a = calcular([fila('global', { deposits: 1000 }), APORTE, SALIDA, ENTRADA], 'Cocos')
    expect(a.ars).toBeCloseTo(-V_ARS, 6)
  })

  it('una pata en dólares va al dólar de su día', () => {
    const entradaUsd = fila('Balanz · USD', { deposits: 100, traspaso_usd_con_dia: { dep: [['2026-11-20', 100]], ret: [] } })
    const b = calcular([fila('global'), entradaUsd], 'Balanz · USD')
    expect(b.ars).toBeCloseTo(100 * 1420, 6)
  })

  it('un pase incompleto (se borró el broker de origen): la global toma el neto que queda, en pesos', () => {
    const monthly = [
      fila('global', { deposits: 1000 + V_USD, traspaso_neto_usd: V_USD, traspaso_neto_pesos: V_ARS }),
      APORTE, ENTRADA,
    ]
    expect(calcular(monthly).ars).toBeCloseTo(1000 * 1350 + V_ARS, 6)
  })
})
