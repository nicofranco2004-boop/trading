import { describe, it, expect, vi } from 'vitest'
import { crearEnVuelo } from './useEnVuelo'

// La lógica del freno, sin React. Que los botones de verdad la usen (y que un
// doble click en el mismo turno mande UN pedido) lo prueba
// pages/dobleClick.test.js montando los formularios reales.

function colgado() {
  let soltar, fallar
  const promesa = new Promise((res, rej) => { soltar = res; fallar = rej })
  return { fn: vi.fn(() => promesa), soltar, fallar }
}

describe('crearEnVuelo', () => {
  it('mientras un pedido viaja, el segundo no sale', async () => {
    const f = crearEnVuelo()
    const p = colgado()
    const primero = f.correr(p.fn)
    const segundo = f.correr(p.fn)
    expect(p.fn).toHaveBeenCalledTimes(1)
    expect(f.activo()).toBe(true)
    expect(await segundo).toBeUndefined()
    p.soltar('ok')
    expect(await primero).toBe('ok')
    expect(f.activo()).toBe(false)
  })

  it('terminado el primero, se puede volver a mandar', async () => {
    const f = crearEnVuelo()
    const fn = vi.fn(async () => 1)
    await f.correr(fn)
    await f.correr(fn)
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('si el pedido falla, el freno se suelta igual y el error llega a quien lo llamó', async () => {
    const f = crearEnVuelo()
    const p = colgado()
    const corrida = f.correr(p.fn)
    p.fallar(new Error('409'))
    await expect(corrida).rejects.toThrow('409')
    expect(f.activo()).toBe(false)
    const otra = vi.fn(async () => 'de nuevo')
    expect(await f.correr(otra)).toBe('de nuevo')
  })

  it('un error SINCRÓNICO (antes del primer await) también suelta el freno', async () => {
    const f = crearEnVuelo()
    await expect(f.correr(() => { throw new Error('validación') })).rejects.toThrow('validación')
    expect(f.activo()).toBe(false)
  })

  it('con clave frena por renglón: el mismo plazo fijo no, otro sí', async () => {
    const f = crearEnVuelo()
    const a = colgado()
    const b = vi.fn(async () => 'b')
    f.correr(a.fn, 7)
    f.correr(a.fn, 7)
    expect(await f.correr(b, 8)).toBe('b')
    expect(a.fn).toHaveBeenCalledTimes(1)
    expect(f.activo(7)).toBe(true)
    expect(f.activo(8)).toBe(false)
    expect(f.activo()).toBe(false)   // sin clave es otro freno
    expect(f.alguno()).toBe(true)
    a.soltar()
    await Promise.resolve(); await Promise.resolve()
    expect(f.alguno()).toBe(false)
  })

  it('avisa al tomar y al soltar (es lo que redibuja el botón)', async () => {
    const avisar = vi.fn()
    const f = crearEnVuelo(avisar)
    await f.correr(async () => {})
    expect(avisar).toHaveBeenCalledTimes(2)
    // El click frenado no avisa: no cambió nada que dibujar.
    const p = colgado()
    f.correr(p.fn)
    avisar.mockClear()
    await f.correr(p.fn)
    expect(avisar).not.toHaveBeenCalled()
    p.soltar()
  })
})
