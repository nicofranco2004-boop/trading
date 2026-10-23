// El botón «Ondas de Elliott» de la lectura técnica, montado de verdad
// (testing/navegadorMinimo.js) con /api/tecnico simulado en la frontera:
//   · apagado de entrada: ni etiquetas ni tarjeta;
//   · al prenderlo: las etiquetas 1 a 5 sobre los puntos, la raya que invalida
//     y la tarjeta en castellano (qué es, dónde estaría hoy, qué lo invalida,
//     la confianza, otra lectura y la aclaración);
//   · convive con el Fibonacci: los dos prendidos a la vez;
//   · sin conteo claro: lo dice y no dibuja nada.
// Y las palabras de cada estado (utils/elliott.js).
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscarBoton, clic } from '../../testing/navegadorMinimo'
import { tarjetaElliott, dondeHoy, veredictoElliott, textoInvalida } from '../../utils/elliott'

const puntos = Array.from({ length: 252 }, (_, i) => {
  const d = new Date(Date.UTC(2025, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = 100 + 30 * Math.sin(i / 20)
  return { d, o: c, h: c * 1.01, l: c * 0.99, c, s50: null, s200: null, rsi: 50 }
})
const onda = (o, i, precio, tipo) => ({ onda: o, fecha: puntos[i].d, precio, tipo })
const PRINCIPAL = {
  tipo: 'impulso', dir: 'suba', ahora: 'onda_5', confianza: 'alta',
  ondas: [onda('0', 120, 100, 'pozo'), onda('1', 140, 120, 'pico'), onda('2', 150, 108, 'pozo'),
    onda('3', 180, 140, 'pico'), onda('4', 200, 128, 'pozo')],
  invalida: { precio: 120, lado: 'debajo', por: 'final_1' },
  pautas: [{ id: 'onda2', valor: 0.6, cumple: true }, { id: 'onda3', valor: 1.6, cumple: true },
    { id: 'onda4', valor: 0.375, cumple: true }, { id: 'alternancia', valor: null, cumple: false }],
}
const ALTERNATIVO = { ...PRINCIPAL, ahora: 'onda_4', confianza: 'media', ondas: PRINCIPAL.ondas.slice(0, 4) }
const ELL = { disponible: true, n_pivote: 3, principal: PRINCIPAL, alternativo: ALTERNATIVO }
const FIB = { disponible: false, motivo: 'tramos_chicos', n_pivote: 3, ruedas: 252, en_curso: null }
const DATOS = (elliott) => ({
  disponible: true, moneda: 'usd', ticker: 'ZZEL', convertida: null, puntos, fibonacci: FIB, elliott,
  lectura: { ruedas: 252, fecha: puntos[251].d, precio: puntos[251].c, rsi: 50 },
})

let respuesta
vi.mock('../../utils/api', () => ({
  api: { get: vi.fn(() => Promise.resolve(respuesta)) },
}))

let LecturaTecnica
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
})

const el = () => h(LecturaTecnica, { asset: 'ZZEL' })
async function dibujar() {
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}
async function tocar(nombre) {
  await clic(montado.contenedor, buscarBoton(montado.contenedor, nombre))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('Ondas de Elliott en la ficha', () => {
  it('apagado de entrada; al prenderlo, etiquetas, raya y tarjeta', async () => {
    respuesta = DATOS(ELL)
    const antes = await dibujar()
    expect(antes).toContain('Ondas de Elliott')        // el botón
    expect(antes).not.toContain('Un conteo posible')
    expect(antes).not.toContain('Invalida el conteo')
    const t = await tocar('Ondas de Elliott')
    expect(t).toContain('Un conteo posible: onda 5')
    expect(t).toContain('La teoría de Elliott dice que el precio suele avanzar en 5 ondas')
    expect(t).toContain('Un conteo posible dice que estaría en la onda 5, la última de la suba.')
    expect(t).toContain('se invalida si el precio baja de US$ 120,00 (donde terminó la onda 1)')
    expect(t).toContain('Confianza alta: cumple 3 de 4 proporciones que suelen darse.')
    expect(t).toContain('La onda 2 devolvió el 60 % de la 1')
    expect(t).toContain('Otra lectura posible: estaría en la onda 4')
    expect(t).toContain('Es una de varias lecturas posibles')
    expect(t).toContain('no es una recomendación')
    expect(t).toContain('Invalida el conteo · US$ 120,00')
    for (const n of ['1', '2', '3', '4']) expect(t).toContain(n)
    // Apagarlo lo saca.
    const despues = await tocar('Ondas de Elliott')
    expect(despues).not.toContain('Un conteo posible')
  })

  it('convive con el Fibonacci: los dos prendidos', async () => {
    respuesta = DATOS(ELL)
    await dibujar()
    await tocar('Ondas de Elliott')
    const t = await tocar('Fibonacci')
    expect(t).toContain('Un conteo posible: onda 5')
    expect(t).toContain('Sin tramo claro')               // la tarjeta del Fibonacci
  })

  it('sin conteo claro: lo dice y no dibuja nada', async () => {
    respuesta = DATOS({ disponible: false, motivo: 'sin_conteo', n_pivote: 3, ruedas: 252 })
    await dibujar()
    const t = await tocar('Ondas de Elliott')
    expect(t).toContain('Sin conteo claro')
    expect(t).toContain('no se fuerza uno')
    expect(t).not.toContain('Invalida el conteo')
  })

  it('una respuesta vieja sin el campo no muestra el botón', async () => {
    respuesta = DATOS(undefined)
    const t = await dibujar()
    expect(t).not.toContain('Ondas de Elliott')
  })
})

describe('las palabras de cada estado', () => {
  const fecha = (d) => d
  const precio = (x) => `$ ${x}`
  const con = (extra) => ({ ...PRINCIPAL, ...extra })

  it('dónde estaría hoy', () => {
    expect(dondeHoy(con({ ahora: 'onda_3' }), fecha)).toBe('estaría en la onda 3 de la suba, la que suele ser la más larga y fuerte')
    expect(dondeHoy(con({ ahora: 'onda_3', dir: 'bajada' }), fecha)).toContain('onda 3 de la bajada')
    const cinco = con({ ahora: 'correccion', ondas: [...PRINCIPAL.ondas, onda('5', 220, 150, 'pico')] })
    expect(dondeHoy(cinco, fecha)).toBe(`las 5 ondas de la suba habrían terminado el ${puntos[220].d} y estaría en la corrección que suele venir después`)
    const abc = { tipo: 'correccion', dir: 'bajada', ahora: 'fin_abc', ondas: [onda('0', 1, 120), onda('A', 2, 100), onda('B', 3, 110), onda('C', 4, 90)] }
    expect(dondeHoy(abc, fecha)).toBe(`la corrección a la baja, después de una suba (A, B y C) habría terminado el ${puntos[4].d}`)
    expect(dondeHoy({ ...abc, ahora: 'onda_C' }, fecha)).toBe('estaría en la onda C de la corrección a la baja, después de una suba, su último tramo')
    expect(veredictoElliott(abc)).toBe('Un conteo posible: terminó una corrección A-B-C')
    expect(veredictoElliott(null)).toBe('Sin conteo claro')
  })

  it('qué lo invalida, en los dos sentidos', () => {
    expect(textoInvalida(con({ invalida: { precio: 100, lado: 'debajo', por: 'arranque_1' } }), precio))
      .toBe('Este conteo se invalida si el precio baja de $ 100 (donde arrancó la onda 1): la onda 2 nunca va más allá de ese punto.')
    expect(textoInvalida(con({ invalida: { precio: 150, lado: 'encima', por: 'final_5' } }), precio))
      .toContain('deja de valer si el precio sube de $ 150 (el final de la onda 5)')
  })

  it('nunca recomienda ni promete', () => {
    const t = tarjetaElliott(ELL, precio, fecha)
    // Todo menos la aclaración del pie (que dice justamente «no es una recomendación de compra»).
    const todo = [t.texto, t.invalida, t.confianza, t.alternativo, ...t.pautas.map(p => p.texto)].join(' ')
    expect(todo).not.toMatch(/\b(compr[áa]|vend[ée]|va a (subir|bajar)|seguro)\b/i)
    expect(t.pie).toContain('No dice qué va a pasar')
  })
})
