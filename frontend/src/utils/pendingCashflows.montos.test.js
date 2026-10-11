/**
 * Lo que la bandeja de cobros de bonos PROPONE: montos, cuenta y lo ya cobrado.
 *
 * Hasta 2026-10-09 la bandeja proponía montos equivocados por dos razones:
 *   · el cronograma de AL30/GD30 de la pantalla tenía 13 cuotas iguales de
 *     7,69 % (el prospecto y el servidor: 4 % + 12×8 %);
 *   · multiplicaba el cronograma —escrito por cada 100 de nominal ORIGINAL— por
 *     los nominales de la posición, que en un bono importado ya son los VIVOS.
 * Con 10.000 nominales originales de AL30 (6.400 vivos hoy) el pago de julio
 * 2026 salía US$ 508,92; el que pagó el bono es US$ 827.
 */
import { describe, it, expect } from 'vitest'
import {
  detectPendingCashflows, detectCobrosImportados, cuentaDelCobro, cobradoDelBonoUsd,
} from './pendingCashflows.js'

const HOY = '2026-08-01'
const BROKERS = [
  { id: 1, name: 'Cocos', currency: 'ARS', parent_broker_id: null },
  { id: 2, name: 'Cocos · USD', currency: 'USDT', parent_broker_id: 1 },
  { id: 3, name: 'IOL', currency: 'USDT', parent_broker_id: null },
]
// Importado: el barrido lo dejó en el nominal vivo de hoy (64 % de 10.000). El
// servidor manda el original exacto (`nominal_original`, de compras − ventas).
const AL30_IMPORTADO = {
  broker: 'Cocos', asset: 'AL30', quantity: 6400, invested: 3_840_000, currency: 'ARS',
  tc_compra: 1000, entry_date: '2025-03-03', is_cash: 0, nominal_por_barrido: true,
  nominal_original: 10000,
}
const julio = (items) => items.find(x => x.date === '2026-07-09')

describe('montos del pago — nominal original, no el vivo', () => {
  it('AL30 importado (6.400 vivos = 10.000 originales): julio 2026 paga 27 + 800', () => {
    const it = julio(detectPendingCashflows([AL30_IMPORTADO], [], [], { today: HOY, brokers: BROKERS }))
    expect(it.nominales).toBe(10000)
    expect(it.coupon).toBeCloseTo(27, 2)       // 0,75 %/2 sobre el 72 % vivo
    expect(it.amort).toBeCloseTo(800, 2)       // cuota de 8 %
    expect(it.total).toBeCloseTo(827, 2)
    expect(it.vivoAntes).toBeCloseTo(72, 6)
    expect(it.vivoDespues).toBeCloseTo(64, 6)
    expect([it.cuota, it.cuotas]).toEqual([5, 13])
  })

  it('cargado a mano (sin barrido): la cantidad con que nació ÷ lo vivo ese día', () => {
    // Cargó 8.800 el 03/03/2025 (quedaba vivo el 88 % → 10.000 originales) y
    // registró dos amortizaciones de 800: hoy tiene 7.200. El servidor manda
    // `nominal_al_cargar` = 7.200 + 1.600.
    const aMano = { ...AL30_IMPORTADO, quantity: 7200, nominal_por_barrido: false,
                    nominal_original: undefined, nominal_al_cargar: 8800 }
    const registrados = ['2025-07-09', '2026-01-09'].map(date =>
      ({ op_type: 'Amortización', broker: 'Cocos · USD', asset: 'AL30', date, quantity: 800 }))
    const it = julio(detectPendingCashflows([aMano], registrados, [], { today: HOY, brokers: BROKERS }))
    expect(it.nominales).toBe(10000)
    expect(it.total).toBeCloseTo(827, 2)
  })

  it('el costo de lo que vuelve se estima en la moneda de la caja (TC de compra)', () => {
    const it = julio(detectPendingCashflows([AL30_IMPORTADO], [], [], { today: HOY, brokers: BROKERS }))
    // $ 600 por nominal vivo ÷ 1.000 = US$ 0,60 → 800 nominales = US$ 480.
    expect(it.costoAmortizado).toBeCloseTo(480, 2)
  })
})

describe('la cuenta donde entra el cobro', () => {
  it('bono en dólares de la cuenta en pesos → la cuenta en dólares', () => {
    expect(cuentaDelCobro({ broker: 'Cocos' }, 'USD', BROKERS)).toBe('Cocos · USD')
  })
  it('bono en pesos → la cuenta en pesos', () => {
    expect(cuentaDelCobro({ broker: 'Cocos' }, 'ARS', BROKERS)).toBe('Cocos')
  })
  it('broker sin cuenta en dólares → él mismo', () => {
    expect(cuentaDelCobro({ broker: 'IOL' }, 'USD', BROKERS)).toBe('IOL')
  })
})

describe('lo ya cobrado', () => {
  const importado = { id: 9, op_type: 'Dividendo', broker: 'Cocos · USD', asset: 'AL30',
                      date: '2026-07-10', quantity: 827, pnl_usd: 827 }

  it('un pago importado no se propone y aparece en "ya entraron con tu importación"', () => {
    const pend = detectPendingCashflows([AL30_IMPORTADO], [importado], [], { today: HOY, brokers: BROKERS })
    expect(julio(pend)).toBeUndefined()
    const ya = detectCobrosImportados([AL30_IMPORTADO], [importado], { today: HOY, brokers: BROKERS })
    expect(ya.map(x => [x.asset, x.date, x.comoLoLlama])).toEqual([['AL30', '2026-07-09', 'Dividendo']])
  })

  it('"aparte: cobrado" suma la ganancia realizada, no el capital que vuelve', () => {
    const ops = [
      // confirmado desde la bandeja (forma nueva): pnl_usd = ganancia, quantity = cobro
      { op_type: 'Cupón', broker: 'Cocos · USD', asset: 'AL30', date: '2026-01-09', quantity: 30, pnl_usd: 30, currency: 'USD' },
      { op_type: 'Amortización', broker: 'Cocos · USD', asset: 'AL30', date: '2026-01-09', quantity: 800, pnl_usd: 320, cost_basis_consumed: 480, currency: 'USD' },
      // amortización VIEJA: guardaba el cobro entero → se le resta el costo
      { op_type: 'Amortización', broker: 'Cocos · USD', asset: 'AL30', date: '2025-07-09', pnl_usd: 800, cost_basis_consumed: 480, currency: 'USD' },
      // importados: el cupón trae la ganancia; la amortización importada es capital (0)
      { op_type: 'Dividendo', broker: 'Cocos · USD', asset: 'AL30', date: '2025-01-10', quantity: 33, pnl_usd: 33 },
      { op_type: 'Amortización', broker: 'Cocos · USD', asset: 'AL30', date: '2024-07-10', quantity: 400, pnl_usd: 0 },
      // otro bono: no cuenta
      { op_type: 'Cupón', broker: 'Cocos · USD', asset: 'GD35', date: '2026-01-09', quantity: 50, pnl_usd: 50, currency: 'USD' },
    ]
    expect(cobradoDelBonoUsd(ops, AL30_IMPORTADO, BROKERS, 1000)).toBeCloseTo(30 + 320 + 320 + 33, 6)
  })
})

// ── Lo que encontró la auditoría del 2026-10-09 ─────────────────────────────
describe('auditoría — un pago por bono y cuenta, aunque haya varios lotes', () => {
  // Cargado a mano el 01/02/2025 (vivo 88 %) con 8.800 = 10.000 originales;
  // `bajado` = lo que ya le descontaron las amortizaciones registradas.
  const lote = (id, q, broker = 'Cocos', bajado = 8800 - q) => ({ ...AL30_IMPORTADO, id, broker, quantity: q,
    invested: q * 600, nominal_por_barrido: false, nominal_original: undefined,
    nominal_al_cargar: q + bajado, entry_date: '2025-02-01' })

  it('dos lotes del mismo bono: UNA tarjeta con el pago de los dos', () => {
    // 7.200 vivos cada uno antes de julio = 10.000 originales cada uno.
    const regs = ['2025-07-09', '2026-01-09'].map(date =>
      ({ op_type: 'Amortización', broker: 'Cocos · USD', asset: 'AL30', date, quantity: 800 }))
    const items = detectPendingCashflows([lote(1, 7200), lote(2, 7200)], regs, [], { today: HOY, brokers: BROKERS })
    const jul = items.filter(x => x.date === '2026-07-09')
    expect(jul).toHaveLength(1)
    expect(jul[0].nominales).toBe(20000)
    expect(jul[0].total).toBeCloseTo(1654, 2)
    expect(new Set(items.map(x => x.key)).size).toBe(items.length)
  })

  it('el mismo bono en la pata pesos y en la pata dólar es la misma cuenta', () => {
    const items = detectPendingCashflows([lote(1, 7200), lote(2, 7200, 'Cocos · USD')],
      ['2025-07-09', '2026-01-09'].map(date => ({ op_type: 'Amortización', broker: 'Cocos · USD', asset: 'AL30', date, quantity: 800 })),
      [], { today: HOY, brokers: BROKERS })
    expect(items.filter(x => x.date === '2026-07-09')).toHaveLength(1)
  })

  it('confirmar julio ANTES que enero no cambia lo que propone enero', () => {
    // Lote a mano: 8.000 vivos = 10.000 originales con 3 cuotas registradas (4+8+8).
    const p = lote(1, 8000)
    const antes = detectPendingCashflows([p], [{ op_type: 'Amortización', broker: 'Cocos · USD', asset: 'AL30', date: '2025-07-09', quantity: 800 }],
      [], { today: HOY, brokers: BROKERS })
    const enero = antes.find(x => x.date === '2026-01-09')
    expect(enero.total).toBeCloseTo(830, 2)
    // Se confirma julio: el servidor baja 800 nominales del lote a mano (y
    // `nominal_al_cargar` sigue en 8.800: 7.200 de hoy + 1.600 bajados).
    const despues = detectPendingCashflows([lote(1, 7200)], [
      { op_type: 'Amortización', broker: 'Cocos · USD', asset: 'AL30', date: '2025-07-09', quantity: 800 },
      { op_type: 'Amortización', broker: 'Cocos · USD', asset: 'AL30', date: '2026-07-09', quantity: 800 },
      { op_type: 'Cupón', broker: 'Cocos · USD', asset: 'AL30', date: '2026-07-09', quantity: 27 },
    ], [], { today: HOY, brokers: BROKERS })
    const enero2 = despues.find(x => x.date === '2026-01-09')
    expect(enero2.nominales).toBe(10000)
    expect(enero2.total).toBeCloseTo(830, 2)
  })
})

describe('auditoría — bonos que no son el AL30', () => {
  it('bono CER sin la serie: marcado sin ajuste (no se confirma con un click)', () => {
    const tx26 = { broker: 'Cocos', asset: 'TX26', quantity: 1000, invested: 900000, currency: 'ARS', entry_date: '2025-01-01', is_cash: 0 }
    const items = detectPendingCashflows([tx26], [], [], { today: HOY, brokers: BROKERS })
    expect(items.length).toBeGreaterThan(0)
    expect(items.every(x => x.sinAjusteCer)).toBe(true)
    expect(items.every(x => x.cuenta === 'Cocos')).toBe(true)   // bono en pesos → cuenta en pesos
  })

  it('cupón cero: el pago único devuelve todo el capital, sin números rotos', () => {
    const tzx = { broker: 'Cocos', asset: 'TZX26', quantity: 1000, invested: 900000, currency: 'ARS', entry_date: '2025-01-01', is_cash: 0 }
    const [it] = detectPendingCashflows([tzx], [], [], { today: '2026-08-01', brokers: BROKERS })
    expect(it.vivoAntes).toBe(100)
    expect(it.vivoDespues).toBe(0)
    expect(it.amortPct).toBe(100)
    expect(Number.isFinite(it.costoAmortizado)).toBe(true)
  })
})

describe('auditoría — a mano o importado, y en qué moneda', () => {
  it('la amortización que escribe el importador no cuenta como cargada a mano', () => {
    const imp = { id: 3, op_type: 'Amortización', broker: 'Cocos · USD', asset: 'AL30', date: '2026-07-10', quantity: 800, pnl_usd: 0, importada: true }
    const ya = detectCobrosImportados([AL30_IMPORTADO], [imp], { today: HOY, brokers: BROKERS })
    expect(ya.map(x => x.date)).toEqual(['2026-07-09'])
  })

  it('un cupón viejo en pesos sin moneda no se cuenta como dólares en "aparte"', () => {
    const viejo = { op_type: 'Cupón', broker: 'Cocos', asset: 'AL30', date: '2025-01-09', pnl_usd: 95000 }
    expect(cobradoDelBonoUsd([viejo], AL30_IMPORTADO, BROKERS, 1000)).toBeCloseTo(95, 6)
  })
})

describe('auditoría 2 — los nominales originales no se deducen de la cantidad', () => {
  it('lote barrido hace meses (cantidad vieja): manda el original del servidor', () => {
    // Importado en junio: quedó en 7.200 (72 %). En julio amortizó otra cuota y el
    // barrido todavía no volvió a correr. Deducido de la cantidad daba 11.250.
    const viejo = { ...AL30_IMPORTADO, quantity: 7200, nominal_original: 10000 }
    const it = julio(detectPendingCashflows([viejo], [], [], { today: HOY, brokers: BROKERS }))
    expect(it.nominales).toBe(10000)
    expect(it.total).toBeCloseTo(827, 2)
  })

  it('lote a mano de antes de que el bono amortice, al que nunca se le bajó nada', () => {
    const p = { broker: 'Cocos', asset: 'AL30', quantity: 10000, invested: 6_000_000, currency: 'ARS',
                entry_date: '2023-05-10', is_cash: 0, nominal_al_cargar: 10000 }
    const it = julio(detectPendingCashflows([p], [], [], { today: HOY, brokers: BROKERS, maxBacklogDays: 60 }))
    expect(it.nominales).toBe(10000)
    expect(it.total).toBeCloseTo(827, 2)
  })

  it('lotes comprados en fechas distintas: cada pago cuenta sólo los que ya estaban', () => {
    const a = { ...AL30_IMPORTADO, id: 1, quantity: 6400, nominal_original: 10000, entry_date: '2025-03-03' }
    const b = { ...AL30_IMPORTADO, id: 2, quantity: 6400, nominal_original: 10000, entry_date: '2026-03-01' }
    const items = detectPendingCashflows([a, b], [], [], { today: HOY, brokers: BROKERS })
    expect(items.find(x => x.date === '2026-01-09').nominales).toBe(10000)
    expect(items.find(x => x.date === '2026-07-09').nominales).toBe(20000)
  })
})

describe('auditoría 2 — la cuenta en otra moneda', () => {
  it('bono en dólares en un broker SIN cuenta en dólares: no se confirma con un click', () => {
    const soloPesos = [{ id: 9, name: 'Balanz', currency: 'ARS', parent_broker_id: null }]
    const p = { ...AL30_IMPORTADO, broker: 'Balanz' }
    const it = julio(detectPendingCashflows([p], [], [], { today: HOY, brokers: soloPesos }))
    expect(it.cuenta).toBe('Balanz')
    expect(it.cuentaMoneda).toBe('ARS')
    expect(it.otraMoneda).toBe(true)
  })
  it('con cuenta en dólares, entra ahí y no hay otra moneda', () => {
    const it = julio(detectPendingCashflows([AL30_IMPORTADO], [], [], { today: HOY, brokers: BROKERS }))
    expect([it.cuenta, it.cuentaMoneda, it.otraMoneda]).toEqual(['Cocos · USD', 'USD', false])
  })
  it('"No lo cobré" vale para toda la cuenta, aunque esa pata ya no tenga lotes', () => {
    const p = { ...AL30_IMPORTADO, broker: 'Cocos · USD', currency: 'USD', invested: 3840 }
    const skips = [{ broker: 'Cocos', asset: 'AL30', date: '2026-07-09' }]
    expect(julio(detectPendingCashflows([p], [], skips, { today: HOY, brokers: BROKERS }))).toBeUndefined()
  })
})
