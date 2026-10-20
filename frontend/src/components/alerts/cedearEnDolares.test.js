// Aviso de precio de un CEDEAR en dólares (AAPL en la Bolsa como AAPLD).
//
// Hasta el 20/10 el selector $/US$ del precio era libre y la moneda era sólo un
// rótulo: «AAPL (CEDEAR) baja a US$ 15» se guardaba y el servidor lo comparaba
// contra los pesos del CEDEAR — no avisaba nunca. Ahora la moneda es una que el
// activo TIENE (misma regla que main._moneda_del_aviso) y el CEDEAR en dólares
// es una opción del buscador, como en "Registrar compra".
import { describe, it, expect, vi } from 'vitest'

vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => Promise.resolve({})) } }))
vi.mock('../../hooks/usePushNotifications', () => ({
  usePushNotifications: () => ({ supported: false, subscribed: false, subscribe: vi.fn() }),
}))

import { monedasPosibles, esCedearEnDolares, claveDePrecio, frase, confirmacion, estado } from './alertasTexto'
import { dolaresPorSimbolo } from '../../utils/opcionesCedear'
import { filasDelBuscador } from './AlertaForm'

// Lo que devuelve GET /api/cedears (recorte del 20/10).
const ITEMS = [
  { s: 'AAPL', pesos: 'AAPL', dolares: 'AAPLD', px_ars: 27780, px_usd: 18.04, fuente_usd: 'byma' },
  { s: 'BRK-B', pesos: 'BRKB', dolares: 'BRKBD', px_ars: 39180, px_usd: 25.45, fuente_usd: 'byma' },
  { s: 'GOOGL', pesos: 'GOOGL', dolares: 'GOGLD', px_ars: 9670, px_usd: 6.3, fuente_usd: 'byma' },
  { s: 'ABEV3', pesos: 'ABEV3', dolares: null, px_ars: 3100, px_usd: null, fuente_usd: null },
]
const DOLARES = dolaresPorSimbolo(ITEMS)

describe('dolaresPorSimbolo', () => {
  it('indexa por el código de la Bolsa y por el ticker de Rendi', () => {
    expect(DOLARES.get('AAPL.BA')).toEqual({ px: 18.04, codigo: 'AAPLD' })
    expect(DOLARES.get('BRKB.BA').codigo).toBe('BRKBD')       // el que arma priceSymbol
    expect(DOLARES.get('BRK-B.BA').codigo).toBe('BRKBD')
    expect(DOLARES.get('GOOGL.BA').codigo).toBe('GOGLD')      // no es pesos + 'D'
    expect(DOLARES.has('ABEV3.BA')).toBe(false)
  })

  it('sin lista no inventa un mapa vacío («no sé» no es «no tiene»)', () => {
    expect(dolaresPorSimbolo(null)).toBeNull()
    expect(dolaresPorSimbolo(undefined)).toBeNull()
  })
})

describe('monedasPosibles: la moneda es una que el activo tiene', () => {
  it('un CEDEAR que cotiza en dólares: pesos o dólares', () => {
    expect(monedasPosibles('AAPL.BA', DOLARES)).toEqual(['ARS', 'USD'])
  })
  it('la trampa: un CEDEAR sin especie en dólares ya no ofrece US$', () => {
    expect(monedasPosibles('ABEV3.BA', DOLARES)).toEqual(['ARS'])
    expect(monedasPosibles('GGAL.BA', DOLARES)).toEqual(['ARS'])
  })
  it('una acción de EE.UU. o una cripto: sólo dólares', () => {
    expect(monedasPosibles('AAPL', DOLARES)).toEqual(['USD'])
    expect(monedasPosibles('BTC', DOLARES)).toEqual(['USD'])
  })
  it('un fondo: los hay en pesos y en dólares', () => {
    expect(monedasPosibles('FCI:ALGO', DOLARES)).toEqual(['ARS', 'USD'])
  })
  it('mientras carga la lista (o si no llegó) no le borra los dólares a un CEDEAR', () => {
    expect(monedasPosibles('AAPL.BA', undefined)).toEqual(['ARS', 'USD'])
    expect(monedasPosibles('AAPL.BA', null)).toEqual(['ARS', 'USD'])
  })
})

describe('esCedearEnDolares (espejo de alerts_engine.cedear_en_dolares)', () => {
  const a = { kind: 'price_target', scope: 'ticker', symbol: 'AAPL.BA', currency: 'USD' }
  it('aviso de precio de un .BA en dólares', () => {
    expect(esCedearEnDolares(a)).toBe(true)
    expect(claveDePrecio(a)).toBe('AAPL.BA|USD')
  })
  it('en pesos, de % o de toda la cartera, no', () => {
    expect(esCedearEnDolares({ ...a, currency: 'ARS' })).toBe(false)
    expect(esCedearEnDolares({ ...a, kind: 'pct_move' })).toBe(false)
    expect(esCedearEnDolares({ ...a, scope: 'holdings' })).toBe(false)
    expect(esCedearEnDolares({ ...a, symbol: 'AAPL' })).toBe(false)
    expect(claveDePrecio({ ...a, currency: 'ARS' })).toBe('AAPL.BA')
  })
})

describe('cómo se dice', () => {
  const a = { kind: 'price_target', scope: 'ticker', symbol: 'AAPL.BA', currency: 'USD',
    direction: 'below', threshold: 17.5, active: true }
  it('la fila distingue el CEDEAR en dólares de la acción de Nasdaq', () => {
    expect(frase(a)).toEqual({ quien: 'AAPL (CEDEAR)', que: 'baja a US$ 17,50' })
    expect(frase({ ...a, symbol: 'AAPL', threshold: 250 }).quien).toBe('AAPL')
  })
  it('la confirmación lo dice entero', () => {
    expect(confirmacion(a)).toBe('Te avisamos cuando el CEDEAR de AAPL en dólares baje a US$ 17,50.')
    expect(confirmacion({ ...a, currency: 'ARS', threshold: 26000 }))
      .toBe('Te avisamos cuando AAPL baje a $ 26.000.')
  })
  it('el estado usa el precio en dólares (no los $27.780)', () => {
    expect(estado(a, 18.04).texto).toBe('Está en US$ 18,04 · le falta 3 %')
  })
})

describe('el buscador de la alerta', () => {
  it('ofrece el CEDEAR en pesos y en dólares, cada uno con su moneda', () => {
    const f = filasDelBuscador('AAPL', DOLARES).filter(x => x.symbol === 'AAPL.BA')
    expect(f.map(x => [x.ccy, x.sub])).toEqual([
      ['ARS', 'CEDEAR en pesos'],
      ['USD', 'CEDEAR en dólares · AAPLD'],
    ])
    // La acción de Nasdaq sigue estando, sin moneda forzada (va la del riel).
    expect(filasDelBuscador('AAPL', DOLARES).some(x => x.symbol === 'AAPL' && x.ccy === null)).toBe(true)
  })

  it('escribiendo el código en dólares aparece primero esa fila', () => {
    const [primera] = filasDelBuscador('AAPLD', DOLARES)
    expect([primera.symbol, primera.ccy]).toEqual(['AAPL.BA', 'USD'])
  })

  it('sin la lista de la Bolsa, el buscador es el de siempre', () => {
    const f = filasDelBuscador('AAPL', null)
    expect(f.some(x => x.ccy === 'USD')).toBe(false)
  })
})
