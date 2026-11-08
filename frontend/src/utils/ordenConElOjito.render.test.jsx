// Con «Ocultar saldos» el ORDEN también dice cuánto tenés (auditoría D1+D5+D6,
// 31/10). Sin un solo % a la vista, «de más a menos plata» delata cuál pesa
// más. Seguían en ese orden:
//   · D1, el termómetro: «tu plata por sector» (los sectores de la frase, los
//     del detalle y los papeles de cada uno) venía del servidor de más a menos
//     plata, y `filasTuPlata` ni recibía el ojito;
//   · D5, Tu lista: «Mayor peso en tu cartera» ordenaba por peso con el ojito
//     prendido (y la franja nombraba «en su máximo» en el orden del peso);
//   · D6, el botón «Comparar»: abría tus 4 que más pesan, en ese orden.
// Arreglo: UN ayudante (ordenConElOjito, utils/parteDeTuPlata) que usan todos,
// también el Panorama, el mapa y Señales, que lo hacían cada uno a su manera.
//
// Los pesos de prueba van al revés del abecedario (el que más pesa es el
// último de la A a la Z), así el orden por peso y el alfabético nunca coinciden.
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { ordenConElOjito } from './parteDeTuPlata'
import { TuPlata } from '../components/home/Termometro'
import { ListaTecnica } from '../pages/TuLista'
import { urlDeCompararTuyos } from '../pages/AnalisisTecnico'
import { ordenarFilas, filasDeLaLista } from './listaTecnica'
import { indexarLecturas } from './radiografia'
import { cuadritosDelMapa } from './mapaCartera'
import { hoyISO } from './fecha'
import { enOrden } from './tusSenales'

const texto = (html) => html.replace(/<[^>]+>/g, ' ').replace(/&#x27;|&#39;/g, "'").replace(/\s+/g, ' ')
const enQueOrden = (t, nombres) => nombres.map(n => t.indexOf(n)).every((p, i, xs) => p >= 0 && (i === 0 || p > xs[i - 1]))

describe('el ayudante', () => {
  it('con el ojito, de la A a la Z; sin el ojito, como vino o con su comparador', () => {
    expect(ordenConElOjito(['YPF', 'AAPL', 'MELI'], true)).toEqual(['AAPL', 'MELI', 'YPF'])
    expect(ordenConElOjito(['YPF', 'AAPL', 'MELI'], false)).toEqual(['YPF', 'AAPL', 'MELI'])
    expect(ordenConElOjito([{ n: 'B', p: 1 }, { n: 'A', p: 9 }], false, { sinOjito: (a, b) => a.p - b.p }).map(x => x.n)).toEqual(['B', 'A'])
    // `antes` manda en los dos casos (el día en Señales, lo tuyo en Tu lista).
    const xs = [{ n: 'Z', g: 0 }, { n: 'A', g: 1 }, { n: 'M', g: 0 }]
    expect(ordenConElOjito(xs, true, { nombre: x => x.n, antes: (a, b) => a.g - b.g }).map(x => x.n)).toEqual(['M', 'Z', 'A'])
    // No toca la lista que recibe.
    const original = ['B', 'A']
    ordenConElOjito(original, true)
    expect(original).toEqual(['B', 'A'])
  })
})

// `tu_plata` como la arma el servidor (backend/termometro.tu_plata): sectores
// y papeles de más a menos plata.
const TP = {
  suben: { pct: 70, sectores: [
    { sector: 'tecnologia', mercado_pct: 61, pct: 50, papeles: ['NVDA', 'AAPL'] },
    { sector: 'financiero', mercado_pct: 81, pct: 20, papeles: ['GGAL'] },
  ] },
  bajan: { pct: 30, sectores: [
    { sector: 'energia', mercado_pct: 21, pct: 20, papeles: ['YPF'] },
    { sector: 'consumo_bas', mercado_pct: 11, pct: 10, papeles: ['KO'] },
  ] },
  sin_sector: { pct: 0, papeles: [] },
}

describe('D1: el termómetro (Inicio › Análisis de mercado)', () => {
  it('sin el ojito, como lo manda el servidor: de más a menos plata', () => {
    const t = texto(renderToStaticMarkup(<TuPlata tp={TP} abierto />))
    expect(t).toContain('(Tecnología y Financiero)')
    const detalle = t.slice(t.indexOf('Ocultar el detalle'))
    expect(enQueOrden(detalle, ['Tecnología', 'Financiero', 'Energía', 'Consumo básico'])).toBe(true)
    expect(t).toContain('NVDA · AAPL')
  })

  it('con el ojito, la frase, los sectores y los papeles van de la A a la Z', () => {
    const t = texto(renderToStaticMarkup(<TuPlata tp={TP} abierto oculto />))
    expect(t).toContain('(Financiero y Tecnología)')
    expect(t).toContain('(Consumo básico y Energía)')
    // El detalle: los que suben primero (eso no dice cuánto), cada parte por nombre.
    const detalle = t.slice(t.indexOf('Ocultar el detalle'))
    expect(enQueOrden(detalle, ['Financiero', 'Tecnología', 'Consumo básico', 'Energía'])).toBe(true)
    expect(t).toContain('AAPL · NVDA')
    // Los % del mercado (61 % de sus acciones sube) sí; los de tu plata, no.
    expect(t).toContain('61 % de sus acciones')
    expect(t).not.toMatch(/\b(70|50|30|20|10) ?%/)
  })
})

// Tu lista: tenencias como las manda el servidor (de más a menos peso).
const hoy = hoyISO()
const lec = (asset, l = {}) => ({
  asset, local: false, disponible: true,
  lectura: { ruedas: 760, fecha: hoy, media200: 90, dist_media200: 11, tendencia: 'alcista', pendiente_media200: 2, media50: 95,
    dist_media50: -2, rsi: 50, adx: 31, dist_maximo_12m: 0, anio_completo: true, ...l },
  linea: [{ d: '2026-08-01', c: 10 }, { d: hoy, c: 12 }], ultimo_cambio: null,
})
const FILAS = filasDeLaLista({
  tenencias: [
    { asset: 'YPF', local: false, peso: 0.5, tipo: 'STOCK' },
    { asset: 'MELI', local: false, peso: 0.3, tipo: 'STOCK' },
    { asset: 'AAPL', local: false, peso: 0.15, tipo: 'STOCK' },
    { asset: 'KO', local: false, peso: 0.05, tipo: 'STOCK' },
  ],
  seguidos: [{ symbol: 'BA' }],
  indice: indexarLecturas(['YPF', 'MELI', 'AAPL', 'KO', 'BA'].map(a => lec(a))),
})

describe('D5: Tu lista', () => {
  it('«por peso» sin el ojito: de más a menos; con el ojito, lo tuyo primero y de la A a la Z', () => {
    expect(ordenarFilas(FILAS, 'peso').map(f => f.nombre)).toEqual(['YPF', 'MELI', 'AAPL', 'KO', 'BA'])
    expect(ordenarFilas(FILAS, 'peso', null, true).map(f => f.nombre)).toEqual(['AAPL', 'KO', 'MELI', 'YPF', 'BA'])
    // Dar vuelta el sentido con el ojito tampoco dice nada del peso.
    expect(ordenarFilas(FILAS, 'peso', false, true).map(f => f.nombre)).toEqual(['AAPL', 'KO', 'MELI', 'YPF', 'BA'])
  })

  const dibujar = (oculto) => texto(renderToStaticMarkup(
    <MemoryRouter><ListaTecnica filas={FILAS} oculto={oculto} vista="tarjetas" /></MemoryRouter>))

  it('el «Ordenar por» no promete «mayor peso» con el ojito (el valor elegido sigue en la lista)', () => {
    expect(dibujar(false)).toContain('Mayor peso en tu cartera')
    const t = dibujar(true)
    expect(t).not.toContain('Mayor peso')
    expect(t).toContain('Tu cartera primero')
  })

  it('la franja nombra «en su máximo» de la A a la Z con el ojito', () => {
    // Los 5 están en su máximo: la franja nombra 2 «y 3 más».
    expect(dibujar(false)).toContain('YPF, MELI y 3 más')
    expect(dibujar(true)).toContain('AAPL, BA y 3 más')
  })
})

describe('D6: el botón «Comparar» del análisis técnico', () => {
  it('sin el ojito, tus 4 que más pesan; con el ojito, los 4 primeros de la A a la Z', () => {
    expect(urlDeCompararTuyos(FILAS)).toBe('/fundamentals?vista=precio&cmp=YPF,MELI,AAPL,KO')
    const masDeCuatro = [...FILAS, { ...FILAS[0], clave: 'ZZZ|0', nombre: 'ZZZ', ruta: 'ZZZ', peso: 90 }]
    expect(urlDeCompararTuyos(masDeCuatro)).toBe('/fundamentals?vista=precio&cmp=ZZZ,YPF,MELI,AAPL')
    expect(urlDeCompararTuyos(masDeCuatro, true)).toBe('/fundamentals?vista=precio&cmp=AAPL,KO,MELI,YPF')
  })
})

describe('las que ya lo hacían, ahora con el mismo ayudante', () => {
  it('el mapa: con el ojito sin peso y de la A a la Z', () => {
    expect(cuadritosDelMapa(FILAS).map(c => c.nombre)).toEqual(['YPF', 'MELI', 'AAPL', 'KO'])
    const oculto = cuadritosDelMapa(FILAS, { hidden: true })
    expect(oculto.map(c => c.nombre)).toEqual(['AAPL', 'KO', 'MELI', 'YPF'])
    expect(oculto.every(c => c.peso == null)).toBe(true)
  })

  it('Señales: con el ojito, por día, lo tuyo primero y por nombre', () => {
    const s = (asset, fecha, tenes = true) => ({ asset, fecha, tenes })
    const delServidor = [s('YPF', '2026-10-30'), s('AAPL', '2026-10-30'), s('BA', '2026-10-30', false), s('KO', '2026-10-29')]
    expect(enOrden(delServidor, false)).toBe(delServidor)
    expect(enOrden(delServidor, true).map(x => x.asset)).toEqual(['AAPL', 'YPF', 'BA', 'KO'])
  })
})
