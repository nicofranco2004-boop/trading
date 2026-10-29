// «Tu lista, con su lectura técnica»: las cuentas de la tabla (utils/listaTecnica.js).
// Lo que importa: cada palabra es la de la ficha, cuánto pesa cada activo es su
// pedazo del total de la Cartera (el mismo motor), lo que seguís se lee con la
// regla de la ficha y lo que no tiene lectura lo dice en vez de inventar.
import { describe, it, expect, beforeEach } from 'vitest'
import {
  lecturaDeSeguido, activosDeLaLista, filasDeLaLista, contarFilas, filtrarFilas, ordenarFilas,
  haceCuanto, trazoDeLinea, motivosSinLectura,
} from './listaTecnica'
import { indexarLecturas, radiografia, MOTIVOS_SIN_LECTURA } from './radiografia'
import { computeBrokerValue, setBrokersRegistry } from './valuation'
import { tarjetas, veredictoRsi } from './tecnico'

const BROKERS = [
  { id: 1, name: 'IOL', currency: 'ARS' },
  { id: 2, name: 'Schwab', currency: 'USD' },
]
beforeEach(() => setBrokersRegistry(BROKERS))

const HOY = '2026-10-24'
// Lecturas como las devuelve POST /api/tecnico/lista.
const lec = (asset, local, l = {}, extra = {}) => ({
  asset, local, disponible: true,
  lectura: { ruedas: 760, fecha: '2026-10-23', media200: 90, dist_media200: 11.1, pendiente_media200: 2,
    media50: 95, dist_media50: 5, rsi: 64, adx: 27.4, dist_maximo_12m: -3.2, anio_completo: true, ...l },
  linea: [{ d: '2026-07-24', c: 90 }, { d: '2026-09-01', c: 95 }, { d: '2026-10-23', c: 100 }],
  ultimo_cambio: null, ...extra,
})

describe('lo que seguís se lee con la regla de la ficha', () => {
  it('acción argentina en BYMA, CEDEAR por su acción de afuera, cripto sin -USD', () => {
    expect(lecturaDeSeguido('GGAL.BA')).toEqual({ asset: 'GGAL', local: true, simbolo: 'GGAL.BA' })
    expect(lecturaDeSeguido('PAMP')).toMatchObject({ asset: 'PAMP', local: true })
    expect(lecturaDeSeguido('AAPL.BA')).toMatchObject({ asset: 'AAPL', local: false })
    expect(lecturaDeSeguido('TSLA')).toMatchObject({ asset: 'TSLA', local: false })
    expect(lecturaDeSeguido('BTC-USD')).toMatchObject({ asset: 'BTC', local: false })
  })

  it('pide cada activo una vez: el CEDEAR que tenés y seguís es uno; el ADR y la acción local, dos', () => {
    const lotes = [
      { id: 1, broker: 'IOL', asset: 'AAPL', asset_type: 'CEDEAR' },
      { id: 2, broker: 'Schwab', asset: 'GGAL', asset_type: 'STOCK' },
      { id: 3, broker: 'IOL', asset: 'ARS', is_cash: true },
    ]
    expect(activosDeLaLista(lotes, [{ symbol: 'AAPL.BA' }, { symbol: 'GGAL.BA' }, { symbol: 'TSLA' }])).toEqual([
      { asset: 'AAPL', local: false }, { asset: 'GGAL', local: false }, { asset: 'GGAL', local: true },
      { asset: 'TSLA', local: false },
    ])
  })
})

describe('las filas, con la valuación de la Cartera', () => {
  const POS = [
    { id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
    { id: 2, broker: 'Schwab', asset: 'KO', asset_type: 'STOCK', quantity: 10, invested: 600, buy_price: 60 },
    { id: 3, broker: 'Schwab', asset: 'USD', is_cash: true, quantity: 500, invested: 500 },
    { id: 4, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
    { id: 5, broker: 'IOL', asset: 'AL30', asset_type: 'BONO', quantity: 100, invested: 50000, buy_price: 500 },
  ]
  const PRICES = { NVDA: 150, KO: 50, 'AL30.BA': 500 }
  const totales = BROKERS.map(b => computeBrokerValue(POS, PRICES, b, 1000, 1000))
  const valorDe = p => totales.find((r, i) => BROKERS[i].name === p.broker).porLote.get(p.id) ?? 0
  const extra = [{ nombre: 'plazos fijos', valor: 1000 }]
  const indice = indexarLecturas([
    lec('NVDA', false),
    lec('KO', false, { dist_media200: -9.1, media200: 110, dist_media50: -4.8, rsi: 24, adx: 18.2, dist_maximo_12m: -24.3 }),
    lec('TSLA', false, { rsi: 71, dist_maximo_12m: 0 }),
    { asset: 'AL30', local: true, disponible: false },
  ])
  const seguidos = [{ symbol: 'TSLA' }, { symbol: 'NVDA' }, { symbol: 'AL29' }]
  const filas = filasDeLaLista({ lotes: POS, valorDe, extra, seguidos, indice, hoy: HOY })
  const de = (n) => filas.find(f => f.nombre === n)

  it('cuánto pesa cada uno es su pedazo del mismo total que la radiografía', () => {
    const r = radiografia(POS, valorDe, indice, extra, HOY)
    expect(de('NVDA').valor).toBeCloseTo(3000, 9)
    expect(de('NVDA').peso).toBeCloseTo((3000 / r.total) * 100, 9)
    expect(de('KO').peso).toBeCloseTo((500 / r.total) * 100, 9)
    // El efectivo y los plazos fijos suman al total pero no son filas.
    expect(filas.map(f => f.nombre).sort()).toEqual(['AL29', 'AL30', 'KO', 'NVDA', 'TSLA'])
  })

  it('lo que tenés y además seguís va una vez, como «lo tenés»; los filtros cuentan', () => {
    expect(de('NVDA').tenes).toBe(true)
    expect(de('TSLA')).toMatchObject({ tenes: false, peso: 0, ruta: 'TSLA' })
    expect(contarFilas(filas)).toEqual({ todo: 5, tenes: 3, watchlist: 2 })
    expect(filtrarFilas(filas, 'watchlist').map(f => f.nombre).sort()).toEqual(['AL29', 'TSLA'])
  })

  it('las palabras son las de la ficha', () => {
    const ko = de('KO')
    expect(ko.fondo.palabra).toBe(tarjetas(indice.get('KO|0').lectura).find(t => t.id === 'fondo').veredicto)
    expect(ko.corto.palabra).toBe('Bajista')
    expect(ko.rsi).toEqual({ rsi: 24, palabra: veredictoRsi(24) })
    expect(ko.adx).toEqual({ valor: 18.2, texto: '18', palabra: 'de costado' })
    expect(de('NVDA').adx.palabra).toBe('marcada')
    expect(de('TSLA').desdeMax.enMaximo).toBe(true)
    expect(ko.desdeMax).toMatchObject({ pct: -24.3, enMaximo: false })
  })

  it('el ADX justo en 23 ya es «marcada» (la línea de la ficha: 23 o más)', () => {
    const f = filasDeLaLista({ lotes: [], valorDe, seguidos: [{ symbol: 'X' }], indice: indexarLecturas([lec('X', false, { adx: 23 })]), hoy: HOY })
    expect(f[0].adx.palabra).toBe('marcada')
    const g = filasDeLaLista({ lotes: [], valorDe, seguidos: [{ symbol: 'X' }], indice: indexarLecturas([lec('X', false, { adx: 22.96 })]), hoy: HOY })
    expect(g[0].adx).toMatchObject({ texto: '22,9', palabra: 'de costado' })
  })

  it('bono, fondo o sin velas: «Sin lectura» con su motivo, sin números', () => {
    for (const n of ['AL30', 'AL29']) {
      expect(de(n)).toMatchObject({ vigente: false, porque: 'no_se_mide', rsi: null, adx: null, desdeMax: null, linea: null, cambio: null })
      expect(de(n).fondo.palabra).toBe('Sin lectura')
    }
    expect(motivosSinLectura(filas)).toEqual([{ porque: 'no_se_mide', nombres: ['AL30', 'AL29'], texto: MOTIVOS_SIN_LECTURA.no_se_mide }])
  })

  it('una acción de la watchlist todavía sin velas: aparece en un día', () => {
    const f = filasDeLaLista({ lotes: [], valorDe, seguidos: [{ symbol: 'IREN' }], indice: new Map(), hoy: HOY })
    expect(f[0]).toMatchObject({ vigente: false, porque: 'sin_historia' })
  })

  it('velas de hace más de 10 días: sin lectura, con su fecha, y sin último cambio', () => {
    const vieja = lec('MSFT', false, { fecha: '2026-10-10' }, { ultimo_cambio: { fecha: '2026-10-08', texto: 'pasó arriba de su promedio de 50 días: el corto plazo se volvió alcista.' } })
    const f = filasDeLaLista({ lotes: [], valorDe, seguidos: [{ symbol: 'MSFT' }], indice: indexarLecturas([vieja]), hoy: HOY })
    expect(f[0]).toMatchObject({ vigente: false, porque: 'vieja', rsi: null, adx: null, cambio: null })
    expect(f[0].motivo).toContain('10/10/2026')
    // El fin de semana largo sigue siendo de hoy.
    const finde = filasDeLaLista({ lotes: [], valorDe, seguidos: [{ symbol: 'MSFT' }], indice: indexarLecturas([lec('MSFT', false, { fecha: '2026-10-16' })]), hoy: HOY })
    expect(finde[0].vigente).toBe(true)
  })

  it('el último cambio: el de la cuenta única, con hace cuánto', () => {
    // Como lo manda el servidor: cambios_desde + senales_semana.texto_del_cambio.
    const x = lec('TSLA', false, {}, { ultimo_cambio: {
      tipo: 'media50', sentido: 'abajo', fecha: '2026-10-21', etiqueta: 'Corto plazo', tono: 'neg',
      texto: 'quedó abajo de su promedio de 50 días: el corto plazo se volvió bajista.', extra: null } })
    const f = filasDeLaLista({ lotes: [], valorDe, seguidos: [{ symbol: 'TSLA' }], indice: indexarLecturas([x]), hoy: HOY })
    expect(f[0].cambio).toEqual({
      corta: 'Quedó abajo de su promedio de 50 días',
      completa: 'Quedó abajo de su promedio de 50 días: el corto plazo se volvió bajista.',
      tono: 'neg', fecha: '2026-10-21', hace: 'hace 3 días',
    })
    // La aclaración de «cayó muy rápido» (la posibilidad de rebote) va al globo.
    const rsi = lec('KO', false, {}, { ultimo_cambio: {
      tipo: 'rsi_bajo_30', fecha: '2026-10-23', tono: 'rsi', texto: 'tiene la fuerza (RSI) en 25.', extra: 'Es una posibilidad, no una certeza.' } })
    const g = filasDeLaLista({ lotes: [], valorDe, seguidos: [{ symbol: 'KO' }], indice: indexarLecturas([rsi]), hoy: HOY })
    expect(g[0].cambio).toMatchObject({ corta: 'Tiene la fuerza (RSI) en 25', completa: 'Tiene la fuerza (RSI) en 25. Es una posibilidad, no una certeza.', hace: 'ayer' })
  })

  it('dos filas con el mismo ticker dicen dónde cotiza cada una', () => {
    const lotes = [
      { id: 1, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION' },
      { id: 2, broker: 'Schwab', asset: 'GGAL', asset_type: 'STOCK' },
      { id: 3, broker: 'Schwab', asset: 'KO', asset_type: 'STOCK' },
    ]
    const f = filasDeLaLista({ lotes, valorDe: () => 100, seguidos: [{ symbol: 'BTC-USD' }], indice: new Map(), hoy: HOY })
    const por = Object.fromEntries(f.map(x => [x.clave, x]))
    expect(por['GGAL|1'].detalle).toBe('en BYMA')
    expect(por['GGAL|0'].detalle).toBe('en Nueva York')
    expect(por['KO|0'].detalle).toBeUndefined()
    expect(por['BTC|0'].nombre).toBe('BTC')
  })
})

describe('el orden', () => {
  const f = (nombre, o) => ({ nombre, vigente: true, tenes: false, peso: 0, rsi: null, desdeMax: null, cambio: null, ...o })
  const filas = [
    f('A', { cambio: { fecha: '2026-10-01' }, rsi: { rsi: 40 }, desdeMax: { pct: -20 }, tenes: true, peso: 10 }),
    f('B', { cambio: { fecha: '2026-10-22' }, rsi: { rsi: 71 }, desdeMax: { pct: 0 }, tenes: true, peso: 30 }),
    f('C', { rsi: { rsi: 25 }, desdeMax: { pct: -5 } }),
    f('Z', { vigente: false, tenes: true, peso: 50 }),
  ]
  const nombres = (fs) => fs.map(x => x.nombre)

  it('lo último que cambió primero; sin cambio, al final; sin lectura, al final de todo', () => {
    expect(nombres(ordenarFilas(filas, 'cambio'))).toEqual(['B', 'A', 'C', 'Z'])
    expect(nombres(ordenarFilas(filas, 'cambio', false))).toEqual(['A', 'B', 'C', 'Z'])
  })
  it('fuerza, desde el máximo y lo que más pesa', () => {
    expect(nombres(ordenarFilas(filas, 'fuerza'))).toEqual(['B', 'A', 'C', 'Z'])
    expect(nombres(ordenarFilas(filas, 'maximo'))).toEqual(['B', 'C', 'A', 'Z'])
    expect(nombres(ordenarFilas(filas, 'maximo', false))).toEqual(['A', 'C', 'B', 'Z'])
    // Lo que más pesa: un bono sin lectura pesa igual; lo que sólo seguís, al final.
    expect(nombres(ordenarFilas(filas, 'peso'))).toEqual(['Z', 'B', 'A', 'C'])
  })
})

describe('hace cuánto y la línea chica', () => {
  it('dice el tiempo como se habla', () => {
    expect(haceCuanto('2026-10-24', HOY)).toBe('hoy')
    expect(haceCuanto('2026-10-23', HOY)).toBe('ayer')
    expect(haceCuanto('2026-10-20', HOY)).toBe('hace 4 días')
    expect(haceCuanto('2026-10-03', HOY)).toBe('hace 3 semanas')
    expect(haceCuanto('2026-05-24', HOY)).toBe('hace 5 meses')
    expect(haceCuanto('2025-10-24', HOY)).toBe('hace un año')
    expect(haceCuanto(null, HOY)).toBeNull()
  })
  it('la línea va del mínimo al máximo de los 3 meses y dice si terminó arriba', () => {
    const t = trazoDeLinea([{ c: 10 }, { c: 5 }, { c: 8 }])
    expect(t.d).toBe('M0.0,1.0L32.0,21.0L64.0,9.0')   // 10 arriba, 5 abajo, 8 al 60 %
    expect(t.sube).toBe(false)
    expect(trazoDeLinea([{ c: 1 }])).toBeNull()
  })
})
