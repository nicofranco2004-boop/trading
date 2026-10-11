// El contrato de IDA Y VUELTA entre la bandeja de cobros de bonos y el servidor.
// La otra mitad, y la explicación entera: backend/tests/test_cupones_contrato.py.
//
//   · lee "pantalla" (lo que el servidor le da a la bandeja; lo escribe el test
//     del servidor) y arma la bandeja con las funciones reales;
//   · compara lo que la bandeja le mandaría al servidor para confirmar cada pago
//     (`cuerpoDelPago`, la misma función del hook) con "pagos", que es lo que el
//     test del servidor postea. Para regenerarlos a propósito:
//       REGENERAR_PAGOS=1 npx vitest run src/utils/cuponesContrato.test.js
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { detectPendingCashflows, detectCobrosImportados, cuerpoDelPago } from './pendingCashflows.js'

const AQUI = dirname(fileURLToPath(import.meta.url))
const RUTA = resolve(AQUI, '../../../backend/tests/fixtures/cupones_contrato.json')
const CONTRATO = JSON.parse(readFileSync(RUTA, 'utf8'))
const HOY = CONTRATO.hoy

// Las posiciones como llegan de /api/positions. La cantidad de un lote que lleva
// el barrido de amortizaciones depende del día: el contrato sólo dice que es > 0
// (la bandeja calcula con `nominal_original`, no con la cantidad).
const posiciones = (esc) => esc.positions.map(p => ({
  ...p, quantity: p.quantity ?? (p.quantity_mayor_a_cero ? 1 : 0),
}))
const opciones = (esc) => ({ today: HOY, brokers: esc.brokers })
// Lo que hace el hook (useCuponesPorCobrar): TODAS las operaciones, sin filtrar.
const bandeja = (esc) => detectPendingCashflows(posiciones(esc), esc.operations, esc.skips, opciones(esc))
// El botón "Confirmar cobro": los montos del cronograma, sin comisión.
const pagosDe = (esc) => bandeja(esc)
  .map(it => cuerpoDelPago(it, { cupon: it.coupon, amort: it.amort, comision: 0 }))
  .map(c => JSON.parse(JSON.stringify(c)))            // como viaja: sin `undefined`

describe('contrato de la bandeja de cupones', () => {
  const escenarios = Object.entries(CONTRATO.pantalla)

  it('lo que la bandeja le manda al servidor es lo que el servidor prueba', () => {
    const real = Object.fromEntries(escenarios.map(([nombre, esc]) => [nombre, pagosDe(esc)]))
    if (process.env.REGENERAR_PAGOS) {
      writeFileSync(RUTA, JSON.stringify({ ...CONTRATO, pagos: real }, null, 2) + '\n')
      return
    }
    expect(real, 'la bandeja manda otra cosa que la que prueba el servidor. Si es a propósito: '
      + 'REGENERAR_PAGOS=1 npx vitest run src/utils/cuponesContrato.test.js y corré '
      + 'backend/tests/test_cupones_contrato.py').toEqual(CONTRATO.pagos)
  })

  it('AL30 importado: propone los pagos sobre los 10.000 originales, en la cuenta en dólares', () => {
    const items = bandeja(CONTRATO.pantalla.importado_con_barrido)
    expect(items.map(it => it.date)).toEqual(['2026-07-09', '2026-01-09'])   // julio 2025 ya vino en el archivo
    const julio = items[0]
    expect([julio.coupon, julio.amort, julio.total]).toEqual([27, 800, 827])
    expect(julio.cuenta).toBe('Cocos · USD')
    expect(julio.nominalesQueBajan).toBe(0)             // los lleva el barrido
    const cuerpo = cuerpoDelPago(julio, { cupon: 27, amort: 800, comision: 0 })
    expect(cuerpo).toMatchObject({ broker: 'Cocos', asset: 'AL30', date: '2026-07-09',
      cash_broker: 'Cocos · USD', coupon_amount: 27, amort_amount: 800, face_amortized: 800 })
  })

  it('GD46 importado (sin cronograma en el servidor): 10.000 originales, no los 9.772 de hoy', () => {
    const esc = CONTRATO.pantalla.importado_sin_cronograma
    const items = bandeja(esc)
    // Enero 2026 vino en el archivo como una "venta": no se ofrece de nuevo.
    expect(items.map(it => it.date)).toEqual(['2026-07-09', '2025-07-09'])
    const julio = items[0]
    expect(julio.nominales).toBe(10000)
    expect(julio.amort).toBeCloseTo(227.27, 2)          // 1/44 de 10.000 (no 238,10 ni 222,11)
    expect(julio.nominalesQueBajan).toBeCloseTo(227.2727, 3)
    expect(cuerpoDelPago(julio, { cupon: julio.coupon, amort: julio.amort, comision: 0 }).face_amortized)
      .toBeCloseTo(227.2727, 3)
    const [yaVino] = detectCobrosImportados(posiciones(esc), esc.operations, opciones(esc))
    expect([yaVino.date, yaVino.comoLoLlama, yaVino.monto]).toEqual(['2026-01-09', 'Venta (amortización)', null])
  })

  it('si el servidor dejara de avisar cuál venta es una amortización, enero volvería a ofrecerse', () => {
    const esc = CONTRATO.pantalla.importado_sin_cronograma
    const sinAviso = { ...esc, operations: esc.operations.map(o => ({ ...o, amortizacion_importada: false })) }
    expect(bandeja(sinAviso).map(it => it.date)).toContain('2026-01-09')
  })

  it('montos editados y otra cuenta: viajan como los cargó el usuario', () => {
    const [julio] = bandeja(CONTRATO.pantalla.importado_con_barrido)
    const cuerpo = cuerpoDelPago(julio, { cupon: 38205, amort: 1132000, comision: 150, cuenta: 'Cocos', editado: true })
    expect(cuerpo).toMatchObject({ cash_broker: 'Cocos', coupon_amount: 38205, amort_amount: 1132000,
      commissions: 150, face_amortized: 800, notes: 'Confirmado desde la bandeja (montos editados)' })
  })
})
