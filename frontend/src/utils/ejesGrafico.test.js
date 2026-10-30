// Las cuentas de arrastrar los ejes (utils/ejesGrafico.js). El arrastre montado
// de verdad se prueba en components/asset/EjesGrafico.test.js.
import { describe, it, expect } from 'vitest'
import { PIXELES_POR_DOBLE, factorDeFechas, fechaDeLaMira, marcasDeFechas, marcasDePrecio, rangoCorrido, rangoEstirado } from './ejesGrafico'

describe('eje de precios', () => {
  it('hacia abajo entra el doble de rango; hacia arriba, la mitad; el centro queda quieto', () => {
    expect(rangoEstirado(100, 200, PIXELES_POR_DOBLE)).toEqual({ lo: 50, hi: 250 })
    expect(rangoEstirado(100, 200, -PIXELES_POR_DOBLE)).toEqual({ lo: 125, hi: 175 })
    expect(rangoEstirado(100, 200, 0)).toEqual({ lo: 100, hi: 200 })
  })

  it('tiene topes por arrastre', () => {
    const lejos = rangoEstirado(100, 200, 5000)
    expect(lejos.hi - lejos.lo).toBeCloseTo(600)
    const cerca = rangoEstirado(100, 200, -5000)
    expect(cerca.hi - cerca.lo).toBeCloseTo(20)
  })

  it('arrastrar el gráfico hacia abajo muestra precios más altos', () => {
    expect(rangoCorrido(100, 200, 0.1)).toEqual({ lo: 110, hi: 210 })
    expect(rangoCorrido(100, 200, -0.25)).toEqual({ lo: 75, hi: 175 })
  })
})

describe('eje de fechas', () => {
  it('a la izquierda acerca (menos días), a la derecha aleja', () => {
    // A la izquierda (dx < 0) acerca: la mitad de días; a la derecha aleja.
    expect(factorDeFechas(-PIXELES_POR_DOBLE)).toBeCloseTo(0.5)
    expect(factorDeFechas(PIXELES_POR_DOBLE)).toBeCloseTo(2)
  })
})

// Los rótulos de los ejes como TradingView (Nico, 29/10).

describe('los rótulos de los ejes', () => {
  // Días de mercado (lunes a viernes) desde una fecha.
  const dias = (n, desde) => {
    const out = []
    for (let t = Date.parse(desde + 'T12:00:00Z'); out.length < n; t += 86400000) {
      const d = new Date(t)
      if (d.getUTCDay() % 6) out.push({ d: d.toISOString().slice(0, 10) })
    }
    return out
  }

  it('precios redondos y parejos; con más alto, más rótulos', () => {
    expect(marcasDePrecio(197.7, 352.4, 500)).toEqual([200, 220, 240, 260, 280, 300, 320, 340])
    expect(marcasDePrecio(197.7, 352.4, 250)).toEqual([200, 250, 300, 350])
    expect(marcasDePrecio(0.0123, 0.0189, 300)).toEqual([0.014, 0.016, 0.018])   // una cripto de centavos
    expect(marcasDePrecio(5, 5, 300)).toEqual([])
  })

  it('las fechas cambian de detalle con el zoom: trimestres, meses, quincenas, días', () => {
    const textos = (n, desde) => marcasDeFechas(dias(n, desde), 900).map(m => m.texto)
    expect(textos(750, '2023-10-30')).toEqual(['2024', 'abr', 'jul', 'oct', '2025', 'abr', 'jul', 'oct', '2026', 'abr', 'jul'])
    expect(textos(252, '2025-10-29')).toEqual(['nov', 'dic', '2026', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct'])
    expect(textos(63, '2025-10-29')).toEqual(['nov', '17', 'dic', '15', '2026', '15'])
    expect(textos(15, '2025-10-29')).toEqual(['30', '31', 'nov', '4', '5', '6', '7', '10', '11', '12', '13', '14', '17', '18'])
  })

  it('nunca dos rótulos pisados, con cualquier ancho', () => {
    for (const ancho of [250, 375, 600, 1200]) {
      const ms = marcasDeFechas(dias(500, '2024-01-02'), ancho)
      const px = ancho / 500
      for (let k = 1; k < ms.length; k++) expect((ms[k].i - ms[k - 1].i) * px).toBeGreaterThanOrEqual(60)
    }
  })

  it('el día bajo el mouse', () => {
    expect(fechaDeLaMira('2026-10-29')).toBe("jue 29 oct '26")
    expect(fechaDeLaMira(null)).toBe('')
  })
})
