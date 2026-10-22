// Tests de las cuentas de la pestaña Cobros: el estimado, el próximo cobro y las
// barras. Lo cobrado viene armado del servidor (backend/tests/test_cobros.py).
import { describe, it, expect, beforeEach } from 'vitest'
import { setBrokersRegistry } from './valuation'
import {
  estimarProximos12, proximoCobro, dividendosAnunciados, barras, variacionAnual,
  sumarAnios, tipoDeCobro, claveActivo,
} from './cobros'

const BROKERS = [
  { id: 1, name: 'Cocos', currency: 'ARS' },
  { id: 2, name: 'Schwab', currency: 'USD' },
]
const POS = [
  { asset: 'KO', broker: 'Cocos', quantity: 150 },       // 150 CEDEARs = 30 acciones
  { asset: 'GGAL', broker: 'Cocos', quantity: 100 },
  { asset: 'AL30', broker: 'Cocos', quantity: 1000 },
  { asset: 'USD', broker: 'Cocos', quantity: 500, is_cash: 1 },
]
const bono = (fecha, coupon, amort = 0, currency = 'USD') => ({
  ticker: 'AL30', eventType: amort ? 'bond_coupon_amort' : 'bond_coupon', eventDate: fecha,
  details: { coupon, amort, total: coupon + amort, currency },
})

beforeEach(() => setBrokersRegistry(BROKERS))

describe('estimarProximos12', () => {
  it('repite lo que te pagó cada empresa que seguís teniendo, un año después', () => {
    const e = estimarProximos12({
      ultimos12: [
        { fecha: '2025-11-14', activo: 'KO', tipo: 'DIVIDEND', usd: 10 },
        { fecha: '2026-04-01', activo: 'GGAL.BA', tipo: 'DIVIDEND', usd: 20 },
        { fecha: '2026-05-01', activo: 'PEP', tipo: 'DIVIDEND', usd: 99 },   // ya no la tenés
      ],
      positions: POS,
    })
    expect(e.items.map(i => [i.fecha, i.activo, i.usd])).toEqual([
      ['2026-11-14', 'KO', 10],
      ['2027-04-01', 'GGAL', 20],
    ])
    expect(e.total).toBe(30)
  })

  it('los bonos van por el cronograma, sólo el cupón, y no por su historia', () => {
    const e = estimarProximos12({
      ultimos12: [{ fecha: '2026-01-09', activo: 'AL30', tipo: 'DIVIDEND', usd: 500 }],
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
      ultimos12: [
        { fecha: '2026-03-01', activo: '', tipo: 'DIVIDEND', usd: 7 },
        { fecha: '2026-03-01', activo: 'KO', tipo: 'DIVIDEND', usd: 10 },
      ],
      positions: POS,
      anunciados: ['KO', 'GGAL'],
    })
    expect(e.sinActivoUsd).toBe(7)
    expect(e.sinHistoria).toEqual(['GGAL'])
    expect(e.total).toBe(10)
  })
})

describe('proximoCobro', () => {
  it('el más cercano entre cronograma, anunciado e historia', () => {
    const estimado = estimarProximos12({
      ultimos12: [{ fecha: '2025-12-20', activo: 'GGAL', tipo: 'DIVIDEND', usd: 20 }],
      positions: POS,
    })
    const p = proximoCobro({ estimado, eventosBonos: [bono('2027-01-09', 5, 40)], positions: POS })
    expect(p).toMatchObject({ activo: 'GGAL', fecha: '2026-12-20', usd: 20, fuente: 'historia' })
  })

  it('un dividendo anunciado se calcula con tu tenencia en la escala de la acción', () => {
    const anunciados = dividendosAnunciados([
      { ticker: 'KO', eventType: 'ex_dividend', eventDate: '2026-11-01', details: { dividend_per_share: 0.53 } },
      { ticker: 'KO', eventType: 'payment_date', eventDate: '2026-11-14', details: { dividend_per_share: 0.53 } },
    ], '2026-10-22')
    expect(anunciados).toHaveLength(1)                       // la fecha de pago manda
    const p = proximoCobro({ anunciados, positions: POS })
    expect(p.fecha).toBe('2026-11-14')
    expect(p.usd).toBeCloseTo(15.9, 2)                       // 30 acciones × 0,53, no 150 × 0,53
    expect(p.bruto).toBe(true)
  })

  it('lo anunciado manda sobre lo estimado por la historia de la misma empresa', () => {
    const estimado = estimarProximos12({
      ultimos12: [{ fecha: '2025-11-01', activo: 'KO', tipo: 'DIVIDEND', usd: 9 }],
      positions: POS,
    })
    const anunciados = [{ ticker: 'KO', eventType: 'payment_date', eventDate: '2026-11-14', details: { dividend_per_share: 0.53 } }]
    expect(proximoCobro({ estimado, anunciados, positions: POS }).fuente).toBe('anunciado')
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
