import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MetricasDelAno } from './PerformanceCalendar'

// La fila de abajo de cada año en Reportes ("S&P 500 ese año", "Inflación AR",
// "comparado del … al …"). Con el año mostrando su TRAMO, esa fila seguía con los
// índices y la ventana del año ENTERO: la pastilla decía la inflación de un
// período y la fila, diez píxeles abajo, la de otro.
const pesos = { enVista: () => ({ depositos: 0, retiros: 0, realizado: 0 }), fmt: (v) => String(v) }

describe('MetricasDelAno — los índices y la ventana del número que se muestra', () => {
  const tramo = {
    year: 2026, is_current: true, pct: null, meses_del_anio: 10,
    // El año entero (otra ventana): no se tiene que mostrar.
    sp500_return_pct: 25.0, inflation_pct: 25.0, bench_desde: '2025-12-31', bench_hasta: '2026-10-27',
    parcial_pct: 6.1, parcial_desde: '2026-06-30', parcial_hasta: '2026-10-27',
    parcial_sp500_return_pct: 2.4, parcial_inflation_pct: 7.5,
  }
  const html = renderToStaticMarkup(<MetricasDelAno resumen={tramo} months={[]} pesos={pesos} ranking={null} />)

  it('el S&P y la inflación del tramo, no los del año', () => {
    expect(html).toContain('S&amp;P 500 en el tramo')
    expect(html).toContain('+2,4%')
    expect(html).toContain('+7,5%')
    expect(html).not.toContain('+25,0%')
  })
  it('y la ventana del tramo', () => {
    expect(html).toContain('comparado del 30/06/26 al 27/10/26')
  })
  it('con el año entero, todo del año', () => {
    const entero = { ...tramo, pct: 18.0, parcial_pct: null }
    const h = renderToStaticMarkup(<MetricasDelAno resumen={entero} months={[]} pesos={pesos} ranking={null} />)
    expect(h).toContain('S&amp;P 500 ese año')
    expect(h).toContain('+25,0%')
    expect(h).toContain('comparado del 31/12/25 al 27/10/26')
  })
})
