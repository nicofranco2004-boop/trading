import { describe, it, expect, beforeEach } from 'vitest'
import {
  esLoteLocal, esAccionLocal, activosParaLeer, indexarLecturas, lecturaDeFila, tendencia, fuerza,
  repartirCien, radiografia,
} from './radiografia'
import { computeBrokerValue, setBrokersRegistry } from './valuation'
import { tarjetas } from './tecnico'

const BROKERS = [
  { id: 1, name: 'IOL', currency: 'ARS' },
  { id: 2, name: 'Schwab', currency: 'USD' },
]
beforeEach(() => setBrokersRegistry(BROKERS))

// Lecturas como las devuelve POST /api/tecnico/cartera.
const lec = (asset, local, l, cambios = []) => ({ asset, local, disponible: true, lectura: { ruedas: 760, ...l }, cambios })
const ALCISTA = { media200: 90, dist_media200: 11.1, pendiente_media200: 2, media50: 95, dist_media50: 5, rsi: 64 }
const BAJISTA = { media200: 110, dist_media200: -9.1, pendiente_media200: -1, media50: 105, dist_media50: -4.8, rsi: 38 }

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
  it('Alcista / Bajista / Sin lectura salen de la tarjeta «Tendencia de fondo»', () => {
    for (const l of [ALCISTA, BAJISTA]) {
      const x = lec('X', false, l)
      expect(tendencia(x).palabra).toBe(tarjetas(x.lectura).find(t => t.id === 'fondo').veredicto)
    }
    expect(tendencia(lec('X', false, { ...ALCISTA, media200: null, dist_media200: null })).id).toBe('sin')
    expect(tendencia({ asset: 'AL30', local: true, disponible: false }).palabra).toBe('Sin lectura')
    expect(tendencia(null).id).toBe('sin')
    expect(fuerza(lec('X', false, ALCISTA))).toEqual({ rsi: 64, palabra: 'Pesan más las subas' })
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

describe('repartirCien', () => {
  it('suma 100 aunque redondear cada uno diera 99 o 101', () => {
    expect(repartirCien([1, 1, 1])).toEqual([34, 33, 33])
    expect(repartirCien([54.4, 29.4, 16.2]).reduce((a, b) => a + b, 0)).toBe(100)
    expect(repartirCien([0, 0, 0])).toEqual([0, 0, 0])
  })
})

describe('radiografia, con la valuación de la Cartera', () => {
  // Una cartera chica valuada por el MISMO motor que el total de la Cartera de
  // compu (computeBrokerValue → valuePositionLot): el peso de cada activo es su
  // pedazo de ese total, no otra cuenta.
  const POS = [
    { id: 1, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
    { id: 2, broker: 'Schwab', asset: 'KO', asset_type: 'STOCK', quantity: 10, invested: 600, buy_price: 60 },
    { id: 3, broker: 'Schwab', asset: 'USD', is_cash: true, quantity: 500, invested: 500 },
    { id: 4, broker: 'Schwab', asset: 'NVDA', asset_type: 'STOCK', quantity: 10, invested: 1000, buy_price: 100 },
  ]
  const PRICES = { NVDA: 150, KO: 50 }
  const totales = BROKERS.map(b => computeBrokerValue(POS, PRICES, b, 1000, 1000))
  const valorDe = p => totales.find((r, i) => BROKERS[i].name === p.broker).porLote.get(p.id) ?? 0
  const totalCartera = totales.reduce((s, r) => s + r.value, 0)

  it('los tres grupos suman el total de la Cartera (más los plazos fijos)', () => {
    const indice = indexarLecturas([
      lec('NVDA', false, ALCISTA, [{ media: 200, direccion: 'arriba', fecha: '2026-10-20' }]),
      lec('KO', false, { ...BAJISTA, rsi: 24 }, [{ media: 50, direccion: 'abajo', fecha: '2026-10-21' }]),
    ])
    const r = radiografia(POS, valorDe, indice, [{ nombre: 'plazos fijos', valor: 1000 }])
    expect(r.total).toBeCloseTo(totalCartera + 1000, 9)
    expect(r.grupos.alcista.valor).toBeCloseTo(3000, 9)     // 2 lotes de NVDA × 10 × 150
    expect(r.grupos.bajista.valor).toBeCloseTo(500, 9)      // KO
    expect(r.grupos.sin.valor).toBeCloseTo(1500, 9)         // efectivo + plazos fijos
    expect(r.grupos.alcista.pct + r.grupos.bajista.pct + r.grupos.sin.pct).toBe(100)
    expect(r.grupos.alcista.pct).toBe(60)
    expect(r.grupos.alcista.nombres).toEqual(['NVDA'])
    expect(r.grupos.sin.nombres).toEqual(['plazos fijos', 'efectivo'])
    expect(r.cambios).toEqual([
      { asset: 'NVDA', tono: 'pos', texto: 'recuperó su media de 200 días (martes 20/10)' },
      { asset: 'KO', tono: 'neg', texto: 'perdió su media de 50 días (miércoles 21/10)' },
      { asset: 'KO', tono: 'aviso', texto: 'tiene el RSI en 24: bajó muy fuerte y rápido' },
    ])
  })

  it('sin lecturas todavía, todo va sin lectura (no se inventa una tendencia)', () => {
    const r = radiografia(POS, valorDe, new Map())
    expect(r.grupos.sin.pct).toBe(100)
    expect(r.grupos.alcista.valor).toBe(0)
    expect(r.cambios).toEqual([])
  })

  it('el RSI en la zona del medio no es un cambio; 70 justo tampoco', () => {
    const indice = indexarLecturas([lec('NVDA', false, { ...ALCISTA, rsi: 70 }), lec('KO', false, { ...BAJISTA, rsi: 30 })])
    expect(radiografia(POS, valorDe, indice).cambios).toEqual([])
  })
})
