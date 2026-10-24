import { describe, it, expect, beforeEach } from 'vitest'
import { opcionesDeVenta, lotesDeLaVenta, etiquetaDeVenta, resultadoUsdDelPedazo } from './opcionesDeVenta'
import { setBrokersRegistry } from './valuation'

const B = (id, name, currency = 'ARS', parent_broker_id = null) =>
  ({ id, name, currency, parent_broker_id })
const BROKERS = [B(1, 'Cocos'), B(2, 'Cocos · USD', 'USDT', 1), B(3, 'IBKR', 'USDT')]

// Un caso con todo junto: NFLX comprado tres veces en pesos y dos en dólares,
// uno de los de dólares cargado (viejo) en el broker de pesos.
const L = (id, broker, asset, currency, quantity, entry_date, invested = 100) =>
  ({ id, broker, asset, currency, quantity, entry_date, invested, is_cash: 0 })
const POS = [
  L(1, 'Cocos', 'NFLX', 'ARS', 68, '2026-03-01', 160072),
  L(2, 'Cocos', 'NFLX', 'ARS', 50, '2026-01-10', 112200),
  L(3, 'Cocos · USD', 'NFLX', 'USD', 5, '2026-06-01', 600),
  L(4, 'Cocos', 'NFLX', 'USD', 2, '2026-02-01', 230),        // dólares en la pata de pesos (viejo)
  L(5, 'Cocos', 'INTC', 'ARS', 3, '2026-04-01', 96900),
  L(6, 'Cocos', 'INTC', 'ARS', 3, null, 79620),               // sin fecha → al final
  L(7, 'IBKR', 'NFLX', 'USD', 1, '2026-05-01', 1200),
  { id: 8, broker: 'Cocos', asset: 'ARS', is_cash: 1, quantity: 0, invested: 5000 },
]

beforeEach(() => setBrokersRegistry(BROKERS))

describe('la lista de venta', () => {
  it('una fila por cuenta, activo y moneda — no por compra ni por sub-broker', () => {
    const o = opcionesDeVenta(POS, BROKERS)
    const resumen = o.map(x => [x.cuenta, x.asset, x.moneda, x.qty, x.lots.length]).sort()
    expect(resumen).toEqual([
      ['Cocos', 'INTC', 'ARS', 6, 2],
      ['Cocos', 'NFLX', 'ARS', 118, 2],
      ['Cocos', 'NFLX', 'USD', 7, 2],      // la de Cocos y la de Cocos · USD, juntas
      ['IBKR', 'NFLX', 'USD', 1, 1],
    ].sort())
  })

  it('se manda a la pata de esa moneda y se muestra como cuenta + moneda', () => {
    const o = opcionesDeVenta(POS, BROKERS)
    const usd = o.find(x => x.cuenta === 'Cocos' && x.asset === 'NFLX' && x.moneda === 'USD')
    expect(usd.broker).toBe('Cocos · USD')
    expect(etiquetaDeVenta(usd)).toBe('Cocos · en dólares')
    const ars = o.find(x => x.cuenta === 'Cocos' && x.asset === 'NFLX' && x.moneda === 'ARS')
    expect(ars.broker).toBe('Cocos')
    expect(etiquetaDeVenta(ars)).toBe('Cocos · en pesos')
    expect(etiquetaDeVenta(o.find(x => x.cuenta === 'IBKR'))).toBe('IBKR')
  })

  it('el efectivo no se vende', () => {
    expect(opcionesDeVenta(POS, BROKERS).some(x => x.asset === 'ARS')).toBe(false)
  })

  it('si sólo tiene pesos, aparece sólo en pesos', () => {
    const o = opcionesDeVenta(POS.filter(p => p.asset === 'INTC'), BROKERS)
    expect(o.map(x => x.moneda)).toEqual(['ARS'])
  })
})

describe('los lotes que cierra la venta (FIFO, espejo del servidor)', () => {
  const ids = (broker, asset, currency) =>
    lotesDeLaVenta(POS, BROKERS, { broker, asset, currency }).map(p => p.id)

  it('en dólares: toda la cuenta, sólo dólares, del más viejo al más nuevo', () => {
    // El de dólares que quedó en la pata de pesos (feb) va antes que el de jun.
    expect(ids('Cocos · USD', 'NFLX', 'USD')).toEqual([4, 3])
    // Pedida desde el padre da lo mismo: la cuenta es una.
    expect(ids('Cocos', 'NFLX', 'USD')).toEqual([4, 3])
  })

  it('en pesos: no toca los de dólares', () => {
    expect(ids('Cocos', 'NFLX', 'ARS')).toEqual([2, 1])
  })

  it('las compras sin fecha van al final', () => {
    expect(ids('Cocos', 'INTC', 'ARS')).toEqual([5, 6])
  })

  it('otra cuenta no se mezcla', () => {
    expect(ids('IBKR', 'NFLX', 'USD')).toEqual([7])
  })
})

describe('resultadoUsdDelPedazo — la vista previa dice lo que anota el servidor', () => {
  const ggal = { cobrado: 690000, costo: 450000, enPesos: true, tcVenta: 1500, tcCompra: 1000 }
  it('cuenta v2: cada punta a su dólar (US$ 460 − US$ 450)', () => {
    expect(resultadoUsdDelPedazo({ ...ggal, cadaPuntaASuDolar: true })).toBeCloseTo(10, 6)
  })
  it('cuenta v1: la ganancia en pesos ÷ el dólar de la venta', () => {
    expect(resultadoUsdDelPedazo({ ...ggal, cadaPuntaASuDolar: false })).toBeCloseTo(160, 6)
  })
  it('sin dólar de compra queda la regla de siempre, como el servidor', () => {
    expect(resultadoUsdDelPedazo({ ...ggal, tcCompra: null, cadaPuntaASuDolar: true })).toBeCloseTo(160, 6)
  })
  it('en dólares no cambia nada', () => {
    expect(resultadoUsdDelPedazo({ cobrado: 1500, costo: 1000, enPesos: false, cadaPuntaASuDolar: true })).toBe(500)
  })
})
