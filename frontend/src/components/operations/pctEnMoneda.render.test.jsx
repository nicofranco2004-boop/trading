import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import TradesTable from './TradesTable'
import TradesFeed from './TradesFeed'
import { pctEnMoneda } from './shared'

// GGAL de $4.500 a $6.900 con el dólar de 1.000 a 1.500: +53,33 % en pesos y
// +2,22 % en dólares. Antes la columna mostraba el 53 % con la app en dólares.
const ggal = {
  id: 1, asset: 'GGAL', broker: 'Cocos', op_type: 'Venta', date: '2024-06-10', quantity: 100,
  entry_price: 4500, exit_price: 6900, pnl_usd: 160, pnl_pct: 53.3333, currency: 'ARS',
  fx_to_usd: 1500, pnl_pct_ars: 53.3333, pnl_pct_usd: 2.2222, pnl_sin_dato: null,
}
const sinFecha = { ...ggal, id: 2, asset: 'YPFD', pnl_pct_usd: null, pnl_sin_dato: 'sin_fecha_compra' }
const dividendo = { id: 3, asset: 'KO', broker: 'Bull', op_type: 'Dividendo', date: '2024-06-10',
  pnl_usd: 5, pnl_pct: 1.5, currency: 'USD' }

const hm = currency => new Proxy({ currency }, {
  get: (t, k) => (k in t ? t[k] : String(k).startsWith('sum') ? () => 0 : () => 'US$ 1'),
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
