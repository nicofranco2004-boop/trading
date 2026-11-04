// La posición del gráfico (Nico, 03/11), como la «posición larga/corta» de
// TradingView (utils/dibujos.js): cuándo es válida, cómo sale al crearla, cómo
// se arrastra y qué pasó con las velas que hay.
import { describe, it, expect } from 'vitest'
import { cuentasDePosicion, dibujoCorrido, dibujoValido, posicionNueva, puntasDe, resultadoDePosicion } from './dibujos'

const a = { d: '2026-03-02', mas: 0, precio: 100 }
const b = { d: '2026-04-01', mas: 0, precio: 100 }
const compra = { id: 'p1', tipo: 'posicion', lado: 'compra', a, b, objetivo: 110, stop: 95 }
const venta = { ...compra, id: 'p2', lado: 'venta', objetivo: 90, stop: 105 }

describe('la posición', () => {
  it('es válida con el objetivo y el stop del lado que corresponde', () => {
    expect(dibujoValido(compra)).toBe(true)
    expect(dibujoValido(venta)).toBe(true)
    expect(dibujoValido({ ...compra, stop: 101 })).toBe(false)
    expect(dibujoValido({ ...venta, objetivo: 120 })).toBe(false)
    expect(dibujoValido({ ...compra, lado: 'larga' })).toBe(false)
    expect(dibujoValido({ ...compra, stop: undefined })).toBe(false)
  })

  it('sale con ratio 2 y el stop nunca en 0', () => {
    const p = posicionNueva('compra', a, b, 5)
    expect([p.objetivo, p.stop]).toEqual([110, 95])
    expect(cuentasDePosicion(p)).toEqual({ gana: 10, pierde: 5, ratio: 2 })
    const v = posicionNueva('venta', a, b, 5)
    expect([v.objetivo, v.stop]).toEqual([90, 105])
    expect(cuentasDePosicion(v).ratio).toBe(2)
    // Un «riesgo» enorme (el gráfico muy alejado) no deja el objetivo de venta en negativo.
    const lejos = posicionNueva('venta', a, b, 500)
    expect(dibujoValido({ id: 'x', ...lejos })).toBe(true)
  })

  it('se arrastra de cada punta y no queda al revés', () => {
    const enVista = { ...compra, a: { k: 10, precio: 100 }, b: { k: 30, precio: 100 } }
    const correr = (dk, dp) => (p) => ({ ...p, k: p.k + dk, precio: p.precio + dp })
    const precio = (dp) => (x) => x + dp
    expect(puntasDe(enVista).map(([n]) => n)).toEqual(['a', 'b', 'objetivo', 'stop'])
    expect(dibujoCorrido(enVista, 'objetivo', correr(0, 5), precio(5)).objetivo).toBe(115)
    expect(dibujoCorrido(enVista, 'stop', correr(0, -2), precio(-2)).stop).toBe(93)
    // El borde: sólo el día; su precio sigue siendo el de la entrada.
    expect(dibujoCorrido(enVista, 'b', correr(5, 3), precio(3)).b).toEqual({ k: 35, precio: 100 })
    const entera = dibujoCorrido(enVista, 'todo', correr(2, 4), precio(4))
    expect([entera.a.k, entera.a.precio, entera.objetivo, entera.stop, entera.b.k]).toEqual([12, 104, 114, 99, 32])
    // El stop arriba de la entrada o el borde antes de la entrada: no se mueve.
    expect(dibujoCorrido(enVista, 'stop', correr(0, 10), precio(10))).toBe(enVista)
    expect(dibujoCorrido(enVista, 'b', correr(-25, 0), precio(0))).toBe(enVista)
  })
})

describe('qué pasó con la posición', () => {
  const v = (h, l, c) => ({ h, l, c })
  it('llegó al objetivo, tocó el stop o sigue abierta', () => {
    expect(resultadoDePosicion(compra, [v(101, 99, 100), v(104, 98, 103), v(111, 102, 109)], 0, 10)).toEqual({ estado: 'objetivo', i: 2 })
    expect(resultadoDePosicion(compra, [v(101, 99, 100), v(102, 94, 96)], 0, 10)).toEqual({ estado: 'stop', i: 1 })
    expect(resultadoDePosicion(compra, [v(101, 99, 100), v(104, 98, 103)], 0, 10))
      .toEqual({ estado: 'abierta', i: 1, precio: 103, pct: 3, termino: false })
    expect(resultadoDePosicion(venta, [v(101, 99, 100), v(100, 89, 92)], 0, 10)).toEqual({ estado: 'objetivo', i: 1 })
  })
  it('la vela de la entrada no cuenta y, si una vela toca los dos, cuenta el stop', () => {
    expect(resultadoDePosicion(compra, [v(120, 80, 100), v(101, 99, 100)], 0, 10).estado).toBe('abierta')
    expect(resultadoDePosicion(compra, [v(101, 99, 100), v(112, 94, 100)], 0, 10)).toEqual({ estado: 'stop', i: 1 })
  })
  it('mira hasta su borde derecho y una entrada hacia adelante no pasó todavía', () => {
    const velas = [v(101, 99, 100), v(102, 99, 101), v(111, 100, 110)]
    expect(resultadoDePosicion(compra, velas, 0, 1)).toEqual({ estado: 'abierta', i: 1, precio: 101, pct: 1, termino: true })
    expect(resultadoDePosicion(compra, velas, 5, 9)).toEqual({ estado: 'adelante' })
  })
})
