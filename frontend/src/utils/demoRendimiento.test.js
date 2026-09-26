/**
 * La demo pública (`?demo=1`) no puede contradecirse en la misma pantalla.
 *
 * Mismo camino que producción: en modo demo `api.get(path)` devuelve
 * `handleDemoRequest('GET', path)` tal cual (utils/api.js), y el Dashboard valúa
 * la cartera con `computeBrokerValue` sobre esas posiciones y precios. Este test
 * hace exactamente eso y después le pide los números a las MISMAS funciones que
 * usa la pantalla. Corre con el reloj de verdad, como la demo.
 *
 * El caso que lo motiva (2026-09-25): "−USD 26.791,78 · −64,9 % en el mes" al
 * lado de "Ganancia total +USD 5.916,82". La "foto de hoy" del demo valía el
 * saldo de BINANCE (US$ 14.517), no la cartera: ver rendimientoDelRango.test.js.
 */
import { describe, it, expect, vi } from 'vitest'
import { handleDemoRequest } from './demo.js'
import { buildPriceSymbols, computeBrokerValue } from './valuation.js'
import { pickFinancialRate } from '../contexts/CurrencyContext.jsx'
import { RANGES } from '../components/RangeTabs.jsx'
import { hoyISO } from './fecha.js'
import {
  buildPortfolioValueSeries,
  capitalMaximoAportado,
  computeDailyPnl,
  computeReturnDelta,
  rendimientoDelRango,
  retornoTotal,
} from './evolution.js'

const get = (path) => handleDemoRequest('GET', path)

// El Dashboard, línea por línea (Dashboard.jsx: loadAll → loadPrices →
// brokerTotals → totalValuePositions / netDepositedPositions). La demo no tiene
// plazos fijos, así que "positions" = total.
function dashboardDemo() {
  const positions = get('/positions')
  const brokers = get('/brokers')
  const dolar = get('/dolar')
  const config = get('/config')
  const monthly = get('/monthly')
  const snapshots = get('/snapshots?days=3650')
  const prices = get(`/prices?symbols=${buildPriceSymbols(positions, brokers).join(',')}`)
  const tcValuacion = pickFinancialRate(dolar, 'mep') || config.tc_blue || 1415
  const tcCedear = pickFinancialRate(dolar, 'mep') || tcValuacion
  const tcCripto = dolar?.cripto?.venta
  const valor = brokers
    .map(b => computeBrokerValue(positions, prices, b, tcValuacion, tcCedear, tcCripto, 'today'))
    .reduce((s, b) => s + b.value, 0)
  const globals = monthly
    .filter(m => m.broker === 'global')
    .sort((a, b) => (a.year !== b.year ? a.year - b.year : a.month - b.month))
  const aportado = (globals[0]?.capital_inicio || 0)
    + globals.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)
  const gananciaTotal = retornoTotal({
    totalValue: valor, netDeposited: aportado, capitalMaximo: capitalMaximoAportado(snapshots, aportado, 0),
  })
  return { snapshots, globals, valor, aportado, gananciaTotal }
}

describe('demo: el chip del gráfico y el resto del Dashboard cuentan la misma cartera', () => {
  const d = dashboardDemo()

  it('EL ESLABÓN ROTO: la foto de hoy del demo es la cartera entera, no un broker', () => {
    const hoy = d.snapshots.find(s => s.date === hoyISO())
    expect(hoy, 'el demo no trae la foto de hoy').toBeTruthy()
    // Antes: 14.517 (Binance) contra ~41.400. Queda una diferencia chica y
    // conocida: el fixture escala con el blue 1.415 y la pantalla valúa al MEP.
    expect(Math.abs(hoy.total_value / d.valor - 1)).toBeLessThan(0.02)
    // Y está marcada como lo que es en producción: la foto de media rueda que el
    // Dashboard escribe en la primera visita, no un cierre.
    expect(hoy.clase).toBe('intradia')
    expect(hoy.apto).toBe(false)
  })

  it('el chip de 1M ya no publica el −64,9 %', () => {
    const r = rendimientoDelRango(d.snapshots, { dias: 30, liveValue: d.valor, liveNetDeposited: d.aportado })
    expect(r).not.toBeNull()
    expect(Math.abs(r.pct)).toBeLessThan(0.15)
  })

  it('todos los rangos del selector tienen número y un rótulo exacto (un cierre por día, como el cron)', () => {
    for (const rango of RANGES) {
      const r = rendimientoDelRango(d.snapshots, {
        dias: rango.days, liveValue: d.valor, liveNetDeposited: d.aportado, gananciaTotal: d.gananciaTotal,
      })
      expect(r, `sin número en ${rango.id}`).not.toBeNull()
      expect(r.desde, `${rango.id} tuvo que rotular "desde"`).toBeNull()
    }
  })

  it('MAX es la "Ganancia total" del título (antes: +66 % contra +51 %)', () => {
    const r = rendimientoDelRango(d.snapshots, { dias: null, liveValue: d.valor, liveNetDeposited: d.aportado, gananciaTotal: d.gananciaTotal })
    expect(r.usd).toBe(d.gananciaTotal.usd)
    expect(r.pct).toBe(d.gananciaTotal.pct)
  })

  it('"Hoy" mide un día y "Este mes" tiene número (antes: "Últimos 3 días" y "—")', () => {
    const hoy = computeDailyPnl(d.snapshots, { liveValue: d.valor, liveNetDeposited: d.aportado })
    expect(hoy.dayDiff).toBe(1)
    const n = new Date()
    const inicioMes = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-01`
    const mes = computeReturnDelta(d.snapshots, { liveValue: d.valor, liveNetDeposited: d.aportado, sinceDate: inicioMes })
    expect(mes).not.toBeNull()
  })

  it('la curva termina en el mismo valor que el título', () => {
    const serie = buildPortfolioValueSeries(d.snapshots, 30, d.valor, d.aportado)
    expect(serie[serie.length - 1].valueUsd).toBe(d.valor)
  })

  it('los cierres de mes de la curva coinciden con la cadena mensual', () => {
    // La curva y /mensual del demo cuentan la misma historia: el cierre del
    // último día de cada mes ES el capital_final de ese mes.
    for (const m of d.globals.slice(0, -1)) {
      const ultimo = new Date(m.year, m.month, 0).getDate()
      const fecha = `${m.year}-${String(m.month).padStart(2, '0')}-${String(ultimo).padStart(2, '0')}`
      const fila = d.snapshots.find(s => s.date === fecha)
      expect(fila, `falta el cierre del ${fecha}`).toBeTruthy()
      expect(fila.total_value).toBeCloseTo(m.capital_final, 2)
    }
  })

  it('los meses del demo son consecutivos (en hora argentina se salteaba abril de 2024)', () => {
    for (let i = 1; i < d.globals.length; i++) {
      const a = d.globals[i - 1], b = d.globals[i]
      expect((b.year * 12 + b.month) - (a.year * 12 + a.month), `${a.year}-${a.month} → ${b.year}-${b.month}`).toBe(1)
    }
  })

  it('Reportes del demo: el capital de hoy es la cartera y el aportado no se cuenta dos veces', () => {
    const snap = get(`/reports/period/year/${new Date().getFullYear()}`).portfolio_snapshot
    expect(Math.abs(snap.latest_value / d.valor - 1)).toBeLessThan(0.02)
    // Antes sumaba los aportes de TODAS las filas (el total + cada broker) y el
    // tope lo ponía el valor de Binance.
    expect(snap.cum_deposited).toBeLessThanOrEqual(d.aportado + 1)
    expect(Math.abs(snap.delta_30d.pct)).toBeLessThan(15)
  })

  it('Reportes del demo: el YTD y el "P&L del año" de la misma tarjeta son el mismo número', () => {
    // Antes el YTD restaba valores a secas (los aportes contaban como ganancia):
    // "YTD +24,71 %" al lado de "P&L del año +10,85 %".
    const anio = get(`/reports/period/year/${new Date().getFullYear()}`)
    const ytd = anio.portfolio_snapshot.ytd
    expect(Math.abs(ytd.usd - anio.metrics.delta_usd)).toBeLessThanOrEqual(1)
    expect(Math.abs(ytd.pct - anio.metrics.delta_pct)).toBeLessThan(0.05)
  })
})

describe('demo: el 1° del mes, "Hoy" no carga el mes entero', () => {
  it('a las 10 de la mañana del 1° de octubre, el día se mueve como un día', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 9, 1, 10, 0))
    try {
      vi.resetModules()
      const demo = await import('./demo.js')
      const ev = await import('./evolution.js')
      const snaps = demo.handleDemoRequest('GET', '/snapshots?days=3650')
      const monthly = demo.handleDemoRequest('GET', '/monthly')
      const g = monthly.filter(m => m.broker === 'global')
      const aportado = g[0].capital_inicio + g.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)
      const hoy = snaps.find(s => s.date === '2026-10-01')
      const r = ev.computeDailyPnl(snaps, { liveValue: hoy.total_value, liveNetDeposited: aportado })
      // Antes: el mes simulado entero en un día (+3,9 % en un caso medido).
      expect(Math.abs(r.pct)).toBeLessThan(0.006)
    } finally {
      vi.useRealTimers()
    }
  })
})
