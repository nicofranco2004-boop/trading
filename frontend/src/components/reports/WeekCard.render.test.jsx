import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// La vista (Pesos/Dólares) la decide el selector global: cada test arma la suya.
const vista = { currency: 'ARS' }
vi.mock('../../contexts/CurrencyContext', async (original) => ({
  ...(await original()),
  useCurrency: () => ({ currency: vista.currency, tcValuacion: 1500 }),
}))
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import WeekCard from './WeekCard.jsx'

// GGAL comprada a $4.500 (dólar 1.000) y vendida a $6.900 (dólar 1.500): +$240.000 y +US$ 10.
// El resultado de la semana, sin nada abierto, es lo que se vendió: la tarjeta no puede decir
// «resultado +$15.000» (dólares × dólar) y, adentro, «realizado +$240.000».
const semana = {
  period_type: 'week', period_key: '2024-W24', period_label: 'Semana 24', period_start: '2024-06-10',
  period_end: '2024-06-16', is_current: false, is_relevant: true, headline: 'Vendiste GGAL',
  metrics: { delta_usd: 10, delta_pct: 0.5, realized_pnl: 10, unrealized_pnl: 0, trades_count: 1,
             basis_incomparable: false, realized_ars: 240000, realized_ars_cubre_usd: 10 },
}
const render = (currency, week = semana) => {
  vista.currency = currency
  return renderToStaticMarkup(<WeekCard week={week} />)
}

describe('WeekCard — el resultado de la semana contiene al realizado', () => {
  it('en Pesos el resultado de la cabecera es el de las ventas en pesos', () => {
    const html = render('ARS')
    expect(html).toContain('240.000')
    expect(html).not.toContain('15.000')
  })
  it('en Dólares no cambia', () => {
    const html = render('USD')
    expect(html).toMatch(/US\$\s?10\b/)
    expect(html).not.toContain('240.000')
  })
  it('una semana de pérdida en dólares y ganancia en pesos: el resultado es el de los pesos', () => {
    const html = render('ARS', { ...semana, metrics: { ...semana.metrics, delta_usd: -130,
      realized_pnl: -130, realized_ars: 30000, realized_ars_cubre_usd: -130 } })
    expect(html).toContain('30.000')
    expect(html).not.toContain('195.000')
  })
})

// El % de una semana sigue en DÓLARES aunque el monto se vea en pesos (el servidor sólo pasa a pesos el
// de un mes o un año): una cartera que cae 0,2 % en dólares con el dólar +0,5 % ganó en pesos, y los dos
// números en la misma fila se leen mal si no se dice en qué moneda está cada uno.
describe('WeekCard — el porcentaje de la semana dice en qué moneda está', () => {
  it('el monto de la fila no se parte ni se encoge en el celular (cede el titular, que ya se trunca)', () => {
    // [auditoría 5] a 375 px un monto negativo dejaba el «−» solo en un renglón y el número en otro.
    const html = render('ARS', { ...semana, metrics: { ...semana.metrics, delta_usd: -130, delta_pct: -0.4,
      realized_pnl: 10, realized_ars: 240000, realized_ars_cubre_usd: 10, unrealized_pnl: -140,
      start_value: 1000, end_value: 870, medicion: 'mercado', puntas_desde: '2024-06-09', puntas_hasta: '2024-06-16' } })
    const caja = html.slice(html.lastIndexOf('<span', html.indexOf('font-mono tabular')), html.indexOf('font-mono tabular') + 120)
    expect(caja).toContain('whitespace-nowrap')
    expect(caja).toContain('flex-shrink-0')
  })
  it('en Pesos lo rotula «en US$»', () => {
    expect(render('ARS')).toContain('en US$')
  })
  it('en Dólares no hay rotulo: un solo idioma', () => {
    expect(render('USD')).not.toContain('en US$')
  })
  it('sin porcentaje (semana de un broker filtrado) no hay nada que rotular', () => {
    expect(render('ARS', { ...semana, metrics: { ...semana.metrics, delta_pct: null } })).not.toContain('en US$')
  })
})

// La celda «Realizado» vive adentro de la tarjeta desplegada: se dibuja abierta.
describe('WeekCard abierta — la celda «Realizado»', () => {
  const abierta = (currency, week = semana) => {
    vista.currency = currency
    return renderToStaticMarkup(<WeekCard week={week} defaultOpen />)
  }
  // Desde la caja de la celda (el aviso va en su `title`, que abre ANTES del rótulo).
  const celdaRealizado = (h) => h.slice(h.lastIndexOf('<div class="rounded-sm', h.indexOf('>Realizado<')))
  it('en Pesos son los pesos de verdad de la venta, no los dólares × el dólar', () => {
    const c = celdaRealizado(abierta('ARS'))
    expect(c).toContain('+$240.000')
    expect(c).not.toContain('15.000')
  })
  it('lo convertido se dice en el aviso de la celda', () => {
    // US$ 10 de la venta + US$ 20 de un dividendo en dólares: US$ 20 se convierten
    const h = abierta('ARS', { ...semana, metrics: { ...semana.metrics, realized_pnl: 30, delta_usd: 30 } })
    expect(celdaRealizado(h)).toContain('title="incluye US$ 20 convertidos al dólar del cierre"')
  })
  it('sin resto convertido, sin aviso', () => {
    expect(celdaRealizado(abierta('ARS'))).not.toContain('title=')
  })
  it('en Dólares: dólares y sin aviso', () => {
    const c = celdaRealizado(abierta('USD'))
    expect(c).toMatch(/US\$\s?10\b/)
    expect(c).not.toContain('title=')
  })
})

// Con un broker elegido el servidor no publica el % (delta_pct nulo) y pone delta = realizado: el
// color tiene que seguir el signo del monto que se VE, no el de los dólares.
describe('WeekCard — el color del monto sin porcentaje', () => {
  // Comprada a $4.500 con el dólar a 1.000, vendida a $6.000 con el dólar a 1.500: −US$ 0,5 y +$1.500.
  const conBroker = { ...semana, metrics: { ...semana.metrics, delta_usd: -0.5, delta_pct: null,
    realized_pnl: -0.5, realized_ars: 1500, realized_ars_cubre_usd: -0.5, unrealized_pnl: 0 } }
  const cabecera = (h) => h.slice(0, h.indexOf('</button>'))
  it('en Pesos, +$1.500 va en verde aunque en dólares sea una pérdida', () => {
    vista.currency = 'ARS'
    const h = cabecera(renderToStaticMarkup(<WeekCard week={conBroker} />))
    expect(h).toContain('1.500')
    expect(h).toContain('text-rendi-pos')
    expect(h).not.toContain('text-rendi-neg')
  })
  it('en Dólares, −US$ 0,5 va en rojo', () => {
    vista.currency = 'USD'
    const h = cabecera(renderToStaticMarkup(<WeekCard week={conBroker} />))
    expect(h).toContain('text-rendi-neg')
  })
})

