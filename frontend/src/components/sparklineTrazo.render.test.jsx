import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import Sparkline from './Sparkline'

// Las mini líneas (Principales posiciones, Cartera) se dibujan al aparecer y
// con los colores del tema, no con los dos hex de fondo oscuro de antes.
describe('Sparkline', () => {
  it('la línea lleva el trazo que se dibuja y el área el fundido', () => {
    const html = renderToStaticMarkup(<Sparkline data={[1, 2, 3, 2, 4]} />)
    expect(html).toContain('pathLength="1"')
    expect(html).toContain('traza-dibuja')
    expect(html).toContain('area-aparece')
  })
  it('colores del tema: ni #21D07A ni #FF5360', () => {
    const sube = renderToStaticMarkup(<Sparkline data={[1, 2, 3]} />)
    const baja = renderToStaticMarkup(<Sparkline data={[3, 2, 1]} />)
    for (const html of [sube, baja]) expect(html).not.toMatch(/#21D07A|#FF5360/i)
    expect(sube).not.toBe(baja)
  })
  it('con menos de dos puntos no dibuja nada', () => {
    expect(renderToStaticMarkup(<Sparkline data={[1]} />)).toBe('')
  })
})
