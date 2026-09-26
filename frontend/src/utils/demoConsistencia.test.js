/**
 * La demo cuenta UNA cartera, la misma en cada pantalla y en cada carga.
 *
 * El audit del 2026-09-25 midió, sobre 60-80 cargas de la demo:
 *   · una tarjeta "Dividendos e intereses" de US$ 1.700–6.900 que no existía,
 *     porque los aportes y el realizado eran azar y no cerraban con la cartera;
 *   · tres historias de operaciones: el Dashboard (azar), Movimientos (14 viejas)
 *     y Reportes ("2026: 46 operaciones cerradas", azar);
 *   · "Ganancia total" entre 16 % y 76 % según la recarga;
 *   · la IA diciendo "45 % en efectivo" y "NVDA pesa 28 %" con 5 % y 15 %;
 *   · Diagnóstico con "Sin mediciones todavía" al lado de 30 meses de curva;
 *   · el Mercado con NVDA +4,4 % y la Cartera con NVDA −0,29 % el mismo día.
 * Mismo camino que producción: en modo demo `api.get(path)` devuelve
 * `handleDemoRequest('GET', path)`, y la pantalla valúa con `computeBrokerValue`.
 */
import { describe, it, expect, vi } from 'vitest'
import { handleDemoRequest } from './demo.js'
import { buildPriceSymbols, computeBrokerValue } from './valuation.js'
import { computeDailyPnl } from './evolution.js'
import { hoyISO } from './fecha.js'

const get = (p) => handleDemoRequest('GET', p)

function pantalla() {
  const positions = get('/positions')
  const brokers = get('/brokers')
  const dolar = get('/dolar')
  const prices = get(`/prices?symbols=${buildPriceSymbols(positions, brokers).join(',')}`)
  const prev = get(`/prices/prev-close?symbols=${buildPriceSymbols(positions, brokers).join(',')}`)
  const tc = dolar.mep.venta
  const val = (precios) => brokers.map(b => computeBrokerValue(positions, precios, b, tc, tc, dolar.cripto.venta, 'purchase'))
  const hoy = val(prices)
  const valor = hoy.reduce((s, b) => s + b.value, 0)
  const costo = hoy.reduce((s, b) => s + b.invested, 0)
  const valorAyer = val({ ...prices, ...prev }).reduce((s, b) => s + b.value, 0)
  const g = get('/monthly').filter(m => m.broker === 'global')
  const aportado = g[0].capital_inicio + g.reduce((s, m) => s + m.deposits - m.withdrawals, 0)
  const realizado = g.reduce((s, m) => s + m.pnl_realized, 0)
  return { valor, costo, valorAyer, aportado, realizado, snapshots: get('/snapshots?days=3650') }
}

describe('la demo cierra y no cambia', () => {
  const d = pantalla()

  it('NO HAY "Dividendos e intereses" inventados: aportado + realizado = costo de hoy', () => {
    // La cuenta que hace el Dashboard: (realizado + no realizado) − ganancia total.
    const brecha = (d.realizado + (d.valor - d.costo)) - (d.valor - d.aportado)
    expect(Math.abs(brecha)).toBeLessThan(1)
  })

  it('el realizado del Dashboard es el de las operaciones de Movimientos', () => {
    const ops = get('/operations')
    expect(d.realizado).toBeCloseTo(ops.reduce((s, o) => s + o.pnl_usd, 0), 1)
    const movs = get('/movements').filter(m => m.type === 'SELL')
    expect(movs).toHaveLength(ops.length)
  })

  it('Reportes cuenta las mismas operaciones que Movimientos, año por año', () => {
    const ops = get('/operations')
    const anio = new Date().getFullYear()
    for (const y of [anio - 1, anio]) {
      const r = get(`/reports/period/year/${y}`)
      if (!r.metrics || r.metrics.trades_count == null) continue
      const delAnio = ops.filter(o => o.date.startsWith(`${y}-`))
      expect(r.metrics.trades_count, `año ${y}`).toBe(delAnio.length)
    }
  })

  it('hay operaciones en los últimos 12 meses (antes la última era de mayo de 2025)', () => {
    const hace12 = new Date()
    hace12.setFullYear(hace12.getFullYear() - 1)
    const iso = hace12.toISOString().slice(0, 10)
    expect(get('/operations').filter(o => o.date >= iso).length).toBeGreaterThan(3)
  })

  it('"Hoy" es la suma de la variación del día de cada posición (la misma que el Mercado)', () => {
    const hoy = computeDailyPnl(d.snapshots, { liveValue: d.valor, liveNetDeposited: d.aportado })
    const dia = new Date().getDate()
    if (dia === 1) return   // el 1° el cierre de ayer es el cierre del mes anterior
    expect(hoy.usd).toBeCloseTo(d.valor - d.valorAyer, 0)
    expect(get('/prices/prev-close?symbols=NVDA').NVDA).toBeCloseTo(178.5 / 1.044, 1)
  })

  it('dos cargas dan exactamente los mismos números (antes, "Ganancia total" 16–76 %)', async () => {
    vi.resetModules()
    const otra = await import('./demo.js')
    const a = otra.handleDemoRequest('GET', '/monthly')
    expect(a).toEqual(get('/monthly'))
    expect(otra.handleDemoRequest('GET', '/snapshots?days=3650')).toEqual(d.snapshots)
    expect(otra.handleDemoRequest('GET', `/reports/period/day/${hoyISO()}`).metrics)
      .toEqual(get(`/reports/period/day/${hoyISO()}`).metrics)
  })
})

describe('las pantallas de análisis del demo tienen datos y dicen la verdad', () => {
  it('Diagnóstico → Performance tiene curva y rendimiento', () => {
    const p = get('/insights/performance?bench=sp500&modo=certero')
    expect(p.curva.length).toBeGreaterThan(100)
    expect(p.twr).not.toBeNull()
    expect(p.benchmark).toHaveLength(p.curva.length)
    expect(p.motivo).toBeNull()
  })

  it('la respuesta del chat usa los números de la cartera', () => {
    const r = handleDemoRequest('POST', '/ai/chat', { messages: [{ role: 'user', content: 'cómo vengo' }] }).reply
    expect(r).not.toMatch(/45\s?%|41\.416|NVDA \(28/)
    expect(r).toMatch(/INTC/)
  })

  it('ningún análisis enlatado deja un {{MARCADOR}} sin completar ni una cartera de "US$ 8.3K"', () => {
    for (const screen of ['dashboard', 'insights', 'reports', 'positions', 'operations', 'events', 'home', 'news']) {
      const r = handleDemoRequest('POST', '/ai/analyze', { screen })
      const txt = JSON.stringify(r.result)
      expect(txt, screen).not.toMatch(/\{\{[A-Z_0-9]+\}\}/)
      expect(txt, screen).not.toMatch(/8\.3K|US\$ 22[.,]?300/)
    }
  })

  it('Comportamiento: el win rate y el efectivo son los de la cartera', () => {
    const b = get('/behavioral/insights')
    const ops = get('/operations')
    const wr = b.cards.find(c => c.code === 'winrate_payoff').evidence
    expect(wr.total_trades).toBe(ops.length)
    expect(wr.winners_count).toBe(ops.filter(o => o.pnl_usd > 0).length)
    const cash = b.cards.find(c => c.code === 'cash_drag').evidence
    expect(cash.total_usd).toBeGreaterThan(30_000)
    expect(b.summary.total_medium).toBe(b.cards.filter(c => c.severity === 'medium').length)
  })

  it('el objetivo no se contradice: los meses del encabezado son los del diagnóstico', () => {
    const [meta] = get('/goals')
    const diag = get('/goals/1/diagnostic')
    expect(diag.months_left).toBe(36)
    expect(diag.eta_months_at_current_rate).toBeLessThanOrEqual(36)
    expect(diag.projected_value_at_target_date).toBeGreaterThanOrEqual(meta.target_usd)
  })

  it('ninguna fecha de "próximo reporte" está en el pasado', () => {
    const r = get('/events/earnings-expectations?ticker=NVDA')
    expect(r.next_earnings_date >= hoyISO()).toBe(true)
  })
})
