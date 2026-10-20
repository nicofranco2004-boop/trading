import { describe, it, expect } from 'vitest'
import { opcionesCedear } from './opcionesCedear'

const CURADA = [{ s: 'AAPL', n: 'Apple' }, { s: 'GOOGL', n: 'Alphabet' }, { s: 'BLK', n: 'BlackRock' }]
// Recorte de lo que devuelve /api/cedears.
const ITEMS = [
  { s: 'AAPL', pesos: 'AAPL', dolares: 'AAPLD', px_ars: 27780, px_usd: 18.04, fuente_usd: 'byma' },
  { s: 'GOOGL', pesos: 'GOOGL', dolares: 'GOGLD', px_ars: 9670, px_usd: 6.3, fuente_usd: 'byma' },
  { s: 'ABEV3', pesos: 'ABEV3', dolares: null, px_ars: 3100, px_usd: null, fuente_usd: null },
  { s: 'YELP', pesos: 'YELP', dolares: 'YELPD', px_ars: 15930, px_usd: 10.34, fuente_usd: 'estimado' },
]

describe('opcionesCedear', () => {
  it('en una cuenta argentina: cada CEDEAR en pesos y en dólares', () => {
    const o = opcionesCedear(CURADA, ITEMS, { enCuentaArgentina: true })
    const apple = o.filter(x => x.s === 'AAPL')
    expect(apple.map(x => x._ccy)).toEqual(['ARS', 'USD'])
    expect(apple[1]).toMatchObject({ n: 'Apple', _codigo: 'AAPLD', _px: 18.04, _sub: 'CEDEAR en dólares · AAPLD' })
    expect(apple[0]).toMatchObject({ _codigo: 'AAPL', _px: 27780, _sub: 'CEDEAR en pesos' })
  })

  it('se guarda con el ticker de siempre: el código D es sólo para mostrar', () => {
    const o = opcionesCedear(CURADA, ITEMS, { enCuentaArgentina: true })
    const google = o.find(x => x.s === 'GOOGL' && x._ccy === 'USD')
    expect(google.s).toBe('GOOGL')
    expect(google._codigo).toBe('GOGLD')
  })

  it('suma los CEDEARs de la Bolsa que no están en la lista curada, después de los curados', () => {
    const o = opcionesCedear(CURADA, ITEMS, { enCuentaArgentina: true })
    const syms = [...new Set(o.map(x => x.s))]
    expect(syms).toEqual(['AAPL', 'GOOGL', 'BLK', 'ABEV3', 'YELP'])
  })

  it('sin especie en dólares, sólo en pesos', () => {
    const o = opcionesCedear(CURADA, ITEMS, { enCuentaArgentina: true })
    expect(o.filter(x => x.s === 'ABEV3').map(x => x._ccy)).toEqual(['ARS'])
    // BLK está en la lista curada pero la Bolsa no lo trae: no se inventa el de dólares.
    expect(o.filter(x => x.s === 'BLK').map(x => x._ccy)).toEqual(['ARS'])
  })

  it('el precio estimado se marca', () => {
    const o = opcionesCedear(CURADA, ITEMS, { enCuentaArgentina: true })
    expect(o.find(x => x.s === 'YELP' && x._ccy === 'USD')._estimado).toBe(true)
  })

  it('si el backend no contestó, la lista curada igual se ofrece en las dos monedas', () => {
    const o = opcionesCedear(CURADA, null, { enCuentaArgentina: true })
    expect(o.filter(x => x.s === 'AAPL').map(x => x._ccy)).toEqual(['ARS', 'USD'])
    expect(o.find(x => x.s === 'AAPL' && x._ccy === 'USD')).toMatchObject({ _codigo: null, _px: null })
  })

  it('en un broker del exterior no cambia nada', () => {
    expect(opcionesCedear(CURADA, ITEMS, { enCuentaArgentina: false })).toBe(CURADA)
  })
})

describe('opcionesCedear — auditoría 20/10', () => {
  it('mientras carga (undefined) sólo pesos: las filas en dólares no aparecen y desaparecen bajo el dedo', () => {
    const o = opcionesCedear(CURADA, undefined, { enCuentaArgentina: true })
    expect(o.every(x => x._ccy === 'ARS')).toBe(true)
  })

  it('Berkshire no aparece dos veces: el alias BRKB sobra si la Bolsa trae BRK-B', () => {
    const curada = [{ s: 'BRK-B', n: 'Berkshire Hathaway' }, { s: 'BRKB', n: 'Berkshire Hathaway (B)' }]
    const items = [{ s: 'BRK-B', pesos: 'BRKB', dolares: 'BRKBD', px_ars: 39180, px_usd: 25.45, fuente_usd: 'byma' }]
    const o = opcionesCedear(curada, items, { enCuentaArgentina: true })
    expect([...new Set(o.map(x => x.s))]).toEqual(['BRK-B'])
  })
})
