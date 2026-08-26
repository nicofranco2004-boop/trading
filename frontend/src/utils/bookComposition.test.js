import { describe, it, expect } from 'vitest'
import { assetSlicesFromRows, mostHeldAssets, pfSlice, DEFAULT_TOP_ASSETS } from './bookComposition.js'
import { computeClassBreakdown } from './assetClass.js'
import { computeSectorBreakdown } from './assetSector.js'

// Una fila tal como la devuelve GET /api/advisor/book/composition.
const row = (asset, value, extra = {}) => ({
  asset, value_usd: value, invested_usd: value, pnl_usd: 0,
  asset_type: null, is_ar_market: false, is_cash: false, clients: 1, ...extra,
})

describe('assetSlicesFromRows — la cola larga del libro', () => {
  it('con pocos activos no inventa un "Resto"', () => {
    const { items, total } = assetSlicesFromRows([row('AAPL', 100), row('GGAL', 50)])
    expect(items.map(i => i.key)).toEqual(['AAPL', 'GGAL'])
    expect(total).toBe(150)
    expect(items[0].pct).toBeCloseTo(66.7, 1)
  })

  it('486 tickers no dejan una torta de "Otros": top-N + un Resto que dice cuántos', () => {
    // El caso real del libro de 100 clientes. Sin el corte explícito, todos
    // menos un puñado caen bajo el 1,5% de CompositionDonut y el "Otros"
    // emergente se come la torta sin explicar nada.
    const rows = Array.from({ length: 486 }, (_, i) => row(`T${i}`, 1000 - i))
    const { items } = assetSlicesFromRows(rows)

    expect(items).toHaveLength(DEFAULT_TOP_ASSETS + 1)
    const resto = items[items.length - 1]
    expect(resto.key).toBe('__resto__')
    expect(resto.label).toBe('Resto (474 activos)')
    expect(resto.assets).toHaveLength(474)
  })

  it('el Resto se puede desplegar y sus % suman su propio peso', () => {
    const rows = Array.from({ length: 20 }, (_, i) => row(`T${i}`, 100))
    const { items } = assetSlicesFromRows(rows, [], 5)
    const resto = items[items.length - 1]
    const suma = resto.assets.reduce((s, a) => s + a.pct, 0)
    expect(suma).toBeCloseTo(resto.pct, 6)
  })

  it('los porcentajes de todas las porciones suman 100', () => {
    const rows = Array.from({ length: 50 }, (_, i) => row(`T${i}`, (i + 1) * 10))
    const { items } = assetSlicesFromRows(rows)
    expect(items.reduce((s, i) => s + i.pct, 0)).toBeCloseTo(100, 6)
  })

  it('un solo activo sobrante igual entra como Resto (1 activo), en singular', () => {
    const rows = Array.from({ length: 6 }, (_, i) => row(`T${i}`, 100))
    const { items } = assetSlicesFromRows(rows, [], 5)
    expect(items[items.length - 1].label).toBe('Resto (1 activo)')
  })
})

describe('assetSlicesFromRows — consolidación por ticker', () => {
  it('el mismo activo en los dos mercados es UNA porción', () => {
    // La exposición a Apple es la exposición a Apple: el CEDEAR en Balanz y la
    // acción en Schwab son el mismo riesgo. Las tortas de tipo y sector sí los
    // separan, porque ahí la pregunta es otra.
    const { items } = assetSlicesFromRows([
      row('AAPL', 100, { is_ar_market: true, asset_type: 'CEDEAR', clients: 3 }),
      row('AAPL', 50, { is_ar_market: false, clients: 2 }),
    ])
    expect(items).toHaveLength(1)
    expect(items[0].value).toBe(150)
  })

  it('el sufijo .BA no parte el activo en dos porciones', () => {
    const { items } = assetSlicesFromRows([row('AMD', 100), row('AMD.BA', 50)])
    expect(items).toHaveLength(1)
    expect(items[0].key).toBe('AMD')
    expect(items[0].value).toBe(150)
  })

  it('el conteo de clientes no se suma entre filas del mismo ticker', () => {
    // Sumar contaría dos veces al cliente que lo tiene en los dos mercados. El
    // máximo es el piso correcto: nunca miente para arriba.
    const { items } = assetSlicesFromRows([
      row('AAPL', 100, { clients: 3 }),
      row('AAPL', 50, { clients: 2 }),
    ])
    expect(items[0].clients).toBe(3)
  })

  it('el símbolo canónico de un FCI se muestra legible', () => {
    const { items } = assetSlicesFromRows([row('FCI:FIMA-PREMIUM-A', 100)])
    expect(items[0].key).toBe('FCI:FIMA-PREMIUM-A')
    expect(items[0].label).toBe('FIMA Premium · A')
  })

  it('ignora filas sin valor', () => {
    const { items, total } = assetSlicesFromRows([
      row('AAPL', 100), row('ZZZ', 0), row('QQQ', null), { asset: '', value_usd: 5 },
    ])
    expect(items).toHaveLength(1)
    expect(total).toBe(100)
  })

  it('libro vacío devuelve el shape vacío, no revienta', () => {
    expect(assetSlicesFromRows([])).toEqual({
      items: [], total: 0, unclassified: { value: 0, pct: 0, assets: [] },
    })
    expect(assetSlicesFromRows()).toEqual({
      items: [], total: 0, unclassified: { value: 0, pct: 0, assets: [] },
    })
  })
})

describe('assetSlicesFromRows — plazos fijos como porción sintética', () => {
  const pf = { key: 'plazo_fijo', label: 'Plazos fijos', value: 100, color: '#C98A2E' }

  it('entra en el total y no compite por el top-N', () => {
    const rows = Array.from({ length: 20 }, (_, i) => row(`T${i}`, 100))
    const { items, total } = assetSlicesFromRows(rows, [pf], 5)
    expect(total).toBe(2100)
    // 5 activos + el plazo fijo + el resto
    expect(items).toHaveLength(7)
    expect(items.find(i => i.key === 'plazo_fijo').pct).toBeCloseTo(100 / 2100 * 100, 6)
    expect(items[items.length - 1].key).toBe('__resto__')
  })

  it('sin plazos fijos no aparece la porción', () => {
    const { items } = assetSlicesFromRows([row('AAPL', 100)], [])
    expect(items.map(i => i.key)).toEqual(['AAPL'])
  })
})

describe('mostHeldAssets — "¿en qué están todos?"', () => {
  it('ordena por cantidad de clientes, no por valor', () => {
    const out = mostHeldAssets([
      row('GRANDE', 1_000_000, { clients: 2 }),
      row('CHICO', 10, { clients: 9 }),
      row('MEDIO', 500, { clients: 5 }),
    ])
    expect(out.map(a => a.asset)).toEqual(['CHICO', 'MEDIO', 'GRANDE'])
  })

  it('un activo que tiene un solo cliente no es "difundido"', () => {
    expect(mostHeldAssets([row('SOLO', 100, { clients: 1 })])).toEqual([])
  })

  it('consolida el mismo ticker de los dos mercados sin duplicar el conteo', () => {
    const out = mostHeldAssets([
      row('AAPL', 100, { is_ar_market: true, clients: 4 }),
      row('AAPL', 50, { is_ar_market: false, clients: 3 }),
    ])
    expect(out).toEqual([{ asset: 'AAPL', clients: 4 }])
  })
})

describe('pfSlice', () => {
  it('null cuando no hay plazos fijos (no dibujar una porción en cero)', () => {
    expect(pfSlice({ plazos_fijos_usd: 0 }, 'plazo_fijo')).toBeNull()
    expect(pfSlice(null, 'plazo_fijo')).toBeNull()
  })

  it('lleva el resultado devengado con su costo al lado', () => {
    const s = pfSlice({ plazos_fijos_usd: 110, plazos_fijos_invested_usd: 100 }, 'plazo_fijo')
    expect(s.value).toBe(110)
    expect(s.pnl).toEqual({ total: 10, cost: 100 })
  })

  it('sin label ni color para las tortas de tipo y sector (usan su meta)', () => {
    const s = pfSlice({ plazos_fijos_usd: 110, plazos_fijos_invested_usd: 100 }, 'renta_fija')
    expect(s.label).toBeUndefined()
    expect(s.color).toBeUndefined()
  })
})

// ── El punto de todo esto: las filas del backend se clasifican con el
//    clasificador del retail, sin tocarlo. ────────────────────────────────
describe('las filas del libro alimentan los clasificadores del retail', () => {
  const rows = [
    row('AAPL', 300, { is_ar_market: true, clients: 5 }),     // CEDEAR
    row('AAPL', 200, { is_ar_market: false, clients: 2 }),    // acción US
    row('GGAL', 100, { is_ar_market: true }),                 // acción AR
    row('AL30', 150, { is_ar_market: true }),                 // bono
    row('USD', 250, { is_cash: true }),                       // efectivo
  ]

  it('computeClassBreakdown corre sin lista de brokers', () => {
    const { items, total } = computeClassBreakdown(rows, [])
    expect(total).toBe(1000)
    const by = Object.fromEntries(items.map(i => [i.key, i.value]))
    expect(by.cedear).toBe(300)
    expect(by.accion_us).toBe(200)
    expect(by.accion_ar).toBe(100)
    expect(by.bono).toBe(150)
    expect(by.cash).toBe(250)
  })

  it('computeSectorBreakdown también', () => {
    const { items } = computeSectorBreakdown(rows, [])
    const by = Object.fromEntries(items.map(i => [i.key, i.value]))
    expect(by.tecnologia).toBe(500)     // el CEDEAR y la acción, mismo sector
    expect(by.financiero).toBe(100)     // GGAL
    expect(by.renta_fija).toBe(150)
    expect(by.efectivo).toBe(250)
  })

  it('las tres tortas suman EXACTAMENTE el mismo total', () => {
    // Si no, la pantalla muestra tres denominadores distintos para el mismo
    // libro y ninguno se puede creer.
    const extraPfClase = [pfSlice({ plazos_fijos_usd: 500, plazos_fijos_invested_usd: 480 }, 'plazo_fijo')]
    const extraPfSector = [pfSlice({ plazos_fijos_usd: 500, plazos_fijos_invested_usd: 480 }, 'renta_fija')]
    const extraPfActivo = [pfSlice({ plazos_fijos_usd: 500, plazos_fijos_invested_usd: 480 }, 'plazo_fijo', 'Plazos fijos')]

    const clase = computeClassBreakdown(rows, [], extraPfClase)
    const sector = computeSectorBreakdown(rows, [], extraPfSector)
    const activo = assetSlicesFromRows(rows, extraPfActivo)

    expect(clase.total).toBe(1500)
    expect(sector.total).toBe(1500)
    expect(activo.total).toBe(1500)
  })
})
