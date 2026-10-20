import { describe, it, expect } from 'vitest'
import { elegirLugar } from './lugarDelBoton'

// Casos medidos en el demo el 2026-10-20 (tarjetas de 560 px de ancho, ✦ de 28×28).
const BOTON = { w: 28, h: 28 }
const tocan = (ancho, l, o) => {
  const c = { left: ancho - l.right - BOTON.w, right: ancho - l.right, top: l.top, bottom: l.top + BOTON.h }
  return Math.min(c.right, o.right) - Math.max(c.left, o.left) > 0 && Math.min(c.bottom, o.bottom) - Math.max(c.top, o.top) > 0
}

describe('elegirLugar — el ✦ no tapa nada de la tarjeta', () => {
  it('esquina libre: queda donde siempre estuvo (arriba a la derecha, 8 px)', () => {
    const titulo = { left: 16, right: 140, top: 16, bottom: 34 }
    expect(elegirLugar(560, BOTON, [titulo])).toEqual({ top: 8, right: 8 })
  })

  it('etiqueta «Media» en la esquina (Comportamiento): se corre a su izquierda', () => {
    const titulo = { left: 16, right: 150, top: 18, bottom: 34 }
    const etiqueta = { left: 474, right: 544, top: 16, bottom: 38 }
    const l = elegirLugar(560, BOTON, [titulo, etiqueta])
    expect(l.top).toBe(8)
    expect(tocan(560, l, etiqueta)).toBe(false)
    expect(tocan(560, l, titulo)).toBe(false)
    expect(560 - l.right).toBeLessThanOrEqual(etiqueta.left) // queda pegado a la izquierda de la etiqueta
  })

  it('varios botones seguidos (1D 1S 1M … MAX): los saltea todos', () => {
    const botones = [380, 412, 444, 476, 508].map(x => ({ left: x, right: x + 28, top: 12, bottom: 36 }))
    const l = elegirLugar(560, BOTON, botones)
    for (const b of botones) expect(tocan(560, l, b)).toBe(false)
    expect(l.top).toBe(8)
  })

  it('franja llena de punta a punta: se monta sobre el borde de arriba', () => {
    const lleno = { left: 0, right: 560, top: 10, bottom: 30 }
    const l = elegirLugar(560, BOTON, [lleno])
    expect(l.top).toBeLessThan(0)
    expect(tocan(560, l, lleno)).toBe(false) // arranca a 10 px: sube lo que haga falta (-20)
  })

  it('franja llena pero con aire arriba: mitad adentro, mitad afuera', () => {
    const lleno = { left: 0, right: 560, top: 20, bottom: 40 }
    expect(elegirLugar(560, BOTON, [lleno]).top).toBe(-14)
  })

  it('lo que está debajo de la franja no lo corre', () => {
    const abajo = { left: 500, right: 552, top: 60, bottom: 80 }
    expect(elegirLugar(560, BOTON, [abajo])).toEqual({ top: 8, right: 8 })
  })

  it('celular: si la pastilla «✦ Analizar» no entra, se achica al ✦ solo en vez de salirse', () => {
    // «Frecuencia de trades» + «Saludable» en 326 px: queda un hueco de ~40 px, no de 80.
    const rotulo = { left: 16, right: 196, top: 16, bottom: 32 }
    const etiqueta = { left: 244, right: 310, top: 12, bottom: 36 }
    const l = elegirLugar(326, { w: 80, h: 32 }, [rotulo, etiqueta], { w: 32, h: 32 })
    expect(l.compacto).toBe(true)
    expect(l.top).toBe(8)
  })
})
