import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import TradesTable from './TradesTable'
import TradesFeed from './TradesFeed'
import { pctEnMoneda } from './shared'
import { dineroHistorico } from '../../hooks/useHistoricalMoney'
import { fmtConvertedRaw, fmtConvertedCompactRaw } from '../../contexts/CurrencyContext'

// GGAL de $4.500 a $6.900 con el dólar de 1.000 a 1.500: +53,33 % en pesos y
// +2,22 % en dólares. Antes la columna mostraba el 53 % con la app en dólares.
// Como la escribe hoy el motor: pnl_usd = US$ 460 − US$ 450.
const ggal = {
  id: 1, asset: 'GGAL', broker: 'Cocos', op_type: 'Venta', date: '2024-06-10', quantity: 100,
  entry_price: 4500, exit_price: 6900, pnl_usd: 10, pnl_pct: 2.2222, currency: 'ARS',
  fx_to_usd: 1500, pnl_pct_ars: 53.3333, pnl_pct_usd: 2.2222, pnl_sin_dato: null,
  costo_ars: 450000, cobrado_ars: 690000, costo_usd: 450, cobrado_usd: 460,
  // Lo calcula el servidor (backend/resultado_dual.py, `resultado_en_pesos`): la pantalla lo lee.
  resultado_ars: 240000, resultado_ars_tipo: 'exacto',
}
const sinFecha = { ...ggal, id: 2, asset: 'YPFD', pnl_usd: 160, pnl_pct: 53.3333, pnl_pct_usd: null,
  costo_usd: null, cobrado_usd: 460, pnl_sin_dato: 'sin_fecha_compra' }
// Una venta vieja, sin las columnas: la regla de siempre.
const vieja = { id: 4, asset: 'ALUA', broker: 'Cocos', op_type: 'Venta', date: '2024-06-10', quantity: 10,
  entry_price: 800, exit_price: 1000, pnl_usd: 1.3333, pnl_pct: 25, currency: 'ARS', fx_to_usd: 1500 }
const dividendo = { id: 3, asset: 'KO', broker: 'Bull', op_type: 'Dividendo', date: '2024-06-10',
  pnl_usd: 5, pnl_pct: 1.5, currency: 'USD' }

// Como el hook `useHistoricalMoney`: la fábrica pura más los formateadores de totales que le suma (ver ahí
// «Ocultar saldos»). Sin `fmtMontoCorto` el subtotal del día de la tarjeta no se dibuja.
const hm = currency => ({
  ...dineroHistorico({ currency, tcValuacion: 1500, getRateForDate: () => null }),
  fmtMonto: (v, opts) => fmtConvertedRaw(v, currency, opts),
  fmtMontoCorto: (v, opts) => fmtConvertedCompactRaw(v, currency, opts),
})
const tabla = (ops, currency) => renderToStaticMarkup(
  <MemoryRouter>
    <TradesTable
      ops={ops} filteredOps={ops} pagedOps={ops} groups={[]} grouped={false} groupBy="none"
      histMoney={hm(currency)} expandedGroups={new Set()} onToggleGroup={() => {}}
      onEdit={() => {}} onDelete={() => {}} onDeleteGroup={() => {}}
      onAdd={() => {}} page={0} totalPages={1} onPage={() => {}}
    />
  </MemoryRouter>,
)
const feed = (ops, currency) => renderToStaticMarkup(
  <TradesFeed groups={[{ key: '2024-06-10', label: '10 jun', rows: ops }]} histMoney={hm(currency)} />,
)

describe('pctEnMoneda', () => {
  it('elige el de la moneda de la app', () => {
    expect(pctEnMoneda(ggal, 'ARS').pct).toBeCloseTo(53.3333)
    expect(pctEnMoneda(ggal, 'USD').pct).toBeCloseTo(2.2222)
  })
  it('si falta, no cae al % de la otra moneda y dice por qué', () => {
    const r = pctEnMoneda(sinFecha, 'USD')
    expect(r.pct).toBeNull()
    expect(r.motivo).toMatch(/no tiene fecha/)
    expect(pctEnMoneda(sinFecha, 'ARS').pct).toBeCloseTo(53.3333)
  })
  it('lo que no es venta de un lote sigue mostrando su pnl_pct', () => {
    expect(pctEnMoneda(dividendo, 'ARS').pct).toBe(1.5)
    expect(pctEnMoneda(dividendo, 'USD').pct).toBe(1.5)
  })
})

describe('el monto del resultado en la moneda de la app', () => {
  it('en pesos es la ganancia en pesos, no los dólares × el dólar de la venta', () => {
    expect(hm('ARS').pnlAt(ggal)).toBe(240000)       // 10 × 1.500 daría 15.000
    expect(hm('USD').pnlAt(ggal)).toBe(10)
  })
  it('una venta vieja sigue con su dólar estampado', () => {
    expect(hm('ARS').pnlAt(vieja)).toBeCloseTo(2000, 0)
    expect(hm('USD').pnlAt(vieja)).toBeCloseTo(1.3333, 4)
  })
  it('la suma de un grupo es la suma de lo que muestran sus filas', () => {
    expect(hm('ARS').sumPnlAt([ggal, vieja])).toBeCloseTo(242000, 0)
    expect(hm('USD').sumPnlAt([ggal, vieja])).toBeCloseTo(11.3333, 4)
  })
  it('la tabla y las tarjetas lo muestran', () => {
    expect(tabla([ggal], 'ARS')).toContain('240.000')
    expect(tabla([ggal], 'ARS')).not.toContain('15.000')
    expect(feed([ggal], 'ARS')).toMatch(/240/)
  })

  // La pantalla LEE el resultado en pesos que manda el servidor; no lo rehace con cobrado − costo.
  it('usa el resultado_ars del servidor aunque cobrado_ars − costo_ars diga otra cosa', () => {
    const delServidor = { ...ggal, resultado_ars: 99999 }          // cobrado − costo = 240.000
    expect(hm('ARS').pnlAt(delServidor)).toBe(99999)
    expect(hm('USD').pnlAt(delServidor)).toBe(10)
  })
  it('una venta vieja como la manda el servidor: su ganancia en pesos, no los dólares × otro dólar', () => {
    const viejaDelServidor = { ...vieja, resultado_ars: 2000, resultado_ars_tipo: 'exacto' }
    expect(hm('ARS').pnlAt(viejaDelServidor)).toBe(2000)
    // Sin la cuenta (el servidor no pudo saberlo: resultado_ars null) cae al dólar estampado de la fila.
    expect(hm('ARS').pnlAt({ ...vieja, resultado_ars: null })).toBeCloseTo(2000, 0)
  })
  it('una venta valuada lo dice al pasar el mouse, sólo mirando en pesos', () => {
    const valuada = { ...ggal, resultado_ars_tipo: 'valuado' }
    expect(tabla([valuada], 'ARS')).toContain('valuado al dólar de cada fecha')
    expect(tabla([valuada], 'USD')).not.toContain('valuado al dólar de cada fecha')
    expect(tabla([ggal], 'ARS')).not.toContain('valuado al dólar de cada fecha')
  })
})

describe('la columna P&L % sigue al selector de moneda', () => {
  it('tabla (compu)', () => {
    expect(tabla([ggal], 'USD')).toContain('+2,2%')
    expect(tabla([ggal], 'USD')).not.toContain('+53,3%')
    expect(tabla([ggal], 'ARS')).toContain('+53,3%')
  })
  it('tabla: sin dato muestra el porqué al pasar el mouse', () => {
    const html = tabla([sinFecha], 'USD')
    expect(html).toContain('no tiene fecha')
    expect(html).not.toContain('+53,3%')
  })
  it('tarjetas (celular)', () => {
    expect(feed([ggal], 'USD')).toContain('+2,2%')
    expect(feed([ggal], 'USD')).not.toContain('+53,3%')
    expect(feed([ggal], 'ARS')).toContain('+53,3%')
  })
})
