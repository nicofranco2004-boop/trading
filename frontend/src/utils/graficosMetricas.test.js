import { describe, it, expect } from 'vitest'
import { ultimoConValor, etiquetasFinales, marcaPeorCaida } from './insightsModel'

// Lo que se escribe AL LADO de un gráfico de Métricas tiene que decir lo mismo
// que la pantalla publica arriba (el KPI "Acumulado", el "Máx histórico").

const FILAS = [
  { key: '2026-01-02', ts: 1, total: 0, bench: 0 },
  { key: '2026-06-02', ts: 2, total: 4.2, bench: 5.0 },
  { key: 'corte-2026-07-01', ts: 3, total: null, bench: null },   // el hueco de un corte
  { key: '2026-09-30', ts: 4, total: 9.94, bench: 10.46 },
  { key: 'today', ts: 5, total: null, estimado: 9.9, bench: null },
]

describe('ultimoConValor — la punta de una línea', () => {
  it('la última fila con número, en el orden de claves pedido', () => {
    expect(ultimoConValor(FILAS, ['total', 'estimado'])).toMatchObject({ clave: 'estimado', valor: 9.9 })
    expect(ultimoConValor(FILAS, ['bench'])).toMatchObject({ valor: 10.46, fila: { ts: 4 } })
    expect(ultimoConValor([], ['total'])).toBe(null)
  })
})

describe('etiquetasFinales — sólo si se leen igual que el KPI', () => {
  it('coinciden con 1 decimal: se escriben, con el texto del KPI', () => {
    const e = etiquetasFinales({ filas: FILAS, clavesCartera: ['total', 'estimado'], claveBench: 'bench', kpiCartera: 9.94, kpiBench: 10.5 })
    expect(e.cartera).toMatchObject({ ts: 5, texto: '+9,9%' })
    expect(e.bench).toMatchObject({ ts: 4, texto: '+10,5%' })
  })
  it('la punta dibujada dice otra cosa que el KPI publicado: esa etiqueta no va (85 de 655 cuentas)', () => {
    const e = etiquetasFinales({ filas: FILAS, clavesCartera: ['total', 'estimado'], claveBench: 'bench', kpiCartera: 9.6, kpiBench: 10.5 })
    expect(e.cartera).toBe(null)
    expect(e.bench).not.toBe(null)
  })
  it('sin KPI (serie partida, el servidor no publica): sin etiquetas', () => {
    const e = etiquetasFinales({ filas: FILAS, clavesCartera: ['total'], claveBench: 'bench', kpiCartera: null, kpiBench: null })
    expect(e).toEqual({ cartera: null, bench: null })
  })
  it('una fila sin lugar en el eje de tiempo (sin ts): sin etiqueta', () => {
    const f = [{ key: '2026-09', total: 9.94 }]
    expect(etiquetasFinales({ filas: f, clavesCartera: ['total'], kpiCartera: 9.94 }).cartera).toBe(null)
  })
  it('una pérdida se escribe con el signo menos de verdad', () => {
    const f = [{ ts: 1, total: -3.04 }]
    expect(etiquetasFinales({ filas: f, clavesCartera: ['total'], kpiCartera: -3.0 }).cartera.texto).toBe('−3,0%')
  })
})

describe('marcaPeorCaida — el punto más hondo, si es el "Máx histórico" que se publica', () => {
  // Los rótulos se repiten (una serie diaria tiene 30 "May '25"): la marca se
  // ubica por la CLAVE (la fecha), que es única.
  const serie = [
    { key: '2025-01-02', label: "Ene '25", ddPct: 0 }, { key: '2025-05-02', label: "May '25", ddPct: -1.2 },
    { key: '2025-05-19', label: "May '25", ddPct: -3.94 }, { key: 'hoy', label: 'Hoy', ddPct: -0.7 },
    { key: 'corte-x', label: '', ddPct: null },
  ]
  it('coincide: la marca con su número, su fecha y su clave', () => {
    expect(marcaPeorCaida(serie, -3.9)).toEqual({
      key: '2025-05-19', label: "May '25", ddPct: -3.94, texto: "Peor caída −3,9% · May '25", posicion: 0.5,
    })
  })
  it('no coincide con lo publicado: no hay marca', () => {
    expect(marcaPeorCaida(serie, -5.2)).toBe(null)
  })
  it('sin caídas (todo en 0) o sin serie: no hay marca', () => {
    expect(marcaPeorCaida([{ label: 'x', ddPct: 0 }], 0)).toBe(null)
    expect(marcaPeorCaida([], -1)).toBe(null)
  })
})

import { ladoDeLaMarca } from './insightsModel'

describe('ladoDeLaMarca — el texto de la peor caída va donde ENTRA, en píxeles', () => {
  const texto = "Peor caída −12,3% · May '25"      // 27 letras ≈ 184 px
  const textoCorto = '−12,3%'
  it('en la compu (1000 px) entra entero, del lado con lugar', () => {
    expect(ladoDeLaMarca({ posicion: 0.2, ancho: 1000, texto, textoCorto })).toEqual({ lado: 'derecha', texto, corto: false })
    expect(ladoDeLaMarca({ posicion: 0.95, ancho: 1000, texto, textoCorto })).toEqual({ lado: 'izquierda', texto, corto: false })
  })
  it('en un celular (~345 px de gráfico) con el punto en el medio: sólo el número (antes se cortaba en "−1")', () => {
    expect(ladoDeLaMarca({ posicion: 0.5, ancho: 345, texto, textoCorto })).toEqual({ lado: 'derecha', texto: textoCorto, corto: true })
  })
  it('pegado a la derecha en un celular: el texto entero entra a la izquierda', () => {
    expect(ladoDeLaMarca({ posicion: 0.98, ancho: 345, texto, textoCorto })).toMatchObject({ lado: 'izquierda', corto: false })
  })
  it('muy angosto y pegado a la derecha: el número corto, a la izquierda', () => {
    expect(ladoDeLaMarca({ posicion: 0.95, ancho: 230, texto, textoCorto })).toEqual({ lado: 'izquierda', texto: textoCorto, corto: true })
  })
  it('sin ancho medido todavía: lo seguro (el corto)', () => {
    expect(ladoDeLaMarca({ posicion: 0.5, ancho: 0, texto, textoCorto })).toMatchObject({ corto: true })
  })
})

import { ubicarEtiquetas } from './insightsModel'

describe('ubicarEtiquetas — las dos etiquetas de punta, dentro del dibujo y sin pisarse', () => {
  const area = { top: 10, bottom: 290 }
  it('la de arriba sobre su punto, la de abajo debajo', () => {
    const [a, b] = ubicarEtiquetas([{ id: 'bench', y: 120 }, { id: 'cartera', y: 60 }], area)
    expect([a.id, a.ty]).toEqual(['cartera', 51])
    expect([b.id, b.ty]).toEqual(['bench', 137])
  })
  it('cartera en su máximo, pegada al techo: la etiqueta no se sale por arriba', () => {
    const [a] = ubicarEtiquetas([{ y: 12 }], area)
    expect(a.ty).toBe(23)                 // top + alto
  })
  it('"Pesos cash" en 0 % pegado al piso: su etiqueta no baja sobre las fechas', () => {
    const [, b] = ubicarEtiquetas([{ id: 'cartera', y: 100 }, { id: 'bench', y: 290 }], area)
    expect(b.ty).toBe(286)                // bottom − 4, no 307
  })
  it('dos puntas casi en el mismo lugar: se separan', () => {
    const [a, b] = ubicarEtiquetas([{ y: 150 }, { y: 152 }], area)
    expect(b.ty - a.ty).toBeGreaterThanOrEqual(15)
  })
  it('las dos pegadas al piso: se separan hacia arriba, sin salirse', () => {
    const [a, b] = ubicarEtiquetas([{ y: 289 }, { y: 290 }], area)
    expect(b.ty).toBe(286)
    expect(a.ty).toBe(271)
  })
})
