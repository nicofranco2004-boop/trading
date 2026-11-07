import { describe, it, expect, beforeEach } from 'vitest'
import {
  esLoteLocal, esAccionLocal, activosParaLeer, indexarLecturas, lecturaDeFila, tendencia, fuerza,
  lecturaVieja, MOTIVOS_SIN_LECTURA,
} from './radiografia'
import { lecturaDeLaFila } from '../components/RadiografiaTecnica'
import { setBrokersRegistry } from './valuation'
import { tarjetas, veredictoRsi } from './tecnico'

const BROKERS = [
  { id: 1, name: 'IOL', currency: 'ARS' },
  { id: 2, name: 'Schwab', currency: 'USD' },
]
beforeEach(() => setBrokersRegistry(BROKERS))

// Lecturas como las devuelve POST /api/tecnico/cartera.
const lec = (asset, local, l, cambios = []) => ({ asset, local, disponible: true, lectura: { ruedas: 760, ...l }, cambios })
const ALCISTA = { media200: 90, dist_media200: 11.1, tendencia: 'alcista', pendiente_media200: 2, media50: 95, dist_media50: 5, rsi: 64 }
const BAJISTA = { media200: 110, dist_media200: -9.1, tendencia: 'bajista', pendiente_media200: -1, media50: 105, dist_media50: -4.8, rsi: 38 }

describe('la marca local (acción argentina)', () => {
  it('es la regla de la ficha, lote por lote', () => {
    expect(esLoteLocal({ asset: 'GGAL', asset_type: 'ACCION', broker: 'IOL' })).toBe(true)
    expect(esLoteLocal({ asset: 'AAPL', asset_type: 'CEDEAR', broker: 'IOL' })).toBe(false)
    expect(esLoteLocal({ asset: 'BTC', asset_type: 'CRYPTO', broker: 'IOL' })).toBe(false)
    expect(esLoteLocal({ asset: 'GGAL', asset_type: 'STOCK', broker: 'Schwab' })).toBe(false)
    expect(esLoteLocal({ asset: 'ARS', is_cash: true, broker: 'IOL' })).toBe(false)
    expect(esAccionLocal('GGAL', [{ asset: 'GGAL', asset_type: 'ACCION', broker: 'IOL' }])).toBe(true)
    expect(esAccionLocal('GGAL', [])).toBe(false)
  })

  it('pide cada activo una vez, sin el efectivo, y separa la acción local del ADR', () => {
    const pedido = activosParaLeer([
      { asset: 'AAPL', asset_type: 'CEDEAR', broker: 'IOL' },
      { asset: 'AAPL', asset_type: 'STOCK', broker: 'Schwab' },
      { asset: 'GGAL', asset_type: 'ACCION', broker: 'IOL' },
      { asset: 'GGAL', asset_type: 'STOCK', broker: 'Schwab' },
      { asset: 'ARS', is_cash: true, broker: 'IOL' },
    ])
    expect(pedido).toEqual([
      { asset: 'AAPL', local: false }, { asset: 'GGAL', local: false }, { asset: 'GGAL', local: true },
    ])
  })
})

describe('las palabras son las de la ficha', () => {
  it('Alcista / Bajista / Sin lectura salen de la tarjeta «Tendencia de largo plazo»', () => {
    for (const l of [ALCISTA, BAJISTA]) {
      const x = lec('X', false, l)
      expect(tendencia(x).palabra).toBe(tarjetas(x.lectura).find(t => t.id === 'fondo').veredicto)
    }
    expect(tendencia(lec('X', false, { ...ALCISTA, media200: null, dist_media200: null, tendencia: null })).id).toBe('sin')
    expect(tendencia({ asset: 'AL30', local: true, disponible: false }).palabra).toBe('Sin lectura')
    expect(tendencia(null).id).toBe('sin')
    expect(fuerza(lec('X', false, ALCISTA))).toEqual({ rsi: 64, palabra: veredictoRsi(64) })
    expect(fuerza({ disponible: false })).toBeNull()
  })

  it('la fila agregada encuentra su lectura con la marca de sus lotes', () => {
    const indice = indexarLecturas([lec('GGAL', true, ALCISTA), lec('GGAL', false, BAJISTA)])
    const lotes = [{ asset: 'GGAL', asset_type: 'ACCION', broker: 'IOL' }, { asset: 'GGAL', asset_type: 'ACCION', broker: 'IOL' }]
    expect(tendencia(lecturaDeFila(indice, { asset: 'GGAL', _lots: lotes })).id).toBe('alcista')
    expect(tendencia(lecturaDeFila(indice, { asset: 'GGAL', asset_type: 'STOCK', broker: 'Schwab' })).id).toBe('bajista')
    expect(lecturaDeFila(indice, { asset: 'ARS', is_cash: true })).toBeNull()
  })
})

// El % de tu cartera en tendencia alcista, sus tres grupos (que suman 100) y el
// motivo de cada «sin lectura» ya no se cuentan en la pantalla (28/10): los arma
// el servidor una vez (senales_semana.reparto). Sus pruebas viven en
// backend/tests/test_reparto_tendencia.py, que además comprueba que la Cartera,
// el Panorama, la pestaña Señales y el mail dan el MISMO %.

describe('lo que no se puede leer no se inventa', () => {
  // «Vieja» lo dice el servidor (`vieja` de cada lectura, tecnico.es_vieja: sin
  // precios de la última semana contada desde el día argentino). La pantalla no
  // cuenta días: antes eran 10 con la fecha de la compu (auditoría 06/11, H2).
  it('una lectura que el servidor marca vieja va sin lectura, con su fecha, y sin RSI', () => {
    const vieja = { ...lec('MSFT', false, { ...ALCISTA, fecha: '2026-09-17' }), vieja: true }
    expect(lecturaVieja(vieja)).toBe(true)
    expect(tendencia(vieja)).toMatchObject({ id: 'sin', palabra: 'Sin lectura', porque: 'vieja' })
    expect(tendencia(vieja).motivo).toContain('17/09/2026')
    expect(fuerza(vieja)).toBeNull()
  })

  it('sin la marca del servidor, una fecha vieja se lee igual: la compu no decide', () => {
    // Con el reloj de la compu adelantado o en otro huso, la Cartera decía «viejo»
    // un día antes (o después) que Comparar. Ahora la fecha sólo se muestra.
    const sinMarca = lec('MSFT', false, { ...ALCISTA, fecha: '2020-01-02' })
    expect(lecturaVieja(sinMarca)).toBe(false)
    expect(tendencia(sinMarca).id).toBe('alcista')
    expect(fuerza(sinMarca)).toEqual({ rsi: 64, palabra: veredictoRsi(64) })
    expect(lecturaVieja({ ...sinMarca, vieja: false })).toBe(false)
  })

  it('si el pedido falla, la fila dice error, no «sin lectura»', () => {
    const p = { asset: 'NVDA', asset_type: 'STOCK', broker: 'Schwab' }
    expect(lecturaDeLaFila({ cargando: false, error: true, indice: null }, p).estado).toBe('error')
    expect(lecturaDeLaFila({ cargando: true, error: false, indice: null }, p).estado).toBe('cargando')
    const listo = lecturaDeLaFila({ cargando: false, error: false, indice: indexarLecturas([lec('NVDA', false, ALCISTA)]) }, p)
    expect(listo.estado).toBe('listo')
    expect(tendencia(listo.x).id).toBe('alcista')
  })
})

describe('el motivo de cada «sin lectura» de una fila', () => {
  const HOY = '2026-10-22'
  it('bono y fondo no se miden; acción sin velas va a aparecer mañana; pocos días y vieja, los suyos', () => {
    const bono = { id: 1, broker: 'IOL', asset: 'AL30', asset_type: 'BONO' }
    const fondo = { id: 2, broker: 'IOL', asset: 'FCI:PIONERO-PESOS', asset_type: 'FUND' }
    const accion = { id: 4, broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION' }
    expect(tendencia({ asset: 'AL30', local: true, disponible: false }, bono).porque).toBe('no_se_mide')
    expect(tendencia(null, fondo).porque).toBe('no_se_mide')
    expect(tendencia({ asset: 'GGAL', local: true, disponible: false }, accion).porque).toBe('sin_historia')
    expect(tendencia(null, accion).motivo).toContain('va a aparecer mañana')
    expect(tendencia(lec('IREN', false, { ...ALCISTA, ruedas: 120, media200: null, dist_media200: null, tendencia: null, fecha: HOY })).porque).toBe('pocos_dias')
    expect(tendencia({ ...lec('MSFT', false, { ...ALCISTA, fecha: '2026-09-17' }), vieja: true }).porque).toBe('vieja')
    // El motivo dice «la última semana», la regla del servidor (tecnico.DIAS_VIEJA = 7).
    expect(MOTIVOS_SIN_LECTURA.vieja).toContain('antes de la última semana')
    for (const k of ['no_se_mide', 'sin_historia', 'pocos_dias', 'vieja']) expect(MOTIVOS_SIN_LECTURA[k]).toBeTruthy()
  })
})
