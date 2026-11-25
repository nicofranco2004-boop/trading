import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo, clic, texto } from '../../testing/navegadorMinimo'

// El globo de Mervall-E en la bienvenida: escribe solo, se completa con un
// toque, aparece entero con «reducir movimiento», y el lector de pantalla
// recibe la frase entera (lo que se va escribiendo no se lee).

let Globo, escritoHasta, esperaDespuesDe
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: Globo, escritoHasta, esperaDespuesDe } = await import('./GloboDeMervallE'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  delete window.matchMedia
  vi.useRealTimers()
})

// Las capas del globo, por atributo: la que se lee (aria-live) y la escrita.
function nodos(pred) {
  const out = []
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.atributos && pred(n)) out.push(n)
    pila.push(...(n.childNodes || []))
  }
  return out
}
// El reloj simulado de a pasitos: cada letra programa la siguiente recién
// cuando React dibujó la anterior (como en el navegador).
async function avanzar(ms) {
  for (let t = 0; t < ms; t += 20) await enActo(async () => { vi.advanceTimersByTime(20) })
}
const loQueSeLee = () => texto(nodos(n => n.atributos['aria-live'] === 'polite')[0])
// La capa escrita es la segunda columna de la grilla (la primera es el texto
// entero, invisible, que le da el tamaño).
const loEscrito = () => {
  const capas = nodos(n => /\brow-start-1\b/.test(n.atributos.class || n.atributos.className || ''))
  return texto(capas[capas.length - 1])
}

describe('las piezas puras', () => {
  it('reparte lo escrito entre los párrafos', () => {
    expect(escritoHasta(['Hola.', 'Soy yo.'], 3)).toEqual(['Hol', ''])
    expect(escritoHasta(['Hola.', 'Soy yo.'], 7)).toEqual(['Hola.', 'So'])
    expect(escritoHasta(['Hola.', 'Soy yo.'], 99)).toEqual(['Hola.', 'Soy yo.'])
  })
  it('respira más después de un punto que después de una letra', () => {
    expect(esperaDespuesDe('.')).toBeGreaterThan(esperaDespuesDe('a'))
    expect(esperaDespuesDe(',')).toBeGreaterThan(esperaDespuesDe('a'))
  })
  it('el saludo entero se escribe en menos de 5 s (antes tardaba ~7 y la persona esperaba parada)', () => {
    // ~15–18 ms por letra y pausas cortas entre frases.
    expect(esperaDespuesDe('a')).toBeGreaterThanOrEqual(15)
    expect(esperaDespuesDe('a')).toBeLessThanOrEqual(18)
    const saludo = '¡Hola, Ana! Soy Mervall-E, y te voy a ayudar a armar tu Rendi.'
      + 'Arrancás con 10 días de Rendi Pro y después 10 de Plus, gratis y sin tarjeta.'
      + 'Para mostrarte tu plata necesito tu historial. Son un par de minutos.'
    const total = [...saludo].reduce((ms, c) => ms + esperaDespuesDe(c), 0)
    expect(total).toBeLessThan(5000)
  })
})

describe('el globo', () => {
  it('escribe de a una letra; el lector de pantalla recibe la frase entera de una vez', async () => {
    vi.useFakeTimers()
    const termino = vi.fn()
    montado = await montar(h(Globo, { texto: ['Hola, Ana.', 'Soy Mervall-E.'], onTermino: termino }))
    await enActo(async () => { vi.advanceTimersByTime(0) })
    expect(loQueSeLee()).toBe('Hola, Ana. Soy Mervall-E.')
    expect(loEscrito().length).toBeLessThan(5)
    await avanzar(400)
    const aMitad = loEscrito()
    expect(aMitad.length).toBeGreaterThan(3)
    expect('Hola, Ana.Soy Mervall-E.'.startsWith(aMitad)).toBe(true)
    expect(termino).not.toHaveBeenCalled()
    await avanzar(3000)
    expect(loEscrito()).toBe('Hola, Ana.Soy Mervall-E.')
    expect(termino).toHaveBeenCalledTimes(1)
  })

  it('tocarlo lo completa al instante (y avisa que terminó, una vez)', async () => {
    vi.useFakeTimers()
    const termino = vi.fn()
    montado = await montar(h(Globo, { texto: 'Una frase bastante larga para que no termine sola.', onTermino: termino }))
    await avanzar(60)
    const globo = nodos(n => /\bbv-globo\b/.test(n.atributos.class || n.atributos.className || ''))[0]
    await enActo(async () => clic(montado.contenedor, globo))
    expect(loEscrito()).toBe('Una frase bastante larga para que no termine sola.')
    expect(termino).toHaveBeenCalledTimes(1)
    await avanzar(500)
    expect(termino).toHaveBeenCalledTimes(1)
  })

  it('con «reducir movimiento» aparece entero desde el principio', async () => {
    window.matchMedia = (q) => ({ matches: /reduce/.test(q), addEventListener() {}, removeEventListener() {} })
    const termino = vi.fn()
    montado = await montar(h(Globo, { texto: 'Hola, Ana.', onTermino: termino }))
    expect(loEscrito()).toBe('Hola, Ana.')
    expect(termino).toHaveBeenCalledTimes(1)
  })
})
