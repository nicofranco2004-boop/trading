import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import InsightsKpiStrip from './InsightsKpiStrip.jsx'

// La tira de arriba de Análisis. Se dibuja de verdad y se lee el texto, porque
// el bug estaba en la unión de dos lugares: el formateador local devolvía
// `p.toFixed(1)` —con PUNTO— y el "%" se pegaba recién en el JSX. Ningún grep
// de "toFixed(...)%" lo veía, y el usuario leía "+16.9%" al lado de "US$ 1.037,74".
function texto(el) {
  return renderToStaticMarkup(el).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
}

const base = {
  diagnosis: [],
  assetPieData: [{ name: 'NVDA', value: 6246 }, { name: 'AAPL', value: 3754 }],
  drawdownTwrr: { currentPct: -12.34, maxPct: -45.06 },
  winRate: { pct: 62.5, total: 8 },
  cumulativeReturnPct: 16.94,
  benchmarkReturnPct: -3.21,
  benchmarkLabel: 'S&P 500',
  ventanaMeses: 12,
}

describe('InsightsKpiStrip — los porcentajes se leen a la argentina', () => {
  const t = texto(<InsightsKpiStrip {...base} />)

  it('acumulado con signo y coma: "+16,9%", no "+16.9%"', () => {
    expect(t).toContain('+16,9%')
    expect(t).not.toContain('16.9')
  })
  it('el benchmark del mismo período, con el menos tipográfico', () => {
    expect(t).toContain('vs S&amp;P 500: −3,2% · mismo período')
  })
  it('drawdown actual y el pico, sin "+" y con coma', () => {
    expect(t).toContain('−12,3%')
    expect(t).toContain('peak histórico −45,1%')
    expect(t).not.toMatch(/\d\.\d%/)
  })
  it('concentración y win rate, enteros', () => {
    expect(t).toContain('62%')     // 6246 / 10000
    expect(t).toContain('63%')     // win rate 62,5 → 63, como toFixed(0)
  })
  it('un acumulado que se escribe "0,0%" no se pinta de rojo', () => {
    // −0,03 se ve como "0,0%": rojo diría "perdiste" al lado de un cero.
    const html = renderToStaticMarkup(<InsightsKpiStrip {...base} cumulativeReturnPct={-0.03} />)
    const celda = html.slice(html.indexOf('Acumulado'), html.indexOf('mismo período'))
    expect(celda).toContain('>0,0%<')
    expect(celda).not.toContain('text-rendi-neg')
  })
  it('sin dato, guión', () => {
    const v = texto(<InsightsKpiStrip {...base} cumulativeReturnPct={null} drawdownTwrr={null} />)
    expect(v).toContain('Drawdown actual —')
  })
})
