// Un aviso de GGAL mira la acción de la Bolsa de Buenos Aires, en pesos, no el
// ADR de Nueva York (22/10/2026).
//
// El buscador ofrecía «Grupo Financiero Galicia · BCBA» con el código pelado
// ('GGAL') y el formulario lo mandaba así: el servidor lo vigilaba como el ADR
// en dólares (US$ ~40, 10 acciones por ADR) y «avisame si llega a $ 8.000» no
// saltaba nunca. Lo mismo al escribir GGAL sin elegir la fila, o con el botón
// de Mervall-E (?new=GGAL&down=10).
//
// No hay jsdom: el formulario llama a `alElegirActivo` (buscador) y a
// `activoDelBorrador` (lo que se pide y lo que se manda) en una línea, y acá se
// recorren esas mismas funciones en el orden en que las toca una persona.
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../hooks/usePushNotifications', () => ({
  usePushNotifications: () => ({ supported: false, permission: 'default', subscribed: false, subscribe: vi.fn(), unsubscribe: vi.fn() }),
}))
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => Promise.resolve({})) } }))

import AlertaForm, { borradorInicial, alElegirActivo, activoDelBorrador, filasDelBuscador } from './AlertaForm'
import { simboloDelAviso, monedasPosibles } from './alertasTexto'
import { linkDeAlerta } from './alertaDePosicion'

const nuevo = () => borradorInicial({ puedeMovimiento: true })
// Lo que se manda al servidor (enviar → pedido): el activo y la moneda del precio.
const pedido = (f, editando = false) => {
  const symbol = activoDelBorrador(f, editando)
  const monedas = monedasPosibles(symbol, new Map())
  return { symbol, currency: editando || monedas.includes(f.currency) ? f.currency : monedas[0] }
}

describe('una acción argentina se vigila en pesos, en la Bolsa', () => {
  it('elegir «Grupo Financiero Galicia» en el buscador → GGAL.BA en pesos', () => {
    const fila = filasDelBuscador('GGAL').find(f => f.name === 'Grupo Financiero Galicia')
    expect(fila).toBeTruthy()
    const f = alElegirActivo(nuevo(), fila.symbol, fila.ccy)
    expect(pedido(f)).toEqual({ symbol: 'GGAL.BA', currency: 'ARS' })
  })

  it('escribir GGAL sin elegir la fila → lo mismo', () => {
    let f = nuevo()
    for (const v of ['G', 'GG', 'GGA', 'GGAL']) f = alElegirActivo(f, v)
    expect(pedido(f)).toEqual({ symbol: 'GGAL.BA', currency: 'ARS' })
  })

  it('el botón de Mervall-E (?new=GGAL&down=10, sin moneda) → GGAL.BA', () => {
    const f = borradorInicial({ prefill: { symbol: 'GGAL', downPct: 10 }, puedeMovimiento: true })
    expect(pedido(f).symbol).toBe('GGAL.BA')
  })

  it('YPFD, BMA y PAMP también', () => {
    for (const s of ['YPFD', 'BMA', 'PAMP']) expect(simboloDelAviso(s)).toBe(`${s}.BA`)
  })
})

describe('lo que NO cambia', () => {
  it('el ADR de un broker de afuera: la posición abre con ccy=USD y se respeta', () => {
    const link = linkDeAlerta({ asset: 'GGAL', asset_type: 'STOCK', broker: 'Schwab', currency: 'USD' })
    const q = new URLSearchParams(link.split('?')[1])
    expect(q.get('new')).toBe('GGAL')
    expect(q.get('ccy')).toBe('USD')
    const f = borradorInicial({ prefill: { symbol: q.get('new'), currency: q.get('ccy') }, puedeMovimiento: true })
    expect(pedido(f)).toEqual({ symbol: 'GGAL', currency: 'USD' })
  })

  it('…pero si después busca otro activo, la moneda del link ya no vale', () => {
    const f0 = borradorInicial({ prefill: { symbol: 'GGAL', currency: 'USD' }, puedeMovimiento: true })
    const f = alElegirActivo(alElegirActivo(f0, 'BM'), 'BMA')
    expect(pedido(f)).toEqual({ symbol: 'BMA.BA', currency: 'ARS' })
  })

  it('acciones de EE.UU., CEDEARs, cripto y fondos quedan como estaban', () => {
    expect(simboloDelAviso('AAPL')).toBe('AAPL')
    expect(simboloDelAviso('AAPL.BA')).toBe('AAPL.BA')
    expect(simboloDelAviso('MELI')).toBe('MELI')
    expect(simboloDelAviso('BTC')).toBe('BTC')
    expect(simboloDelAviso('FCI:BALANZ AHORRO')).toBe('FCI:BALANZ AHORRO')
    expect(simboloDelAviso('ggal.ba')).toBe('GGAL.BA')
  })

  it('una alerta que se edita no cambia de activo (el servidor no lo permite)', () => {
    const alerta = { id: 3, kind: 'price_target', scope: 'ticker', symbol: 'GGAL', currency: 'USD',
      direction: 'above', threshold: 50, channel: 'both', repeat: 'once', active: true }
    expect(pedido(borradorInicial({ alerta }), true)).toEqual({ symbol: 'GGAL', currency: 'USD' })
  })
})

describe('lo que ve la persona', () => {
  it('con GGAL del botón de Mervall-E, el formulario arranca en pesos y muestra lo escrito', () => {
    const f = borradorInicial({ prefill: { symbol: 'GGAL' }, puedeMovimiento: true })
    expect(f.currency).toBe('ARS')
    const h = renderToStaticMarkup(
      <MemoryRouter><AlertaForm plan={{ can: () => true, limit: () => null }} onClose={() => {}} prefill={{ symbol: 'GGAL' }} /></MemoryRouter>)
    expect(h).toContain('value="GGAL"')   // el campo muestra lo que escribió
  })
})
