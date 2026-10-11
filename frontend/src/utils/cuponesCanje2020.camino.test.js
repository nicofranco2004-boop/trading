/**
 * Los cupones de los bonos del canje 2020, por el camino que recorre la app.
 *
 * `bondSchedulesAR.test.js` fija la TABLA contra el prospecto. Este archivo mira
 * otra cosa: que el monto que termina en cada pantalla sea el que paga el bono.
 * Parte de una tenencia como la que manda /api/positions y pasa por las mismas
 * funciones que llaman las pantallas:
 *
 *   · la bandeja «Tenés N cobros para confirmar»  → detectPendingCashflows
 *     (Positions.jsx la llama con las posiciones, los cobros anotados y los
 *     salteados; el monto que devuelve es el que pre-llena el formulario)
 *   · el «próximo cobro» de la ficha y del formulario → nextPaymentForPosition
 *   · la tarjeta y la página de eventos              → upcomingBondEvents
 *   · el calendario de cobros del asesor             → aggregateCashflows
 *   · la TIR y el cronograma de la ficha             → estimateYieldDetailed /
 *                                                      getRemainingPayments
 *   · el renglón «Cupón» de la ficha                 → formatCouponLabel
 *
 * Hasta 2026-10-10 el catálogo tenía tasas «de memoria» en cuatro bonos y todas
 * esas pantallas mostraban de menos: por 1.000 nominales de GD35 la bandeja
 * proponía US$ 7,50 por semestre y el bono paga US$ 20,63; por 1.000 de GD38,
 * US$ 19,38 contra US$ 25. Los números de abajo salen de la tabla «Financial
 * terms of the New Bonds» del suplemento de prospecto presentado ante la SEC el
 * 17/08/2020 (págs. S-32 a S-35):
 *   https://www.sec.gov/Archives/edgar/data/914021/000119312520221606/d68512d424b5.htm
 *
 * Las tenencias de acá son de bonos que todavía NO devolvieron capital (2035,
 * 2038 y 2041) o que se compraron antes de la primera cuota (2046): en ellas
 * «los nominales que tengo» y «los nominales originales» son el mismo número, y
 * el monto no depende de cómo se cuenten. Los que ya amortizan (2029 y 2030)
 * tienen su propia prueba junto a la bandeja de cobros.
 */
import { describe, it, expect } from 'vitest'
import { detectPendingCashflows } from './pendingCashflows.js'
import {
  nextPaymentForPosition, estimateYieldDetailed, getRemainingPayments,
} from './bondSchedule.js'
import { upcomingBondEvents } from './upcomingEvents.js'
import { aggregateCashflows } from './aggregateCashflows.js'
import { getBondMeta, formatCouponLabel, tasaVigente, BOND_META } from './bondMeta.js'
import { CANJE_2020_BY_TICKER } from './bondSchedulesAR.js'

const HOY = '2026-10-10'

// Una tenencia como la que llega de /api/positions: 1.000 nominales comprados
// en 2023, en la cuenta en dólares del broker.
const tenencia = (asset, extra = {}) => ({
  id: 1, broker: 'IOL · USD', asset, quantity: 1000, is_cash: 0,
  buy_price: 0.3, invested: 300, currency: 'USDT', entry_date: '2023-03-01',
  client_uid: 'c1', ...extra,
})

// Lo que paga cada bono por 1.000 nominales, semestre por semestre (prospecto).
// La tasa es anual: cada pago es la mitad, sobre lo que queda vivo.
const PAGA = {
  // 2035: 1,5 % hasta jul-2023 · 3,625 % · 4,125 % desde jul-2024 · 4,75 % · 5 %
  GD35: { '2023-07-09': 7.50, '2024-01-09': 18.125, '2024-07-09': 18.125, '2025-01-09': 20.625,
          '2025-07-09': 20.625, '2026-01-09': 20.625, '2026-07-09': 20.625, '2027-01-09': 20.625,
          '2027-07-09': 20.625, '2028-01-09': 23.75, '2028-07-09': 23.75, '2029-01-09': 25 },
  // 2038: 3,875 % hasta jul-2023 · 4,25 % · 5 % desde jul-2024
  GD38: { '2023-07-09': 19.375, '2024-01-09': 21.25, '2024-07-09': 21.25, '2025-01-09': 25,
          '2025-07-09': 25, '2026-01-09': 25, '2026-07-09': 25, '2027-01-09': 25 },
  // 2041: 3,5 % de jul-2022 a jul-2029 (no cambió con el arreglo: testigo)
  GD41: { '2025-01-09': 17.50, '2025-07-09': 17.50, '2026-01-09': 17.50, '2026-07-09': 17.50,
          '2027-01-09': 17.50 },
}
const LEY_LOCAL = { GD35: 'AL35', GD38: 'AE38', GD41: 'AL41' }

describe('la bandeja de cobros propone lo que paga el bono', () => {
  for (const [global, pagos] of Object.entries(PAGA)) {
    for (const ticker of [global, LEY_LOCAL[global]]) {
      it(`${ticker}: los cuatro semestres que la bandeja tiene a la vista`, () => {
        const items = detectPendingCashflows([tenencia(ticker)], [], [], { today: HOY })
        // Mira dos años para atrás: enero 2025 a julio 2026.
        const fechas = ['2025-01-09', '2025-07-09', '2026-01-09', '2026-07-09']
        expect(items.map(x => x.date).sort()).toEqual(fechas)
        for (const x of items) {
          expect(x.kind).toBe('cupon')
          expect(x.amort).toBe(0)
          expect(x.coupon, `${ticker} ${x.date}`).toBeCloseTo(pagos[x.date], 1)
          expect(x.total).toBe(x.coupon)
          expect(x.currency).toBe('USD')
        }
      })
    }
  }

  it('GD35 y GD38: los tramos que el catálogo viejo no tenía (2023-24)', () => {
    // Parado en agosto 2024, la bandeja ve los pagos de 2023 y 2024: ahí están
    // el 3,625 % del 2035 y el 4,25 % del 2038, que antes no existían.
    for (const ticker of ['GD35', 'GD38']) {
      const items = detectPendingCashflows([tenencia(ticker)], [], [], { today: '2024-08-01' })
      const porFecha = Object.fromEntries(items.map(x => [x.date, x.coupon]))
      for (const f of ['2023-07-09', '2024-01-09', '2024-07-09']) {
        expect(porFecha[f], `${ticker} ${f}`).toBeCloseTo(PAGA[ticker][f], 1)
      }
    }
  })

  it('un cobro ya anotado no vuelve a aparecer; los otros siguen con su monto', () => {
    const anotado = [{ op_type: 'Cupón', broker: 'IOL · USD', asset: 'GD35', date: '2026-07-10', pnl_usd: 20.63 }]
    const items = detectPendingCashflows([tenencia('GD35')], anotado, [], { today: HOY })
    expect(items.map(x => x.date)).not.toContain('2026-07-09')
    expect(items.find(x => x.date === '2026-01-09').coupon).toBeCloseTo(20.625, 1)
  })

  it('GD46: 4,125 % sobre lo que queda vivo, y la primera cuota de capital es la de enero 2025', () => {
    const items = detectPendingCashflows([tenencia('GD46')], [], [], { today: HOY })
    const porFecha = Object.fromEntries(items.map(x => [x.date, x]))
    // 44 cuotas iguales desde el 09/01/2025. Antes de la de julio 2026 ya se
    // devolvieron 3: queda vivo 100 − 3×(100/44) = 93,18 %.
    const cuota = 1000 / 44
    expect(porFecha['2026-07-09'].coupon).toBeCloseTo(1000 * (1 - 3 / 44) * 0.04125 / 2, 1)   // 19,22
    expect(porFecha['2026-07-09'].amort).toBeCloseTo(cuota, 1)                                // 22,73
    // Enero 2025: cupón sobre el 100 % (todavía no había devuelto nada) + 1ª cuota.
    expect(porFecha['2025-01-09'].coupon).toBeCloseTo(20.625, 1)
    expect(porFecha['2025-01-09'].amort).toBeCloseTo(cuota, 1)
  })

  it('GD46: en julio 2024 no hubo devolución de capital (el catálogo viejo inventaba una)', () => {
    const items = detectPendingCashflows([tenencia('GD46')], [], [], { today: '2024-08-01' })
    const julio = items.find(x => x.date === '2024-07-09')
    expect(julio.kind).toBe('cupon')
    expect(julio.amort).toBe(0)
    expect(julio.coupon).toBeCloseTo(18.125, 1)       // 3,625 %/2 sobre el 100 %
  })
})

describe('el próximo cobro', () => {
  it('GD35: los que vienen, con los escalones de 2027 y 2028', () => {
    const desde = { [HOY]: '2027-01-09', '2027-02-01': '2027-07-09', '2027-08-01': '2028-01-09',
                    '2028-02-01': '2028-07-09', '2028-08-01': '2029-01-09' }
    for (const [hoy, fecha] of Object.entries(desde)) {
      const r = nextPaymentForPosition('GD35', 1000, hoy)
      expect(r.date).toBe(fecha)
      expect(r.coupon, fecha).toBeCloseTo(PAGA.GD35[fecha], 1)
      expect(r.amort).toBe(0)
      expect(r.isPureCoupon).toBe(true)
    }
  })

  it('AE38 y GD38: US$ 25 por 1.000 nominales', () => {
    for (const ticker of ['AE38', 'GD38']) {
      const r = nextPaymentForPosition(ticker, 1000, HOY)
      expect(r.date).toBe('2027-01-09')
      expect(r.coupon).toBeCloseTo(25, 2)
    }
  })

  it('AL29 y GD29: 1 % fijo, también después de julio 2027 (el catálogo viejo subía a 1,75 %)', () => {
    // Por 100 nominales ORIGINALES: en enero 2028 queda vivo el 40 % → 0,5 % de 40.
    for (const ticker of ['AL29', 'GD29']) {
      const enero2028 = getRemainingPayments(ticker, HOY).find(p => p.date === '2028-01-09')
      expect(enero2028.rate).toBe(1)
      expect(enero2028.coupon).toBeCloseTo(0.20, 4)
    }
  })
})

describe('eventos y calendario de cobros', () => {
  it('la tarjeta de próximos eventos publica el cupón real', () => {
    const ev = upcomingBondEvents([tenencia('GD35'), tenencia('AE38')], { today: HOY, windowDays: 120 })
    const de = (t) => ev.find(e => e.ticker === t && e.eventDate === '2027-01-09')
    expect(de('GD35').eventType).toBe('bond_coupon')
    expect(de('GD35').details.coupon).toBeCloseTo(20.625, 1)
    expect(de('AE38').details.coupon).toBeCloseTo(25, 2)
  })

  it('el calendario del asesor suma el cupón real de cada cliente', () => {
    const libro = [tenencia('GD35', { client_uid: 'c1' }), tenencia('GD35', { client_uid: 'c2', quantity: 3000 }),
                   tenencia('GD38', { client_uid: 'c1' })]
    const r = aggregateCashflows(libro, [{ client_uid: 'c1', label: 'Ana' }, { client_uid: 'c2', label: 'Beto' }],
      { today: HOY, end: '2027-01-31' })
    const dia = r.days.find(d => d.date === '2027-01-09')
    const pago = (t) => dia.payments.find(p => p.asset === t)
    expect(pago('GD35').totalUsd).toBeCloseTo(4 * 20.625, 1)      // 4.000 nominales
    expect(pago('GD38').totalUsd).toBeCloseTo(25, 2)
    expect(pago('GD35').holders.find(h => h.client_uid === 'c2').amountUsd).toBeCloseTo(3 * 20.625, 1)
  })
})

describe('la ficha del bono', () => {
  it('GD35: lo que falta cobrar de intereses hasta 2035, por 100 nominales', () => {
    // 2027: 2 pagos de 2,0625 · 2028: 2 de 2,375 · 2029-30: 4 de 2,5 sobre 100 ·
    // 2031-35: 5 % anual sobre lo que queda (100, 90, 80 … 10) = 13,75.
    const intereses = getRemainingPayments('GD35', HOY).reduce((s, p) => s + p.coupon, 0)
    expect(intereses).toBeCloseTo(2 * 2.0625 + 2 * 2.375 + 4 * 2.5 + 13.75, 4)   // 32,625 (decía 22,34)
  })

  it('GD38: lo que falta cobrar de intereses hasta 2038, por 100 nominales', () => {
    // 5 % anual. Enero y julio 2027 sobre 100; después cada pago sobre lo que
    // queda tras cada una de las 22 cuotas: 2,5 % × (21 + 20 + … + 1)/22 × 100.
    const intereses = getRemainingPayments('GD38', HOY).reduce((s, p) => s + p.coupon, 0)
    expect(intereses).toBeCloseTo(2 * 2.5 + 2.5 * (21 * 22 / 2) / 22, 4)         // 31,25 (decía 30,13)
  })

  it('la TIR sale de esos flujos: la que descuenta lo que falta cobrar hasta el precio', () => {
    // Cuenta propia, sin pasar por el motor: 30/360, capitalización anual, y el
    // precio "sucio" que informa la función (precio + interés corrido).
    const t360 = (a, b) => {
      const [y1, m1, d1] = a.split('-').map(Number), [y2, m2, d2] = b.split('-').map(Number)
      return ((y2 - y1) * 360 + (m2 - m1) * 30 + (Math.min(d2, 30) - Math.min(d1, 30))) / 360
    }
    for (const [ticker, precio] of [['GD35', 70], ['GD38', 75], ['GD46', 68]]) {
      const r = estimateYieldDetailed(ticker, precio, HOY)
      expect(r.converged).toBe(true)
      const vp = getRemainingPayments(ticker, HOY)
        .reduce((s, p) => s + p.total / Math.pow(1 + r.ytm, t360(HOY, p.date)), 0)
      expect(vp, ticker).toBeCloseTo(r.dirty, 2)
    }
  })

  it('el renglón «Cupón» de la ficha', () => {
    // Escalonados: de la tasa más baja a la más alta de su vida.
    expect(formatCouponLabel(getBondMeta('GD35'))).toMatch(/step-up 0,125\s?% → 5\s?% TNA \(semestral\)/)
    expect(formatCouponLabel(getBondMeta('AE38'))).toMatch(/step-up 0,125\s?% → 5\s?% TNA \(semestral\)/)
    expect(formatCouponLabel(getBondMeta('GD41'))).toMatch(/step-up 0,125\s?% → 4,875\s?% TNA/)
    // El 2029 no es escalonado: 1 % fijo, medio punto por cupón.
    const al29 = formatCouponLabel(getBondMeta('AL29'))
    expect(al29).not.toMatch(/step-up/)
    expect(al29).toMatch(/cupón 1\s?% TNA \(0,5\s?% por cupón, semestral\)/)
  })

  it('ningún bono del canje dice «cronograma aproximado»: todos están cotejados con el prospecto', () => {
    for (const [ticker, cat] of Object.entries(CANJE_2020_BY_TICKER)) {
      expect(cat._verificationLevel, ticker).toBe('verified')
      expect(cat._prospectusRef, ticker).toMatch(/SEC 424B5/)
    }
  })
})

describe('la tasa «de rótulo» sale del cronograma, no de una segunda lista', () => {
  // bondMeta guardaba un `couponRate` escrito a mano por bono (GD35: 1,875 %,
  // que no es ninguna tasa del prospecto). Ahora es el tramo vigente del mismo
  // cronograma con el que se calculan los pagos.
  it('tasaVigente lee el tramo que corresponde a la fecha', () => {
    const gd35 = CANJE_2020_BY_TICKER.GD35
    expect(tasaVigente(gd35, '2024-01-01')).toBe(3.625)
    expect(tasaVigente(gd35, HOY)).toBe(4.125)
    expect(tasaVigente(gd35, '2027-10-10')).toBe(4.75)
    expect(tasaVigente(gd35, '2030-01-01')).toBe(5)
    expect(tasaVigente(CANJE_2020_BY_TICKER.AE38, HOY)).toBe(5)
    expect(tasaVigente(CANJE_2020_BY_TICKER.AL29, HOY)).toBe(1)
    expect(tasaVigente(CANJE_2020_BY_TICKER.GD46, '2027-10-10')).toBe(4.375)
    expect(tasaVigente(gd35, '2040-01-01')).toBeNull()          // ya vencido
  })

  it('el día del cambio de tramo vale la tasa del tramo que termina (igual que el motor)', () => {
    // El cupón que se paga el 09/07/2027 se devengó al 4,125 %.
    expect(tasaVigente(CANJE_2020_BY_TICKER.GD35, '2027-07-09')).toBe(4.125)
    const pago = getRemainingPayments('GD35', HOY).find(p => p.date === '2027-07-09')
    expect(pago.rate).toBe(4.125)
  })

  it('el `couponRate` de cada bono del canje es una tasa de SU cronograma', () => {
    for (const ticker of Object.keys(CANJE_2020_BY_TICKER)) {
      const tasas = CANJE_2020_BY_TICKER[ticker].couponSchedule.map(c => c.rate)
      expect(tasas, ticker).toContain(BOND_META[ticker].couponRate)
    }
  })
})
