// "¿Le ganás a la inflación?" sobre una cuenta que compra y mantiene, con las
// respuestas REALES del servidor.
//
// El caso (medido el 2026-10-13 en producción): broker en pesos, depósito de
// $10 M y siete compras el 13/10/2025, cargados a mano. La pantalla decía
// Plazo fijo UVA "Le ganás +1,6 %", Dólar "Le ganás +25,9 %" e Inflación
// "Le perdés −16,6 %": contradictorio (el UVA sigue a la inflación) y falso.
// La celda deflactaba un retorno en pesos armado sobre `capital_final` de
// `/monthly`, que para esta cuenta vale AL COSTO todos los meses.
//
// `fixtures/compraYMantieneArs.json` lo arma
// `backend/scripts/fixture_compra_y_mantiene_ars.py` cargando la cuenta por las
// mismas puertas que la app (`/brokers`, `/cash/flow`, `/positions`, con fecha
// pasada) y guardando lo que la pantalla recibe. Acá se corre la cuenta de
// Insights.jsx con las mismas funciones y en el mismo orden: valor de hoy
// (`computeBrokerValue`), cobertura de precios, `applyMtmToMonthly` sobre las
// filas `global`, y `veredictoInflacion`.

import { describe, it, expect } from 'vitest'
import datos from './fixtures/compraYMantieneArs.json'
import { computeBrokerValue, coberturaDePrecios, COBERTURA_MINIMA } from './valuation'
import { applyMtmToMonthly } from './insightsModel'
import { veredictoInflacion, simulatePlazoFijoUva, simulateDolarCash, compararEnPesos, patrimonioEnPesos, blueAlCierre } from './benchmarkSim'
import { selectDiagnostics } from './diagnostics'
import { computeReturnExpectation } from './profileMatch'
import { pickFinancialRate } from '../contexts/CurrencyContext'

const { monthly, positions, brokers, snapshots, benchmarks: bench, dolar, prices } = datos

// Lo mismo que Insights.jsx, en el mismo orden. `dolarElegido` es el selector
// de "dólar de valuación" (MEP por defecto, CCL si el usuario lo cambia).
function comoLaPantalla(precios, dolarElegido = 'mep') {
  const tc = pickFinancialRate(dolar, dolarElegido) || 1415
  const tcCripto = dolar?.cripto?.venta
  const pieData = brokers
    .map(b => ({ name: b.name, value: +computeBrokerValue(positions, precios, b, tc, tc, tcCripto, undefined).value.toFixed(2) }))
    .filter(x => x.value > 0)
  const totalPortfolio = pieData.reduce((s, x) => s + x.value, 0)
  const cobertura = coberturaDePrecios(positions, precios, brokers, { tcValuacion: tc, tcCedear: tc, tcCripto })
  const preciosCompletos = cobertura >= COBERTURA_MINIMA
  const globalMonthly = applyMtmToMonthly(
    [...monthly.filter(m => m.broker === 'global')].sort((a, b) => (a.year - b.year) || (a.month - b.month)),
    snapshots, undefined, totalPortfolio)
  const patrimonioHoyArs = patrimonioEnPesos(
    brokers.map(b => ({ currency: b.currency, valueUsd: pieData.find(x => x.name === b.name)?.value || 0 })),
    tc, blueAlCierre(globalMonthly, bench.dolar_blue))
  const vsInflacion = veredictoInflacion({
    globalMonthly, inflationMap: bench.inflation_ar, blueMap: bench.dolar_blue,
    valorHoyUsd: totalPortfolio, valorHoyArs: patrimonioHoyArs, valorHoyMedido: preciosCompletos,
  })
  const uva = simulatePlazoFijoUva(globalMonthly, bench.uva, bench.dolar_blue)
  const quieto = simulateDolarCash(globalMonthly)
  return {
    totalPortfolio, preciosCompletos, globalMonthly, vsInflacion,
    vsUva: compararEnPesos(totalPortfolio, patrimonioHoyArs, uva.finalArs)?.pct ?? null,
    vsDolar: (totalPortfolio / quieto.finalValue - 1) * 100,
  }
}

describe('Inflación — cuenta que compra y mantiene, cargada por la API', () => {
  it('el punto de partida: /monthly trae el broker AL COSTO todos los meses', () => {
    // Si esto deja de ser cierto (la cuenta manual pasa a tener historia a
    // mercado), el caso cambia y esta prueba hay que revisarla, no borrarla.
    const balanz = monthly.filter(m => m.broker === 'Balanz')
    expect(balanz.length).toBeGreaterThanOrEqual(12)
    const finales = new Set(balanz.map(m => m.capital_final.toFixed(2)))
    expect(finales.size).toBe(1)
    expect(snapshots).toEqual([])
  })

  const r = comoLaPantalla(prices)
  // La cuenta exacta, en pesos y sin pasar por ningún dólar: lo que vale hoy
  // contra los $10 M ajustados por el IPC de cada mes desde noviembre de 2025
  // (el mes del depósito no capitaliza, como en el plazo fijo UVA).
  const pesosHoy = positions.filter(p => !p.is_cash)
    .reduce((s, p) => s + p.quantity * prices[`${p.asset}.BA`], 0)
    + positions.filter(p => p.is_cash).reduce((s, p) => s + (p.invested || 0), 0)
  const ipc = Object.keys(bench.inflation_ar).sort().filter(k => k > '2025-10')
  const indice = ipc.reduce((f, k) => f * (1 + bench.inflation_ar[k] / 100), 1)
  const exacto = (pesosHoy / (10_000_000 * indice) - 1) * 100

  it('con los precios de hoy, le GANA a la inflación (antes: "Le perdés −16,6 %")', () => {
    expect(r.preciosCompletos).toBe(true)
    expect(r.vsInflacion).not.toBeNull()
    expect(r.vsInflacion.pct).toBeGreaterThan(0)
    expect(exacto).toBeGreaterThan(0)
  })

  it('se aparta de la cuenta exacta en pesos sólo por el riel del dólar (< 3 puntos)', () => {
    // El depósito se dolarizó a un dólar y la simulación lo vuelve a pesos al
    // blue del mes: es la misma aproximación que usan Plazo fijo UVA y Dólar.
    expect(Math.abs(r.vsInflacion.pct - exacto)).toBeLessThan(3)
  })

  it('no contradice a la celda del plazo fijo UVA (que sigue a la inflación)', () => {
    expect(Math.sign(r.vsInflacion.pct)).toBe(Math.sign(r.vsUva))
    expect(Math.abs(r.vsInflacion.pct - r.vsUva)).toBeLessThan(6)
  })

  it('dice hasta qué mes cuenta la inflación (el INDEC publica con atraso)', () => {
    expect(r.vsInflacion.hastaMes).toBe(ipc[ipc.length - 1])
    expect(r.vsInflacion.meses).toBe(ipc.length)
  })

  it('el hallazgo del diagnóstico y la tarjeta del perfil dicen el MISMO número', () => {
    const pool = selectDiagnostics({ vsInflacion: r.vsInflacion, currency: 'ARS' }, 999)
    const ids = pool.map(d => d.id)
    expect(ids).toContain('beat_inflation_ars')
    expect(ids).not.toContain('lose_to_inflation_ars')
    const txt = pool.find(d => d.id === 'beat_inflation_ars').text
    expect(txt).toContain(r.vsInflacion.pct.toFixed(1).replace('.', ','))

    const card = computeReturnExpectation({ return_expectation: 'beat_inflation' }, {
      realReturnPct: r.vsInflacion.pct, inflationPct: r.vsInflacion.inflacionPct,
      monthsCounted: r.vsInflacion.meses,
      valorHoyArs: r.vsInflacion.valorHoyArs, mismaPlataArs: r.vsInflacion.mismaPlataArs,
    })
    expect(card.status).toBe('ready')
    expect(card.actual.realReturnPct).toBe(Math.round(r.vsInflacion.pct * 10) / 10)
  })

  it('el veredicto no depende del dólar elegido para valuar (antes: +7,9 % en MEP, +2,7 % en CCL)', () => {
    const ccl = comoLaPantalla(prices, 'ccl')
    expect(pickFinancialRate(dolar, 'ccl')).not.toBeCloseTo(pickFinancialRate(dolar, 'mep'), 0)
    // Iguales salvo el redondeo a centavos de dólar que la pantalla le aplica
    // al total de cada broker (milésimas de punto).
    expect(ccl.vsInflacion.pct).toBeCloseTo(r.vsInflacion.pct, 3)
    expect(ccl.vsUva).toBeCloseTo(r.vsUva, 3)
  })

  it('sin precios, la valuación cae al costo y NO se publica ningún veredicto', () => {
    const sin = comoLaPantalla({})
    expect(sin.preciosCompletos).toBe(false)
    expect(sin.vsInflacion).toBeNull()
  })
})
