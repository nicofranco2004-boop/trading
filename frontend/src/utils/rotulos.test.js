// Los rótulos de capas distintas que se pisarían con todo prendido
// (utils/rotulos.js): se esconde el de menos prioridad, nunca la capa.
import { describe, it, expect } from 'vitest'
import { PRIORIDAD, rotulosTapados, taparRotulos, rotuloCorteFib, rotuloInvalidaElliott, ANCHO_GRAFICO_CELULAR } from './rotulos'

const caja = (prioridad, x0, y0, ancho = 120, alto = 14) => ({ prioridad, x0, x1: x0 + ancho, y0, y1: y0 + alto })

describe('rotulosTapados', () => {
  it('el caso de AAPL (24/10): el corte del Fibonacci pisaba el «El conteo dejaría de valer» y la onda 4', () => {
    // Medidas tomadas del gráfico de AAPL en dólares, 1 año, todo prendido.
    const cajas = [
      caja(PRIORIDAD.corteFib, 540, 84, 200, 14),        // «Si cierra debajo, podría frenar · US$ 325»
      caja(PRIORIDAD.invalidaElliott, 448, 97, 120, 14),  // «El conteo dejaría de valer · US$ 317,40»
      caja(PRIORIDAD.onda, 650, 82, 18, 18),              // la onda 4
      caja(PRIORIDAD.onda, 515, 74, 18, 18),              // la onda 1, lejos
    ]
    // La onda 4 gana: el corte del Fibonacci se esconde; con él fuera, el de
    // Elliott ya no pisa nada y queda.
    expect([...rotulosTapados(cajas)]).toEqual([0])
  })

  it('a igual prioridad queda el primero; lo que no se toca queda siempre', () => {
    const cajas = [caja(PRIORIDAD.nivelFib, 0, 0), caja(PRIORIDAD.nivelFib, 50, 5), caja(PRIORIDAD.nivelFib, 0, 40)]
    expect([...rotulosTapados(cajas)]).toEqual([1])
  })

  it('rozarse por un píxel no es pisarse', () => {
    expect(rotulosTapados([caja(4, 0, 0, 100, 14), caja(3, 99, 13, 100, 14)]).size).toBe(0)
  })

  it('lo que no ocupa lugar (sin medir) no tapa ni se tapa', () => {
    expect(rotulosTapados([caja(6, 0, 0, 0, 0), caja(2, 0, 0)]).size).toBe(0)
  })

  it('el orden de importancia', () => {
    expect(PRIORIDAD.medicion).toBeGreaterThan(PRIORIDAD.onda)
    expect(PRIORIDAD.onda).toBeGreaterThan(PRIORIDAD.nivelFib)
    expect(PRIORIDAD.nivelFib).toBeGreaterThan(PRIORIDAD.corteFib)
    expect(PRIORIDAD.corteFib).toBeGreaterThan(PRIORIDAD.invalidaElliott)
  })
})

// Un rótulo de mentira. Uno de raya (`voltear`): su caja depende de en qué punta de su raya está
// (`left-1` / `right-1`, o lo que le puso taparRotulos) y de qué lado (abajo
// con `top-0.5`, arriba con `-translate-y-full`).
function rotulo({ prioridad, clase = '', voltear = false, izq, der, y, ancho = 120 }) {
  const atr = { 'data-rotulo': String(prioridad), class: clase, ...(voltear ? { 'data-rotulo-voltear': '' } : {}) }
  return {
    nodeType: 1, childNodes: [], style: {},
    getAttribute: (k) => (k in atr ? atr[k] : null),
    setAttribute: (k, v) => { atr[k] = String(v) },
    removeAttribute: (k) => { delete atr[k] },
    getBoundingClientRect() {
      const derecha = this.style.left === '4px' ? false : this.style.right === '4px' ? true : /right-1/.test(atr.class)
      const abajo = /top-0\.5/.test(atr.class) ? this.style.bottom !== '2px' : this.style.top === '2px'
      const x0 = derecha ? der - ancho : izq
      // Los que no son de raya (los números de las ondas) están donde están.
      const y0 = !voltear ? y : abajo ? y + 2 : y - 16
      return { left: x0, right: x0 + ancho, top: y0, bottom: y0 + 14 }
    },
  }
}
const raiz = (...hijos) => ({ nodeType: 1, getAttribute: () => null, childNodes: hijos })

describe('taparRotulos (lo dibujado)', () => {
  // Las rayas: `y` es la altura de la raya; el rótulo va abajo (top-0.5) o arriba.
  it('AAPL 24/10: raya corta, choca en las dos puntas con la onda 4 → pasa arriba de su raya', () => {
    // Medido en el navegador: raya del corte de 1006 a 1211, rótulo de 212 px,
    // la onda 4 en 997–1015 justo debajo.
    const onda4 = rotulo({ prioridad: PRIORIDAD.onda, izq: 997, y: 194, ancho: 18 })
    const corte = rotulo({ prioridad: PRIORIDAD.corteFib, clase: 'absolute top-0.5 right-1', voltear: true, izq: 1010, der: 1207, y: 194, ancho: 212 })
    taparRotulos(raiz(onda4, corte))
    expect(corte.style.visibility).toBe('')
    expect(corte.style.bottom).toBe('2px')          // arriba de la raya
    expect(corte.style.left).toBe('')               // en su punta de siempre
  })

  it('primero prueba la otra punta; el de menos prioridad le deja el lugar', () => {
    const onda4 = rotulo({ prioridad: PRIORIDAD.onda, izq: 650, y: 82, ancho: 18 })
    const corte = rotulo({ prioridad: PRIORIDAD.corteFib, clase: 'absolute top-0.5 right-1', voltear: true, izq: 448, der: 700, y: 82 })
    const elliott = rotulo({ prioridad: PRIORIDAD.invalidaElliott, clase: 'absolute top-0.5 left-1', voltear: true, izq: 448, der: 820, y: 88 })
    taparRotulos(raiz(onda4, corte, elliott))
    expect(corte.style.left).toBe('4px')             // el del Fibonacci, a la otra punta
    expect(corte.style.visibility).toBe('')
    expect(elliott.style.right).toBe('4px')          // el de Elliott, a la otra punta de la suya
    expect(elliott.style.visibility).toBe('')
  })

  it('si no entra en ningún lugar, se esconde y queda en el suyo', () => {
    // Una onda en cada lugar posible del rótulo.
    const ondas = [[650, 82], [300, 82], [650, 66], [300, 66]].map(([x, y]) => rotulo({ prioridad: PRIORIDAD.onda, izq: x, y, ancho: 18 }))
    const corte = rotulo({ prioridad: PRIORIDAD.corteFib, clase: 'absolute top-0.5 right-1', voltear: true, izq: 300, der: 700, y: 82 })
    taparRotulos(raiz(...ondas, corte))
    expect(corte.getAttribute('data-tapado')).toBe('')
    expect(corte.style.visibility).toBe('hidden')
    expect([corte.style.left, corte.style.right, corte.style.top, corte.style.bottom, corte.style.transform]).toEqual(['', '', '', '', ''])
  })

  it('GGAL en el celular: el rótulo de raya que se sale del gráfico prueba la otra punta', () => {
    // Gráfico de 0 a 245 px; la raya del corte arranca en 150 y el rótulo
    // (220 px) a la izquierda de la raya se salía por la derecha, sobre el
    // último precio de la columna.
    const corte = rotulo({ prioridad: PRIORIDAD.corteFib, clase: 'absolute top-0.5 left-1', voltear: true, izq: 150, der: 241, y: 120, ancho: 220 })
    const r = raiz(corte)
    r.getBoundingClientRect = () => ({ left: 0, right: 245, top: 0, bottom: 250 })
    taparRotulos(r)
    expect(corte.style.right).toBe('4px')            // pegado a la punta derecha: entra entero
    expect(corte.style.visibility).toBe('')
    // Si no entra en ningún lado (más ancho que el gráfico), se esconde.
    const ancho = rotulo({ prioridad: PRIORIDAD.corteFib, clase: 'absolute top-0.5 left-1', voltear: true, izq: 150, der: 241, y: 120, ancho: 300 })
    const r2 = raiz(ancho)
    r2.getBoundingClientRect = r.getBoundingClientRect
    taparRotulos(r2)
    expect(ancho.style.visibility).toBe('hidden')
  })

  it('un rótulo sin `voltear` no se mueve: se esconde', () => {
    const a = rotulo({ prioridad: PRIORIDAD.onda, izq: 100, y: 0, ancho: 18 })
    const b = rotulo({ prioridad: PRIORIDAD.nivelFib, izq: 90, y: 2 })
    // La posición que le pone React (los números de las ondas van con `left`) no se toca.
    a.style.left = '37.5%'
    b.style.left = '12%'
    taparRotulos(raiz(a, b))
    expect(a.style.left).toBe('37.5%')
    expect(b.style.left).toBe('12%')
    expect(b.style.visibility).toBe('hidden')
    // En el dibujo siguiente, sin el que lo tapaba, vuelve.
    a.getBoundingClientRect = () => ({ left: 0, right: 0, top: 0, bottom: 0 })
    taparRotulos(raiz(a, b))
    expect(b.style.visibility).toBe('')
    expect(b.getAttribute('data-tapado')).toBeNull()
  })
})

// D2 (re-test de la auditoría D, 29/10): en el celular el rótulo del corte del
// Fibonacci medía más que el gráfico (x −16 a 270 en 245 px) y se escondía:
// quedaba la raya sin texto. Ancho estimado: 5 px por carácter con la letra de
// 10,5 px, calibrado con lo medido en el navegador (el rótulo viejo, 44
// caracteres = 217 px; el de 60 = 286 px), más 8 de margen. Tiene que entrar
// con el precio más largo que puede tener.
describe('los rótulos de raya entran en el gráfico del celular', () => {
  const ancho = (t) => t.length * 5 + 8
  const PRECIOS = ['US$ 38,84', 'US$ 1.854,88', '$ 12.345,67', '$ 1.234.567']
  it('el corte del Fibonacci y el del conteo de Elliott, con cualquier precio', () => {
    for (const p of PRECIOS) {
      for (const t of [rotuloCorteFib(true, p), rotuloCorteFib(false, p), rotuloInvalidaElliott(p)]) {
        expect(ancho(t), t).toBeLessThanOrEqual(ANCHO_GRAFICO_CELULAR)
      }
    }
  })
  it('y siguen hablando como posibilidad', () => {
    for (const t of [rotuloCorteFib(true, 'US$ 1'), rotuloCorteFib(false, 'US$ 1'), rotuloInvalidaElliott('US$ 1')]) {
      expect(t).toMatch(/podría|dejaría/)
    }
  })
})
