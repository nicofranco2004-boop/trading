// El «Avisame» de la ficha técnica: lo que arma y lo que manda. Va por las
// mismas funciones que los botones (sin jsdom, como las otras pruebas del
// formulario): la señal de cada tarjeta → el borrador del formulario → el
// pedido al servidor (main._crear_alerta_tecnica).
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../hooks/usePushNotifications', () => ({
  usePushNotifications: () => ({ supported: false, permission: 'default', subscribed: false, subscribe: vi.fn(), unsubscribe: vi.fn() }),
}))
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => Promise.resolve({})) } }))

import AlertaForm, { borradorInicial, pedidoTecnico, repeticionPorDefecto } from './AlertaForm'
import { prefillTecnico, alertaExistente, senalDeTarjeta } from './AvisameTecnico'
import { setBrokersRegistry } from '../../utils/valuation'

const plan = { can: () => true, limit: () => null }
const html = (props) => renderToStaticMarkup(
  <MemoryRouter><AlertaForm plan={plan} onClose={() => {}} {...props} /></MemoryRouter>)

describe('la señal de cada tarjeta', () => {
  it('arriba del promedio ofrece avisar cuando quede abajo, y al revés', () => {
    expect(senalDeTarjeta('fondo', { dist_media200: 4.2 })).toEqual({ senal: 'media200', direction: 'below' })
    expect(senalDeTarjeta('fondo', { dist_media200: -1 })).toEqual({ senal: 'media200', direction: 'above' })
    expect(senalDeTarjeta('corto', { dist_media50: 2 })).toEqual({ senal: 'media50', direction: 'below' })
    expect(senalDeTarjeta('fondo', {})).toEqual({ senal: 'media200', direction: 'either' })
  })

  it('el RSI: castigado → que vuelva a pasar 30; con fuerza → que pase 70', () => {
    expect(senalDeTarjeta('rsi', { rsi: 24 }).senal).toBe('rsi_sube_30')
    expect(senalDeTarjeta('rsi', { rsi: 62 }).senal).toBe('rsi_sobre_70')
    expect(senalDeTarjeta('rsi', { rsi: 41 }).senal).toBe('rsi_bajo_30')
    // Ya arriba de 70, «que pase 70» no puede pasar pronto: que vuelva a bajar.
    expect(senalDeTarjeta('rsi', { rsi: 76 }).senal).toBe('rsi_baja_70')
    expect(senalDeTarjeta('maximo', {}).senal).toBe('maximo_12m')
    expect(senalDeTarjeta('tuyo', {})).toBeNull()
  })
})

describe('de la ficha al servidor', () => {
  it('un CEDEAR mirado en dólares', () => {
    const p = prefillTecnico({ asset: 'aapl', moneda: 'usd', senal: 'media200', direction: 'below' })
    const f = borradorInicial({ prefill: p })
    expect(f.repeat).toBe(repeticionPorDefecto('tecnica', 'ticker'))
    expect(pedidoTecnico(f, true)).toEqual({
      kind: 'tecnica', scope: 'ticker', symbol: 'AAPL', senal: 'media200', direction: 'below',
      currency: 'USD', accion_local: false, channel: 'both', repeat: 'always',
    })
  })

  it('una acción argentina mirada en pesos, y el RSI sin lado', () => {
    const p = prefillTecnico({ asset: 'GGAL', accionLocal: true, moneda: 'ars', senal: 'rsi_bajo_30', direction: 'below' })
    expect(pedidoTecnico(borradorInicial({ prefill: p }), true)).toMatchObject({
      symbol: 'GGAL', accion_local: true, currency: 'ARS', senal: 'rsi_bajo_30', direction: 'either',
    })
  })

  it('desde el buscador de Alertas, GGAL es la acción argentina si la tenés en BYMA (como la ficha)', () => {
    setBrokersRegistry([{ name: 'IOL', currency: 'ARS' }])
    const f = { ...borradorInicial({ prefill: { kind: 'tecnica' } }), symbol: 'GGAL' }
    const lotes = [{ asset: 'GGAL', broker: 'IOL', asset_type: 'ACCION', quantity: 10 }]
    expect(pedidoTecnico(f, false, lotes)).toMatchObject({ symbol: 'GGAL', accion_local: true, currency: 'USD' })
    expect(pedidoTecnico(f, false, [])).toMatchObject({ symbol: 'GGAL', accion_local: false })
  })

  it('el formulario desde la ficha: sin selector de tipo, con el activo fijo y la frase', () => {
    const h = html({ prefill: prefillTecnico({ asset: 'AAPL', senal: 'media200', direction: 'below' }) })
    expect(h).toContain('Nuevo aviso técnico')
    expect(h).not.toContain('Se mueve un %')
    expect(h).toContain('Te avisamos cuando AAPL quede abajo de su promedio de 200 días.')
    expect(h).toContain('Para qué lado')
  })

  it('el formulario desde Alertas ofrece los tres tipos', () => {
    const h = html({ prefill: { kind: 'tecnica' } })
    expect(h).toContain('Señal técnica')
    expect(h).toContain('Se mueve un %')
    expect(h).toContain('La fuerza (RSI) baje de 30')
  })
})

describe('«Te avisamos» si ya hay una igual', () => {
  const p = prefillTecnico({ asset: 'AAPL', senal: 'media200', direction: 'below' })
  const a = { kind: 'tecnica', active: true, symbol: 'AAPL', senal: 'media200', currency: 'USD', accion_local: 0, direction: 'either' }
  it('misma señal, activo y moneda; «los dos lados» cubre cualquiera', () => {
    expect(alertaExistente([a], p)).toBe(a)
    expect(alertaExistente([{ ...a, direction: 'below' }], p)).not.toBeNull()
  })
  it('una de «para arriba» no avisa cuando queda abajo', () => {
    expect(alertaExistente([{ ...a, direction: 'above' }], p)).toBeNull()
  })
  it('pausada, en pesos u otra señal: no cuenta', () => {
    expect(alertaExistente([{ ...a, active: false }], p)).toBeNull()
    expect(alertaExistente([{ ...a, currency: 'ARS' }], p)).toBeNull()
    expect(alertaExistente([{ ...a, senal: 'media50' }], p)).toBeNull()
  })
})
