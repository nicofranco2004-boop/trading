import { describe, it, expect } from 'vitest'
import { computePnlByKey, ratePct } from './assetPnl.js'
import { classifyAsset } from './assetClass.js'
import { classifySector } from './assetSector.js'
import { computeClassBreakdown } from './assetClass.js'

const BROKERS = [
  { name: 'Balanz', currency: 'ARS' },
  { name: 'Schwab', currency: 'USD' },
  { name: 'Binance', currency: 'USDT' },
]
// Una venta cuyo costo hay que despejar: pnl_pct viene en PORCENTAJE.
const venta = (asset, broker, pnl_usd, pnl_pct) =>
  ({ asset, broker, op_type: 'Venta', pnl_usd, pnl_pct })
const renta = (asset, broker, pnl_usd, tipo = 'Dividendo') =>
  ({ asset, broker, op_type: tipo, pnl_usd, pnl_pct: null })
const abierta = (asset, broker, value_usd, pnl_usd, extra = {}) =>
  ({ asset, broker, value_usd, pnl_usd, is_cash: 0, ...extra })

describe('las tres patas del resultado', () => {
  it('suma no realizado + realizado + renta', () => {
    const m = computePnlByKey(
      [abierta('AAPL', 'Schwab', 1200, 200)],
      [venta('AAPL', 'Schwab', 300, 50), renta('AAPL', 'Schwab', 40)],
      BROKERS, classifyAsset,
    )
    const b = m.get('accion_us')
    expect(b.unrealized).toBe(200)
    expect(b.realized).toBe(300)
    expect(b.income).toBe(40)
    expect(b.total).toBe(540)
  })

  it('el costo de una venta se despeja de (pnl_usd, pnl_pct), no de entry_price', () => {
    // +300 con +50% ⇒ el costo fue 600.
    const m = computePnlByKey([], [venta('AAPL', 'Schwab', 300, 50)], BROKERS, classifyAsset)
    expect(m.get('accion_us').cost).toBeCloseTo(600, 6)
  })

  it('el costo de una posición abierta es valor − pnl', () => {
    const m = computePnlByKey([abierta('AAPL', 'Schwab', 1200, 200)], [], BROKERS, classifyAsset)
    expect(m.get('accion_us').cost).toBe(1000)
    expect(m.get('accion_us').pct).toBeCloseTo(20, 6)
  })

  it('la renta suma al resultado pero NO al capital invertido', () => {
    // Un bono comprado en 1000, hoy 1050, que pagó 200 de cupones ⇒ +25%.
    const m = computePnlByKey(
      [abierta('AL30', 'Balanz', 1050, 50, { asset_type: 'BOND' })],
      [renta('AL30', 'Balanz', 200, 'Interés')],
      BROKERS, classifyAsset,
    )
    const b = m.get('bono')
    expect(b.cost).toBe(1000)
    expect(b.total).toBe(250)
    expect(b.pct).toBeCloseTo(25, 6)
  })

  it('sin la renta, un bono que rindió por cupón parecería no haber rendido', () => {
    // Es el motivo por el que existe la pata de renta — el caso medido en la
    // base real: dividendos + intereses ≫ ventas realizadas.
    const soloAbiertas = computePnlByKey(
      [abierta('AL30', 'Balanz', 1050, 50, { asset_type: 'BOND' })], [], BROKERS, classifyAsset,
    )
    expect(soloAbiertas.get('bono').pct).toBeCloseTo(5, 6)   // ← el número equivocado
  })
})

describe('honestidad del porcentaje', () => {
  it('sin pnl_pct no se puede despejar el costo → pct null, pero el monto queda', () => {
    const m = computePnlByKey([], [venta('AAPL', 'Schwab', 300, null)], BROKERS, classifyAsset)
    const b = m.get('accion_us')
    expect(b.total).toBe(300)
    expect(b.costIncomplete).toBe(true)
    expect(b.pct).toBeNull()
  })

  it('una sola venta sin denominador contamina el % de toda la porción', () => {
    const m = computePnlByKey(
      [abierta('AAPL', 'Schwab', 1200, 200)],
      [venta('AMD', 'Schwab', 300, null)],
      BROKERS, classifyAsset,
    )
    // Preferimos no mostrar % antes que mostrar uno inflado.
    expect(m.get('accion_us').pct).toBeNull()
    expect(m.get('accion_us').total).toBe(500)
  })

  it('una posición sin precio no aporta ni al monto ni al costo', () => {
    const m = computePnlByKey(
      [abierta('AAPL', 'Schwab', null, null), abierta('AMD', 'Schwab', 1200, 200)],
      [], BROKERS, classifyAsset,
    )
    expect(m.get('accion_us').cost).toBe(1000)
    expect(m.get('accion_us').total).toBe(200)
  })
})

describe('clasificación de lo cerrado', () => {
  it('las conversiones de moneda no entran', () => {
    const m = computePnlByKey([], [
      { asset: 'ARS→USDT', broker: 'IOL', op_type: 'CONVERSION IMPORT ARS→USDT', pnl_usd: 0, pnl_pct: null },
    ], BROKERS, classifyAsset)
    expect(m.size).toBe(0)
  })

  it('hereda el asset_type de la posición abierta del mismo broker', () => {
    // `operations` no guarda asset_type. Sin el hint, la venta de un CEDEAR en
    // un sub-broker USD caería en "acciones US" y la ganancia iría a la
    // porción equivocada.
    const BR = [...BROKERS, { name: 'Balanz · USD', currency: 'USD' }]
    const m = computePnlByKey(
      [abierta('MELI', 'Balanz · USD', 500, 0, { asset_type: 'CEDEAR' })],
      [venta('MELI', 'Balanz · USD', 100, 25)],
      BR, classifyAsset,
    )
    expect(m.has('cedear')).toBe(true)
    expect(m.get('cedear').realized).toBe(100)
    expect(m.has('accion_us')).toBe(false)
  })

  it('el efectivo no tiene rendimiento', () => {
    const m = computePnlByKey(
      [{ asset: 'ARS', broker: 'Balanz', is_cash: 1, value_usd: 900, pnl_usd: 0 }],
      [], BROKERS, classifyAsset,
    )
    expect(m.has('cash')).toBe(false)
  })

  it('funciona igual sobre el eje de sector', () => {
    const m = computePnlByKey(
      [abierta('NVDA', 'Balanz', 1200, 200, { asset_type: 'CEDEAR' })],
      [venta('AMD', 'Schwab', 300, 50)],
      BROKERS, classifySector,
    )
    // El CEDEAR de NVDA y la acción de AMD caen en el mismo sector.
    expect(m.get('semis').total).toBe(500)
    expect(m.get('semis').cost).toBeCloseTo(1600, 6)
  })
})

describe('integración con la torta', () => {
  const positions = [
    abierta('AAPL', 'Schwab', 1200, 200),
    abierta('AL30', 'Balanz', 1050, 50, { asset_type: 'BOND' }),
  ]
  const ops = [venta('AAPL', 'Schwab', 300, 50), renta('AL30', 'Balanz', 200, 'Interés')]

  it('sin operations la torta es solo peso — pnl null', () => {
    const { items } = computeClassBreakdown(positions, BROKERS)
    expect(items.every(i => i.pnl === null)).toBe(true)
  })

  it('con operations cada porción trae su resultado', () => {
    const { items } = computeClassBreakdown(positions, BROKERS, [], ops)
    const us = items.find(i => i.key === 'accion_us')
    expect(us.pnl.total).toBe(500)
    expect(us.pnl.pct).toBeCloseTo(31.25, 4)   // 500 / (1000 + 600)
    const bono = items.find(i => i.key === 'bono')
    expect(bono.pnl.total).toBe(250)
    expect(bono.pnl.pct).toBeCloseTo(25, 6)
  })

  it('cada activo del desglose trae el suyo', () => {
    const { items } = computeClassBreakdown(positions, BROKERS, [], ops)
    const aapl = items.find(i => i.key === 'accion_us').assets[0]
    expect(aapl.asset).toBe('AAPL')
    expect(aapl.pnl.total).toBe(500)
  })

  it('las porciones sintéticas no inventan rendimiento', () => {
    const { items } = computeClassBreakdown(positions, BROKERS, [{ key: 'plazo_fijo', value: 500 }], ops)
    expect(items.find(i => i.key === 'plazo_fijo').pnl).toBeNull()
  })
})

describe('porciones sintéticas con resultado propio (plazo fijo)', () => {
  const pos = [{ asset: 'AL30', broker: 'Balanz', asset_type: 'BOND', value_usd: 1050, pnl_usd: 50, is_cash: 0 }]
  const ops = [{ asset: 'AL30', broker: 'Balanz', op_type: 'Interés', pnl_usd: 200, pnl_pct: null }]

  it('el capital del plazo fijo entra en el denominador junto con su interés', () => {
    // Sin esto el % se calculaba solo sobre los bonos y no cerraba contra el
    // monto que la porción mostraba al lado.
    const { items } = computeClassBreakdown(pos, BROKERS, [], ops)
    expect(items.find(i => i.key === 'bono').pnl.cost).toBe(1000)

    const conPf = computeClassBreakdown(
      pos, BROKERS, [{ key: 'bono', value: 5000, pnl: { total: 300, cost: 4700 } }], ops,
    )
    const b = conPf.items.find(i => i.key === 'bono')
    expect(b.pnl.total).toBe(550)          // 250 de bonos + 300 del PF
    expect(b.pnl.cost).toBe(5700)          // 1000 + 4700
    expect(b.pnl.pct).toBeCloseTo(550 / 5700 * 100, 6)
  })

  it('una porción que SOLO es sintética igual muestra su resultado', () => {
    const { items } = computeClassBreakdown(
      pos, BROKERS, [{ key: 'plazo_fijo', value: 5000, pnl: { total: 300, cost: 4700 } }], ops,
    )
    const pf = items.find(i => i.key === 'plazo_fijo')
    expect(pf.pnl.total).toBe(300)
    expect(pf.pnl.pct).toBeCloseTo(6.383, 3)
    expect(pf.assets).toEqual([])
  })

  it('sin pnl en la porción sintética el resultado sigue siendo null', () => {
    const { items } = computeClassBreakdown(pos, BROKERS, [{ key: 'plazo_fijo', value: 5000 }], ops)
    expect(items.find(i => i.key === 'plazo_fijo').pnl).toBeNull()
  })
})



describe('regresión: la proyección de la página no puede comerse pnl_usd', () => {
  // Bug real (Métricas mostraba las tortas sin "Resultado" mientras el Dashboard
  // sí lo mostraba): Insights armaba su lista de posiciones enumerando campos a
  // mano y dejaba afuera `pnl_usd`. Sin él NO hay pata de no realizado, así que
  // el resultado solo aparecía en las clases que además tuvieran ventas — y un
  // CEDEAR que nunca vendiste no tiene ninguna.
  const BR = [{ name: 'Balanz', currency: 'ARS' }, { name: 'Schwab', currency: 'USD' }]
  const cartera = [
    { asset: 'AAPL', asset_type: 'CEDEAR', broker: 'Balanz', value_usd: 1200, pnl_usd: 200 },
    { asset: 'NVDA', asset_type: 'CEDEAR', broker: 'Balanz', value_usd: 900, pnl_usd: -100 },
  ]

  it('con pnl_usd, una clase SIN ventas igual muestra resultado', () => {
    const { items } = computeClassBreakdown(
      cartera.map(p => ({ ...p, is_cash: false })), BR, [], [],  // cero operaciones
    )
    const cedear = items.find(i => i.key === 'cedear')
    expect(cedear.pnl).not.toBeNull()
    expect(cedear.pnl.total).toBe(100)
    expect(cedear.pnl.unrealized).toBe(100)
  })

  it('la proyección que enumera campos a mano rompe el resultado', () => {
    // Reproduce la proyección vieja: mismo set de posiciones, sin pnl_usd.
    const proyeccionVieja = cartera.map(p => ({
      asset: p.asset, asset_type: p.asset_type, broker: p.broker,
      is_cash: false, value_usd: p.value_usd,
    }))
    const { items } = computeClassBreakdown(proyeccionVieja, BR, [], [])
    // El peso sale bien — por eso la torta se veía normal y el bug no cantaba.
    expect(items.find(i => i.key === 'cedear').value).toBe(2100)
    // Pero el resultado desaparece.
    expect(items.find(i => i.key === 'cedear').pnl).toBeNull()
  })

  it('el peso es idéntico con y sin pnl_usd — el bug es invisible en la torta', () => {
    const conPnl = computeClassBreakdown(cartera.map(p => ({ ...p, is_cash: false })), BR, [], [])
    const sinPnl = computeClassBreakdown(
      cartera.map(({ asset, asset_type, broker, value_usd }) =>
        ({ asset, asset_type, broker, value_usd, is_cash: false })), BR, [], [])
    expect(conPnl.items.map(i => [i.key, i.pct]))
      .toEqual(sinPnl.items.map(i => [i.key, i.pct]))
  })
})

// ─── Los cupones son RENTA, aunque lleven acento ───────────────────────────
// La app escribe op_type='Cupón' (main.py, 6 lugares) y el matcheo era
// includes('CUPON') sobre el string en mayúsculas: 'CUPÓN' no lo contiene, así
// que cada cupón entraba como si fuera una venta. El monto seguía sumando al
// total, pero como los cupones no traen pnl_pct marcaban el costo incompleto y
// le borraban el rendimiento % a TODA la porción de bonos — justo la porción
// donde el cupón ES el rendimiento.
describe('renta con acentos', () => {
  const positions = [
    { asset: 'AL30', broker: 'Balanz', asset_type: 'BONO', value_usd: 1000, pnl_usd: 0 },
  ]
  const brokers = [{ name: 'Balanz', currency: 'ARS' }]
  const classify = () => 'bono'

  it("'Cupón' cuenta como renta, no como venta", () => {
    const out = computePnlByKey(positions, [
      { asset: 'AL30', broker: 'Balanz', op_type: 'Cupón', pnl_usd: 80, pnl_pct: null },
    ], brokers, classify)
    const b = out.get('bono')
    expect(b.income).toBe(80)
    expect(b.realized).toBe(0)
    expect(b.costIncomplete).toBe(false)
    // Y por lo tanto la porción conserva su rendimiento %.
    expect(b.pct).toBeCloseTo(8, 6)
  })

  it("'Interés' también", () => {
    const out = computePnlByKey(positions, [
      { asset: 'AL30', broker: 'Balanz', op_type: 'Interés', pnl_usd: 50, pnl_pct: null },
    ], brokers, classify)
    expect(out.get('bono').income).toBe(50)
  })

  it('una venta de verdad sigue siendo realizado', () => {
    const out = computePnlByKey(positions, [
      { asset: 'AL30', broker: 'Balanz', op_type: 'Venta', pnl_usd: 50, pnl_pct: 10 },
    ], brokers, classify)
    const b = out.get('bono')
    expect(b.realized).toBe(50)
    expect(b.income).toBe(0)
  })
})

// ─── Cuándo el % deja de ser un rendimiento ────────────────────────────────
// total/costo se rompe cuando la plata se ganó sobre un capital que ya no
// está: un bono que amortizó casi todo sigue sumando años de cupones contra
// un costo residual. Medido en el libro demo, GD35 con US$15 de posición y
// US$1.463 de renta cobrada daba +9.804% — eso no comunica un rendimiento,
// comunica que el denominador se evaporó. Mostramos el monto y ocultamos la
// tasa, igual que ya se hace cuando falta el costo de una venta.
describe('ratePct — la tasa, o null cuando no hay tasa que valga', () => {
  it('devuelve la tasa normal cuando el costo se sostiene', () => {
    expect(ratePct(200, 1000, false)).toBeCloseTo(20, 9)
    expect(ratePct(-300, 1000, false)).toBeCloseTo(-30, 9)
  })

  it('null si no hay costo o el costo está incompleto', () => {
    expect(ratePct(200, 0, false)).toBeNull()
    expect(ratePct(200, -5, false)).toBeNull()
    expect(ratePct(200, 1000, true)).toBeNull()
  })

  it('null cuando el resultado supera 10× el costo (el denominador se evaporó)', () => {
    expect(ratePct(1464, 15, false)).toBeNull()      // GD35: +9.804%
    expect(ratePct(2459, 185, false)).toBeNull()     // AL30: +1.331%
  })

  it('la pérdida grande también se corta: −5000% no es una tasa', () => {
    expect(ratePct(-1464, 15, false)).toBeNull()
  })

  it('el borde es 10× exacto y sigue siendo válido', () => {
    expect(ratePct(1000, 100, false)).toBeCloseTo(1000, 6)   // 10× justo
    expect(ratePct(1001, 100, false)).toBeNull()             // apenas arriba
  })
})

describe('el guard llega hasta la porción y el activo', () => {
  const brokers = [{ name: 'Balanz', currency: 'ARS' }]
  const classify = () => 'bono'

  it('un bono amortizado con mucha renta muestra monto pero no tasa', () => {
    const out = computePnlByKey(
      [{ asset: 'GD35', broker: 'Balanz', asset_type: 'BONO', value_usd: 15, pnl_usd: 0 }],
      [{ asset: 'GD35', broker: 'Balanz', op_type: 'Cupón', pnl_usd: 1463, pnl_pct: null }],
      brokers, classify,
    )
    const b = out.get('bono')
    expect(b.total).toBe(1463)          // el monto sigue estando
    expect(b.pct).toBeNull()            // la tasa no
    expect(b.byAsset[0].total).toBe(1463)
    expect(b.byAsset[0].pct).toBeNull()
  })

  it('un bono normal conserva su tasa', () => {
    const out = computePnlByKey(
      [{ asset: 'AO28', broker: 'Balanz', asset_type: 'BONO', value_usd: 18152, pnl_usd: 724 }],
      [{ asset: 'AO28', broker: 'Balanz', op_type: 'Cupón', pnl_usd: 881, pnl_pct: null }],
      brokers, classify,
    )
    expect(out.get('bono').pct).toBeCloseTo((724 + 881) / 17428 * 100, 6)
  })
})
