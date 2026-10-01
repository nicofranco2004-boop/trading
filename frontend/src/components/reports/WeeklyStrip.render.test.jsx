import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
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
