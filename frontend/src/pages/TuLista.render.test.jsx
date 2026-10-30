// Lo que DIBUJA «Tu lista, con su lectura técnica» (pages/TuLista.jsx), en sus
// dos vistas. La TABLA: los filtros con su cantidad, las palabras de la ficha
// en cada columna, «Sin lectura» con su motivo, la «i» de cada columna, la
// línea «no es una recomendación», y que con «Ocultar saldos» no se vea cuánto
// pesa cada uno. Las TARJETAS (la de entrada, Nico 30/10): la franja de 4
// números, lo mismo con otra forma, «Nuevo» en lo que cambió esta semana, el
// link de verdad a la ficha, «Avisame» y el ojito.
import { describe, it, expect, beforeEach } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { ListaTecnica } from './TuLista'
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
const dibujar = (oculto = false, vista = 'tabla', estas = filas) => renderToStaticMarkup(
  <MemoryRouter><ListaTecnica filas={estas} oculto={oculto} vista={vista} /></MemoryRouter>,
)
const texto = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;|&#39;/g, "'").replace(/\s+/g, ' ')

describe('Tu lista: la tabla', () => {
  it('los filtros con su cantidad y el «Ordenar por»', () => {
    const t = texto(dibujar())
    expect(t).toContain('Todo · 3')
    expect(t).toContain('Tu cartera · 2')
    expect(t).toContain('Watchlist · 1')
    for (const o of ['Cambio más reciente', 'Impulso (RSI)', 'Desde el máximo', 'Mayor peso en tu cartera']) expect(t).toContain(o)
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

  it('cada columna con su «i» que explica qué mide, y «no es una recomendación»', () => {
    const html = dibujar()
    for (const k of ['Largo plazo', 'Mediano plazo', 'Impulso (RSI)', 'Fuerza de la tendencia (ADX)', 'Último cambio']) {
      expect(html).toContain(`aria-label="Qué es «${k}»"`)
    }
    expect(html).toContain('Debajo de 23, se mueve sin una dirección clara')
    expect(texto(html)).toContain('No es una recomendación de compra ni de venta.')
    expect(texto(html)).not.toContain('Tendencia: si el precio está arriba o abajo')   // el pie es de las tarjetas
  })

  it('con «Ocultar saldos» no se ve cuánto pesa', () => {
    const t = texto(dibujar(true))
    expect(t).not.toContain('12%')
    expect(t).not.toContain('88%')
    expect(t).toContain('Sí')
  })
})

// Una lectura con su línea de 3 meses: de 100 a 120 (+20 %) o de 120 a 100.
const conLinea = (asset, sube, l = {}, extra = {}) => lec(asset, false, { precio: sube ? 120 : 100, ...l },
  { linea: [{ d: '2026-08-01', c: sube ? 100 : 120 }, { d: '2026-09-15', c: 110 }, { d: hoy, c: sube ? 120 : 100 }], ...extra })
const haceDias = (n) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10)
const cambio = (fecha) => ({ ultimo_cambio: { tipo: 'maximo', fecha, tono: 'max', corta: 'marcó su máximo del año', texto: 'marcó su máximo del año.' } })
const filasTarjetas = filasDeLaLista({
  tenencias: [...TENENCIAS, { asset: 'NVDA', local: false, peso: 0, tipo: 'STOCK' }],
  seguidos: [{ symbol: 'TSLA' }, { symbol: 'KO' }],
  indice: indexarLecturas([
    conLinea('MELI', true, { rsi: 61, adx: 31 }, cambio(haceDias(2))),
    conLinea('NVDA', true, { rsi: 74, adx: 40, dist_maximo_12m: 0 }),
    conLinea('TSLA', false, { rsi: 28, adx: 12, dist_media200: -5, tendencia: 'bajista' }, cambio(haceDias(20))),
    conLinea('KO', false, { rsi: 50, adx: 20 }),
    { asset: 'AL30', local: true, disponible: false },
  ]),
})
const tarjetas = (oculto = false) => dibujar(oculto, 'tarjetas', filasTarjetas)

describe('Tu lista: las tarjetas', () => {
  it('el botón «Tarjetas / Tabla» marca la vista elegida', () => {
    expect(tarjetas()).toMatch(/aria-pressed="true"[^>]*>.*?Tarjetas</)
    expect(dibujar()).toMatch(/aria-pressed="true"[^>]*>.*?Tabla</)
    expect(tarjetas()).not.toContain('<table')
    expect(dibujar()).toContain('<table')
  })

  it('la franja: alcistas de largo plazo de cuántos, ganando impulso, en su máximo y cuántos cambiaron esta semana', () => {
    const t = texto(tarjetas())
    expect(t).toContain('Con tendencia alcista de largo plazo 3 de 4')   // MELI, NVDA, KO; TSLA bajista; AL30 sin lectura
    expect(t).toContain('Ganando impulso 2 Impulso (RSI) arriba de 55')  // 61 y 74
    expect(t).toContain('En su máximo del año 1 NVDA')
    expect(t).toContain('Cambiaron esta semana 1 Ver las señales')       // el de hace 20 días no cuenta
    expect(tarjetas()).toContain('href="/analisis-tecnico?tab=senales"')
  })

  it('separadas en «En tu cartera» y «En tu watchlist», con el nombre, el precio y los 3 meses', () => {
    const t = texto(tarjetas())
    expect(t).toMatch(/En tu cartera 3 .*MELI.*En tu watchlist 2 .*(KO|TSLA)/)
    expect(t).toContain('NVIDIA')
    expect(t).toContain('$120,00 USD')
    expect(t).toContain('+20,0% en 3 meses')
    expect(t).toContain('−16,7% en 3 meses')
  })

  it('los tres medidores, con las palabras de la ficha', () => {
    const html = tarjetas()
    const t = texto(html)
    expect(t).toContain('Alcista largo')
    expect(t).toContain('Bajista mediano')
    expect(html).toContain('aria-label="Impulso (RSI): 74 de 100"')
    expect(t).toContain('subió muy rápido')
    expect(t).toContain('cayó muy rápido')
    expect(t).toContain('dirección marcada')
    expect(t).toContain('sin dirección clara')                    // TSLA, ADX 12
    expect(html).toContain('aria-label="Fuerza de la tendencia (ADX): 12"')
  })

  it('lo que cambió esta semana va con «Nuevo» y borde violeta; lo de antes, no', () => {
    const html = tarjetas()
    const meli = html.slice(html.indexOf('href="/activo/MELI"') - 900, html.indexOf('href="/activo/MELI"') + 400)
    expect(meli).toContain('border-data-violet/45')
    expect(meli).toContain('Nuevo')
    const tsla = html.slice(html.indexOf('href="/activo/TSLA"') - 900, html.indexOf('href="/activo/TSLA"') + 400)
    expect(tsla).not.toContain('Nuevo')
    expect(texto(html)).toContain('Marcó su máximo del año · hace 2 semanas')
    expect(texto(html)).toContain('Sin cambios en el último año')
  })

  it('cada tarjeta es un link de verdad a la ficha y lleva su «Avisame»', () => {
    const html = tarjetas()
    for (const a of ['MELI', 'NVDA', 'TSLA', 'KO', 'AL30']) expect(html).toContain(`href="/activo/${a}"`)
    expect((html.match(/> ?Avisame</g) || []).length).toBe(4)       // AL30, sin lectura, no
  })

  it('el bono va en una tarjeta punteada que dice por qué no tiene lectura', () => {
    const html = tarjetas()
    expect(html).toContain('border-dashed')
    expect(texto(html)).toContain('Sin lectura técnica. Rendi no guarda la historia de precios de bonos')
  })

  it('el % de tu cartera, y con «Ocultar saldos» nada que lo delate', () => {
    expect(texto(tarjetas())).toContain('12% de tu cartera')
    expect(texto(tarjetas())).toContain('88% de tu cartera')
    const t = texto(tarjetas(true))
    expect(t).not.toMatch(/\d% de tu cartera/)
    expect(t).not.toContain('12%')
    expect(t).not.toContain('88%')
    expect(t).toContain('Watchlist')
  })

  it('el pie explica en una línea qué mide cada cosa', () => {
    const t = texto(tarjetas())
    expect(t).toContain('Tendencia: si el precio está arriba o abajo de su promedio de 200 días de mercado')
    expect(t).toContain('debajo de 23, se mueve sin una dirección clara')
    expect(t).toContain('No es una recomendación de compra ni de venta.')
  })
})
