import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// La vista (Pesos/Dólares) la decide el selector global: cada test arma la suya.
const vista = { currency: 'ARS' }
vi.mock('../../contexts/CurrencyContext', async (original) => ({
  ...(await original()),
  useCurrency: () => ({ currency: vista.currency, tcValuacion: 1500 }),
}))
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import MonthCard from './MonthCard.jsx'

// El encabezado de la tarjeta grande de un período (la que se abre desde «Ver detalle técnico»). En Pesos el
// % de un día o una semana sigue en DÓLARES (el servidor sólo pasa a pesos el de mes y año): se rotula, igual
// que en la fila y en el encabezado de Reportes. Quinta auditoría: esta tarjeta no tenía ninguna prueba.
const periodo = (tipo, metrics = {}) => ({
  period_type: tipo, period_key: tipo === 'week' ? '2024-W24' : '2024-06', period_label: 'Período',
  period_start: '2024-06-10', period_end: tipo === 'week' ? '2024-06-16' : '2024-06-30', is_current: false,
  is_relevant: true, headline: 'x',
  metrics: { start_value: 100000, end_value: 99800, delta_usd: -200, delta_pct: -0.2, realized_pnl: 0,
    unrealized_pnl: -200, deposits: 0, withdrawals: 0, trades_count: 0, basis_incomparable: false,
    medicion: 'mercado', puntas_desde: '2024-06-07', puntas_hasta: '2024-06-16', moneda: 'ars', ...metrics },
  portfolio_snapshot: {},
})
const render = (currency, p) => {
  vista.currency = currency
  return renderToStaticMarkup(<MemoryRouter><MonthCard period={p} defaultExpanded /></MemoryRouter>)
}

describe('MonthCard — el % de un día o una semana en Pesos dice que es en dólares', () => {
  it('semana en Pesos: «en US$» al lado del %', () => {
    expect(render('ARS', periodo('week'))).toContain('en US$')
  })
  it('en Dólares no hay rótulo: un solo idioma', () => {
    expect(render('USD', periodo('week'))).not.toContain('en US$')
  })
  it('un mes en Pesos del servidor (moneda ars) no lo rotula: su % ya está en pesos', () => {
    expect(render('ARS', periodo('month'))).not.toContain('en US$')
  })
  it('un mes que llega con el % en dólares (la demo o un servidor anterior) sí lo rotula', () => {
    expect(render('ARS', periodo('month', { moneda: 'usd' }))).toContain('en US$')
  })
})
