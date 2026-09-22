// El calendario de cobros del asesor corre el MISMO motor que la Cartera, una
// vez por (cliente, ticker), y suma con el nombre de cada cliente al lado.
import { describe, it, expect } from 'vitest'
import { aggregateCashflows, groupDaysByMonth, rangeEnd, settlementNote } from './aggregateCashflows'
import { nextPaymentForPosition, getRemainingPayments } from './bondSchedule'
import { getBondMeta } from './bondMeta'

const TODAY = '2026-09-21'
const clients = [
  { client_uid: 1, label: 'Ferreyra' },
  { client_uid: 2, label: 'Ocampo' },
  { client_uid: 3, label: 'Sin bonos' },
]

describe('aggregateCashflows', () => {
  it('usa el mismo motor que la Cartera: el monto de un cliente es nextPaymentForPosition', () => {
    const r = aggregateCashflows([{ client_uid: 1, asset: 'AL30', quantity: 1500, account_currency: 'ARS' }],
      clients, { today: TODAY, range: 'year', end: '2027-12-31', tcMep: 1500 })
    const esperado = nextPaymentForPosition('AL30', 1500, TODAY)
    const pay = r.days[0].payments[0]
    expect(pay.date).toBe(esperado.date)
    expect(pay.holders[0].amountUsd).toBe(esperado.total)   // AL30 paga en USD: sin conversión
    expect(pay.payCurrency).toBe('USD')
  })

  it('suma dos clientes con el mismo bono en la misma fecha, y los nombra', () => {
    const r = aggregateCashflows([
      { client_uid: 1, asset: 'AL30', quantity: 1000, account_currency: 'ARS' },
      { client_uid: 2, asset: 'AL30', quantity: 500, account_currency: 'USD' },
    ], clients, { today: TODAY, range: 'year', end: '2027-12-31', tcMep: 1500 })
    const pay = r.days[0].payments[0]
    expect(pay.holders.map(h => h.label)).toEqual(['Ferreyra', 'Ocampo'])
    const a = nextPaymentForPosition('AL30', 1000, TODAY).total
    const b = nextPaymentForPosition('AL30', 500, TODAY).total
    expect(pay.totalUsd).toBeCloseTo(a + b, 2)
    expect(r.byClient[0]).toMatchObject({ label: 'Ferreyra', assets: ['AL30'] })
    expect(r.byClient[0].totalUsd).toBeGreaterThan(r.byClient[1].totalUsd)
    expect(r.clientesSinCobros.map(c => c.label)).toEqual(['Sin bonos'])
  })

  it('la moneda de PAGO la decide el catálogo, no la pata donde está el título', () => {
    // TX26 paga en pesos (CER) aunque esté en la pata USD: se convierte con el MEP y va marcado como estimado.
    expect(getBondMeta('TX26').currency).toBe('ARS')
    const r = aggregateCashflows([{ client_uid: 1, asset: 'TX26', quantity: 100000, account_currency: 'USD' }],
      clients, { today: TODAY, range: 'year', end: '2027-12-31', tcMep: 1500 })
    const pay = r.days[0].payments[0]
    expect(pay.payCurrency).toBe('ARS')
    expect(pay.estimated).toBe(true)
    expect(pay.totalUsd).toBeCloseTo(pay.totalNative / 1500, 2)
    // Y un bono en dólares en la pata pesos NO se divide por el MEP.
    const r2 = aggregateCashflows([{ client_uid: 1, asset: 'AL30', quantity: 100, account_currency: 'ARS' }],
      clients, { today: TODAY, range: 'year', end: '2027-12-31', tcMep: 1500 })
    expect(r2.days[0].payments[0].totalUsd).toBe(r2.days[0].payments[0].totalNative)
  })

  it('sin cotización, un pago en pesos no inventa dólares', () => {
    const r = aggregateCashflows([{ client_uid: 1, asset: 'TX26', quantity: 100000, account_currency: 'ARS' }],
      clients, { today: TODAY, range: 'year', end: '2027-12-31', tcMep: null })
    const pay = r.days[0].payments[0]
    expect(pay.totalUsd).toBeNull()
    expect(pay.totalNative).toBeGreaterThan(0)
    expect(r.totals.usdRange).toBe(0)
  })

  it('respeta el rango y cuenta los 30 días aparte', () => {
    const all = getRemainingPayments('AL30', TODAY)
    const r30 = aggregateCashflows([{ client_uid: 1, asset: 'AL30', quantity: 100, account_currency: 'ARS' }],
      clients, { today: TODAY, range: '30d', tcMep: 1500 })
    const rYear = aggregateCashflows([{ client_uid: 1, asset: 'AL30', quantity: 100, account_currency: 'ARS' }],
      clients, { today: TODAY, range: 'year', end: '2027-12-31', tcMep: 1500 })
    expect(r30.days.every(d => d.date <= rangeEnd('30d', TODAY))).toBe(true)
    expect(rYear.days.length).toBe(all.filter(p => p.date <= '2027-12-31').length)
    expect(rYear.totals.count30).toBe(r30.totals.countRange)
  })

  it('un ticker sin cronograma se lista, no se pierde en silencio', () => {
    const r = aggregateCashflows([{ client_uid: 1, asset: 'FCI:COCOS-AHORRO', quantity: 500, account_currency: 'ARS' }],
      clients, { today: TODAY, range: '90d', tcMep: 1500 })
    expect(r.days).toEqual([])
    expect(r.sinCronograma).toEqual(['FCI:COCOS-AHORRO'])
  })

  // ─── Letras ───────────────────────────────────────────────────────────────
  // No están en el catálogo de bonos (no tienen prospecto): su único pago lo
  // manda el servidor leído del mercado, en `opts.letras`.
  const LETRAS = {
    S30O6: { maturity: '2026-10-30', payout_per_100: 135.33, currency: 'ARS',
             price_per_100: 132.45, tem_pct: 1.71, source: 'ArgentinaDatos' },
  }

  it('una letra entra al calendario como vencimiento, con el pago del mercado', () => {
    const r = aggregateCashflows([{ client_uid: 1, asset: 'S30O6', quantity: 1000000, account_currency: 'ARS' }],
      clients, { today: TODAY, range: 'year', tcMep: 1500, letras: LETRAS })
    expect(r.sinCronograma).toEqual([])
    const pay = r.days[0].payments[0]
    expect([pay.date, pay.kind, pay.payCurrency]).toEqual(['2026-10-30', 'vencimiento', 'ARS'])
    expect(pay.totalNative).toBeCloseTo(1353300, 2)        // 135,33 por cada 100 nominales
    expect(pay.totalUsd).toBeCloseTo(1353300 / 1500, 2)
    expect(pay.estimateKind).toBe('letra')                  // la pantalla lo marca distinto del CER
    expect(pay.holders[0].label).toBe('Ferreyra')
  })

  it('el pago de una letra NO es su nominal: capitaliza, y por eso lo trae el servidor', () => {
    // La trampa que motivó esto: mostrar "cantidad × 100" daba 1.000.000 cuando
    // el mercado dice 1.353.300 — 26 % menos plata de la que el cliente cobra.
    const r = aggregateCashflows([{ client_uid: 1, asset: 'S30O6', quantity: 1000000, account_currency: 'ARS' }],
      clients, { today: TODAY, range: 'year', tcMep: 1500, letras: LETRAS })
    expect(r.days[0].payments[0].totalNative).toBeGreaterThan(1000000)
  })

  it('una letra sin pago conocido se lista, no se inventa el monto', () => {
    // Sin catálogo (fuente caída), o un papel que no califica: mismo lugar que
    // cualquier ticker sin cronograma.
    const r = aggregateCashflows([{ client_uid: 1, asset: 'S30O6', quantity: 1000000, account_currency: 'ARS' }],
      clients, { today: TODAY, range: 'year', tcMep: 1500 })
    expect(r.days).toEqual([])
    expect(r.sinCronograma).toEqual(['S30O6'])
  })

  it('una letra que ya venció no es un cobro por venir', () => {
    const r = aggregateCashflows([{ client_uid: 1, asset: 'S30O6', quantity: 1000000, account_currency: 'ARS' }],
      clients, { today: '2026-11-15', range: 'year', tcMep: 1500, letras: LETRAS })
    expect(r.days).toEqual([])
    expect(r.sinCronograma).toEqual(['S30O6'])
  })

  it('agrupa por mes y avisa el fin de semana', () => {
    const days = [{ date: '2027-01-09', totalUsd: 10, payments: [] }, { date: '2027-01-15', totalUsd: 5, payments: [] }, { date: '2027-02-01', totalUsd: 1, payments: [] }]
    const m = groupDaysByMonth(days)
    expect(m.map(x => [x.ym, x.totalUsd])).toEqual([['2027-01', 15], ['2027-02', 1]])
    expect(settlementNote('2027-01-09')).toMatch(/sábado/)
    expect(settlementNote('2027-01-11')).toBeNull()
  })
})
