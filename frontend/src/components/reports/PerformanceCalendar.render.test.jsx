import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import { MetricasDelAno } from './PerformanceCalendar.jsx'
import { crearPesosDelPeriodo } from '../../utils/periodoEnPesos'
import { fmtConvertedRaw } from '../../contexts/CurrencyContext'

// La fila de métricas del año, en la moneda en que se mira (la misma `pesos` que arma usePesosDelPeriodo).
function pesosEn(moneda, tcEnFecha = () => 1000) {
  const p = crearPesosDelPeriodo({ moneda, tcHoy: 1500, tcEnFecha, dolarMes: {}, monthly: [], brokers: [] })
  return { ...p, fmt: (v, opts) => fmtConvertedRaw(v, p.moneda, opts) }
}
const fila = (pesos, resumen, months = []) => renderToStaticMarkup(
  <MetricasDelAno resumen={{ year: 2024, is_current: false, deposits: 0, withdrawals: 0, trades_count: 0, ...resumen }}
                  months={months} pesos={pesos} ranking={null} />,
)
// El Dato «P&L realizado» ya con su color: busca el span del valor justo después del rótulo.
const colorDelRealizado = (html) => (html.match(/P&amp;L realizado<\/span><span class="[^"]*?(text-rendi-pos|text-rendi-neg)/) || [])[1]

describe('Reportes · fila del año · P&L realizado', () => {
  // 100 u. compradas a $4.500 con el dólar a 1.500 y vendidas a $4.400 con el dólar a 1.000:
  // +US$ 140 en dólares y −$10.000 en pesos (el peso se apreció).
  const resumen = { realized_pnl: 140, realized_ars: -10000, realized_ars_cubre_usd: 140, realized_ars_valuado: false }

  it('en Pesos el color es el del número que se ve (rojo: −$10.000), no el de los dólares', () => {
    const html = fila(pesosEn('ARS'), resumen)
    expect(html).toContain('10.000')
    expect(colorDelRealizado(html)).toBe('text-rendi-neg')
  })
  it('en Dólares es el de siempre (verde: +US$ 140)', () => {
    expect(colorDelRealizado(fila(pesosEn('USD'), resumen))).toBe('text-rendi-pos')
  })
  it('lo convertido se dice en la fila del año', () => {
    // US$ 140 de la venta + US$ 40 de dividendos en dólares: US$ 40 se convierten
    const html = fila(pesosEn('ARS'), { ...resumen, realized_pnl: 180 })
    expect(html).toMatch(/incluye US\$ 40 convertidos/)
  })
  it('en Dólares no hay nada que avisar', () => {
    expect(fila(pesosEn('USD'), { ...resumen, realized_pnl: 180 })).not.toMatch(/convertidos/)
  })
  it('si el realizado en dólares da cero pero en pesos no, la fila aparece', () => {
    const marzo = { period_type: 'month', period_key: '2024-03', period_start: '2024-03-01', period_end: '2024-03-31',
      is_current: false, metrics: { realized_pnl: 0, realized_ars: 5000, realized_ars_cubre_usd: 0 } }
    const html = fila(pesosEn('ARS'), { realized_pnl: 0, realized_ars: 5000, realized_ars_cubre_usd: 0 }, [marzo])
    expect(html).toContain('P&amp;L realizado')
    expect(colorDelRealizado(html)).toBe('text-rendi-pos')
  })
})
