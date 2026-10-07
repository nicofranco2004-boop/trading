import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import TradesTable from './TradesTable'
import TradesFeed from './TradesFeed'
import MovementsTable from './MovementsTable'
import MovementsFeed from './MovementsFeed'
import { nuevasDe, paginaDeLaNueva } from '../../hooks/useRecienLlegadas'

// La operación que el usuario acaba de cargar destella (`.destello-nueva`). Se
// cuenta cuántas veces aparece la marca y en qué fila, dibujando los mismos
// renderers que usa Operations en la compu (tabla) y en el celular (tarjetas).
const histMoney = new Proxy({ currency: 'USD' }, {
  get: (t, k) => (k in t ? t[k] : String(k).startsWith('sum') ? () => 0 : () => 'US$ 1'),
})
const op = (id, asset) => ({
  id, asset, broker: 'Schwab', op_type: 'Venta', date: '2026-09-30', quantity: 1,
  entry_price: 1, exit_price: 2, pnl_usd: 1, pnl_pct: 1, currency: 'USD',
})
const A = op(1, 'AAPL'), B = op(2, 'NVDA')
const grupo = { key: 'NVDA', label: 'NVDA', count: 1, brokers: ['Schwab'], rows: [B] }
const cuantas = html => (html.match(/destello-nueva/g) || []).length
// Las filas de la tabla, para saber CUÁL destella.
const filas = html => html.split('<tr').slice(1)
const tabla = props => renderToStaticMarkup(
  <MemoryRouter>
    <TradesTable
      ops={[A, B]} filteredOps={[A, B]} pagedOps={[A, B]} groups={[]} grouped={false} groupBy="none"
      histMoney={histMoney} expandedGroups={new Set()} onToggleGroup={() => {}}
      onEdit={() => {}} onDelete={() => {}} onDeleteGroup={() => {}}
      onAdd={() => {}} page={1} totalPages={1} onPage={() => {}}
      {...props}
    />
  </MemoryRouter>,
)

describe('la operación recién cargada destella', () => {
  it('tabla sin agrupar: sólo la fila nueva', () => {
    const html = tabla({ nuevas: new Set([2]) })
    expect(cuantas(html)).toBe(1)
    const conDestello = filas(html).find(f => f.includes('destello-nueva'))
    expect(conDestello).toContain('NVDA')
    expect(conDestello).not.toContain('AAPL')
  })
  it('sin nada nuevo (al entrar, al filtrar, al editar), nada destella', () => {
    expect(cuantas(tabla({}))).toBe(0)
  })
  it('agrupada con el grupo CERRADO: destella el grupo, sin abrirlo', () => {
    const html = tabla({ grouped: true, groupBy: 'asset', groups: [grupo], nuevas: new Set([2]) })
    expect(cuantas(html)).toBe(1)
    expect(html).not.toContain('└')   // el detalle sigue cerrado
    expect(filas(html).find(f => f.includes('destello-nueva'))).toContain('aria-expanded="false"')
  })
  it('agrupada con el grupo ABIERTO: destella la fila, no el grupo', () => {
    const html = tabla({ grouped: true, groupBy: 'asset', groups: [grupo], expandedGroups: new Set(['NVDA']), nuevas: new Set([2]) })
    expect(cuantas(html)).toBe(1)
    const conDestello = filas(html).find(f => f.includes('destello-nueva'))
    expect(conDestello).toContain('└')                    // es la fila del detalle
    expect(conDestello).not.toContain('aria-expanded')     // y no la del grupo
  })
  it('celular: sólo la tarjeta nueva', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <TradesFeed groups={[{ key: '2026-09-30', label: 'Hoy', rows: [A, B] }]} histMoney={histMoney} onDelete={() => {}} nuevas={new Set([2])} />
      </MemoryRouter>,
    )
    expect(cuantas(html)).toBe(1)
    expect(cuantas(renderToStaticMarkup(
      <MemoryRouter><TradesFeed groups={[{ key: 'x', label: 'Hoy', rows: [A, B] }]} histMoney={histMoney} onDelete={() => {}} /></MemoryRouter>,
    ))).toBe(0)
  })
})

// "Todos los movimientos": la pestaña que se abre de entrada.
const mov = (id, asset, type = 'SELL') => ({
  id, type, asset, broker: 'Schwab', date: '2026-09-30', amount_usd: 100, amount: 100,
  currency: 'USD', fx_to_usd: 1, quantity: 1, price: 100,
})
const M1 = mov('m1', 'AAPL'), M2 = mov('m2', 'MELI')
const grupoMov = { key: 'MELI', label: 'MELI', count: 1, brokers: ['Schwab'], rows: [M2] }
const tablaMov = props => renderToStaticMarkup(
  <MemoryRouter>
    <MovementsTable
      movements={[M1, M2]} filtered={[M1, M2]} pageRows={[M1, M2]} groups={[]} grouped={false} groupBy="none"
      histMoney={histMoney} currency="USD" expandedGroups={new Set()} onToggleGroup={() => {}}
      onDelete={() => {}} onDeleteGroup={() => {}}
      page={1} totalPages={1} onPage={() => {}}
      {...props}
    />
  </MemoryRouter>,
)

describe('todos los movimientos: el recién agregado destella', () => {
  it('tabla: sólo la fila nueva; sin nada nuevo, nada', () => {
    const html = tablaMov({ nuevas: new Set(['m2']) })
    expect(cuantas(html)).toBe(1)
    const f = filas(html).find(x => x.includes('destello-nueva'))
    expect(f).toContain('MELI')
    expect(f).not.toContain('AAPL')
    expect(cuantas(tablaMov({}))).toBe(0)
  })
  it('agrupada y cerrada: destella el grupo', () => {
    const html = tablaMov({ grouped: true, groupBy: 'asset', groups: [grupoMov], nuevas: new Set(['m2']) })
    expect(cuantas(html)).toBe(1)
    expect(filas(html).find(x => x.includes('destello-nueva'))).toContain('aria-expanded="false"')
  })
  it('celular: sólo la tarjeta nueva', () => {
    const html = renderToStaticMarkup(
      <MemoryRouter><MovementsFeed groups={[{ key: 'd', label: 'Hoy', rows: [M1, M2] }]} histMoney={histMoney} onDelete={() => {}} nuevas={new Set(['m2'])} /></MemoryRouter>,
    )
    expect(cuantas(html)).toBe(1)
  })
})

describe('nuevasDe — qué llegó recién', () => {
  it('las que no estaban antes de guardar', () => {
    expect([...nuevasDe(new Set([1, 2]), [{ id: 3 }, { id: 1 }, { id: 2 }])]).toEqual([3])
  })
  it('la primera operación de una cuenta vacía también es nueva', () => {
    expect([...nuevasDe(new Set(), [{ id: 7 }])]).toEqual([7])
  })
  it('sin filas o sin ids, nada', () => {
    expect(nuevasDe(new Set([1]), null).size).toBe(0)
    expect(nuevasDe(new Set(), [{ nombre: 'x' }]).size).toBe(0)
  })
})

describe('paginaDeLaNueva — la lista salta a donde quedó la nueva', () => {
  const lista = Array.from({ length: 120 }, (_, i) => ({ id: i }))
  it('página (desde 0) de la primera fila nueva', () => {
    expect(paginaDeLaNueva(lista, new Set([0]), 50)).toBe(0)
    expect(paginaDeLaNueva(lista, new Set([75]), 50)).toBe(1)
    expect(paginaDeLaNueva(lista, new Set([119, 3]), 50)).toBe(0)
  })
  it('si un filtro la esconde, o no hay nada nuevo, no salta', () => {
    expect(paginaDeLaNueva(lista, new Set([999]), 50)).toBe(-1)
    expect(paginaDeLaNueva(lista, new Set(), 50)).toBe(-1)
  })
})

