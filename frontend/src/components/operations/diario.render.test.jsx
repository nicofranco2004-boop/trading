import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import TradesTable from './TradesTable'
import TradesFeed from './TradesFeed'
import DiarioResumen from './DiarioResumen'
import TesisDelActivo, { lineaDeTendencias } from '../tesis/TesisDelActivo'
import { abiertasPorActivo } from '../tesis/TesisPosiciones'
import { resumenDiario } from '../../utils/diarioOperaciones'

// Las columnas nuevas del diario (pieza 11), dibujadas con los MISMOS
// renderers que usa Operations en la compu (tabla) y en el celular (tarjetas).
const histMoney = new Proxy({ currency: 'USD' }, {
  get: (t, k) => (k in t ? t[k] : String(k).startsWith('sum') ? () => 0 : () => 'US$ 1'),
})
const op = (id, extra) => ({
  id, asset: 'NVDA', broker: 'Schwab', op_type: 'Venta', date: '2026-04-28', entry_date: '2025-11-14',
  quantity: 1, entry_price: 1, exit_price: 2, pnl_usd: -1, pnl_pct: -0.3, currency: 'USD', ...extra,
})
const ops = [
  op(1),                                                                        // 5,4 meses, alcista
  op(2, { asset: 'MELI', entry_date: '2026-03-15', pnl_pct: -9.8 }),            // 1,4 meses: sin «por año»
  op(3, { asset: 'KO', op_type: 'Dividendo', entry_date: null, pnl_usd: 3 }),  // un cobro
  op(4, { asset: 'TSLA', entry_date: '2025-06-10' }),                           // sin velas ese día
]
const diario = {
  tendencias: { 1: { tendencia: 'alcista', fecha: '2025-11-14', dist: 4.2 },
                2: { tendencia: 'bajista', fecha: '2026-03-13', dist: -3 },
                4: { tendencia: null, motivo: 'sin_precio' } },
  estadoTendencias: 'listo',
  tesis: [{ id: 9, asset: 'NVDA', escrita_el: '2025-11-14', texto: 'Data centers e IA' }],
}
const tabla = () => renderToStaticMarkup(
  <MemoryRouter>
    <TradesTable
      ops={ops} filteredOps={ops} pagedOps={ops} groups={[]} grouped={false} groupBy="none"
      histMoney={histMoney} expandedGroups={new Set()} onToggleGroup={() => {}}
      onEdit={() => {}} onDelete={() => {}} onDeleteGroup={() => {}}
      onAdd={() => {}} page={0} totalPages={1} onPage={() => {}} diario={diario}
    />
  </MemoryRouter>,
)
const fila = (html, asset) => html.split('<tr').find(f => f.includes(`>${asset}<`))
const sinTags = (h) => h.replace(/<[^>]+>/g, '|').replace(/\|+/g, '|')

describe('tabla de cerradas: columnas nuevas', () => {
  it('encabezados', () => {
    const html = tabla()
    for (const t of ['Tiempo', 'Por año', 'Tendencia al comprar', 'Tu tesis']) expect(html).toContain(t)
  })
  it('una venta de 5,4 meses: tiempo, por año, Alcista y su tesis', () => {
    const f = sinTags(fila(tabla(), 'NVDA'))
    expect(f).toContain('5,4 meses')
    expect(f).toMatch(/−0,7\s?%|-0,7\s?%/)
    expect(f).toContain('Alcista')
    expect(f).toContain('Data centers e IA')
  })
  it('menos de 3 meses: «—» en por año y el porqué en el globo', () => {
    const f = fila(tabla(), 'MELI')
    expect(f).toContain('con menos de 3 meses, pasarlo a un año infla el número')
    expect(f).toContain('Bajista')
  })
  it('un cobro no tiene tiempo, por año ni tendencia', () => {
    const f = sinTags(fila(tabla(), 'KO'))
    expect(f).not.toMatch(/Alcista|Bajista|sin dato|meses|días/)
  })
  it('sin velas ese día: «sin dato» con el motivo', () => {
    const f = fila(tabla(), 'TSLA')
    expect(f).toContain('sin dato')
    expect(f).toContain('No hay precios de ese día')
  })
  it('si el pedido de tendencias falló, lo dice (no «no tenemos precios»)', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <TradesTable ops={ops} filteredOps={ops} pagedOps={ops} groups={[]} grouped={false} groupBy="none"
          histMoney={histMoney} expandedGroups={new Set()} onToggleGroup={() => {}}
          onEdit={() => {}} onDelete={() => {}} onDeleteGroup={() => {}}
          onAdd={() => {}} page={0} totalPages={1} onPage={() => {}}
          diario={{ ...diario, tendencias: {}, estadoTendencias: 'error' }} />
      </MemoryRouter>)
    const f = fila(html, 'NVDA')
    expect(f).toContain('sin dato')
    expect(f).toContain('No pudimos traer los precios')
    const r = resumenDiario(ops, {})
    expect(renderToStaticMarkup(<DiarioResumen resumen={r} estadoTendencias="error" />)).toContain('no pudimos traer los precios')
  })
  it('sin `diario` (antes de que llegue) la tabla se dibuja igual', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <TradesTable ops={ops} filteredOps={ops} pagedOps={ops} groups={[]} grouped={false} groupBy="none"
          histMoney={histMoney} expandedGroups={new Set()} onToggleGroup={() => {}}
          onEdit={() => {}} onDelete={() => {}} onDeleteGroup={() => {}}
          onAdd={() => {}} page={0} totalPages={1} onPage={() => {}} />
      </MemoryRouter>)
    expect(html).toContain('5,4 meses')
  })
})

describe('celular: el mismo diario en cada tarjeta', () => {
  it('tiempo, por año, tendencia y tesis', () => {
    const html = sinTags(renderToStaticMarkup(
      <TradesFeed groups={[{ key: 'd', label: '28/04', rows: ops }]} histMoney={histMoney} diario={diario} />))
    expect(html).toContain('5,4 meses')
    expect(html).toContain('por año')
    expect(html).toContain('Alcista')
    expect(html).toContain('Tu tesis: «Data centers e IA»')
  })
})

describe('tarjetas y frase', () => {
  it('se dibujan con los números del resumen', () => {
    const r = resumenDiario([...ops, op(5, { pnl_usd: 10, pnl_pct: 20, entry_date: '2025-01-01' })], diario.tendencias)
    const html = sinTags(renderToStaticMarkup(<DiarioResumen resumen={r} />))
    expect(html).toContain('Tiempo que las tuviste')
    expect(html).toContain('Rendimiento por año')
    expect(html).toContain('Compraste con tendencia a favor')
    expect(html).toContain('Lo que dicen tus números:')
    expect(html).toContain('no anticipa')
  })
  it('sin cerradas no dibuja nada', () => {
    expect(renderToStaticMarkup(<DiarioResumen resumen={resumenDiario([])} />)).toBe('')
  })
})

describe('la tesis de una posición abierta', () => {
  const tesis = { estado: 'listo', items: diario.tesis, hoy: { NVDA: { tendencia: 'bajista', dist: -8.1 } }, recargar: () => {} }
  it('muestra el texto, la tendencia de ese día y la de hoy, y el recordatorio', () => {
    const html = sinTags(renderToStaticMarkup(<TesisDelActivo asset="NVDA" tesis={{ ...tesis, items: [{ ...diario.tesis[0], tendencia: { tendencia: 'alcista' } }] }} />))
    expect(html).toContain('«Data centers e IA»')
    expect(html).toContain('Cuando la escribiste el precio estaba arriba de su promedio de 200 días (alcista). Hoy está 8,1 % abajo: bajista.')
    expect(html).toContain('Recordarme revisarla')
    expect(html).toContain('Después del próximo balance')
  })
  it('sin tesis: el campo para escribirla', () => {
    const html = renderToStaticMarkup(<TesisDelActivo asset="AAPL" tesis={tesis} />)
    expect(html).toContain('¿Por qué lo compraste?')
    expect(html).toContain('<textarea')
  })
  it('recordatorio pendiente', () => {
    const items = [{ ...diario.tesis[0], recordatorio: { tipo: 'balance', fecha: '2026-11-20', avisado_at: null } }]
    const html = sinTags(renderToStaticMarkup(<TesisDelActivo asset="NVDA" tesis={{ ...tesis, items }} />))
    expect(html).toContain('Te avisamos el 20/11/26 por mail y notificación, el día después del balance.')
  })
  it('si el servidor no contesta (o es el demo) no se muestra', () => {
    expect(renderToStaticMarkup(<TesisDelActivo asset="NVDA" tesis={{ ...tesis, estado: 'error' }} />)).toBe('')
  })
  it('bono sin lectura', () => {
    expect(lineaDeTendencias({ tendencia: null }, { tendencia: null, motivo: 'sin_velas' })).toMatch(/bonos y fondos/)
  })
  it('posiciones abiertas por activo, sin efectivo, desde la compra más vieja', () => {
    expect(abiertasPorActivo([
      { asset: 'NVDA', quantity: 2, entry_date: '2025-11-14' },
      { asset: 'NVDA', quantity: 1, entry_date: '2025-02-01' },
      { asset: 'USD', quantity: 100, is_cash: 1 },
      { asset: 'GGAL', quantity: 0 },
    ]).map(g => [g.asset, g.lots.length, g.desde])).toEqual([['NVDA', 2, '2025-02-01']])
  })
})
