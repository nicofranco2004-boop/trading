// «Tu lista, con su lectura técnica»: las cuentas de la tabla (utils/listaTecnica.js).
// Lo que importa: cada palabra es la de la ficha, cuánto pesa cada activo es su
// pedazo del total de la Cartera (el mismo motor), lo que seguís se lee con la
// regla de la ficha y lo que no tiene lectura lo dice en vez de inventar.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  lecturaDeSeguido, activosDeLaLista, filasDeLaLista, contarFilas, filtrarFilas, ordenarFilas,
  haceCuanto, trazoDeLinea, motivosSinLectura,
  barrasDeFuerza, resumenDeLaLista, vistaGuardada, guardarVista, nombreDeActivo, DIAS_SEMANA, dondeEstaEnLaLista,
} from './listaTecnica'
import { indexarLecturas, MOTIVOS_SIN_LECTURA } from './radiografia'
import { setBrokersRegistry } from './valuation'
import { tarjetas, veredictoRsi, ADX_CLAVE, RSI_GANA, RSI_PIERDE } from './tecnico'

const BROKERS = [
  { id: 1, name: 'IOL', currency: 'ARS' },
  { id: 2, name: 'Schwab', currency: 'USD' },
]
beforeEach(() => setBrokersRegistry(BROKERS))

const HOY = '2026-10-24'
// Lecturas como las devuelve POST /api/tecnico/lista.
const lec = (asset, local, l = {}, extra = {}) => ({
  asset, local, disponible: true,
  lectura: { ruedas: 760, fecha: '2026-10-23', media200: 90, dist_media200: 11.1, tendencia: 'alcista', pendiente_media200: 2,
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

  it('pide lo que seguís, cada uno una vez (lo que tenés lo pone el servidor)', () => {
    expect(activosDeLaLista([{ symbol: 'AAPL.BA' }, { symbol: 'GGAL.BA' }, { symbol: 'TSLA' }, { symbol: 'GGAL' }])).toEqual([
      { asset: 'AAPL', local: false }, { asset: 'GGAL', local: true }, { asset: 'TSLA', local: false },
    ])
  })
})

describe('las filas, con lo que manda el servidor', () => {
  // `tenencias` de POST /api/tecnico/lista: lo que tenés y su peso sobre toda
  // tu plata (senales_semana.cartera, la misma valuación del % y de Señales).
  const TENENCIAS = [
    { asset: 'NVDA', local: false, peso: 0.5, tipo: 'STOCK' },
    { asset: 'KO', local: false, peso: 0.25, tipo: 'STOCK' },
    { asset: 'AL30', local: true, peso: 0.004, tipo: 'BONO' },
  ]
  const indice = indexarLecturas([
    lec('NVDA', false),
    lec('KO', false, { dist_media200: -9.1, tendencia: 'bajista', media200: 110, dist_media50: -4.8, rsi: 24, adx: 18.2, dist_maximo_12m: -24.3 }),
    lec('TSLA', false, { rsi: 71, dist_maximo_12m: 0 }),
    { asset: 'AL30', local: true, disponible: false },
  ])
  const seguidos = [{ symbol: 'TSLA' }, { symbol: 'NVDA' }, { symbol: 'AL29' }]
  const filas = filasDeLaLista({ tenencias: TENENCIAS, seguidos, indice, hoy: HOY })
  const de = (n) => filas.find(f => f.nombre === n)

  it('cuánto pesa cada uno es lo que dice el servidor, sin recalcular', () => {
    expect(de('NVDA').peso).toBeCloseTo(50, 9)
    expect(de('KO').peso).toBeCloseTo(25, 9)
    expect(de('AL30').peso).toBeCloseTo(0.4, 9)
    // El efectivo y los plazos fijos suman al total del servidor pero no son filas.
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
    expect(ko.adx).toEqual({ valor: 18.2, texto: '18', palabra: 'lateral' })
    expect(de('NVDA').adx.palabra).toBe('marcada')
    expect(de('TSLA').desdeMax.enMaximo).toBe(true)
    expect(ko.desdeMax).toMatchObject({ pct: -24.3, enMaximo: false })
  })

  it('el ADX justo en 23 ya es «marcada» (la línea de la ficha: 23 o más)', () => {
    const f = filasDeLaLista({ seguidos: [{ symbol: 'X' }], indice: indexarLecturas([lec('X', false, { adx: 23 })]), hoy: HOY })
    expect(f[0].adx.palabra).toBe('marcada')
    const g = filasDeLaLista({ seguidos: [{ symbol: 'X' }], indice: indexarLecturas([lec('X', false, { adx: 22.96 })]), hoy: HOY })
    expect(g[0].adx).toMatchObject({ texto: '22,9', palabra: 'lateral' })
  })

  it('bono, fondo o sin velas: «Sin lectura» con su motivo, sin números', () => {
    for (const n of ['AL30', 'AL29']) {
      expect(de(n)).toMatchObject({ vigente: false, porque: 'no_se_mide', rsi: null, adx: null, desdeMax: null, linea: null, cambio: null })
      expect(de(n).fondo.palabra).toBe('Sin lectura')
    }
    expect(motivosSinLectura(filas)).toEqual([{ porque: 'no_se_mide', nombres: ['AL30', 'AL29'], texto: MOTIVOS_SIN_LECTURA.no_se_mide }])
  })

  it('una acción de la watchlist todavía sin velas: va a aparecer mañana', () => {
    const f = filasDeLaLista({ seguidos: [{ symbol: 'IREN' }], indice: new Map(), hoy: HOY })
    expect(f[0]).toMatchObject({ vigente: false, porque: 'sin_historia' })
  })

  it('velas de hace más de 10 días: sin lectura, con su fecha, y sin último cambio', () => {
    const vieja = lec('MSFT', false, { fecha: '2026-10-10' }, { ultimo_cambio: { fecha: '2026-10-08', texto: 'superó su promedio de 50 días: la tendencia de mediano plazo pasó a ser alcista.' } })
    const f = filasDeLaLista({ seguidos: [{ symbol: 'MSFT' }], indice: indexarLecturas([vieja]), hoy: HOY })
    expect(f[0]).toMatchObject({ vigente: false, porque: 'vieja', rsi: null, adx: null, cambio: null })
    expect(f[0].motivo).toContain('10/10/2026')
    // El fin de semana largo sigue siendo de hoy.
    const finde = filasDeLaLista({ seguidos: [{ symbol: 'MSFT' }], indice: indexarLecturas([lec('MSFT', false, { fecha: '2026-10-16' })]), hoy: HOY })
    expect(finde[0].vigente).toBe(true)
  })

  it('el último cambio: el de la cuenta única, con hace cuánto', () => {
    // Como lo manda el servidor: cambios_desde + senales_semana.texto_del_cambio.
    const x = lec('TSLA', false, {}, { ultimo_cambio: {
      tipo: 'media50', sentido: 'abajo', fecha: '2026-10-21', etiqueta: 'Mediano plazo', tono: 'neg',
      texto: 'cayó por debajo de su promedio de 50 días: la tendencia de mediano plazo pasó a ser bajista.', extra: null } })
    const f = filasDeLaLista({ seguidos: [{ symbol: 'TSLA' }], indice: indexarLecturas([x]), hoy: HOY })
    expect(f[0].cambio).toEqual({
      corta: 'Cayó por debajo de su promedio de 50 días',
      completa: 'Cayó por debajo de su promedio de 50 días: la tendencia de mediano plazo pasó a ser bajista.',
      tono: 'neg', fecha: '2026-10-21', hace: 'hace 3 días',
    })
    // La aclaración de «cayó muy rápido» (la posibilidad de rebote) va al globo.
    const rsi = lec('KO', false, {}, { ultimo_cambio: {
      tipo: 'rsi_bajo_30', fecha: '2026-10-23', tono: 'rsi', corta: 'cayó muy rápido',
      texto: 'cayó muy rápido: el impulso (RSI) bajó de 30 y quedó en 25.', extra: 'Es una posibilidad, no una certeza.' } })
    const g = filasDeLaLista({ seguidos: [{ symbol: 'KO' }], indice: indexarLecturas([rsi]), hoy: HOY })
    expect(g[0].cambio).toMatchObject({ corta: 'Cayó muy rápido', completa: 'Cayó muy rápido: el impulso (RSI) bajó de 30 y quedó en 25. Es una posibilidad, no una certeza.', hace: 'ayer' })
  })

  it('D6: la celda usa la frase corta del servidor, sin jerga (antes «Tiene el ADX en 23,3»)', () => {
    const adx = lec('KO', false, {}, { ultimo_cambio: {
      tipo: 'adx23', fecha: '2026-10-23', tono: 'adx', corta: 'dejó de moverse de forma lateral y tomó una dirección (al alza)',
      texto: 'dejó de moverse de forma lateral y tomó una dirección (al alza): la fuerza de la tendencia (ADX) superó 23 y quedó en 23,3.' } })
    const g = filasDeLaLista({ seguidos: [{ symbol: 'KO' }], indice: indexarLecturas([adx]), hoy: HOY })
    expect(g[0].cambio.corta).toBe('Dejó de moverse de forma lateral y tomó una dirección (al alza)')
    expect(g[0].cambio.corta).not.toMatch(/ADX|\d/)
  })

  it('dos filas con el mismo ticker dicen dónde cotiza cada una', () => {
    const tenencias = [
      { asset: 'GGAL', local: true, peso: 0.3, tipo: 'ACCION' },
      { asset: 'GGAL', local: false, peso: 0.2, tipo: 'STOCK' },
      { asset: 'KO', local: false, peso: 0.1, tipo: 'STOCK' },
    ]
    const f = filasDeLaLista({ tenencias, seguidos: [{ symbol: 'BTC-USD' }], indice: new Map(), hoy: HOY })
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
    // Mayor peso en tu cartera: un bono sin lectura pesa igual; lo que sólo seguís, al final.
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

describe('las tarjetas de Tu lista', () => {
  it('la Fuerza: cada barrita es media línea del ADX; desde la tercera, dirección marcada', () => {
    expect(barrasDeFuerza(null)).toBeNull()
    expect(barrasDeFuerza(5)).toEqual({ prendidas: 1, clara: false })
    expect(barrasDeFuerza(ADX_CLAVE - 0.1)).toEqual({ prendidas: 2, clara: false })
    expect(barrasDeFuerza(ADX_CLAVE)).toEqual({ prendidas: 3, clara: true })
    expect(barrasDeFuerza(90)).toEqual({ prendidas: 5, clara: true })
  })

  it('los cortes del impulso son los de la ficha (veredictoRsi), no números nuevos', () => {
    expect(veredictoRsi(RSI_GANA + 0.1)).toBe('Gana impulso')
    expect(veredictoRsi(RSI_GANA)).toBe('Sin impulso claro')
    expect(veredictoRsi(RSI_PIERDE - 0.1)).toBe('Pierde impulso')
  })

  it('el nombre de la empresa; una acción argentina con el de BYMA', () => {
    expect(nombreDeActivo('NVDA')).toBe('NVIDIA')
    expect(nombreDeActivo('GGAL', true)).toBe('Grupo Financiero Galicia')
    expect(nombreDeActivo('ZZZZ')).toBeNull()
  })

  it('cada fila trae su precio, cuánto cambió en 3 meses y si cambió esta semana', () => {
    const hace = (n) => new Date(Date.parse(HOY + 'T00:00:00Z') - n * 86400000).toISOString().slice(0, 10)
    const x = (asset, fecha) => ({ asset, local: false, disponible: true,
      lectura: { ruedas: 760, fecha: HOY, precio: 150, media200: 90, dist_media200: 10, tendencia: 'alcista', rsi: 60, adx: 30 },
      linea: [{ d: hace(90), c: 100 }, { d: HOY, c: 150 }], ultimo_cambio: { tipo: 'media200', fecha, texto: 'superó su promedio.' } })
    const filas = filasDeLaLista({
      seguidos: [{ symbol: 'AAA' }, { symbol: 'BBB' }], hoy: HOY,
      indice: indexarLecturas([x('AAA', hace(DIAS_SEMANA - 1)), x('BBB', hace(DIAS_SEMANA))]),
    })
    const [a, b] = filas
    expect(a.precio).toBe(150)
    expect(a.var3m).toBeCloseTo(50)
    expect(a.nuevo).toBe(true)
    expect(b.nuevo).toBe(false)          // hace 7 días ya no es «esta semana» (la de Señales)
  })

  it('la franja cuenta activos, nunca plata', () => {
    const f = (fondo, extra = {}) => ({ fondo: { id: fondo }, vigente: fondo !== 'sin', nombre: extra.nombre || fondo, ...extra })
    const r = resumenDeLaLista([
      f('alcista', { rsi: { rsi: 60 }, nuevo: true }),
      f('alcista', { rsi: { rsi: RSI_GANA }, desdeMax: { enMaximo: true }, nombre: 'NVDA' }),
      f('bajista', { rsi: { rsi: 20 } }),
      f('sin'),
    ])
    expect(r).toEqual({ alcistas: 2, conLectura: 3, puntos: ['alcista', 'alcista', 'bajista'], ganando: 1, enMaximo: ['NVDA'], cambiaron: 1 })
  })

  it('el promedio de 200 días va en la MISMA escala que el precio, y corta donde no hay', () => {
    // Precio de 10 a 20, promedio en 30: la escala se estira hasta 30 para que el
    // promedio quede arriba de la línea (el precio está abajo de su promedio).
    const t = trazoDeLinea([{ c: 10, m: null }, { c: 20, m: 30 }, { c: 15, m: 30 }], 100, 22, { promedio: true })
    expect(t.ma).toBe('M50.0,1.0L100.0,1.0')
    expect(t.d).toBe('M0.0,21.0L50.0,11.0L100.0,16.0')
    expect(trazoDeLinea([{ c: 1 }, { c: 2 }], 100, 22, { promedio: true }).ma).toBeNull()
    expect(trazoDeLinea([{ c: 1, m: 5 }, { c: 2, m: 5 }]).ma).toBeNull()   // la de la tabla no lo dibuja
  })

  it('el mini-gráfico trae el relleno de abajo de la línea', () => {
    const t = trazoDeLinea([{ c: 1 }, { c: 2 }], 300, 70)
    expect(t.area.startsWith(t.d)).toBe(true)
    expect(t.area.endsWith('L300,70L0,70Z')).toBe(true)
  })
})

describe('«Tarjetas / Tabla» se recuerda por persona en el navegador', () => {
  afterEach(() => { vi.unstubAllGlobals() })
  const memoria = () => {
    const m = new Map()
    return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }
  }

  it('de entrada, tarjetas; lo que elige uno no lo ve otro', () => {
    vi.stubGlobal('localStorage', memoria())
    expect(vistaGuardada('7:propia')).toBe('tarjetas')
    guardarVista('7:propia', 'tabla')
    expect(vistaGuardada('7:propia')).toBe('tabla')
    expect(vistaGuardada('8:propia')).toBe('tarjetas')
    expect(vistaGuardada('7:cliente:3')).toBe('tarjetas')
  })

  it('sin nadie logueado no se guarda; sin almacenamiento (o roto), tarjetas sin romper', () => {
    const m = memoria()
    vi.stubGlobal('localStorage', m)
    guardarVista(null, 'tabla')
    expect(vistaGuardada(null)).toBe('tarjetas')
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('bloqueado') }, setItem: () => { throw new Error('bloqueado') } })
    expect(() => guardarVista('7:propia', 'tabla')).not.toThrow()
    expect(vistaGuardada('7:propia')).toBe('tarjetas')
  })
})

describe('¿ya está en tu lista? (el buscador de «Tu lista» avisa en vez de duplicar)', () => {
  // Con la MISMA regla con que la lista junta lo que tenés y lo que seguís.
  const filas = filasDeLaLista({
    tenencias: [{ asset: 'GGAL', local: true, peso: 0.5, tipo: 'STOCK' }, { asset: 'MELI', local: false, peso: 0.5, tipo: 'STOCK' }],
    seguidos: [{ symbol: 'TSLA' }, { symbol: 'BTC-USD' }],
    indice: indexarLecturas([]),
  })

  it('lo que tenés, lo que seguís y lo que no está', () => {
    expect(dondeEstaEnLaLista(filas, 'MELI')).toBe('cartera')
    expect(dondeEstaEnLaLista(filas, 'tsla')).toBe('watchlist')
    expect(dondeEstaEnLaLista(filas, 'KO')).toBeNull()
    expect(dondeEstaEnLaLista(filas, '')).toBeNull()
  })

  it('con otro nombre del mismo papel: GGAL.BA es tu GGAL de BYMA; BTC es tu BTC-USD', () => {
    expect(dondeEstaEnLaLista(filas, 'GGAL.BA')).toBe('cartera')
    expect(dondeEstaEnLaLista(filas, 'BTC')).toBe('watchlist')
  })
})

describe('un bono que tenés y seguís es UNA fila (revisión del 02/11)', () => {
  // El servidor marca tu AL30 de IOL como de BYMA (local); lo que seguís sólo
  // es de BYMA si es una acción argentina. Eran dos filas del mismo bono.
  const tenencias = [{ asset: 'AL30', local: true, peso: 1, tipo: 'BONO' }]

  it('el buscador lo reconoce como tuyo, con o sin «.BA»', () => {
    const filas = filasDeLaLista({ tenencias, seguidos: [], indice: indexarLecturas([]) })
    expect(dondeEstaEnLaLista(filas, 'AL30')).toBe('cartera')
    expect(dondeEstaEnLaLista(filas, 'AL30.BA')).toBe('cartera')
  })

  it('si igual lo seguís, no aparece dos veces', () => {
    const filas = filasDeLaLista({ tenencias, seguidos: [{ symbol: 'AL30' }], indice: indexarLecturas([]) })
    expect(filas.map(f => f.clave)).toEqual(['AL30|1'])
  })

  it('una acción sigue separando mercados: el ADR no es tu GGAL de BYMA', () => {
    const filas = filasDeLaLista({ tenencias: [{ asset: 'GGAL', local: true, peso: 1, tipo: 'STOCK' }], seguidos: [], indice: indexarLecturas([]) })
    expect(dondeEstaEnLaLista(filas, 'GGAL.BA')).toBe('cartera')
  })
})
