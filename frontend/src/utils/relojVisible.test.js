import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { relojVisible } from './relojVisible'

// El reloj que refresca solas las secciones de mercado: la cinta, los movers y
// la watchlist. Pide cada `ms` con la pestaña a la vista y nunca oculta.

let handler
beforeEach(() => {
  vi.useFakeTimers()
  handler = null
  globalThis.document = {
    visibilityState: 'visible',
    addEventListener: vi.fn((ev, fn) => { if (ev === 'visibilitychange') handler = fn }),
    removeEventListener: vi.fn(),
  }
})
afterEach(() => {
  vi.useRealTimers()
  delete globalThis.document
})

describe('relojVisible', () => {
  it('llama cada `ms` con la pestaña a la vista', () => {
    const fn = vi.fn()
    const apagar = relojVisible(fn, 1000)
    vi.advanceTimersByTime(3000)
    expect(fn).toHaveBeenCalledTimes(3)
    apagar()
  })

  it('con la pestaña oculta no pide nada', () => {
    const fn = vi.fn()
    const apagar = relojVisible(fn, 1000)
    document.visibilityState = 'hidden'
    vi.advanceTimersByTime(5000)
    expect(fn).not.toHaveBeenCalled()
    apagar()
  })

  it('al volver, pide en el momento sólo si ya pasó el plazo', () => {
    const fn = vi.fn()
    const apagar = relojVisible(fn, 1000)
    document.visibilityState = 'hidden'
    vi.advanceTimersByTime(400)
    document.visibilityState = 'visible'
    handler()
    expect(fn).not.toHaveBeenCalled()          // 400 ms: todavía fresco
    document.visibilityState = 'hidden'
    vi.advanceTimersByTime(2000)
    document.visibilityState = 'visible'
    handler()
    expect(fn).toHaveBeenCalledTimes(1)        // pasó el plazo: pide ya
    apagar()
  })

  it('quien necesita otra cuenta al volver pasa la suya', () => {
    const fn = vi.fn()
    const alVolver = vi.fn()
    const apagar = relojVisible(fn, 1000, { alVolver })
    handler()
    expect(alVolver).toHaveBeenCalledTimes(1)
    expect(fn).not.toHaveBeenCalled()
    apagar()
  })

  it('apagado, no llama más ni escucha la pestaña', () => {
    const fn = vi.fn()
    const apagar = relojVisible(fn, 1000)
    apagar()
    vi.advanceTimersByTime(5000)
    expect(fn).not.toHaveBeenCalled()
    expect(document.removeEventListener).toHaveBeenCalledWith('visibilitychange', handler)
  })
})
