// "Capital aportado" y "Ganancia total" EN PESOS, con las respuestas REALES del
// servidor.
//
// El caso (medido el 2026-10-14 con un servidor local): broker en pesos,
// depósito de $10.000.000 y siete compras el 13/10/2025, cargados por la API.
// En pesos el Dashboard decía "Aportado ARS 10.861.131 · Ganancia total
// +ARS 3.357.029", y Análisis → "Atribución del crecimiento" lo mismo. La persona
// puso $10 M; las acciones valen hoy ~$14,2 M. El servidor guarda el depósito en
// dólares (US$ 7.067, al dólar de ese día) y la pantalla los multiplicaba por el
// dólar de HOY: la devaluación del medio pasaba de "ganancia" a "aportado".
//
// `fixtures/compraYMantieneArs.json` lo arma
// `backend/scripts/fixture_compra_y_mantiene_ars.py` cargando la cuenta por las
// mismas puertas que la app y guardando lo que la pantalla recibe. Acá se corre
// la cuenta del Dashboard y de Análisis con las mismas funciones y en el mismo
// orden que las páginas.

import { describe, it, expect } from 'vitest'
import datos from './fixtures/compraYMantieneArs.json'
import { computeBrokerValue, coberturaDePrecios, COBERTURA_MINIMA, noRealizadoEnVista } from './valuation'
import { applyMtmToMonthly, atribucionDelCrecimiento, netCapitalContributed } from './insightsModel'
import { capitalAportado, resultadoTotal, aportadoEnPesosAl, diferenciaDeCambio } from './capitalAportado'
import { convertSeriesToArs } from './evolution'
import { buildDashboardInsight } from './insights'
import { selectDiagnostics } from './diagnostics'
import { pickFinancialRate } from '../contexts/CurrencyContext'

const { monthly, positions, brokers, dolar, prices, benchmarks } = datos
const DEPOSITO = 10_000_000

// Lo mismo que Dashboard.jsx, en el mismo orden (sin plazos fijos: la cuenta no tiene).
function comoElDashboard(moneda, precios = prices) {
  const tcValuacion = pickFinancialRate(dolar, 'mep') || 1415
  const tcCripto = dolar?.cripto?.venta
  const brokerTotals = brokers.map(b => computeBrokerValue(positions, precios, b, tcValuacion, tcValuacion, tcCripto, 'purchase'))
  const totalValue = brokerTotals.reduce((s, b) => s + b.value, 0)
  const resultado = resultadoTotal({
    monthly, brokers, blueMap: benchmarks.dolar_blue, tcHoy: tcValuacion,
    valorHoyUsd: totalValue, moneda, extraUsd: 0, capitalMaximoUsd: null,
  })
  const costoHoyUsd = brokers.reduce((s, b) => s + computeBrokerValue(positions, precios, b, tcValuacion, tcValuacion, tcCripto, 'today').invested, 0)
  return { tcValuacion, totalValue, resultado, costoHoyUsd }
}

// La cuenta exacta, en pesos: lo que valen hoy las tenencias más el efectivo.
const pesosHoy = positions.filter(p => !p.is_cash)
  .reduce((s, p) => s + p.quantity * prices[`${p.asset}.BA`], 0)
  + positions.filter(p => p.is_cash).reduce((s, p) => s + (p.invested || 0), 0)
// Lo que suma la lista "Atribución por activo" en pesos: valor de hoy − lo pagado.
const pnlPorActivoEnPesos = positions.filter(p => !p.is_cash)
  .reduce((s, p) => s + p.quantity * prices[`${p.asset}.BA`] - p.invested, 0)

describe('Capital aportado en pesos — cuenta que compra y mantiene, cargada por la API', () => {
  const ars = comoElDashboard('ARS')

  it('el punto de partida: el servidor guarda el depósito en dólares y los pesos aparte', () => {
    const fila = monthly.find(m => m.broker === 'Balanz' && m.year === 2025 && m.month === 10)
    expect(fila.manual_deposits_native).toBe(DEPOSITO)
    expect(fila.manual_deposits).toBeCloseTo(7067.14, 2)
    // La cuenta vieja: esos dólares × el dólar de hoy. Es el número que se veía.
    const viejo = netCapitalContributed(monthly.filter(m => m.broker === 'global')) * ars.tcValuacion
    expect(Math.round(viejo)).toBe(10_871_378)   // 7.067,14 × 1.538,3 (MEP medio de la foto)
  })

  it('"Capital aportado" en pesos son los $10 M que se depositaron', () => {
    expect(ars.resultado.moneda).toBe('ARS')
    expect(ars.resultado.aportado).toBe(DEPOSITO)
  })

  it('"Ganancia total" en pesos = lo que vale hoy − los $10 M = la suma de la lista por activo', () => {
    expect(Math.abs(ars.resultado.valor - pesosHoy)).toBeLessThan(1)
    expect(Math.abs(ars.resultado.ganancia - (pesosHoy - DEPOSITO))).toBeLessThan(1)
    // El efectivo que sobró (32.200) no es ganancia: la ganancia es la de los papeles.
    expect(Math.abs(ars.resultado.ganancia - pnlPorActivoEnPesos)).toBeLessThan(1)
    expect(ars.resultado.ganancia).toBeGreaterThan(4_000_000)
    expect(ars.resultado.pct).toBeCloseTo(ars.resultado.ganancia / DEPOSITO, 10)
  })

  it('"P&L no realizado" en pesos cuenta la misma plata (no hay nada realizado)', () => {
    // La cuenta de Dashboard.jsx: el costo en los pesos que se pagaron.
    const noRealizado = (ars.totalValue - ars.costoHoyUsd) * ars.tcValuacion
    expect(Math.abs(noRealizado - ars.resultado.ganancia)).toBeLessThan(1)
  })

  it('la frase del Dashboard dice el % y la plata del chip, en pesos', () => {
    const ins = buildDashboardInsight({
      totalValue: ars.totalValue, netDeposited: ars.resultado.aportadoUsd,
      positions: [], resultado: ars.resultado,
    })
    const pct = (ars.resultado.pct * 100).toFixed(1).replace('.', ',')
    expect(ins.text).toContain(`+${pct}%`)
    expect(ins.text).toContain('ARS ')
    expect(ins.text).not.toContain('USD')
  })

  it('en dólares no cambia nada: la cuenta de siempre', () => {
    const usd = comoElDashboard('USD')
    const nd = netCapitalContributed(monthly.filter(m => m.broker === 'global'))
    expect(usd.resultado.moneda).toBe('USD')
    expect(usd.resultado.aportado).toBe(nd)
    expect(usd.resultado.ganancia).toBeCloseTo(usd.totalValue - nd, 8)
  })

  it('Análisis → "Atribución del crecimiento" en pesos: aportes $10 M, mercado = la ganancia del Dashboard', () => {
    const tc = ars.tcValuacion
    const precios = prices
    const totalPortfolio = brokers.reduce(
      (s, b) => s + +computeBrokerValue(positions, precios, b, tc, tc, dolar?.cripto?.venta, undefined).value.toFixed(2), 0)
    const cobertura = coberturaDePrecios(positions, precios, brokers, { tcValuacion: tc, tcCedear: tc, tcCripto: dolar?.cripto?.venta })
    const globalMonthly = applyMtmToMonthly(
      [...monthly.filter(m => m.broker === 'global')].sort((a, b) => (a.year - b.year) || (a.month - b.month)),
      [], undefined, totalPortfolio)
    const resultado = resultadoTotal({
      monthly, brokers, blueMap: benchmarks.dolar_blue, tcHoy: tc, valorHoyUsd: totalPortfolio, moneda: 'ARS',
    })
    const d = atribucionDelCrecimiento({
      globalMonthly, valorHoy: resultado.valor, aportado: resultado.aportado,
      valorHoyMedido: cobertura >= COBERTURA_MINIMA,
    })
    expect(d.deposits).toBe(DEPOSITO)
    expect(Math.abs(d.pnl - (pesosHoy - DEPOSITO))).toBeLessThan(5)   // el .toFixed(2) por broker de la página
    expect(Math.abs(d.total - pesosHoy)).toBeLessThan(5)
    // El hallazgo lee el MISMO reparto que la tarjeta: ~70 % aportes / ~30 % mercado.
    const share = (d.deposits / (d.deposits + d.pnl)) * 100
    const dep = selectDiagnostics({ discipline: d }, 999).find(x => x.id === 'growth_from_deposits')
    expect(dep.text).toContain(`**${share.toFixed(0)}%**`)
  })

  it('la línea punteada del gráfico en pesos se queda en $10 M (no sube con el dólar)', () => {
    const nd = netCapitalContributed(monthly.filter(m => m.broker === 'global'))
    const conv = aportadoEnPesosAl({ monthly, brokers, blueMap: benchmarks.dolar_blue, tcHoy: ars.tcValuacion })
    // Fotos de fin de mes, cada una con su dólar (el blue del mes) y el mismo aportado en dólares.
    const serie = Object.entries(benchmarks.dolar_blue).filter(([k]) => k >= '2025-10')
      .map(([k, blue]) => ({ date: `${k}-28`, valueUsd: 9000, netDeposited: nd, fxToUsdBlue: blue }))
    const vieja = convertSeriesToArs(serie, null)
    const nueva = convertSeriesToArs(serie, null, conv)
    // Antes: subía y bajaba con el blue (de 10,1 M a 10,95 M sin un solo depósito).
    expect(Math.max(...vieja.map(p => p.netDeposited)) - Math.min(...vieja.map(p => p.netDeposited))).toBeGreaterThan(500_000)
    for (const p of nueva) expect(Math.abs(p.netDeposited - DEPOSITO)).toBeLessThan(0.01)
    // El valor sigue al dólar de cada foto, como antes.
    expect(nueva.map(p => p.valueUsd)).toEqual(vieja.map(p => p.valueUsd))
  })
})

// ── La regla, caso por caso ────────────────────────────────────────────────
const fila = (broker, year, month, extra = {}) => ({
  broker, year, month, deposits: 0, withdrawals: 0, capital_inicio: 0,
  manual_deposits: 0, manual_deposits_native: 0, manual_withdrawals: 0, manual_withdrawals_native: 0,
  ...extra,
})
const BLUE = { '2025-01': 1200, '2025-02': 1250, '2025-03': 1300, '2025-06': 1500 }
const PESOS = [{ name: 'Cocos', currency: 'ARS' }]
const DOLARES = [{ name: 'IBKR', currency: 'USD' }]

describe('capitalAportado — la regla', () => {
  it('un depósito en pesos son esos pesos, aunque el dólar del mes sea otro', () => {
    const monthly = [
      fila('global', 2025, 2, { deposits: 1000, manual_deposits: 1000 }),
      fila('Cocos', 2025, 2, { deposits: 1000, manual_deposits: 1000, manual_deposits_native: 1_180_000 }),
    ]
    expect(capitalAportado({ monthly, brokers: PESOS, blueMap: BLUE, tcHoy: 1500 }).ars).toBe(1_180_000)
  })

  it('un depósito en dólares va al blue de SU mes, no al de hoy', () => {
    const monthly = [
      fila('global', 2025, 2, { deposits: 1000, manual_deposits: 1000 }),
      fila('IBKR', 2025, 2, { deposits: 1000, manual_deposits: 1000, manual_deposits_native: 1000 }),
    ]
    expect(capitalAportado({ monthly, brokers: DOLARES, blueMap: BLUE, tcHoy: 1500 }).ars).toBe(1_250_000)
  })

  it('una fila vieja sin los pesos guardados (o con un cociente imposible) cae al blue del mes', () => {
    const sinNativo = [
      fila('global', 2025, 3, { deposits: 1000, manual_deposits: 1000 }),
      fila('Cocos', 2025, 3, { deposits: 1000, manual_deposits: 1000 }),
    ]
    expect(capitalAportado({ monthly: sinNativo, brokers: PESOS, blueMap: BLUE, tcHoy: 1500 }).ars).toBe(1_300_000)
    // Mitad de las cargas con pesos guardados y mitad sin: el cociente da 650, la mitad de un dólar posible.
    const mezclada = [
      fila('global', 2025, 3, { deposits: 1000, manual_deposits: 1000 }),
      fila('Cocos', 2025, 3, { deposits: 1000, manual_deposits: 1000, manual_deposits_native: 650_000 }),
    ]
    expect(capitalAportado({ monthly: mezclada, brokers: PESOS, blueMap: BLUE, tcHoy: 1500 }).ars).toBe(1_300_000)
  })

  it('el saldo con que arrancó la historia va al blue del mes anterior; sin serie, al dólar de hoy', () => {
    const monthly = [fila('global', 2025, 2, { capital_inicio: 500 })]
    expect(capitalAportado({ monthly, brokers: [], blueMap: BLUE, tcHoy: 1500 }).ars).toBe(600_000)
    expect(capitalAportado({ monthly, brokers: [], blueMap: null, tcHoy: 1500 }).ars).toBe(750_000)
  })

  it('los retiros en pesos restan sus pesos, y el máximo aportado es el denominador del %', () => {
    const monthly = [
      fila('global', 2025, 1, { deposits: 1000, manual_deposits: 1000 }),
      fila('Cocos', 2025, 1, { deposits: 1000, manual_deposits: 1000, manual_deposits_native: 1_200_000 }),
      fila('global', 2025, 6, { withdrawals: 800, manual_withdrawals: 800 }),
      fila('Cocos', 2025, 6, { withdrawals: 800, manual_withdrawals: 800, manual_withdrawals_native: 1_200_000 }),
    ]
    const r = capitalAportado({ monthly, brokers: PESOS, blueMap: BLUE, tcHoy: 1500 })
    expect(r.usd).toBe(200)
    expect(r.ars).toBe(0)
    expect(r.arsMaximo).toBe(1_200_000)
    // Vale hoy $300.000: ganó $300.000 sobre lo máximo que llegó a tener puesto.
    const res = resultadoTotal({ monthly, brokers: PESOS, blueMap: BLUE, tcHoy: 1500, valorHoyUsd: 200, moneda: 'ARS' })
    expect(res.ganancia).toBe(300_000)
    expect(res.pct).toBeCloseTo(0.25, 10)
  })

  it('el capital de los plazos fijos (al dólar de hoy) suma igual en las dos monedas', () => {
    const monthly = [
      fila('global', 2025, 2, { deposits: 1000, manual_deposits: 1000 }),
      fila('Cocos', 2025, 2, { deposits: 1000, manual_deposits: 1000, manual_deposits_native: 1_250_000 }),
    ]
    const res = resultadoTotal({ monthly, brokers: PESOS, blueMap: BLUE, tcHoy: 1500, valorHoyUsd: 1200, moneda: 'ARS', extraUsd: 100 })
    expect(res.aportado).toBe(1_250_000 + 150_000)
    expect(res.valor).toBe(1_800_000)
  })

  it('la línea del gráfico: dentro del mes, lo aportado al dólar que tuvieron esos aportes', () => {
    const monthly = [
      fila('global', 2025, 1, { deposits: 1000, manual_deposits: 1000 }),
      fila('Cocos', 2025, 1, { deposits: 1000, manual_deposits: 1000, manual_deposits_native: 1_200_000 }),
      fila('global', 2025, 3, { deposits: 1000, manual_deposits: 1000 }),
      fila('Cocos', 2025, 3, { deposits: 1000, manual_deposits: 1000, manual_deposits_native: 1_250_000 }),
    ]
    const conv = aportadoEnPesosAl({ monthly, brokers: PESOS, blueMap: BLUE, tcHoy: 1500 })
    expect(conv(1000, '2025-02-15')).toBe(1_200_000)            // sin aportes nuevos: lo mismo
    expect(conv(1500, '2025-03-10')).toBe(1_200_000 + 625_000)  // la mitad del aporte de marzo
    expect(conv(2000, '2025-03-31')).toBe(2_450_000)            // al cierre, el acumulado exacto
    expect(conv(2000, '2026-10-15')).toBe(2_450_000)            // y hoy, igual
  })
})

describe('diferenciaDeCambio — el desglose en pesos de quien tiene dólares', () => {
  it('US$ 1.000 depositados con el dólar a 1.200 que hoy valen US$ 1.100 con el dólar a 1.500', () => {
    const monthly = [
      fila('global', 2025, 2, { deposits: 1000, manual_deposits: 1000 }),
      fila('IBKR', 2025, 2, { deposits: 1000, manual_deposits: 1000, manual_deposits_native: 1000 }),
    ]
    const blue = { '2025-02': 1200 }
    const res = resultadoTotal({ monthly, brokers: DOLARES, blueMap: blue, tcHoy: 1500, valorHoyUsd: 1100, moneda: 'ARS' })
    expect(res.aportado).toBe(1_200_000)
    expect(res.ganancia).toBe(450_000)
    // El no realizado del Dashboard en pesos: (valor − costo) al dólar de hoy.
    const noRealizado = (1100 - 1000) * 1500
    const cambio = diferenciaDeCambio({ moneda: 'ARS', ganancia: res.ganancia, realizado: 0, noRealizado, descuadreUsd: 0, tcHoy: 1500 })
    expect(cambio).toBe(300_000)
    expect(noRealizado + cambio).toBe(res.ganancia)   // el desglose suma el título
    // En dólares no existe.
    expect(diferenciaDeCambio({ moneda: 'USD', ganancia: 100, realizado: 0, noRealizado: 100, tcHoy: 1500 })).toBe(0)
  })

  it('la cuenta del caso (todo en pesos) no tiene diferencia de cambio', () => {
    const tc = pickFinancialRate(dolar, 'mep')
    const r = comoElDashboard('ARS')
    const noRealizado = (r.totalValue - r.costoHoyUsd) * tc
    expect(Math.abs(diferenciaDeCambio({ moneda: 'ARS', ganancia: r.resultado.ganancia, realizado: 0, noRealizado, tcHoy: tc }))).toBeLessThan(1)
  })
})

describe('noRealizadoEnVista — el no realizado del Dashboard y el % del inicio del celular', () => {
  const tc = pickFinancialRate(dolar, 'mep')
  const args = { positions, prices, brokers, tcValuacion: tc, tcCedear: tc, tcCripto: dolar?.cripto?.venta, costBasis: 'purchase' }
  it('en pesos: valor de hoy − lo que se pagó en pesos (= la ganancia de la cuenta del caso)', () => {
    const r = noRealizadoEnVista({ ...args, moneda: 'ARS' })
    expect(Math.abs(r.monto - pnlPorActivoEnPesos)).toBeLessThan(1)
    expect(r.pct).toBeCloseTo(pnlPorActivoEnPesos / (DEPOSITO), 2)
  })
  it('en dólares: lo de siempre (valor − costo con el costo elegido)', () => {
    const r = noRealizadoEnVista({ ...args, moneda: 'USD' })
    const v = brokers.map(b => computeBrokerValue(positions, prices, b, tc, tc, dolar?.cripto?.venta, 'purchase'))
    const valor = v.reduce((s, x) => s + x.value, 0), costo = v.reduce((s, x) => s + x.invested, 0)
    expect(r.monto).toBeCloseTo(valor - costo, 8)
    expect(r.pct).toBeCloseTo((valor - costo) / costo, 10)
  })
})
