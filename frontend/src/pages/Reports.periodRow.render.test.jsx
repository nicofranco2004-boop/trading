import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// La vista (Pesos/Dólares) la decide el selector global: cada test arma la suya.
const vista = { currency: 'ARS' }
vi.mock('../contexts/CurrencyContext', async (original) => ({
  ...(await original()),
  useCurrency: () => ({ currency: vista.currency, tcValuacion: 1500 }),
}))
vi.mock('../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))
// El dólar de cada fecha: antes de junio de 2024, 1.000; de ahí en adelante, 1.500 (el de hoy).
vi.mock('../hooks/useFxHistory', async (original) => ({
  ...(await original()),
  useFxHistory: () => ({ getRateForDate: (iso) => (String(iso) < '2024-06' ? 1000 : 1500), fxKey: 'k' }),
}))

import { PeriodRow, CurrentPeriodView } from './Reports.jsx'

// La fila de cada mes en Reportes → Mes → "Ver más meses". Escribía el % con
// PUNTO ("+3.25%") mientras la tarjeta que se abre debajo decía "+3,25%": el
// mismo número de dos formas en la misma pantalla.
function fila(delta_pct, delta_usd = 100, extra = {}) {
  const period = {
    period_key: '2026-08', period_label: 'Agosto 2026', is_relevant: true, is_current: false,
    metrics: { delta_pct, delta_usd, basis_incomparable: false }, ...extra,
  }
  return renderToStaticMarkup(<PeriodRow period={period} expanded={false} onToggle={() => {}} />)
}

describe('Reports — la fila del mes', () => {
  it('coma decimal y signo: dos decimales si es chico, uno si es grande', () => {
    expect(fila(3.25)).toContain('>+3,25%<')
    expect(fila(-12.34, -500)).toContain('>−12,3%<')
    expect(fila(3.25)).not.toMatch(/\d\.\d+%/)
  })
  it('lo que se escribe "0,00%" va neutro, no rojo', () => {
    vista.currency = 'USD'
    const h = fila(-0.001, 0)
    expect(h).toContain('>0,00%<')
    expect(h).not.toContain('text-rendi-neg')
  })
})

// La tercera auditoría: en Pesos el % de un día o una semana sigue en DÓLARES y el monto es en pesos.
// Una cartera de US$ 100.000 que cae 0,2 % mientras el dólar sube 0,5 % ganó plata en pesos: el monto
// positivo no se pinta de rojo por el % ni se deja sin aclarar de qué moneda es el porcentaje.
describe('Reports — la fila de una semana en Pesos', () => {
  const semana = {
    period_type: 'week', period_start: '2024-06-10', period_end: '2024-06-16',
  }
  const metricas = { start_value: 100000, end_value: 99800, delta_usd: -200, delta_pct: -0.2,
    realized_pnl: 0, unrealized_pnl: -200, deposits: 0, withdrawals: 0, medicion: 'mercado',
    puntas_desde: '2024-06-07', puntas_hasta: '2024-06-16', basis_incomparable: false }
  it('el monto positivo va en verde aunque el % en dólares sea negativo, y el % dice que es en US$', () => {
    vista.currency = 'ARS'
    // Sin tabla de dólares por fecha, todas valen lo mismo (1.500): para que el dólar de las puntas
    // sea distinto, el hook usa el de hoy; lo que se prueba acá es el color y el rótulo.
    const h = fila(-0.2, -200, { ...semana, metrics: { ...metricas, end_value: 100500, delta_usd: 500,
      delta_pct: -0.2 } })
    expect(h).toContain('en US$')
    expect(h).toMatch(/text-rendi-neg[^>]*>[^<]*−0,20%/)          // el % en dólares, rojo
    expect(h).toMatch(/text-rendi-pos[^>]*>\+\$/)                // el monto en pesos, verde
  })
  it('un mes en Pesos no rotula nada: su % ya está en pesos', () => {
    vista.currency = 'ARS'
    expect(fila(3.25, 100, { period_type: 'month' })).not.toContain('en US$')
  })
  it('en Dólares tampoco: un solo idioma', () => {
    vista.currency = 'USD'
    expect(fila(-0.2, -200, { ...semana, metrics: { ...metricas } })).not.toContain('en US$')
  })
})

// Con un broker elegido, en Día o Semana, el servidor no publica el % (delta_pct nulo) y pone delta =
// realizado. Comprada a $4.500 con el dólar a 1.000 y vendida a $6.000 con el dólar a 1.500: −US$ 0,5
// en dólares y +$1.500 en pesos. El color del «P&L de la semana» sigue el número que se ve.
describe('Reports — el color del P&L del período sin porcentaje', () => {
  const semana = {
    period_type: 'week', period_key: '2024-W24', period_label: 'Semana 24', period_start: '2024-06-10',
    period_end: '2024-06-16', is_current: false, is_relevant: true, headline: 'Vendiste GGAL',
    metrics: { delta_usd: -0.5, delta_pct: null, realized_pnl: -0.5, realized_ars: 1500, realized_ars_cubre_usd: -0.5,
               unrealized_pnl: 0, trades_count: 1, basis_incomparable: false },
    portfolio_snapshot: {},
  }
  const kpi = (currency) => {
    vista.currency = currency
    const h = renderToStaticMarkup(
      <MemoryRouter><CurrentPeriodView period={semana} loading={false} tab="week" broker="IOL" /></MemoryRouter>)
    // La celda «P&L de la semana» y nada más (hasta el rótulo siguiente).
    const desde = h.indexOf('P&amp;L de la semana')
    return h.slice(desde, h.indexOf('P&amp;L realizado'))
  }
  it('en Pesos, +$1.500 va en verde aunque en dólares sea una pérdida', () => {
    const c = kpi('ARS')
    expect(c).toContain('1.500')
    expect(c).toContain('text-rendi-pos')
    expect(c).not.toContain('text-rendi-neg')
  })
  it('en Dólares, la pérdida va en rojo', () => {
    expect(kpi('USD')).toContain('text-rendi-neg')
  })
  it('el color es el del RESULTADO, no el del realizado: vendiste con ganancia pero la cartera cayó', () => {
    // Realizado +$240.000 (verde) y la cartera valía US$ 1.000 y hoy US$ 900 con el mismo dólar: el
    // resultado de la semana es −$150.000 y se pinta en rojo.
    vista.currency = 'ARS'
    const cayo = { ...semana, metrics: { ...semana.metrics, start_value: 1000, end_value: 900, delta_usd: -100,
      realized_pnl: 10, realized_ars: 240000, realized_ars_cubre_usd: 10, unrealized_pnl: -110,
      deposits: 0, withdrawals: 0, medicion: 'mercado', puntas_desde: '2024-06-09', puntas_hasta: '2024-06-16' } }
    const h = renderToStaticMarkup(
      <MemoryRouter><CurrentPeriodView period={cayo} loading={false} tab="week" broker="IOL" /></MemoryRouter>)
    const celda = h.slice(h.indexOf('P&amp;L de la semana'), h.indexOf('P&amp;L realizado'))
    expect(celda).toContain('text-rendi-neg')
    expect(celda).not.toContain('text-rendi-pos')
    const realizado = h.slice(h.indexOf('P&amp;L realizado'))
    expect(realizado.slice(0, 600)).toContain('text-rendi-pos')
  })
  describe('el KPI «P&L de la semana» en Pesos con el % en dólares', () => {
    // US$ 100.000 → 99.800 (−0,2 %) con el dólar de 1.000 a 1.500: en pesos ganó 99.800 × 1.500 − 100.000 × 1.000.
    const cayoEnDolares = {
      period_type: 'week', period_key: '2024-W24', period_label: 'Semana 24', period_start: '2024-06-10',
      period_end: '2024-06-16', is_current: false, is_relevant: true, headline: 'x',
      metrics: { start_value: 100000, end_value: 99800, delta_usd: -200, delta_pct: -0.2, realized_pnl: 0,
        unrealized_pnl: -200, deposits: 0, withdrawals: 0, trades_count: 1, basis_incomparable: false,
        medicion: 'mercado', puntas_desde: '2024-05-31', puntas_hasta: '2024-06-16' },
      portfolio_snapshot: {},
    }
    const celda = () => {
      vista.currency = 'ARS'
      const h = renderToStaticMarkup(
        <MemoryRouter><CurrentPeriodView period={cayoEnDolares} loading={false} tab="week" broker="global" /></MemoryRouter>)
      return h.slice(h.indexOf('P&amp;L de la semana'), h.indexOf('P&amp;L de la semana') + 700)
    }
    it('el monto va en verde aunque el % en dólares sea negativo', () => {
      const c = celda()
      expect(c).toContain('text-rendi-pos')
      expect(c).not.toContain('text-rendi-neg')
    })
    it('el subtítulo aclara que el porcentaje es en dólares', () => {
      expect(celda()).toContain('−0,20% en dólares')
    })
  })

  describe('«P&L no realizado» sale del número que se ve (en Pesos), no de los dólares del servidor', () => {
    // Mayo con el dólar a 1.000 y junio a 1.500. El servidor deja unrealized_pnl en 0 en todo mes cerrado.
    const kpiNoRealizado = (metricas) => {
      vista.currency = 'ARS'
      const mes = { period_type: 'month', period_key: '2024-06', period_label: 'Junio 2024', period_start: '2024-06-01',
        period_end: '2024-06-30', is_current: false, is_relevant: true, headline: 'x',
        metrics: { deposits: 0, withdrawals: 0, trades_count: 0, basis_incomparable: false, medicion: 'mercado',
          puntas_desde: '2024-05-31', puntas_hasta: '2024-06-30', realized_pnl: 0, ...metricas },
        portfolio_snapshot: {} }
      const h = renderToStaticMarkup(
        <MemoryRouter><CurrentPeriodView period={mes} loading={false} tab="month" broker="global" /></MemoryRouter>)
      const desde = h.indexOf('P&amp;L no realizado')
      return desde < 0 ? null : h.slice(Math.max(0, desde - 200), desde + 400)
    }
    it('una cartera en dólares quieta con el dólar +50 %: aparece, en verde, aunque el servidor diga 0', () => {
      // (Con una operación en el mes: sin operaciones ni movimientos en dólares la pantalla lo da por «plano».)
      const c = kpiNoRealizado({ start_value: 1000, end_value: 1000, delta_usd: 0, delta_pct: 0, unrealized_pnl: 0,
        trades_count: 1 })
      expect(c).not.toBeNull()
      expect(c).toContain('500.000')
      expect(c).toContain('text-rendi-pos')
    })
    it('el servidor dice +US$ 5 pero en pesos perdió: va en rojo', () => {
      const c = kpiNoRealizado({ start_value: 1000, end_value: 600, delta_usd: -400, delta_pct: 1, unrealized_pnl: 5 })
      expect(c).toContain('text-rendi-neg')
      expect(c).not.toContain('text-rendi-pos')
    })
    it('un período al costo sin nada abierto no dibuja el renglón', () => {
      expect(kpiNoRealizado({ start_value: 450, end_value: 460, delta_usd: 10, delta_pct: 1, realized_pnl: 10,
        realized_ars: 240000, realized_ars_cubre_usd: 10, unrealized_pnl: 0, medicion: 'costo',
        puntas_desde: null, puntas_hasta: null, trades_count: 1 })).toBeNull()
    })
  })
})
