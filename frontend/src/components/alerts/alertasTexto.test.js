// Cómo se dice una alerta: la frase de la fila, la confirmación del formulario
// y la línea de estado. Son las tres caras de la misma alerta y tienen que
// decir lo mismo.
import { describe, it, expect } from 'vitest'
import { frase, confirmacion, estado, fmtPrecio, fmtPct, diaArgentina, fechaCorta, simbolo } from './alertasTexto'

const precio = { id: 1, kind: 'price_target', scope: 'ticker', symbol: 'GGAL.BA', currency: 'ARS', direction: 'above', threshold: 8000, active: true, repeat: 'once' }
const cartera = { id: 2, kind: 'pct_move', scope: 'holdings', symbol: null, up_pct: 8, down_pct: 5, baseline: 'prev_close', active: true, repeat: 'always' }

describe('números a la argentina', () => {
  it('pesos sin decimales, dólares con dos, % sin decimales de más', () => {
    expect(fmtPrecio(7350, 'ARS')).toBe('$ 7.350')
    expect(fmtPrecio(2145.3, 'USD')).toBe('US$ 2.145,30')
    expect(fmtPct(8)).toBe('8')
    expect(fmtPct(8.84)).toBe('8,8')
    expect(fmtPct(-3.1)).toBe('3,1')
    expect(simbolo('FCI:BALANZ')).toBe('BALANZ')
    expect(simbolo('BTC-USD')).toBe('BTC')
  })
})

describe('la frase de la fila y la confirmación dicen lo mismo', () => {
  it('precio objetivo', () => {
    expect(frase(precio)).toEqual({ quien: 'GGAL', que: 'sube a $ 8.000' })
    expect(confirmacion(precio)).toBe('Te avisamos cuando GGAL suba a $ 8.000.')
    expect(frase({ ...precio, direction: 'below' }).que).toBe('baja a $ 8.000')
  })

  it('toda la cartera, con los dos lados', () => {
    expect(frase(cartera)).toEqual({ quien: 'Mi cartera', que: 'algo sube 8 % o cae 5 % en el día' })
    expect(confirmacion(cartera)).toBe('Te avisamos si algo de tu cartera sube más de 8 % o cae más de 5 % en el día.')
  })

  it('un activo desde que se armó, con un solo lado', () => {
    const a = { ...cartera, scope: 'ticker', symbol: 'MELI', up_pct: null, down_pct: 10, baseline: 'set_price' }
    expect(frase(a)).toEqual({ quien: 'MELI', que: 'cae 10 % desde que la armé' })
    expect(confirmacion(a)).toBe('Te avisamos si MELI cae más de 10 % desde el precio de ahora.')
  })

  it('sin datos suficientes la confirmación no inventa una frase', () => {
    expect(confirmacion({ ...precio, threshold: NaN })).toBe(null)
    expect(confirmacion({ ...cartera, up_pct: NaN, down_pct: NaN })).toBe(null)
  })
})

describe('la línea de estado', () => {
  it('cuánto le falta a un precio objetivo', () => {
    expect(estado(precio, 7350).texto).toBe('Está en $ 7.350 · le falta 8,8 %')
    expect(estado({ ...precio, direction: 'below', threshold: 210, currency: 'USD', symbol: 'AAPL' }, 231.8).texto)
      .toBe('Está en US$ 231,80 · le falta 9,4 %')
  })

  it('pausada y cumplida', () => {
    expect(estado({ ...precio, active: false }, 7350).texto).toBe('Pausada')
    expect(estado({ ...precio, active: false, last_fired_at: '2026-10-14T18:47:00' }, 7350).texto).toBe('Cumplida el 14/10')
  })

  it('el aviso de hoy de toda la cartera', () => {
    const ev = [{ alert_id: 2, fired_at: '2026-10-19T14:32:00', message: 'GGAL cayó 5,2% hoy' }]
    expect(estado(cartera, null, ev, '2026-10-19').texto).toBe('Hoy avisó: GGAL cayó 5,2% hoy')
    // El de ayer no es «hoy».
    expect(estado(cartera, null, ev, '2026-10-20').texto).toBe('Mira tus activos cada día')
  })

  it('cuánto va un % medido desde que se armó', () => {
    const a = { ...cartera, scope: 'ticker', symbol: 'MELI', baseline: 'set_price', anchor_price: 2140 }
    expect(estado(a, 2073.66).texto).toBe('Va −3,1 % desde que la armaste')
  })
})

describe('el servidor sella en UTC sin «Z»', () => {
  it('un aviso de las 22:30 de Argentina es de ese día, no del siguiente', () => {
    // 01:30 UTC del 20 = 22:30 del 19 en Argentina.
    expect(diaArgentina('2026-10-20T01:30:00')).toBe('2026-10-19')
    expect(fechaCorta('2026-10-20T01:30:00.123456')).toBe('19/10')
  })
})
