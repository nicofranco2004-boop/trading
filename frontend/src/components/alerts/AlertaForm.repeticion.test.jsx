// «Cuántas veces» arranca en lo que sirve para lo que se vigila (21/10/2026).
//
// Antes todo arrancaba en «Una vez». En el servidor, una alerta de toda la
// cartera con «Una vez» se apaga con el primer activo que pasa el % y avisa
// sólo de ése aunque se muevan tres en el mismo momento: «avisame si algo de
// mi cartera se mueve 3 %» daba un aviso y nunca más, y como «cuántas veces»
// está plegado abajo («Por mail y celular · una vez · cambiar»), casi nadie lo
// cambiaba. Decisión de Nico: % de toda la cartera → «Todos los días»; precio
// y % de un activo → «Una vez». Las alertas que ya existen no cambian.
//
// No hay jsdom: los botones del formulario llaman a `alElegirTipo` y
// `alCambiarVigilancia` en una línea, y acá se recorren esas mismas funciones
// en el orden en que las toca una persona.
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../hooks/usePushNotifications', () => ({
  usePushNotifications: () => ({ supported: false, permission: 'default', subscribed: false, subscribe: vi.fn(), unsubscribe: vi.fn() }),
}))
vi.mock('../../utils/api', () => ({ api: { get: vi.fn(() => Promise.resolve({})) } }))

import AlertaForm, { borradorInicial, repeticionPorDefecto, alElegirTipo, alCambiarVigilancia } from './AlertaForm'

const nuevo = () => borradorInicial({ puedeMovimiento: true })

describe('el valor de arranque de «Cuántas veces»', () => {
  it('% de toda la cartera: todos los días; precio y % de un activo: una vez', () => {
    expect(repeticionPorDefecto('pct_move', 'holdings')).toBe('always')
    expect(repeticionPorDefecto('pct_move', 'ticker')).toBe('once')
    expect(repeticionPorDefecto('price_target', 'ticker')).toBe('once')
  })

  it('el formulario nuevo abre en el aviso de precio, una vez', () => {
    expect(nuevo()).toMatchObject({ kind: 'price_target', repeat: 'once' })
  })
})

describe('lo que toca una persona', () => {
  it('«Se mueve un %» sin activo → Toda mi cartera, todos los días', () => {
    const f = alElegirTipo(nuevo(), 'pct_move', false)
    expect(f).toMatchObject({ kind: 'pct_move', scope: 'holdings', repeat: 'always' })
  })

  it('después «Un activo» → una vez; y de vuelta a «Toda mi cartera» → todos los días', () => {
    const cartera = alElegirTipo(nuevo(), 'pct_move', false)
    const unActivo = alCambiarVigilancia(cartera, { scope: 'ticker' }, false)
    expect(unActivo.repeat).toBe('once')
    expect(alCambiarVigilancia(unActivo, { scope: 'holdings' }, false).repeat).toBe('always')
  })

  it('de vuelta a «Llega a un precio» → una vez', () => {
    const cartera = alElegirTipo(nuevo(), 'pct_move', false)
    expect(alElegirTipo(cartera, 'price_target', false)).toMatchObject({ kind: 'price_target', repeat: 'once' })
  })

  it('con un activo ya escrito, «Se mueve un %» sigue con ese activo, una vez', () => {
    const conActivo = { ...nuevo(), symbol: 'GGAL.BA' }
    expect(alElegirTipo(conActivo, 'pct_move', false)).toMatchObject({ scope: 'ticker', repeat: 'once' })
  })

  it('si eligió «Una vez» a mano, cambiar lo que vigila no se lo pisa', () => {
    const elegida = { ...nuevo(), repeat: 'once' }
    expect(alElegirTipo(elegida, 'pct_move', true)).toMatchObject({ scope: 'holdings', repeat: 'once' })
    const todosLosDias = { ...alElegirTipo(nuevo(), 'pct_move', false), repeat: 'always' }
    expect(alCambiarVigilancia(todosLosDias, { scope: 'ticker' }, true).repeat).toBe('always')
  })

  it('«Crear alerta −10 %» de Mervall-E (un activo) sigue en una vez', () => {
    expect(borradorInicial({ prefill: { symbol: 'BTC', downPct: 10 }, puedeMovimiento: true }))
      .toMatchObject({ kind: 'pct_move', scope: 'ticker', repeat: 'once' })
  })
})

describe('las alertas que ya existen no cambian', () => {
  const vieja = {
    id: 9, kind: 'pct_move', scope: 'holdings', symbol: null, up_pct: 3, down_pct: 3,
    baseline: 'prev_close', channel: 'both', repeat: 'once', active: true,
  }
  const plan = { can: () => true, limit: () => null }

  it('editar una de toda la cartera con «Una vez» la deja en una vez', () => {
    expect(borradorInicial({ alerta: vieja }).repeat).toBe('once')
    const h = renderToStaticMarkup(<MemoryRouter><AlertaForm plan={plan} alerta={vieja} onClose={() => {}} /></MemoryRouter>)
    expect(h).toContain('Toda mi cartera')
    expect(h).toMatch(/· una vez ·/)
  })
})
