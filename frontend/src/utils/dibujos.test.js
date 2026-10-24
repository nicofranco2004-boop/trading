// Los dibujos a mano del gráfico (utils/dibujos.js): dónde se guardan, cómo un
// punto queda en su día y qué línea se tocó.
import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'
import {
  DIBUJOS_MAXIMOS, copiaLocal, diaDelPunto, dibujoTocado, dibujoValido, dibujosGuardados, distanciaASegmento, guardarDibujos,
  marcarSubidos, puntoDelDia,
} from './dibujos'

beforeAll(() => { instalarNavegadorMinimo() })
afterEach(() => { localStorage.clear() })

const dias = ['2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23'].map(d => ({ d }))
const horizontal = { id: 'h1', tipo: 'horizontal', precio: 210.5 }
const tendencia = { id: 't1', tipo: 'tendencia', a: { d: '2026-10-19', mas: 0, precio: 200 }, b: { d: '2026-10-23', mas: 7, precio: 230 } }

describe('dónde se guardan', () => {
  it('por activo y por moneda: los de AAPL en dólares no aparecen en pesos ni en otro activo', () => {
    guardarDibujos('aapl', 'usd', [horizontal, tendencia])
    expect(dibujosGuardados('AAPL', 'usd')).toEqual([horizontal, tendencia])
    expect(dibujosGuardados('AAPL', 'ars')).toEqual([])
    expect(dibujosGuardados('GGAL', 'usd')).toEqual([])
    // Sin ninguno y ya en la cuenta, la clave se borra (no queda un [] guardado).
    guardarDibujos('AAPL', 'usd', [], false)
    expect(localStorage.getItem('rendi_dibujos:AAPL:usd')).toBeNull()
  })

  it('un valor roto o de otra versión no rompe nada: se ignora lo que no se puede dibujar', () => {
    localStorage.setItem('rendi_dibujos:AAPL:usd', '{roto')
    expect(dibujosGuardados('AAPL', 'usd')).toEqual([])
    localStorage.setItem('rendi_dibujos:AAPL:usd', JSON.stringify([horizontal, { id: 'x', tipo: 'flecha' },
      { id: 'y', tipo: 'horizontal', precio: -3 }, { ...tendencia, id: 'z', b: { d: 'ayer', mas: 0, precio: 1 } }, null]))
    expect(dibujosGuardados('AAPL', 'usd')).toEqual([horizontal])
    expect(dibujoValido(tendencia)).toBe(true)
  })

  it('con el almacenamiento bloqueado, ni guardar ni leer revientan', () => {
    const roto = () => { throw new Error('SecurityError') }
    const real = globalThis.localStorage
    vi.stubGlobal('localStorage', { getItem: roto, setItem: roto, removeItem: roto })
    try {
      expect(() => guardarDibujos('AAPL', 'usd', [horizontal])).not.toThrow()
      expect(dibujosGuardados('AAPL', 'usd')).toEqual([])
    } finally {
      vi.stubGlobal('localStorage', real)
    }
  })

  it('tope de dibujos por activo', () => {
    const muchos = Array.from({ length: DIBUJOS_MAXIMOS + 5 }, (_, k) => ({ ...horizontal, id: `h${k}` }))
    guardarDibujos('AAPL', 'usd', muchos)
    expect(dibujosGuardados('AAPL', 'usd')).toHaveLength(DIBUJOS_MAXIMOS)
  })
})

describe('la copia del navegador y la cuenta', () => {
  it('un cambio sin subir queda pendiente; subido, deja de estarlo', () => {
    guardarDibujos('AAPL', 'usd', [horizontal])
    expect(copiaLocal('AAPL', 'usd')).toEqual({ dibujos: [horizontal], pendiente: true })
    marcarSubidos('AAPL', 'usd', [horizontal])
    expect(copiaLocal('AAPL', 'usd')).toEqual({ dibujos: [horizontal], pendiente: false })
  })

  it('borrar todo sin poder subirlo también queda pendiente (si no, la cuenta los traería de vuelta)', () => {
    guardarDibujos('AAPL', 'usd', [])
    expect(copiaLocal('AAPL', 'usd')).toEqual({ dibujos: [], pendiente: true })
  })

  it('si mientras subía se dibujó otra cosa, la copia sigue pendiente', () => {
    guardarDibujos('AAPL', 'usd', [horizontal])
    guardarDibujos('AAPL', 'usd', [horizontal, tendencia])     // el segundo cambio, antes de que vuelva el primero
    marcarSubidos('AAPL', 'usd', [horizontal])                  // volvió el primero
    expect(copiaLocal('AAPL', 'usd').pendiente).toBe(true)
  })

  it('la copia de antes del guardado en la cuenta (la lista sola) cuenta como pendiente: se sube', () => {
    localStorage.setItem('rendi_dibujos:AAPL:usd', JSON.stringify([horizontal]))
    expect(copiaLocal('AAPL', 'usd')).toEqual({ dibujos: [horizontal], pendiente: true })
  })
})

describe('un punto queda en su día', () => {
  it('un día que hay: su fecha; hacia adelante: días de mercado después del último', () => {
    expect(puntoDelDia(dias, 2, 205)).toEqual({ d: '2026-10-21', mas: 0, precio: 205 })
    // El precio del toque, redondeado (sin los 15 decimales del píxel).
    expect(puntoDelDia(dias, 2, 205.123456789).precio).toBe(205.1235)
    expect(puntoDelDia(dias, 2, 0.0000123456789).precio).toBe(0.0000123457)
    expect(puntoDelDia(dias, 9, 240)).toEqual({ d: '2026-10-23', mas: 5, precio: 240 })
    expect(diaDelPunto(dias, { d: '2026-10-21', mas: 0 })).toBe(2)
    expect(diaDelPunto(dias, { d: '2026-10-23', mas: 5 })).toBe(9)
  })

  it('cuando llegan días nuevos, el punto que era «hacia adelante» sigue en el mismo día', () => {
    const p = puntoDelDia(dias, 6, 240)                      // 2 días de mercado después del 23/10
    const despues = [...dias, { d: '2026-10-26' }, { d: '2026-10-27' }]
    expect(diaDelPunto(despues, p)).toBe(6)                  // = el 27/10, que ahora ya existe
    expect(despues[diaDelPunto(despues, p)].d).toBe('2026-10-27')
  })

  it('una fecha que no está (un feriado) va al día de antes; una anterior al gráfico queda afuera', () => {
    expect(diaDelPunto(dias, { d: '2026-10-25', mas: 0 })).toBe(4)
    expect(diaDelPunto(dias, { d: '2020-01-01', mas: 0 })).toBe(-1)
  })
})

describe('qué línea se tocó', () => {
  it('la distancia a un segmento, también más allá de sus puntas', () => {
    expect(distanciaASegmento(5, 3, 0, 0, 10, 0)).toBe(3)
    expect(distanciaASegmento(14, 3, 0, 0, 10, 0)).toBe(5)       // pasado la punta: a la punta
    expect(distanciaASegmento(1, 1, 2, 2, 2, 2)).toBeCloseTo(Math.SQRT2)
  })

  it('la más cercana dentro del margen; lejos de todas, ninguna', () => {
    const trazos = [{ id: 'a', ax: 0, ay: 50, bx: 100, by: 50 }, { id: 'b', ax: 0, ay: 56, bx: 100, by: 56 }]
    expect(dibujoTocado(trazos, 40, 54)).toBe('b')
    expect(dibujoTocado(trazos, 40, 52)).toBe('a')
    expect(dibujoTocado(trazos, 40, 80)).toBeNull()
    expect(dibujoTocado(trazos, 40, 70, 16)).toBe('b')           // con el dedo, más margen
  })
})
