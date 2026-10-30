import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// La vista (Pesos/Dólares) la decide el selector global: cada test arma la suya.
const vista = { currency: 'USD' }
vi.mock('../../contexts/CurrencyContext', async (original) => {
  const real = await original()
  return {
    ...real,
    useCurrency: () => ({ currency: vista.currency, tcValuacion: 1500 }),
    // `useMoneyFormat` llama a su propio `useCurrency` (no al exportado): se arma acá con el mismo selector.
    useMoneyFormat: () => {
      const isArs = vista.currency === 'ARS'
      return { currency: vista.currency, tcValuacion: 1500, isArs,
               fmtMoney: (v) => real.fmtConvertedRaw(isArs ? v * 1500 : v, vista.currency) }
    },
  }
})
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import InsightEvidence from './InsightEvidence.jsx'
import { PeriodoEnVista } from '../../hooks/usePesosDelPeriodo'
import { crearPesosDelPeriodo } from '../../utils/periodoEnPesos'

// La evidencia va abajo del texto del insight, que lo escribe el SERVIDOR
// (reporting/detectors.py: `fmt_num(delta_pct, 1, signed=True)`). Los dos
// tienen que decir la misma cifra. Python escribe fmt_num(19.95, 1) → "19,9"
// (medido 2026-10-01); con el redondeo de toLocaleString la pantalla decía
// "+20,0%" justo abajo de "Tu portfolio: +19,9%".
function html(insight) {
  return renderToStaticMarkup(<InsightEvidence insight={insight} />)
}
const texto = (h) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

describe('InsightEvidence — la misma cifra que el texto del servidor', () => {
  it('cartera y S&P con el redondeo del backend', () => {
    const t = texto(html({ code: 'BEAT_BENCHMARK', evidence: { type: 'metric', portfolio: 19.95, sp500: 2.15 } }))
    expect(t).toContain('Cartera +19,9%')
    expect(t).toContain('S&amp;P 500 +2,1%')
  })
  it('una cartera que se escribe "0,0%" no va en rojo', () => {
    const h = html({ code: 'UNDERPERFORM_BENCHMARK', evidence: { type: 'metric', portfolio: -0.04, sp500: 3.2 } })
    const celda = h.slice(h.indexOf('Cartera'), h.indexOf('S&amp;P'))
    expect(celda).toContain('>0,0%<')
    expect(celda).not.toContain('text-rendi-neg')
  })
  it('las porciones sin "+", con coma', () => {
    const t = texto(html({ code: 'LARGE_CASH_DRAG', evidence: { type: 'metric', cash_usd: 5000, cash_pct: 35.2 } }))
    expect(t).toContain('35,2% de la cartera total')
  })
})

// ─── Dentro de una tarjeta de período, en Pesos ──────────────────────────────────────────────────
// GGAL comprada a $4.500 (dólar 1.000) y vendida a $6.900 (dólar 1.500) en un mes con un aporte de
// US$ 1.000: +$240.000 y +US$ 10 (sin nada abierto, sin saldo previo).
describe('InsightEvidence — en Pesos, dentro de la tarjeta del período', () => {
  const periodo = {
    period_type: 'month', period_start: '2024-06-01', period_end: '2024-06-30', is_current: false,
    metrics: { deposits: 1000, withdrawals: 0, delta_usd: 10, realized_pnl: 10, realized_ars: 240000,
               realized_ars_cubre_usd: 10, unrealized_pnl: 0 },
  }
  const enTarjeta = (currency, insight, p = periodo) => {
    vista.currency = currency
    const pesos = crearPesosDelPeriodo({ moneda: currency, tcHoy: 1500, tcEnFecha: () => 1500, dolarMes: {}, monthly: [], brokers: [] })
    return texto(renderToStaticMarkup(
      <PeriodoEnVista.Provider value={pesos.enVista(p)}><InsightEvidence insight={insight} /></PeriodoEnVista.Provider>))
  }
  const aportes = { code: 'DEPOSITS_DRIVE_GROWTH', evidence: { type: 'deposits', deposits: 1000, market_growth: 10 } }
  const driver = { code: 'DRIVER_OF_PERIOD', evidence: { type: 'driver', asset: 'GGAL', pnl: 10 } }

  it('«Mercado» del hallazgo de aportes es el MISMO resultado que muestra la cabecera de la tarjeta', () => {
    const t = enTarjeta('ARS', aportes)
    expect(t).toContain('Mercado $240.000')
    expect(t).not.toContain('$15.000')    // los US$ 10 × 1.500
  })
  it('y «Aportaste» sigue en los pesos de los depósitos', () => {
    expect(enTarjeta('ARS', aportes)).toContain('Aportaste $1.500.000')
  })
  it('un mercado que perdió: el signo es el del resultado en pesos', () => {
    const t = enTarjeta('ARS', aportes, { ...periodo, metrics: { ...periodo.metrics, delta_usd: -130, realized_pnl: -130,
      realized_ars: 30000, realized_ars_cubre_usd: -130 } })
    expect(t).toContain('Mercado $30.000')
  })
  it('en Dólares: los dólares del servidor', () => {
    expect(enTarjeta('USD', aportes)).toMatch(/Mercado US\$\s?10\b/)
  })

  it('los mini-cuadros en dólares pasados al dólar avisan que no son los pesos exactos', () => {
    const t = enTarjeta('ARS', driver)
    expect(t).toContain('Estos montos son dólares multiplicados por el dólar del cierre')
    expect(t).toContain('usa los pesos exactos de tus ventas en pesos')
  })
  it('en Dólares no hay aviso', () => {
    expect(enTarjeta('USD', driver)).not.toContain('dólares multiplicados')
  })
  it('suelta (sin tarjeta de período) tampoco', () => {
    vista.currency = 'ARS'
    expect(texto(html(driver))).not.toContain('dólares multiplicados')
  })
})

