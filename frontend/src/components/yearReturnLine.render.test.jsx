import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// La tarjeta "Este año" del inicio, DIBUJADA. El caso reportado: el año en curso
// medido "desde el 31 de enero" mostraba "vs el S&P 500 +1,5 pp" y escondía la
// inflación (`vsInfl = parcial ? null : …`). Y cada modo trae su propio tramo:
// la tarjeta tiene que mostrar los veredictos del modo que se está mirando.

// Lo que devuelve `/api/reports/years` para el año en curso, por modo. Mismos
// campos que arma `builder.tramo_parcial_del_anio`.
const FILAS = {
  estimado: {
    year: 2026, is_current: true, pct: null, basis: 'contable',
    parcial_pct: 13.0, parcial_desde: '2026-01-31', parcial_hasta: '2026-10-27',
    parcial_vs_sp500_pct: 1.5, parcial_vs_inflation_pct: -0.8,
    parcial_retorno_ars_pct: 19.24, parcial_inflation_pct: 20.2,
  },
  certero: {
    year: 2026, is_current: true, pct: null, basis: 'mercado',
    parcial_pct: 6.08, parcial_desde: '2026-07-01', parcial_hasta: '2026-10-27',
    parcial_vs_sp500_pct: 3.69, parcial_vs_inflation_pct: 1.56,
    parcial_retorno_ars_pct: 9.1, parcial_inflation_pct: 7.5,
  },
}
let moneda = 'USD'
const pedidos = []
vi.mock('../contexts/CurrencyContext', () => ({ useCurrency: () => ({ currency: moneda }) }))
vi.mock('../hooks/useReportYears', () => ({
  default: (broker, modo, mon) => {
    pedidos.push({ modo, mon })
    return { current: FILAS[modo], loading: false, refreshing: false }
  },
}))

import YearReturnLine from './YearReturnLine'

const dibujar = (modo, mon = 'USD') => {
  moneda = mon
  return renderToStaticMarkup(<MemoryRouter><YearReturnLine modo={modo} /></MemoryRouter>)
}

describe('Este año — el tramo parcial trae sus dos veredictos', () => {
  it('"vs el S&P 500" Y "vs la inflación", con la fecha del tramo', () => {
    const html = dibujar('estimado')
    expect(html).toContain('desde el 31 de enero')
    expect(html).toContain('vs el S&amp;P 500')
    expect(html).toContain('+1,5 pp')
    expect(html).toContain('vs la inflación')
    expect(html).toContain('−0,8 pp')
  })

  it('en dólares, el globo dice contra qué número en pesos se restó', () => {
    expect(dibujar('estimado')).toContain(
      'Se compara en pesos: tu cartera hizo 19,24% en pesos y la inflación 20,2%')
  })

  it('en pesos no hace falta aclarar: el número de la tarjeta es el que se restó', () => {
    expect(dibujar('estimado', 'ARS')).not.toContain('Se compara en pesos')
  })

  it('cada modo muestra SU tramo y SUS veredictos', () => {
    pedidos.length = 0
    const cert = dibujar('certero')
    expect(pedidos.at(-1)).toEqual({ modo: 'certero', mon: 'usd' })
    expect(cert).toContain('desde el 1 de julio')
    expect(cert).toContain('+3,7 pp')
    expect(cert).toContain('+1,6 pp')
    expect(cert).not.toContain('−0,8 pp')
  })
})
