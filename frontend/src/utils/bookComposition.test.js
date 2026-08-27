import { describe, it, expect } from 'vitest'
import { assetSlicesFromRows, mostHeldAssets, pfSlice, realizedToOps, attachSpread, riskMixFromBreakdown, toBookCompositionAiParams, DEFAULT_TOP_ASSETS } from './bookComposition.js'
import { computeClassBreakdown, classifyAsset } from './assetClass.js'
import { opPnlUsd } from './assetPnl.js'
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

describe('realizedToOps — lo cerrado y la renta con forma de operaciones', () => {
  const rr = (asset, o = {}) => ({
    asset, asset_type: null, is_ar_market: false,
    realized_usd: 0, income_usd: 0, cost_usd: 0, cost_incomplete: false, ...o,
  })

  it('el costo viaja EXPLÍCITO, sin despejarlo de un porcentaje', () => {
    const [op] = realizedToOps([rr('AAPL', { realized_usd: 200, cost_usd: 800 })])
    expect(op.pnl_usd).toBe(200)
    expect(op.cost_usd).toBe(800)
  })

  it('con el costo incompleto no manda costo: la tasa se oculta, no se inventa', () => {
    const [op] = realizedToOps([rr('AAPL', { realized_usd: 200, cost_usd: 0, cost_incomplete: true })])
    expect(op.cost_usd).toBeUndefined()
  })

  it('separa la venta de la renta en dos filas', () => {
    const ops = realizedToOps([rr('AL30', { realized_usd: 50, cost_usd: 500, income_usd: 120 })])
    expect(ops).toHaveLength(2)
    expect(ops.map(o => o.op_type)).toEqual(['Venta', 'Dividendo'])
    expect(ops[1].cost_usd).toBeUndefined()   // la renta no aporta costo
  })

  it('el resultado NETO cero igual manda su costo al denominador', () => {
    // Un cliente vendió +500 y otro −500: el neto es 0, pero los US$10.000 que
    // estuvieron en juego van al denominador igual. Antes la fila no emitía
    // ninguna operación y la porción publicaba un % 6x más alto que el real.
    const ops = realizedToOps([rr('AAPL', { realized_usd: 0, cost_usd: 10000 })])
    expect(ops).toHaveLength(1)
    expect(ops[0].pnl_usd).toBe(0)
    expect(ops[0].cost_usd).toBe(10000)
  })

  it('neto cero SIN costo confiable no emite nada', () => {
    expect(realizedToOps([rr('AAPL', { realized_usd: 0, cost_usd: 10000, cost_incomplete: true })])).toEqual([])
  })

  it('no emite filas para montos en cero', () => {
    expect(realizedToOps([rr('AAPL')])).toEqual([])
    expect(realizedToOps([])).toEqual([])
    expect(realizedToOps()).toEqual([])
  })

  it('lleva el tipo y el mercado para que el clasificador acierte la porción', () => {
    const [op] = realizedToOps([
      rr('KO', { realized_usd: 40, cost_usd: 200, asset_type: 'CEDEAR', is_ar_market: true }),
    ])
    expect(op.asset_type).toBe('CEDEAR')
    expect(op.is_ar_market).toBe(true)
  })
})

describe('resultado por porción, de punta a punta', () => {
  const rows = [
    { asset: 'AAPL', value_usd: 1200, invested_usd: 1000, pnl_usd: 200, is_ar_market: true, is_cash: false, asset_type: 'CEDEAR', clients: 3 },
    { asset: 'AL30', value_usd: 500, invested_usd: 500, pnl_usd: 0, is_ar_market: true, is_cash: false, asset_type: 'BONO', clients: 2 },
  ]

  it('suma las tres patas: no realizado + realizado + renta', () => {
    const ops = realizedToOps([
      { asset: 'AAPL', asset_type: 'CEDEAR', is_ar_market: true, realized_usd: 100, income_usd: 0, cost_usd: 400, cost_incomplete: false },
      { asset: 'AL30', asset_type: 'BONO', is_ar_market: true, realized_usd: 0, income_usd: 80, cost_usd: 0, cost_incomplete: false },
    ])
    const { items } = computeClassBreakdown(rows, [], [], ops)
    const cedear = items.find(i => i.key === 'cedear')
    const bono = items.find(i => i.key === 'bono')

    // CEDEAR: 200 no realizado + 100 realizado = 300, sobre 1000 + 400 = 1400.
    expect(cedear.pnl.total).toBe(300)
    expect(cedear.pnl.pct).toBeCloseTo(300 / 1400 * 100, 6)
    // Bono: todo el rendimiento está en el cupón, y no infla el denominador.
    expect(bono.pnl.total).toBe(80)
    expect(bono.pnl.income).toBe(80)
    expect(bono.pnl.pct).toBeCloseTo(80 / 500 * 100, 6)
  })

  it('sin operaciones la torta sigue funcionando (solo peso)', () => {
    const { items } = computeClassBreakdown(rows, [], [], null)
    expect(items.every(i => i.pnl === null)).toBe(true)
  })

  it('el plazo fijo aporta su devengado y su costo a la porción', () => {
    const pf = pfSlice({ plazos_fijos_usd: 110, plazos_fijos_invested_usd: 100 }, 'plazo_fijo')
    const { items } = computeClassBreakdown(rows, [], [pf], [])
    const slice = items.find(i => i.key === 'plazo_fijo')
    expect(slice.pnl.total).toBe(10)
    expect(slice.pnl.pct).toBeCloseTo(10, 6)
  })
})

describe('toBookCompositionAiParams — el packet del libro para la IA', () => {
  const rows = [
    { asset: 'AAPL', value_usd: 600, invested_usd: 500, pnl_usd: 100, is_ar_market: true, is_cash: false, asset_type: 'CEDEAR', clients: 9 },
    { asset: 'USD', value_usd: 400, invested_usd: 400, pnl_usd: 0, is_ar_market: false, is_cash: true, clients: 12 },
  ]

  it('lleva el corte de siempre más el contexto del libro', () => {
    const bd = computeClassBreakdown(rows, [])
    const p = toBookCompositionAiParams(bd, { clients: 12, mostHeld: mostHeldAssets(rows) })
    expect(p.total_usd).toBe(1000)
    expect(p.slices.map(s => s.label)).toEqual(['CEDEARs', 'Efectivo'])
    expect(p.clientes).toBe(12)
    expect(p.mas_difundidos).toEqual([{ a: 'USD', c: 12 }, { a: 'AAPL', c: 9 }])
  })

  it('sin contexto de libro no inventa las claves', () => {
    const p = toBookCompositionAiParams(computeClassBreakdown(rows, []))
    expect(p.clientes).toBeUndefined()
    expect(p.mas_difundidos).toBeUndefined()
  })
})

describe('attachSpread — el rango entre clientes al lado del % agrupado', () => {
  const rows = [
    { asset: 'AAPL', value_usd: 600, invested_usd: 500, pnl_usd: 100, is_ar_market: false, is_cash: false, clients: 5 },
    { asset: 'GGAL', value_usd: 400, invested_usd: 380, pnl_usd: 20, is_ar_market: true, is_cash: false, clients: 3 },
  ]
  const spread = [
    { asset: 'AAPL', is_ar_market: false, clients: 5, clients_total: 5, min_pct: -20.4, max_pct: 38.1 },
    { asset: 'GGAL', is_ar_market: true, clients: 3, clients_total: 3, min_pct: 1.2, max_pct: 9.0 },
  ]
  const opts = { rows, classify: classifyAsset }

  it('pega el rango a cada activo sin tocar porciones ni porcentajes', () => {
    const bd = computeClassBreakdown(rows, [], [], [])
    const out = attachSpread(bd, spread, opts)
    expect(out.total).toBe(bd.total)
    expect(out.items.map(i => i.pct)).toEqual(bd.items.map(i => i.pct))
    const aapl = out.items.flatMap(i => i.assets).find(a => a.asset === 'AAPL')
    expect(aapl.spread).toEqual(spread[0])
  })

  it('un activo sin rango queda sin el campo (no un objeto vacío)', () => {
    const out = attachSpread(computeClassBreakdown(rows, [], [], []), [spread[0]], opts)
    const ggal = out.items.flatMap(i => i.assets).find(a => a.asset === 'GGAL')
    expect(ggal.spread).toBeUndefined()
  })

  it('normaliza el .BA para matchear', () => {
    const r = [{ asset: 'AMD.BA', value_usd: 100, invested_usd: 90, pnl_usd: 10, is_ar_market: true, is_cash: false }]
    const out = attachSpread(computeClassBreakdown(r, [], [], []),
      [{ asset: 'AMD', is_ar_market: true, clients: 4, clients_total: 4, min_pct: -3, max_pct: 12 }],
      { rows: r, classify: classifyAsset })
    expect(out.items.flatMap(i => i.assets)[0].spread.clients).toBe(4)
  })

  it('sin rangos no agrega ningún rango, pero igual estampa el mercado', () => {
    // El mercado va siempre: lo necesita el detalle por cliente para no
    // mezclar el CEDEAR con la acción del exterior.
    const bd = computeClassBreakdown(rows, [], [], [])
    for (const arg of [[], null]) {
      const out = attachSpread(bd, arg, opts)
      const assets = out.items.flatMap(i => i.assets)
      expect(assets.every(a => a.spread === undefined)).toBe(true)
      expect(assets.find(a => a.asset === 'AAPL').market).toBe(false)
      expect(assets.find(a => a.asset === 'GGAL').market).toBe(true)
      // y no tocó ni los pesos ni el total
      expect(out.total).toBe(bd.total)
      expect(out.items.map(i => i.pct)).toEqual(bd.items.map(i => i.pct))
    }
  })

  it('sin breakdown devuelve lo que le dieron', () => {
    expect(attachSpread(null, [], opts)).toBeNull()
    const vacio = computeClassBreakdown([], [])
    expect(attachSpread(vacio, [], opts)).toBe(vacio)
  })
})

// ─── El rango tiene que describir la MISMA población que el % de al lado ───
// El mismo papel comprado como CEDEAR y como acción del exterior cae en
// porciones DISTINTAS de la torta por tipo. Medido en el libro demo: la fila
// de NU en "Acciones US" mostraba +6,8% con un rango de +14,8% a +41,5% — el
// de los dos mercados juntos, o sea de otra población.
describe('attachSpread — el mercado tiene que coincidir con la porción', () => {
  const rows = [
    { asset: 'NU', value_usd: 300, invested_usd: 200, pnl_usd: 100, is_ar_market: true, is_cash: false, clients: 4 },
    { asset: 'NU', value_usd: 200, invested_usd: 190, pnl_usd: 10, is_ar_market: false, is_cash: false, clients: 3 },
  ]
  const spread = [
    { asset: 'NU', is_ar_market: true, clients: 4, clients_total: 4, min_pct: 20, max_pct: 80 },
    { asset: 'NU', is_ar_market: false, clients: 3, clients_total: 3, min_pct: -5, max_pct: 12 },
  ]

  it('cada porción recibe el rango de SU mercado', () => {
    const out = attachSpread(computeClassBreakdown(rows, [], [], []), spread,
      { rows, classify: classifyAsset })
    const cedear = out.items.find(i => i.key === 'cedear').assets.find(a => a.asset === 'NU')
    const usa = out.items.find(i => i.key === 'accion_us').assets.find(a => a.asset === 'NU')
    expect(cedear.spread.min_pct).toBe(20)
    expect(usa.spread.min_pct).toBe(-5)
  })

  it('el % agrupado de cada porción cae DENTRO de su rango', () => {
    const out = attachSpread(computeClassBreakdown(rows, [], [], []), spread,
      { rows, classify: classifyAsset })
    for (const i of out.items) {
      for (const a of (i.assets || [])) {
        if (!a.spread || a.pnl?.pct == null) continue
        expect(a.pnl.pct).toBeGreaterThanOrEqual(a.spread.min_pct)
        expect(a.pnl.pct).toBeLessThanOrEqual(a.spread.max_pct)
      }
    }
  })

  it('si la porción MEZCLA los dos mercados, no se muestra rango', () => {
    // Cripto en un broker AR y en un exchange caen los dos en 'cripto': ahí el
    // % suma los dos mercados y ningún rango por mercado lo describe.
    const cripto = [
      { asset: 'BTC', value_usd: 300, invested_usd: 200, pnl_usd: 100, is_ar_market: true, is_cash: false },
      { asset: 'BTC', value_usd: 200, invested_usd: 190, pnl_usd: 10, is_ar_market: false, is_cash: false },
    ]
    const out = attachSpread(computeClassBreakdown(cripto, [], [], []), [
      { asset: 'BTC', is_ar_market: true, clients: 2, clients_total: 2, min_pct: 20, max_pct: 80 },
      { asset: 'BTC', is_ar_market: false, clients: 2, clients_total: 2, min_pct: -5, max_pct: 12 },
    ], { rows: cripto, classify: classifyAsset })
    expect(out.items.find(i => i.key === 'cripto').assets[0].spread).toBeUndefined()
  })
})

// ─── La invariante que justifica todo el diseño ────────────────────────────
// El libro del asesor y la cartera del cliente tienen que dar EL MISMO número
// para la misma plata. Con un cupón en pesos hay dos caminos distintos hasta
// computePnlByKey: retail pasa la fila cruda de /api/operations, el asesor pasa
// el agregado ya convertido del backend. Si no convergen, volvimos al bug que
// en producción hizo que el dashboard dijera US$100 y la IA US$125.000.
describe('el cupón en pesos da lo mismo por los dos caminos', () => {
  // AL30 en un broker ARS: costo US$50.000, cupón de $250.000 al FX 1250.
  // Verdad: US$200 sobre US$50.000 = +0,4%.
  const posRetail = [{ asset: 'AL30', broker: 'Balanz', asset_type: 'BONO', is_cash: 0, value_usd: 50000, pnl_usd: 0 }]
  const BROKERS = [{ name: 'Balanz', currency: 'ARS' }]

  it('camino retail: la fila cruda de /api/operations', () => {
    const { items } = computeClassBreakdown(posRetail, BROKERS, [], [
      { asset: 'AL30', broker: 'Balanz', op_type: 'Cupón', pnl_usd: 250000, pnl_pct: null, currency: 'ARS', fx_to_usd: 1250 },
    ])
    const bono = items.find(i => i.key === 'bono')
    expect(bono.pnl.total).toBe(200)
    expect(bono.pnl.pct).toBeCloseTo(0.4, 6)
  })

  it('camino asesor: el agregado ya convertido del backend', () => {
    // Lo que devuelve /advisor/book/composition despues del arreglo: el cupon
    // ya viene en USD (realized_usd_sql lo dividio por el fx sellado).
    const rows = [{ asset: 'AL30', asset_type: 'BONO', is_ar_market: true, is_cash: false, value_usd: 50000, invested_usd: 50000, pnl_usd: 0, clients: 1 }]
    const ops = realizedToOps([
      { asset: 'AL30', asset_type: 'BONO', is_ar_market: true, realized_usd: 0, income_usd: 200, cost_usd: 0, cost_incomplete: false },
    ])
    const { items } = computeClassBreakdown(rows, [], [], ops)
    const bono = items.find(i => i.key === 'bono')
    expect(bono.pnl.total).toBe(200)
    expect(bono.pnl.pct).toBeCloseTo(0.4, 6)
  })

  it('realizedToOps no vuelve a convertir lo que el backend ya convirtio', () => {
    // Las ops sinteticas son 'Venta'/'Dividendo', que NO estan en
    // NATIVE_CCY_OPS — si alguien las renombrara a 'Cupon', opPnlUsd las
    // dividiria por segunda vez.
    const ops = realizedToOps([
      { asset: 'AL30', asset_type: 'BONO', is_ar_market: true, realized_usd: 50, income_usd: 200, cost_usd: 500, cost_incomplete: false },
    ])
    for (const o of ops) {
      expect(['Venta', 'Dividendo']).toContain(o.op_type)
      expect(o.currency).toBeUndefined()
      expect(opPnlUsd(o)).toBe(o.pnl_usd)
    }
  })
})

describe('attachSpread — fusiona en vez de pisar', () => {
  const rows = [
    { asset: 'GGAL', value_usd: 400, invested_usd: 380, pnl_usd: 20, is_ar_market: true, is_cash: false, clients: 3 },
  ]

  it('dos filas que normalizan al mismo ticker y mercado se combinan, no se pisan', () => {
    // Ventana de deploy no atómico: un backend viejo manda las dos por separado.
    const out = attachSpread(computeClassBreakdown(rows, [], [], []), [
      { asset: 'GGAL', is_ar_market: true, clients: 3, clients_total: 3, min_pct: -20, max_pct: 40 },
      { asset: 'GGAL.BA', is_ar_market: true, clients: 9, clients_total: 9, min_pct: 1, max_pct: 2 },
    ], { rows, classify: classifyAsset })
    const g = out.items.flatMap(i => i.assets).find(a => a.asset === 'GGAL')
    expect(g.spread.min_pct).toBe(-20)   // el peor de los dos grupos
    expect(g.spread.max_pct).toBe(40)    // el mejor de los dos grupos
    expect(g.spread.clients).toBe(9)
  })

  it('ignora filas sin ticker en vez de romper', () => {
    const bd = computeClassBreakdown(rows, [], [], [])
    expect(() => attachSpread(bd, [{ asset: '', clients: 2, min_pct: 1, max_pct: 2 }, null],
      { rows, classify: classifyAsset })).not.toThrow()
  })
})

describe('el rango parcial viaja a la IA', () => {
  const rows = [
    { asset: 'GD35', value_usd: 100, invested_usd: 100, pnl_usd: 0, is_ar_market: true, is_cash: false, clients: 3 },
  ]

  it('cuando no cubre a todos, manda cuántos lo tienen', () => {
    const p = toBookCompositionAiParams(computeClassBreakdown(rows, [], [], []), {
      clients: 3,
      spread: [{ asset: 'GD35', clients: 2, clients_total: 3, min_pct: 5, max_pct: 5 }],
    })
    expect(p.mas_dispersos).toEqual([{ a: 'GD35', c: 2, min: 5, max: 5, ct: 3 }])
  })

  it('manda cuántos están en rojo — es la lectura accionable', () => {
    const p = toBookCompositionAiParams(computeClassBreakdown(rows, [], [], []), {
      clients: 3,
      spread: [{ asset: 'GD35', clients: 4, clients_total: 4, clients_red: 2, min_pct: -20, max_pct: 30 }],
    })
    expect(p.mas_dispersos[0].rojo).toBe(2)
  })

  it('con todos en verde no ensucia el packet', () => {
    const p = toBookCompositionAiParams(computeClassBreakdown(rows, [], [], []), {
      clients: 3,
      spread: [{ asset: 'GD35', clients: 4, clients_total: 4, clients_red: 0, min_pct: 5, max_pct: 30 }],
    })
    expect(p.mas_dispersos[0].rojo).toBeUndefined()
  })

  it('cuando cubre a todos no ensucia el packet', () => {
    const p = toBookCompositionAiParams(computeClassBreakdown(rows, [], [], []), {
      clients: 3,
      spread: [{ asset: 'GD35', clients: 3, clients_total: 3, min_pct: 5, max_pct: 9 }],
    })
    expect(p.mas_dispersos[0].ct).toBeUndefined()
  })
})

describe('el denominador con ventas que se cancelan', () => {
  it('la porción no infla su rendimiento cuando lo realizado neto es cero', () => {
    // AAPL abierto: valor 2.200 sobre costo 2.000 (+200). Además dos clientes
    // vendieron +500 y −500 sobre US$10.000 de costo.
    // Correcto: 200 / (2.000 + 10.000) = +1,7%. Antes daba +10,0%.
    const rows = [{ asset: 'AAPL', asset_type: null, is_ar_market: false, is_cash: false, value_usd: 2200, invested_usd: 2000, pnl_usd: 200, clients: 2 }]
    const ops = realizedToOps([
      { asset: 'AAPL', asset_type: null, is_ar_market: false, realized_usd: 0, income_usd: 0, cost_usd: 10000, cost_incomplete: false },
    ])
    const { items } = computeClassBreakdown(rows, [], [], ops)
    const us = items.find(i => i.key === 'accion_us')
    expect(us.pnl.total).toBe(200)
    expect(us.pnl.cost).toBe(12000)
    expect(us.pnl.pct).toBeCloseTo(200 / 12000 * 100, 6)
  })
})

// ─── El corte grueso: variable / fija / efectivo ───────────────────────────
describe('riskMixFromBreakdown', () => {
  const rows = [
    { asset: 'AAPL', value_usd: 300, invested_usd: 300, pnl_usd: 0, is_ar_market: true, is_cash: false },   // CEDEAR
    { asset: 'GGAL', value_usd: 100, invested_usd: 100, pnl_usd: 0, is_ar_market: true, is_cash: false },   // acción AR
    { asset: 'BTC', value_usd: 200, invested_usd: 200, pnl_usd: 0, is_ar_market: false, is_cash: false },   // cripto
    { asset: 'AL30', value_usd: 150, invested_usd: 150, pnl_usd: 0, is_ar_market: true, is_cash: false },   // bono
    { asset: 'FCI:FIMA-PREMIUM-A', value_usd: 50, invested_usd: 50, pnl_usd: 0, is_ar_market: true, is_cash: false },
    { asset: 'USD', value_usd: 200, invested_usd: 200, pnl_usd: 0, is_ar_market: false, is_cash: true },
  ]

  it('agrupa en variable / fija / efectivo', () => {
    const { items, total } = riskMixFromBreakdown(computeClassBreakdown(rows, []))
    const by = Object.fromEntries(items.map(i => [i.key, i.value]))
    expect(total).toBe(1000)
    expect(by.variable).toBe(600)    // CEDEAR 300 + acción AR 100 + cripto 200
    expect(by.fija).toBe(200)        // bono 150 + FCI 50
    expect(by.efectivo).toBe(200)
  })

  it('la cripto cuenta como renta variable (decisión declarada)', () => {
    const solo = [{ asset: 'BTC', value_usd: 100, invested_usd: 100, pnl_usd: 0, is_ar_market: false, is_cash: false }]
    const { items } = riskMixFromBreakdown(computeClassBreakdown(solo, []))
    expect(items.map(i => i.key)).toEqual(['variable'])
  })

  it('los plazos fijos entran en renta fija', () => {
    const bd = computeClassBreakdown(rows, [], [pfSlice({ plazos_fijos_usd: 500, plazos_fijos_invested_usd: 480 }, 'plazo_fijo')])
    const by = Object.fromEntries(riskMixFromBreakdown(bd).items.map(i => [i.key, i.value]))
    expect(by.fija).toBe(700)
  })

  it('lo que el clasificador no supo tipar NO se reparte: va a su propia barra', () => {
    const r = [...rows, { asset: 'ZZZZ', value_usd: 100, invested_usd: 100, pnl_usd: 0, is_ar_market: true, is_cash: false }]
    const { items } = riskMixFromBreakdown(computeClassBreakdown(r, []))
    const otro = items.find(i => i.key === 'otro')
    expect(otro.value).toBe(100)
    // y no infló ninguno de los otros dos
    expect(items.find(i => i.key === 'variable').value).toBe(600)
    expect(items.find(i => i.key === 'fija').value).toBe(200)
  })

  it('sin nada sin clasificar son exactamente TRES barras', () => {
    const { items } = riskMixFromBreakdown(computeClassBreakdown(rows, []))
    expect(items.map(i => i.key)).toEqual(['variable', 'fija', 'efectivo'])
  })

  it('los porcentajes suman 100', () => {
    const { items } = riskMixFromBreakdown(computeClassBreakdown(rows, []))
    expect(items.reduce((s, i) => s + i.pct, 0)).toBeCloseTo(100, 9)
  })

  it('cada barra dice qué clases la componen (para el pie de la card)', () => {
    const { items } = riskMixFromBreakdown(computeClassBreakdown(rows, []))
    expect(items.find(i => i.key === 'variable').classes).toEqual(
      expect.arrayContaining(['CEDEARs', 'Acciones AR', 'Cripto']))
    expect(items.find(i => i.key === 'fija').classes).toEqual(
      expect.arrayContaining(['Bonos y letras', 'FCI']))
  })

  it('LA INVARIANTE: suma exactamente lo mismo que la torta que plegó', () => {
    // Es el motivo por el que pliega el breakdown en vez de recorrer las filas.
    const bd = computeClassBreakdown(rows, [], [pfSlice({ plazos_fijos_usd: 500, plazos_fijos_invested_usd: 480 }, 'plazo_fijo')])
    const mix = riskMixFromBreakdown(bd)
    expect(mix.total).toBe(bd.total)
    expect(mix.items.reduce((s, i) => s + i.value, 0)).toBeCloseTo(bd.total, 9)
  })

  it('cartera vacía no revienta', () => {
    expect(riskMixFromBreakdown(computeClassBreakdown([], []))).toEqual({ items: [], total: 0 })
    expect(riskMixFromBreakdown(null)).toEqual({ items: [], total: 0 })
  })
})
