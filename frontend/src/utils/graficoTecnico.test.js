// La pestaña «Gráfico» sin React: qué activo abre, qué queda guardado y qué
// ofrece su buscador (utils/graficoTecnico.js).
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'
import {
  ACTIVO_DE_ENTRADA, RECIENTES_MAXIMOS, activoDeEntrada, activoValido, canonico, guardado, opcionesDelBuscador, recordar, tuyos,
} from './graficoTecnico'

const ANA = 'ana@x.com:propia'
const BETO = 'beto@x.com:propia'

let almacen
beforeEach(() => { ({ local: almacen } = instalarNavegadorMinimo()) })
afterEach(() => { vi.unstubAllGlobals() })

describe('activoValido: sólo lo que tiene forma de ticker (la de _SYMBOL_RE del servidor)', () => {
  it('pasa a mayúsculas y acepta .BA', () => {
    expect(activoValido(' ggal.ba ')).toBe('GGAL.BA')
  })
  it('tal cual: BTC-USD es BTC-USD (puede ser el nombre de tus lotes)', () => {
    expect(activoValido('btc-usd')).toBe('BTC-USD')
  })
})

describe('canonico: un nombre por papel (los dibujos se guardan por nombre)', () => {
  it('una cripto, por su código corto', () => {
    expect(canonico('btc-usd')).toBe('BTC')
    expect(canonico('ETH-USDT')).toBe('ETH')
  })
  it('una acción argentina, sin .BA (la estrella de la ficha guarda GGAL.BA, el buscador GGAL)', () => {
    expect(canonico('GGAL.BA')).toBe('GGAL')
    expect(canonico('ypfd.ba')).toBe('YPFD')
  })
  it('un CEDEAR no: AAPL.BA y AAPL son dos papeles; lo demás queda como está', () => {
    expect(canonico('AAPL.BA')).toBe('AAPL.BA')
    expect(canonico('BRK-B')).toBe('BRK-B')
    expect(canonico('FCI:X')).toBeNull()
  })
  it('no acepta un fondo, texto suelto ni nada', () => {
    expect(activoValido('FCI:FIMA-AHORRO')).toBeNull()
    expect(activoValido('<script>')).toBeNull()
    expect(activoValido('apple inc')).toBeNull()
    expect(activoValido(null)).toBeNull()
  })
})

describe('qué queda guardado', () => {
  it('el último abierto y los recientes, sin repetir, el más nuevo primero', () => {
    recordar(ANA, 'GGAL'); recordar(ANA, 'AAPL'); recordar(ANA, 'ggal')
    expect(guardado(ANA)).toEqual({ activo: 'GGAL', recientes: ['GGAL', 'AAPL'] })
  })
  it(`hasta ${RECIENTES_MAXIMOS} recientes`, () => {
    for (let i = 0; i < 12; i++) recordar(ANA, `A${i}`)
    expect(guardado(ANA).recientes).toHaveLength(RECIENTES_MAXIMOS)
    expect(guardado(ANA).recientes[0]).toBe('A11')
  })
  it('por persona: en la misma compu, Beto no ve lo que miró Ana', () => {
    recordar(ANA, 'GGAL')
    expect(guardado(BETO)).toEqual({ activo: null, recientes: [] })
  })
  it('sin sesión no se guarda nada', () => {
    recordar(null, 'GGAL')
    expect(almacen.size).toBe(0)
    expect(guardado(null).activo).toBeNull()
  })
  it('lo guardado roto o inventado no se abre', () => {
    almacen.set(`rendi_grafico:${ANA}`, '{"activo":"FCI:X","recientes":["GGAL","<b>",3]}')
    expect(guardado(ANA)).toEqual({ activo: null, recientes: ['GGAL'] })
    almacen.set(`rendi_grafico:${ANA}`, 'no es json')
    expect(guardado(ANA)).toEqual({ activo: null, recientes: [] })
  })
})

describe('qué activo abre la pestaña', () => {
  const posiciones = [
    { asset: 'USD', is_cash: 1 },
    { asset: 'FCI:FIMA', asset_type: 'FUND' },
    { asset: 'NVDA', asset_type: 'STOCK', broker: 'Schwab' },
  ]
  it('la dirección gana; si no, el último que miraste; si no, lo tuyo; si no, el S&P 500', () => {
    recordar(ANA, 'KO')
    expect(activoDeEntrada({ deLaDireccion: 'tsla', persona: ANA, posiciones })).toBe('TSLA')
    expect(activoDeEntrada({ deLaDireccion: null, persona: ANA, posiciones })).toBe('KO')
    expect(activoDeEntrada({ deLaDireccion: null, persona: BETO, posiciones })).toBe('NVDA')
    expect(activoDeEntrada({ deLaDireccion: null, persona: BETO, posiciones: [] })).toBe(ACTIVO_DE_ENTRADA)
  })
  it('la primera vez no abre un bono (no tiene gráfico técnico): el primero tuyo que sí', () => {
    const conBono = [{ asset: 'AL30', asset_type: 'BOND', broker: 'IOL', currency: 'ARS' }, { asset: 'GGAL', asset_type: 'ACCION', broker: 'IOL', currency: 'ARS' }]
    expect(activoDeEntrada({ deLaDireccion: null, persona: BETO, posiciones: conBono })).toBe('GGAL')
  })
  it('lo guardado y la dirección, por el nombre del papel', () => {
    expect(activoDeEntrada({ deLaDireccion: 'GGAL.BA', persona: BETO })).toBe('GGAL')
    recordar(ANA, 'GGAL.BA'); recordar(ANA, 'GGAL')
    expect(guardado(ANA).recientes).toEqual(['GGAL'])
  })
  it('lo tuyo con gráfico: sin el efectivo ni los fondos', () => {
    expect(tuyos(posiciones).map(f => f.simbolo)).toEqual(['NVDA'])
  })
})

describe('el buscador', () => {
  const posiciones = [
    { asset: 'GGAL', asset_type: 'ACCION', broker: 'IOL', currency: 'ARS' },
    { asset: 'AL30', asset_type: 'BOND', broker: 'IOL', currency: 'ARS' },
    { asset: 'NVDA', asset_type: 'STOCK', broker: 'Schwab' },
  ]
  const lista = [{ symbol: 'TSLA' }, { symbol: 'NVDA' }, { symbol: 'BTC-USD' }]
  const titulos = (s) => s.map(x => x.titulo)
  const simbolos = (s) => s.flatMap(x => x.filas.map(f => f.simbolo))

  it('sin nada escrito: los últimos que miraste, tu cartera y tu lista (sin repetir lo tuyo)', () => {
    const s = opcionesDelBuscador({ recientes: ['MELI'], posiciones, lista })
    expect(titulos(s)).toEqual(['Últimos que miraste', 'Tu cartera', 'Tu lista'])
    expect(s[2].filas.map(f => f.simbolo)).toEqual(['TSLA', 'BTC'])
  })
  it('el cartelito lo dice tu lote: AL30 de IOL es un bono (no «Acción AR»), GGAL de IOL la acción argentina', () => {
    const t = Object.fromEntries(tuyos(posiciones).map(f => [f.simbolo, f.tipo]))
    expect(t).toEqual({ GGAL: 'stock_ar', AL30: 'bond', NVDA: 'stock_us' })
  })
  it('un bono que tenés aparece (es tuyo); uno que no, no (no tiene gráfico técnico)', () => {
    expect(simbolos(opcionesDelBuscador({ consulta: 'al3', posiciones }))).toContain('AL30')
    expect(simbolos(opcionesDelBuscador({ consulta: 'al3', posiciones: [] }))).not.toContain('AL30')
  })
  it('GGAL una sola vez aunque tu lista la tenga como GGAL.BA (y los dibujos, en un solo lugar)', () => {
    const s = opcionesDelBuscador({ consulta: 'ggal', posiciones: [], lista: [{ symbol: 'GGAL.BA' }] })
    expect(s[0].filas.map(f => [f.simbolo, f.origen])).toEqual([['GGAL', 'lista']])
  })
  it('tu lote BTC-USD y el BTC del catálogo son uno: queda el tuyo', () => {
    const s = opcionesDelBuscador({ consulta: 'btc', posiciones: [{ asset: 'BTC-USD', asset_type: 'CRYPTO', broker: 'Binance' }] })
    expect(s[0].filas.map(f => [f.simbolo, f.origen])).toEqual([['BTC-USD', 'cartera']])
  })
  it('«Abrir» sólo si no se encontró nada y tiene largo de ticker', () => {
    const t = (consulta) => opcionesDelBuscador({ consulta, posiciones: [], lista: [] }).flatMap(x => x.filas)
    expect(t('agrometal').some(f => f.origen === 'escrito')).toBe(false)
    // AAPL.BA (el CEDEAR, del catálogo) no se confunde con AAPL (Nueva York).
    expect(t('AAPL.BA')[0]).toMatchObject({ simbolo: 'AAPL.BA', tipo: 'cedear' })
    expect(t('ZZZQ.BA').at(-1)).toMatchObject({ simbolo: 'ZZZQ.BA', origen: 'escrito' })
    expect(t('aapl').some(f => f.origen === 'escrito')).toBe(false)
  })
  it('Bitcoin una sola vez, con su nombre, aunque tu lista lo tenga como BTC-USD', () => {
    const s = opcionesDelBuscador({ consulta: 'btc', posiciones, lista })
    expect(s[0].filas.map(f => [f.simbolo, f.nombre])).toEqual([['BTC', 'Bitcoin']])
  })
  it('por nombre, lo tuyo primero', () => {
    const s = opcionesDelBuscador({ consulta: 'galicia', posiciones, lista })
    expect(simbolos(s)[0]).toBe('GGAL')
  })
  it('lo escrito con forma de ticker que no está: «Abrir XYZ»; lo mismo con otro nombre, no', () => {
    const s = opcionesDelBuscador({ consulta: 'ZZZQ', posiciones, lista })
    expect(s[0].filas.at(-1)).toMatchObject({ simbolo: 'ZZZQ', origen: 'escrito' })
    const g = opcionesDelBuscador({ consulta: 'GGAL.BA', posiciones, lista })
    expect(g[0].filas.some(f => f.origen === 'escrito')).toBe(false)
    // Un nombre que ya encontró algo no se ofrece como ticker.
    const n = opcionesDelBuscador({ consulta: 'galicia', posiciones, lista })
    expect(n[0].filas.map(f => f.simbolo)).toEqual(['GGAL'])
  })
  it('los filtros: tu cartera, acciones argentinas (lo dice tu lote: GGAL de IOL) y cripto', () => {
    expect(simbolos(opcionesDelBuscador({ filtro: 'cartera', posiciones, lista }))).toEqual(['GGAL', 'AL30', 'NVDA'])
    expect(simbolos(opcionesDelBuscador({ filtro: 'ar', consulta: 'gg', posiciones, lista }))).toEqual(['GGAL'])
    expect(simbolos(opcionesDelBuscador({ filtro: 'cripto', posiciones, lista }))).toContain('BTC')
  })
})
