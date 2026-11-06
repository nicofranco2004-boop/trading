// La pestaña «Precio» de Comparar: qué se le pide al servidor (con las reglas
// de la ficha para tus lotes) y las palabras de abajo. La cuenta del 100 la
// prueba el servidor (backend/tests/test_comparar_precio.py).
import { describe, it, expect, beforeEach } from 'vitest'
import { setBrokersRegistry } from './valuation'
import {
  marcaLocal, primeraCompraDe, urlDelPedido, urlDeComparar, filasDelGrafico, fraseComparacion, monto,
  vaciaPorVieja,
} from './comparadorPrecio'

const serie = (clave, final, tipo = 'activo') => ({ clave, nombre: clave, tipo, final, puntos: [] })
const res = (series, extra = {}) => ({ moneda: 'usd', base: '2025-03-14', desde: '2025-03-14', plazo: '1a', base_corrida_por: null, series, ...extra })

describe('qué se pide', () => {
  beforeEach(() => setBrokersRegistry([{ name: 'IOL', currency: 'ARS' }, { name: 'Schwab', currency: 'USD' }]))

  it('una acción argentina: la deciden tus lotes; sin lotes, el ticker (como la ficha)', () => {
    const tuya = [{ asset: 'GGAL', broker: 'IOL', asset_type: 'ACCION', quantity: 10 }]
    expect(marcaLocal('GGAL', tuya)).toBe(true)
    // Tu GGAL es el ADR de Schwab: no es la acción de BYMA.
    expect(marcaLocal('GGAL', [{ asset: 'GGAL', broker: 'Schwab', asset_type: 'STOCK', quantity: 1 }])).toBe(false)
    expect(marcaLocal('GGAL', [])).toBe(true)
    expect(marcaLocal('GGAL.BA', [])).toBe(true)
    expect(marcaLocal('NVDA', [])).toBe(false)
    expect(marcaLocal('AAPL', [{ asset: 'AAPL', broker: 'IOL', asset_type: 'CEDEAR', quantity: 1 }])).toBe(false)
    // Lo vendiste todo: deciden tus operaciones.
    expect(marcaLocal('GGAL', [], [{ asset: 'GGAL', broker: 'Schwab', asset_type: 'STOCK' }])).toBe(false)
  })

  it('tu primera compra: el lote abierto más viejo de cualquiera de los activos', () => {
    const lotes = [
      { asset: 'GGAL', broker: 'IOL', quantity: 10, entry_date: '2025-03-14' },
      { asset: 'MSFT', broker: 'Schwab', quantity: 1, entry_date: '2024-06-02' },
      { asset: 'MSFT', broker: 'Schwab', quantity: 0, entry_date: '2023-01-02' },   // vendido
      { asset: 'KO', broker: 'Schwab', quantity: 5, entry_date: '2020-01-02' },     // no se compara
    ]
    expect(primeraCompraDe(['GGAL', 'MSFT', 'NVDA'], lotes)).toBe('2024-06-02')
    expect(primeraCompraDe(['NVDA'], lotes)).toBeNull()
    // GGAL.BA (lo que manda el buscador) es tu GGAL de IOL.
    expect(primeraCompraDe(['GGAL.BA'], lotes)).toBe('2025-03-14')
    // Comprado hoy: no hay nada que comparar todavía (el servidor lo rechazaba y la pantalla abría con error).
    expect(primeraCompraDe(['GGAL'], lotes, '2025-03-14')).toBeNull()
    expect(primeraCompraDe(['GGAL'], lotes, '2025-03-15')).toBe('2025-03-14')
  })

  it('tus lotes de un activo: los de ese nombre, como la ficha (BRK.B y BRKB son dos fichas)', () => {
    const lotes = [
      { asset: 'BRK.B', broker: 'Schwab', asset_type: 'STOCK', quantity: 1, entry_date: '2021-05-03' },
      { asset: 'BRKB', broker: 'IOL', asset_type: 'CEDEAR', quantity: 4, entry_date: '2024-02-01' },
    ]
    expect(primeraCompraDe(['BRKB'], lotes)).toBe('2024-02-01')
    expect(primeraCompraDe(['BRK.B'], lotes)).toBe('2021-05-03')
    // Pedido con otro nombre y sin lotes con ése: el tuyo (como te redirige la ficha).
    expect(primeraCompraDe(['BRK-B'], lotes)).toBe('2021-05-03')
  })

  it('la dirección de Comparar → Precio', () => {
    expect(urlDeComparar(['ggal', 'MSFT', 'GGAL', 'NVDA', 'KO', 'AAPL'])).toBe('/fundamentals?vista=precio&cmp=GGAL,MSFT,NVDA,KO')
    expect(urlDeComparar([])).toBe('/fundamentals?vista=precio')
  })

  it('la dirección', () => {
    expect(urlDelPedido({ activos: ['GGAL', 'MSFT'], locales: ['GGAL'], moneda: 'usd', plazo: 'compra', desde: '2025-03-14' }))
      .toBe('/comparar/precio?activos=GGAL%2CMSFT&moneda=usd&plazo=compra&local=GGAL&desde=2025-03-14')
    expect(urlDelPedido({ activos: ['NVDA'], locales: [], moneda: 'ars', plazo: '1a', desde: '2025-03-14' }))
      .toBe('/comparar/precio?activos=NVDA&moneda=ars&plazo=1a')
  })
})

describe('el gráfico', () => {
  it('una fila por día con lo que tuvo dato ese día', () => {
    const filas = filasDelGrafico([
      { clave: 'BTC', puntos: [{ d: '2025-03-14', v: 100 }, { d: '2025-03-15', v: 102 }] },
      { clave: 'sp500', puntos: [{ d: '2025-03-14', v: 100 }, { d: '2025-03-17', v: 101 }] },
    ])
    expect(filas).toEqual([
      { d: '2025-03-14', BTC: 100, sp500: 100 }, { d: '2025-03-15', BTC: 102 }, { d: '2025-03-17', sp500: 101 },
    ])
  })

  it('cada 100, en la moneda', () => {
    expect(monto(157.6, 'usd')).toBe('US$ 158')
    expect(monto(1240.2, 'ars')).toBe('$ 1.240')
  })
})

describe('lo que dicen los números', () => {
  it('cuántos le ganaron al S&P y quién quedó abajo de guardar los dólares', () => {
    const f = fraseComparacion(res([serie('GGAL', 158), serie('YPFD', 131), serie('MELI', 94),
      serie('sp500', 112, 'vara'), serie('mep', 100, 'vara')]))
    expect(f).toBe('2 de los 3 le ganaron al S&P 500 desde el 14/03/25. MELI quedó abajo de lo que habría dado guardar los dólares.')
  })

  it('compara lo que se ve: 136,7 contra 137,3 es un empate, no una derrota', () => {
    const f = fraseComparacion(res([serie('GGAL', 76), serie('MSFT', 136.66), serie('NVDA', 177),
      serie('sp500', 137.33, 'vara')]))
    expect(f).toBe('1 de los 3 le ganó al S&P 500 desde el 14/03/25. MSFT quedó igual.')
  })

  it('desde tu primera compra, y uno solo', () => {
    expect(fraseComparacion(res([serie('GGAL', 90), serie('sp500', 110, 'vara')], { plazo: 'compra' })))
      .toBe('GGAL quedó abajo del S&P 500 desde tu primera compra.')
    // Si el 100 se corrió (aunque sea unos días), no es tu primera compra: se dice la fecha.
    expect(fraseComparacion(res([serie('GGAL', 120), serie('sp500', 110, 'vara')], { plazo: 'compra', desde: '2025-03-10' })))
      .toBe('GGAL le ganó al S&P 500 desde el 14/03/25.')
  })

  it('en pesos: el dólar y la inflación, sin decir qué hacer', () => {
    const f = fraseComparacion(res([serie('GGAL', 180), serie('PAMP', 90), serie('mep', 200, 'vara'),
      serie('cer', 150, 'vara')], { moneda: 'ars' }))
    // PAMP BAJÓ: no puede decir que «subió menos» (la prueba vieja lo daba por bueno).
    expect(f).toBe('GGAL y PAMP quedaron abajo del dólar MEP. PAMP terminó con menos pesos que al principio.')
    const g = fraseComparacion(res([serie('GGAL', 130), serie('cer', 150, 'vara')], { moneda: 'ars' }))
    expect(g).toBe('GGAL subió menos que la inflación: en pesos hay más, pero alcanza para menos.')
    // En 100 redondo no «subió»: terminó con los mismos pesos.
    expect(fraseComparacion(res([serie('GGAL', 100.3), serie('cer', 150, 'vara')], { moneda: 'ars' })))
      .toBe('GGAL terminó con los mismos pesos, que alcanzan para menos.')
  })

  it('sin varas prendidas o sin activos, nada', () => {
    expect(fraseComparacion(res([serie('GGAL', 130)]))).toBe('')
    expect(fraseComparacion(res([serie('sp500', 110, 'vara')]))).toBe('')
  })
})

describe('el panel vacío cuando todo lo pedido está viejo (H1, 06/11)', () => {
  const vieja = (clave, hasta) => ({ clave, motivo: 'vieja', hasta })
  it('dice que faltan precios recientes, con el último que hay; no «probá con otro activo»', () => {
    // La noche caída: los dos activos, cada uno hasta su día; vale el más nuevo.
    const r = { series: [], faltan: [vieja('MU', '2026-08-14'), vieja('AAPL', '2026-10-05'), { clave: 'cer', motivo: 'solo_en_pesos' }] }
    expect(vaciaPorVieja(r, ['MU', 'AAPL'])).toEqual({
      titulo: 'No hay precios recientes para comparar',
      texto: 'Para comparar hacen falta precios de la última semana, y los últimos que tenemos son del 05/10/26.',
    })
  })
  it('si falta otro por otra cosa (un bono), el panel de siempre', () => {
    const r = { series: [], faltan: [vieja('MU', '2026-08-14'), { clave: 'AL30', motivo: 'sin_serie' }] }
    expect(vaciaPorVieja(r, ['MU', 'AL30'])).toBeNull()
    expect(vaciaPorVieja({ series: [], faltan: [{ clave: 'AL30', motivo: 'sin_serie' }] }, ['AL30'])).toBeNull()
    expect(vaciaPorVieja({ series: [], faltan: [] }, ['MU'])).toBeNull()
  })
})
