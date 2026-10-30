import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// La vista (Pesos/Dólares) la decide el selector global: cada test arma la suya.
const vista = { currency: 'ARS' }
vi.mock('../../contexts/CurrencyContext', async (original) => ({
  ...(await original()),
  useCurrency: () => ({ currency: vista.currency, tcValuacion: 1500 }),
}))
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import WeekCard from './WeekCard.jsx'

// GGAL comprada a $4.500 (dólar 1.000) y vendida a $6.900 (dólar 1.500): +$240.000 y +US$ 10.
// El resultado de la semana, sin nada abierto, es lo que se vendió: la tarjeta no puede decir
// «resultado +$15.000» (dólares × dólar) y, adentro, «realizado +$240.000».
const semana = {
  period_type: 'week', period_key: '2024-W24', period_label: 'Semana 24', period_start: '2024-06-10',
  period_end: '2024-06-16', is_current: false, is_relevant: true, headline: 'Vendiste GGAL',
  metrics: { delta_usd: 10, delta_pct: 0.5, realized_pnl: 10, unrealized_pnl: 0, trades_count: 1,
             basis_incomparable: false, realized_ars: 240000, realized_ars_cubre_usd: 10 },
}
const render = (currency, week = semana) => {
  vista.currency = currency
  return renderToStaticMarkup(<WeekCard week={week} />)
}

describe('WeekCard — el resultado de la semana contiene al realizado', () => {
  it('en Pesos el resultado de la cabecera es el de las ventas en pesos', () => {
    const html = render('ARS')
    expect(html).toContain('240.000')
    expect(html).not.toContain('15.000')
  })
  it('en Dólares no cambia', () => {
    const html = render('USD')
    expect(html).toMatch(/US\$\s?10\b/)
    expect(html).not.toContain('240.000')
  })
  it('una semana de pérdida en dólares y ganancia en pesos: el resultado es el de los pesos', () => {
    const html = render('ARS', { ...semana, metrics: { ...semana.metrics, delta_usd: -130,
      realized_pnl: -130, realized_ars: 30000, realized_ars_cubre_usd: -130 } })
    expect(html).toContain('30.000')
    expect(html).not.toContain('195.000')
  })
})
