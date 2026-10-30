// Lo que DIBUJA «Tu lista, con su lectura técnica» (pages/TuLista.jsx): los
// filtros con su cantidad, las palabras de la ficha en cada columna, «Sin
// lectura» con su motivo, las cuatro explicaciones, la línea «no es una
// recomendación», y que con «Ocultar saldos» no se vea cuánto pesa cada uno.
import { describe, it, expect, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { TablaLista } from './TuLista'
import { filasDeLaLista } from '../utils/listaTecnica'
import { indexarLecturas } from '../utils/radiografia'
import { setBrokersRegistry } from '../utils/valuation'

beforeEach(() => setBrokersRegistry([{ id: 1, name: 'IOL', currency: 'ARS' }, { id: 2, name: 'Schwab', currency: 'USD' }]))

const hoy = new Date().toISOString().slice(0, 10)
const lec = (asset, local, l = {}, extra = {}) => ({
  asset, local, disponible: true,
  lectura: { ruedas: 760, fecha: hoy, media200: 90, dist_media200: 11, tendencia: 'alcista', pendiente_media200: 2, media50: 95,
    dist_media50: -2, rsi: 28, adx: 31, dist_maximo_12m: -24.3, anio_completo: true, ...l },
  linea: [{ d: '2026-08-01', c: 10 }, { d: hoy, c: 12 }], ultimo_cambio: null, ...extra,
})
// Como lo manda el servidor (POST /api/tecnico/lista → tenencias).
const TENENCIAS = [
  { asset: 'AL30', local: true, peso: 0.88, tipo: 'BONO' },
  { asset: 'MELI', local: false, peso: 0.12, tipo: 'STOCK' },
]
const filas = filasDeLaLista({
  tenencias: TENENCIAS, seguidos: [{ symbol: 'TSLA' }],
  indice: indexarLecturas([lec('MELI', false, {}, { ultimo_cambio: {
    tipo: 'media200', sentido: 'arriba', fecha: hoy, etiqueta: 'Tendencia de largo plazo', tono: 'pos', extra: null,
    texto: 'superó su promedio de 200 días: la tendencia de largo plazo pasó a ser alcista.' } }), lec('TSLA', false, { adx: 12 }), { asset: 'AL30', local: true, disponible: false }]),
})
const dibujar = (oculto = false) => renderToStaticMarkup(
  <MemoryRouter><TablaLista filas={filas} oculto={oculto} /></MemoryRouter>,
)
const texto = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;|&#39;/g, "'").replace(/\s+/g, ' ')

describe('Tu lista: la tabla', () => {
  it('los filtros con su cantidad y el «Ordenar por»', () => {
    const t = texto(dibujar())
    expect(t).toContain('Todo · 3')
    expect(t).toContain('Lo que tenés · 2')
    expect(t).toContain('Watchlist · 1')
    for (const o of ['Lo último que cambió', 'Impulso (RSI)', 'Desde el máximo', 'Lo que más pesa']) expect(t).toContain(o)
  })

  it('cada columna con las palabras de la ficha', () => {
    const t = texto(dibujar())
    expect(t).toContain('Sí · 12%')
    expect(t).toContain('Alcista')
    expect(t).toContain('Bajista')                 // corto plazo, debajo del de 50
    expect(t).toContain('28 cayó muy rápido')
    expect(t).toContain('31 marcada')
    expect(t).toContain('12 lateral')
    expect(t).toContain('−24,3%')
    expect(t).toContain('Superó su promedio de 200 días · hoy')
    expect(dibujar()).toContain('title="Superó su promedio de 200 días: la tendencia de largo plazo pasó a ser alcista."')
  })

  it('el bono va «Sin lectura» y dice por qué; las filas abren la ficha', () => {
    const html = dibujar()
    const t = texto(html)
    expect(t).toContain('Sin lectura')
    expect(t).toContain('no se les calcula la tendencia')   // el motivo del globo de la radiografía
    expect(html).toContain('href="/activo/MELI"')
    expect(html).toContain('href="/activo/TSLA"')
  })

  it('las cuatro explicaciones y «no es una recomendación»', () => {
    const t = texto(dibujar())
    for (const k of ['Largo y mediano plazo', 'Fuerza de la tendencia (ADX)', 'Debajo de 23, se mueve sin una dirección clara', 'Último cambio']) {
      expect(t).toContain(k)
    }
    expect(t).toContain('No es una recomendación de compra ni de venta.')
  })

  it('con «Ocultar saldos» no se ve cuánto pesa', () => {
    const t = texto(dibujar(true))
    expect(t).not.toContain('12%')
    expect(t).not.toContain('88%')
    expect(t).toContain('Sí')
  })
})
