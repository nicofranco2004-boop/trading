// Tests de las cuentas de la pestaña Cobros: las sumas, el cupón de un pago
// mixto, el estimado, el próximo cobro y las barras. Los renglones que llegan del
// servidor se prueban por el endpoint en backend/tests/test_cobros.py.
import { describe, it, expect, beforeEach } from 'vitest'
import { setBrokersRegistry } from './valuation'
import { generateSchedule } from './bondSchedule'
import {
  resumirCobros, cuponDelPago, cantidadEn, estimarProximos12, proximoCobro,
  dividendosAnunciados, barras, variacionAnual, sumarAnios, tipoDeCobro, claveActivo,
} from './cobros'

const BROKERS = [
  { id: 1, name: 'Cocos', currency: 'ARS' },
  { id: 2, name: 'Schwab', currency: 'USD' },
]
const POS = [
  { asset: 'KO', broker: 'Cocos', quantity: 150, entry_date: '2025-01-10' },     // 150 CEDEARs = 30 acciones
  { asset: 'GGAL', broker: 'Cocos', quantity: 100, entry_date: '2025-01-10' },
  { asset: 'AL30', broker: 'Cocos', quantity: 1000, entry_date: '2025-01-10' },
  { asset: 'USD', broker: 'Cocos', quantity: 500, is_cash: 1 },
]
const bono = (fecha, coupon, amort = 0, currency = 'USD') => ({
  ticker: 'AL30', eventType: amort ? 'bond_coupon_amort' : 'bond_coupon', eventDate: fecha,
  details: { coupon, amort, total: coupon + amort, currency },
})
const cobro = (fecha, activo, usd, tipo = 'DIVIDEND') => ({ fecha, activo, tipo, usd })

beforeEach(() => setBrokersRegistry(BROKERS))

describe('cuponDelPago', () => {
  it('separa el cupón con la proporción del cronograma de ese pago', () => {
    const pago = generateSchedule('AL30').find(p => p.date === '2026-01-09')
    expect(pago.amort).toBeGreaterThan(0)
    const usd = 43.2
    expect(cuponDelPago({ fecha: '2026-01-12', activo: 'AL30', usd }))   // el broker acreditó 3 días después
      .toBeCloseTo(usd * pago.coupon / pago.total, 6)
  })
  it('sin un pago del cronograma cerca, no adivina', () => {
    expect(cuponDelPago({ fecha: '2026-04-01', activo: 'AL30', usd: 10 })).toBeNull()
    expect(cuponDelPago({ fecha: '2026-01-09', activo: 'NOEXISTE', usd: 10 })).toBeNull()
  })
})

describe('resumirCobros', () => {
  const datos = {
    hoy: '2026-10-22',
    dias_hasta_el_pago: 21,
    cobros: [
      cobro('2025-03-01', 'KO', 5),
      cobro('2025-12-01', 'KO', 6),              // después de "hoy hace un año"
      cobro('2026-03-01', 'KO', 7),
      cobro('2026-05-20', 'GGAL.BA', 10),
      cobro('2026-06-01', 'GGAL', 2),
    ],
    pagos_mixtos: [
      { fecha: '2026-01-09', activo: 'AL30', tipo: 'MIXTO', usd: 43.2 },
      { fecha: '2026-04-01', activo: 'AL30', tipo: 'MIXTO', usd: 9 },     // sin pago del cronograma
    ],
    anios_previos: [{ anio: 2023, usd: 12 }],
  }

  it('suma el año, el mismo período del anterior y los años viejos', () => {
    const r = resumirCobros(datos)
    const cupon = cuponDelPago(datos.pagos_mixtos[0])
    expect(r.total_anio).toBeCloseTo(7 + 10 + 2 + cupon, 6)
    expect(r.total_anterior).toBe(11)
    expect(r.total_anterior_a_la_fecha).toBe(5)
    expect(r.por_anio.map(a => a.anio)).toEqual([2023, 2025, 2026])
    expect(r.por_mes[0].anio).toBeCloseTo(cupon, 6)
    expect(r.por_mes[2]).toMatchObject({ anio: 7, anterior: 5 })
  })

  it('el cupón de un pago mixto entra; lo que no se puede separar se cuenta aparte', () => {
    const r = resumirCobros(datos)
    expect(r.mixtos).toEqual({ separados: 1, sinSeparar: 1, usdSinSeparar: 9 })
    expect(r.por_activo.find(a => a.activo === 'AL30').usd).toBeCloseTo(cuponDelPago(datos.pagos_mixtos[0]), 6)
  })

  it('GGAL y GGAL.BA son la misma fila', () => {
    const r = resumirCobros(datos)
    expect(r.por_activo.find(a => a.activo === 'GGAL')).toMatchObject({ usd: 12, cobros: 2 })
    expect(r.por_activo.some(a => a.activo === 'GGAL.BA')).toBe(false)
  })

  it('los últimos 12 meses, hasta hoy', () => {
    const r = resumirCobros(datos)
    expect(r.ultimos_12_meses.map(c => c.fecha)).toEqual(['2025-12-01', '2026-01-09', '2026-03-01', '2026-05-20', '2026-06-01'])
  })
})

describe('cantidadEn', () => {
  const OPS = [
    // 75 CEDEARs de KO comprados en 2025 y vendidos en agosto de 2026.
    { asset: 'KO', broker: 'Cocos', quantity: 75, entry_date: '2025-01-10', date: '2026-08-01', op_type: 'Venta', pnl_usd: 3 },
  ]
  it('suma lo abierto y lo que todavía no se había vendido, en acciones', () => {
    expect(cantidadEn('2026-06-01', 'KO', POS, OPS)).toBe(45)      // (150 + 75) / 5
    expect(cantidadEn('2026-09-01', 'KO', POS, OPS)).toBe(30)      // ya vendido
  })
  it('sin fecha de compra no se sabe', () => {
    expect(cantidadEn('2026-06-01', 'KO', [{ asset: 'KO', broker: 'Cocos', quantity: 10 }], [])).toBeNull()
  })
})

describe('estimarProximos12', () => {
  it('repite lo cobrado de lo que seguís teniendo, ajustado a la tenencia de hoy', () => {
    const OPS = [{ asset: 'KO', broker: 'Cocos', quantity: 150, entry_date: '2025-01-10', date: '2026-08-01', op_type: 'Venta', pnl_usd: 1 }]
    const e = estimarProximos12({
      ultimos12: [
        cobro('2025-11-14', 'KO', 10),             // tenías 300 CEDEARs, hoy 150: la mitad
        cobro('2026-04-01', 'GGAL', 20),
        cobro('2026-05-01', 'PEP', 99),            // ya no la tenés
      ],
      positions: POS, operations: OPS,
    })
    expect(e.items.map(i => [i.fecha, i.activo, i.usd])).toEqual([
      ['2026-11-14', 'KO', 5],
      ['2027-04-01', 'GGAL', 20],
    ])
    expect(e.sinAjustar).toEqual([])
  })

  it('si no se sabe qué tenías al cobrar, repite sin ajustar y lo dice', () => {
    const e = estimarProximos12({
      ultimos12: [cobro('2026-04-01', 'KO', 10)],
      positions: [{ asset: 'KO', broker: 'Cocos', quantity: 150 }],
    })
    expect(e.total).toBe(10)
    expect(e.sinAjustar).toEqual(['KO'])
  })

  it('los bonos van por el cronograma, sólo el cupón, y no por su historia', () => {
    const e = estimarProximos12({
      ultimos12: [cobro('2026-01-09', 'AL30', 500)],
      positions: POS,
      eventosBonos: [bono('2027-01-09', 5, 40)],
    })
    expect(e.items).toEqual([{ fecha: '2027-01-09', activo: 'AL30', usd: 5, fuente: 'cronograma' }])
  })

  it('un cupón en pesos va al dólar de hoy; sin dólar, no se inventa', () => {
    const ev = [bono('2026-12-01', 14500, 0, 'ARS')]
    expect(estimarProximos12({ eventosBonos: ev, tc: 1450 }).total).toBe(10)
    const sin = estimarProximos12({ eventosBonos: ev })
    expect(sin.total).toBe(0)
    expect(sin.cuponesSinDolar).toBe(1)
  })

  it('dice lo que no entra: cobros sin activo y dividendos anunciados sin historia', () => {
    const e = estimarProximos12({
      ultimos12: [cobro('2026-03-01', '', 7), cobro('2026-03-01', 'KO', 10)],
      positions: POS,
      anunciados: ['KO', 'GGAL'],
    })
    expect(e.sinActivoUsd).toBe(7)
    expect(e.sinHistoria).toEqual(['GGAL'])
    expect(e.total).toBe(10)
  })
})

describe('proximoCobro', () => {
  const ctx = { positions: POS }

  it('el más cercano entre cronograma, anunciado e historia', () => {
    const estimado = estimarProximos12({ ultimos12: [cobro('2025-12-20', 'GGAL', 20)], positions: POS })
    const p = proximoCobro({ estimado, eventosBonos: [bono('2027-01-09', 5, 40)], cobroCtx: ctx })
    expect(p).toMatchObject({ activo: 'GGAL', fecha: '2026-12-20', usd: 20, fuente: 'historia' })
  })

  it('un dividendo anunciado se calcula con la misma cuenta que Eventos', () => {
    const anunciados = dividendosAnunciados([
      { ticker: 'KO', eventType: 'ex_dividend', eventDate: '2026-11-01', details: { dividend_per_share: 0.53 } },
      { ticker: 'KO', eventType: 'payment_date', eventDate: '2026-11-14', details: { dividend_per_share: 0.53 } },
    ], '2026-10-22')
    expect(anunciados).toHaveLength(1)                       // la fecha de pago manda
    const p = proximoCobro({ anunciados, cobroCtx: ctx })
    expect(p.fecha).toBe('2026-11-14')
    expect(p.usd).toBeCloseTo(15.9, 2)                       // 30 acciones × 0,53, no 150 × 0,53
    expect(p.bruto).toBe(true)
  })

  it('si sólo se conoce el corte, la plata entra los días de la regla después', () => {
    const anunciados = [{ ticker: 'KO', eventType: 'ex_dividend', eventDate: '2026-12-01', details: { dividend_per_share: 0.53 } }]
    const p = proximoCobro({ anunciados, cobroCtx: ctx, diasHastaElPago: 21, eventosBonos: [bono('2026-12-09', 5)] })
    // El cupón del 9/12 entra antes que el dividendo de KO (corte 1/12 → ~22/12).
    expect(p.activo).toBe('AL30')
    const ko = proximoCobro({ anunciados, cobroCtx: ctx, diasHastaElPago: 21 })
    expect(ko).toMatchObject({ fecha: '2026-12-22', corte: '2026-12-01' })
  })

  it('un monto que cubre sólo parte de la tenencia no se publica', () => {
    const conAccionReal = [...POS, { asset: 'XYZQ', broker: 'Schwab', quantity: 10 }, { asset: 'XYZQ', broker: 'Cocos', quantity: 40 }]
    const anunciados = [{ ticker: 'XYZQ', eventType: 'payment_date', eventDate: '2026-11-14', details: { dividend_per_share: 1 } }]
    const p = proximoCobro({ anunciados, cobroCtx: { positions: conAccionReal } })
    expect(p).toMatchObject({ activo: 'XYZQ', usd: null, parcial: true })
  })

  it('lo anunciado manda sobre lo estimado por la historia de la misma empresa', () => {
    const estimado = estimarProximos12({ ultimos12: [cobro('2025-11-01', 'KO', 9)], positions: POS })
    const anunciados = [{ ticker: 'KO', eventType: 'payment_date', eventDate: '2026-11-14', details: { dividend_per_share: 0.53 } }]
    expect(proximoCobro({ estimado, anunciados, cobroCtx: ctx }).fuente).toBe('anunciado')
  })

  it('sin nada que respalde un cobro, null', () => {
    expect(proximoCobro({ estimado: { items: [] } })).toBeNull()
  })
})

describe('barras', () => {
  const resumen = {
    anio: 2026,
    total_anio: 60, total_anterior_a_la_fecha: 40,
    por_mes: Array.from({ length: 12 }, (_, k) => ({ mes: k + 1, anio: k < 10 ? 6 : 0, anterior: 5 })),
    por_anio: [{ anio: 2024, usd: 10 }, { anio: 2025, usd: 60 }, { anio: 2026, usd: 60 }],
  }
  const estimado = { items: [
    { fecha: '2026-11-14', activo: 'KO', usd: 10, fuente: 'historia' },
    { fecha: '2027-01-09', activo: 'AL30', usd: 5, fuente: 'cronograma' },   // otro año: no entra
  ] }

  it('por mes: lo cobrado, lo estimado en los meses que faltan y el año anterior', () => {
    const b = barras(resumen, estimado, 'mes')
    expect(b).toHaveLength(12)
    expect(b[10]).toMatchObject({ etiqueta: 'N', cobrado: 0, estimado: 10, anterior: 5 })
    expect(b[0]).toMatchObject({ cobrado: 6, estimado: 0 })
  })

  it('por trimestre suma de a tres meses', () => {
    const b = barras(resumen, estimado, 'trimestre')
    expect(b.map(x => x.etiqueta)).toEqual(['T1', 'T2', 'T3', 'T4'])
    expect(b[3]).toMatchObject({ cobrado: 6, estimado: 10, anterior: 15 })
  })

  it('por año: desde el primero con cobros, lo que falta del año en curso como estimado', () => {
    const b = barras(resumen, estimado, 'anio')
    expect(b.map(x => [x.etiqueta, x.cobrado, x.estimado])).toEqual([
      ['2024', 10, 0], ['2025', 60, 0], ['2026', 60, 10],
    ])
  })
})

describe('detalles', () => {
  it('variación contra el mismo período; sin base, null', () => {
    expect(variacionAnual({ total_anio: 60, total_anterior_a_la_fecha: 40 })).toBeCloseTo(0.5)
    expect(variacionAnual({ total_anio: 60, total_anterior_a_la_fecha: 0 })).toBeNull()
  })
  it('el 29/2 cae al 28 en un año no bisiesto', () => {
    expect(sumarAnios('2028-02-29', 1)).toBe('2029-02-28')
    expect(sumarAnios('2025-11-14', 1)).toBe('2026-11-14')
  })
  it('rótulos y claves', () => {
    expect(tipoDeCobro('AL30', ['DIVIDEND'])).toBe('Cupones')
    expect(tipoDeCobro('KO', ['DIVIDEND'])).toBe('Dividendos')
    expect(tipoDeCobro('', ['DIVIDEND'])).toBe('Sin activo')
    expect(claveActivo('aapl.ba')).toBe('AAPL')
  })
})
