// "Atribución del crecimiento" sobre una cuenta que compra y mantiene, con las
// respuestas REALES del servidor.
//
// El caso (medido el 2026-10-14 con un servidor local): broker en pesos,
// depósito de $10 M y siete compras el 13/10/2025, cargados por la API; hoy vale
// ~$14,2 M. La tarjeta decía "Aportes netos +ARS 10.871.378 (100 %) ·
// Rendimiento del mercado +ARS 0 (0 %)": sumaba capital_final − capital_inicio −
// aportes de la cadena mensual, que para esta cuenta vale AL COSTO todos los
// meses (sin fotos, `applyMtmToMonthly` no re-ancla nada).
//
// `fixtures/compraYMantieneArs.json` lo arma
// `backend/scripts/fixture_compra_y_mantiene_ars.py` cargando la cuenta por las
// mismas puertas que la app y guardando lo que la pantalla recibe. Acá se corre
// la cuenta de Insights.jsx con las mismas funciones y en el mismo orden: valor
// de hoy (`computeBrokerValue`), cobertura de precios, `applyMtmToMonthly` sobre
// las filas `global`, `atribucionDelCrecimiento` y el diagnóstico.

import { describe, it, expect } from 'vitest'
import datos from './fixtures/compraYMantieneArs.json'
import { computeBrokerValue, coberturaDePrecios, COBERTURA_MINIMA } from './valuation'
import { applyMtmToMonthly, atribucionDelCrecimiento } from './insightsModel'
import { selectDiagnostics } from './diagnostics'
import { pickFinancialRate } from '../contexts/CurrencyContext'

const { monthly, positions, brokers, snapshots, dolar, prices } = datos

// Lo mismo que Insights.jsx, en el mismo orden.
function comoLaPantalla(precios) {
  const tc = pickFinancialRate(dolar, 'mep') || 1415
  const tcCripto = dolar?.cripto?.venta
  const totalPortfolio = brokers.reduce(
    (s, b) => s + +computeBrokerValue(positions, precios, b, tc, tc, tcCripto, undefined).value.toFixed(2), 0)
  const cobertura = coberturaDePrecios(positions, precios, brokers, { tcValuacion: tc, tcCedear: tc, tcCripto })
  const preciosCompletos = cobertura >= COBERTURA_MINIMA
  const globalMonthly = applyMtmToMonthly(
    [...monthly.filter(m => m.broker === 'global')].sort((a, b) => (a.year - b.year) || (a.month - b.month)),
    snapshots, undefined, totalPortfolio)
  const discipline = atribucionDelCrecimiento({
    globalMonthly, valorHoy: totalPortfolio, valorHoyMedido: preciosCompletos,
  })
  return { tc, totalPortfolio, preciosCompletos, globalMonthly, discipline }
}

// La cuenta vieja, tal cual estaba en Insights.jsx hasta el 2026-10-14.
function sumaDeLaCadena(globalMonthly) {
  return globalMonthly.reduce((s, m) => {
    const net = (m.deposits || 0) - (m.withdrawals || 0)
    return s + ((m.capital_final || 0) - (m.capital_inicio || 0) - net)
  }, 0)
}

describe('Atribución del crecimiento — cuenta que compra y mantiene, cargada por la API', () => {
  const r = comoLaPantalla(prices)
  // La cuenta exacta, en pesos: lo que valen hoy las tenencias más el efectivo.
  const pesosHoy = positions.filter(p => !p.is_cash)
    .reduce((s, p) => s + p.quantity * prices[`${p.asset}.BA`], 0)
    + positions.filter(p => p.is_cash).reduce((s, p) => s + (p.invested || 0), 0)

  it('el punto de partida: la cadena mensual está al costo y su suma da mercado = 0', () => {
    // Si esto deja de ser cierto (la cuenta manual pasa a tener historia a
    // mercado), el caso cambia y esta prueba hay que revisarla, no borrarla.
    expect(snapshots).toEqual([])
    expect(Math.abs(sumaDeLaCadena(r.globalMonthly))).toBeLessThan(0.01)
  })

  it('con los precios de hoy, el mercado es lo que vale la cartera menos lo aportado', () => {
    expect(r.preciosCompletos).toBe(true)
    const d = r.discipline
    expect(d).not.toBeNull()
    // Contra cuentas hechas por separado, no con las mismas funciones: el
    // depósito tal cual lo guardó el servidor (pesos ÷ el dólar con que lo
    // dolarizó) y lo que valen hoy los papeles en pesos (precio × cantidad).
    // ⚠️ La base del fixture no tenía historia del dólar y dolarizó al de
    // respaldo (1415); en producción es el MEP del día del depósito.
    const fila = monthly.find(m => m.broker === 'Balanz' && m.manual_deposits_native > 0)
    const depositoUsd = fila.manual_deposits
    expect(fila.manual_deposits_native).toBe(10_000_000)
    expect(d.deposits).toBeCloseTo(depositoUsd, 2)
    expect(Math.abs(d.total * r.tc - pesosHoy)).toBeLessThan(1000)
    expect(Math.abs((d.pnl + depositoUsd) * r.tc - pesosHoy)).toBeLessThan(1000)
    // Y el mercado ya no es cero: ~$3,3 M al tipo de hoy (la cartera vale ~$14,2 M).
    expect(d.pnl * r.tc).toBeGreaterThan(3_000_000)
  })

  it('los hallazgos del diagnóstico leen el MISMO reparto que la tarjeta', () => {
    const d = r.discipline
    const pool = selectDiagnostics({ discipline: d }, 999)
    const dep = pool.find(x => x.id === 'growth_from_deposits')
    const share = (Math.abs(d.deposits) / (Math.abs(d.deposits) + Math.abs(d.pnl))) * 100
    // ~77 % aportes / ~23 % mercado: el hallazgo de aportes se dispara con su
    // porcentaje real, no con el 100 % que salía con el mercado en cero.
    expect(dep).toBeTruthy()
    expect(dep.text).toContain(`**${share.toFixed(0)}%**`)
    expect(share).toBeLessThan(90)
  })

  it('sin precios, la valuación cae al costo y la tarjeta NO se publica', () => {
    const sin = comoLaPantalla({})
    expect(sin.preciosCompletos).toBe(false)
    expect(sin.discipline).toBeNull()
    expect(selectDiagnostics({ discipline: sin.discipline }, 999)
      .filter(x => x.id.startsWith('growth_from_'))).toEqual([])
  })
})

// Casos que el fixture no tiene. Cada número esperado está hecho a mano.
describe('atribucionDelCrecimiento — capital inicial, retiros y pérdidas', () => {
  const mes = (y, m, ci, cf, dep = 0, ret = 0) =>
    ({ year: y, month: m, capital_inicio: ci, capital_final: cf, deposits: dep, withdrawals: ret })

  it('el capital con que arranca el registro cuenta como aporte (igual que el Dashboard)', () => {
    // Importada con 1.000 ya adentro, deposita 500 después; hoy vale 1.800.
    const filas = [mes(2025, 1, 1000, 1000), mes(2025, 2, 1000, 1500, 500)]
    const d = atribucionDelCrecimiento({ globalMonthly: filas, valorHoy: 1800, valorHoyMedido: true })
    expect(d.deposits).toBe(1500)
    expect(d.pnl).toBe(300)
    expect(d.total).toBe(1800)
  })

  it('el capital inicial se toma AL COSTO aunque una foto lo haya re-anclado', () => {
    const filas = [{ ...mes(2025, 1, 1300, 1400), capital_inicio_costo: 1000 }]
    const d = atribucionDelCrecimiento({ globalMonthly: filas, valorHoy: 1400, valorHoyMedido: true })
    expect(d.deposits).toBe(1000)
    expect(d.pnl).toBe(400)
  })

  it('con retiros, los aportes son netos y aportes + mercado = valor de hoy', () => {
    // Pone 1.000, retira 600; hoy vale 700 → aportó 400 neto, el mercado puso 300.
    const filas = [mes(2025, 1, 0, 1000, 1000), mes(2025, 6, 1100, 500, 0, 600)]
    const d = atribucionDelCrecimiento({ globalMonthly: filas, valorHoy: 700, valorHoyMedido: true })
    expect(d.deposits).toBe(400)
    expect(d.pnl).toBe(300)
    expect(d.deposits + d.pnl).toBe(700)
  })

  it('con pérdida, el mercado es negativo y el hallazgo "del mercado" no sale', () => {
    const filas = [mes(2025, 1, 0, 1000, 1000)]
    const d = atribucionDelCrecimiento({ globalMonthly: filas, valorHoy: 800, valorHoyMedido: true })
    expect(d.pnl).toBe(-200)
    const ids = selectDiagnostics({ discipline: d }, 999).map(x => x.id)
    expect(ids).not.toContain('growth_from_market')
  })

  it('sin historia o sin valor de hoy no hay atribución', () => {
    expect(atribucionDelCrecimiento({ globalMonthly: [], valorHoy: 100, valorHoyMedido: true })).toBeNull()
    expect(atribucionDelCrecimiento({ globalMonthly: [mes(2025, 1, 0, 0, 100)], valorHoy: 0, valorHoyMedido: true })).toBeNull()
  })
})
