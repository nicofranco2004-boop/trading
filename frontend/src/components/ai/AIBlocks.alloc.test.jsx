// La torta de composición de Rendi AI: la rampa violeta de toda composición,
// y "Otros" al final y en gris aunque sea la porción más grande.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import AIBlocks from './AIBlocks.jsx'
import { MONO_VIOLET, PORCION_RESTO, porcionColor } from '../../utils/chartTheme'

const html = (items) => renderToStaticMarkup(
  <MemoryRouter><AIBlocks blocks={[{ type: 'alloc', items }]} /></MemoryRouter>)

// Tal cual lo manda el demo (y a veces el modelo): "Otros" es el 53%.
const DEMO = [
  { l: 'Otros', pct: 53 }, { l: 'BTC', pct: 17 }, { l: 'NVDA', pct: 15 },
  { l: 'AAPL', pct: 10 }, { l: 'Efectivo', pct: 5 },
]

describe('torta de composición de Rendi AI', () => {
  it('el titular del centro es el activo más grande, no "Otros"', () => {
    const h = html(DEMO)
    const centro = [...h.matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map(m => m[1])
    expect(centro).toEqual(['17%', 'BTC'])
  })

  it('"Otros" va último en la leyenda y pintado con el gris del resto', () => {
    const h = html(DEMO)
    expect(h.indexOf('>Otros<')).toBeGreaterThan(h.indexOf('>Efectivo<'))
    expect(h).toContain(`stroke="${PORCION_RESTO}"`)
  })

  it('los activos van con la rampa violeta en orden de peso — nunca el verde de ganancia', () => {
    const h = html(DEMO)
    expect(h).toContain(`stroke="${MONO_VIOLET[0]}"`)   // BTC, el mayor real
    expect(h).not.toMatch(/rendi-pos|rendi-neg/)
  })

  it('porcionColor: 5 pasos de la rampa y del sexto en adelante el gris', () => {
    expect([0, 1, 2, 3, 4].map(porcionColor)).toEqual([...MONO_VIOLET])
    expect(porcionColor(5)).toBe(PORCION_RESTO)
    expect(porcionColor(9)).toBe(PORCION_RESTO)
  })
})
