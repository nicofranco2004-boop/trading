import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => new Promise(() => {})), post: vi.fn() } }))

import MovementsTable from './MovementsTable'
import MovementsFeed from './MovementsFeed'
import { TYPE_META, MOVEMENT_TYPES, DELETABLE_MOVEMENT_TYPES } from './shared'
import { resolveHistoricalFx } from '../../hooks/useHistoricalMoney'

// Una conversión de moneda en Movimientos. Las filas son las que devuelve
// GET /api/movements (copiadas de una medición real, 2026-10-07): la compra de
// US$10 con $15.400 que antes llegaba como SELL de US$23.710.610.
const compra = {
  id: 'op-1-fx', kind: 'movement', date: '2024-03-05', type: 'FX_ARS_TO_USD',
  broker: 'IOL', asset: 'ARS→USD', quantity: 10.002273243919072, unit_price: 1539.65,
  amount_usd: 10.002273243919072, currency: 'ARS', fx_to_usd: 1539.65, fees_usd: 0,
  pnl_usd: 0, notes: '', source: 'manual', ref_id: 1,
}
const venta = {
  ...compra, id: 'op-2-fx', type: 'FX_USD_TO_ARS', broker: 'IOL · USD', asset: 'USD→ARS',
  quantity: 4, unit_price: 1600, amount_usd: 4, fx_to_usd: 1600, pnl_usd: 0.15, ref_id: 2,
}

// El formateador de verdad hace `amount_usd × fx` en pesos; acá alcanza con
// ver QUÉ número le llega, en dólares.
const histMoney = new Proxy({ currency: 'USD' }, {
  get: (t, k) => (k in t ? t[k]
    : k === 'fmtMoneyAt' ? (v) => `US$ ${Number(v).toFixed(2)}`
    : String(k).startsWith('sum') ? () => 0 : () => 'US$ 1'),
})

const tabla = rows => renderToStaticMarkup(
  <MemoryRouter>
    <MovementsTable
      movements={rows} filtered={rows} pageRows={rows} groups={[]} grouped={false} groupBy="none"
      histMoney={histMoney} expandedGroups={new Set()} onToggleGroup={() => {}}
      onDelete={() => {}} onDeleteGroup={() => {}} page={0} totalPages={1} onPage={() => {}}
      deletingId={null} busyGroup={{}} nuevas={new Set()}
    />
  </MemoryRouter>,
)
const feed = rows => renderToStaticMarkup(
  <MemoryRouter>
    <MovementsFeed groups={[{ key: '2024-03-05', label: '5 Mar 2024', rows }]} histMoney={histMoney} onDelete={() => {}} />
  </MemoryRouter>,
)

describe('una conversión de moneda en Movimientos', () => {
  it('dice "Compra de USD" / "Venta de USD", no "Venta" ni el código crudo', () => {
    for (const html of [tabla([compra, venta]), feed([compra, venta])]) {
      expect(html).toContain('Compra de USD')
      expect(html).toContain('Venta de USD')
      expect(html).not.toContain('FX_ARS_TO_USD')
      expect(html).not.toContain('FX_USD_TO_ARS')
      expect(html).not.toMatch(/>Venta</)
    }
  })

  it('el monto que se muestra son los dólares de la operación', () => {
    for (const html of [tabla([compra]), feed([compra])]) {
      expect(html).toContain('US$ 10.00')
      expect(html).not.toContain('23710610')
    }
  })

  it('en la vista en pesos multiplica por el TC de la propia conversión: $15.400', () => {
    // Prioridad 1 de resolveHistoricalFx: el TC sellado, porque la fila es ARS.
    // El dólar de hoy (1500) y el de la fecha (1450) NO tienen que ganar.
    const fx = resolveHistoricalFx('ARS', 1500, {
      stampedFx: compra.fx_to_usd, rowCurrency: compra.currency, dateIso: compra.date,
    }, () => 1450)
    expect(compra.amount_usd * fx).toBeCloseTo(15400, 2)
  })

  it('una conversión VIEJA no ofrece borrar: sin receta no se puede revertir', () => {
    // Antes salía como SELL → tacho → "¿Borrar venta de ARS→USDT (US$ 23.710.610)?"
    // → 400. Las que no guardaron su receta siguen sin tacho: en una compra de
    // dólares vieja ni siquiera quedó cuántos dólares entraron.
    expect(DELETABLE_MOVEMENT_TYPES).not.toContain('FX_ARS_TO_USD')
    expect(DELETABLE_MOVEMENT_TYPES).not.toContain('FX_USD_TO_ARS')
    expect(tabla([compra])).not.toContain('Borrar movimiento')
    expect(feed([compra])).not.toContain('Borrar movimiento')
  })

  it('una conversión CON receta sí ofrece borrar, en la tabla y en el celular', () => {
    // Desde 2026-10-09 el backend la marca `borrable` y su borrado devuelve las
    // dos monedas (test_operaciones_con_receta.py).
    for (const fila of [{ ...compra, borrable: true }, { ...venta, borrable: true }]) {
      expect(tabla([fila])).toContain('Borrar movimiento')
      expect(feed([fila])).toContain('Borrar movimiento')
    }
  })

  it('tiene rótulo y chip de filtro, como el resto de los tipos', () => {
    for (const t of ['FX_ARS_TO_USD', 'FX_USD_TO_ARS']) {
      expect(TYPE_META[t]?.label).toBeTruthy()
      expect(MOVEMENT_TYPES.some(x => x.id === t)).toBe(true)
    }
  })
})
