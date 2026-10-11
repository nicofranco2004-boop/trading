// El botón «Registrar»: la lista única de lo que se anota a mano y el camino
// de cada opción hasta su formulario.
//
// El "+" del celular tuvo una acción que iba a una dirección que ninguna
// pantalla leía y caía en Inicio sin abrir nada. Acá se exige, para CADA
// opción: que su dirección exista en la app, que la Cartera la reconozca, y que
// las dos Carteras (compu y celular) tengan qué hacer con ella.
import { describe, it, expect } from 'vitest'
import {
  ACCIONES_REGISTRAR, direccionDeRegistrar, accionDelPedido,
  conversionDeLaCaja, cajasParaConvertir,
} from './registrar'
import fuenteDeApp from '../App.jsx?raw'
import fuenteCompu from '../pages/Positions.jsx?raw'
import fuenteCelular from '../pages/PositionsMobile.jsx?raw'

describe('las opciones de «Registrar»', () => {
  it('son cinco, en el orden pedido: venta, compra, depósito, retiro, movimiento', () => {
    expect(ACCIONES_REGISTRAR.map(a => a.label)).toEqual(['Venta', 'Compra', 'Depósito', 'Retiro', 'Movimiento'])
  })
  it('ninguna repite su valor en la dirección', () => {
    const valores = ACCIONES_REGISTRAR.map(a => a.valor)
    expect(new Set(valores).size).toBe(valores.length)
  })
  it('la compra y la venta conservan los valores que ya usaba el "+" del celular', () => {
    expect(direccionDeRegistrar('comprar')).toBe('/posiciones?action=new')
    expect(direccionDeRegistrar('vender')).toBe('/posiciones?action=sell')
  })

  const rutasDeApp = new Set([...fuenteDeApp.matchAll(/path="([^"]+)"/g)].map(m => m[1]))
  // El cuerpo de la función que reparte el pedido en cada pantalla.
  const reparto = (fuente) => {
    const i = fuente.indexOf('function atenderPedido(')
    expect(i, 'la pantalla perdió su atenderPedido').toBeGreaterThan(0)
    return fuente.slice(i, fuente.indexOf('\n  }\n', i))
  }
  for (const a of ACCIONES_REGISTRAR) {
    describe(a.label, () => {
      const [ruta, consulta] = direccionDeRegistrar(a.id).split('?')
      it('va a una pantalla que existe', () => {
        expect(rutasDeApp).toContain(ruta)
      })
      it('la Cartera lee de la dirección la misma acción que se pidió', () => {
        expect(accionDelPedido(`?${consulta}`)).toBe(a.id)
      })
      it('la Cartera de la compu tiene qué abrir', () => {
        expect(reparto(fuenteCompu)).toContain(`'${a.id}'`)
      })
      it('la Cartera del celular tiene qué abrir', () => {
        // La compra no espera a las listas: se atiende antes del reparto.
        const fuente = a.id === 'comprar' ? fuenteCelular : reparto(fuenteCelular)
        expect(fuente).toContain(`'${a.id}'`)
      })
    })
  }

  it('una dirección sin pedido, o con uno que no existe, no abre nada', () => {
    expect(accionDelPedido('')).toBeNull()
    expect(accionDelPedido('?action=watchlist')).toBeNull()
    expect(accionDelPedido('?otra=sell')).toBeNull()
  })
  it('pedir la dirección de algo que no está en la lista falla en vez de inventarla', () => {
    expect(() => direccionDeRegistrar('regalar')).toThrow()
  })
})

describe('«Movimiento»: qué efectivo se puede convertir', () => {
  const brokers = [
    { id: 1, name: 'Cocos', currency: 'ARS', parent_broker_id: null },
    { id: 2, name: 'Cocos · USD', currency: 'USDT', parent_broker_id: 1 },
    { id: 3, name: 'Binance', currency: 'USDT', parent_broker_id: null },
  ]
  const caja = (id, broker, invested) => ({ id, broker, is_cash: 1, invested })

  it('los pesos de una cuenta argentina se pasan a dólares', () => {
    expect(conversionDeLaCaja(caja(1, 'Cocos', 500000), brokers[0])).toBe('ars_to_usd')
  })
  it('los dólares de su sub-cuenta se pasan a pesos', () => {
    expect(conversionDeLaCaja(caja(2, 'Cocos · USD', 300), brokers[1])).toBe('usd_to_ars')
  })
  it('un exchange en dólares (sin cuenta en pesos) no tiene conversión', () => {
    expect(conversionDeLaCaja(caja(3, 'Binance', 1000), brokers[2])).toBeNull()
  })
  it('una tenencia que no es efectivo, o una caja sin broker, tampoco', () => {
    expect(conversionDeLaCaja({ id: 9, broker: 'Cocos', is_cash: 0 }, brokers[0])).toBeNull()
    expect(conversionDeLaCaja(caja(1, 'Cocos', 1), undefined)).toBeNull()
  })
  it('el selector lista sólo las cajas convertibles, cada una con su dirección', () => {
    const positions = [
      caja(1, 'Cocos', 500000), caja(2, 'Cocos · USD', 300), caja(3, 'Binance', 1000),
      { id: 4, broker: 'Cocos', is_cash: 0, asset: 'GGAL' },
    ]
    expect(cajasParaConvertir(positions, brokers).map(c => [c.p.id, c.direction]))
      .toEqual([[1, 'ars_to_usd'], [2, 'usd_to_ars']])
  })
  it('sin cajas convertibles la lista queda vacía (el cartel explica por qué)', () => {
    expect(cajasParaConvertir([caja(3, 'Binance', 1000)], brokers)).toEqual([])
    expect(cajasParaConvertir(null, null)).toEqual([])
  })
})
