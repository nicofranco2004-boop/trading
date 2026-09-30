import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// La cinta de cotizaciones, dibujada DE VERDAD con el hook real. Los datos
// entran por donde entran en producción: la respuesta de /home/indices.
vi.mock('../utils/api', () => ({ api: { get: vi.fn() } }))
vi.mock('../utils/demo', () => ({ isDemoMode: () => false }))

import { api } from '../utils/api'
import { refreshMarketIndices, _resetMarketIndices } from '../hooks/useMarketIndices'
import MarketTicker, { copiasPorMitad } from './MarketTicker'

const ITEMS = [
  { symbol: '^GSPC', label: 'S&P 500', kind: 'index', price: 5840.5, change_pct: 0.42 },
  { symbol: '^MERV', label: 'Merval', kind: 'index', price: 2150420, change_pct: -0.85 },
  { symbol: 'BTC-USD', label: 'Bitcoin', kind: 'crypto', price: 81595, change_pct: 0 },
  { symbol: 'GC=F', label: 'Oro', kind: 'commodity', price: null, change_pct: null },
]

async function dibujar(respuesta) {
  if (respuesta instanceof Error) api.get.mockRejectedValue(respuesta)
  else api.get.mockResolvedValue(respuesta)
  await refreshMarketIndices()
  return renderToStaticMarkup(<MarketTicker />)
}

beforeEach(() => {
  _resetMarketIndices()
  api.get.mockReset()
})

describe('MarketTicker — la cinta de arriba', () => {
  it('cada cotización con su precio y su variación, a la argentina', async () => {
    const html = await dibujar({ items: ITEMS })
    expect(html).toContain('S&amp;P 500')
    expect(html).toContain('5.840,50')
    expect(html).toContain('+0,42%')
    expect(html).toContain('2.150.420')
    expect(html).toContain('−0,85%')   // el menos tipográfico, no el guion
    expect(html).toContain('81.595')
  })

  it('flecha y color según hacia dónde se movió; sin flecha si no se movió', async () => {
    const html = await dibujar({ items: ITEMS.slice(0, 3) })
    const una = html.slice(0, html.indexOf('</ul>'))
    expect((una.match(/▲/g) || []).length).toBe(1)
    expect((una.match(/▼/g) || []).length).toBe(1)
    expect(una).toMatch(/text-rendi-pos[^>]*>.*\+0,42%/)
    expect(una).toMatch(/text-rendi-neg[^>]*>.*−0,85%/)
    expect(una).toMatch(/text-ink-2[^>]*>0,00%/)
  })

  it('la cotización que no llegó no pasa por la cinta como un guión', async () => {
    const html = await dibujar({ items: ITEMS })
    expect(html).not.toContain('Oro')
    expect(html).not.toContain('—')
  })

  it('un lector de pantalla lee la lista UNA vez: las copias que hacen el giro están ocultas', async () => {
    const html = await dibujar({ items: ITEMS })
    const listas = html.match(/<ul[^>]*>/g) || []
    expect(listas.length).toBeGreaterThanOrEqual(2)
    expect(listas[0]).toContain('aria-label="Cotizaciones de mercado"')
    expect(listas[0]).not.toContain('aria-hidden')
    listas.slice(1).forEach(ul => expect(ul).toContain('aria-hidden="true"'))
  })

  it('la pista son dos mitades iguales: corre media pista y el reinicio no se ve', async () => {
    const html = await dibujar({ items: ITEMS })
    const listas = html.match(/<ul[^>]*>[\s\S]*?<\/ul>/g) || []
    expect(listas.length % 2).toBe(0)
    const sinAria = s => s.replace(/<ul[^>]*>/, '')
    listas.forEach(l => expect(sinAria(l)).toBe(sinAria(listas[0])))
    expect(html).toContain('ticker-scroll')
  })

  it('los números no van en mono (R1 del contrato)', async () => {
    const html = await dibujar({ items: ITEMS })
    expect(html).not.toContain('font-mono')
    expect(html).toContain('tabular')
  })

  it('si no llegó ninguna cotización, la cinta no aparece', async () => {
    expect(await dibujar({ items: [ITEMS[3]] })).toBe('')
    _resetMarketIndices()
    expect(await dibujar(new Error('caído'))).toBe('')
  })

  it('mientras carga reserva el alto (no empuja la pantalla al aparecer)', () => {
    const html = renderToStaticMarkup(<MarketTicker />)
    expect(html).toContain('h-7')
    expect(html).toContain('esqueleto')   // el brillo de carga compartido
  })
})

describe('copiasPorMitad — que no quede hueco antes de volver a empezar', () => {
  it('en el celular la lista ya es más ancha que la pantalla: una copia', () => {
    expect(copiasPorMitad(375, 1100)).toBe(1)
  })
  it('en una compu ancha hacen falta más', () => {
    expect(copiasPorMitad(1700, 1100)).toBe(2)
    expect(copiasPorMitad(2600, 1100)).toBe(3)
  })
  it('sin medida todavía, una', () => {
    expect(copiasPorMitad(0, 1100)).toBe(1)
    expect(copiasPorMitad(375, 0)).toBe(1)
  })
})
