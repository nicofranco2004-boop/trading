// Cómo se dice una alerta: la frase de la fila, la confirmación del formulario
// y la línea de estado. Son las tres caras de la misma alerta y tienen que
// decir lo mismo.
import { describe, it, expect } from 'vitest'
import { frase, confirmacion, estado, fmtPrecio, fmtPct, diaArgentina, fechaCorta, simbolo, activoTecnico, dondeEstaLaLinea, alertaDeLinea } from './alertasTexto'
import { setBrokersRegistry } from '../../utils/valuation'

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
    expect(frase(cartera)).toEqual({ quien: 'Mi cartera', que: 'algo sube 8 % o cae 5 % en el día', sep: ': ' })
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

describe('alertas técnicas', () => {
  const tec = { id: 9, kind: 'tecnica', scope: 'ticker', symbol: 'AAPL', senal: 'media200', direction: 'below', currency: 'USD', accion_local: 0, active: true, repeat: 'always' }

  it('el cruce de un promedio, con su lado', () => {
    expect(frase(tec)).toEqual({ quien: 'AAPL', que: 'queda abajo de su promedio de 200 días' })
    expect(confirmacion(tec)).toBe('Te avisamos cuando AAPL quede abajo de su promedio de 200 días. Lo miramos cada día con el precio de cierre.')
    expect(frase({ ...tec, direction: 'above' }).que).toBe('pasa para arriba su promedio de 200 días')
    expect(frase({ ...tec, senal: 'media50', direction: 'either' }).que).toBe('cruza su promedio de 50 días')
  })

  it('el RSI se dice como fuerza, y el máximo del año', () => {
    expect(frase({ ...tec, senal: 'rsi_bajo_30' })).toEqual({ quien: 'AAPL', que: 'la fuerza (RSI) baja de 30', sep: ': ' })
    expect(confirmacion({ ...tec, senal: 'rsi_sube_30' })).toBe('Te avisamos cuando la fuerza (RSI) de AAPL vuelva a pasar 30. Lo miramos cada día con el precio de cierre.')
    expect(frase({ ...tec, senal: 'maximo_12m' }).que).toBe('cierra en su máximo del año')
    expect(frase({ ...tec, senal: 'rsi_baja_70' }).que).toBe('la fuerza (RSI) vuelve a bajar de 70')
  })

  it('en pesos lo dice; una acción argentina en dólares también', () => {
    expect(frase({ ...tec, currency: 'ARS' }).quien).toBe('AAPL en pesos')
    expect(frase({ ...tec, symbol: 'GGAL', accion_local: 1, currency: 'ARS' }).quien).toBe('GGAL')
    expect(frase({ ...tec, symbol: 'GGAL', accion_local: 1 }).quien).toBe('GGAL en dólares')
  })

  it('el estado no habla de precio: se mira con el cierre', () => {
    expect(estado(tec, null, [], '2026-10-22').texto).toBe('Se mira cada día con el precio de cierre')
    const ev = [{ alert_id: 9, fired_at: '2026-10-22 12:05:00', message: 'AAPL quedó abajo de su promedio de 200 días: la tendencia de fondo se volvió bajista' }]
    expect(estado(tec, null, ev, '2026-10-22')).toEqual({ texto: `Hoy avisó: ${ev[0].message}`, tono: 'aviso' })
  })

  it('del buscador: la misma regla que la ficha (por tus lotes)', () => {
    setBrokersRegistry([{ name: 'IOL', currency: 'ARS' }, { name: 'Schwab', currency: 'USD' }])
    const enIol = [{ asset: 'GGAL', broker: 'IOL', asset_type: 'ACCION', quantity: 10 }]
    const enSchwab = [{ asset: 'GGAL', broker: 'Schwab', asset_type: 'STOCK', quantity: 10 }]
    // GGAL en IOL: la acción de BYMA (÷ MEP), como la ficha.
    expect(activoTecnico('GGAL', enIol)).toEqual({ symbol: 'GGAL', accion_local: true })
    expect(activoTecnico('GGAL.BA', enIol)).toEqual({ symbol: 'GGAL', accion_local: true })
    // El ADR en Schwab: la ficha muestra el ADR, la alerta también.
    expect(activoTecnico('GGAL', enSchwab)).toEqual({ symbol: 'GGAL', accion_local: false })
    // Sin lotes, la ficha decide por el ticker (AssetDetail → miradaSinTenencia):
    // GGAL que no tenés se mira en BYMA. Esta prueba esperaba el ADR, de cuando
    // la ficha lo mostraba; la ficha cambió y la alerta no (auditoría 29/10).
    expect(activoTecnico('GGAL.BA')).toEqual({ symbol: 'GGAL', accion_local: true })
    expect(activoTecnico('NVDA')).toEqual({ symbol: 'NVDA', accion_local: false })
    // Un CEDEAR va pelado (se mira la acción de afuera) aunque esté en IOL.
    expect(activoTecnico('AAPL.BA', [{ asset: 'AAPL', broker: 'IOL', asset_type: 'CEDEAR', quantity: 1 }]))
      .toEqual({ symbol: 'AAPL', accion_local: false })
    expect(activoTecnico('BTC')).toEqual({ symbol: 'BTC', accion_local: false })
  })
})

describe('el aviso de tu línea del gráfico (Nico, 28/10)', () => {
  const guardada = (tipo) => ({ kind: 'tecnica', senal: 'linea', symbol: 'AAPL', currency: 'USD', direction: 'either',
    dibujo: JSON.stringify({ asset: 'AAPL', moneda: 'usd', id: 'd1', tipo }) })
  it('en Mis alertas dice qué línea; en pesos, que es en pesos', () => {
    expect(frase(guardada('horizontal'))).toEqual({ quien: 'AAPL', que: 'toca tu línea horizontal' })
    expect(frase(guardada('tendencia')).que).toBe('toca tu línea de tendencia')
    expect(frase({ ...guardada('horizontal'), currency: 'ARS' }).quien).toBe('AAPL en pesos')
  })
  it('la confirmación del formulario, con el borrador (aún sin guardar)', () => {
    expect(confirmacion({ kind: 'tecnica', senal: 'linea', symbol: 'AAPL', currency: 'USD', tipoLinea: 'tendencia' }))
      .toBe('Te avisamos cuando AAPL toque tu línea de tendencia. Lo miramos cada día con el precio más alto y el más bajo del día.')
  })
})

describe('el aviso de tu canal (Nico, 29/10)', () => {
  const canal = (extra = {}, modo) => ({ id: 5, kind: 'tecnica', senal: 'linea', symbol: 'AAPL', currency: 'USD', direction: 'either', active: true,
    dibujo: JSON.stringify({ asset: 'AAPL', moneda: 'usd', id: 'c1', tipo: 'canal', ...(modo ? { modo } : {}) }), ...extra })
  it('la fila dice por qué borde y cuándo cuenta', () => {
    expect(frase(canal())).toEqual({ quien: 'AAPL', que: 'sale de tu canal, por cualquier borde' })
    expect(frase(canal({ direction: 'above' })).que).toBe('sale de tu canal, por arriba')
    expect(frase(canal({ direction: 'below' }, 'cierre')).que).toBe('cierra afuera de tu canal, por abajo')
  })
  it('la confirmación, con el borrador del formulario', () => {
    const b = { kind: 'tecnica', senal: 'linea', symbol: 'AAPL', currency: 'USD', tipoLinea: 'canal', direction: 'above', modo: 'toque' }
    expect(confirmacion(b)).toMatch(/^Te avisamos cuando AAPL toque o pase el borde de arriba de tu canal\. /)
    expect(confirmacion(b)).toContain('si lo tocó, te llega a la mañana siguiente.')
    expect(confirmacion({ ...b, modo: 'cierre', direction: 'either' })).toMatch(/^Te avisamos cuando AAPL cierre afuera de tu canal\. .*precio de cierre/)
  })
  it('el estado: adentro y a cuánto del borde; ya afuera; o que borraste la línea', () => {
    const r = { tipo: 'canal', ultimo: 187.6, hoy: [182.23, 193.75] }
    expect(estado(canal(), null, [], '', r).texto).toBe('Está en US$ 187,60 · adentro, a 2,9 % del borde de abajo')
    expect(estado(canal({ direction: 'above' }), null, [], '', r).texto).toBe('Está en US$ 187,60 · adentro, a 3,3 % del borde de arriba')
    // Ya afuera: sólo dónde está (el aviso de la mañana puede estar por llegar).
    expect(estado(canal(), null, [], '', { ...r, ultimo: 195 }).texto).toBe('Está en US$ 195,00 · afuera del canal, por arriba')
    // Un borde de abajo en cero o menos no existe: se mide contra el de arriba.
    // (Más cerca del de abajo, en -1, que del de arriba: igual se mide contra el de arriba.)
    expect(estado(canal(), null, [], '', { tipo: 'canal', ultimo: 4, hoy: [-1, 20] }).texto).toBe('Está en US$ 4,00 · adentro, a 400 % del borde de arriba')
    const borrada = estado(canal({ active: false }), null, [], '', { borrada: true })
    expect(borrada).toMatchObject({ texto: 'Se apagó: borraste la línea del gráfico', borrada: true })
    expect(dondeEstaLaLinea(canal(), undefined)).toBeNull()
  })
  it('una línea: cuánto le falta; sin datos, con qué se mira (el más alto y el más bajo, no el cierre)', () => {
    const h = { ...canal(), dibujo: JSON.stringify({ asset: 'MELI', moneda: 'usd', id: 'h1', tipo: 'horizontal' }) }
    expect(estado(h, null, [], '', { tipo: 'horizontal', ultimo: 2140, hoy: [2050] }).texto).toBe('Está en US$ 2.140,00 · le falta 4,2 %')
    expect(estado(h, null, [], '').texto).toBe('Se mira cada día con el precio más alto y el más bajo')
    expect(estado(canal({}, 'cierre'), null, [], '').texto).toBe('Se mira cada día con el precio de cierre')
  })
  it('«ya te avisamos» reconoce el canal por su id, activo y moneda', () => {
    expect(alertaDeLinea([canal()], { asset: 'aapl', moneda: 'usd', dibujo: 'c1' })).not.toBeNull()
    expect(alertaDeLinea([canal()], { asset: 'AAPL', moneda: 'ars', dibujo: 'c1' })).toBeNull()
    expect(alertaDeLinea([canal({ active: false })], { asset: 'AAPL', moneda: 'usd', dibujo: 'c1' })).toBeNull()
  })
})
