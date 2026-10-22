import { describe, it, expect } from 'vitest'
import {
  esPataDolar, brokersParaElegir, admiteDosMonedas, cuentaDe, pataDeLaMoneda, formularioDeCaja,
} from './pataDeLaMoneda'

const B = (id, name, currency = 'ARS', parent_broker_id = null) =>
  ({ id, name, currency, parent_broker_id })

const COCOS = B(1, 'Cocos')
const COCOS_USD = B(2, 'Cocos · USD', 'USDT', 1)
const IOL = B(3, 'IOL')                       // cuenta argentina SIN pata en dólares todavía
const IBKR = B(4, 'IBKR', 'USDT')
const BROKERS = [COCOS, COCOS_USD, IOL, IBKR]

describe('qué brokers se ofrecen', () => {
  it('la pata en dólares de una cuenta argentina no se ofrece', () => {
    expect(brokersParaElegir(BROKERS).map(b => b.name)).toEqual(['Cocos', 'IOL', 'IBKR'])
  })
  it('se reconoce por el padre, no por el nombre', () => {
    // Renombrada sin el sufijo: sigue siendo la pata en dólares de Cocos.
    expect(esPataDolar(B(2, 'Dólares de Cocos', 'USDT', 1), BROKERS)).toBe(true)
    // Un broker que se llama "· USD" pero no tiene padre es un broker más.
    expect(esPataDolar(B(9, 'Algo · USD', 'USDT'), BROKERS)).toBe(false)
  })
  it('una cuenta argentina admite pesos y dólares; una del exterior no', () => {
    expect(admiteDosMonedas('Cocos', BROKERS)).toBe(true)
    expect(admiteDosMonedas('IOL', BROKERS)).toBe(true)
    expect(admiteDosMonedas('Cocos · USD', BROKERS)).toBe(true)
    expect(admiteDosMonedas('IBKR', BROKERS)).toBe(false)
  })
})

describe('a qué caja va', () => {
  it('Cocos + dólares → la pata en dólares', () => {
    expect(pataDeLaMoneda(BROKERS, 'Cocos', 'USD')).toBe('Cocos · USD')
    expect(pataDeLaMoneda(BROKERS, 'Cocos', 'ARS')).toBe('Cocos')
    expect(pataDeLaMoneda(BROKERS, 'Cocos · USD', 'ARS')).toBe('Cocos')
    expect(cuentaDe('Cocos · USD', BROKERS)).toBe('Cocos')
  })
  it('sin pata en dólares todavía → el padre (el backend la crea)', () => {
    expect(pataDeLaMoneda(BROKERS, 'IOL', 'USD')).toBe('IOL')
  })
  it('un broker del exterior no se toca', () => {
    expect(pataDeLaMoneda(BROKERS, 'IBKR', 'ARS')).toBe('IBKR')
  })
})

describe('formulario del depósito / retiro', () => {
  const POS = [
    { broker: 'Cocos', is_cash: 1, invested: 120000 },
    { broker: 'Cocos · USD', is_cash: 1, invested: 150 },
  ]
  const f = (brokerName, moneda) => formularioDeCaja({
    brokers: BROKERS, positions: POS, brokerName, moneda, direction: 'withdraw', date: '2026-10-20' })

  it('dólares en Cocos: la caja de dólares, con su saldo', () => {
    const r = f('Cocos', 'USD')
    expect(r).toMatchObject({ broker: 'Cocos · USD', cuenta: 'Cocos', moneda: 'USD', currency: 'USD', available: 150 })
  })
  it('pesos en Cocos: la caja de pesos', () => {
    expect(f('Cocos', 'ARS')).toMatchObject({ broker: 'Cocos', moneda: 'ARS', currency: 'ARS', available: 120000 })
  })
  it('dólares en una cuenta sin pata: saldo 0, NO el de pesos', () => {
    const r = formularioDeCaja({ brokers: BROKERS, positions: [{ broker: 'IOL', is_cash: 1, invested: 50000 }],
      brokerName: 'IOL', moneda: 'USD', direction: 'withdraw', date: '2026-10-20' })
    expect(r).toMatchObject({ broker: 'IOL', moneda: 'USD', currency: 'USD', available: 0 })
  })
  it('broker del exterior: sin moneda que mandar, como siempre', () => {
    const r = formularioDeCaja({ brokers: BROKERS, positions: [], brokerName: 'IBKR', moneda: 'USD',
      direction: 'deposit', date: '2026-10-20' })
    expect(r).toMatchObject({ broker: 'IBKR', moneda: null, currency: 'USDT' })
  })
})

describe('auditoría 20/10', () => {
  it('la cuenta se arma por parent_broker_id, como broker_pair del servidor', () => {
    const raro = [B(1, 'Cocos'), B(5, 'Cocos bis', 'ARS', 1)]   // hijo en pesos
    expect(cuentaDe('Cocos bis', raro)).toBe('Cocos')
  })
  it('desde la caja de una pata en dólares, el depósito va a ESA pata', () => {
    const dos = [...BROKERS, B(6, 'Cocos · USD 2', 'USDT', 1)]
    expect(pataDeLaMoneda(dos, 'Cocos · USD 2', 'USD')).toBe('Cocos · USD 2')
    expect(pataDeLaMoneda(dos, 'Cocos', 'USD')).toBe('Cocos · USD')
  })
})
