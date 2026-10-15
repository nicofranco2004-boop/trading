// Movimientos, Reportes y el libro del asesor EN PESOS, con las respuestas REALES
// del servidor.
//
// La cuenta (`fixtures/compraYMantieneArs.json` → `mixta`, la arma
// `backend/scripts/fixture_compra_y_mantiene_ars.py` por la API, con la historia
// real del dólar): un broker en pesos con un depósito de $10.000.000 (13/10/2025)
// y un retiro de $1.000.000 (10/02/2026), y un broker en dólares con un aporte de
// US$2.000 (02/03/2026) y un retiro de US$500 (15/06/2026).
//
// Las dos cosas que se prueban:
//   1. Cada número en pesos es la suma de lo que muestran sus filas, cada fila
//      al dólar de SU fecha — no la suma en dólares pasada al dólar de HOY.
//   2. Ese dólar es el que eligió el usuario (MEP), el mismo con el que el
//      servidor guardó los depósitos en pesos, y no el blue.
//
// Todo pasa por las mismas funciones que las pantallas: `dineroHistorico` es lo
// que corre `useHistoricalMoney`, con el dólar de cada fecha armado como lo arma
// `useFxHistory` sobre la misma `/api/fx-rates`.

import { describe, it, expect } from 'vitest'
import datos from './fixtures/compraYMantieneArs.json'
import { indexarSerie, tcDeFechaDetalle } from './tcHistorico'
import { dolarMensualDe } from './capitalAportado'
import { dineroHistorico } from '../hooks/useHistoricalMoney'
import { computeMovementKpis } from '../pages/Operations.jsx'
import { capitalAportado } from './capitalAportado'
import { crearPesosDelPeriodo } from './periodoEnPesos'
import { serieDelLibroEnVista } from './evolution'
import { pickFinancialRate } from '../contexts/CurrencyContext'

const { mixta, fx_rates: FX, dolar } = datos
const TC_HOY = pickFinancialRate(dolar, 'mep')
const IDX = indexarSerie(FX)
// Lo que hace `useFxHistory().getRateOrFallback`.
const tcEn = (d) => tcDeFechaDetalle(IDX, d).tc || TC_HOY
const TC_MENSUAL = dolarMensualDe(FX)
const mep = (d) => FX.find(r => r.date === d).mep
const blue = (d) => FX.find(r => r.date === d).blue

const dinero = (currency) => dineroHistorico({ currency, tcValuacion: TC_HOY, getRateForDate: tcEn })
// Lo que muestra cada fila de la lista (MovementsTable / MovementsFeed).
const fila = (hm, m) => hm.convertedValue(m.amount_usd, {
  stampedFx: m.fx_to_usd, rowCurrency: m.currency, dateIso: m.date,
})
const kpisDe = (hm, rows, filtro = 'all') => computeMovementKpis(
  rows, filtro, { sumar: hm.sumConvertedAt, fmt: String }, 0)
const kpi = (lista, label) => lista.find(k => k.label === label).num

const movs = mixta.movements
const deposito = movs.find(m => m.type === 'DEPOSIT' && m.broker === 'Balanz')
const retiroPesos = movs.find(m => m.type === 'WITHDRAW' && m.broker === 'Balanz')
const aporteUsd = movs.find(m => m.type === 'DEPOSIT' && m.broker === 'IBKR')
const retiroUsd = movs.find(m => m.type === 'WITHDRAW' && m.broker === 'IBKR')

describe('el dólar de una fecha es el elegido (MEP), no el blue', () => {
  it('el depósito de $10.000.000 se lee $10.000.000: el servidor lo guardó al MEP de ese día', () => {
    const hm = dinero('ARS')
    expect(fila(hm, deposito)).toBeCloseTo(10_000_000, 0)
    // Con el blue de ese día (1.395 contra un MEP de 1.412,3) la fila decía otra cosa.
    expect(10_000_000 - deposito.amount_usd * blue('2025-10-13')).toBeGreaterThan(100_000)
    expect(fila(hm, retiroPesos)).toBeCloseTo(1_000_000, 0)
  })

  it('un aporte en dólares va al MEP del día en que entró', () => {
    const hm = dinero('ARS')
    expect(fila(hm, aporteUsd)).toBeCloseTo(2000 * mep('2026-03-02'), 6)
    expect(fila(hm, retiroUsd)).toBeCloseTo(500 * mep('2026-06-15'), 6)
  })
})

describe('Movimientos — los números de arriba son la suma de las filas', () => {
  const hm = dinero('ARS')
  const sumaFilas = (tipo) => movs.filter(m => m.type === tipo).reduce((s, m) => s + fila(hm, m), 0)

  it('"Aportado neto" = depósitos − retiros que muestra la lista', () => {
    const aportado = kpi(kpisDe(hm, movs), 'Aportado neto')
    expect(aportado).toBeCloseTo(sumaFilas('DEPOSIT') - sumaFilas('WITHDRAW'), 6)
    expect(aportado).toBeCloseTo(
      10_000_000 - 1_000_000 + 2000 * mep('2026-03-02') - 500 * mep('2026-06-15'), 0)
    // La cuenta vieja: los dólares sumados × el dólar de hoy (unos $950.000 de más).
    const usd = movs.filter(m => m.type === 'DEPOSIT').reduce((s, m) => s + m.amount_usd, 0)
      - movs.filter(m => m.type === 'WITHDRAW').reduce((s, m) => s + m.amount_usd, 0)
    expect(usd * TC_HOY - aportado).toBeGreaterThan(900_000)
  })

  it('"Total depositado" y "Promedio" con el filtro de depósitos', () => {
    const deps = movs.filter(m => m.type === 'DEPOSIT')
    const lista = kpisDe(hm, deps, 'DEPOSIT')
    expect(kpi(lista, 'Total depositado')).toBeCloseTo(sumaFilas('DEPOSIT'), 6)
    expect(kpi(lista, 'Promedio')).toBeCloseTo(sumaFilas('DEPOSIT') / deps.length, 6)
  })

  it('en dólares no cambia nada: la suma de siempre', () => {
    const usd = dinero('USD')
    const aportado = kpi(kpisDe(usd, movs), 'Aportado neto')
    const esperado = movs.filter(m => m.type === 'DEPOSIT').reduce((s, m) => s + m.amount_usd, 0)
      - movs.filter(m => m.type === 'WITHDRAW').reduce((s, m) => s + m.amount_usd, 0)
    expect(aportado).toBe(esperado)
  })
})

describe('Reportes — cada período a los pesos de su momento', () => {
  const pesos = crearPesosDelPeriodo({
    moneda: 'ARS', tcHoy: TC_HOY, tcEnFecha: tcEn, dolarMes: TC_MENSUAL,
    monthly: mixta.monthly, brokers: mixta.brokers,
  })
  const mes = (y, m, metrics) => ({
    period_type: 'month', period_key: `${y}-${String(m).padStart(2, '0')}`,
    period_start: `${y}-${String(m).padStart(2, '0')}-01`,
    period_end: new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10),
    is_current: false, metrics,
  })
  const filaGlobal = (y, m) => mixta.monthly.find(r => r.broker === 'global' && r.year === y && r.month === m)

  it('octubre 2025: "Depósitos" son los $10.000.000 que se pusieron', () => {
    const r = filaGlobal(2025, 10)
    const v = pesos.enVista(mes(2025, 10, { deposits: r.deposits, withdrawals: r.withdrawals }))
    expect(v.depositos).toBeCloseTo(10_000_000, 4)
    // Antes: × el dólar de hoy.
    expect(r.deposits * TC_HOY).toBeGreaterThan(10_800_000)
  })

  it('el año 2026: los pesos que salieron, y los dólares al dólar de su mes', () => {
    const filas = mixta.monthly.filter(r => r.broker === 'global' && r.year === 2026)
    const dep = filas.reduce((s, r) => s + r.deposits, 0)
    const ret = filas.reduce((s, r) => s + r.withdrawals, 0)
    const v = pesos.enVista({
      period_type: 'year', period_start: '2026-01-01', period_end: '2026-12-31',
      is_current: false, metrics: { deposits: dep, withdrawals: ret },
    })
    expect(v.depositos).toBeCloseTo(2000 * TC_MENSUAL['2026-03'], 6)
    expect(v.retiros).toBeCloseTo(1_000_000 + 500 * TC_MENSUAL['2026-06'], 4)
  })

  it('"Capital aportado" del año = el del Dashboard (la misma tabla)', () => {
    const usd = capitalAportado({ monthly: mixta.monthly, brokers: mixta.brokers, dolarMes: TC_MENSUAL, tcHoy: TC_HOY })
    expect(pesos.aportadoHasta('2026-10-15', usd.usd)).toBeCloseTo(usd.ars, 6)
    // Y si los dólares no coinciden con los del servidor, no inventa pesos.
    expect(pesos.aportadoHasta('2026-10-15', usd.usd + 500)).toBe(null)
  })

  it('valor de inicio y de cierre, cada uno al dólar de su día', () => {
    const v = pesos.enVista(mes(2026, 3, { start_value: 100, end_value: 110, delta_usd: 10 }))
    expect(v.inicio).toBeCloseTo(100 * mep('2026-02-27'), 6)   // 28/02 fue sábado: el viernes
    expect(v.cierre).toBeCloseTo(110 * mep('2026-03-31'), 6)
    expect(v.resultado).toBeCloseTo(10 * mep('2026-03-31'), 6)
  })

  it('en dólares, los números del servidor tal cual', () => {
    const usd = crearPesosDelPeriodo({ moneda: 'USD', tcHoy: TC_HOY, tcEnFecha: tcEn, dolarMes: TC_MENSUAL })
    const m = { deposits: 7058.16, withdrawals: 0, start_value: 1, end_value: 2, delta_usd: 1, realized_pnl: 3 }
    expect(usd.enVista(mes(2025, 10, m))).toMatchObject({
      depositos: 7058.16, retiros: 0, inicio: 1, cierre: 2, resultado: 1, realizado: 3,
    })
  })
})

describe('Libro del asesor — la línea "Aportado neto" en pesos', () => {
  // Una curva con el aportado quieto mientras el dólar se mueve, y un aporte en el medio.
  const serie = [
    { date: '2026-02-27', aum_usd: 1000, net_deposited_usd: 1000, clients: 1 },
    { date: '2026-03-31', aum_usd: 1000, net_deposited_usd: 1000, clients: 1 },
    { date: '2026-06-15', aum_usd: 1500, net_deposited_usd: 1500, clients: 1 },
    { date: '2026-06-30', aum_usd: 1500, net_deposited_usd: 1500, clients: 1 },
  ]
  it('no sube con el dólar: sólo cuando entra plata, a los pesos con que entró', () => {
    const v = serieDelLibroEnVista(serie, 'ARS', tcEn, TC_HOY, '2026-10-15')
    expect(v[1].aportado).toBeCloseTo(v[0].aportado, 6)              // el dólar se movió, nadie aportó
    expect(v[2].aportado - v[1].aportado).toBeCloseTo(500 * mep('2026-06-15'), 6)
    expect(v[3].aportado).toBeCloseTo(v[2].aportado, 6)
    // Lo administrado, al dólar de cada día.
    expect(v[3].aum).toBeCloseTo(1500 * mep('2026-06-30'), 6)
  })
  it('en dólares, la curva de siempre', () => {
    const v = serieDelLibroEnVista(serie, 'USD', tcEn, TC_HOY, '2026-10-15')
    expect(v.map(p => [p.aum, p.aportado])).toEqual(serie.map(p => [p.aum_usd, p.net_deposited_usd]))
  })
})
