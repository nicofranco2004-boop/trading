import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { preciosQueCambiaron, haceDesde, textoPreciosEnVivo } from './preciosEnVivo'
import PreciosEnVivo from '../components/PreciosEnVivo'

// El punto del cartel de precios late SÓLO si el último refresco movió algo.
describe('preciosQueCambiaron', () => {
  it('cuenta los símbolos cuyo precio cambió', () => {
    expect(preciosQueCambiaron({ NVDA: 181.2, AAPL: 228.4 }, { NVDA: 181.9, AAPL: 228.4 })).toBe(1)
  })
  it('mercado cerrado: el refresco trae lo mismo → 0 (el punto queda quieto)', () => {
    expect(preciosQueCambiaron({ NVDA: 181.2 }, { NVDA: 181.2 })).toBe(0)
  })
  it('la primera carga no tiene contra qué comparar → 0', () => {
    expect(preciosQueCambiaron(null, { NVDA: 181.2 })).toBe(0)
  })
  it('__meta es la procedencia, no un precio', () => {
    expect(preciosQueCambiaron({ __meta: { a: 1 } }, { __meta: { a: 2 } })).toBe(0)
  })
  it('un símbolo nuevo (cargaste un activo) no es "el mercado se movió"', () => {
    expect(preciosQueCambiaron({ NVDA: 1 }, { NVDA: 1, MELI: 2000 })).toBe(0)
  })
  it('un precio que no llegó (null) no cuenta como cambio', () => {
    expect(preciosQueCambiaron({ NVDA: 1 }, { NVDA: null })).toBe(0)
  })
})

describe('haceDesde', () => {
  const ahora = 1_000_000_000
  it('segundos por debajo del minuto', () => {
    expect(haceDesde(new Date(ahora - 40_000), ahora)).toBe('hace 40 s')
  })
  it('minutos y horas', () => {
    expect(haceDesde(new Date(ahora - 3 * 60_000), ahora)).toBe('hace 3 min')
    expect(haceDesde(new Date(ahora - 2 * 3600_000), ahora)).toBe('hace 2 h')
  })
  it('sin hora no inventa nada', () => {
    expect(haceDesde(null, ahora)).toBe('')
  })
})

describe('textoPreciosEnVivo', () => {
  const ahora = 1_000_000_000
  const actualizado = new Date(ahora - 40_000)
  it('Cartera (los vuelve a pedir sola) lo promete', () => {
    expect(textoPreciosEnVivo({ actualizado, seActualizanSolos: true }, ahora)).toBe('Precios de hace 40 s · se actualizan solos')
  })
  it('el Dashboard (los pide una vez) NO lo promete', () => {
    expect(textoPreciosEnVivo({ actualizado }, ahora)).toBe('Precios de hace 40 s')
  })
  it('antes de la primera respuesta dice que está buscando', () => {
    expect(textoPreciosEnVivo({ actualizado: null, actualizando: true }, ahora)).toBe('Buscando precios…')
  })
})

describe('<PreciosEnVivo>', () => {
  const html = (props) => renderToStaticMarkup(createElement(PreciosEnVivo, { actualizado: new Date(), ...props }))
  it('con precios que se movieron, el punto late (live-dot)', () => {
    expect(html({ seMueven: true })).toContain('live-dot')
  })
  it('con precios quietos, el punto NO late', () => {
    expect(html({ seMueven: false })).not.toContain('live-dot')
  })
  it('sin hora ni carga en curso no dibuja nada', () => {
    expect(renderToStaticMarkup(createElement(PreciosEnVivo, { actualizado: null }))).toBe('')
  })
})

import { proximoTic, hayPrecios as _hp } from './preciosEnVivo'
describe('proximoTic', () => {
  const ahora = 1_000_000_000
  it('cada segundo mientras dice segundos', () => {
    expect(proximoTic(new Date(ahora - 30_000), ahora)).toBe(1000)
  })
  it('cada 15 s cuando ya dice minutos (redibujar cada segundo no cambiaría nada)', () => {
    expect(proximoTic(new Date(ahora - 5 * 60_000), ahora)).toBe(15_000)
  })
  it('sin hora todavía, cada segundo', () => {
    expect(proximoTic(null, ahora)).toBe(1000)
    expect(_hp).toBeTypeOf('function')
  })
})
