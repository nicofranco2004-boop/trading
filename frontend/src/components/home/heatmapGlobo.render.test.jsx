import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})) } }))

import { GloboCelda } from './Heatmap'

// El globo del mapa de calor con el mouse encima de un cuadro.
const celda = { symbol: 'NVDA', name: 'NVIDIA', price: 178.5, change_pct: 2.34, x: 600, y: 300, w: 100, h: 80 }

describe('GloboCelda', () => {
  it('ticker, nombre, precio en dólares y variación del día', () => {
    const html = renderToStaticMarkup(<GloboCelda b={celda} market="sp500" />)
    expect(html).toContain('NVDA')
    expect(html).toContain('NVIDIA')
    expect(html).toContain('US$ 178,50')
    expect(html).toContain('+2,34%')
    expect(html).toContain('text-rendi-pos')
  })
  it('Merval en pesos, cripto sin el "-USD" y el menos tipográfico', () => {
    expect(renderToStaticMarkup(<GloboCelda b={{ ...celda, symbol: 'GGAL.BA', price: 4820 }} market="merval" />))
      .toContain('$ 4.820')
    const cripto = renderToStaticMarkup(<GloboCelda b={{ ...celda, symbol: 'BTC-USD', change_pct: -1.2 }} market="crypto" />)
    expect(cripto).toContain('>BTC<')
    expect(cripto).toContain('−1,20%')
  })
  it('un cuadro pegado arriba abre el globo hacia abajo', () => {
    expect(renderToStaticMarkup(<GloboCelda b={{ ...celda, y: 0 }} market="sp500" />)).toContain('translate(-50%, 6px)')
    expect(renderToStaticMarkup(<GloboCelda b={celda} market="sp500" />)).toContain('calc(-100% - 6px)')
  })
  it('cerca de un costado se alinea con el borde del cuadro y no se sale del mapa', () => {
    // Centro del mapa: centrado sobre el cuadro.
    expect(renderToStaticMarkup(<GloboCelda b={celda} market="sp500" />)).toContain('translate(-50%,')
    // Cuadro contra el borde izquierdo: el globo arranca en el borde del cuadro.
    const izq = renderToStaticMarkup(<GloboCelda b={{ ...celda, x: 0, w: 120 }} market="sp500" />)
    expect(izq).toContain('left:0%')
    expect(izq).toContain('translate(0%,')
    // Contra el derecho (WIDTH 1200): termina en el borde del cuadro.
    const der = renderToStaticMarkup(<GloboCelda b={{ ...celda, x: 1080, w: 120 }} market="sp500" />)
    expect(der).toContain('left:100%')
    expect(der).toContain('translate(-100%,')
  })
  it('sin cuadro, nada', () => {
    expect(renderToStaticMarkup(<GloboCelda b={null} market="sp500" />)).toBe('')
  })
})
