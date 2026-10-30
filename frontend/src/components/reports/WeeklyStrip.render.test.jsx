import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// La vista (Pesos/Dólares) la decide el selector global: cada test arma la suya.
const vista = { currency: 'USD' }
vi.mock('../../contexts/CurrencyContext', async (original) => ({
  ...(await original()),
  useCurrency: () => ({ currency: vista.currency, tcValuacion: 1500 }),
}))
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import WeeklyStrip from './WeeklyStrip.jsx'

// La tira semanal ubica la línea del cero y sus marcas con `top`/`bottom` en %.
// Esos números los lee el NAVEGADOR, no una persona: van con PUNTO. Desde el
// barrido de separadores del 2026-09-15 iban con coma ("42,50%"), que para CSS
// no es una medida: el navegador descarta la declaración sin avisar y la línea
// del cero quedaba arriba de todo, sin importar dónde estaba el cero.
function semana(clave, inicio, fin, delta_pct, delta_usd) {
  return {
    period_type: 'week', period_key: clave, period_label: `Semana ${clave.slice(-2)}`,
    period_start: inicio, period_end: fin, is_current: false, is_relevant: true,
    metrics: { delta_usd, delta_pct, realized_pnl: 0, unrealized_pnl: 0, trades_count: 0, basis_incomparable: false },
  }
}
const yearGroups = [{ year: 2026, months: [{ children: [
  semana('2026-W36', '2026-08-31', '2026-09-06', 1.7, 170),
  semana('2026-W37', '2026-09-07', '2026-09-13', -0.6, -60),
  semana('2026-W38', '2026-09-14', '2026-09-20', 2.3, 230),
] }] }]

describe('WeeklyStrip — las posiciones de la tira son CSS válido', () => {
  const html = renderToStaticMarkup(<WeeklyStrip yearGroups={yearGroups} />)
  const medidas = [...html.matchAll(/(top|bottom):([^;"]+)/g)].map(m => `${m[1]}:${m[2]}`)

  it('hay posiciones en % (si no, el test no estaría mirando nada)', () => {
    expect(medidas.some(m => /%$/.test(m))).toBe(true)
  })
  it('ninguna lleva coma decimal', () => {
    expect(medidas.filter(m => /\d,\d/.test(m))).toEqual([])
  })
})

// GGAL comprada a $4.500 (dólar 1.000) y vendida a $6.900 (dólar 1.500): +$240.000 y +US$ 10.
// La tarjeta de la semana (WeekCard) dice $240.000; la tira decía $15.000 (US$ 10 × 1.500).
describe('WeeklyStrip — en Pesos, lo cerrado es lo mismo que dice la tarjeta de la semana', () => {
  const ggal = [{ year: 2024, months: [{ children: [{
    period_type: 'week', period_key: '2024-W24', period_label: 'Semana 24',
    period_start: '2024-06-10', period_end: '2024-06-16', is_current: false, is_relevant: true,
    metrics: { delta_usd: 10, delta_pct: 0.5, realized_pnl: 10, unrealized_pnl: 0, trades_count: 1,
               basis_incomparable: false, realized_ars: 240000, realized_ars_cubre_usd: 10 },
  }] }] }]
  const render = (currency) => {
    vista.currency = currency
    return renderToStaticMarkup(<WeeklyStrip yearGroups={ggal} />)
  }

  it('en Pesos muestra los $240.000 de las ventas, no los $15.000 de dólares × dólar', () => {
    const html = render('ARS')
    expect(html).toContain('240.000')
    expect(html).not.toContain('15.000')
  })
  it('en Dólares no cambia: US$ 10', () => {
    const html = render('USD')
    expect(html).toMatch(/US\$\s?10\b/)
    expect(html).not.toContain('240.000')
  })
})
