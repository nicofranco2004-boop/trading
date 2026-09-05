import { describe, it, expect } from 'vitest'
import { groupBrokersIntoAccounts, accountForBrokerName, flattenAccounts, brokerLegLabel } from './brokerAccounts'

const B = (id, name, currency = 'ARS', parent_broker_id = null) =>
  ({ id, name, currency, parent_broker_id })

describe('groupBrokersIntoAccounts', () => {
  it('un broker sin hijos es una cuenta de una sola pata', () => {
    const [a, ...resto] = groupBrokersIntoAccounts([B(1, 'Schwab', 'USD')])
    expect(resto).toHaveLength(0)
    expect(a.label).toBe('Schwab')
    expect(a.isPair).toBe(false)
    expect([...a.patasNames]).toEqual(['Schwab'])
  })

  it('padre + sub-broker · USD son UNA cuenta con dos patas', () => {
    const accounts = groupBrokersIntoAccounts([
      B(1, 'Cocos', 'ARS'),
      B(2, 'Cocos · USD', 'USDT', 1),
    ])
    expect(accounts).toHaveLength(1)
    expect(accounts[0].label).toBe('Cocos')
    expect(accounts[0].isPair).toBe(true)
    expect(accounts[0].patas.map(p => p.name)).toEqual(['Cocos', 'Cocos · USD'])
  })

  it('el label es el del padre — el sufijo de la pata no se filtra a la cuenta', () => {
    // Tres lugares de la app unen nombres de broker con ' · ', el MISMO carácter
    // que separa el sibling. Si el label saliera de una pata, se leería
    // "Cocos · Cocos · USD".
    const [a] = groupBrokersIntoAccounts([
      B(1, 'Cocos', 'ARS'),
      B(2, 'Cocos · USD', 'USDT', 1),
    ])
    expect(a.label).toBe('Cocos')
    expect(a.label).not.toContain('·')
  })

  it('agrupa por parent_broker_id y NO por el sufijo del nombre', () => {
    // El caso que rompe un parseo por nombre: un sibling renombrado sigue
    // siendo hijo, y un broker que TERMINA en '· USD' sin FK no lo es.
    const accounts = groupBrokersIntoAccounts([
      B(1, 'Cocos', 'ARS'),
      B(2, 'Cocos dolares', 'USDT', 1),   // hijo real, sin el sufijo
      B(3, 'Otro · USD', 'USD'),          // parece hijo, no lo es
    ])
    expect(accounts).toHaveLength(2)
    expect(accounts[0].patas.map(p => p.name)).toEqual(['Cocos', 'Cocos dolares'])
    expect(accounts[1].label).toBe('Otro · USD')
    expect(accounts[1].isPair).toBe(false)
  })

  it('soporta N patas: un padre puede tener más de un hijo', () => {
    const [a] = groupBrokersIntoAccounts([
      B(1, 'IOL', 'ARS'),
      B(2, 'IOL · USD', 'USDT', 1),
      B(3, 'IOL · EUR', 'EUR', 1),
    ])
    expect(a.patas).toHaveLength(3)
    expect(a.patasNames.size).toBe(3)
  })

  it('el huérfano (padre borrado) sale como cuenta propia, al final', () => {
    const accounts = groupBrokersIntoAccounts([
      B(2, 'Cocos · USD', 'USDT', 99),   // padre 99 no existe
      B(1, 'Balanz', 'ARS'),
    ])
    expect(accounts.map(a => a.label)).toEqual(['Balanz', 'Cocos · USD'])
    const huerfano = accounts.find(a => a.label === 'Cocos · USD')
    expect(huerfano.isOrphan).toBe(true)
    expect(huerfano.isPair).toBe(false)
  })

  it('conserva el orden en que vienen los padres', () => {
    const accounts = groupBrokersIntoAccounts([
      B(1, 'Zeta', 'ARS'), B(2, 'Alfa', 'ARS'), B(3, 'Zeta · USD', 'USDT', 1),
    ])
    expect(accounts.map(a => a.label)).toEqual(['Zeta', 'Alfa'])
  })

  it('tolera lista vacía, null y undefined', () => {
    expect(groupBrokersIntoAccounts([])).toEqual([])
    expect(groupBrokersIntoAccounts(null)).toEqual([])
    expect(groupBrokersIntoAccounts(undefined)).toEqual([])
  })

  it('cada pata conserva su fila real — la cuenta no la reemplaza', () => {
    // Es lo que mantiene las filas editables: p.broker sigue siendo un nombre
    // unívoco, y el contrato de precio del sufijo sigue intacto.
    const [a] = groupBrokersIntoAccounts([
      B(1, 'Cocos', 'ARS'),
      B(2, 'Cocos · USD', 'USDT', 1),
    ])
    const sub = a.patas.find(p => p.id === 2)
    expect(sub.name).toBe('Cocos · USD')
    expect(sub.currency).toBe('USDT')
    expect(sub.parent_broker_id).toBe(1)
  })

  it('parent apunta al padre, que es a quien hay que renombrar/eliminar', () => {
    const [a] = groupBrokersIntoAccounts([
      B(1, 'Cocos', 'ARS'),
      B(2, 'Cocos · USD', 'USDT', 1),
    ])
    expect(a.parent.id).toBe(1)
    expect(a.key).toBe('1')
  })
})

describe('accountForBrokerName', () => {
  const accounts = groupBrokersIntoAccounts([
    B(1, 'Cocos', 'ARS'), B(2, 'Cocos · USD', 'USDT', 1), B(3, 'Binance', 'USD'),
  ])

  it('encuentra la cuenta desde el nombre de CUALQUIER pata', () => {
    expect(accountForBrokerName(accounts, 'Cocos').key).toBe('1')
    expect(accountForBrokerName(accounts, 'Cocos · USD').key).toBe('1')
    expect(accountForBrokerName(accounts, 'Binance').key).toBe('3')
  })

  it('devuelve undefined para un broker que ya no existe', () => {
    expect(accountForBrokerName(accounts, 'Borrado')).toBeUndefined()
  })
})

describe('flattenAccounts', () => {
  it('reproduce la forma plana que consumía el render viejo', () => {
    const accounts = groupBrokersIntoAccounts([
      B(1, 'Cocos', 'ARS'), B(2, 'Cocos · USD', 'USDT', 1), B(3, 'Binance', 'USD'),
    ])
    expect(flattenAccounts(accounts)).toEqual([
      { broker: expect.objectContaining({ name: 'Cocos' }), indent: false, parentName: null },
      { broker: expect.objectContaining({ name: 'Cocos · USD' }), indent: true, parentName: 'Cocos' },
      { broker: expect.objectContaining({ name: 'Binance' }), indent: false, parentName: null },
    ])
  })

  it('el huérfano sale sin indentar, como standalone', () => {
    const accounts = groupBrokersIntoAccounts([B(2, 'Suelto · USD', 'USDT', 99)])
    const flat = flattenAccounts(accounts)
    expect(flat).toHaveLength(1)
    expect(flat[0].indent).toBe(false)
    expect(flat[0].parentName).toBeNull()
  })
})

describe('brokerLegLabel', () => {
  const conPar = [
    B(1, 'Cocos', 'ARS'), B(2, 'Cocos · USD', 'USDT', 1), B(3, 'Binance', 'USD'),
  ]

  it('el padre de un par se muestra con su moneda, para que sea simétrico', () => {
    // Antes la lista decía "Cocos" y "Cocos · USD": el de dólares declaraba su
    // moneda y el de pesos había que deducirlo.
    expect(brokerLegLabel('Cocos', conPar)).toBe('Cocos · ARS')
    expect(brokerLegLabel('Cocos · USD', conPar)).toBe('Cocos · USD')
  })

  it('un broker sin hermanas NO gana sufijo', () => {
    expect(brokerLegLabel('Binance', conPar)).toBe('Binance')
    expect(brokerLegLabel('Schwab', [B(9, 'Schwab', 'USD')])).toBe('Schwab')
  })

  it('no repite la moneda si el nombre ya la trae', () => {
    // Un padre llamado "Cocos · USD" con un hijo — raro, pero no debe rendir
    // "Cocos · USD · USD".
    const raro = [B(1, 'Cocos · USD', 'USDT'), B(2, 'Cocos · USD · EUR', 'EUR', 1)]
    expect(brokerLegLabel('Cocos · USD', raro)).toBe('Cocos · USD')
  })

  it('un broker que no está en la lista se devuelve tal cual', () => {
    expect(brokerLegLabel('Borrado', conPar)).toBe('Borrado')
    expect(brokerLegLabel('Cocos', null)).toBe('Cocos')
  })

  it('USDT se muestra como USD (el usuario no tiene "USDT", tiene dólares)', () => {
    const p = [B(1, 'IOL', 'ARS'), B(2, 'IOL algo', 'USDT', 1)]
    expect(brokerLegLabel('IOL', p)).toBe('IOL · ARS')
  })
})
