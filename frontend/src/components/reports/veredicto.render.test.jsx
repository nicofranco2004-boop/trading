import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { Veredicto } from './PerformanceCalendar'

// "vs inflación" del calendario de Reportes: el número, el color y la ayuda
// dicen lo mismo, y la aclaración ("Se compara en pesos…") va siempre.
describe('Veredicto — contra un benchmark, en puntos porcentuales', () => {
  const detalle = 'Se compara en pesos'
  it('empate (0,0 pp): neutro, "Igual que la inflación" y CON la aclaración', () => {
    const html = renderToStaticMarkup(<Veredicto nombre="inflación" articulo="la" pp={0} detalle={detalle} />)
    expect(html).toContain('title="Igual que la inflación. Se compara en pesos"')
    expect(html).toContain('text-ink-1')
    expect(html).not.toMatch(/text-rendi-(pos|neg)/)
  })
  it('por debajo por poco: "−0,04 pp" en rojo, no "−0,0 pp"', () => {
    const html = renderToStaticMarkup(<Veredicto nombre="S&P 500" articulo="el" pp={-0.04} detalle={detalle} />)
    expect(html).toContain('−0,04 pp')
    expect(html).toContain('text-rendi-neg')
    expect(html).toContain('Por debajo del S&amp;P 500 por 0,04 puntos porcentuales. Se compara en pesos')
  })
  it('por encima: verde, con su signo', () => {
    const html = renderToStaticMarkup(<Veredicto nombre="S&P 500" articulo="el" pp={2.31} />)
    expect(html).toContain('+2,3 pp')
    expect(html).toContain('text-rendi-pos')
  })
})
