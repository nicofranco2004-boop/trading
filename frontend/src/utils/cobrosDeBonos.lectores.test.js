// Los LECTORES de un cobro de bono en la pantalla (auditoría 2026-10-10).
//
// La fila de un cobro guarda `quantity` = lo que entró y `pnl_usd` = la ganancia,
// en la moneda de la cuenta. Estas pruebas fijan que quien la lee no la trate
// como una venta: que la sume en dólares, que no muestre la plata como unidades,
// que el costo de una amortización no le borre el % a la porción de bonos, y que
// la "venta" con la que Balanz anota una amortización cuente como pago anotado.
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { opPnlUsd, operacionesEnUsd, computePnlByKey } from './assetPnl.js'
import { esCobro, computeTradeStats } from './tradeStats.js'
import { computeAssetContribution, computeBestWorstClosedOp } from './insightsModel.js'
import { esPagoDelBono, esCobroDeRenta, cobroRegistrado, cobradoDelBonoUsd,
         detectPendingCashflows, detectCobrosImportados } from './pendingCashflows.js'
import { classifyAsset } from './assetClass.js'

const aqui = dirname(fileURLToPath(import.meta.url))
const backend = (f) => readFileSync(resolve(aqui, '../../../backend', f), 'utf8')

const CUPON_EN_PESOS = { id: 1, date: '2026-08-10', broker: 'Cocos', asset: 'TX26', op_type: 'Cupón',
  quantity: 95000, pnl_usd: 95000, currency: 'ARS', fx_to_usd: 1250 }
const AMORTIZACION = { id: 2, date: '2026-07-09', broker: 'Cocos · USD', asset: 'AL30', op_type: 'Amortización',
  quantity: 800, pnl_usd: 320, currency: 'USDT', fx_to_usd: 1, cost_basis_consumed: 480 }
const VENTA = { id: 3, date: '2026-06-01', broker: 'Cocos', asset: 'GGAL', op_type: 'Venta',
  quantity: 10, pnl_usd: 40, pnl_pct: 10 }

describe('la lista de cobros es la misma que la del servidor', () => {
  it('esCobro reconoce exactamente los tipos de realized_pnl._TIPO_DE_COBRO', () => {
    const py = backend('realized_pnl.py')
    const bloque = py.slice(py.indexOf('_TIPO_DE_COBRO = {'), py.indexOf('}', py.indexOf('_TIPO_DE_COBRO = {')))
    const tipos = [...bloque.matchAll(/"([^"]+)":\s*"[A-Z]+"/g)].map(m => m[1])
    expect(tipos.length).toBeGreaterThanOrEqual(9)
    for (const t of tipos) expect(esCobro(t), t).toBe(true)
    for (const t of ['Venta', 'Compra', 'CONVERSION MEP ARS→USDT', '', null]) expect(esCobro(t), String(t)).toBe(false)
    // Y ni uno de más: los que la pantalla llama cobro, el servidor también.
    for (const t of ['Dividendo', 'Cupón', 'Cupon', 'Renta', 'Interés', 'Interes', 'Interés PF',
      'Amortización', 'Amortizacion']) expect(tipos, t).toContain(t)
  })
})

describe('operacionesEnUsd — se normaliza una vez, en el borde', () => {
  it('pasa a dólares el cupón en pesos y conserva el valor guardado', () => {
    const [c] = operacionesEnUsd([CUPON_EN_PESOS])
    expect(c.pnl_usd).toBeCloseTo(76, 6)
    expect(c.pnl_usd_native).toBe(95000)
  })
  it('no divide dos veces', () => {
    const una = operacionesEnUsd([CUPON_EN_PESOS])
    const dos = operacionesEnUsd(una)
    expect(dos[0].pnl_usd).toBeCloseTo(76, 6)
    expect(opPnlUsd(dos[0])).toBeCloseTo(76, 6)
  })
  it('lo que lee Métricas ya no ve US$ 95.000', () => {
    const ops = operacionesEnUsd([CUPON_EN_PESOS, AMORTIZACION, VENTA])
    const mejor = computeBestWorstClosedOp(ops).best
    expect(mejor.asset).toBe('AL30')
    expect(mejor.pnl_usd).toBe(320)
    const tx26 = computeAssetContribution(ops, []).find(x => x.asset === 'TX26')
    expect(tx26.realized).toBeCloseTo(76, 6)
  })
  it('una lista vacía o nula no rompe', () => {
    expect(operacionesEnUsd(null)).toEqual([])
    expect(operacionesEnUsd([])).toEqual([])
  })
})

describe('el costo de una amortización en el rendimiento por tipo de activo', () => {
  it('con el costo anotado, la porción conserva su porcentaje', () => {
    const out = computePnlByKey([], [AMORTIZACION], [], classifyAsset)
    const porcion = [...out.values()].find(b => b.byAsset.some(a => a.asset === 'AL30'))
    expect(porcion.costIncomplete).toBe(false)
    expect(porcion.realized).toBe(320)
    expect(porcion.cost).toBe(480)
    expect(porcion.pct).toBeCloseTo(66.67, 1)
  })
  it('el costo de una fila en pesos se pasa a dólares', () => {
    const enPesos = { ...AMORTIZACION, currency: 'ARS', fx_to_usd: 1250, quantity: 1000000,
      pnl_usd: 400000, cost_basis_consumed: 600000 }
    const out = computePnlByKey([], [enPesos], [], classifyAsset)
    const porcion = [...out.values()].find(b => b.byAsset.some(a => a.asset === 'AL30'))
    expect(porcion.realized).toBeCloseTo(320, 6)
    expect(porcion.cost).toBeCloseTo(480, 6)
  })
  it('sin costo (el lote lo conservó) el cobro es renta y tampoco borra el porcentaje', () => {
    const sinCosto = { ...AMORTIZACION, pnl_usd: 800, cost_basis_consumed: null }
    const out = computePnlByKey([], [sinCosto], [], classifyAsset)
    const porcion = [...out.values()].find(b => b.byAsset.some(a => a.asset === 'AL30'))
    expect(porcion.costIncomplete).toBe(false)
    expect(porcion.income).toBe(800)
    expect(porcion.cost).toBe(0)
  })
})

describe('la "venta" con la que Balanz anota una amortización', () => {
  const BONO = { id: 9, broker: 'Balanz', asset: 'GD30', quantity: 6400, invested: 3840,
    entry_date: '2025-03-03', nominal_original: 10000, nominal_por_barrido: true }
  const VENTA_AMORT = { id: 5, date: '2026-07-10', broker: 'Balanz', asset: 'GD30', op_type: 'Venta',
    quantity: 800, exit_price: 1.03, pnl_usd: 347, importada: true, amortizacion_importada: true }
  const VENTA_COMUN = { ...VENTA_AMORT, id: 6, amortizacion_importada: false }
  const hoy = { today: '2026-10-10' }

  it('es un pago del bono, pero no un cobro de renta (su cantidad son nominales)', () => {
    expect(esPagoDelBono(VENTA_AMORT)).toBe(true)
    expect(esCobroDeRenta(VENTA_AMORT)).toBe(false)
    expect(esPagoDelBono(VENTA_COMUN)).toBe(false)
  })
  it('la bandeja no ofrece el pago de julio; con una venta común sí', () => {
    const fechas = (ops) => detectPendingCashflows([BONO], ops, [], hoy).map(p => p.date)
    expect(fechas([VENTA_COMUN])).toContain('2026-07-09')
    expect(fechas([VENTA_AMORT])).not.toContain('2026-07-09')
    expect(cobroRegistrado([VENTA_AMORT], BONO, '2026-07-09')).toBe(VENTA_AMORT)
  })
  it('aparece como "ya entró con tu importación", sin un monto inventado', () => {
    const [y] = detectCobrosImportados([BONO], [VENTA_AMORT], hoy).filter(x => x.date === '2026-07-09')
    expect(y.comoLoLlama).toBe('Venta (amortización)')
    expect(y.monto).toBeNull()
  })
  it('no se suma a lo cobrado "aparte": su ganancia ya cuenta como venta', () => {
    expect(cobradoDelBonoUsd([VENTA_AMORT], BONO, [], 1400)).toBe(0)
  })
})

describe('el win rate no cambió de regla (decisión de producto pendiente)', () => {
  it('un cupón y una amortización siguen contando como hoy', () => {
    // Si esto cambia, que sea a propósito: ver backend/realized_pnl.py, Pendiente #1.
    const s = computeTradeStats(operacionesEnUsd([CUPON_EN_PESOS, AMORTIZACION, VENTA]))
    expect(s.trades).toBe(3)
  })
})
