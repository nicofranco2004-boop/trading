import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import AIBlocks from './AIBlocks'

// Los gráficos de una respuesta de Rendi AI se arman sólo si la respuesta
// ACABA de llegar (animarDesde != null); una vieja aparece quieta.
const bloques = [
  { type: 'compare', title: 'Vos vs S&P', items: [{ l: 'Vos', v: '+8,8%', pct: 88 }, { l: 'S&P 500', v: '+8,0%', pct: 80 }] },
  { type: 'alloc', title: 'Composición', items: [{ l: 'BTC', pct: 40 }, { l: 'NVDA', pct: 35 }, { l: 'Otros', pct: 25 }] },
  { type: 'client_list', title: 'Tus clientes', items: [{ l: 'Martín', v: 'US$ 800.000' }, { l: 'Lucía', v: 'US$ 600.000' }] },
]
const dibujar = props => renderToStaticMarkup(<MemoryRouter><AIBlocks blocks={bloques} {...props} /></MemoryRouter>)
const cuantas = (html, clase) => (html.match(new RegExp(clase, 'g')) || []).length

describe('AIBlocks — respuesta recién llegada', () => {
  it('los bloques entran en escalera desde el turno que les toca', () => {
    const html = dibujar({ animarDesde: 3 })
    expect(cuantas(html, '"entra"')).toBe(3)
    expect(html).toContain('--i:3')
    expect(html).toContain('--i:5')
  })
  it('las barras crecen, en "Comparación" Y en "Tus clientes" (antes nacían llenas)', () => {
    expect(cuantas(dibujar({ animarDesde: 0 }), 'crece-ancho')).toBe(4)
  })
  it('la torta aparece por porciones', () => {
    expect(cuantas(dibujar({ animarDesde: 0 }), 'porcion-aparece')).toBe(3)
  })
  it('una respuesta vieja: nada se mueve', () => {
    const html = dibujar({})
    for (const c of ['"entra"', 'crece-ancho', 'porcion-aparece']) expect(cuantas(html, c)).toBe(0)
  })
})
