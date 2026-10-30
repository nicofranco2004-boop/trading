import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// La vista (Pesos/Dólares) la decide el selector global: cada test arma la suya.
const vista = { currency: 'ARS' }
vi.mock('../contexts/CurrencyContext', async (original) => ({
  ...(await original()),
  useCurrency: () => ({ currency: vista.currency, tcValuacion: 1500 }),
}))
vi.mock('../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import { PeriodRow, CurrentPeriodView } from './Reports.jsx'

// La fila de cada mes en Reportes → Mes → "Ver más meses". Escribía el % con
// PUNTO ("+3.25%") mientras la tarjeta que se abre debajo decía "+3,25%": el
// mismo número de dos formas en la misma pantalla.
function fila(delta_pct, delta_usd = 100) {
  const period = {
    period_key: '2026-08', period_label: 'Agosto 2026', is_relevant: true, is_current: false,
    metrics: { delta_pct, delta_usd, basis_incomparable: false },
  }
  return renderToStaticMarkup(<PeriodRow period={period} expanded={false} onToggle={() => {}} />)
}

describe('Reports — la fila del mes', () => {
  it('coma decimal y signo: dos decimales si es chico, uno si es grande', () => {
    expect(fila(3.25)).toContain('>+3,25%<')
    expect(fila(-12.34, -500)).toContain('>−12,3%<')
    expect(fila(3.25)).not.toMatch(/\d\.\d+%/)
  })
  it('lo que se escribe "0,00%" va neutro, no rojo', () => {
    const h = fila(-0.001, -3)
    expect(h).toContain('>0,00%<')
    expect(h).not.toContain('text-rendi-neg')
  })
})

// Con un broker elegido, en Día o Semana, el servidor no publica el % (delta_pct nulo) y pone delta =
// realizado. Comprada a $4.500 con el dólar a 1.000 y vendida a $6.000 con el dólar a 1.500: −US$ 0,5
// en dólares y +$1.500 en pesos. El color del «P&L de la semana» sigue el número que se ve.
describe('Reports — el color del P&L del período sin porcentaje', () => {
  const semana = {
    period_type: 'week', period_key: '2024-W24', period_label: 'Semana 24', period_start: '2024-06-10',
    period_end: '2024-06-16', is_current: false, is_relevant: true, headline: 'Vendiste GGAL',
    metrics: { delta_usd: -0.5, delta_pct: null, realized_pnl: -0.5, realized_ars: 1500, realized_ars_cubre_usd: -0.5,
               unrealized_pnl: 0, trades_count: 1, basis_incomparable: false },
    portfolio_snapshot: {},
  }
  const kpi = (currency) => {
    vista.currency = currency
    const h = renderToStaticMarkup(
      <MemoryRouter><CurrentPeriodView period={semana} loading={false} tab="week" broker="IOL" /></MemoryRouter>)
    // La celda «P&L de la semana» y nada más (hasta el rótulo siguiente).
    const desde = h.indexOf('P&amp;L de la semana')
    return h.slice(desde, h.indexOf('P&amp;L realizado'))
  }
  it('en Pesos, +$1.500 va en verde aunque en dólares sea una pérdida', () => {
    const c = kpi('ARS')
    expect(c).toContain('1.500')
    expect(c).toContain('text-rendi-pos')
    expect(c).not.toContain('text-rendi-neg')
  })
  it('en Dólares, la pérdida va en rojo', () => {
    expect(kpi('USD')).toContain('text-rendi-neg')
  })
})

