// Los dibujos a mano del gráfico (utils/dibujos.js): dónde se guardan, cómo un
// punto queda en su día y qué línea se tocó.
import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'
import { extensionFibonacci, fibonacciAMano, rayas } from './fibonacci'
import {
  DIBUJOS_MAXIMOS, ETIQUETAS_ELLIOTT, copiaLocal, diaDelPunto, diasHabilesEntre, dibujoTocado, dibujoValido, dibujosGuardados, distanciaASegmento, guardarDibujos,
  marcarSubidos, puntoDelDia, NOTA_MAXIMA, largoDeNota, limpiarNota, recortarNota,
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
    // Afuera a la izquierda, a su distancia en días hábiles (no pegada en -1:
    // así la línea no gira a medida que se borran los días viejos).
    expect(diaDelPunto(dias, { d: '2020-01-01', mas: 0 })).toBeLessThan(-1700)
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

describe('Fibonacci y Elliott a mano', () => {
  const p = (d, precio) => ({ d, mas: 0, precio })
  it('tu Fibonacci usa la misma cuenta que el automático (backend/estructura.py: hasta − r × (hasta − desde))', () => {
    const f = fibonacciAMano(100, 200)
    expect(f.dir).toBe('suba')
    expect(f.niveles.find(n => n.nivel === 0.618).precio).toBeCloseTo(138.2, 9)
    expect(rayas(f).map(r => r.precio)).toEqual([200, 176.4, 161.8, 150, 138.2, 121.4, 100].map(x => expect.closeTo(x, 9)))
    const b = fibonacciAMano(200, 100)                   // una bajada: del techo al piso
    expect(b.dir).toBe('bajada')
    expect(b.niveles.find(n => n.nivel === 0.382).precio).toBeCloseTo(138.2, 9)
  })

  it('qué se puede guardar', () => {
    const a = p('2026-10-01', 100), b = p('2026-10-20', 130)
    expect(dibujoValido({ id: 'f', tipo: 'fibonacci', a, b })).toBe(true)
    expect(dibujoValido({ id: 'f', tipo: 'fibonacci', a })).toBe(false)
    const puntos = ETIQUETAS_ELLIOTT.map((_, k) => p('2026-10-01', 100 + k))
    expect(dibujoValido({ id: 'e', tipo: 'elliott', puntos })).toBe(true)
    expect(dibujoValido({ id: 'e', tipo: 'elliott', puntos: puntos.slice(0, 2) })).toBe(true)
    expect(dibujoValido({ id: 'e', tipo: 'elliott', puntos: puntos.slice(0, 1) })).toBe(false)
    expect(dibujoValido({ id: 'e', tipo: 'elliott', puntos: [...puntos, puntos[0]] })).toBe(false)
    expect(dibujoValido({ id: 'e', tipo: 'elliott', puntos: [...puntos.slice(0, 2), { d: 'x' }] })).toBe(false)
  })
})

describe('extensión de Fibonacci y las dos formas de Elliott', () => {
  const p = (precio) => ({ d: '2026-10-01', mas: 0, precio })
  it('la extensión proyecta el movimiento desde el fin del retroceso: c + r × (b − a)', () => {
    const niveles = extensionFibonacci(100, 150, 130)       // sube 50, retrocede a 130
    expect(niveles.map(n => n.nivel)).toEqual([0, 0.618, 1, 1.618, 2, 2.618])
    expect(niveles.find(n => n.nivel === 1).precio).toBe(180)
    expect(niveles.find(n => n.nivel === 1.618).precio).toBeCloseTo(210.9, 9)
    expect(extensionFibonacci(200, 150, 170).find(n => n.nivel === 1).precio).toBe(120)   // en una bajada, hacia abajo
  })
  it('qué se puede guardar', () => {
    expect(dibujoValido({ id: 'x', tipo: 'extension', a: p(1), b: p(2), c: p(3) })).toBe(true)
    expect(dibujoValido({ id: 'x', tipo: 'extension', a: p(1), b: p(2) })).toBe(false)
    const n = (k) => Array.from({ length: k }, (_, i) => p(100 + i))
    expect(dibujoValido({ id: 'e', tipo: 'elliott', forma: 'impulso', puntos: n(6) })).toBe(true)
    expect(dibujoValido({ id: 'e', tipo: 'elliott', forma: 'impulso', puntos: n(7) })).toBe(false)
    expect(dibujoValido({ id: 'e', tipo: 'elliott', forma: 'correccion', puntos: n(4) })).toBe(true)
    expect(dibujoValido({ id: 'e', tipo: 'elliott', forma: 'correccion', puntos: n(5) })).toBe(false)
    expect(dibujoValido({ id: 'e', tipo: 'elliott', forma: 'triangulo', puntos: n(3) })).toBe(false)
    expect(dibujoValido({ id: 'e', tipo: 'elliott', puntos: n(9) })).toBe(true)          // los guardados antes de separarlos
  })
})

describe('un punto anclado antes de la historia guardada (auditoría 29/10)', () => {
  const pts = [{ d: '2026-10-05' }, { d: '2026-10-06' }, { d: '2026-10-07' }]
  it('queda a su distancia en días hábiles, no pegado en -1 (la línea no gira cuando se borran días viejos)', () => {
    expect(diaDelPunto(pts, { d: '2026-10-02', mas: 0 })).toBe(-1)          // viernes → lunes: 1 día hábil
    expect(diaDelPunto(pts, { d: '2026-09-28', mas: 0 })).toBe(-5)          // una semana antes
    expect(diaDelPunto(pts, { d: '2026-09-28', mas: 2 })).toBe(-3)
    expect(diaDelPunto(pts, { d: '2026-10-06', mas: 0 })).toBe(1)
    expect(diasHabilesEntre('2026-09-26', '2026-10-05')).toBe(5)            // de sábado a lunes de la otra semana
  })
})

describe('las notas de texto (Nico, 30/10)', () => {
  const a = { d: '2026-03-02', mas: 0, precio: 180.25 }
  it('se limpian como en el servidor (main._texto_de_nota), así la copia del navegador y la de tu cuenta son la misma', () => {
    // El mismo caso que backend/tests/test_dibujos_grafico.test_las_notas_de_texto.
    expect(limpiarNota('  a\u0000b\u0007\r\nc\td\n\n\n\n\ne  ')).toBe('ab\nc d\n\ne')
    expect(limpiarNota('subió \ud83d')).toBe('subió')          // medio emoji suelto: afuera
    expect(limpiarNota('  \n\t ')).toBe('')
    // Lo que no se ve no es una nota (sería una banderita vacía); el U+0085 y
    // la marca BOM se sacan, igual que el servidor (auditoría 30/10: el U+0085
    // la pantalla lo dejaba y el servidor no, y trababa el guardado entero).
    for (const invisible of ['\u200b', '\u200b \u2060', '\x85', '\ufeff', '\u00a0\u3000']) expect(limpiarNota(invisible)).toBe('')
    expect(limpiarNota('\x85\ufeffhola\x85')).toBe('hola')
    expect(limpiarNota('👨\u200d👩\u200d👧')).toBe('👨\u200d👩\u200d👧')    // la unión de una familia queda
  })
  it('se cuentan letras: un emoji es una, y cortar no lo parte al medio', () => {
    expect(largoDeNota('🚀a')).toBe(2)
    expect(recortarNota('🚀'.repeat(NOTA_MAXIMA + 5))).toBe('🚀'.repeat(NOTA_MAXIMA))
    // Una bandera son dos partes: si no entra entera, no queda media.
    expect(recortarNota('a'.repeat(NOTA_MAXIMA - 1) + '🇦🇷')).toBe('a'.repeat(NOTA_MAXIMA - 1))
    expect(largoDeNota('👍🏽')).toBe(2)                                     // como el servidor
  })
  it('la copia de este navegador es de quien la guardó: otra persona en la misma compu no la ve ni la sube', () => {
    const nota = { id: 'n1', tipo: 'nota', a, texto: 'mi idea' }
    localStorage.setItem('rendi_user', JSON.stringify({ email: 'A@rendi.test' }))
    guardarDibujos('AAPL', 'usd', [nota])                                  // pendiente: no llegó a la cuenta
    expect(copiaLocal('AAPL', 'usd')).toEqual({ dibujos: [nota], pendiente: true })
    localStorage.setItem('rendi_user', JSON.stringify({ email: 'b@rendi.test' }))   // la sesión venció y entró otra
    expect(copiaLocal('AAPL', 'usd')).toEqual({ dibujos: [], pendiente: false })
    localStorage.setItem('rendi_user', JSON.stringify({ email: 'a@rendi.test' }))   // vuelve la primera
    expect(copiaLocal('AAPL', 'usd').dibujos).toEqual([nota])
  })
  it('una nota es un dibujo con su punto y su texto; sin texto o de más, no', () => {
    expect(dibujoValido({ id: 'n', tipo: 'nota', a, texto: 'compré acá' })).toBe(true)
    expect(dibujoValido({ id: 'n', tipo: 'nota', a, texto: '🚀'.repeat(NOTA_MAXIMA) })).toBe(true)
    for (const malo of [{ texto: '' }, { texto: '   ' }, { texto: 'x'.repeat(NOTA_MAXIMA + 1) }, { texto: 5 }, { a: undefined }, { a: { ...a, precio: 0 } }]) {
      expect(dibujoValido({ id: 'n', tipo: 'nota', a, texto: 'ok', ...malo })).toBe(false)
    }
  })
})
