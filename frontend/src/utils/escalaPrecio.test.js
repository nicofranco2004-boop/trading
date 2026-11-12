// La regla precio ↔ altura del gráfico técnico (utils/escalaPrecio.js), en
// lineal y en logarítmica. El gráfico montado de verdad con «Log» prendido se
// prueba en components/asset/EscalaLogGrafico.test.js.
import { describe, it, expect } from 'vitest'
import { armarEscala, cabeEnLaEscala, escalaDe, ladoDeAfuera, largoEnEje, marcasLog, precioCorrido, precioEnLaRecta, precioMasAncho, rangoConAire } from './escalaPrecio'
import { marcasDePrecio } from './ejesGrafico'

describe('la escala', () => {
  it('en lineal, la mitad de la plata va a la mitad del alto (como siempre)', () => {
    const e = armarEscala(100, 300, 400, 'lineal')
    expect(e.y(300)).toBeCloseTo(0)
    expect(e.y(100)).toBeCloseTo(400)
    expect(e.y(200)).toBeCloseTo(200)
    expect(e.precio(200)).toBeCloseTo(200)
  })

  it('en log, cada vez que el precio se duplica sube lo mismo', () => {
    const e = armarEscala(100, 800, 300, 'log')
    // 100 → 200 → 400 → 800: tres duplicaciones en 300 de alto, 100 cada una.
    expect(e.y(800)).toBeCloseTo(0)
    expect(e.y(400)).toBeCloseTo(100)
    expect(e.y(200)).toBeCloseTo(200)
    expect(e.y(100)).toBeCloseTo(300)
    // El medio del alto es el precio que multiplica igual para los dos lados.
    expect(e.precio(150)).toBeCloseTo(Math.sqrt(100 * 800))
  })

  it('ida y vuelta da el mismo precio en las dos escalas', () => {
    for (const escala of ['lineal', 'log']) {
      const e = armarEscala(3.2, 9123, 517, escala)
      for (const p of [3.2, 17.5, 640, 9123]) expect(e.precio(e.y(p))).toBeCloseTo(p, 6)
    }
  })

  it('un valor desconocido o viejo es lineal', () => {
    expect(escalaDe(undefined)).toBe('lineal')
    expect(escalaDe('LOG')).toBe('lineal')
    expect(escalaDe('log')).toBe('log')
    expect(armarEscala(0, 10, 10, null).y(5)).toBeCloseTo(5)
  })

  it('en log no entra un precio cero o negativo', () => {
    expect(cabeEnLaEscala(0, 'log')).toBe(false)
    expect(cabeEnLaEscala(-3, 'log')).toBe(false)
    expect(cabeEnLaEscala(0, 'lineal')).toBe(true)
    expect(cabeEnLaEscala(NaN, 'lineal')).toBe(false)
  })
})

describe('arrastres y márgenes, en el eje de cada escala', () => {
  it('correr un precio: en lineal suma plata, en log multiplica', () => {
    expect(precioCorrido(100, 20, 'lineal')).toBe(120)
    expect(precioCorrido(100, -500, 'lineal')).toBe(2)          // nunca llega a 0
    expect(precioCorrido(100, Math.log(2), 'log')).toBeCloseTo(200)
    expect(precioCorrido(100, -Math.log(4), 'log')).toBeCloseTo(25)
  })

  it('lo que mide un rango en el eje', () => {
    expect(largoEnEje(100, 300, 'lineal')).toBe(200)
    expect(largoEnEje(100, 400, 'log')).toBeCloseTo(Math.log(4))
  })

  it('el aire de arriba y abajo: parejo en pantalla y nunca bajo cero en log', () => {
    const [lo, hi] = rangoConAire(10, 1000, 'log', 0.1, 0.25)
    expect(lo).toBeGreaterThan(0)
    const e = armarEscala(lo, hi, 1000, 'log')
    // 10 % de aire arriba del máximo.
    expect(e.y(1000) / 1000).toBeCloseTo(0.1 / (1.2 * 1.25), 6)
    // En lineal, igual que antes: (b - a) * 0.08 y un 25 % más abajo para el volumen.
    expect(rangoConAire(100, 200, 'lineal', 0.08, 0.25)).toEqual([92 - 0.25 * 116, 208])
  })

  it('«tu precio» lejos: medido en el eje', () => {
    expect(ladoDeAfuera(50, 100, 200, 'lineal', 0.35)).toBe('abajo')      // 50 < 100 − 35
    expect(ladoDeAfuera(70, 100, 200, 'lineal', 0.35)).toBe(null)
    // En log, 100 → 200 es una duplicación; 35 % de eso es ×1,27: 70 está más lejos.
    expect(ladoDeAfuera(70, 100, 200, 'log', 0.35)).toBe('abajo')
    expect(ladoDeAfuera(85, 100, 200, 'log', 0.35)).toBe(null)
    expect(ladoDeAfuera(0, 100, 200, 'log', 0.35)).toBe('abajo')
  })
})

describe('la recta de una línea, en su escala', () => {
  const a = { k: 0, precio: 100 }, b = { k: 10, precio: 200 }
  it('en lineal sube la misma plata por lugar; en log, el mismo porcentaje', () => {
    expect(precioEnLaRecta(a, b, 20, 'lineal')).toBeCloseTo(300)
    expect(precioEnLaRecta(a, b, 20, 'log')).toBeCloseTo(400)
    expect(precioEnLaRecta(a, b, 5, 'log')).toBeCloseTo(100 * Math.SQRT2)
    expect(precioEnLaRecta(a, { k: 0, precio: 300 }, 7, 'log')).toBe(100)   // mismo lugar: la de a
  })

  it('el ejemplo de NVDA de la propuesta: US$ 66 contra US$ 89', () => {
    // 2/1/2023 US$ 14,8095 → 1/1/2024 US$ 48,9551 (52 semanas), seguida 26 semanas más.
    const p = { k: 0, precio: 14.8095 }, q = { k: 52, precio: 48.9551 }
    expect(precioEnLaRecta(p, q, 78, 'lineal')).toBeCloseTo(66.03, 1)
    expect(precioEnLaRecta(p, q, 78, 'log')).toBeCloseTo(89.01, 1)
  })

  it('la paralela de un canal: plata en lineal, cuánto multiplica en log', () => {
    expect(precioMasAncho(100, 15, 'lineal')).toBe(115)
    expect(precioMasAncho(100, Math.log(1.5), 'log')).toBeCloseTo(150)
  })
})

describe('los rótulos del eje en log', () => {
  const parejos = (lo, hi, alto) => marcasDePrecio(lo, hi, alto)

  it('cinco años de un papel que subió 20 veces: 1-2-5 por década, sin pisarse', () => {
    const m = marcasLog(10, 250, 500, parejos)
    expect(m[0]).toBeGreaterThanOrEqual(10)
    expect(m[m.length - 1]).toBeLessThanOrEqual(250)
    const e = armarEscala(10, 250, 500, 'log')
    for (let i = 1; i < m.length; i++) expect(e.y(m[i - 1]) - e.y(m[i])).toBeGreaterThanOrEqual(40)
    // Números redondos: 10, 20, 50, 100, 200 están; un 37 no.
    for (const v of [10, 20, 50, 100, 200]) expect(m).toContain(v)
    expect(m.every(v => /^(1|1\.2|1\.5|2|2\.5|3|4|5|6|7|8)$/.test(String(v / Math.pow(10, Math.floor(Math.log10(v))))))).toBe(true)
  })

  it('un rango angosto (unas semanas) usa los redondos parejos de siempre', () => {
    const m = marcasLog(197.7, 212.4, 400, parejos)
    expect(m.length).toBeGreaterThanOrEqual(3)
    for (const v of m) expect(parejos(197.7, 212.4, 400)).toContain(v)
    const e = armarEscala(197.7, 212.4, 400, 'log')
    for (let i = 1; i < m.length; i++) expect(e.y(m[i - 1]) - e.y(m[i])).toBeGreaterThanOrEqual(30)
  })

  it('centavos y miles también', () => {
    expect(marcasLog(0.0123, 0.95, 400, parejos).length).toBeGreaterThanOrEqual(3)
    expect(marcasLog(130, 9000, 300, parejos).length).toBeGreaterThanOrEqual(3)
  })

  it('sin rango, sin alto o con precios no positivos, nada', () => {
    expect(marcasLog(5, 5, 300, parejos)).toEqual([])
    expect(marcasLog(-1, 5, 300, parejos)).toEqual([])
    expect(marcasLog(1, 5, 0, parejos)).toEqual([])
  })
})
