import { describe, it, expect } from 'vitest'
import { suggestBrokerAmount, sameCurrency } from './bondCashflowFx.js'

// TC de referencia: el MEP del día del pago vs uno muy distinto de "hoy", para que
// un test que tome el dólar equivocado no pueda pasar por casualidad.
const MEP_PAGO = 1254.3756
const MEP_HOY = 1890.0
const FECHA_PAGO = '2026-07-09'

const fxDe = (tc, asOf = FECHA_PAGO, source = 'mep') => ({ tc, asOf, source })

describe('sameCurrency', () => {
  it('USDT y USD son la misma plata', () => {
    expect(sameCurrency('USDT', 'USD')).toBe(true)
    expect(sameCurrency('USD', 'USDT')).toBe(true)
  })
  it('ARS no es USD', () => {
    expect(sameCurrency('ARS', 'USD')).toBe(false)
  })
  it('null no matchea con nada', () => {
    expect(sameCurrency(null, 'USD')).toBe(false)
    expect(sameCurrency('ARS', undefined)).toBe(false)
  })
})

describe('suggestBrokerAmount — el caso argentino (bono USD, broker ARS)', () => {
  it('multiplica por el MEP de la FECHA DEL PAGO, no por el de hoy', () => {
    const r = suggestBrokerAmount({
      theoreticalAmount: 100,
      bondCurrency: 'USD',
      brokerCurrency: 'ARS',
      paymentDate: FECHA_PAGO,
      fx: fxDe(MEP_PAGO),
    })
    expect(r.applies).toBe(true)
    expect(r.amount).toBe(125437.56)
    expect(r.amount).not.toBe(round2(100 * MEP_HOY))
    expect(r.tc).toBe(MEP_PAGO)
    expect(r.stale).toBe(false)
    expect(r.operacion).toBe('multiplicar')
  })

  it('el fx a sellar ES el TC: la fila queda en pesos', () => {
    const r = suggestBrokerAmount({
      theoreticalAmount: 100,
      bondCurrency: 'USD', brokerCurrency: 'ARS',
      paymentDate: FECHA_PAGO, fx: fxDe(MEP_PAGO),
    })
    expect(r.fxToUsdForRow).toBe(MEP_PAGO)
    // round-trip: el monto en pesos dividido por el sello da el teórico en USD
    expect(round2(r.amount / r.fxToUsdForRow)).toBe(100)
  })

  it('marca stale y expone la fecha real cuando el TC es de un día anterior', () => {
    const r = suggestBrokerAmount({
      theoreticalAmount: 100,
      bondCurrency: 'USD',
      brokerCurrency: 'ARS',
      paymentDate: FECHA_PAGO,          // jueves
      fx: fxDe(MEP_PAGO, '2026-07-06'), // el último con dato
    })
    expect(r.stale).toBe(true)
    expect(r.asOf).toBe('2026-07-06')
  })

  it('declara cuando el TC vino del blue (fecha pre-serie MEP)', () => {
    const r = suggestBrokerAmount({
      theoreticalAmount: 100,
      bondCurrency: 'USD',
      brokerCurrency: 'ARS',
      paymentDate: '2015-03-10',
      fx: fxDe(9.5, '2015-03-10', 'blue'),
    })
    expect(r.applies).toBe(true)
    expect(r.source).toBe('blue')
    expect(r.amount).toBe(950)
  })
})

describe('suggestBrokerAmount — la dirección inversa (bono ARS, broker USD)', () => {
  it('divide: un TZX26 en una cuenta en dólares', () => {
    const r = suggestBrokerAmount({
      theoreticalAmount: 125437.56,
      bondCurrency: 'ARS',
      brokerCurrency: 'USD',
      paymentDate: FECHA_PAGO,
      fx: fxDe(MEP_PAGO),
    })
    expect(r.applies).toBe(true)
    expect(r.amount).toBe(100)
    expect(r.operacion).toBe('dividir')
  })

  it('el fx a sellar es 1, NO el TC: la fila queda en dólares', () => {
    // El bug: sellar el TC (1254) sobre una fila cuya moneda es USD hace que todo
    // lector que divida muestre US$100 como US$0,08.
    const r = suggestBrokerAmount({
      theoreticalAmount: 125437.56,
      bondCurrency: 'ARS', brokerCurrency: 'USD',
      paymentDate: FECHA_PAGO, fx: fxDe(MEP_PAGO),
    })
    expect(r.fxToUsdForRow).toBe(1)
    expect(r.amount / r.fxToUsdForRow).toBe(100)   // round-trip: da el monto en USD
  })

  it('también con broker USDT', () => {
    const r = suggestBrokerAmount({
      theoreticalAmount: 125437.56,
      bondCurrency: 'ARS',
      brokerCurrency: 'USDT',
      paymentDate: FECHA_PAGO,
      fx: fxDe(MEP_PAGO),
    })
    expect(r.amount).toBe(100)
  })
})

describe('suggestBrokerAmount — cuando NO hay que sugerir', () => {
  it('misma moneda: no aplica y no toca el teórico', () => {
    for (const [bond, broker] of [['USD', 'USD'], ['ARS', 'ARS'], ['USD', 'USDT']]) {
      const r = suggestBrokerAmount({
        theoreticalAmount: 100, bondCurrency: bond, brokerCurrency: broker,
        paymentDate: FECHA_PAGO, fx: fxDe(MEP_PAGO),
      })
      expect(r.applies).toBe(false)
      expect(r.amount).toBe(null)
    }
  })

  it('bono fuera del catálogo (currency null): no aplica, sin romper', () => {
    const r = suggestBrokerAmount({
      theoreticalAmount: 100, bondCurrency: null, brokerCurrency: 'ARS',
      paymentDate: FECHA_PAGO, fx: fxDe(MEP_PAGO),
    })
    expect(r.applies).toBe(false)
    expect(r.amount).toBe(null)
  })

  it('sin TC: aplica pero NO inventa un monto, y lo declara', () => {
    const r = suggestBrokerAmount({
      theoreticalAmount: 100, bondCurrency: 'USD', brokerCurrency: 'ARS',
      paymentDate: FECHA_PAGO, fx: { tc: null, asOf: null, source: null },
    })
    expect(r.applies).toBe(true)   // el modal sabe que hay conversión pendiente
    expect(r.amount).toBe(null)    // pero no sugiere nada
    expect(r.faltaTc).toBe(true)   // y la UI puede decir POR QUÉ
  })

  it('sin monto teórico NO es culpa del dólar', () => {
    // El modal decía "no tenemos el dólar del X" cuando en realidad el dólar estaba
    // y lo que faltaba era el cronograma. Mentirle al usuario sobre la causa lo
    // manda a buscar el problema donde no está.
    const r = suggestBrokerAmount({
      theoreticalAmount: null, bondCurrency: 'USD', brokerCurrency: 'ARS',
      paymentDate: FECHA_PAGO, fx: fxDe(MEP_PAGO),
    })
    expect(r.applies).toBe(true)
    expect(r.amount).toBe(null)
    expect(r.faltaTc).toBe(false)
  })

  it('serie sin cargar (fx undefined): no sugiere', () => {
    const r = suggestBrokerAmount({
      theoreticalAmount: 100, bondCurrency: 'USD', brokerCurrency: 'ARS',
      paymentDate: FECHA_PAGO,
    })
    expect(r.amount).toBe(null)
  })

  it('monto teórico 0 o negativo: no sugiere', () => {
    for (const amt of [0, -5, null]) {
      const r = suggestBrokerAmount({
        theoreticalAmount: amt, bondCurrency: 'USD', brokerCurrency: 'ARS',
        paymentDate: FECHA_PAGO, fx: fxDe(MEP_PAGO),
      })
      expect(r.amount).toBe(null)
    }
  })

  it('sin argumentos: no explota', () => {
    expect(suggestBrokerAmount().amount).toBe(null)
    expect(suggestBrokerAmount({}).applies).toBe(false)
  })
})

describe('suggestBrokerAmount — idempotencia', () => {
  it('llamarlo dos veces da lo mismo (no acumula conversión)', () => {
    const args = {
      theoreticalAmount: 100, bondCurrency: 'USD', brokerCurrency: 'ARS',
      paymentDate: FECHA_PAGO, fx: fxDe(MEP_PAGO),
    }
    expect(suggestBrokerAmount(args).amount).toBe(suggestBrokerAmount(args).amount)
  })

  it('el resultado NO se puede re-alimentar como teórico sin volver a inflar', () => {
    // Guarda conceptual: si algún día alguien pasa el convertido como teórico,
    // el número explota. El modal tiene que seguir derivando de `estimate`.
    const uno = suggestBrokerAmount({
      theoreticalAmount: 100, bondCurrency: 'USD', brokerCurrency: 'ARS',
      paymentDate: FECHA_PAGO, fx: fxDe(MEP_PAGO),
    })
    const dos = suggestBrokerAmount({
      theoreticalAmount: uno.amount, bondCurrency: 'USD', brokerCurrency: 'ARS',
      paymentDate: FECHA_PAGO, fx: fxDe(MEP_PAGO),
    })
    expect(dos.amount).toBeGreaterThan(uno.amount * 1000)
  })
})

function round2(n) { return Math.round(n * 100) / 100 }
