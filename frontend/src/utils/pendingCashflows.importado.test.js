/**
 * Un cupón que entró IMPORTADO no puede aparecer en «Tenés N cobros para confirmar».
 *
 * EL BUG (2026-10-09). La bandeja sólo reconocía 'Cupón'/'Amortización' (lo que
 * escribe la carga a mano); el importador guarda el cupón como 'Dividendo' o
 * 'Interés'. La bandeja lo ofrecía como pendiente y confirmarlo anotaba la plata
 * dos veces. Y el cupón en dólares de un bono comprado en pesos queda en la pata
 * «Cocos · USD», mientras el bono vive en «Cocos».
 *
 * La entrada NO está escrita a mano: es backend/tests/fixtures/cupon_importado_bandeja.json,
 * lo que devolvieron /api/positions, /api/operations y /api/brokers después de
 * importar un CSV por las puertas reales (backend/tests/test_cupon_importado_bandeja.py
 * verifica que siga siendo eso). Acá pasa por el mismo camino que en Positions.jsx:
 * `ops.filter(esCobroDeRenta)` → `detectPendingCashflows(..., { brokers })`.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { detectPendingCashflows, esCobroDeRenta, cobroRegistrado } from './pendingCashflows.js'

const AQUI = dirname(fileURLToPath(import.meta.url))
const CONTRATO = JSON.parse(readFileSync(
  resolve(AQUI, '../../../backend/tests/fixtures/cupon_importado_bandeja.json'), 'utf8'))

// Después de los dos pagos importados (2025-07-09 y 2026-01-09) y antes del
// siguiente (2026-07-09). Fijo: el resultado no depende del día en que corra.
const HOY = '2026-03-01'
const PAGOS_COBRADOS = ['2025-07-09', '2026-01-09']

// Las posiciones como las ve la pantalla: el contrato guarda si la cantidad es
// positiva (el número exacto depende del barrido de vencimientos del día).
const posiciones = (esc) => esc.positions.map(p => ({
  ...p, quantity: p.quantity_mayor_a_cero ? 1000 : 0,
}))

// EXACTAMENTE lo que hace Positions.jsx (loadAll + el useMemo de la bandeja).
const bandeja = (esc) => detectPendingCashflows(
  posiciones(esc),
  esc.operations.filter(esCobroDeRenta),
  esc.skips,
  { today: HOY, brokers: esc.brokers },
)

// Lo que hacía antes: filtro de nombres a mano, sin brokers.
const bandejaVieja = (esc) => detectPendingCashflows(
  posiciones(esc),
  esc.operations.filter(o => o.op_type === 'Cupón' || o.op_type === 'Amortización'),
  esc.skips,
  { today: HOY },
)

describe('bandeja de cobros — cupones importados', () => {
  for (const [nombre, esc] of Object.entries(CONTRATO)) {
    it(`${nombre}: los pagos ya importados NO aparecen como pendientes`, () => {
      const fechas = bandeja(esc).map(it => it.date)
      for (const f of PAGOS_COBRADOS) expect(fechas).not.toContain(f)
    })

    it(`${nombre}: la bandeja vieja SÍ los ofrecía (el test detecta el bug)`, () => {
      const fechas = bandejaVieja(esc).map(it => it.date)
      for (const f of PAGOS_COBRADOS) expect(fechas).toContain(f)
    })
  }

  it('sin la lista de brokers, el cupón de la pata USD no se reconoce', () => {
    // Por eso Positions.jsx la pasa: el nombre del broker no alcanza.
    const esc = CONTRATO.cupon_en_la_pata_usd
    const sinBrokers = detectPendingCashflows(
      posiciones(esc), esc.operations.filter(esCobroDeRenta), esc.skips, { today: HOY })
    expect(sinBrokers.map(it => it.date)).toEqual(expect.arrayContaining(PAGOS_COBRADOS))
  })

  it('un pago que NO se importó sigue apareciendo', () => {
    const esc = CONTRATO.cupon_en_pesos
    const sinElUltimo = { ...esc, operations: esc.operations.filter(o => o.date < '2026-01-01') }
    const fechas = bandeja(sinElUltimo).map(it => it.date)
    expect(fechas).toContain('2026-01-09')
    expect(fechas).not.toContain('2025-07-09')
  })
})

describe('esCobroDeRenta', () => {
  it('reconoce la carga a mano, la importada y las filas viejas sin tilde', () => {
    for (const t of ['Cupón', 'Amortización', 'Dividendo', 'Interés', 'Renta', 'Cupon', 'Interes', 'Amortizacion'])
      expect(esCobroDeRenta({ op_type: t })).toBe(true)
  })

  it('no confunde un plazo fijo, una venta ni una conversión con renta de un bono', () => {
    for (const t of ['Interés PF', 'Venta', 'CONVERSION IMPORT ARS→USDT', 'Futuros', '', null])
      expect(esCobroDeRenta({ op_type: t })).toBe(false)
  })
})

describe('cobroRegistrado — la fila que junta las dos patas', () => {
  it('reconoce el cobro de cualquiera de las patas listadas en _brokers', () => {
    const esc = CONTRATO.cupon_en_la_pata_usd
    const filaFusionada = { broker: null, _brokers: ['Cocos', 'Cocos · USD'], asset: 'AL30' }
    expect(cobroRegistrado(esc.operations, filaFusionada, '2026-01-09', esc.brokers)).toBeTruthy()
  })

  it('no toma el cobro de OTRO activo de la misma cuenta', () => {
    const esc = CONTRATO.cupon_en_pesos
    const otro = { broker: 'Cocos', asset: 'GD30' }
    expect(cobroRegistrado(esc.operations, otro, '2026-01-09', esc.brokers)).toBeUndefined()
  })
})
