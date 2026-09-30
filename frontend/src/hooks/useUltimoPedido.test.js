import { describe, it, expect } from 'vitest'
import { crearUltimoPedido } from './useUltimoPedido'

// El refresco periódico de movers, watchlist y noticias: una respuesta vieja
// que llega tarde no puede pisar a una más nueva.

describe('crearUltimoPedido — el último pedido gana', () => {
  it('el pedido viejo deja de estar vigente cuando sale uno nuevo', () => {
    const p = crearUltimoPedido()
    const primero = p.nuevoPedido()
    expect(primero()).toBe(true)
    const segundo = p.nuevoPedido()
    expect(primero()).toBe(false)      // la respuesta lenta se descarta
    expect(segundo()).toBe(true)
  })
  it('desmontado, ninguno está vigente; al volver a montar, el último sí', () => {
    const p = crearUltimoPedido()
    const v = p.nuevoPedido()
    p.desmontar()
    expect(v()).toBe(false)
    p.montar()                           // React en modo estricto monta dos veces
    expect(v()).toBe(true)
  })
  it('nuevoPedido es la misma función siempre (sirve de dependencia estable)', () => {
    const p = crearUltimoPedido()
    const f = p.nuevoPedido
    expect(p.nuevoPedido).toBe(f)
  })
})
