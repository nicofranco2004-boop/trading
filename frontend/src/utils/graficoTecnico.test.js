// La pestaña «Gráfico» sin React: qué activo abre, qué queda guardado y qué
// ofrece su buscador (utils/graficoTecnico.js).
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { instalarNavegadorMinimo } from '../testing/navegadorMinimo'
import {
  ACTIVO_DE_ENTRADA, RECIENTES_MAXIMOS, activoDeEntrada, activoValido, guardado, opcionesDelBuscador, recordar, tuyos,
} from './graficoTecnico'
// La regla del dueño (la persona y la cuenta de la pestaña): se registra al cargarse.
import './duenoDeLaPestana'

// Los dueños, como los arma utils/duenoDeLaPestana: `persona|cuenta`.
const ANA = 'ana@x.com|propia'
const BETO = 'beto@x.com|propia'

let almacen
beforeEach(() => {
  ({ local: almacen } = instalarNavegadorMinimo())
  localStorage.setItem('rendi_user', JSON.stringify({ email: 'ana@x.com' }))   // Ana logueada en su cuenta
})
afterEach(() => { vi.unstubAllGlobals() })

describe('activoValido: sólo lo que tiene forma de ticker (la de _SYMBOL_RE del servidor)', () => {
  it('pasa a mayúsculas y acepta .BA', () => {
    expect(activoValido(' ggal.ba ')).toBe('GGAL.BA')
  })
  it('tal cual: BTC-USD es BTC-USD y GGAL.BA es GGAL.BA (el nombre con que lo abriría la ficha)', () => {
    expect(activoValido('btc-usd')).toBe('BTC-USD')
    expect(activoValido('GGAL.BA')).toBe('GGAL.BA')
  })
  it('no acepta un fondo, texto suelto ni nada', () => {
    expect(activoValido('FCI:FIMA-AHORRO')).toBeNull()
    expect(activoValido('<script>')).toBeNull()
    expect(activoValido('apple inc')).toBeNull()
    expect(activoValido(null)).toBeNull()
    expect(activoValido(3)).toBeNull()
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
  it('lo de otra persona no se guarda con la pestaña de Ana (la puerta lo frena)', () => {
    recordar(BETO, 'GGAL')
    expect(guardado(BETO)).toEqual({ activo: null, recientes: [] })
  })
  it('sin sesión no se guarda nada', () => {
    localStorage.removeItem('rendi_user')
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
  it('la dirección, tal cual: GGAL.BA es el de BYMA aunque tengas el ADR', () => {
    expect(activoDeEntrada({ deLaDireccion: 'GGAL.BA', persona: BETO })).toBe('GGAL.BA')
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
    expect(s[2].filas.map(f => f.simbolo)).toEqual(['TSLA', 'BTC-USD'])
  })
  it('el cartelito lo dice tu lote: AL30 de IOL es un bono (no «Acción AR»), GGAL de IOL la acción argentina', () => {
    const t = Object.fromEntries(tuyos(posiciones).map(f => [f.simbolo, f.tipo]))
    expect(t).toEqual({ GGAL: 'stock_ar', AL30: 'bond', NVDA: 'stock_us' })
  })
  it('un bono que tenés aparece (es tuyo); uno que no, no (no tiene gráfico técnico)', () => {
    expect(simbolos(opcionesDelBuscador({ consulta: 'al3', posiciones }))).toContain('AL30')
    expect(simbolos(opcionesDelBuscador({ consulta: 'al3', posiciones: [] }))).not.toContain('AL30')
  })
  it('GGAL una sola vez aunque tu lista la tenga como GGAL.BA: queda la de tu lista, con su nombre (el mismo de la ficha)', () => {
    const s = opcionesDelBuscador({ consulta: 'ggal', posiciones: [], lista: [{ symbol: 'GGAL.BA' }] })
    expect(s[0].filas.map(f => [f.simbolo, f.origen, f.nombre])).toEqual([['GGAL.BA', 'lista', 'Grupo Financiero Galicia']])
  })
  it('tu lote BTC-USD y el BTC del catálogo abren lo mismo: queda el tuyo', () => {
    const s = opcionesDelBuscador({ consulta: 'btc', posiciones: [{ asset: 'BTC-USD', asset_type: 'CRYPTO', broker: 'Binance' }] })
    expect(s[0].filas.map(f => [f.simbolo, f.origen])).toEqual([['BTC-USD', 'cartera']])
  })
  describe('el mercado cuenta: un papel argentino que tenés en Nueva York no es el de BYMA', () => {
    const schwab = [{ asset: 'AGRO', asset_type: 'STOCK', broker: 'Schwab' }]
    it('tu AGRO de Schwab es Adecoagro: sin el nombre de Agrometal ni el cartel «Acción AR»', () => {
      expect(tuyos(schwab)).toEqual([expect.objectContaining({ simbolo: 'AGRO', nombre: null, tipo: 'stock_us' })])
    })
    it('AGRO.BA de tu lista (Agrometal, BYMA) no se esconde detrás de tu AGRO de Schwab', () => {
      const s = opcionesDelBuscador({ consulta: 'agro', posiciones: schwab, lista: [{ symbol: 'AGRO.BA' }] })
      expect(s[0].filas.map(f => [f.simbolo, f.origen])).toEqual([['AGRO', 'cartera'], ['AGRO.BA', 'lista']])
      // Escribiendo «AGRO.BA», primero el de BYMA.
      const e = opcionesDelBuscador({ consulta: 'AGRO.BA', posiciones: schwab, lista: [{ symbol: 'AGRO.BA' }] })
      expect(e[0].filas[0]).toMatchObject({ simbolo: 'AGRO.BA', origen: 'lista' })
    })
    it('con tu GGAL de Schwab, escribir GGAL.BA ofrece abrir el de BYMA; con tu GGAL de IOL, encuentra el tuyo', () => {
      const ny = opcionesDelBuscador({ consulta: 'GGAL.BA', posiciones: [{ asset: 'GGAL', asset_type: 'STOCK', broker: 'Schwab' }] })
      expect(ny[0].filas.map(f => [f.simbolo, f.origen])).toEqual([['GGAL.BA', 'escrito']])
      const ba = opcionesDelBuscador({ consulta: 'GGAL.BA', posiciones })
      expect(ba[0].filas[0]).toMatchObject({ simbolo: 'GGAL', origen: 'cartera' })
    })
  })
  it('un asesor adentro de un cliente: «Cartera de…» y «Lista de…», no «Tu»', () => {
    const s = opcionesDelBuscador({ posiciones, lista, cliente: 'Ana Pérez' })
    expect(s.map(x => x.titulo)).toEqual(['Cartera de Ana Pérez', 'Lista de Ana Pérez'])
  })
  it('«Abrir» sólo si no se encontró nada y tiene largo de ticker', () => {
    const t = (consulta) => opcionesDelBuscador({ consulta, posiciones: [], lista: [] }).flatMap(x => x.filas)
    expect(t('agrometal').some(f => f.origen === 'escrito')).toBe(false)
    // AAPL.BA (el CEDEAR, del catálogo) no se confunde con AAPL (Nueva York).
    expect(t('AAPL.BA')[0]).toMatchObject({ simbolo: 'AAPL.BA', tipo: 'cedear' })
    expect(t('ZZZQ.BA').at(-1)).toMatchObject({ simbolo: 'ZZZQ.BA', origen: 'escrito' })
    expect(t('aapl').some(f => f.origen === 'escrito')).toBe(false)
  })
  it('Bitcoin una sola vez, con su nombre, aunque tu lista lo tenga como BTC-USD (y abre BTC-USD, como la ficha desde tu lista)', () => {
    const s = opcionesDelBuscador({ consulta: 'btc', posiciones, lista })
    expect(s[0].filas.map(f => [f.simbolo, f.nombre])).toEqual([['BTC-USD', 'Bitcoin']])
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
    // Bitcoin, con el nombre de tu lista (BTC-USD): el BTC del catálogo abre lo mismo.
    expect(simbolos(opcionesDelBuscador({ filtro: 'cripto', posiciones, lista }))).toContain('BTC-USD')
    expect(simbolos(opcionesDelBuscador({ filtro: 'cripto', posiciones, lista }))).not.toContain('BTC')
  })
})
